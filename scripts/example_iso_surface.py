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
# ./repo.sh launch -n omni.cae.kit -- --exec ./scripts/example_iso_surface.py

DATASET_PATH = "/World/StaticMixer/Base/StaticMixer/B1_P3"
ISO_SURFACE_PATH = "/World/CAE/IsoSurface_B1_P3"
BOUNDS_PATH = "/World/CAE/BoundingBox_B1_P3"


async def main():
    # 0. Import the CGNS file.
    await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")

    ctx = get_context()
    stage = ctx.get_stage()

    # Create the CAE anchor.
    UsdGeom.Xform.Define(stage, "/World/CAE")

    # 1. Extract the 300 K temperature iso-surface.
    await execute_command("CreateCaeVizIsoSurface", dataset_path=DATASET_PATH, prim_path=ISO_SURFACE_PATH)
    iso_surface = stage.GetPrimAtPath(ISO_SURFACE_PATH)
    cae_viz.IsoSurfaceAPI(iso_surface).CreateIsoValueAttr().Set(300.0)
    cae_viz.FieldSelectionAPI(iso_surface, "contour").CreateFieldNamesAttr().Set(["Temperature"])
    cae_viz.FieldSelectionAPI(iso_surface, "colors").CreateFieldNamesAttr().Set(["Temperature"])
    await wait_for_update()

    # 2. Create and frame the dataset bounding box.
    await execute_command(
        "CreateCaeVizBoundingBox",
        dataset_paths=[DATASET_PATH],
        prim_path=BOUNDS_PATH,
    )
    await wait_for_update()
    ctx.get_selection().set_selected_prim_paths([ISO_SURFACE_PATH], True)
    await frame_prims([BOUNDS_PATH], zoom=1.0)


if __name__ == "__main__":
    asyncio.ensure_future(main())
