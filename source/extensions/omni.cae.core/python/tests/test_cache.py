# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import logging

import carb.settings
import omni.kit.app
import omni.kit.test
import omni.usd
from omni.cae.core import cache
from omni.cae.core import settings as cae_settings
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from pxr import Sdf, Usd, UsdGeom

logger = logging.getLogger(__name__)


class TestCache(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        cache._initialize()
        settings = carb.settings.get_settings()
        self._cache_mode_key = cae_settings.SettingsKeys.CACHE_MODE
        self._original_cache_mode = settings.get_as_string(self._cache_mode_key)
        settings.set_string(self._cache_mode_key, "always")

    async def tearDown(self):
        settings = carb.settings.get_settings()
        settings.set_string(self._cache_mode_key, self._original_cache_mode)
        cache.clear()
        cache._finalize()
        ctx = omni.usd.get_context()
        if ctx.get_stage():
            ctx.close_stage()

    async def _attach_stage(self, stage):
        await omni.usd.get_context().attach_stage_async(stage)

    async def _next_frame(self):
        await omni.kit.app.get_app().next_update_async()

    async def test_source_prim_field_array_modification_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field_array = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field_array.GetPrim().GetPath())

        await self._attach_stage(stage)

        cache_key = "test_key_1"
        test_data = {"value": 42}
        cache.put(cache_key, test_data, sourcePrims=[dataset.GetPrim()], consumerPrims=[], force=True)

        self.assertEqual(cache.get(cache_key), test_data)

        field_array.CreateFileNamesAttr().Set(["/some/path/to/file"])

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_source_prim_field_array_property_change_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field_array = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field_array.GetPrim().GetPath())

        await self._attach_stage(stage)

        cache_key = "test_key_2"
        test_data = {"value": 100}
        cache.put(cache_key, test_data, sourcePrims=[dataset.GetPrim()], consumerPrims=[], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        attr = field_array.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.Float)
        attr.Set(123.0)

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_consumer_prim_property_change_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        consumer_prim = UsdGeom.Xform.Define(stage, "/Root/Consumer")

        await self._attach_stage(stage)

        cache_key = "test_key_3"
        test_data = {"value": 200}
        cache.put(cache_key, test_data, sourcePrims=[], consumerPrims=[consumer_prim.GetPrim()], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        consumer_prim.AddTranslateOp().Set((1.0, 2.0, 3.0))

        await self._next_frame()

        self.assertEqual(cache.get(cache_key), test_data)

    async def test_consumer_prim_resync_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        consumer_prim = UsdGeom.Mesh.Define(stage, "/Root/Consumer")

        await self._attach_stage(stage)

        cache_key = "test_key_4"
        test_data = {"value": 300}
        cache.put(cache_key, test_data, sourcePrims=[], consumerPrims=[consumer_prim.GetPrim()], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        cae_viz.FacesAPI.Apply(consumer_prim.GetPrim())

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_consumer_prim_deletion_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        consumer_prim = UsdGeom.Xform.Define(stage, "/Root/Consumer")

        await self._attach_stage(stage)

        cache_key = "test_key_5"
        test_data = {"value": 400}
        cache.put(cache_key, test_data, sourcePrims=[], consumerPrims=[consumer_prim.GetPrim()], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        stage.RemovePrim(consumer_prim.GetPrim().GetPath())

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_source_prim_resync_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")

        await self._attach_stage(stage)

        cache_key = "test_key_6"
        test_data = {"value": 500}
        cache.put(cache_key, test_data, sourcePrims=[dataset.GetPrim()], consumerPrims=[], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        cae_viz.DatasetSelectionAPI.Apply(dataset.GetPrim(), "foo")

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_source_prim_property_change_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")

        await self._attach_stage(stage)

        cache_key = "test_key_7"
        test_data = {"value": 600}
        cache.put(cache_key, test_data, sourcePrims=[dataset.GetPrim()], consumerPrims=[], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        attr = dataset.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.String)
        attr.Set("test_value")

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_multiple_source_prims_one_change_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        dataset1 = cae.DataSet.Define(stage, "/Root/DataSet1")
        dataset2 = cae.DataSet.Define(stage, "/Root/DataSet2")

        await self._attach_stage(stage)

        cache_key = "test_key_8"
        test_data = {"value": 700}
        cache.put(cache_key, test_data, sourcePrims=[dataset1.GetPrim(), dataset2.GetPrim()], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        attr = dataset1.GetPrim().CreateAttribute("testAttr", Sdf.ValueTypeNames.Float)
        attr.Set(123.0)

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_watch_added_during_notice_is_deferred(self):
        stage = Usd.Stage.CreateInMemory()
        await self._attach_stage(stage)

        added_prim = UsdGeom.Xform.Define(stage, "/Root/Added").GetPrim()

        class MutatingPrim:
            def GetPath(self):
                cache._watches[added_prim] = {}
                return Sdf.Path("/Root/Mutating")

        class EmptyNotice:
            def GetChangedInfoOnlyPaths(self):
                return []

            def GetResyncedPaths(self):
                return []

        cache._watches = {MutatingPrim(): {"key": [None]}}

        cache._listener.on_objects_changed(EmptyNotice(), stage)

        self.assertIn(added_prim, cache._watches)

    async def test_multiple_consumer_prims_one_resync_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        consumer1 = UsdGeom.Mesh.Define(stage, "/Root/Consumer1")
        consumer2 = UsdGeom.Mesh.Define(stage, "/Root/Consumer2")

        await self._attach_stage(stage)

        cache_key = "test_key_9"
        test_data = {"value": 800}
        cache.put(cache_key, test_data, consumerPrims=[consumer1.GetPrim(), consumer2.GetPrim()], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        cae_viz.FacesAPI.Apply(consumer1.GetPrim())

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_field_array_relationship_target_modification_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field_array = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field_array.GetPrim().GetPath())

        await self._attach_stage(stage)

        cache_key = "test_key_10"
        test_data = {"value": 900}
        cache.put(cache_key, test_data, sourcePrims=[dataset.GetPrim()], force=True)

        self.assertIsNotNone(cache.get(cache_key))

        field_array.CreateFileNamesAttr().Set(["/modified/path"])

        await self._next_frame()

        self.assertIsNone(cache.get(cache_key))

    async def test_put_ex_any_mode_property_update_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        field_array = cae.FieldArray.Define(stage, "/Root/Field")

        await self._attach_stage(stage)

        key = "ex_any_update"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(field_array.GetPrim(), on="any")], force=True)
        self.assertIsNotNone(cache.get(key))

        field_array.CreateFileNamesAttr().Set(["/a/path"])

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_any_mode_structural_resync_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")

        await self._attach_stage(stage)

        key = "ex_any_resync"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(mesh.GetPrim(), on="any")], force=True)
        self.assertIsNotNone(cache.get(key))

        cae_viz.FacesAPI.Apply(mesh.GetPrim())

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_update_mode_property_change_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        field_array = cae.FieldArray.Define(stage, "/Root/Field")

        await self._attach_stage(stage)

        key = "ex_update_prop"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(field_array.GetPrim(), on="update")], force=True)
        self.assertIsNotNone(cache.get(key))

        field_array.CreateFileNamesAttr().Set(["/a/path"])

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_update_mode_structural_resync_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")

        await self._attach_stage(stage)

        key = "ex_update_resync"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(mesh.GetPrim(), on="update")], force=True)
        self.assertIsNotNone(cache.get(key))

        cae_viz.FacesAPI.Apply(mesh.GetPrim())

        await self._next_frame()

        self.assertIsNotNone(cache.get(key))

    async def test_put_ex_resync_mode_property_change_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        xform = UsdGeom.Xform.Define(stage, "/Root/Xform")

        await self._attach_stage(stage)

        key = "ex_resync_prop"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(xform.GetPrim(), on="resync")], force=True)
        self.assertIsNotNone(cache.get(key))

        xform.AddTranslateOp().Set((1.0, 2.0, 3.0))

        await self._next_frame()

        self.assertIsNotNone(cache.get(key))

    async def test_put_ex_resync_mode_structural_resync_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")

        await self._attach_stage(stage)

        key = "ex_resync_resync"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(mesh.GetPrim(), on="resync")], force=True)
        self.assertIsNotNone(cache.get(key))

        cae_viz.FacesAPI.Apply(mesh.GetPrim())

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_delete_mode_property_change_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        xform = UsdGeom.Xform.Define(stage, "/Root/Xform")

        await self._attach_stage(stage)

        key = "ex_delete_prop"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(xform.GetPrim(), on="delete")], force=True)
        self.assertIsNotNone(cache.get(key))

        xform.AddTranslateOp().Set((1.0, 2.0, 3.0))

        await self._next_frame()

        self.assertIsNotNone(cache.get(key))

    async def test_put_ex_delete_mode_resync_without_deletion_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")

        await self._attach_stage(stage)

        key = "ex_delete_resync_no_del"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(mesh.GetPrim(), on="delete")], force=True)
        self.assertIsNotNone(cache.get(key))

        cae_viz.FacesAPI.Apply(mesh.GetPrim())

        await self._next_frame()

        self.assertIsNotNone(cache.get(key))

    async def test_put_ex_delete_mode_prim_deletion_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        xform = UsdGeom.Xform.Define(stage, "/Root/Xform")

        await self._attach_stage(stage)

        key = "ex_delete_deleted"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(xform.GetPrim(), on="delete")], force=True)
        self.assertIsNotNone(cache.get(key))

        stage.RemovePrim(xform.GetPrim().GetPath())

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_schema_filter_matching_property_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        field_array = cae.FieldArray.Define(stage, "/Root/Field")

        await self._attach_stage(stage)

        key = "ex_schema_match"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(field_array.GetPrim(), on="update", schemas=[cae.FieldArray])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        field_array.CreateFileNamesAttr().Set(["/changed/path"])

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_schema_filter_non_matching_property_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        field_array = cae.FieldArray.Define(stage, "/Root/Field")

        await self._attach_stage(stage)

        key = "ex_schema_no_match"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(field_array.GetPrim(), on="update", schemas=[cae.FieldArray])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        field_array.GetPrim().CreateAttribute("customAttr", Sdf.ValueTypeNames.Float).Set(99.0)

        await self._next_frame()

        self.assertIsNotNone(cache.get(key))

    async def test_put_ex_schema_filter_any_mode_resync_still_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        field_array = cae.FieldArray.Define(stage, "/Root/Field")

        await self._attach_stage(stage)

        key = "ex_schema_any_resync"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(field_array.GetPrim(), on="any", schemas=[cae.FieldArray])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        cae_viz.DatasetSelectionAPI.Apply(field_array.GetPrim(), "bar")

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_schema_filter_string_name(self):
        stage = Usd.Stage.CreateInMemory()
        field_array = cae.FieldArray.Define(stage, "/Root/Field")

        await self._attach_stage(stage)

        key = "ex_schema_str"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(field_array.GetPrim(), on="update", schemas=["CaeFieldArray"])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        field_array.CreateFileNamesAttr().Set(["/str/path"])

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_multi_apply_tuple_matching_instance_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")
        cae_viz.DatasetTransformingAPI.Apply(mesh.GetPrim(), "source")

        await self._attach_stage(stage)

        key = "ex_multi_tuple_match"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(mesh.GetPrim(), on="update", schemas=[(cae_viz.DatasetTransformingAPI, "source")])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        mesh.GetPrim().GetAttribute("cae:viz:dataset_transforming:source:useGlobalTransform").Set(True)

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_put_ex_multi_apply_tuple_other_instance_does_not_drop_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")
        cae_viz.DatasetTransformingAPI.Apply(mesh.GetPrim(), "source")
        cae_viz.DatasetTransformingAPI.Apply(mesh.GetPrim(), "other")

        await self._attach_stage(stage)

        key = "ex_multi_tuple_other"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(mesh.GetPrim(), on="update", schemas=[(cae_viz.DatasetTransformingAPI, "source")])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        mesh.GetPrim().GetAttribute("cae:viz:dataset_transforming:other:useGlobalTransform").Set(True)

        await self._next_frame()

        self.assertIsNotNone(cache.get(key))

    async def test_put_ex_multi_apply_string_qualified_drops_cache(self):
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/Root/Mesh")
        cae_viz.DatasetTransformingAPI.Apply(mesh.GetPrim(), "source")

        await self._attach_stage(stage)

        key = "ex_multi_str_qual"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(mesh.GetPrim(), on="update", schemas=["CaeVizDatasetTransformingAPI:source"])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        mesh.GetPrim().GetAttribute("cae:viz:dataset_transforming:source:useGlobalTransform").Set(True)

        await self._next_frame()

        self.assertIsNone(cache.get(key))


