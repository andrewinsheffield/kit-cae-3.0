# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Extract planar slices from an axisymmetric FLASH dataset."""

import asyncio
import os

from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import frame_prims, get_test_data_path, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import UsdGeom

# Usage:
# Copy/paste this script into Developer > Script Editor, or execute it on launch:
# ./repo.sh launch -n omni.cae.kit -- --exec ./scripts/example_flash_planar_slice.py

FLASH_DATASET = os.environ.get("FLASH_DATASET") or get_test_data_path(
    "FLASH/axisymmetric_wavelet/axisymmetric_wavelet.flash"
)
FLASH_FIELD = os.environ.get("FLASH_FIELD", "dens")
FLASH_ANGULAR_CELLS = int(os.environ.get("FLASH_ANGULAR_CELLS", "16"))
FLASH_SLICE_MODE = os.environ.get("FLASH_SLICE_MODE", "xyz")
DATASET_PATH = "/World/FlashDataset"
SLICE_PATH = "/World/CAE/FlashPlanarSlice"
BOUNDS_PATH = "/World/CAE/FlashBounds"


async def main():
    # 0. Import the FLASH descriptor.
    await import_to_stage(FLASH_DATASET, DATASET_PATH)

    ctx = get_context()
    stage = ctx.get_stage()

    # Create the CAE anchor.
    UsdGeom.Xform.Define(stage, "/World/CAE")

    # 1. Reconstruct the axisymmetric topology and extract centered slices.
    await execute_command("CreateCaeVizPlanarSlice", dataset_path=DATASET_PATH, prim_path=SLICE_PATH)
    planar_slice = stage.GetPrimAtPath(SLICE_PATH)
    cae_viz.DatasetAxisymmetricRepresentationAPI(planar_slice, "source").CreateAngularCellsAttr().Set(
        FLASH_ANGULAR_CELLS
    )
    cae_viz.PlanarSliceAPI(planar_slice).CreateModeAttr().Set(FLASH_SLICE_MODE)
    cae_viz.FieldSelectionAPI(planar_slice, "colors").CreateFieldNamesAttr().Set([FLASH_FIELD])
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
