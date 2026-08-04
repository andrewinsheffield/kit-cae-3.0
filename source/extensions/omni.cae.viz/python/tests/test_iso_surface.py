# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from unittest import mock

import numpy as np
import omni.kit.test
from omni.cae.core import usd_utils
from omni.cae.core.commands import execute_command
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path, new_stage
from omni.cae.usd_plugins_importers import import_to_stage
from omni.cae.viz import utils
from pxr import OmniSci, Usd
from usdrt import UsdGeom as UsdGeomRT
from warp_simdata.operators import iso_surface as simdata_iso_surface

from ..execution_context import ExecutionContext, ExecutionReason
from ..iso_surface import IsoSurface
from ._operator_test_utils import read_rt_array, wait_for_operator_complete


def _set_field_names(field_selection_api: cae_viz.FieldSelectionAPI, *names: str) -> None:
    field_selection_api.CreateFieldNamesAttr().Set(list(names))


class TestIsoSurface(omni.kit.test.AsyncTestCase):
    async def test_iso_surface_consumes_derived_contour_field(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("hex_timesteps.cgns"), "/World/hex_timesteps")
            dataset_path = "/World/hex_timesteps/Base/Zone/ElementsUniform"
            field_prim = next(prim for prim in stage.Traverse() if prim.HasAPI(OmniSci.FieldAPI, "CellSinusoid"))
            expression = cae.ArrayExpressionAPI.Apply(field_prim, "derived_contour")
            expression.CreateExpressionAttr("CellSinusoid * 1")

            iso_path = "/World/CAE/IsoSurface_Derived"
            async with wait_for_operator_complete(iso_path, operator="IsoSurface", allow_failure=True):
                await execute_command("CreateCaeVizIsoSurface", dataset_path=dataset_path, prim_path=iso_path)

            prim = stage.GetPrimAtPath(iso_path)
            # Materializing the first CPU expression can compile multiple Warp
            # kernels. Give slower CI workers enough update cycles to publish
            # the completion event.
            async with wait_for_operator_complete(iso_path, operator="IsoSurface", max_updates=500):
                cae_viz.OperatorAPI(prim).CreateDeviceAttr().Set("cpu")
                _set_field_names(cae_viz.FieldSelectionAPI(prim, "contour"), "derived_contour")

            mesh_rt = UsdGeomRT.Mesh(usd_utils.get_prim_rt(prim))
            points = read_rt_array(mesh_rt.GetPointsAttr(), "derived iso-surface points")
            self.assertGreater(points.size, 0)

    async def test_cell_field_iso_surface_and_cached_reconstruction(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("hex_timesteps.cgns"), "/World/hex_timesteps")
            dataset_path = "/World/hex_timesteps/Base/Zone/ElementsUniform"
            iso_path = "/World/CAE/IsoSurface_Test"

            async with wait_for_operator_complete(iso_path, operator="IsoSurface", allow_failure=True):
                await execute_command("CreateCaeVizIsoSurface", dataset_path=dataset_path, prim_path=iso_path)

            prim: Usd.Prim = stage.GetPrimAtPath(iso_path)
            self.assertTrue(prim.IsValid())
            self.assertTrue(prim.HasAPI(cae_viz.IsoSurfaceAPI))
            self.assertFalse(prim.HasAPI(cae_viz.DatasetAxisymmetricRepresentationAPI, "source"))
            self.assertFalse(prim.HasAPI(cae_viz.DatasetDualAPI, "source"))
            self.assertEqual(cae_viz.IsoSurfaceAPI(prim).GetIsoValueAttr().Get(), 0.0)

            async with wait_for_operator_complete(iso_path, operator="IsoSurface") as completion:
                cae_viz.OperatorAPI(prim).CreateDeviceAttr().Set("cpu")
                _set_field_names(cae_viz.FieldSelectionAPI(prim, "contour"), "CellSinusoid")
                _set_field_names(cae_viz.FieldSelectionAPI(prim, "colors"), "CellSinusoid")

            prim_rt = usd_utils.get_prim_rt(prim)
            mesh_rt = UsdGeomRT.Mesh(prim_rt)
            points = read_rt_array(mesh_rt.GetPointsAttr(), "iso-surface points")
            face_counts = read_rt_array(mesh_rt.GetFaceVertexCountsAttr(), "iso-surface face counts")
            face_indices = read_rt_array(mesh_rt.GetFaceVertexIndicesAttr(), "iso-surface face indices")
            colors = read_rt_array(prim_rt.GetAttribute("primvars:colors"), "iso-surface colors")

            self.assertTrue(np.all(face_counts == 3))
            self.assertEqual(face_indices.size, face_counts.size * 3)
            self.assertEqual(colors.shape[0], points.shape[0])
            self.assertEqual(prim_rt.GetAttribute("primvars:colors:interpolation").Get(), "vertex")
            self.assertEqual(mesh_rt.GetVisibilityAttr().Get(), UsdGeomRT.Tokens.inherited)

            execution_time = Usd.TimeCode(completion.result["timecode"])
            temporal_context = ExecutionContext(
                reason=ExecutionReason.TEMPORAL_UPDATE,
                timecode=execution_time,
                raw_timecode=execution_time,
                next_time_code=None,
                device="cpu",
            )
            with mock.patch.object(simdata_iso_surface, "compute", wraps=simdata_iso_surface.compute) as iso_compute:
                await IsoSurface().exec(prim, "cpu", temporal_context)
            iso_compute.assert_not_called()

            structural_context = ExecutionContext(
                reason=ExecutionReason.STRUCTURAL_CHANGE,
                timecode=execution_time,
                raw_timecode=execution_time,
                next_time_code=None,
                device="cpu",
            )
            with mock.patch.object(simdata_iso_surface, "compute", wraps=simdata_iso_surface.compute) as iso_compute:
                await IsoSurface().exec(prim, "cpu", structural_context)
            iso_compute.assert_called_once()

            with (
                mock.patch.object(
                    utils.simdata_node_field, "compute", wraps=utils.simdata_node_field.compute
                ) as node_compute,
                mock.patch.object(simdata_iso_surface, "compute", wraps=simdata_iso_surface.compute) as iso_compute,
            ):
                async with wait_for_operator_complete(iso_path, operator="IsoSurface", allow_failure=True):
                    cae_viz.IsoSurfaceAPI(prim).GetIsoValueAttr().Set(2.0)

            node_compute.assert_not_called()
            iso_compute.assert_called_once()
            self.assertEqual(mesh_rt.GetVisibilityAttr().Get(), UsdGeomRT.Tokens.invisible)

            empty_context = ExecutionContext(
                reason=ExecutionReason.TEMPORAL_UPDATE,
                timecode=execution_time,
                raw_timecode=execution_time,
                next_time_code=None,
                device="cpu",
            )
            with mock.patch.object(simdata_iso_surface, "compute", wraps=simdata_iso_surface.compute) as iso_compute:
                with self.assertRaises(usd_utils.QuietableException):
                    await IsoSurface().exec(prim, "cpu", empty_context)
            iso_compute.assert_not_called()

            async with wait_for_operator_complete(iso_path, operator="IsoSurface"):
                cae_viz.IsoSurfaceAPI(prim).GetIsoValueAttr().Set(0.0)

            restored_points = read_rt_array(mesh_rt.GetPointsAttr(), "restored iso-surface points")
            restored_counts = read_rt_array(mesh_rt.GetFaceVertexCountsAttr(), "restored iso-surface face counts")
            self.assertGreater(restored_points.size, 0)
            self.assertGreater(restored_counts.size, 0)
            self.assertEqual(mesh_rt.GetVisibilityAttr().Get(), UsdGeomRT.Tokens.inherited)

    async def test_create_authors_dual_for_supported_dataset(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("hex_timesteps.cgns"), "/World/hex_timesteps")
            dataset_path = "/World/hex_timesteps/Base/Zone/ElementsUniform"
            iso_path = "/World/CAE/IsoSurface_Dual_Default"

            with mock.patch("omni.cae.viz.create_commands.cae_simdata.supports_dual_representation", return_value=True):
                async with wait_for_operator_complete(iso_path, operator="IsoSurface", allow_failure=True):
                    await execute_command("CreateCaeVizIsoSurface", dataset_path=dataset_path, prim_path=iso_path)

            prim = stage.GetPrimAtPath(iso_path)
            self.assertTrue(prim.HasAPI(cae_viz.DatasetAxisymmetricRepresentationAPI, "source"))
            self.assertTrue(prim.HasAPI(cae_viz.DatasetDualAPI, "source"))
