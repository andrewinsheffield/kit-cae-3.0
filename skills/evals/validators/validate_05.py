"""
Eval 05 Validator: Streamlines
Runs inside Kit-CAE via --exec. Imports NPZ as an OmniSci CGNS dataset, creates
streamlines with a seed sphere, verifies field bindings, and captures a screenshot.
"""

import asyncio
import json
import os

import numpy as np
import omni.kit.app
import omni.usd
from omni.cae.core import array_utils
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
OUTPUT_PATH = os.path.join(RENDER_DIR, "eval_05_streamlines.png")


async def main():
    app = omni.kit.app.get_app()
    checks = []

    # 1. Import NPZ using its CGNS interpretation.
    try:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
        await import_to_stage(os.path.join(data_dir, "disk_out_ref.npz"), "/World/disk", schema="CGNS")
        await wait_for_update(20)
        checks.append({"name": "import_success", "pass": True, "detail": "Imported"})
    except Exception as e:
        checks.append({"name": "import_success", "pass": False, "detail": str(e)})
        _emit_result("05_streamlines", checks)
        _shutdown(app)
        return

    stage = get_context().get_stage()

    # 2. Create streamlines + seed.
    dataset_path = "/World/disk/Base/Zone/Section"
    dataset_prim = stage.GetPrimAtPath(dataset_path)
    bbox_path = "/World/CAE/BoundingBox"
    stream_path = "/World/CAE/Streamlines"
    seed_path = "/World/CAE/Seed"

    try:
        await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path)

        await execute_command(
            "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=stream_path, type="standard"
        )
        await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=seed_path)
        await execute_command("TransformPrimSRT", path=seed_path, new_scale=[0.2, 0.2, 0.2])

        # Bind fields IMMEDIATELY — before any wait
        stream_prim = stage.GetPrimAtPath(stream_path)
        cae_viz.StreamlinesAPI(stream_prim).GetDirectionAttr().Set(cae_viz.Tokens.forward)
        cae_viz.DatasetSelectionAPI(stream_prim, "seeds").GetTargetRel().SetTargets([seed_path])
        cae_viz.FieldSelectionAPI(stream_prim, "velocities").CreateFieldNamesAttr().Set(["V"])
        cae_viz.FieldSelectionAPI(stream_prim, "colors").CreateFieldNamesAttr().Set(["Temp"])

        # Wait for controller to process field bindings and auto-rescale
        await wait_for_update(120)

        # Ensure coloring is enabled (fallback if controller hasn't processed)
        shader_path = f"{stream_path}/Materials/ScalarColor/Shader"
        shader = UsdShade.Shader(stage.GetPrimAtPath(shader_path))
        if shader.GetPrim().IsValid():
            ec = shader.GetInput("enable_coloring")
            dm = shader.GetInput("domain")

            if ec and not ec.Get():
                ec.Set(True)
            if dm:
                dval = dm.Get()
                if dval and dval[1] < dval[0]:
                    attr = dataset_prim.GetAttribute("omni:sci:array:Temp:value")
                    value = await asyncio.to_thread(attr.Get, Usd.TimeCode.EarliestTime())
                    farray = np.asarray(value)
                    ranges = array_utils.get_componentwise_ranges(farray)
                    if ranges:
                        fmin, fmax = float(ranges[0][0]), float(ranges[0][1])
                        dm.Set(Gf.Vec2f(fmin, fmax))
                        ec.Set(True)

        await wait_for_update(30)
        checks.append({"name": "streamlines_created", "pass": True, "detail": stream_path})
    except Exception as e:
        checks.append({"name": "streamlines_created", "pass": False, "detail": str(e)})

    # 5. Verify streamlines prim
    stream_prim = stage.GetPrimAtPath(stream_path)
    prim_exists = bool(stream_prim and stream_prim.IsValid())
    checks.append({"name": "streamlines_prim_exists", "pass": prim_exists, "detail": stream_path})

    # 6. Verify seed prim
    seed_prim = stage.GetPrimAtPath(seed_path)
    seed_exists = bool(seed_prim and seed_prim.IsValid())
    checks.append({"name": "seed_prim_exists", "pass": seed_exists, "detail": seed_path})

    # 7. Verify velocity binding
    if prim_exists:
        vel_names = cae_viz.FieldSelectionAPI(stream_prim, "velocities").GetFieldNamesAttr().Get() or []
        vel_bound = "V" in vel_names
        checks.append({"name": "velocity_bound", "pass": vel_bound, "detail": str(vel_names)})

    # 8. Verify color binding
    if prim_exists:
        color_names = cae_viz.FieldSelectionAPI(stream_prim, "colors").GetFieldNamesAttr().Get() or []
        color_bound = "Temp" in color_names
        checks.append({"name": "color_bound", "pass": color_bound, "detail": str(color_names)})

    # 9. Verify seed binding
    if prim_exists:
        seed_targets = cae_viz.DatasetSelectionAPI(stream_prim, "seeds").GetTargetRel().GetTargets()
        seed_bound = len(seed_targets) > 0
        checks.append(
            {"name": "seed_bound", "pass": seed_bound, "detail": str(seed_targets[0]) if seed_targets else "No targets"}
        )

    # 10. Capture screenshot
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

    _emit_result("05_streamlines", checks)
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
