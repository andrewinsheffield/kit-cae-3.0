# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""End-to-end visualization tests for the synthetic axisymmetric FLASH fixture."""

import numpy as np
import omni.kit.test
import warp_simdata as simdata
from omni.cae.core import cache, usd_utils
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path, new_stage, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from pxr import Sdf, Usd, UsdShade, UsdVol
from usdrt import UsdGeom as UsdGeomRt

from .. import slice as slice_module
from ..index_axisymmetric_volume import _state_cache_key
from ._operator_test_utils import read_rt_array, wait_for_operator_complete

_DATASET_PATH = "/World/FlashWavelet"
_FIXTURE_PATH = "FLASH/axisymmetric_wavelet/axisymmetric_wavelet.flash"
_FIELD_NAME = "dens"


def _set_field_names(field_selection_api: cae_viz.FieldSelectionAPI, *names: str) -> None:
    field_selection_api.CreateFieldNamesAttr().Set(list(names))


async def _import_fixture() -> None:
    await import_to_stage(get_test_data_path(_FIXTURE_PATH), _DATASET_PATH)


def _get_active_slice_output(slice_prim: Usd.Prim):
    rt_stage = usd_utils.get_prim_rt(slice_prim).GetStage()
    output_prims = [
        rt_stage.GetPrimAtPath(path) for path in slice_module._output_paths(slice_prim.GetPath().pathString)
    ]
    active = [prim for prim in output_prims if prim and prim.GetAttribute("_worldVisibility").Get()]
    if len(active) != 1:
        raise AssertionError(f"Expected one active planar-slice output, found {len(active)}")
    return active[0]


