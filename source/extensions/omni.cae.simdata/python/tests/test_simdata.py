# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import math
from unittest import mock

import numpy as np
import omni.cae.simdata as cae_simdata
import omni.kit.test
import omni.usd
import warp as wp
import warp_simdata as simdata
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path
from pxr import OmniSci, OmniSciCgns, OmniSciFlash, Sdf, Usd
from warp_simdata.usd import utils as simusd_utils
from warp_simdata.usd.adapters import flash as flash_adapter
from warp_simdata.usd.types import AxisymmetricDualRepresentation, AxisymmetricRepresentation


class Test(omni.kit.test.AsyncTestCase):
    async def test_get_field_combines_native_and_derived_components(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        expression = cae.ArrayExpressionAPI.Apply(dataset, "vz")
        expression.CreateExpressionAttr("velx * 0")

        values = {
            "velx": [1.0, 2.0, 3.0],
            "vely": [4.0, 5.0, 6.0],
        }
        for name, value in values.items():
            field_api = OmniSci.FieldAPI.Apply(dataset, name)
            field_api.CreateNameAttr(name)
            field_api.CreateAssociationAttr("element")
            OmniSci.ArrayAPI.Apply(dataset, name)
            dataset.CreateAttribute(f"omni:sci:array:{name}:value", Sdf.ValueTypeNames.FloatArray).Set(value)

        async def load_field(_dataset, field_name_or_names, device, time_code, _representation=None):
            names = field_name_or_names if isinstance(field_name_or_names, list) else [field_name_or_names]
            arrays = [simusd_utils.get_sci_array(dataset, name, time_code, device=device) for name in names]
            return simdata.Field.from_arrays(arrays, simdata.AssociationType.ELEMENT)

        native_fields = [cae_simdata.FieldInfo(name, name, simdata.AssociationType.ELEMENT) for name in values]
        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=load_field),
        ):
            field = await cae_simdata.GetField.invoke(
                dataset,
                ["velx", "vely", "vz"],
                device="cpu",
                timeCode=Usd.TimeCode.Default(),
            )

        self.assertEqual(field.dtype, wp.vec3f)
        self.assertEqual(field.association, simdata.AssociationType.ELEMENT)
        np.testing.assert_array_equal(
            field.to_array().numpy(),
            np.array([[1.0, 4.0, 0.0], [2.0, 5.0, 0.0], [3.0, 6.0, 0.0]], dtype=np.float32),
        )

    async def test_flash_default_representation(self):
        representation = flash_adapter.DEFAULT_REPRESENTATION

        self.assertEqual(representation.angular_cells, 32)
        self.assertEqual(representation.radial_dimension, 0)
        self.assertEqual(representation.axial_dimension, 1)
        self.assertEqual(representation.angle_range, (0.0, 2.0 * math.pi))

    async def test_flash_supports_dual_representation(self):
        stage = Usd.Stage.CreateInMemory()
        flash_prim = OmniSci.Dataset.Define(stage, "/Flash").GetPrim()
        OmniSciFlash.AmrAPI.Apply(flash_prim)
        other_prim = OmniSci.Dataset.Define(stage, "/Other").GetPrim()

        representation = cae_simdata.get_dual_representation(flash_prim)
        self.assertIsInstance(representation, AxisymmetricDualRepresentation)
        self.assertEqual(representation.angular_cells, 32)
        self.assertTrue(cae_simdata.supports_dual_representation(flash_prim))
        self.assertFalse(cae_simdata.supports_dual_representation(other_prim))

    async def test_flash_representation_resolution_uses_concrete_defaults_and_authored_options(
        self,
    ):
        stage = Usd.Stage.CreateInMemory()
        flash_prim = OmniSci.Dataset.Define(stage, "/Flash").GetPrim()
        OmniSciFlash.AmrAPI.Apply(flash_prim)
        operator_prim = stage.DefinePrim("/Operator")

        default = cae_simdata.resolve_representation(flash_prim, operator_prim, "source")
        self.assertIs(type(default), AxisymmetricRepresentation)
        self.assertEqual(default, flash_adapter.DEFAULT_REPRESENTATION)

        api = cae_viz.DatasetAxisymmetricRepresentationAPI.Apply(operator_prim, "source")
        authored_default = cae_simdata.resolve_representation(flash_prim, operator_prim, "source")
        self.assertEqual(authored_default, default)
        self.assertEqual(repr(authored_default), repr(default))

        api.CreateAngularCellsAttr().Set(12)
        api.CreateMinimumAngleAttr().Set(30.0)
        api.CreateMaximumAngleAttr().Set(120.0)

        native = cae_simdata.resolve_representation(flash_prim, operator_prim, "source")
        dual = cae_simdata.resolve_representation(flash_prim, operator_prim, "source", dual=True)
        self.assertIs(type(native), AxisymmetricRepresentation)
        self.assertIsInstance(dual, AxisymmetricDualRepresentation)
        self.assertEqual(native.angular_cells, 12)
        self.assertEqual(native.angle_range, (math.pi / 6.0, 2.0 * math.pi / 3.0))
        self.assertEqual(dual.angular_cells, native.angular_cells)
        self.assertEqual(dual.angle_range, native.angle_range)

    async def test_flash_representation_resolution_rejects_invalid_authored_options(
        self,
    ):
        stage = Usd.Stage.CreateInMemory()
        flash_prim = OmniSci.Dataset.Define(stage, "/Flash").GetPrim()
        OmniSciFlash.AmrAPI.Apply(flash_prim)
        operator_prim = stage.DefinePrim("/Operator")
        api = cae_viz.DatasetAxisymmetricRepresentationAPI.Apply(operator_prim, "source")
        api.CreateMinimumAngleAttr().Set(180.0)
        api.CreateMaximumAngleAttr().Set(90.0)

        with self.assertRaisesRegex(ValueError, "Minimum Angle < Maximum Angle"):
            cae_simdata.resolve_representation(flash_prim, operator_prim, "source")

    async def test_cgns_ngon_cell_field_subset(self):
        """Cell-centered CGNS fields on NGON_n sections are remapped through NFACE_n."""
        usd_context = omni.usd.get_context()
        await usd_context.open_stage_async(get_test_data_path("hex_polyhedra.cgns"))
        stage = usd_context.get_stage()

        zone_path = "/hex_polyhedra/Base/Zone"
        ngon = stage.GetPrimAtPath(f"{zone_path}/ElementsNgons")
        nface = stage.GetPrimAtPath(f"{zone_path}/ElementsNfaces")
        self.assertTrue(ngon.IsValid())
        self.assertTrue(nface.IsValid())
        self.assertTrue(ngon.HasAPI(OmniSciCgns.UnstructuredElementsAPI))
        self.assertTrue(nface.HasAPI(OmniSciCgns.UnstructuredElementsAPI))

        ngon_field = await cae_simdata.GetField.invoke(
            ngon,
            "CellDistanceToCenter",
            device="cpu",
            timeCode=Usd.TimeCode.EarliestTime(),
        )
        ngon_field_cached = await cae_simdata.GetField.invoke(
            ngon,
            "CellDistanceToCenter",
            device="cpu",
            timeCode=Usd.TimeCode.EarliestTime(),
        )
        ngon_field_device_cached = await cae_simdata.GetField.invoke(
            ngon,
            "CellDistanceToCenter",
            device=wp.get_device("cpu"),
            timeCode=Usd.TimeCode.EarliestTime(),
        )
        nface_field = await cae_simdata.GetField.invoke(
            nface,
            "CellDistanceToCenter",
            device="cpu",
            timeCode=Usd.TimeCode.EarliestTime(),
        )

        ngon_api = OmniSciCgns.UnstructuredElementsAPI(ngon)
        ngon_element_range = ngon_api.GetElementRangeAttr().Get()
        nface_api = OmniSciCgns.UnstructuredElementsAPI(nface)
        nface_element_range = nface_api.GetElementRangeAttr().Get()

        ngon_count = ngon_element_range[1] - ngon_element_range[0] + 1
        nface_count = nface_element_range[1] - nface_element_range[0] + 1

        self.assertEqual(ngon_field.association, simdata.AssociationType.ELEMENT)
        self.assertEqual(ngon_field.size, ngon_count)
        self.assertEqual(ngon_field_cached.association, simdata.AssociationType.ELEMENT)
        self.assertEqual(ngon_field_cached.size, ngon_count)
        self.assertEqual(ngon_field_device_cached.association, simdata.AssociationType.ELEMENT)
        self.assertEqual(ngon_field_device_cached.size, ngon_count)
        self.assertEqual(nface_field.association, simdata.AssociationType.ELEMENT)
        self.assertEqual(nface_field.size, nface_count)

        usd_context.close_stage()
