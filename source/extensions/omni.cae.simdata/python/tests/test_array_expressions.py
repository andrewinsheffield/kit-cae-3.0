# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from pathlib import Path
from unittest import mock

import numpy as np
import omni.cae.simdata as cae_simdata
import omni.kit.test
import warp as wp
import warp_simdata as simdata
from omni.cae.core import cache
from omni.cae.schema import cae
from pxr import OmniSci, OmniSciFlash, Sdf, Usd, Vt
from warp_simdata.usd import AxisymmetricRepresentation
from warp_simdata.usd import utils as simusd_utils


def _add_expression(prim, name, expression, *, enabled=True, version=1, device="auto"):
    api = cae.ArrayExpressionAPI.Apply(prim, name)
    api.CreateExpressionAttr(expression)
    api.CreateEnabledAttr(enabled)
    api.CreateLanguageVersionAttr(version)
    api.CreateComputeDeviceAttr(device)
    return api


def _add_native_field(
    prim,
    name,
    values,
    association="element",
    value_type=Sdf.ValueTypeNames.FloatArray,
):
    field_api = OmniSci.FieldAPI.Apply(prim, name)
    field_api.CreateNameAttr(name)
    field_api.CreateAssociationAttr(association)
    OmniSci.ArrayAPI.Apply(prim, name)
    attr = prim.CreateAttribute(f"omni:sci:array:{name}:value", value_type)
    if isinstance(values, dict):
        for time, sample in values.items():
            attr.Set(sample, Usd.TimeCode(time))
    else:
        attr.Set(values)
    return cae_simdata.FieldInfo(
        name,
        name,
        simdata.AssociationType.ELEMENT if association == "element" else simdata.AssociationType.NODE,
    )


def _add_array(prim, name, values, value_type):
    OmniSci.ArrayAPI.Apply(prim, name)
    prim.CreateAttribute(f"omni:sci:array:{name}:value", value_type).Set(values)


def _make_flash_prim(stage):
    prim = OmniSci.Dataset.Define(stage, "/Flash").GetPrim()
    api = OmniSciFlash.AmrAPI.Apply(prim)
    api.CreateSpatialDimensionAttr(2)
    api.CreateBoundingBoxShapeAttr(Vt.IntArray([3, 2]))
    api.CreateFieldShapeAttr(Vt.IntArray([1, 1, 2]))
    _add_array(prim, "nodeType", Vt.IntArray([1, 2, 1]), Sdf.ValueTypeNames.IntArray)
    _add_array(
        prim,
        "gid",
        Vt.IntArray(
            [
                -2,
                -2,
                -2,
                3,
                -1,
                -1,
                -1,
                -1,
                -1,
                -2,
                -2,
                -2,
                -2,
                -1,
                -1,
                -1,
                -1,
                -1,
                -2,
                -2,
                1,
                -2,
                -1,
                -1,
                -1,
                -1,
                -1,
            ]
        ),
        Sdf.ValueTypeNames.IntArray,
    )
    _add_array(
        prim,
        "boundingBox",
        Vt.FloatArray(
            [
                0.0,
                1.0,
                -1.0,
                0.0,
                0.0,
                0.1,
                1.0,
                2.0,
                -1.0,
                0.0,
                0.0,
                0.1,
                0.0,
                1.0,
                0.0,
                1.0,
                0.0,
                0.1,
            ]
        ),
        Sdf.ValueTypeNames.FloatArray,
    )
    _add_native_field(prim, "dens", Vt.FloatArray([10, 11, 20, 21, 30, 31]))
    return prim


async def _load_raw_field(dataset, field_name_or_names, device, time_code, _representation=None):
    names = field_name_or_names if isinstance(field_name_or_names, list) else [field_name_or_names]
    arrays = [simusd_utils.get_sci_array(dataset, name, time_code, device=device) for name in names]
    associations = {str(OmniSci.FieldAPI(dataset, name).GetAssociationAttr().Get(time_code)) for name in names}
    if len(associations) != 1:
        raise ValueError("field components do not share an association")
    association = simdata.AssociationType.ELEMENT if associations.pop() == "element" else simdata.AssociationType.NODE
    return simdata.Field.from_arrays(arrays, association)