class TestFlashWaveletVisualizations(omni.kit.test.AsyncTestCase):
    async def test_faces_extract_axisymmetric_surface(self):
        async with new_stage() as stage:
            await _import_fixture()
            faces_path = "/World/CAE/FlashFaces"

            async with wait_for_operator_complete(faces_path, operator="Faces", max_updates=500):
                await execute_command("CreateCaeVizFaces", dataset_path=_DATASET_PATH, prim_path=faces_path)

            faces_prim = stage.GetPrimAtPath(faces_path)
            async with wait_for_operator_complete(faces_path, operator="Faces", max_updates=500):
                _set_field_names(cae_viz.FieldSelectionAPI(faces_prim, "colors"), _FIELD_NAME)

            mesh_rt = UsdGeomRt.Mesh(usd_utils.get_prim_rt(faces_prim))
            points = read_rt_array(mesh_rt.GetPointsAttr(), "FLASH faces points")
            counts = read_rt_array(mesh_rt.GetFaceVertexCountsAttr(), "FLASH face counts")
            indices = read_rt_array(mesh_rt.GetFaceVertexIndicesAttr(), "FLASH face indices")
            colors = read_rt_array(mesh_rt.GetPrim().GetAttribute("primvars:colors"), "FLASH face colors")

            self.assertGreater(points.shape[0], 0)
            self.assertGreater(counts.shape[0], 0)
            self.assertEqual(indices.shape[0], int(counts.sum()))
            self.assertGreater(colors.shape[0], 0)
            np.testing.assert_allclose(points.min(axis=0), [-1.0, -1.0, -1.0], atol=1.0e-5)
            np.testing.assert_allclose(points.max(axis=0), [1.0, 1.0, 1.0], atol=1.0e-5)

    async def test_planar_slice_extracts_dual_flash_mesh(self):
        async with new_stage() as stage:
            await _import_fixture()
            slice_path = "/World/CAE/FlashSlice"

            async with wait_for_operator_complete(
                slice_path,
                operator="PlanarSlice",
                allow_failure=True,
                max_updates=500,
            ):
                await execute_command("CreateCaeVizPlanarSlice", dataset_path=_DATASET_PATH, prim_path=slice_path)

            slice_prim = stage.GetPrimAtPath(slice_path)
            self.assertTrue(slice_prim.HasAPI(cae_viz.DatasetAxisymmetricRepresentationAPI, "source"))
            self.assertTrue(slice_prim.HasAPI(cae_viz.DatasetDualAPI, "source"))

            with Sdf.ChangeBlock():
                cae_viz.DatasetAxisymmetricRepresentationAPI(slice_prim, "source").CreateAngularCellsAttr().Set(8)
                _set_field_names(cae_viz.FieldSelectionAPI(slice_prim, "colors"), _FIELD_NAME)

            async with wait_for_operator_complete(
                slice_path,
                operator="PlanarSlice",
                max_updates=500,
            ):
                cae_viz.PlanarSliceAPI(slice_prim).CreateModeAttr().Set("x")

            output_prim = _get_active_slice_output(slice_prim)
            mesh_rt = UsdGeomRt.Mesh(output_prim)
            points = read_rt_array(mesh_rt.GetPointsAttr(), "FLASH slice points")
            counts = read_rt_array(mesh_rt.GetFaceVertexCountsAttr(), "FLASH slice face counts")
            colors = read_rt_array(output_prim.GetAttribute("primvars:colors"), "FLASH slice colors")

            self.assertGreater(points.shape[0], 0)
            self.assertTrue(np.all(counts == 3))
            self.assertGreater(colors.shape[0], 0)

    async def test_iso_surface_extracts_wavelet_boundary(self):
        async with new_stage() as stage:
            await _import_fixture()
            iso_path = "/World/CAE/FlashIsoSurface"

            async with wait_for_operator_complete(
                iso_path,
                operator="IsoSurface",
                allow_failure=True,
                max_updates=500,
            ):
                await execute_command("CreateCaeVizIsoSurface", dataset_path=_DATASET_PATH, prim_path=iso_path)

            iso_prim = stage.GetPrimAtPath(iso_path)
            with Sdf.ChangeBlock():
                cae_viz.DatasetAxisymmetricRepresentationAPI(iso_prim, "source").CreateAngularCellsAttr().Set(8)
                cae_viz.IsoSurfaceAPI(iso_prim).CreateIsoValueAttr().Set(0.25)
                _set_field_names(cae_viz.FieldSelectionAPI(iso_prim, "contour"), _FIELD_NAME)
                _set_field_names(cae_viz.FieldSelectionAPI(iso_prim, "colors"), _FIELD_NAME)

            async with wait_for_operator_complete(
                iso_path,
                operator="IsoSurface",
                max_updates=500,
            ):
                cae_viz.IsoSurfaceAPI(iso_prim).GetIsoValueAttr().Set(0.3)

            mesh_rt = UsdGeomRt.Mesh(usd_utils.get_prim_rt(iso_prim))
            points = read_rt_array(mesh_rt.GetPointsAttr(), "FLASH iso-surface points")
            counts = read_rt_array(mesh_rt.GetFaceVertexCountsAttr(), "FLASH iso-surface face counts")
            indices = read_rt_array(mesh_rt.GetFaceVertexIndicesAttr(), "FLASH iso-surface indices")

            self.assertGreater(points.shape[0], 0)
            self.assertTrue(np.all(counts == 3))
            self.assertEqual(indices.shape[0], counts.shape[0] * 3)

    async def test_nanovdb_volume_voxelizes_flash_field(self):
        async with new_stage() as stage:
            await _import_fixture()
            volume_path = "/World/CAE/FlashNanoVDB"

            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXVolume",
                allow_failure=True,
                max_updates=500,
            ):
                await execute_command(
                    "CreateCaeVizVolume",
                    dataset_path=_DATASET_PATH,
                    prim_path=volume_path,
                    type="vdb",
                )

            volume_prim = stage.GetPrimAtPath(volume_path)
            with Sdf.ChangeBlock():
                cae_viz.DatasetVoxelizationAPI(volume_prim, "source").CreateMaxResolutionAttr().Set(32)
                _set_field_names(cae_viz.FieldSelectionAPI(volume_prim, "colors"), _FIELD_NAME)

            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXVolume",
                max_updates=1000,
            ) as completion:
                cae_viz.DatasetVoxelizationAPI(volume_prim, "source").GetMaxResolutionAttr().Set(31)

            dataset = cache.get(
                f"[viz:index_volume]::{volume_prim.GetPath()}",
                timeCode=Usd.TimeCode(completion.result["timecode"]),
            )
            self.assertIsInstance(dataset, simdata.Dataset)
            self.assertEqual(dataset.data_model, simdata.data_models.vtk.image_data.DataModel)
            self.assertIn("colors", dataset.get_field_names())
            self.assertIn("cae_mask", dataset.get_field_names())
            self.assertEqual(volume_prim.GetAttribute("nvindex:type").Get(), "vdb")

    async def test_irregular_volume_preserves_flash_mesh(self):
        async with new_stage() as stage:
            await _import_fixture()
            volume_path = "/World/CAE/FlashIrregularVolume"

            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXVolume",
                allow_failure=True,
                max_updates=500,
            ):
                await execute_command(
                    "CreateCaeVizVolume",
                    dataset_path=_DATASET_PATH,
                    prim_path=volume_path,
                    type="irregular",
                )

            volume_prim = stage.GetPrimAtPath(volume_path)
            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXVolume",
                max_updates=1000,
            ) as completion:
                _set_field_names(cae_viz.FieldSelectionAPI(volume_prim, "colors"), _FIELD_NAME)

            dataset = cache.get(
                f"[viz:index_volume]::{volume_prim.GetPath()}",
                timeCode=Usd.TimeCode(completion.result["timecode"]),
            )
            self.assertIsInstance(dataset, simdata.Dataset)
            self.assertNotEqual(dataset.data_model, simdata.data_models.vtk.image_data.DataModel)
            self.assertIn("colors", dataset.get_field_names())
            self.assertGreater(dataset.get_num_elems(), 0)
            self.assertEqual(volume_prim.GetAttribute("nvindex:type").Get(), "irregular_volume")
            self.assertTrue(UsdVol.Volume(volume_prim).GetFieldPaths())

    async def test_direct_axisymmetric_volume_builds_native_levels(self):
        async with new_stage() as stage:
            from omni.timeline import get_timeline_interface

            stage.SetTimeCodesPerSecond(1.0)
            timeline = get_timeline_interface()
            timeline.set_time_codes_per_second(1.0)
            timeline.set_current_time(0.0)
            await wait_for_update()

            await _import_fixture()
            volume_path = "/World/CAE/FlashAxisymmetricVolume"

            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXAxisymmetricVolume",
                allow_failure=True,
                max_updates=500,
            ):
                await execute_command(
                    "CreateCaeVizVolume",
                    dataset_path=_DATASET_PATH,
                    prim_path=volume_path,
                    type="axisymmetric",
                )

            volume_prim = stage.GetPrimAtPath(volume_path)
            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXAxisymmetricVolume",
                max_updates=1000,
            ) as completion:
                _set_field_names(cae_viz.FieldSelectionAPI(volume_prim, "colors"), _FIELD_NAME)

            state = cache.get(
                _state_cache_key(str(volume_prim.GetPath())),
                timeCode=Usd.TimeCode(completion.result["timecode"]),
            )
            self.assertIsNotNone(state)
            self.assertEqual(len(state.spec.levels), 2)
            self.assertAlmostEqual(state.spec.native_spacing, 1.0 / 64.0)
            self.assertEqual(
                cae_viz.IndeXAxisymmetricVolumeAPI(volume_prim).GetSamplingDistanceScaleAttr().Get(),
                1.0,
            )
            self.assertEqual(volume_prim.GetAttribute("nvindex:type").Get(), "vdb")

            last_time = stage.GetEndTimeCode()
            self.assertGreater(last_time, 0.0)
            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXAxisymmetricVolume",
                max_updates=1000,
            ) as last_completion:
                timeline.set_current_time(last_time)

            last_state = cache.get(
                _state_cache_key(str(volume_prim.GetPath())),
                timeCode=Usd.TimeCode(last_completion.result["timecode"]),
            )
            self.assertIsNotNone(last_state)
            self.assertEqual(len(last_state.spec.levels), 4)
            self.assertAlmostEqual(last_state.spec.native_spacing, 1.0 / 256.0)

            async with wait_for_operator_complete(
                volume_path,
                operator="IndeXAxisymmetricVolume",
                max_updates=1000,
            ):
                timeline.set_current_time(0.0)

            restored_state = cache.get(
                _state_cache_key(str(volume_prim.GetPath())),
                timeCode=Usd.TimeCode(completion.result["timecode"]),
            )
            self.assertIs(restored_state, state)
            loader = UsdShade.Shader(volume_prim.GetChild("Material").GetChild("DataLoader"))
            self.assertEqual(loader.GetInput("params_generation").Get(), state.generation)
