# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

import gc
import weakref
from unittest.mock import AsyncMock, patch

import numpy as np
import omni.kit.test
from omni.cae.core import cache
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import get_test_data_path, new_stage
from omni.cae.usd_plugins_importers import import_to_stage
from pxr import Sdf, Usd, UsdShade, UsdVol

from ..execution_context import ExecutionContext, ExecutionReason
from ..index_axisymmetric_volume import (
    AxisymmetricVolumeCompute,
    IndeXAxisymmetricVolume,
    LookupLevelSpec,
    LookupSpec,
    _state_cache_key,
    _volume_states,
    _VolumeState,
    classify_flash_refinement_levels,
)
from ..operator import get_operators


class TestIndeXAxisymmetricVolume(omni.kit.test.AsyncTestCase):
    def test_generation_lookup_does_not_retain_released_states(self):
        generation = 2**31 - 1
        spec = LookupSpec(
            levels=(),
            native_spacing=1.0,
            render_bounds=(0.0, 1.0, 0.0, 1.0),
            angle_range=(0.0, 2.0 * np.pi),
            domain_spacing=1.0,
            domain_dims=(1, 1, 1),
            domain_nanovdb_voxels=1,
        )
        state = _VolumeState(volumes=(), spec=spec, generation=generation, retained_objects=())
        state_ref = weakref.ref(state)
        _volume_states[generation] = state

        del state
        gc.collect()

        self.assertIsNone(state_ref())
        self.assertNotIn(generation, _volume_states)

    def test_stale_compute_generation_is_a_warning(self):
        generation = 2**31 - 1
        _volume_states.pop(generation, None)
        compute = AxisymmetricVolumeCompute(
            {
                "state_key": "/World/MissingVolume",
                "time_code": "54",
                "generation": str(generation),
            }
        )

        with self.assertLogs("omni.cae.viz.index_axisymmetric_volume", level="WARNING") as captured:
            compute.launch_compute(None)

        self.assertIn("Skipping stale axisymmetric lookup generation", captured.output[0])

    def test_lookup_preserves_native_refinement_levels(self):
        block_bounds = np.asarray(
            [
                [0.0, 2.0, 10.0, 12.0],
                [2.0, 3.0, 10.0, 11.0],
            ],
            dtype=np.float32,
        )
        field_values = np.asarray(
            [
                [[1.0, 2.0], [3.0, 4.0]],
                [[5.0, 6.0], [7.0, 8.0]],
            ],
            dtype=np.float32,
        )

        bounds, values, spacings, assignments = classify_flash_refinement_levels(block_bounds, field_values, (2, 2))

        np.testing.assert_array_equal(bounds, block_bounds)
        np.testing.assert_array_equal(values, field_values)
        np.testing.assert_array_equal(spacings, [0.5, 1.0])
        # Finest leaf is slot zero; the coarse leaf remains one native level.
        np.testing.assert_array_equal(assignments, [1, 0])

    def test_lookup_rejects_empty_input(self):
        with self.assertRaisesRegex(ValueError, "at least one FLASH leaf block"):
            classify_flash_refinement_levels(
                np.empty((0, 4), dtype=np.float32),
                np.empty((0, 2, 2), dtype=np.float32),
                (2, 2),
            )

    def test_lookup_rejects_nonpositive_cell_dimensions(self):
        with self.assertRaisesRegex(ValueError, "positive FLASH cell dimensions"):
            classify_flash_refinement_levels(
                np.asarray([[0.0, 1.0, 0.0, 1.0]], dtype=np.float32),
                np.empty((1, 2, 0), dtype=np.float32),
                (0, 2),
            )

    def test_lookup_rejects_nonfinite_bounds(self):
        with self.assertRaisesRegex(ValueError, "finite values"):
            classify_flash_refinement_levels(
                np.asarray([[0.0, np.inf, 0.0, 1.0]], dtype=np.float32),
                np.zeros((1, 2, 2), dtype=np.float32),
                (2, 2),
            )

    async def test_creation_uses_visible_transfer_function(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            await execute_command(
                "CreateCaeVizVolume",
                dataset_path="/World/StaticMixer/Base/StaticMixer/B1_P3",
                prim_path="/World/CAE/AxisymmetricVolume",
                type="axisymmetric",
            )

            colormap = stage.GetPrimAtPath("/World/CAE/AxisymmetricVolume/Material/Colormap")
            volume = stage.GetPrimAtPath("/World/CAE/AxisymmetricVolume")
            shader = UsdShade.Shader(stage.GetPrimAtPath("/World/CAE/AxisymmetricVolume/Material/VolumeShader"))
            self.assertEqual(volume.GetAttribute("nvindex:type").Get(), "vdb")
            np.testing.assert_allclose(colormap.GetAttribute("xPoints").Get(), [0.0, 0.001, 1.0])
            self.assertAlmostEqual(colormap.GetAttribute("rgbaPoints").Get()[1][3], 0.8)
            np.testing.assert_allclose(shader.GetInput("lookup_angle_range").Get(), [0.0, 2.0 * np.pi])

    async def test_uses_dedicated_operator(self):
        async with new_stage() as stage:
            volume = UsdVol.Volume.Define(stage, "/World/AxisymmetricVolume").GetPrim()
            cae_viz.IndeXVolumeAPI.Apply(volume)
            cae_viz.IndeXAxisymmetricVolumeAPI.Apply(volume)
            cae_viz.DatasetSelectionAPI.Apply(volume, "source")

            applied_schemas = set(volume.GetAppliedSchemas())
            matching_operators = [
                operator_class
                for operator_class in get_operators()
                if operator_class.prim_type == volume.GetTypeName()
                and operator_class.api_schemas.issubset(applied_schemas)
            ]

            self.assertTrue(matching_operators)
            self.assertEqual(matching_operators[0].__name__, "IndeXAxisymmetricVolume")

    async def test_time_tick_selects_cached_payload(self):
        async with new_stage() as stage:
            await import_to_stage(get_test_data_path("StaticMixer.cgns"), "/World/StaticMixer")
            await execute_command(
                "CreateCaeVizVolume",
                dataset_path="/World/StaticMixer/Base/StaticMixer/B1_P3",
                prim_path="/World/CAE/AxisymmetricVolume",
                type="axisymmetric",
            )
            prim = stage.GetPrimAtPath("/World/CAE/AxisymmetricVolume")
            loader = UsdShade.Shader(prim.GetChild("Material").GetChild("DataLoader"))
            loader.CreateInput("params_generation", Sdf.ValueTypeNames.Int).Set(9)

            spec = LookupSpec(
                levels=(LookupLevelSpec(0.5, 1, 4, 8),),
                native_spacing=0.5,
                render_bounds=(0.0, 2.0, -1.0, 1.0),
                angle_range=(0.25 * np.pi, 0.75 * np.pi),
                domain_spacing=0.5,
                domain_dims=(8, 4, 8),
                domain_nanovdb_voxels=256,
            )
            state = _VolumeState(volumes=(), spec=spec, generation=10, retained_objects=())
            cache_key = _state_cache_key(str(prim.GetPath()))
            cache.put_ex(cache_key, state, force=True, timeCode=Usd.TimeCode(30.0))
            context = ExecutionContext(
                reason=ExecutionReason.TEMPORAL_TICK,
                timecode=Usd.TimeCode(30.0),
                raw_timecode=Usd.TimeCode(30.0),
                next_time_code=None,
                device="cuda:0",
            )

            try:
                with patch("omni.cae.viz.index_axisymmetric_volume.configure_volume") as configure:
                    await IndeXAxisymmetricVolume().on_time_changed(prim, "cuda:0", context)

                configure.assert_called_once_with(
                    prim,
                    spec,
                    10,
                    Usd.TimeCode(30.0),
                    cae_viz.IndeXAxisymmetricVolumeAPI(prim).GetSamplingDistanceScaleAttr().Get(),
                )

                loader.GetInput("params_generation").Set(10)
                with patch("omni.cae.viz.index_axisymmetric_volume.configure_volume") as configure:
                    await IndeXAxisymmetricVolume().on_time_changed(prim, "cuda:0", context)
                configure.assert_not_called()

                cache.remove(cache_key)
                operator = IndeXAxisymmetricVolume()
                with patch.object(operator, "exec", new_callable=AsyncMock) as execute:
                    await operator.on_time_changed(prim, "cuda:0", context)
                execute.assert_awaited_once_with(prim, "cuda:0", context)
            finally:
                cache.remove(cache_key)
