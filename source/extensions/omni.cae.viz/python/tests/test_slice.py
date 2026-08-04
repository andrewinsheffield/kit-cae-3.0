# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from unittest.mock import patch

import numpy as np
import omni.kit.test
from omni.cae.core import usd_utils
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path, new_stage
from omni.cae.usd_plugins_importers import import_to_stage
from omni.cae.viz import slice as slice_module
from pxr import Gf, Usd, UsdGeom, UsdShade
from usdrt import Rt
from usdrt import UsdGeom as UsdGeomRt

from ._operator_test_utils import read_rt_array, wait_for_operator_complete

_STATIC_MIXER_DATASET_PATH = "/World/StaticMixer/Base/StaticMixer/B1_P3"


def _set_field_names(field_selection_api: cae_viz.FieldSelectionAPI, *names: str) -> None:
    field_selection_api.CreateFieldNamesAttr().Set(list(names))


def _get_active_output_prims(slice_prim: Usd.Prim):
    rt_stage = usd_utils.get_prim_rt(slice_prim).GetStage()
    active = []
    for path in slice_module._output_paths(slice_prim.GetPath().pathString):
        output_prim = rt_stage.GetPrimAtPath(path)
        if output_prim and output_prim.GetAttribute("_worldVisibility").Get():
            active.append(output_prim)
    return active


def _get_active_output_prim(slice_prim: Usd.Prim):
    active = _get_active_output_prims(slice_prim)
    if len(active) != 1:
        raise AssertionError(f"Expected one active planar-slice output, found {len(active)}")
    return active[0]


class TestSlicePureFunctions(omni.kit.test.AsyncTestCase):
    def test_compute_plane_identity(self):
        origin, normal = slice_module._compute_plane(np.eye(4))
        np.testing.assert_allclose(origin, [0, 0, 0], atol=1e-7)
        np.testing.assert_allclose(normal, [0, 1, 0], atol=1e-7)

    def test_compute_plane_translation(self):
        transform = np.eye(4)
        transform[3, :3] = [3.0, 4.0, 5.0]
        origin, normal = slice_module._compute_plane(transform)
        np.testing.assert_allclose(origin, [3, 4, 5], atol=1e-7)
        np.testing.assert_allclose(normal, [0, 1, 0], atol=1e-7)

    def test_compute_plane_normal_is_normalized(self):
        transform = np.eye(4)
        transform[1, :3] = [1.0, 2.0, 3.0]
        _, normal = slice_module._compute_plane(transform)
        np.testing.assert_allclose(np.linalg.norm(normal), 1.0, atol=1e-7)

    def test_compute_plane_rejects_degenerate_normal(self):
        transform = np.eye(4)
        transform[1, :3] = 0.0
        with self.assertRaises(usd_utils.QuietableException):
            slice_module._compute_plane(transform)