class TestArrayExpressions(omni.kit.test.AsyncTestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    async def test_static_analysis_reports_dependencies_and_source_diagnostics(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        _add_native_field(dataset, "x", [1.0], association="element")
        _add_native_field(dataset, "y", [1.0], association="node")
        _add_expression(dataset, "valid", "x * 2")
        _add_expression(dataset, "unknown", "x + missing")
        _add_expression(dataset, "unknown_in_if", "if(ge(x, 0), missing, 0)")
        _add_expression(dataset, "syntax", "x +")
        _add_expression(dataset, "cycle_a", "cycle_b + 1")
        _add_expression(dataset, "cycle_b", "cycle_a + 1")
        _add_expression(dataset, "disabled", "x + 1", enabled=False)
        _add_expression(dataset, "future", "x + 1", version=99)
        _add_expression(dataset, "invalid_zero_version", "x + 1", version=0)
        _add_expression(dataset, "x", "valid + 1")
        _add_expression(dataset, "mixed_association", "x + y")

        descriptions = {item.name: item for item in await cae_simdata.get_array_expression_descriptions(dataset)}

        self.assertTrue(descriptions["valid"].valid)
        self.assertEqual(descriptions["valid"].dependencies, ("x",))
        self.assertFalse(descriptions["disabled"].valid)
        self.assertFalse(descriptions["disabled"].enabled)
        self.assertEqual(descriptions["unknown"].diagnostics[0].code, "E_UNKNOWN_FIELD")
        self.assertEqual(descriptions["unknown"].diagnostics[0].column, 5)
        self.assertEqual(descriptions["unknown_in_if"].diagnostics[0].column, 14)
        self.assertEqual(descriptions["syntax"].diagnostics[0].code, "E_SYNTAX")
        self.assertEqual(descriptions["cycle_a"].diagnostics[0].code, "E_CYCLE")
        self.assertEqual(descriptions["future"].diagnostics[0].code, "E_VERSION")
        self.assertEqual(descriptions["invalid_zero_version"].diagnostics[0].code, "E_VERSION")
        self.assertEqual(descriptions["x"].diagnostics[0].code, "E_COLLISION")
        self.assertEqual(
            descriptions["mixed_association"].diagnostics[0].code,
            "E_ASSOCIATION",
        )

    async def test_packaged_flash_authoring_layer_is_valid_usd(self):
        extension_root = next(
            parent for parent in Path(__file__).parents if (parent / "config" / "extension.toml").is_file()
        )
        sample_path = extension_root / "data" / "flash_array_expressions.usda"
        layer = Sdf.Layer.FindOrOpen(str(sample_path))
        self.assertIsNotNone(layer)
        stage = Usd.Stage.Open(layer)
        dataset = stage.GetPrimAtPath("/World/Flash")
        self.assertTrue(dataset.HasAPI(cae.ArrayExpressionAPI, "beryllium_density"))
        self.assertTrue(dataset.HasAPI(cae.ArrayExpressionAPI, "liner_density"))

    async def test_flash_evaluates_recursive_expressions_before_axisymmetric_expansion(
        self,
    ):
        stage = Usd.Stage.CreateInMemory()
        dataset = _make_flash_prim(stage)
        _add_expression(dataset, "twice_density", "dens * 2")
        _add_expression(dataset, "four_times_density", "twice_density * 2")

        field = await cae_simdata.GetField.invoke(
            dataset,
            "four_times_density",
            device="cpu",
            timeCode=Usd.TimeCode.Default(),
            representation=AxisymmetricRepresentation(angular_cells=4),
        )

        self.assertEqual(field.size, 16)
        self.assertEqual(
            field.to_array().numpy().tolist(),
            [40.0] * 4 + [44.0] * 4 + [120.0] * 4 + [124.0] * 4,
        )

    async def test_scalar_v1_functions_evaluate_to_float32(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        _add_expression(dataset, "result", "clamp(sqrt(abs(x)) + max(y, 2), 0, 10)")
        values = {
            "x": np.array([4.0, 9.0, 16.0], dtype=np.float32),
            "y": np.array([1.0, 4.0, 20.0], dtype=np.float32),
        }
        native_fields = [_add_native_field(dataset, name, value) for name, value in values.items()]
        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
        ):
            field = await cae_simdata.GetField.invoke(dataset, "result", device="cpu", timeCode=Usd.TimeCode(0))

        self.assertEqual(field.dtype, wp.float32)
        np.testing.assert_allclose(field.to_array().numpy(), [4.0, 7.0, 10.0])

    async def test_expression_can_be_owned_by_a_non_dataset_array_prim(self):
        stage = Usd.Stage.CreateInMemory()
        array_prim = stage.DefinePrim("/Fields")
        _add_native_field(array_prim, "density", [1.0, 2.0, 3.0])
        _add_expression(array_prim, "twice_density", "density * 2")

        field = await cae_simdata.get_prim_field(
            array_prim,
            "twice_density",
            device="cpu",
            timeCode=Usd.TimeCode.Default(),
        )

        np.testing.assert_allclose(field.to_array().numpy(), [2.0, 4.0, 6.0])

    async def test_native_vector_dependency_preserves_companion_width(self):
        stage = Usd.Stage.CreateInMemory()
        array_prim = stage.DefinePrim("/Fields")
        _add_native_field(
            array_prim,
            "velocity",
            Vt.Vec3fArray([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]),
            value_type=Sdf.ValueTypeNames.Float3Array,
        )
        _add_expression(array_prim, "scaled", "velocity * 2")

        fields = cae_simdata.get_prim_fields(array_prim)
        field = await cae_simdata.get_prim_field(
            array_prim,
            "scaled",
            device="cpu",
            timeCode=Usd.TimeCode.Default(),
        )

        self.assertIn("scaled", {item.name for item in fields})
        self.assertEqual(
            array_prim.GetAttribute("omni:sci:array:scaled:value").GetTypeName(),
            Sdf.ValueTypeNames.Float3Array,
        )
        np.testing.assert_allclose(field.to_array().numpy(), [[2.0, 4.0, 6.0], [8.0, 10.0, 12.0]])

    async def test_expression_lookup_prefers_the_requested_owner_over_siblings(self):
        stage = Usd.Stage.CreateInMemory()
        left = OmniSci.Dataset.Define(stage, "/Left").GetPrim()
        right = OmniSci.Dataset.Define(stage, "/Right").GetPrim()
        left_native = _add_native_field(left, "density", [1.0, 2.0])
        _add_native_field(right, "density", [10.0, 20.0])
        _add_expression(left, "derived", "density * 2")
        _add_expression(right, "derived", "density * 3")

        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=[left_native],
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
        ):
            field = await cae_simdata.GetField.invoke(
                left,
                "derived",
                device="cpu",
                timeCode=Usd.TimeCode.Default(),
            )

        np.testing.assert_allclose(field.to_array().numpy(), [2.0, 4.0])

    async def test_expression_lookup_bridges_an_element_prim_to_its_field_owner(self):
        stage = Usd.Stage.CreateInMemory()
        element_prim = OmniSci.Dataset.Define(stage, "/Base/Zone/Section").GetPrim()
        field_owner = stage.DefinePrim("/Base/Zone/FlowSolution")
        native_field = _add_native_field(field_owner, "density", [1.0, 2.0, 3.0])
        _add_expression(field_owner, "derived", "density * 2")

        async def load_from_field_owner(_dataset, field_name_or_names, device, time_code, _representation=None):
            names = field_name_or_names if isinstance(field_name_or_names, list) else [field_name_or_names]
            arrays = [simusd_utils.get_sci_array(field_owner, name, time_code, device=device) for name in names]
            return simdata.Field.from_arrays(arrays, simdata.AssociationType.ELEMENT)

        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=[native_field],
            ),
            mock.patch.object(
                cae_simdata.GetField,
                "_invoke_native",
                side_effect=load_from_field_owner,
            ),
        ):
            fields = await cae_simdata.GetAvailableFields.invoke(element_prim)
            field = await cae_simdata.GetField.invoke(
                element_prim,
                "derived",
                device="cpu",
                timeCode=Usd.TimeCode.Default(),
            )

        self.assertIn("derived", {item.name for item in fields})
        np.testing.assert_allclose(field.to_array().numpy(), [2.0, 4.0, 6.0])

    async def test_prim_field_discovery_synchronizes_expression_array_metadata(self):
        stage = Usd.Stage.CreateInMemory()
        array_prim = stage.DefinePrim("/Fields")
        _add_native_field(array_prim, "density", [1.0, 2.0, 3.0])
        expression = _add_expression(array_prim, "derived", "density * 2")

        fields = cae_simdata.get_prim_fields(array_prim)

        self.assertIn("derived", {field.name for field in fields})
        value_attr = array_prim.GetAttribute("omni:sci:array:derived:value")
        self.assertEqual(value_attr.GetTypeName(), Sdf.ValueTypeNames.FloatArray)
        self.assertTrue(array_prim.HasAPI(OmniSci.FieldAPI, "derived"))
        self.assertTrue(array_prim.HasAPI(OmniSci.ArrayAPI, "derived"))

        expression.GetExpressionAttr().Set("vec3(density, density, density)")
        cae_simdata.get_prim_fields(array_prim)
        self.assertEqual(
            array_prim.GetAttribute("omni:sci:array:derived:value").GetTypeName(),
            Sdf.ValueTypeNames.Float3Array,
        )

        expression.GetExpressionAttr().Set("missing * 2")
        fields = cae_simdata.get_prim_fields(array_prim)
        self.assertNotIn("derived", {field.name for field in fields})
        self.assertFalse(array_prim.HasAPI(OmniSci.FieldAPI, "derived"))
        self.assertFalse(array_prim.HasAPI(OmniSci.ArrayAPI, "derived"))
        self.assertTrue(array_prim.HasAPI(cae.ArrayExpressionAPI, "derived"))

        expression.GetExpressionAttr().Set("density * 2")
        cae_simdata.get_prim_fields(array_prim)
        array_prim.RemoveAPI("CaeArrayExpressionAPI", "derived")
        fields = cae_simdata.get_prim_fields(array_prim)
        self.assertNotIn("derived", {field.name for field in fields})
        self.assertFalse(array_prim.HasAPI(OmniSci.FieldAPI, "derived"))
        self.assertFalse(array_prim.HasAPI(OmniSci.ArrayAPI, "derived"))

    async def test_cache_reuses_shared_dependency_and_separates_time_and_representation(
        self,
    ):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        _add_expression(dataset, "shared", "x * 2")
        _add_expression(dataset, "first", "shared + 1")
        _add_expression(dataset, "second", "shared + 2")
        calls = []
        native_fields = [_add_native_field(dataset, "x", {0: [1.0], 1: [2.0]}, "node")]
        original_get_sci_array = simusd_utils.get_sci_array

        def counted_get_sci_array(prim, instance_or_instances, time_code, **kwargs):
            if instance_or_instances == "x":
                calls.append(time_code.GetValue())
            return original_get_sci_array(prim, instance_or_instances, time_code, **kwargs)

        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
            mock.patch.object(simusd_utils, "get_sci_array", side_effect=counted_get_sci_array),
        ):
            first = await cae_simdata.GetField.invoke(
                dataset,
                "first",
                device="cpu",
                timeCode=Usd.TimeCode(0),
                representation="a",
            )
            second = await cae_simdata.GetField.invoke(
                dataset,
                "second",
                device="cpu",
                timeCode=Usd.TimeCode(0),
                representation="a",
            )
            later = await cae_simdata.GetField.invoke(
                dataset,
                "first",
                device="cpu",
                timeCode=Usd.TimeCode(1),
                representation="a",
            )
            other_representation = await cae_simdata.GetField.invoke(
                dataset,
                "first",
                device="cpu",
                timeCode=Usd.TimeCode(0),
                representation="b",
            )

        self.assertEqual(calls, [0.0, 1.0])
        np.testing.assert_allclose(first.to_array().numpy(), [3.0])
        np.testing.assert_allclose(second.to_array().numpy(), [4.0])
        np.testing.assert_allclose(later.to_array().numpy(), [5.0])
        np.testing.assert_allclose(other_representation.to_array().numpy(), [3.0])

    async def test_expression_edit_changes_cached_graph(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        api = _add_expression(dataset, "result", "x + 1")
        native_fields = [_add_native_field(dataset, "x", [2.0], "node")]
        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
        ):
            before = await cae_simdata.GetField.invoke(dataset, "result", device="cpu", timeCode=Usd.TimeCode(0))
            api.GetExpressionAttr().Set("x + 2")
            after = await cae_simdata.GetField.invoke(dataset, "result", device="cpu", timeCode=Usd.TimeCode(0))

        np.testing.assert_allclose(before.to_array().numpy(), [3.0])
        np.testing.assert_allclose(after.to_array().numpy(), [4.0])

    async def test_cuda_evaluation_when_available(self):
        if wp.get_cuda_device_count() == 0:
            self.skipTest("CUDA is not available")

        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        _add_expression(dataset, "result", "x * 3", device="cuda:0")
        native_fields = [_add_native_field(dataset, "x", [2.0], "node")]
        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
        ):
            field = await cae_simdata.GetField.invoke(dataset, "result", device="cpu", timeCode=Usd.TimeCode(0))

        self.assertEqual(field.device, "cpu")
        np.testing.assert_allclose(field.to_array().numpy(), [6.0])

    async def test_like_constants_match_scalar_vector_and_derived_layouts(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Fields")
        _add_native_field(prim, "x", Vt.FloatArray([float("nan"), float("inf")]))
        _add_expression(prim, "vector", "vec3(x, x, x)")
        _add_expression(prim, "zero_vector", "zeros_like(vector)")
        _add_expression(prim, "one_scalar", "ones_like(x)")
        _add_expression(prim, "filled_vector", "full_like(vector, -2.5)")

        fields = cae_simdata.get_prim_fields(prim)
        zero_vector = await cae_simdata.get_prim_field(
            prim, "zero_vector", device="cpu", timeCode=Usd.TimeCode.Default()
        )
        one_scalar = await cae_simdata.get_prim_field(prim, "one_scalar", device="cpu", timeCode=Usd.TimeCode.Default())
        filled_vector = await cae_simdata.get_prim_field(
            prim, "filled_vector", device="cpu", timeCode=Usd.TimeCode.Default()
        )

        self.assertTrue({"zero_vector", "one_scalar", "filled_vector"}.issubset({field.name for field in fields}))
        self.assertEqual(
            prim.GetAttribute("omni:sci:array:zero_vector:value").GetTypeName(),
            Sdf.ValueTypeNames.Float3Array,
        )
        np.testing.assert_array_equal(zero_vector.to_array().numpy(), np.zeros((2, 3), dtype=np.float32))
        np.testing.assert_array_equal(one_scalar.to_array().numpy(), np.ones(2, dtype=np.float32))
        np.testing.assert_array_equal(
            filled_vector.to_array().numpy(),
            np.full((2, 3), -2.5, dtype=np.float32),
        )

    async def test_full_like_requires_a_literal_and_like_requires_a_field_dependency(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Fields")
        _add_native_field(prim, "x", [1.0])
        _add_expression(prim, "computed_fill", "full_like(x, x)")
        _add_expression(prim, "missing_reference", "zeros_like(1)")

        descriptions = {item.name: item for item in await cae_simdata.get_array_expression_descriptions(prim)}

        self.assertEqual(descriptions["computed_fill"].diagnostics[0].code, "E_FILL_VALUE")
        self.assertEqual(descriptions["missing_reference"].diagnostics[0].code, "E_NO_DEPENDENCY")

    async def test_vector_construction_component_magnitude_dot_and_cross(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        _add_expression(dataset, "velocity", "vec3(x, y, z)")
        _add_expression(dataset, "speed", "magnitude(velocity)")
        _add_expression(dataset, "vertical", "component(velocity, 2)")
        _add_expression(dataset, "alignment", "dot(velocity, vec3(1, 0, 0))")
        _add_expression(dataset, "normal", "cross(velocity, vec3(0, 0, 1))")
        _add_expression(dataset, "bounded", "clamp(x, 0, vec3(1, 2, 4))")
        values = {"x": [3.0], "y": [4.0], "z": [0.0]}
        native_fields = [_add_native_field(dataset, name, value, "node") for name, value in values.items()]
        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
        ):
            velocity = await cae_simdata.GetField.invoke(dataset, "velocity", device="cpu", timeCode=Usd.TimeCode(0))
            speed = await cae_simdata.GetField.invoke(dataset, "speed", device="cpu", timeCode=Usd.TimeCode(0))
            vertical = await cae_simdata.GetField.invoke(dataset, "vertical", device="cpu", timeCode=Usd.TimeCode(0))
            alignment = await cae_simdata.GetField.invoke(dataset, "alignment", device="cpu", timeCode=Usd.TimeCode(0))
            normal = await cae_simdata.GetField.invoke(dataset, "normal", device="cpu", timeCode=Usd.TimeCode(0))
            bounded = await cae_simdata.GetField.invoke(dataset, "bounded", device="cpu", timeCode=Usd.TimeCode(0))

        self.assertEqual(velocity.dtype, wp.vec3f)
        np.testing.assert_allclose(velocity.to_array().numpy(), [[3.0, 4.0, 0.0]])
        np.testing.assert_allclose(speed.to_array().numpy(), [5.0])
        np.testing.assert_allclose(vertical.to_array().numpy(), [0.0])
        np.testing.assert_allclose(alignment.to_array().numpy(), [3.0])
        np.testing.assert_allclose(normal.to_array().numpy(), [[4.0, -3.0, 0.0]])
        np.testing.assert_allclose(bounded.to_array().numpy(), [[1.0, 2.0, 3.0]])

    async def test_vector_only_functions_reject_scalars(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = OmniSci.Dataset.Define(stage, "/Dataset").GetPrim()
        _add_expression(dataset, "bad_component", "component(x, 0)")
        _add_expression(dataset, "bad_dot", "dot(x, vec2(x, x))")
        _add_expression(dataset, "bad_cross", "cross(vec3(x, x, x), x)")
        native_fields = [_add_native_field(dataset, "x", [1.0], "node")]
        with (
            mock.patch.object(
                cae_simdata.GetAvailableFields,
                "_invoke_native",
                return_value=native_fields,
            ),
            mock.patch.object(cae_simdata.GetField, "_invoke_native", side_effect=_load_raw_field),
        ):
            for name in ("bad_component", "bad_dot", "bad_cross"):
                with self.assertRaisesRegex(Exception, "E_VECTOR_ARGUMENT"):
                    await cae_simdata.GetField.invoke(
                        dataset,
                        name,
                        device="cpu",
                        timeCode=Usd.TimeCode(0),
                    )
