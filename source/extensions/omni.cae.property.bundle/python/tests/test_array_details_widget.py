# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import omni.kit.app
import omni.kit.test
import omni.ui as ui
from omni.cae.property.bundle.array_details_widget import _DETAILS_CACHE, OmniSciArrayDetailsSection
from omni.cae.property.bundle.property_widget import OmniSciPropertiesWidget, _OmniSciArraysSection
from omni.cae.schema import cae
from pxr import Usd


class TestArrayDetailsWidget(omni.kit.test.AsyncTestCase):
    async def test_collect_instances_includes_array_expressions(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Data")
        expression = cae.ArrayExpressionAPI.Apply(prim, "liner_density")
        expression.CreateDisplayNameAttr("Liner Density")

        self.assertEqual(
            OmniSciArrayDetailsSection._collect_instances(prim),
            [("liner_density", "Liner Density")],
        )
        field_rows, array_rows = _OmniSciArraysSection.collect_rows(prim)
        self.assertEqual(
            field_rows,
            [
                {
                    "instance_name": "liner_density",
                    "field_name": "Liner Density",
                    "association": "inferred",
                    "temporal": "derived",
                }
            ],
        )
        self.assertEqual(array_rows, [])

        expression.CreateComputeDeviceAttr("cpu")
        metadata = OmniSciArrayDetailsSection._cheap_metadata(None, prim, "liner_density")
        self.assertEqual(metadata["device"], "cpu")
        self.assertEqual(metadata["type"], "float32 (derived)")

        expression.CreateEnabledAttr(False)
        self.assertEqual(OmniSciArrayDetailsSection._collect_instances(prim), [])
        self.assertEqual(_OmniSciArraysSection.collect_rows(prim), ([], []))

    async def test_timeline_event_marks_details_obsolete_without_clearing_them(self):
        section = object.__new__(OmniSciArrayDetailsSection)
        section._instances = [("velocity", "Velocity")]
        section._selected_index = 0
        section._selected_component = 2
        section._prim_path = "/Data"
        section._request_generation = 4
        section._loaded_array = object()
        section._observed_time_sample = 10.0
        section._get_effective_time_sample = lambda _instance: 20.0
        rebuilt = []
        section._rebuild_body = lambda: rebuilt.append(True)

        cache_key = (section._prim_path, "velocity")
        _DETAILS_CACHE[cache_key] = {"time_sample": 10.0}
        try:
            section._on_timeline_event(None)

            self.assertEqual(section._request_generation, 5)
            self.assertEqual(section._selected_component, 2)
            self.assertIsNotNone(section._loaded_array)
            self.assertEqual(rebuilt, [True])

            section._get_effective_time_sample = lambda _instance: 10.0
            section._on_timeline_event(None)

            self.assertEqual(section._request_generation, 6)
            self.assertEqual(section._observed_time_sample, 10.0)
            self.assertEqual(rebuilt, [True, True])
        finally:
            _DETAILS_CACHE.pop(cache_key, None)

    async def test_select_instance_updates_dropdown_and_details_state(self):
        class SelectionModel:
            def __init__(self):
                self.value = 0

            def get_value_as_int(self):
                return self.value

            def set_value(self, value):
                self.value = value

        section = object.__new__(OmniSciArrayDetailsSection)
        section._instances = [("pressure", "Pressure"), ("temperature", "Temperature")]
        section._selected_index = 0
        section._selected_component = 2
        section._request_generation = 4
        section._loaded_array = object()
        section._selection_model = SelectionModel()
        section._get_effective_time_sample = lambda instance: 10.0 if instance == "temperature" else None
        rebuilt = []
        section._rebuild_body = lambda: rebuilt.append(True)

        self.assertTrue(section.select_instance("temperature"))
        self.assertEqual(section._selected_index, 1)
        self.assertEqual(section._selection_model.value, 1)
        self.assertEqual(section._selected_component, 0)
        self.assertEqual(section._request_generation, 5)
        self.assertEqual(section._observed_time_sample, 10.0)
        self.assertIsNone(section._loaded_array)
        self.assertEqual(rebuilt, [True])

        self.assertFalse(section.select_instance("missing"))
        self.assertEqual(section._selected_index, 1)

    async def test_summary_selection_opens_array_details(self):
        class DetailsSection:
            def __init__(self):
                self.selected = []

            def select_instance(self, instance):
                self.selected.append(instance)
                return True

        class Frame:
            collapsed = True

        widget = object.__new__(OmniSciPropertiesWidget)
        widget._array_details_section = DetailsSection()
        widget._array_details_frame = Frame()

        widget._on_array_selected("temperature")

        self.assertEqual(widget._array_details_section.selected, ["temperature"])
        self.assertFalse(widget._array_details_frame.collapsed)

    async def test_summary_rows_build_as_selectable_controls(self):
        selected = []
        window = ui.Window("Array Summary Selection Test", width=600, height=200)
        with window.frame:
            _OmniSciArraysSection.build_items(
                [
                    {
                        "instance_name": "temperature",
                        "field_name": "Temperature",
                        "association": "node",
                        "temporal": "N",
                    }
                ],
                [],
                selected.append,
            )

        await omni.kit.app.get_app().next_update_async()
        window.destroy()
