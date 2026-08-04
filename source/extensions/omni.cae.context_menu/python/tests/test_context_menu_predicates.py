# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from unittest import mock

import omni.kit.test
from omni.cae.context_menu import context_menu
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from pxr import OmniSci, Usd, UsdGeom, UsdVol


def _objects(stage: Usd.Stage, prims: list[Usd.Prim], hovered: Usd.Prim = None) -> dict:
    return {
        "stage": stage,
        "prim_list": prims,
        "hovered_prim": hovered or prims[0],
        "use_hovered": True,
    }


class TestContextMenuPredicates(omni.kit.test.AsyncTestCase):
    async def test_volume_slice_is_only_shown_for_one_volume(self):
        stage = Usd.Stage.CreateInMemory()
        volume = UsdVol.Volume.Define(stage, "/Volume").GetPrim()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()

        self.assertTrue(context_menu.VolumeSlice.show(_objects(stage, [volume])))
        self.assertTrue(context_menu.VolumeSlice.enabled(_objects(stage, [volume])))
        self.assertFalse(context_menu.VolumeSlice.show(_objects(stage, [dataset])))
        self.assertFalse(context_menu.VolumeSlice.enabled(_objects(stage, [dataset])))

    async def test_mixed_dataset_types_enable_dataset_operators(self):
        stage = Usd.Stage.CreateInMemory()
        cae_dataset = cae.DataSet.Define(stage, "/CaeDataset").GetPrim()
        omnisci_dataset = OmniSci.Dataset.Define(stage, "/OmniSciDataset").GetPrim()
        objects = _objects(stage, [cae_dataset, omnisci_dataset])

        self.assertTrue(context_menu.OperatorsPoints.enabled(objects))
        self.assertTrue(context_menu.BoundingBox.enabled(objects))

    async def test_mixed_invalid_selection_is_not_reduced_to_hovered_prim(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Dataset").GetPrim()
        other = UsdGeom.Xform.Define(stage, "/Other").GetPrim()
        objects = _objects(stage, [dataset, other], hovered=dataset)

        self.assertEqual(context_menu.get_active_prims(objects, lambda prim: prim.IsA(cae.DataSet)), [])
        self.assertFalse(context_menu.OperatorsPoints.enabled(objects))

    async def test_add_api_entries_are_hidden_without_a_selection(self):
        stage = Usd.Stage.CreateInMemory()
        self.assertFalse(context_menu.can_apply_api("CaeVizOperatorDebuggingAPI", {"stage": stage}))

    async def test_colormap_texture_is_only_offered_for_colormaps(self):
        stage = Usd.Stage.CreateInMemory()
        colormap = stage.DefinePrim("/Colormap", "Colormap")
        other = UsdGeom.Xform.Define(stage, "/Other").GetPrim()

        with mock.patch.object(context_menu, "can_apply_api_prim", return_value=True):
            self.assertTrue(context_menu.can_apply_colormap_texture(_objects(stage, [colormap])))
            self.assertFalse(context_menu.can_apply_colormap_texture(_objects(stage, [other])))
            self.assertFalse(context_menu.can_apply_colormap_texture(_objects(stage, [colormap, other])))

    async def test_adding_colormap_texture_rebuilds_property_window(self):
        stage = Usd.Stage.CreateInMemory()
        colormap = stage.DefinePrim("/Colormap", "Colormap")
        property_window = mock.Mock()

        with mock.patch("omni.kit.window.property.get_window", return_value=property_window):
            context_menu._add_colormap_texture_api({"stage": stage, "prim_list": [colormap]})

        self.assertTrue(colormap.HasAPI(cae_viz.ColormapTextureAPI))
        self.assertTrue(cae_viz.ColormapTextureAPI(colormap).GetIdentifierAttr().Get())
        property_window.request_rebuild.assert_called_once_with()

    async def test_colormap_source_and_texture_actions_expose_color_and_opacity_workflows(self):
        source_entries = context_menu.get_sources_menu_dict()["name"]["CAE Sources"]
        self.assertIn("Colormap", [entry["name"] for entry in source_entries])

        stage = Usd.Stage.CreateInMemory()
        colormap = stage.DefinePrim("/Colormap", "Colormap")
        cae_viz.ColormapTextureAPI.Apply(colormap).GetIdentifierAttr().Set("abc123")
        objects = _objects(stage, [colormap])

        with mock.patch("omni.kit.clipboard.copy") as copy:
            context_menu.ColormapCopyLutUrl.onclick(objects)
            copy.assert_called_once_with("dynamic://cae_colormap_abc123")
            copy.reset_mock()
            context_menu.ColormapCopyOpacityLutUrl.onclick(objects)
            copy.assert_called_once_with("dynamic://cae_opacitymap_abc123")

    async def test_mdl_shaded_operators_suggest_an_opacity_field(self):
        stage = Usd.Stage.CreateInMemory()
        operators = [
            cae_viz.FacesAPI.Apply(UsdGeom.Mesh.Define(stage, "/Faces").GetPrim()).GetPrim(),
            cae_viz.IsoSurfaceAPI.Apply(UsdGeom.Mesh.Define(stage, "/IsoSurface").GetPrim()).GetPrim(),
            cae_viz.StreamlinesAPI.Apply(UsdGeom.BasisCurves.Define(stage, "/Streamlines").GetPrim()).GetPrim(),
            cae_viz.PointsAPI.Apply(UsdGeom.Points.Define(stage, "/Points").GetPrim()).GetPrim(),
            cae_viz.GlyphsAPI.Apply(UsdGeom.PointInstancer.Define(stage, "/Glyphs").GetPrim()).GetPrim(),
            cae_viz.PlanarSliceAPI.Apply(UsdGeom.Mesh.Define(stage, "/PlanarSlice").GetPrim()).GetPrim(),
        ]

        for prim in operators:
            self.assertIn("opacity", context_menu.get_field_selection_suggestions([prim]))

    async def test_flow_dataset_injector_accepts_omnisci_datasets(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()

        with mock.patch.object(context_menu, "get_flow_layer_numbers", return_value=[0]):
            self.assertTrue(context_menu.FlowDatasetInjector.enabled(_objects(stage, [dataset])))

    async def test_flow_boundary_accepts_mixed_dataset_and_boundable_selection(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        mesh = UsdGeom.Mesh.Define(stage, "/Mesh").GetPrim()
        objects = _objects(stage, [dataset, mesh])

        with mock.patch.object(context_menu, "get_flow_layer_numbers", return_value=[0]):
            self.assertTrue(context_menu.FlowBoundary.enabled(objects))
            self.assertTrue(context_menu.FlowFuelInjectorSphere.enabled(objects))
