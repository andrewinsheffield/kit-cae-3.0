"""
Eval 04 Validator: Multi-Viz Composition
Runs inside Kit-CAE via --exec. Imports NPZ as an OmniSci CGNS dataset, creates
an irregular volume and glyphs, verifies bindings, and captures a screenshot.
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
from pxr import Gf, Usd, UsdGeom, UsdShade

RENDER_DIR = os.environ.get("KIT_CAE_EVAL_RENDER_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "renders"
)
os.makedirs(RENDER_DIR, exist_ok=True)
OUTPUT_PATH = os.path.join(RENDER_DIR, "eval_04_multi.png")


async def main():
    app = omni.kit.app.get_app()
    checks = []

    # 1. Import NPZ using its CGNS interpretation.
    try:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
        await import_to_stage(os.path.join(data_dir, "disk_out_ref.npz"), "/World/disk", schema="CGNS")
        await wait_for_update(20)
        checks.append({"name": "import_success", "pass": True, "detail": "Imported as CGNS"})
    except Exception as e:
        checks.append({"name": "import_success", "pass": False, "detail": str(e)})
        _emit_result("04_multi_viz", checks)
        _shutdown(app)
        return

    stage = get_context().get_stage()

    # 2. Validate the dataset and field instances authored by the plugin.
    dataset_path = "/World/disk/Base/Zone/Section"
    dataset_prim = stage.GetPrimAtPath(dataset_path)
    field_names = usd_utils.get_instances(dataset_prim, "OmniSciFieldAPI") if dataset_prim else []
    checks.append({"name": "fields_found", "pass": {"Temp", "V"}.issubset(field_names), "detail": str(field_names)})

    # 4. Create bounding box + volume + glyphs
    bbox_path = "/World/CAE/BoundingBox"
    vol_path = "/World/CAE/Volume"
    glyphs_path = "/World/CAE/Glyphs"

    try:
        await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path)

        # Create volume — bind field IMMEDIATELY before any wait
        await execute_command("CreateCaeVizVolume", dataset_path=dataset_path, prim_path=vol_path, type="irregular")
        vol_prim = stage.GetPrimAtPath(vol_path)
        cae_viz.FieldSelectionAPI(vol_prim, "colors").CreateFieldNamesAttr().Set(["Temp"])

        # Create glyphs — bind fields IMMEDIATELY before any wait
        await execute_command("CreateCaeVizGlyphs", dataset_path=dataset_path, prim_path=glyphs_path, shape="Arrow")
        glyphs_prim = stage.GetPrimAtPath(glyphs_path)
        cae_viz.FieldSelectionAPI(glyphs_prim, "colors").CreateFieldNamesAttr().Set(["Temp"])
        cae_viz.FieldSelectionAPI(glyphs_prim, "orientations").CreateFieldNamesAttr().Set(["V"])
        # Reduce glyph size so the volume cloud is clearly visible through/around them
        cae_viz.GlyphsAPI(glyphs_prim).CreateScaleAttr().Set(0.3)

        # NOW let the controllers process everything with fields already bound
        await wait_for_update(120)

        # Compute field range for manual colormap setup
        attr = dataset_prim.GetAttribute("omni:sci:array:Temp:value")
        value = await asyncio.to_thread(attr.Get, Usd.TimeCode.EarliestTime())
        farray = np.asarray(value)
        ranges = array_utils.get_componentwise_ranges(farray)
        fmin, fmax = (0.0, 1.0)
        if ranges:
            fmin, fmax = float(ranges[0][0]), float(ranges[0][1])

        # Set volume colormap domain if controller hasn't done it yet
        colormap_prim = stage.GetPrimAtPath(f"{vol_path}/Material/Colormap")
        if colormap_prim and colormap_prim.IsValid():
            cur_domain = colormap_prim.GetAttribute("domain").Get()
            if cur_domain and cur_domain[1] < cur_domain[0]:
                colormap_prim.GetAttribute("domain").Set(Gf.Vec2f(fmin, fmax))

        # Ensure glyphs coloring is enabled (fallback if controller hasn't processed)
        shader_path = f"{glyphs_path}/Materials/ScalarColor/Shader"
        shader = UsdShade.Shader(stage.GetPrimAtPath(shader_path))
        if shader.GetPrim().IsValid():
            ec = shader.GetInput("enable_coloring")
            dm = shader.GetInput("domain")
            if ec and not ec.Get():
                ec.Set(True)
            if dm:
                dval = dm.Get()
                if dval and dval[1] < dval[0]:
                    dm.Set(Gf.Vec2f(fmin, fmax))

        await wait_for_update(30)
        checks.append({"name": "viz_created", "pass": True, "detail": "Volume + Glyphs"})
    except Exception as e:
        checks.append({"name": "viz_created", "pass": False, "detail": str(e)})

    # 5. Verify prims exist
    ds_prim = stage.GetPrimAtPath(dataset_path)
    checks.append({"name": "dataset_exists", "pass": bool(ds_prim and ds_prim.IsValid()), "detail": dataset_path})

    vol_prim = stage.GetPrimAtPath(vol_path)
    vol_ok = bool(vol_prim and vol_prim.IsValid())
    checks.append({"name": "volume_prim_exists", "pass": vol_ok, "detail": vol_path})

    glyphs_prim = stage.GetPrimAtPath(glyphs_path)
    glyphs_ok = bool(glyphs_prim and glyphs_prim.IsValid())
    checks.append({"name": "glyphs_prim_exists", "pass": glyphs_ok, "detail": glyphs_path})

    # 6. Verify volume field binding
    if vol_ok:
        names = cae_viz.FieldSelectionAPI(vol_prim, "colors").GetFieldNamesAttr().Get() or []
        checks.append({"name": "volume_color_bound", "pass": "Temp" in names, "detail": str(names)})

    # 7. Verify glyphs field bindings
    if glyphs_ok:
        color_names = cae_viz.FieldSelectionAPI(glyphs_prim, "colors").GetFieldNamesAttr().Get() or []
        orient_names = cae_viz.FieldSelectionAPI(glyphs_prim, "orientations").GetFieldNamesAttr().Get() or []
        color_ok = "Temp" in color_names
        orient_ok = "V" in orient_names
        checks.append({"name": "glyphs_color_bound", "pass": color_ok, "detail": str(color_names)})
        checks.append({"name": "glyphs_orient_bound", "pass": orient_ok, "detail": str(orient_names)})

    # 8. Capture screenshot
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

    _emit_result("04_multi_viz", checks)
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