class TestPutExExpansion(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        cache._initialize()
        settings = carb.settings.get_settings()
        self._cache_mode_key = cae_settings.SettingsKeys.CACHE_MODE
        self._original_cache_mode = settings.get_as_string(self._cache_mode_key)
        settings.set_string(self._cache_mode_key, "always")

    async def tearDown(self):
        settings = carb.settings.get_settings()
        settings.set_string(self._cache_mode_key, self._original_cache_mode)
        cache.clear()
        cache._finalize()
        ctx = omni.usd.get_context()
        if ctx.get_stage():
            ctx.close_stage()

    async def _attach_stage(self, stage):
        await omni.usd.get_context().attach_stage_async(stage)

    async def _next_frame(self):
        await omni.kit.app.get_app().next_update_async()

    async def test_field_array_property_change_invalidates_dataset_watch(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field.GetPrim().GetPath())

        await self._attach_stage(stage)

        key = "expansion_field_change"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(dataset.GetPrim())], force=True)
        self.assertIsNotNone(cache.get(key))

        field.CreateFileNamesAttr().Set(["/new/file.dat"])

        await self._next_frame()

        self.assertIsNone(cache.get(key))

    async def test_expansion_respects_on_mode_resync(self):
        stage = Usd.Stage.CreateInMemory()
        dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        field = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field.GetPrim().GetPath())

        await self._attach_stage(stage)

        key = "expansion_resync_mode"
        cache.put_ex(key, {"v": 1}, prims=[cache.PrimWatch(dataset.GetPrim(), on="resync")], force=True)
        self.assertIsNotNone(cache.get(key))

        field.CreateFileNamesAttr().Set(["/new/file.dat"])
        await self._next_frame()
        self.assertIsNotNone(cache.get(key))

        cae_viz.FacesAPI.Apply(field.GetPrim())
        await self._next_frame()
        self.assertIsNone(cache.get(key))

    async def test_schema_filtered_watch_on_operator_prim_is_noop_expansion(self):
        stage = Usd.Stage.CreateInMemory()
        op_prim = UsdGeom.Xform.Define(stage, "/Root/OpPrim").GetPrim()
        cae_viz.DatasetSelectionAPI.Apply(op_prim, "inst0")

        await self._attach_stage(stage)

        key = "expansion_noop_op_prim"
        cache.put_ex(
            key,
            {"v": 1},
            prims=[cache.PrimWatch(op_prim, on="any", schemas=[(cae_viz.DatasetSelectionAPI, "inst0")])],
            force=True,
        )
        self.assertIsNotNone(cache.get(key))

        ds_api = cae_viz.DatasetSelectionAPI(op_prim, "inst0")
        ds_api.GetTargetRel().ClearTargets(True)

        await self._next_frame()

        self.assertIsNone(cache.get(key))
