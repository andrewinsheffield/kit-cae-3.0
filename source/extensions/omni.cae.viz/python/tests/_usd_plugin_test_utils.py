# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from omni.cae.testing import get_test_data_path, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from pxr import Usd, Vt

EARLIEST_TIME = Usd.TimeCode.EarliestTime()


async def import_animated_beam_sequence(stage: Usd.Stage, prim_path: str = "/World/animated_beam_vtu") -> str:
    """Import two VTU frames and author time samples on the plugin-backed dataset."""
    stage.SetTimeCodesPerSecond(1.0)

    frame_0 = await import_to_stage(get_test_data_path("animated_beam/animated_beam_00.vtu"), prim_path)
    frame_1 = await import_to_stage(get_test_data_path("animated_beam/animated_beam_01.vtu"), f"{prim_path}_frame_01")
    await wait_for_update()

    for instance in ("points", "RTData"):
        attr_name = f"omni:sci:array:{instance}:value"
        attr = frame_0.GetAttribute(attr_name)
        frame_1_attr = frame_1.GetAttribute(attr_name)
        if not attr or not frame_1_attr:
            raise ValueError(f"Animated beam VTU frame is missing {attr_name}")

        frame_0_value = attr.Get(EARLIEST_TIME)
        frame_1_value = frame_1_attr.Get(EARLIEST_TIME)
        if frame_0_value is None or frame_1_value is None:
            raise ValueError(f"Animated beam VTU frame has no value for {attr_name}")

        attr.Set(frame_0_value, Usd.TimeCode(0.0))
        attr.Set(frame_1_value, Usd.TimeCode(10.0))

    points_count = len(frame_0.GetAttribute("omni:sci:array:points:value").Get(Usd.TimeCode(0.0)))
    displ_attr = frame_0.GetAttribute("omni:sci:array:displ:value")
    displ_value = displ_attr.Get(EARLIEST_TIME) if displ_attr else None
    if displ_value is not None and len(displ_value) != points_count:
        displ_attr.Set(Vt.FloatArray([float(value) for value in displ_value[:points_count]]))

    stage.RemovePrim(frame_1.GetPath())
    await wait_for_update()
    return str(frame_0.GetPath())
