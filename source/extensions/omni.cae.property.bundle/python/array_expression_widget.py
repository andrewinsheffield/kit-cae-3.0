# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Expression editor with field/function completion and live static validation."""

__all__ = ["build_array_expression_widget"]

import asyncio
from typing import List

import omni.cae.simdata as cae_simdata
import omni.ui as ui
from omni.kit.property.usd.usd_attribute_model import UsdAttributeModel
from omni.kit.property.usd.usd_property_widget_builder import UsdPropertiesWidgetBuilder
from omni.kit.window.property.templates import HORIZONTAL_SPACING, LABEL_HEIGHT
from pxr import Sdf, Usd

_FUNCTION_COMPLETIONS = (
    "abs()",
    "ceil()",
    "clamp(, , )",
    "component(, 0)",
    "cos()",
    "cross(, )",
    "dot(, )",
    "eq(, )",
    "exp()",
    "floor()",
    "full_like(, )",
    "ge(, )",
    "gt(, )",
    "if(, , )",
    "le(, )",
    "log()",
    "lt(, )",
    "magnitude()",
    "max(, )",
    "min(, )",
    "ne(, )",
    "ones_like()",
    "pow(, )",
    "sin()",
    "sqrt()",
    "vec2(, )",
    "vec3(, , )",
    "vec4(, , , )",
    "where(, , )",
    "zeros_like()",
)


def _instance_name(attr_name: str) -> str:
    parts = attr_name.split(":")
    return parts[-2] if len(parts) >= 2 else ""


def build_array_expression_widget(
    stage: Usd.Stage,
    attr_name: str,
    metadata: dict,
    property_type,
    prim_paths: List[Sdf.Path],
    additional_label_kwargs=None,
    additional_widget_kwargs=None,
):
    """Build a USD-backed expression field with completion and live diagnostics."""
    attribute_paths = [path.AppendProperty(attr_name) for path in prim_paths]
    model = UsdAttributeModel(stage, attribute_paths, False, metadata)
    generation = [0]
    menu_holder = [None]

    with ui.HStack(spacing=HORIZONTAL_SPACING):
        label = UsdPropertiesWidgetBuilder.create_label(attr_name, metadata, additional_label_kwargs)
        with ui.VStack(spacing=2):
            with ui.HStack(height=LABEL_HEIGHT, spacing=2):
                field = ui.StringField(model=model, height=LABEL_HEIGHT, width=ui.Fraction(1))
                ui.Button(
                    "⌄",
                    width=20,
                    tooltip="Insert a field or expression function",
                    clicked_fn=lambda: show_completions(),
                )
            diagnostic_label = ui.Label(
                "",
                height=0,
                word_wrap=True,
                style={"font_size": 11, "color": 0xFF777777},
            )

        UsdPropertiesWidgetBuilder.create_control_state(
            model,
            value_widget=field,
            label=label,
            **(additional_widget_kwargs or {}),
        )

    def append_completion(text: str):
        current = model.get_value_as_string() or ""
        separator = " " if current and not current.endswith((" ", "(", ",")) else ""
        model.set_value(f"{current}{separator}{text}")

    def show_completions():
        async def build_menu():
            fields_by_name = {}
            for prim_path in prim_paths:
                prim = stage.GetPrimAtPath(prim_path)
                if not prim:
                    continue
                available_fields = cae_simdata.get_prim_fields(prim)
                for field_info in available_fields:
                    fields_by_name.setdefault(field_info.name, field_info)

            menu_holder[0] = ui.Menu("Expression completion")
            with menu_holder[0]:
                with ui.Menu("Fields"):
                    for name, field_info in sorted(fields_by_name.items()):
                        label_text = name if field_info.label == name else f"{name} ({field_info.label})"
                        ui.MenuItem(
                            label_text,
                            triggered_fn=lambda value=name: append_completion(value),
                        )
                with ui.Menu("Functions"):
                    for completion in _FUNCTION_COMPLETIONS:
                        ui.MenuItem(
                            completion,
                            triggered_fn=lambda value=completion: append_completion(value),
                        )
            menu_holder[0].show()

        asyncio.ensure_future(build_menu())

    def validate(_model=None):
        generation[0] += 1
        request = generation[0]

        async def run_validation():
            if len(prim_paths) != 1:
                diagnostic_label.text = "Validation is available for one selected array prim."
                return
            prim = stage.GetPrimAtPath(prim_paths[0])
            try:
                descriptions = await cae_simdata.get_array_expression_descriptions(prim)
            except Exception as exc:
                if request == generation[0]:
                    diagnostic_label.text = f"Validation unavailable: {exc}"
                    diagnostic_label.style = {"font_size": 11, "color": 0xFF6666FF}
                return
            if request != generation[0]:
                return
            name = _instance_name(attr_name)
            description = next((item for item in descriptions if item.name == name), None)
            if description is None:
                diagnostic_label.text = "Expression API instance is no longer available."
                diagnostic_label.style = {"font_size": 11, "color": 0xFF6666FF}
            elif description.diagnostics:
                diagnostic_label.text = description.diagnostics[0].format()
                diagnostic_label.style = {"font_size": 11, "color": 0xFF6666FF}
            elif not description.enabled:
                diagnostic_label.text = "Disabled"
                diagnostic_label.style = {"font_size": 11, "color": 0xFF999999}
            else:
                dependencies = ", ".join(description.dependencies) or "none"
                diagnostic_label.text = f"Valid · dependencies: {dependencies}"
                diagnostic_label.style = {"font_size": 11, "color": 0xFF66CC88}

        asyncio.ensure_future(run_validation())

    model.add_value_changed_fn(validate)
    validate()
    return [model]
