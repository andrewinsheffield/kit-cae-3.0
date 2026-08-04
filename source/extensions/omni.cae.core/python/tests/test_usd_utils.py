# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from logging import getLogger
from math import inf

import omni.kit.test
from omni.cae.core import usd_utils
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path
from omni.kit.app import get_app
from omni.usd import get_context
from pxr import Sdf, Usd, UsdGeom

logger = getLogger(__name__)


class TestUsdUtils(omni.kit.test.AsyncTestCase):
    async def tearDown(self):
        ctx = get_context()
        if ctx.get_stage():
            ctx.close_stage()

    async def _attach_stage(self, stage):
        await get_context().attach_stage_async(stage)

    async def test_get_bracketing_time_samples_for_prim(self):
        stage = Usd.Stage.CreateInMemory()

        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field1 = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        field2 = cae.FieldArray.Define(stage, "/Root/DataSet/Field2")

        attr1 = field1.GetPrim().CreateAttribute("testAttr1", Sdf.ValueTypeNames.Float)
        attr2 = field2.GetPrim().CreateAttribute("testAttr2", Sdf.ValueTypeNames.Float)

        attr1.Set(10.0, Usd.TimeCode(0.0))
        attr1.Set(20.0, Usd.TimeCode(1.0))
        attr1.Set(30.0, Usd.TimeCode(2.0))
        attr1.Set(40.0, Usd.TimeCode(3.0))

        attr2.Set(100.0, Usd.TimeCode(1.5))
        attr2.Set(200.0, Usd.TimeCode(2.5))

        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())
        dataset.GetPrim().CreateRelationship("field:Field2").AddTarget(field2.GetPrim().GetPath())

        await self._attach_stage(stage)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(dataset.GetPrim(), 1.0)
        self.assertEqual(lower, 1.0)
        self.assertEqual(upper, 1.0)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(dataset.GetPrim(), 1.5)
        self.assertEqual(lower, 1.5)
        self.assertEqual(upper, 1.5)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(dataset.GetPrim(), 2.2)
        self.assertEqual(lower, 2.0)
        self.assertEqual(upper, 2.5)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(dataset.GetPrim(), -1.0)
        self.assertEqual(lower, 0.0)
        self.assertEqual(upper, 0.0)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(dataset.GetPrim(), 5.0)
        self.assertEqual(lower, 3.0)
        self.assertEqual(upper, 3.0)
        self.assertTrue(has_time_samples)

        empty_prim = cae.DataSet.Define(stage, "/Root/EmptyDataSet")
        earliest_time = Usd.TimeCode.EarliestTime().GetValue()
        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(empty_prim.GetPrim(), 1.0)
        self.assertEqual(lower, earliest_time)
        self.assertEqual(upper, earliest_time)
        self.assertFalse(has_time_samples)

        invalid_prim = stage.GetPrimAtPath("/Root/NonExistent")
        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(invalid_prim, 1.0)
        self.assertEqual(lower, earliest_time)
        self.assertEqual(upper, earliest_time)
        self.assertFalse(has_time_samples)

    async def test_get_bracketing_time_samples_for_omnisci_relationship_prim(self):
        stage = Usd.Stage.CreateInMemory()

        operator_prim = stage.DefinePrim("/Root/FacesLike", "Mesh")
        cae_viz.DatasetSelectionAPI.Apply(operator_prim, "source")

        source = stage.DefinePrim("/Root/Zone/ElementsUniform", "OmniCgnsElements_t")
        field = stage.DefinePrim("/Root/Zone/SolutionVertex0001/PointSinusoid", "OmniSciArray")
        value_attr = field.CreateAttribute("omni:sci:array:PointSinusoid:value", Sdf.ValueTypeNames.Float)
        value_attr.Set(1.0, Usd.TimeCode(1.0))
        value_attr.Set(2.0, Usd.TimeCode(2.0))

        source.CreateRelationship("field:PointSinusoid").AddTarget(field.GetPath())
        cae_viz.DatasetSelectionAPI(operator_prim, "source").GetTargetRel().SetTargets({source.GetPath()})

        await self._attach_stage(stage)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(operator_prim, 1.5)
        self.assertTrue(has_time_samples)
        self.assertEqual(lower, 1.0)
        self.assertEqual(upper, 2.0)

    async def test_get_bracketing_time_samples_for_omnisci_dataset_selection(self):
        manager = get_app().get_extension_manager()
        if not manager.is_extension_enabled("omni.cae.usd_plugins"):
            self.skipTest("CGNS USD file-format plugin is not enabled")

        usd_context = get_context()
        await usd_context.open_stage_async(get_test_data_path("hex_timesteps.cgns"))
        stage: Usd.Stage = usd_context.get_stage()
        if stage is None:
            self.skipTest("CGNS USD file-format plugin is not available")

        source = stage.GetPrimAtPath("/hex_timesteps/Base/Zone/ElementsUniform")
        self.assertTrue(source.IsValid())

        query_time = 3.0

        zone = stage.GetPrimAtPath("/hex_timesteps/Base/Zone")
        self.assertTrue(zone.IsValid())

        flow_solution_targets = zone.GetRelationship("omni:cgns:zone:flowSolutions").GetForwardedTargets()
        self.assertTrue(flow_solution_targets)

        point_sinusoid_times = set()
        for target in flow_solution_targets:
            flow_solution = stage.GetPrimAtPath(target)
            value_attr = flow_solution.GetAttribute("omni:sci:array:PointSinusoid:value")
            if not value_attr.IsValid():
                continue
            if bracket := value_attr.GetBracketingTimeSamples(query_time):
                point_sinusoid_times.update(bracket)

        self.assertTrue(point_sinusoid_times)

        expected_lower = max((t for t in point_sinusoid_times if t <= query_time), default=-inf)
        expected_upper = min((t for t in point_sinusoid_times if t >= query_time), default=inf)
        if expected_lower == -inf:
            expected_lower = expected_upper
        if expected_upper == inf:
            expected_upper = expected_lower

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(source, query_time)
        self.assertTrue(has_time_samples)
        self.assertEqual(lower, expected_lower)
        self.assertEqual(upper, expected_upper)

        operator_prim = stage.DefinePrim("/hex_timesteps/CAE/FacesLike", "Mesh")
        cae_viz.DatasetSelectionAPI.Apply(operator_prim, "source")
        cae_viz.DatasetSelectionAPI(operator_prim, "source").GetTargetRel().SetTargets({source.GetPath()})

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_prim(operator_prim, query_time)
        self.assertTrue(has_time_samples)
        self.assertEqual(lower, expected_lower)
        self.assertEqual(upper, expected_upper)

    async def test_get_bracketing_time_samples_for_data_set_prim(self):
        stage = Usd.Stage.CreateInMemory()

        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field1 = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        field2 = cae.FieldArray.Define(stage, "/Root/DataSet/Field2")

        attr1 = field1.GetPrim().CreateAttribute("testAttr1", Sdf.ValueTypeNames.Float)
        attr2 = field2.GetPrim().CreateAttribute("testAttr2", Sdf.ValueTypeNames.Float)

        attr1.Set(10.0, Usd.TimeCode(0.0))
        attr1.Set(20.0, Usd.TimeCode(1.0))
        attr1.Set(30.0, Usd.TimeCode(2.0))
        attr1.Set(40.0, Usd.TimeCode(3.0))

        attr2.Set(100.0, Usd.TimeCode(1.5))
        attr2.Set(200.0, Usd.TimeCode(2.5))

        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())
        dataset.GetPrim().CreateRelationship("field:Field2").AddTarget(field2.GetPrim().GetPath())

        coords = cae.FieldArray.Define(stage, "/Root/DataSet/Coords")
        coords_attr = coords.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.Float)
        coords_attr.Set(5.0, Usd.TimeCode(0.5))
        coords_attr.Set(6.0, Usd.TimeCode(1.5))
        dataset.GetPrim().CreateRelationship("coordinates").AddTarget(coords.GetPrim().GetPath())

        await self._attach_stage(stage)

        earliest_time = Usd.TimeCode.EarliestTime().GetValue()

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            dataset.GetPrim(), 1.0, traverse_field_relationships=True
        )
        self.assertEqual(lower, 1.0)
        self.assertEqual(upper, 1.0)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            dataset.GetPrim(), 1.0, traverse_field_relationships=False
        )
        self.assertEqual(lower, 0.5)
        self.assertEqual(upper, 1.5)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            dataset.GetPrim(), 0.3, traverse_field_relationships=False
        )
        self.assertEqual(lower, 0.5)
        self.assertEqual(upper, 0.5)
        self.assertTrue(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            dataset.GetPrim(), 2.0, traverse_field_relationships=False
        )
        self.assertEqual(lower, 1.5)
        self.assertEqual(upper, 1.5)
        self.assertTrue(has_time_samples)

        dataset_only_fields = cae.DataSet.Define(stage, "/Root/DataSetOnlyFields")
        field_only = cae.FieldArray.Define(stage, "/Root/DataSetOnlyFields/Field")
        field_attr = field_only.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.Float)
        field_attr.Set(10.0, Usd.TimeCode(1.0))
        dataset_only_fields.GetPrim().CreateRelationship("field:Field").AddTarget(field_only.GetPrim().GetPath())

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            dataset_only_fields.GetPrim(), 1.0, traverse_field_relationships=False
        )
        self.assertEqual(lower, earliest_time)
        self.assertEqual(upper, earliest_time)
        self.assertFalse(has_time_samples)

        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            dataset_only_fields.GetPrim(), 1.0, traverse_field_relationships=True
        )
        self.assertEqual(lower, 1.0)
        self.assertEqual(upper, 1.0)
        self.assertTrue(has_time_samples)

        invalid_prim = stage.GetPrimAtPath("/Root/NonExistent")
        lower, upper, has_time_samples = usd_utils.get_bracketing_time_samples_for_data_set_prim(
            invalid_prim, 1.0, traverse_field_relationships=True
        )
        self.assertEqual(lower, earliest_time)
        self.assertEqual(upper, earliest_time)
        self.assertFalse(has_time_samples)

    async def test_snap_time_code_to_prim(self):
        stage = Usd.Stage.CreateInMemory()

        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field1 = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        field2 = cae.FieldArray.Define(stage, "/Root/DataSet/Field2")

        attr1 = field1.GetPrim().CreateAttribute("testAttr1", Sdf.ValueTypeNames.Float)
        attr2 = field2.GetPrim().CreateAttribute("testAttr2", Sdf.ValueTypeNames.Float)

        attr1.Set(10.0, Usd.TimeCode(0.0))
        attr1.Set(20.0, Usd.TimeCode(1.0))
        attr1.Set(30.0, Usd.TimeCode(2.0))
        attr1.Set(40.0, Usd.TimeCode(3.0))

        attr2.Set(100.0, Usd.TimeCode(1.5))
        attr2.Set(200.0, Usd.TimeCode(2.5))

        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())
        dataset.GetPrim().CreateRelationship("field:Field2").AddTarget(field2.GetPrim().GetPath())

        await self._attach_stage(stage)

        earliest_time = Usd.TimeCode.EarliestTime()

        self.assertEqual(usd_utils.snap_time_code_to_prim(dataset.GetPrim(), Usd.TimeCode(1.0)), Usd.TimeCode(1.0))
        self.assertEqual(usd_utils.snap_time_code_to_prim(dataset.GetPrim(), Usd.TimeCode(2.2)), Usd.TimeCode(2.0))
        self.assertEqual(usd_utils.snap_time_code_to_prim(dataset.GetPrim(), Usd.TimeCode(-1.0)), Usd.TimeCode(0.0))
        self.assertEqual(usd_utils.snap_time_code_to_prim(dataset.GetPrim(), Usd.TimeCode(5.0)), Usd.TimeCode(3.0))

        empty_prim = cae.DataSet.Define(stage, "/Root/EmptyDataSet")
        self.assertEqual(usd_utils.snap_time_code_to_prim(empty_prim.GetPrim(), Usd.TimeCode(1.0)), earliest_time)

        invalid_prim = stage.GetPrimAtPath("/Root/NonExistent")
        self.assertEqual(usd_utils.snap_time_code_to_prim(invalid_prim, Usd.TimeCode(1.0)), earliest_time)

    async def test_snap_time_code_to_prims(self):
        stage = Usd.Stage.CreateInMemory()

        dataset1 = cae.DataSet.Define(stage, "/Root/DataSet1")
        field1 = cae.FieldArray.Define(stage, "/Root/DataSet1/Field1")
        attr1 = field1.GetPrim().CreateAttribute("testAttr1", Sdf.ValueTypeNames.Float)
        attr1.Set(10.0, Usd.TimeCode(0.0))
        attr1.Set(20.0, Usd.TimeCode(1.0))
        attr1.Set(30.0, Usd.TimeCode(2.0))
        attr1.Set(40.0, Usd.TimeCode(3.0))
        dataset1.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())

        dataset2 = cae.DataSet.Define(stage, "/Root/DataSet2")
        field2 = cae.FieldArray.Define(stage, "/Root/DataSet2/Field2")
        attr2 = field2.GetPrim().CreateAttribute("testAttr2", Sdf.ValueTypeNames.Float)
        attr2.Set(100.0, Usd.TimeCode(0.5))
        attr2.Set(200.0, Usd.TimeCode(1.5))
        attr2.Set(300.0, Usd.TimeCode(2.5))
        dataset2.GetPrim().CreateRelationship("field:Field2").AddTarget(field2.GetPrim().GetPath())

        dataset3 = cae.DataSet.Define(stage, "/Root/DataSet3")
        field3 = cae.FieldArray.Define(stage, "/Root/DataSet3/Field3")
        attr3 = field3.GetPrim().CreateAttribute("testAttr3", Sdf.ValueTypeNames.Float)
        attr3.Set(1000.0, Usd.TimeCode(1.2))
        attr3.Set(2000.0, Usd.TimeCode(2.2))
        dataset3.GetPrim().CreateRelationship("field:Field3").AddTarget(field3.GetPrim().GetPath())

        await self._attach_stage(stage)

        earliest_time = Usd.TimeCode.EarliestTime()

        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset1.GetPrim(), dataset2.GetPrim(), dataset3.GetPrim()], Usd.TimeCode(1.0)
            ),
            Usd.TimeCode(1.0),
        )
        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset1.GetPrim(), dataset2.GetPrim(), dataset3.GetPrim()], Usd.TimeCode(1.1)
            ),
            Usd.TimeCode(1.0),
        )
        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset1.GetPrim(), dataset2.GetPrim(), dataset3.GetPrim()], Usd.TimeCode(1.3)
            ),
            Usd.TimeCode(1.2),
        )
        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset1.GetPrim(), dataset2.GetPrim(), dataset3.GetPrim()], Usd.TimeCode(0.3)
            ),
            Usd.TimeCode(0.0),
        )
        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset1.GetPrim(), dataset2.GetPrim(), dataset3.GetPrim()], Usd.TimeCode(-1.0)
            ),
            Usd.TimeCode(0.0),
        )
        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset1.GetPrim(), dataset2.GetPrim(), dataset3.GetPrim()], Usd.TimeCode(5.0)
            ),
            Usd.TimeCode(3.0),
        )
        self.assertEqual(usd_utils.snap_time_code_to_prims([], Usd.TimeCode(1.0)), earliest_time)

        invalid_prim = stage.GetPrimAtPath("/Root/NonExistent")
        self.assertEqual(
            usd_utils.snap_time_code_to_prims([dataset1.GetPrim(), invalid_prim], Usd.TimeCode(1.0)),
            Usd.TimeCode(1.0),
        )

        empty_prim = cae.DataSet.Define(stage, "/Root/EmptyDataSet")
        self.assertEqual(usd_utils.snap_time_code_to_prims([empty_prim.GetPrim()], Usd.TimeCode(1.0)), earliest_time)
        self.assertEqual(
            usd_utils.snap_time_code_to_prims([dataset1.GetPrim(), empty_prim.GetPrim()], Usd.TimeCode(1.0)),
            Usd.TimeCode(1.0),
        )

        dataset_mixed = cae.DataSet.Define(stage, "/Root/DataSetMixed")
        field_field = cae.FieldArray.Define(stage, "/Root/DataSetMixed/FieldField")
        field_field_attr = field_field.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.Float)
        field_field_attr.Set(10.0, Usd.TimeCode(1.0))

        coords = cae.FieldArray.Define(stage, "/Root/DataSetMixed/Coords")
        coords_attr = coords.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.Float)
        coords_attr.Set(20.0, Usd.TimeCode(0.5))

        dataset_mixed.GetPrim().CreateRelationship("field:FieldField").AddTarget(field_field.GetPrim().GetPath())
        dataset_mixed.GetPrim().CreateRelationship("coordinates").AddTarget(coords.GetPrim().GetPath())

        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset_mixed.GetPrim()], Usd.TimeCode(1.0), traverse_field_relationships=False
            ),
            Usd.TimeCode(0.5),
        )
        self.assertEqual(
            usd_utils.snap_time_code_to_prims(
                [dataset_mixed.GetPrim()], Usd.TimeCode(1.0), traverse_field_relationships=True
            ),
            Usd.TimeCode(1.0),
        )

    async def test_get_related_data_prims(self):
        stage = Usd.Stage.CreateInMemory()

        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field1 = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        field2 = cae.FieldArray.Define(stage, "/Root/DataSet/Field2")
        field3 = cae.FieldArray.Define(stage, "/Root/DataSet/Field3")

        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())
        field1.GetPrim().CreateRelationship("coordinates").AddTarget(field2.GetPrim().GetPath())
        dataset.GetPrim().CreateRelationship("field:Field3").AddTarget(field3.GetPrim().GetPath())

        await self._attach_stage(stage)

        related = usd_utils.get_related_data_prims(dataset.GetPrim())
        related_paths = {p.GetPath() for p in related}
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
        self.assertIn(field3.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(dataset.GetPrim(), transitive=False, include_self=True)
        related_paths = {p.GetPath() for p in related}
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field3.GetPrim().GetPath(), related_paths)
        self.assertNotIn(field2.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(dataset.GetPrim(), transitive=True, include_self=False)
        related_paths = {p.GetPath() for p in related}
        self.assertNotIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
        self.assertIn(field3.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(dataset.GetPrim(), transitive=False, include_self=False)
        related_paths = {p.GetPath() for p in related}
        self.assertNotIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field3.GetPrim().GetPath(), related_paths)
        self.assertNotIn(field2.GetPrim().GetPath(), related_paths)

        xform = UsdGeom.Xform.Define(stage, "/Root/Xform")
        xform.GetPrim().CreateRelationship("targetDataSet").AddTarget(dataset.GetPrim().GetPath())

        related = usd_utils.get_related_data_prims(xform.GetPrim(), transitive=True, include_self=True)
        related_paths = {p.GetPath() for p in related}
        self.assertIn(xform.GetPrim().GetPath(), related_paths)
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
        self.assertIn(field3.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(xform.GetPrim(), transitive=True, include_self=False)
        related_paths = {p.GetPath() for p in related}
        self.assertNotIn(xform.GetPrim().GetPath(), related_paths)
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
        self.assertIn(field3.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(field1.GetPrim(), transitive=True, include_self=False)
        related_paths = {p.GetPath() for p in related}
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
        self.assertNotIn(field1.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(Usd.Prim())
        self.assertEqual(len(related), 0)

        standalone = cae.FieldArray.Define(stage, "/Root/Standalone")
        related = usd_utils.get_related_data_prims(standalone.GetPrim(), transitive=True, include_self=True)
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0].GetPath(), standalone.GetPrim().GetPath())

        related = usd_utils.get_related_data_prims(standalone.GetPrim(), transitive=True, include_self=False)
        self.assertEqual(len(related), 0)

    async def test_get_related_data_prims_rel_names_filter(self):
        stage = Usd.Stage.CreateInMemory()

        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field1 = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        field2 = cae.FieldArray.Define(stage, "/Root/DataSet/Field2")
        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())
        dataset.GetPrim().CreateRelationship("field:Field2").AddTarget(field2.GetPrim().GetPath())

        await self._attach_stage(stage)

        related = usd_utils.get_related_data_prims(dataset.GetPrim(), rel_names=[])
        related_paths = {p.GetPath() for p in related}
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
        related = usd_utils.get_related_data_prims(dataset.GetPrim(), rel_names=["field:Field1"])
        related_paths = {p.GetPath() for p in related}
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertNotIn(field2.GetPrim().GetPath(), related_paths)

        related = usd_utils.get_related_data_prims(dataset.GetPrim(), rel_names=["nonexistent:rel"])
        related_paths = {p.GetPath() for p in related}
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertNotIn(field1.GetPrim().GetPath(), related_paths)
        self.assertNotIn(field2.GetPrim().GetPath(), related_paths)

        field1.GetPrim().CreateRelationship("extra:link").AddTarget(field2.GetPrim().GetPath())
        related = usd_utils.get_related_data_prims(dataset.GetPrim(), rel_names=["field:Field1"])
        related_paths = {p.GetPath() for p in related}
        self.assertIn(dataset.GetPrim().GetPath(), related_paths)
        self.assertIn(field1.GetPrim().GetPath(), related_paths)
        self.assertIn(field2.GetPrim().GetPath(), related_paths)
