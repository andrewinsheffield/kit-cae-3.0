# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

import omni.kit.app
import omni.kit.test
import omni.ui as ui
import omni.usd
from omni.cae.property.bundle.array_expression_widget import _FUNCTION_COMPLETIONS, build_array_expression_widget
from omni.cae.schema import cae


class TestArrayExpressionUI(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        await omni.usd.get_context().new_stage_async()
        self.stage = omni.usd.get_context().get_stage()
        self.prim = self.stage.DefinePrim("/Dataset")
        self.api = cae.ArrayExpressionAPI.Apply(self.prim, "density")
        self.api.CreateExpressionAttr("mass / volume")

    async def test_expression_editor_builds_in_standard_schema_group(self):
        window = ui.Window("Array Expression Test", width=600, height=400)
        with window.frame:
            with ui.VStack():
                build_array_expression_widget(
                    self.stage,
                    self.api.GetExpressionAttr().GetName(),
                    self.api.GetExpressionAttr().GetAllMetadata(),
                    None,
                    [self.prim.GetPath()],
                )

        await omni.kit.app.get_app().next_update_async()
        await omni.kit.app.get_app().next_update_async()
        window.destroy()

    async def test_constant_like_functions_are_offered_for_completion(self):
        self.assertTrue({"zeros_like()", "ones_like()", "full_like(, )"}.issubset(_FUNCTION_COMPLETIONS))
