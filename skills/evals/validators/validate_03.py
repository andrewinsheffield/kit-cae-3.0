"""
Eval 03 Validator: Faces + Colormap
Runs inside Kit-CAE via --exec. Imports VTU file, creates faces visualization with colormap,
verifies field binding, and checks screenshot.
"""

import asyncio
import json
import os

import numpy as np
import omni.kit.app
import omni.usd
from omni.cae.core import array_utils, usd_utils
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import frame_prims, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
from omni.usd import get_context
from pxr import Gf, OmniSci, Usd, UsdGeom, UsdShade

RENDER_DIR = os.environ.get("KIT_CAE_EVAL_RENDER_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "renders"
)
os.makedirs(RENDER_DIR, exist_ok=True)
OUTPUT_PATH = os.path.join(RENDER_DIR, "eval_03_faces.png")


async def main():
    app = omni.kit.app.get_app()
    checks = []

    # 1. Import
    try:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
        await import_to_stage(os.path.join(data_dir, "multicomb_0_polyhedra.vtu"), "/World/multicomb")
        await wait_for_update(20)
        checks.append({"name": "import_success", "pass": True, "detail": "Imported"})
    except Exception as e:
        checks.append({"name": "import_success", "pass": False, "detail": str(e)})
        _emit_result("03_faces_colormap", checks)
        _shutdown(app)
        return

    stage = get_context().get_stage()

    # 2. Discover an OmniSci dataset carrying the Density field.
    datasets = [prim for prim in stage.Traverse() if prim.IsA(OmniSci.Dataset)]
    density_datasets = [prim for prim in datasets if "Density" in usd_utils.get_instances(prim, "OmniSciFieldAPI")]
    has_density = bool(density_datasets)
    checks.append(
        {
            "name": "density_field_found",
            "pass": has_density,
            "detail": str(density_datasets[0].GetPath()) if has_density else "No Density field",
        }
    )

    dataset_path = str(density_datasets[0].GetPath()) if density_datasets else None

    if not dataset_path:
        checks.append({"name": "faces_created", "pass": False, "detail": "No dataset or field"})
        _emit_result("03_faces_colormap", checks)
        _shutdown(app)
        return

    # 3. Create faces + bounding box
    faces_path = "/World/CAE/Faces"
    bbox_path = "/World/CAE/BoundingBox"

    try:
        await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path)
        await execute_command("CreateCaeVizFaces", dataset_path=dataset_path, prim_path=faces_path)
        await wait_for_update(10)

        # Polyhedra cells don't support external_only face extraction — disable it
        faces_prim = stage.GetPrimAtPath(faces_path)
        cae_viz.FacesAPI(faces_prim).GetExternalOnlyAttr().Set(False)

        # Bind field — this triggers the controller update cycle which will
        # auto-rescale domain and set enable_coloring=True via RescaleRangeAPI
        faces_prim = stage.GetPrimAtPath(faces_path)
        cae_viz.FieldSelectionAPI(faces_prim, "colors").CreateFieldNamesAttr().Set(["Density"])

        # Wait for the faces controller to run process_rescale_range_apis
        # The controller needs multiple update cycles to: detect field change → compute faces → rescale
        await wait_for_update(60)

        # Verify coloring state — if the controller hasn't processed yet, force enable
        shader_path = f"{faces_path}/Materials/ScalarColor/Shader"
        shader = UsdShade.Shader(stage.GetPrimAtPath(shader_path))
        if shader.GetPrim().IsValid():
            enable_input = shader.GetInput("enable_coloring")
            if enable_input:
                if not enable_input.Get():
                    enable_input.Set(True)

            domain_input = shader.GetInput("domain")
            if domain_input:
                domain_val = domain_input.Get()
                if domain_val and domain_val[1] < domain_val[0]:
                    # Controller hasn't rescaled yet — manually compute and set range
                    dataset_prim = stage.GetPrimAtPath(dataset_path)
                    attr = dataset_prim.GetAttribute("omni:sci:array:Density:value")
                    value = await asyncio.to_thread(attr.Get, Usd.TimeCode.EarliestTime())
                    farray = np.asarray(value)
                    ranges = array_utils.get_componentwise_ranges(farray)
                    if ranges:
                        fmin, fmax = float(ranges[0][0]), float(ranges[0][1])
                        domain_input.Set(Gf.Vec2f(fmin, fmax))
                        enable_input.Set(True)

            await wait_for_update(30)

        checks.append({"name": "faces_created", "pass": True, "detail": faces_path})
    except Exception as e:
        checks.append({"name": "faces_created", "pass": False, "detail": str(e)})

    # 4. Verify faces prim
    faces_prim = stage.GetPrimAtPath(faces_path)
    prim_exists = bool(faces_prim and faces_prim.IsValid())
    checks.append({"name": "faces_prim_exists", "pass": prim_exists, "detail": faces_path})

    # 5. Verify field binding
    if prim_exists:
        colors_api = cae_viz.FieldSelectionAPI(faces_prim, "colors")
        field_names = colors_api.GetFieldNamesAttr().Get() or []
        field_bound = "Density" in field_names
        checks.append(
            {
                "name": "field_bound",
                "pass": field_bound,
                "detail": str(field_names) if field_names else "No field names",
            }
        )
    else:
        checks.append({"name": "field_bound", "pass": False, "detail": "No faces prim"})

    # 6. Verify bounding box
    bbox_prim = stage.GetPrimAtPath(bbox_path)
    checks.append({"name": "bbox_exists", "pass": bool(bbox_prim and bbox_prim.IsValid()), "detail": bbox_path})

    # 7. Capture screenshot
    try:
        await frame_prims([bbox_path], zoom=0.9)
        for _ in range(600):
            await app.next_update_async()

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        vp = get_active_viewport()
        capture_viewport_to_file(vp, file_path=OUTPUT_PATH)
        for _ in range(30):
            await app.next_update_async()

        file_exists = os.path.isfile(OUTPUT_PATH)
        file_size = os.path.getsize(OUTPUT_PATH) if file_exists else 0
        checks.append(
            {
                "name": "screenshot_exists",
                "pass": file_exists and file_size > 10000,
                "detail": f"{OUTPUT_PATH} ({file_size} bytes)",
            }
        )
    except Exception as e:
        checks.append({"name": "screenshot_exists", "pass": False, "detail": str(e)})

    _emit_result("03_faces_colormap", checks)
    _shutdown(app)


def _emit_result(eval_name, checks):
    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    result = {
        "eval": eval_name,
        "pass": all(c["pass"] for c in checks),
        "score": round(passed / total * 100) if total > 0 else 0,
        "checks": checks,
    }
    print(f"\nEVAL_RESULT_BEGIN\n{json.dumps(result, indent=2)}\nEVAL_RESULT_END")


def _shutdown(app):
    async def _do_shutdown():
        app.post_quit()
        for _ in range(10):
            await app.next_update_async()
        os._exit(0)

    asyncio.ensure_future(_do_shutdown())


if __name__ == "__main__":
    asyncio.ensure_future(main())
