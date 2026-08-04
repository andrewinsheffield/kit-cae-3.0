# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

import asyncio

from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import frame_prims, get_test_data_path, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import UsdGeom

# Usage:
# Copy/paste this script into Developer > Script Editor, or execute it on launch:
# ./repo.sh launch -n omni.cae.kit -- --exec ./scripts/example_planar_slice.py

DATASET_PATH = "/World/StaticMixer/Base/StaticMixer/B1_P3"
SLICE_PATH = "/World/CAE/PlanarSlice_B1_P3"
BOUNDS_PATH = "/World/CAE/BoundingBox_B1_P3"


async def main():
    # 0. Import the CGNS file.
    await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")

    ctx = get_context()
    stage = ctx.get_stage()

    # Create the CAE anchor.
    UsdGeom.Xform.Define(stage, "/World/CAE")

    # 1. Extract three axis-aligned slices through the dataset center.
    await execute_command("CreateCaeVizPlanarSlice", dataset_path=DATASET_PATH, prim_path=SLICE_PATH)
    planar_slice = stage.GetPrimAtPath(SLICE_PATH)
    cae_viz.PlanarSliceAPI(planar_slice).CreateModeAttr().Set("xyz")
    cae_viz.FieldSelectionAPI(planar_slice, "colors").CreateFieldNamesAttr().Set(["Temperature"])
    await wait_for_update()

    # 2. Create and frame the dataset bounding box.
    await execute_command(
        "CreateCaeVizBoundingBox",
        dataset_paths=[DATASET_PATH],
        prim_path=BOUNDS_PATH,
    )
    await wait_for_update()
    ctx.get_selection().set_selected_prim_paths([SLICE_PATH], True)
    await frame_prims([BOUNDS_PATH], zoom=1.0)


if __name__ == "__main__":
    asyncio.ensure_future(main())