class TestPlanarSlice(omni.kit.test.AsyncTestCase):
    async def _create_slice_from_dataset(self, stage: Usd.Stage, slice_path: str) -> Usd.Prim:
        async with wait_for_operator_complete(slice_path, operator="PlanarSlice", allow_failure=True):
            await execute_command(
                "CreateCaeVizPlanarSlice",
                dataset_path=_STATIC_MIXER_DATASET_PATH,
                prim_path=slice_path,
            )

        slice_prim = stage.GetPrimAtPath(slice_path)
        async with wait_for_operator_complete(slice_path, operator="PlanarSlice"):
            _set_field_names(cae_viz.FieldSelectionAPI(slice_prim, "colors"), "Temperature")
        return slice_prim

    async def _create_slice(self, stage: Usd.Stage, slice_path: str) -> Usd.Prim:
        await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
        return await self._create_slice_from_dataset(stage, slice_path)

    async def test_planar_slice_extracts_colored_triangle_mesh(self):
        async with new_stage() as stage:
            slice_prim = await self._create_slice(stage, "/World/CAE/PlanarSlice_Test")

            self.assertTrue(slice_prim.HasAPI(cae_viz.PlanarSliceAPI))
            self.assertFalse(slice_prim.HasAttribute("cae:viz:planarSlice:textureResolution"))
            self.assertEqual(cae_viz.PlanarSliceAPI(slice_prim).GetModeAttr().Get(), "free")

            output_prim = _get_active_output_prim(slice_prim)
            mesh_rt = UsdGeomRt.Mesh(output_prim)
            self.assertTrue(mesh_rt.GetDoubleSidedAttr().Get())
            self.assertEqual(
                [str(path) for path in output_prim.GetRelationship("material:binding").GetTargets()],
                [f"{slice_prim.GetPath()}/Materials/UnlitScalarColor"],
            )
            points = read_rt_array(mesh_rt.GetPointsAttr(), "slice points")
            counts = read_rt_array(mesh_rt.GetFaceVertexCountsAttr(), "slice face counts")
            indices = read_rt_array(mesh_rt.GetFaceVertexIndicesAttr(), "slice face indices")
            colors_primvar = UsdGeomRt.PrimvarsAPI(output_prim).GetPrimvar("colors")
            colors = read_rt_array(colors_primvar.GetAttr(), "slice colors")

            self.assertGreater(points.shape[0], 3)
            self.assertGreater(counts.shape[0], 0)
            np.testing.assert_array_equal(counts, np.full(counts.shape, 3))
            self.assertEqual(indices.shape[0], counts.shape[0] * 3)
            expected_color_count = points.shape[0] if colors_primvar.GetInterpolation() == "vertex" else counts.shape[0]
            self.assertEqual(colors.shape[0], expected_color_count)

    async def test_planar_slice_interpolates_independent_opacity_and_preserves_its_lut(self):
        async with new_stage() as stage:
            slice_prim = await self._create_slice(stage, "/World/CAE/PlanarSlice_Opacity")
            shader = UsdShade.Shader(slice_prim.GetPrimAtPath("Materials/UnlitScalarColor/Shader"))
            opacity_lut = shader.GetInput("opacity_lut")
            opacity_lut.Set("dynamic://cae_opacitymap_test")

            async with wait_for_operator_complete(slice_prim.GetPath().pathString, operator="PlanarSlice"):
                _set_field_names(cae_viz.FieldSelectionAPI(slice_prim, "opacity"), "Temperature")

            output_prim = _get_active_output_prim(slice_prim)
            opacity_primvar = UsdGeomRt.PrimvarsAPI(output_prim).GetPrimvar("opacity")
            opacity = read_rt_array(opacity_primvar.GetAttr(), "slice opacity")

            self.assertGreater(opacity.shape[0], 0)
            self.assertEqual(opacity.shape[1], 1)
            self.assertEqual(opacity_lut.Get().path, "dynamic://cae_opacitymap_test")
            self.assertTrue(shader.GetInput("enable_opacity").Get())
            opacity_domain = shader.GetInput("opacity_domain").Get()
            self.assertLess(opacity_domain[0], opacity_domain[1])

    async def test_create_authors_dual_for_supported_dataset(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            dataset_path = "/World/StaticMixer/Base/StaticMixer/B1_P3"
            slice_path = "/World/CAE/PlanarSlice_Dual_Default"

            with patch("omni.cae.viz.create_commands.cae_simdata.supports_dual_representation", return_value=True):
                async with wait_for_operator_complete(slice_path, operator="PlanarSlice", allow_failure=True):
                    await execute_command("CreateCaeVizPlanarSlice", dataset_path=dataset_path, prim_path=slice_path)

            prim = stage.GetPrimAtPath(slice_path)
            self.assertTrue(prim.HasAPI(cae_viz.DatasetAxisymmetricRepresentationAPI, "source"))
            self.assertTrue(prim.HasAPI(cae_viz.DatasetDualAPI, "source"))

    async def test_interactive_move_publishes_transformed_alternate_buffer(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")

            cae_parent = UsdGeom.Xform.Define(stage, "/World/CAE")
            parent_xform = UsdGeom.Xformable(cae_parent.GetPrim())
            parent_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 250.0, 32.0))
            parent_xform.AddRotateZOp().Set(-90.0)
            parent_xform.AddScaleOp().Set(Gf.Vec3d(100.0, 100.0, 100.0))
            parent_transform = UsdGeom.XformCache().GetLocalToWorldTransform(cae_parent.GetPrim())

            def assert_spatial_metadata(output_prim, points):
                boundable = Rt.Boundable(output_prim)
                np.testing.assert_allclose(
                    np.asarray(boundable.GetFabricHierarchyLocalMatrixAttr().Get()),
                    np.asarray(parent_transform),
                    atol=1e-8,
                )
                np.testing.assert_allclose(
                    np.asarray(boundable.GetFabricHierarchyWorldMatrixAttr().Get()),
                    np.asarray(parent_transform),
                    atol=1e-8,
                )

                local_min = (float(value) for value in points.min(axis=0))
                local_max = (float(value) for value in points.max(axis=0))
                local_extent = Gf.Range3d(Gf.Vec3d(*local_min), Gf.Vec3d(*local_max))
                expected_world_extent = Gf.BBox3d(local_extent, parent_transform).ComputeAlignedRange()
                actual_world_extent = boundable.GetWorldExtentAttr().Get()
                np.testing.assert_allclose(
                    actual_world_extent.GetMin(),
                    expected_world_extent.GetMin(),
                    atol=1e-3,
                )
                np.testing.assert_allclose(
                    actual_world_extent.GetMax(),
                    expected_world_extent.GetMax(),
                    atol=1e-3,
                )

            slice_prim = await self._create_slice_from_dataset(stage, "/World/CAE/PlanarSlice_Move")
            first_output = _get_active_output_prim(slice_prim)
            first_points = read_rt_array(UsdGeomRt.Mesh(first_output).GetPointsAttr(), "first slice points").copy()
            assert_spatial_metadata(first_output, first_points)

            xformable = UsdGeom.Xformable(slice_prim)
            translate_op = xformable.GetOrderedXformOps()[0]
            initial_translation = translate_op.Get()
            moved_translation = Gf.Vec3d(
                initial_translation[0],
                initial_translation[1] + 0.05,
                initial_translation[2],
            )
            async with wait_for_operator_complete(slice_prim.GetPath().pathString, operator="PlanarSlice"):
                translate_op.Set(moved_translation)

            second_output = _get_active_output_prim(slice_prim)
            second_points = read_rt_array(UsdGeomRt.Mesh(second_output).GetPointsAttr(), "second slice points")

            self.assertNotEqual(first_output.GetPath(), second_output.GetPath())
            self.assertGreater(first_points.shape[0], 0)
            self.assertGreater(second_points.shape[0], 0)
            np.testing.assert_allclose(second_points[:, 1], moved_translation[1], atol=1e-4)
            assert_spatial_metadata(first_output, first_points)
            assert_spatial_metadata(second_output, second_points)

    async def test_direction_mode_extracts_axis_aligned_planes(self):
        async with new_stage() as stage:
            slice_prim = await self._create_slice(stage, "/World/CAE/PlanarSlice_Directions")
            mode_attr = cae_viz.PlanarSliceAPI(slice_prim).GetModeAttr()

            with patch.object(
                slice_module.simdata_slice,
                "compute_many",
                wraps=slice_module.simdata_slice.compute_many,
            ) as compute_many:
                async with wait_for_operator_complete(slice_prim.GetPath().pathString, operator="PlanarSlice"):
                    mode_attr.Set("xyz")

            rt_stage = usd_utils.get_prim_rt(slice_prim).GetStage()
            center = UsdGeom.Xformable(slice_prim).GetOrderedXformOps()[0].Get()
            active_outputs = _get_active_output_prims(slice_prim)
            self.assertEqual(compute_many.call_count, 1)
            self.assertEqual(np.asarray(compute_many.call_args.kwargs["origins"]).shape, (3, 3))
            self.assertEqual(np.asarray(compute_many.call_args.kwargs["normals"]).shape, (3, 3))
            self.assertEqual(len(active_outputs), 3)

            for plane_slot, axis_index in enumerate(range(3)):
                output_prims = [
                    rt_stage.GetPrimAtPath(
                        slice_module._output_path(
                            slice_prim.GetPath().pathString,
                            plane_slot,
                            buffer_slot,
                        )
                    )
                    for buffer_slot in range(slice_module._OUTPUT_BUFFER_COUNT)
                ]
                active_plane_outputs = [
                    output_prim
                    for output_prim in output_prims
                    if output_prim and output_prim.GetAttribute("_worldVisibility").Get()
                ]
                self.assertEqual(len(active_plane_outputs), 1)
                points = read_rt_array(
                    UsdGeomRt.Mesh(active_plane_outputs[0]).GetPointsAttr(),
                    f"axis {axis_index} slice points",
                )
                np.testing.assert_allclose(points[:, axis_index], center[axis_index], atol=1e-4)
