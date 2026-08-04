# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Create the experimental direct-axisymmetric volume from a FLASH descriptor."""

import asyncio
import os

from carb.settings import get_settings
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import frame_prims, get_test_data_path, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import Gf, UsdGeom, Vt

# Usage:
# Copy/paste this script into Developer > Script Editor, or execute it on launch:
# ./repo.sh launch -n omni.cae.kit -- --exec ./scripts/example_flash_axisymmetric_volume.py
#
# The checked-in synthetic FLASH fixture is used by default. Override the input
# without editing the script:
# FLASH_DATASET=/path/to/data.flash ./repo.sh launch -n omni.cae.kit -- \
#     --exec ./scripts/example_flash_axisymmetric_volume.py

FLASH_DATASET = os.environ.get("FLASH_DATASET") or get_test_data_path(
    "FLASH/axisymmetric_wavelet/axisymmetric_wavelet.flash"
)
FLASH_FIELD = os.environ.get("FLASH_FIELD", "dens")
SAMPLING_DISTANCE_SCALE = float(os.environ.get("FLASH_SAMPLING_DISTANCE_SCALE", "1.0"))
DATASET_PATH = "/World/FlashDataset"
VOLUME_PATH = "/World/CAE/AxisymmetricVolume"
BOUNDS_PATH = "/World/CAE/FlashBounds"


async def main():
    # 0. Import the FLASH descriptor.
    await import_to_stage(FLASH_DATASET, DATASET_PATH)

    ctx = get_context()
    stage = ctx.get_stage()

    # Create the CAE anchor.
    UsdGeom.Xform.Define(stage, "/World/CAE")

    # 1. Create and frame the dataset bounding box.
    await execute_command(
        "CreateCaeVizBoundingBox",
        dataset_paths=[DATASET_PATH],
        prim_path=BOUNDS_PATH,
    )
    await wait_for_update()
    ctx.get_selection().set_selected_prim_paths([BOUNDS_PATH], True)
    await frame_prims([BOUNDS_PATH], zoom=0.9)

    # 2. Create the direct-axisymmetric volume.
    await execute_command(
        "CreateCaeVizVolume",
        dataset_path=DATASET_PATH,
        prim_path=VOLUME_PATH,
        type="axisymmetric",
    )

    # 3. Select the field and sampling quality.
    volume = stage.GetPrimAtPath(VOLUME_PATH)
    cae_viz.IndeXAxisymmetricVolumeAPI(volume).CreateSamplingDistanceScaleAttr().Set(SAMPLING_DISTANCE_SCALE)
    cae_viz.FieldSelectionAPI(volume, "colors").CreateFieldNamesAttr().Set([FLASH_FIELD])
    await wait_for_update()

    # 4. Configure a transfer function that makes the thresholded fixture
    # immediately visible.
    colormap = stage.GetPrimAtPath(f"{VOLUME_PATH}/Material/Colormap")
    colormap.GetAttribute("rgbaPoints").Set(
        Vt.Vec4fArray(
            [
                Gf.Vec4f(0.0, 0.0, 0.0, 0.0),
                Gf.Vec4f(0.1, 0.3, 1.0, 0.8),
                Gf.Vec4f(1.0, 0.05, 0.05, 1.0),
            ]
        )
    )
    colormap.GetAttribute("xPoints").Set(Vt.FloatArray([0.0, 0.001, 1.0]))

    # 5. Configure IndeX and select the result.
    settings = get_settings()
    settings.set("/rtx/index/colorScale", 85.0)
    settings.set("/rtx/index/renderingSamples", 1)
    await wait_for_update()
    ctx.get_selection().set_selected_prim_paths([VOLUME_PATH, BOUNDS_PATH], True)


if __name__ == "__main__":
    asyncio.ensure_future(main())
