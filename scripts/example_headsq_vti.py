# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
from pxr import Sdf, Usd, UsdGeom

# Usage:
# Copy paste this script into the Script Editor (Developer > Script Editor) or execute it on launch w/
# ./repo.sh launch -n omni.cae.kit -- --exec scripts/example_headsq_vti.py


async def main():
    # 1. Import the VTI file through the native OpenUSD file-format plugin
    vti_path = get_test_data_path("headsq.vti")
    await import_to_stage(vti_path, "/World/headsq_vti")

    ctx = get_context()
    stage: Usd.Stage = ctx.get_stage()
    UsdGeom.Xform.Define(stage, "/World/CAE")

    dataset_path = "/World/headsq_vti"
    viz_path = "/World/CAE/NanoVdbIndeXVolume_VTKImageData"

    # 2. Create Bounding Box
    bbox_path = "/World/CAE/BoundingBox_VTKDataSet"
    await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path)
    await wait_for_update()

    # 2. Frame the bounding box
    bbox_prim = stage.GetPrimAtPath(bbox_path)
    await frame_prims([bbox_path], zoom=0.9)

    # 3. Create Bounding Box ROI
    bbox_path_roi = "/World/CAE/BoundingBox_VTKDataSet_ROI"
    await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path_roi)

    # 4. Set the bounding box ROI scale
    bbox_roi_prim = stage.GetPrimAtPath(bbox_path_roi)
    xformApi = UsdGeom.XformCommonAPI(bbox_roi_prim)
    xformApi.SetScale((0.5, 1.0, 1.0))

    # 5. Create Volume
    await execute_command("CreateCaeVizVolume", dataset_path=dataset_path, prim_path=viz_path, type="vdb")

    # 6. Specify the color field
    viz_prim = stage.GetPrimAtPath(viz_path)

    assert viz_prim.HasAPI(cae_viz.FieldSelectionAPI, "colors"), "Should have FieldSelectionAPI for colors"
    colors_fs_api = cae_viz.FieldSelectionAPI(viz_prim, "colors")
    colors_fs_api.CreateFieldNamesAttr().Set(["Scalars_"])

    # 7. Set the ROI
    assert viz_prim.HasAPI(cae_viz.DatasetVoxelizationAPI, "source"), "Should have DatasetVoxelizationAPI for source"
    vox_api = cae_viz.DatasetVoxelizationAPI(viz_prim, "source")
    vox_api.CreateRoiRel().SetTargets([bbox_path_roi])

    # 8. Let the stage update
    await wait_for_update()


if __name__ == "__main__":
    asyncio.ensure_future(main())
