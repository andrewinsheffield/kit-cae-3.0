# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from unittest import mock

import omni.kit.test
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path, new_stage
from omni.cae.usd_plugins_importers import import_to_stage
from pxr import Usd, UsdShade


def _assert_opacity_mapping(test_case, prim: Usd.Prim, material_name: str) -> None:
    test_case.assertTrue(prim.HasAPI(cae_viz.FieldSelectionAPI, "opacity"))
    test_case.assertTrue(prim.HasAPI(cae_viz.RescaleRangeAPI, "opacity"))

    material = prim.GetChild("Materials").GetChild(material_name)
    test_case.assertTrue(material)
    test_case.assertTrue(material.GetAttribute("omni:rtx:enableCutoutOpacity").Get())

    shader = UsdShade.Shader(material.GetChild("Shader"))
    opacity_domain = shader.GetInput("opacity_domain")
    opacity_lut = shader.GetInput("opacity_lut")
    opacity = shader.GetInput("opacity")
    enable_opacity = shader.GetInput("enable_opacity")
    test_case.assertEqual(tuple(opacity_domain.Get()), (0.0, -1.0))
    test_case.assertEqual(opacity_lut.Get().path, "cae/colormaps/gist_gray.png")
    test_case.assertEqual(opacity.Get(), 1.0)
    test_case.assertFalse(enable_opacity.Get())

    rescale_api = cae_viz.RescaleRangeAPI(prim, "opacity")
    test_case.assertIn(opacity_domain.GetAttr().GetPath(), rescale_api.GetIncludesRel().GetTargets())
    test_case.assertIn(enable_opacity.GetAttr().GetPath(), rescale_api.GetEnableIncludesRel().GetTargets())


class TestMdlOpacityAuthoring(omni.kit.test.AsyncTestCase):
    async def test_mdl_shaded_operator_commands_author_independent_opacity_mapping(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            dataset_path = "/World/StaticMixer/Base/StaticMixer/B1_P3"

            commands = [
                ("CreateCaeVizFaces", "/World/CAE/Faces", {}, ("ScalarColor",)),
                ("CreateCaeVizPoints", "/World/CAE/Points", {}, ("ScalarColor",)),
                ("CreateCaeVizIsoSurface", "/World/CAE/IsoSurface", {}, ("ScalarColor",)),
                ("CreateCaeVizGlyphs", "/World/CAE/Glyphs", {}, ("ScalarColor",)),
                (
                    "CreateCaeVizStreamlines",
                    "/World/CAE/Streamlines",
                    {"type": "standard"},
                    ("ScalarColor", "AnimatedStreaks"),
                ),
                (
                    "CreateCaeVizPlanarSlice",
                    "/World/CAE/PlanarSlice",
                    {"type": "standard"},
                    ("UnlitScalarColor",),
                ),
            ]

            with mock.patch("omni.cae.viz.create_commands.settings.get_default_operator_enabled", return_value=False):
                for command_name, prim_path, kwargs, material_names in commands:
                    await execute_command(
                        command_name,
                        dataset_path=dataset_path,
                        prim_path=prim_path,
                        **kwargs,
                    )
                    prim = stage.GetPrimAtPath(prim_path)
                    self.assertTrue(prim)
                    for material_name in material_names:
                        _assert_opacity_mapping(self, prim, material_name)
