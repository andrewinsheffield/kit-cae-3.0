# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

import numpy as np
import omni.cae.simdata as cae_simdata
import omni.kit.test
import warp as wp
from omni.cae.schema import cae
from omni.cae.simdata.array_expressions import ArrayExpressionValueProvider
from pxr import OmniSci, Sdf, Usd


class _VirtualArrayProvider:
    def __init__(self, prim, instance_name, values, samples=()):
        self._prim = prim
        self._instance_name = instance_name
        self._values = values
        self._samples = samples

    def can_handle(self, prim, instance_name):
        return prim == self._prim and instance_name == self._instance_name

    def resolve(self, request):
        return wp.array(self._values, dtype=wp.float32, device=request.device)

    def get_time_samples(self, prim, instance_name):
        del prim, instance_name
        return self._samples


def _add_array(prim, name, values=None):
    OmniSci.ArrayAPI.Apply(prim, name)
    attr = prim.CreateAttribute(f"omni:sci:array:{name}:value", Sdf.ValueTypeNames.FloatArray)
    if values is not None:
        attr.Set(values)
    field = OmniSci.FieldAPI.Apply(prim, name)
    field.CreateNameAttr(name)
    field.CreateAssociationAttr("node")
    return attr


class TestArrayValues(omni.kit.test.AsyncTestCase):
    async def test_materialize_array_falls_back_to_authored_usd(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Data")
        _add_array(prim, "temperature", [1.0, 2.0, 3.0])

        value = cae_simdata.materialize_array(
            prim,
            "temperature",
            device="cpu",
            time_code=Usd.TimeCode.Default(),
        )

        np.testing.assert_array_equal(value.numpy(), [1.0, 2.0, 3.0])
        self.assertEqual(cae_simdata.get_array_time_samples(prim, "temperature"), ())

    async def test_authored_array_sampling_uses_held_values(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Data")
        attr = _add_array(prim, "temperature")
        attr.Set([1.0], Usd.TimeCode(10.0))
        attr.Set([2.0], Usd.TimeCode(20.0))

        effective_sample = cae_simdata.effective_array_time_sample
        self.assertEqual(effective_sample(prim, "temperature", Usd.TimeCode(0.0)), 10.0)
        self.assertEqual(effective_sample(prim, "temperature", Usd.TimeCode(10.0)), 10.0)
        self.assertEqual(effective_sample(prim, "temperature", Usd.TimeCode(15.0)), 10.0)
        self.assertEqual(effective_sample(prim, "temperature", Usd.TimeCode(20.0)), 20.0)
        self.assertEqual(effective_sample(prim, "temperature", Usd.TimeCode(30.0)), 20.0)

    async def test_registered_provider_supplies_value_and_sampling(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Data")
        _add_array(prim, "temperature")
        registration = cae_simdata.register_array_value_provider(
            _VirtualArrayProvider(prim, "temperature", [4.0, 5.0], (0.0, 10.0, 20.0))
        )
        try:
            value = cae_simdata.materialize_array(
                prim,
                "temperature",
                device="cpu",
                time_code=Usd.TimeCode(16.0),
            )

            np.testing.assert_array_equal(value.numpy(), [4.0, 5.0])
            self.assertEqual(cae_simdata.get_array_time_samples(prim, "temperature"), (0.0, 10.0, 20.0))
            self.assertEqual(
                cae_simdata.effective_array_time_sample(prim, "temperature", Usd.TimeCode(16.0)),
                10.0,
            )
        finally:
            registration.close()

        self.assertEqual(cae_simdata.get_array_time_samples(prim, "temperature"), ())

    async def test_expression_composes_with_virtual_native_array(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Data")
        _add_array(prim, "temperature")
        expression = cae.ArrayExpressionAPI.Apply(prim, "doubled")
        expression.CreateExpressionAttr("temperature * 2")
        expression.CreateEnabledAttr(True)
        expression.CreateLanguageVersionAttr(1)
        expression.CreateComputeDeviceAttr("cpu")

        virtual_registration = cae_simdata.register_array_value_provider(
            _VirtualArrayProvider(prim, "temperature", [2.0, 3.0], (0.0, 20.0)),
            priority=10,
        )
        expression_registration = cae_simdata.register_array_value_provider(
            ArrayExpressionValueProvider(),
            priority=100,
        )
        try:
            value = cae_simdata.materialize_array(
                prim,
                "doubled",
                device="cpu",
                time_code=Usd.TimeCode(10.0),
            )

            np.testing.assert_array_equal(value.numpy(), [4.0, 6.0])
            self.assertEqual(cae_simdata.get_array_time_samples(prim, "doubled"), (0.0, 20.0))
        finally:
            expression_registration.close()
            virtual_registration.close()
