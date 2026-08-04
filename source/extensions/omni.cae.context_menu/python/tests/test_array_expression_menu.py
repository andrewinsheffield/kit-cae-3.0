# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from unittest import mock

import omni.kit.test
from omni.cae.context_menu import api_schema_dialog
from omni.cae.context_menu.context_menu import (
    add_api_async,
    can_apply_array_expression,
    get_selected_prims,
    is_scientific_field_owner,
    validate_array_expression_name,
)
from omni.cae.schema import cae
from pxr import OmniSci, Usd


class TestArrayExpressionMenu(omni.kit.test.AsyncTestCase):
    async def test_untyped_scientific_field_owner_is_eligible(self):
        stage = Usd.Stage.CreateInMemory()
        flow_solution = stage.DefinePrim("/FlowSolution")
        OmniSci.FieldAPI.Apply(flow_solution, "Density")
        OmniSci.ArrayAPI.Apply(flow_solution, "Density")
        objects = {"stage": stage, "prim_list": [flow_solution]}

        self.assertFalse(flow_solution.IsA(Usd.Typed))
        self.assertTrue(is_scientific_field_owner(flow_solution))
        self.assertEqual(
            get_selected_prims(objects, is_scientific_field_owner),
            [flow_solution],
        )
        self.assertTrue(can_apply_array_expression(objects))

    async def test_prim_without_scientific_fields_is_not_eligible(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Other")

        self.assertFalse(can_apply_array_expression({"stage": stage, "prim_list": [prim]}))

    async def test_applying_array_expression_rebuilds_property_window(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/FlowSolution")
        property_window = mock.Mock()

        with (
            mock.patch.object(
                api_schema_dialog.APISchemaDialog,
                "exec",
                new=mock.AsyncMock(return_value="temperature"),
            ),
            mock.patch("omni.kit.window.property.get_window", return_value=property_window),
        ):
            await add_api_async(
                [prim],
                "CaeArrayExpressionAPI",
                validator=validate_array_expression_name,
            )

        self.assertTrue(prim.HasAPI(cae.ArrayExpressionAPI, "temperature"))
        property_window.request_rebuild.assert_called_once_with()
