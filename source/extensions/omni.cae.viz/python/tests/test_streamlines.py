# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import json
from logging import getLogger

import numpy as np
import omni.kit.test
from omni.cae.core import usd_utils
from omni.cae.core.commands import execute_command
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path, new_stage, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from pxr import OmniSci, Usd
from usdrt import UsdGeom as UsdGeomRT

from ._operator_test_utils import read_rt_array, wait_for_operator_complete

logger = getLogger(__name__)


def _set_field_names(field_selection_api: cae_viz.FieldSelectionAPI, *names: str) -> None:
    field_selection_api.CreateFieldNamesAttr().Set(list(names))


class TestStreamlines(omni.kit.test.AsyncTestCase):
    tolerance = 1e-5

    def _get_rt_curves(self, viz_prim: Usd.Prim):
        return UsdGeomRT.BasisCurves(usd_utils.get_prim_rt(viz_prim))

    async def test_streamlines_consumes_derived_vector_field(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            dataset_path = "/World/StaticMixer/Base/StaticMixer/B1_P3"
            field_prim = next(
                prim
                for prim in stage.Traverse()
                if all(prim.HasAPI(OmniSci.FieldAPI, name) for name in ("VelocityX", "VelocityY", "VelocityZ"))
            )
            expression = cae.ArrayExpressionAPI.Apply(field_prim, "derived_velocity")
            expression.CreateExpressionAttr("vec3(VelocityX, VelocityY, VelocityZ)")

            viz_path = "/World/CAE/Streamlines_Derived"
            sphere_path = "/World/CAE/DerivedSeeds"
            async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                await execute_command(
                    "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type="standard"
                )
            await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=sphere_path)
            await execute_command("TransformPrimSRT", path=sphere_path, new_scale=[0.2, 0.2, 0.2])

            viz_prim = stage.GetPrimAtPath(viz_path)
            sphere_prim = stage.GetPrimAtPath(sphere_path)
            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                cae_viz.OperatorAPI(viz_prim).CreateDeviceAttr().Set("cpu")
                cae_viz.StreamlinesAPI(viz_prim).GetDirectionAttr().Set(cae_viz.Tokens.forward)
                cae_viz.DatasetSelectionAPI(viz_prim, "seeds").GetTargetRel().SetTargets({sphere_prim.GetPath()})
                _set_field_names(cae_viz.FieldSelectionAPI(viz_prim, "velocities"), "derived_velocity")

            points = read_rt_array(self._get_rt_curves(viz_prim).GetPointsAttr(), "derived streamline points")
            self.assertGreater(len(points), 4)

    async def _streamlines_static_mixer(self, streamlines_type: str, use_colors: bool = False):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            base_path: str = "/World/StaticMixer/Base/StaticMixer"

            dataset_path: str = f"{base_path}/B1_P3"
            viz_path: str = f"/World/CAE/Streamlines_B1_P3"
            sphere_path: str = f"/World/CAE/Sphere"
            async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                await execute_command(
                    "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type=streamlines_type
                )
            await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=sphere_path)
            await execute_command("TransformPrimSRT", path=sphere_path, new_scale=[0.2, 0.2, 0.2])

            viz_prim: Usd.Prim = stage.GetPrimAtPath(viz_path)
            sphere_prim: Usd.Prim = stage.GetPrimAtPath(sphere_path)
            self.assertTrue(viz_prim.IsValid())
            self.assertTrue(sphere_prim.IsValid())

            streamlines_api: cae_viz.StreamlinesAPI = cae_viz.StreamlinesAPI(viz_prim)

            ds_api: cae_viz.DatasetSelectionAPI = cae_viz.DatasetSelectionAPI(viz_prim, "seeds")

            vs_api = cae_viz.FieldSelectionAPI(viz_prim, "velocities")

            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.forward)
                ds_api.GetTargetRel().SetTargets({sphere_prim.GetPath()})
                _set_field_names(vs_api, "VelocityX", "VelocityY", "VelocityZ")
                if use_colors:
                    _set_field_names(cae_viz.FieldSelectionAPI(viz_prim, "colors"), "Temperature")

            # Get forward direction points
            curves = self._get_rt_curves(viz_prim)
            points_forward = read_rt_array(curves.GetPointsAttr(), "forward points")
            self.assertGreater(len(points_forward), 4)

            # Verify times and rnd primvars are present
            times_forward = read_rt_array(curves.GetPrim().GetAttribute("primvars:times"), "forward times primvar")
            self.assertEqual(len(times_forward), len(points_forward))
            self.assertGreater(len(times_forward), 0, "times primvar should have values")

            rnd_forward = read_rt_array(curves.GetPrim().GetAttribute("primvars:rnd"), "forward rnd primvar")
            self.assertGreater(len(rnd_forward), 0, "rnd primvar should have values")

            colors_forward = None
            if use_colors:
                colors_forward = read_rt_array(
                    curves.GetPrim().GetAttribute("primvars:colors"), "forward colors primvar"
                )
                self.assertEqual(len(colors_forward), len(points_forward))

            # Switch to backward direction
            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.backward)
            points_backward = read_rt_array(curves.GetPointsAttr(), "backward points")
            self.assertFalse(np.array_equal(points_backward, points_forward))
            colors_backward = None
            if use_colors:
                colors_backward = read_rt_array(
                    curves.GetPrim().GetAttribute("primvars:colors"), "backward colors primvar"
                )
                self.assertEqual(len(colors_backward), len(points_backward))

            # Move the sphere to the right
            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                await execute_command("TransformPrimSRT", path=sphere_path, new_translation=[0.1, 0, 0])
            points_moved = read_rt_array(curves.GetPointsAttr(), "moved points")
            self.assertFalse(np.array_equal(points_moved, points_backward))
            colors_moved = None
            if use_colors:
                colors_moved = read_rt_array(curves.GetPrim().GetAttribute("primvars:colors"), "moved colors primvar")
                self.assertEqual(len(colors_moved), len(points_moved))

            # Return summary values for assertions in the test methods
            result = {
                "forward": {
                    "min": points_forward.min(axis=0).tolist(),
                    "max": points_forward.max(axis=0).tolist(),
                    "shape": points_forward.shape,
                },
                "backward": {
                    "min": points_backward.min(axis=0).tolist(),
                    "max": points_backward.max(axis=0).tolist(),
                    "shape": points_backward.shape,
                },
                "moved": {
                    "min": points_moved.min(axis=0).tolist(),
                    "max": points_moved.max(axis=0).tolist(),
                    "shape": points_moved.shape,
                },
            }

            # Add color information if colors were used
            if use_colors:
                if colors_forward is not None:
                    result["forward"]["colors_min"] = colors_forward.min(axis=0).tolist()
                    result["forward"]["colors_max"] = colors_forward.max(axis=0).tolist()
                    result["forward"]["colors_shape"] = colors_forward.shape
                if colors_backward is not None:
                    result["backward"]["colors_min"] = colors_backward.min(axis=0).tolist()
                    result["backward"]["colors_max"] = colors_backward.max(axis=0).tolist()
                    result["backward"]["colors_shape"] = colors_backward.shape
                if colors_moved is not None:
                    result["moved"]["colors_min"] = colors_moved.min(axis=0).tolist()
                    result["moved"]["colors_max"] = colors_moved.max(axis=0).tolist()
                    result["moved"]["colors_shape"] = colors_moved.shape

            logger.info("Streamlines result: %s", json.dumps(result, indent=4))
            return result

    async def test_streamlines_static_mixer_standard(self):
        result = await self._streamlines_static_mixer("standard")

        # Forward direction assertions
        np.testing.assert_allclose(
            result["forward"]["min"], [-0.19455785, -0.19781476, -1.9918408], atol=self.tolerance
        )
        np.testing.assert_allclose(result["forward"]["max"], [0.19890438, 0.19781476, 0.2], atol=self.tolerance)
        self.assertEqual(result["forward"]["shape"], (2992, 3))

        # Backward direction assertions
        np.testing.assert_allclose(result["backward"]["min"], [-1.9416908, -1.9246704, -0.2], atol=self.tolerance)
        np.testing.assert_allclose(result["backward"]["max"], [1.9306283, 1.8990393, 1.9998803], atol=self.tolerance)
        self.assertEqual(result["backward"]["shape"], (34724, 3))

        # Moved sphere assertions
        np.testing.assert_allclose(result["moved"]["min"], [-1.983881, -2.990228, -0.2], atol=self.tolerance)
        np.testing.assert_allclose(result["moved"]["max"], [1.9660718, 2.9283297, 1.9999539], atol=self.tolerance)
        self.assertEqual(result["moved"]["shape"], (31858, 3))

    async def test_streamlines_static_mixer_nanovdb(self):
        result = await self._streamlines_static_mixer("nanovdb")

        # Forward direction assertions
        np.testing.assert_allclose(
            result["forward"]["min"], [-0.19496827, -0.19781476, -2.01943183], atol=self.tolerance
        )
        np.testing.assert_allclose(result["forward"]["max"], [0.19890438, 0.19781476, 0.2], atol=self.tolerance)
        self.assertEqual(result["forward"]["shape"], (13218, 3))

        # Backward direction assertions
        np.testing.assert_allclose(result["backward"]["min"], [-0.47952273, -0.47531837, -0.2], atol=self.tolerance)
        np.testing.assert_allclose(result["backward"]["max"], [0.53531051, 0.61094195, 1.94740367], atol=self.tolerance)
        self.assertEqual(result["backward"]["shape"], (38400, 3))

        # Moved sphere assertions
        np.testing.assert_allclose(result["moved"]["min"], [-0.69408685, -0.82115805, -0.2], atol=self.tolerance)
        np.testing.assert_allclose(result["moved"]["max"], [0.71303058, 0.66411346, 1.94949317], atol=self.tolerance)
        self.assertEqual(result["moved"]["shape"], (38400, 3))

    async def test_streamlines_static_mixer_standard_with_colors(self):
        result = await self._streamlines_static_mixer("standard", use_colors=True)

        # Points assertions (same as without colors)
        np.testing.assert_allclose(
            result["forward"]["min"], [-0.19455785, -0.19781476, -1.9918408], atol=self.tolerance
        )
        np.testing.assert_allclose(result["forward"]["max"], [0.19890438, 0.19781476, 0.2], atol=self.tolerance)
        self.assertEqual(result["forward"]["shape"], (2992, 3))

        # Color assertions for forward direction
        self.assertIsNotNone(result["forward"].get("colors_min"))
        np.testing.assert_allclose(result["forward"]["colors_min"], [299.43332], atol=self.tolerance)
        np.testing.assert_allclose(result["forward"]["colors_max"], [300.4997], atol=self.tolerance)
        self.assertEqual(result["forward"]["colors_shape"], (2992, 1))

        # Backward direction assertions
        np.testing.assert_allclose(result["backward"]["min"], [-1.9416908, -1.9246704, -0.2], atol=self.tolerance)
        np.testing.assert_allclose(result["backward"]["max"], [1.9306283, 1.8990393, 1.9998803], atol=self.tolerance)
        self.assertEqual(result["backward"]["shape"], (34724, 3))

        # Color assertions for backward direction
        np.testing.assert_allclose(result["backward"]["colors_min"], 289.355, atol=1e-3)
        np.testing.assert_allclose(result["backward"]["colors_max"], 307.960, atol=1e-3)
        self.assertEqual(result["backward"]["colors_shape"], (34724, 1))

        # Moved sphere assertions
        np.testing.assert_allclose(result["moved"]["min"], [-1.983881, -2.990228, -0.2], atol=self.tolerance)
        np.testing.assert_allclose(result["moved"]["max"], [1.9660718, 2.9283297, 1.9999539], atol=self.tolerance)
        self.assertEqual(result["moved"]["shape"], (31858, 3))

        # Color assertions for moved sphere
        np.testing.assert_allclose(result["moved"]["colors_min"], [284.99997], atol=self.tolerance)
        np.testing.assert_allclose(result["moved"]["colors_max"], [315.00027], atol=self.tolerance)
        self.assertEqual(result["moved"]["colors_shape"], (31858, 1))

    async def test_streamlines_static_mixer_nanovdb_with_colors(self):
        result = await self._streamlines_static_mixer("nanovdb", use_colors=True)

        # Points assertions (same as without colors)
        np.testing.assert_allclose(
            result["forward"]["min"], [-0.19496827, -0.19781476, -2.01943183], atol=self.tolerance
        )
        np.testing.assert_allclose(result["forward"]["max"], [0.19890438, 0.19781476, 0.2], atol=self.tolerance)
        self.assertEqual(result["forward"]["shape"], (13218, 3))

        # Color assertions for forward direction
        self.assertIsNotNone(result["forward"].get("colors_min"))
        self.assertAlmostEqual(result["forward"]["colors_min"][0], 285.0234, places=3)
        self.assertAlmostEqual(result["forward"]["colors_max"][0], 300.4997, places=3)
        self.assertEqual(result["forward"]["colors_shape"], (13218, 1))

    async def test_streamlines_static_mixer_standard_with_widths(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            base_path: str = "/World/StaticMixer/Base/StaticMixer"

            dataset_path: str = f"{base_path}/B1_P3"
            viz_path: str = f"/World/CAE/Streamlines_B1_P3"
            sphere_path: str = f"/World/CAE/Sphere"
            async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                await execute_command(
                    "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type="standard"
                )
            await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=sphere_path)
            await execute_command("TransformPrimSRT", path=sphere_path, new_scale=[0.2, 0.2, 0.2])

            viz_prim: Usd.Prim = stage.GetPrimAtPath(viz_path)
            sphere_prim: Usd.Prim = stage.GetPrimAtPath(sphere_path)
            self.assertTrue(viz_prim.IsValid())
            self.assertTrue(sphere_prim.IsValid())

            streamlines_api: cae_viz.StreamlinesAPI = cae_viz.StreamlinesAPI(viz_prim)

            ds_api: cae_viz.DatasetSelectionAPI = cae_viz.DatasetSelectionAPI(viz_prim, "seeds")

            vs_api = cae_viz.FieldSelectionAPI(viz_prim, "velocities")

            # first; pass constant width and confirm that's what we get.
            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.forward)
                ds_api.GetTargetRel().SetTargets({sphere_prim.GetPath()})
                _set_field_names(vs_api, "VelocityX", "VelocityY", "VelocityZ")
                streamlines_api.GetWidthAttr().Set(0.05)

            widths = read_rt_array(
                self._get_rt_curves(viz_prim).GetPrim().GetAttribute("primvars:widths"),
                "constant widths primvar",
            )
            np.testing.assert_allclose(widths, 0.05, atol=self.tolerance)

            # now; pass field-specific width and confirm that's what we get.
            vs_api = cae_viz.FieldSelectionAPI(viz_prim, "widths")

            mapping_api = cae_viz.FieldMappingAPI(viz_prim, "widths")

            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                _set_field_names(vs_api, "Temperature")
                mapping_api.GetRangeAttr().Set((0.045, 0.1))

            widths = read_rt_array(
                self._get_rt_curves(viz_prim).GetPrim().GetAttribute("primvars:widths"),
                "temperature widths primvar",
            )
            self.assertGreater(widths.max(), widths.min())
            self.assertTrue(widths.min() >= 0.045)
            self.assertTrue(widths.max() <= 0.1)
            self.assertAlmostEqual(widths.mean(), 0.072453074, places=3)

            domain = mapping_api.GetDomainAttr().Get()
            self.assertAlmostEqual(domain[0], 285.0, places=3)
            self.assertAlmostEqual(domain[1], 315.0, places=3)

            # change range and confirm that's what we get.
            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                mapping_api.GetRangeAttr().Set((0.01, 0.05))
            widths = read_rt_array(
                self._get_rt_curves(viz_prim).GetPrim().GetAttribute("primvars:widths"),
                "remapped widths primvar",
            )
            self.assertTrue(widths.min() >= 0.01)
            self.assertTrue(widths.max() <= 0.05)
            self.assertAlmostEqual(widths.mean(), 0.02996587, places=3)

            # change array to Pres; drop rescale range and confirm that range remains unchanged.
            rescale_range_api = cae_viz.RescaleRangeAPI(viz_prim, "widths")

            async with wait_for_operator_complete(viz_path, operator="Streamlines"):
                rescale_range_api.GetIncludesRel().SetTargets([])
                _set_field_names(vs_api, "Pressure")

            widths = read_rt_array(
                self._get_rt_curves(viz_prim).GetPrim().GetAttribute("primvars:widths"),
                "pressure widths primvar",
            )
            self.assertGreater(widths.mean(), 0.035)
            self.assertTrue(widths.min() >= (0.01 - self.tolerance))
            self.assertTrue(widths.max() <= (0.05 + self.tolerance))
            self.assertAlmostEqual(widths.mean(), 0.042299, places=3)

            domain = mapping_api.GetDomainAttr().Get()
            self.assertAlmostEqual(domain[0], 285.0, places=3)
            self.assertAlmostEqual(domain[1], 315.0, places=3)

    async def test_streamlines_seeds_outside_bounds(self):
        """Test that streamlines with seeds outside dataset bounds doesn't raise errors."""
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            base_path: str = "/World/StaticMixer/Base/StaticMixer"

            dataset_path: str = f"{base_path}/B1_P3"
            viz_path: str = f"/World/CAE/Streamlines_Outside"
            sphere_path: str = f"/World/CAE/SphereOutside"

            # Create streamlines and sphere
            async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                await execute_command(
                    "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type="standard"
                )
            await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=sphere_path)

            # Move sphere far outside the dataset bounds
            await execute_command(
                "TransformPrimSRT", path=sphere_path, new_translation=[100, 100, 100], new_scale=[0.2, 0.2, 0.2]
            )

            viz_prim: Usd.Prim = stage.GetPrimAtPath(viz_path)
            sphere_prim: Usd.Prim = stage.GetPrimAtPath(sphere_path)
            self.assertTrue(viz_prim.IsValid())
            self.assertTrue(sphere_prim.IsValid())

            streamlines_api: cae_viz.StreamlinesAPI = cae_viz.StreamlinesAPI(viz_prim)

            ds_api: cae_viz.DatasetSelectionAPI = cae_viz.DatasetSelectionAPI(viz_prim, "seeds")

            vs_api = cae_viz.FieldSelectionAPI(viz_prim, "velocities")

            # This should complete without raising errors (though streamlines will be empty/invisible)
            async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.forward)
                ds_api.GetTargetRel().SetTargets({sphere_prim.GetPath()})
                _set_field_names(vs_api, "VelocityX", "VelocityY", "VelocityZ")

            # Verify the prim is still valid and invisible (since no streamlines were generated)
            usdrt_curves = UsdGeomRT.BasisCurves(usd_utils.get_prim_rt(viz_prim))
            visibility = usdrt_curves.GetVisibilityAttr().Get()
            # When seeds are outside bounds, prim should be invisible due to QuietableException
            self.assertEqual(
                visibility,
                UsdGeomRT.Tokens.invisible,
                "Streamlines prim should be invisible when seeds are outside dataset bounds",
            )

    async def test_streamlines_nanovdb_point_cloud_applies_splatting(self):
        """Test that NanoVDB streamlines apply DatasetGaussianSplattingAPI for point cloud data.

        Point clouds have no cells, so the voxelization kernel cannot sample them directly
        (CellLocatorAPI.find_cell_containing_point always returns False). The streamlines
        command must detect this (nb_cells <= 0) and apply DatasetGaussianSplattingAPI
        to splat point values onto a grid before voxelization.
        """
        import os
        import tempfile

        async with new_stage() as stage:
            # Create a minimal point cloud NPZ
            n_points = 100
            rng = np.random.default_rng(42)
            coords = rng.uniform(-1.0, 1.0, (n_points, 3)).astype(np.float32)
            velocity = np.tile(np.array([1.0, 0.0, 0.0], dtype=np.float32), (n_points, 1))

            with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
                npz_path = f.name
                np.savez(f, coordinates=coords, velocity=velocity)

            try:
                from omni.cae.usd_plugins_importers import import_to_stage as import_npz

                await import_npz(npz_path, "/World/PointCloud", schema="Point Cloud")
                await wait_for_update()

                dataset_path = "/World/PointCloud"
                viz_path = "/World/CAE/Streamlines_PointCloud"

                async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                    await execute_command(
                        "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type="nanovdb"
                    )

                viz_prim = stage.GetPrimAtPath(viz_path)
                self.assertTrue(viz_prim.IsValid())

                # The fix: for point cloud sources (nb_cells=0), the command should apply
                # DatasetGaussianSplattingAPI alongside DatasetVoxelizationAPI.
                self.assertTrue(
                    viz_prim.HasAPI(cae_viz.DatasetVoxelizationAPI, "source"),
                    "NanoVDB streamlines should have DatasetVoxelizationAPI applied",
                )
                self.assertTrue(
                    viz_prim.HasAPI(cae_viz.DatasetGaussianSplattingAPI, "source"),
                    "NanoVDB streamlines on point cloud should have DatasetGaussianSplattingAPI applied",
                )
            finally:
                os.unlink(npz_path)

    async def test_streamlines_nanovdb_mesh_no_splatting(self):
        """Test that NanoVDB streamlines do NOT apply DatasetGaussianSplattingAPI for mesh data.

        Mesh data has cells, so voxelization can sample directly — no splatting needed.
        """
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            base_path = "/World/StaticMixer/Base/StaticMixer"
            dataset_path = f"{base_path}/B1_P3"
            viz_path = "/World/CAE/Streamlines_Mesh"

            async with wait_for_operator_complete(viz_path, operator="Streamlines", allow_failure=True):
                await execute_command(
                    "CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=viz_path, type="nanovdb"
                )

            viz_prim = stage.GetPrimAtPath(viz_path)
            self.assertTrue(viz_prim.IsValid())

            self.assertTrue(
                viz_prim.HasAPI(cae_viz.DatasetVoxelizationAPI, "source"),
                "NanoVDB streamlines should have DatasetVoxelizationAPI applied",
            )
            self.assertFalse(
                viz_prim.HasAPI(cae_viz.DatasetGaussianSplattingAPI, "source"),
                "NanoVDB streamlines on mesh should NOT have DatasetGaussianSplattingAPI applied",
            )
