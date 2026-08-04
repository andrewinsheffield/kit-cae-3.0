# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import asyncio

from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import frame_prims, get_test_data_path, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import Usd, UsdGeom

# Usage:
# Copy paste this script into the Script Editor (Developer > Script Editor) or execute it on launch w/
# ./repo.sh launch -n omni.cae.kit -- --exec scripts/example_npz_streamlines.py


async def main():
    # 0. Import the NPZ file as CGNS
    npz_path = get_test_data_path("disk_out_ref.npz")
    await import_to_stage(npz_path, "/World/disk_out_ref_npz", schema="CGNS")

    ctx = get_context()
    stage: Usd.Stage = ctx.get_stage()

    # Create CAE anchor
    UsdGeom.Xform.Define(stage, "/World/CAE")

    # 1. Generate the streamlines and the seed sphere
    dataset_path: str = "/World/disk_out_ref_npz/Base/Zone/Section"
    viz_path = "/World/CAE/Streamlines_NumPyDataSet"
    sphere_path: str = "/World/CAE/Sphere"
    sphere_scale = 0.2

    await execute_command("CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type="standard")
    await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=sphere_path)
    await execute_command("TransformPrimSRT", path=sphere_path, new_scale=[sphere_scale, sphere_scale, sphere_scale])
    await wait_for_update()

    # 3. Get prims and set up streamlines
    viz_prim: Usd.Prim = stage.GetPrimAtPath(viz_path)
    sphere_prim: Usd.Prim = stage.GetPrimAtPath(sphere_path)

    # Set streamlines direction
    streamlines_api: cae_viz.StreamlinesAPI = cae_viz.StreamlinesAPI(viz_prim)
    streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.forward)
    streamlines_api.GetMaxStepsAttr().Set(48)

    # Set the seed target to the sphere prim
    ds_api: cae_viz.DatasetSelectionAPI = cae_viz.DatasetSelectionAPI(viz_prim, "seeds")
    ds_api.GetTargetRel().SetTargets({sphere_prim.GetPath()})

    # Set the velocity targets (V is a vector field with 3 components)
    vs_api = cae_viz.FieldSelectionAPI(viz_prim, "velocities")
    vs_api.CreateFieldNamesAttr().Set(["V"])

    # Set the color target
    colors_api = cae_viz.FieldSelectionAPI(viz_prim, "colors")
    colors_api.CreateFieldNamesAttr().Set(["Temp"])
    await wait_for_update()

    # Create a Bounding Box
    bbox_path = "/World/CAE/BoundingBox_NumPyDataSet"
    await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path)
    await wait_for_update()

    # Frame the bounding box
    await frame_prims([bbox_path], zoom=1.0)

    # 4. Select the sphere
    ctx.get_selection().set_selected_prim_paths([sphere_path], True)


if __name__ == "__main__":
    asyncio.ensure_future(main())
