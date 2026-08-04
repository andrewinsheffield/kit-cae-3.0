# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

__all__ = [
    "CaeGeomPrimSchemeDelegate",
    "SchemaPropertiesWidget",
    "CaePropertiesWidget",
    "RtwtPropertiesWidget",
    "OmniSciPropertiesWidget",
]

import omni.cae.simdata as cae_simdata
import omni.ui as ui
import omni.usd
from omni.cae.core import usd_utils
from omni.cae.property.bundle.array_details_widget import OmniSciArrayDetailsSection
from omni.cae.property.bundle.array_expression_widget import build_array_expression_widget
from omni.cae.property.bundle.field_names_widget import build_field_names_widget
from omni.cae.property.bundle.operator_pipelines_widget import CaeOperatorPipelinesSection
from omni.cae.schema import cae
from omni.kit.property.bundle import GeomPrimSchemeDelegate
from omni.kit.property.usd.usd_property_widget import MultiSchemaPropertiesWidget, UiDisplayGroup, UsdPropertiesWidget
from omni.kit.window.property.style import get_style
from omni.kit.window.property.templates import HORIZONTAL_SPACING, LABEL_HEIGHT
from pxr import Usd


class SchemaPropertiesWidget(UsdPropertiesWidget):
    """Base properties widget that filters and groups USD attributes by API schema family.

    Subclasses implement ``_accepts_schema`` to declare which schema names they own.
    The widget shows only attributes belonging to accepted schemas, groups them by
    instance name, and preserves schema-defined attribute order.
    """

    def __init__(self, title: str):
        super().__init__(title, collapsed=False, maintain_property_order=True)
        self._schema_attr_names = set()
        self._multi_schema_properties_widgets = {}

    def on_new_payload(self, payload):
        if not super().on_new_payload(payload):
            return False

        if not self._payload or len(self._payload) == 0:
            return False

        return self._build_schema_attr_names()

    def _accepts_schema(self, api_schema: str) -> bool:
        """Return True if this widget should handle *api_schema*.

        Override in subclasses to restrict the widget to a specific schema family.
        The default accepts nothing so subclasses must override.
        """
        return False

    def _add_multi_schema_properties_widget(self, api_schema):
        # Registering here ensures that properties for these schemas are not also shown in
        # the generic "Geometry" widget, which would produce duplicates.
        self._multi_schema_properties_widgets[api_schema] = MultiSchemaPropertiesWidget(
            f"{api_schema} Properties", Usd.Typed, [], api_schemas=[api_schema]
        )

    def _schema_ui_group(self, api_schema: str) -> str | None:
        """Return a UI group key for *api_schema*, or ``None`` for the default behaviour.

        When two schemas share the same instance name **and** return the same non-None
        string here, their properties are merged into a single frame labelled
        ``"{Instance} [{group key}]"``.  Returning ``None`` preserves the current
        per-schema grouping (``"{Instance} [{schema display group}]"``).

        Override in subclasses to declare merge groups::

            _SCHEMA_UI_GROUPS = {"OmniSciArrayAPI": "Array", "OmniSciFieldAPI": "Array"}

            def _schema_ui_group(self, api_schema):
                return self._SCHEMA_UI_GROUPS.get(api_schema)
        """
        return None

    def _build_schema_attr_names(self):
        self._schema_attr_names = set()
        self._ordered_schema_attr_names = []
        self._instance_names = {}
        self._prop_schemas = {}  # prop_name -> api_schema
        schema_reg = Usd.SchemaRegistry()
        for prim_path in self._payload:
            prim = self._get_prim(prim_path)

            if not prim:
                return False

            for api_schema_full in [prim.GetTypeName()] + list(prim.GetAppliedSchemas()):
                api_schema, api_instance = schema_reg.GetTypeNameAndInstance(api_schema_full)
                if self._accepts_schema(api_schema):
                    if api_schema not in self._multi_schema_properties_widgets:
                        self._add_multi_schema_properties_widget(api_schema)
                    defn = schema_reg.FindAppliedAPIPrimDefinition(api_schema)
                    defn = defn or schema_reg.FindConcretePrimDefinition(api_schema)
                    if defn:
                        api_prop_names = defn.GetPropertyNames()
                        if api_instance:
                            api_prop_names = [
                                name.replace("__INSTANCE_NAME__", api_instance) for name in api_prop_names
                            ]
                            for name in api_prop_names:
                                self._instance_names[name] = api_instance
                        for name in api_prop_names:
                            self._prop_schemas[name] = api_schema
                        self._schema_attr_names.update(api_prop_names)
                        self._ordered_schema_attr_names.extend(api_prop_names)

        return len(self._schema_attr_names) > 0

    def _filter_props_to_build(self, props):
        if len(props) == 0:
            return props

        self._build_schema_attr_names()
        return [prop for prop in props if prop.GetName() in self._schema_attr_names]

    def _customize_props_layout(self, props):
        for prop in props:
            if prop.prop_name in self._instance_names:
                instance_name = self._instance_names[prop.prop_name]
                instance_label = f"{instance_name[0].upper()}{instance_name[1:]}"
                api_schema = self._prop_schemas.get(prop.prop_name)
                ui_group = self._schema_ui_group(api_schema) if api_schema else None
                if ui_group is None:
                    group = f"{instance_label} [{prop.display_group}]"
                else:
                    group = f"{instance_label} [{ui_group}]" if ui_group else instance_label
                prop.override_display_group(group)

            if prop.prop_name.endswith(":fieldNames"):
                prop.build_fn = build_field_names_widget
            elif prop.prop_name.startswith("cae:array:expression:") and prop.prop_name.endswith(":expression"):
                prop.build_fn = build_array_expression_widget

        # sort props to be in the order of self._ordered_schema_attr_names
        props.sort(key=lambda p: self._ordered_schema_attr_names.index(p.prop_name))

        # Group properties with the same instance name together when first encountered
        reordered_props = []
        processed = set()

        for prop in props:
            if prop.prop_name in processed:
                continue

            reordered_props.append(prop)
            processed.add(prop.prop_name)

            # If this property has an instance name, add all other properties with the same instance name
            if prop.prop_name in self._instance_names:
                instance_name = self._instance_names[prop.prop_name]
                for other_prop in props:
                    if (
                        other_prop.prop_name not in processed
                        and other_prop.prop_name in self._instance_names
                        and self._instance_names[other_prop.prop_name] == instance_name
                    ):
                        reordered_props.append(other_prop)
                        processed.add(other_prop.prop_name)

        return super()._customize_props_layout(reordered_props)

    def _build_framestack(self, prefix, display_group):
        """Overridden to collapse certain frames by default. This avoid clutter in the property window
        with rarely modified property groups."""
        frame, stack, wid = super()._build_framestack(prefix, display_group)
        suffixes = ["[Array]", "[Rescale Range]", "[Configure XAC Shader]", "[Configure Flow Environment]"]
        if frame is not None and any(wid.endswith(suffix) for suffix in suffixes):
            frame.collapsed = True
        return frame, stack, wid


class CaePropertiesWidget(SchemaPropertiesWidget):
    """Properties widget for Cae* API schemas."""

    def __init__(self, title: str):
        super().__init__(title)
        self._operator_pipelines_section = None
        self._operator_pipelines_built = False

    def on_new_payload(self, payload):
        if not super().on_new_payload(payload):
            return False

        self._operator_pipelines_section = None
        # temporarily disable operator pipelines section until it's ready
        # if len(self._payload) == 1 and CaeOperatorPipelinesSection.accepts_prim(...):
        #     self._operator_pipelines_section = CaeOperatorPipelinesSection(...)

        return True

    def _accepts_schema(self, api_schema: str) -> bool:
        return api_schema.startswith("Cae")

    def build_items(self):
        self._operator_pipelines_built = False
        super().build_items()
        if self._operator_pipelines_section and not self._operator_pipelines_built:
            self._build_operator_pipelines_section()

    def _build_framestack(self, prefix, display_group):
        frame, stack, wid = super()._build_framestack(prefix, display_group)
        if self._operator_pipelines_section and not self._operator_pipelines_built and str(wid).endswith("Operator"):
            self._build_operator_pipelines_section()
        return frame, stack, wid

    def _build_operator_pipelines_section(self):
        self._operator_pipelines_built = True
        for instance_name in self._operator_pipelines_section.instance_names:
            _, stack, _ = super()._build_framestack(
                "",
                UiDisplayGroup(self._operator_pipelines_section.frame_title(instance_name), False),
            )
            with stack:
                self._operator_pipelines_section.build_items(instance_name)


class RtwtPropertiesWidget(SchemaPropertiesWidget):
    """Properties widget for Rtwt* API schemas."""

    def _accepts_schema(self, api_schema: str) -> bool:
        return api_schema.startswith("Rtwt")


class _OmniSciArraysSection:
    """Summarize OmniSci array instances on the selected prim."""

    _ARRAY_API = "OmniSciArrayAPI"
    _FIELD_API = "OmniSciFieldAPI"
    _EXPRESSION_API = "CaeArrayExpressionAPI"
    _COLUMNS = (
        {"key": "field_name", "label": "Field Name", "weight": 2},
        {"key": "association", "label": "Association", "weight": 1},
        {"key": "temporal", "label": "Time Samples", "weight": 1},
    )

    @classmethod
    def collect_rows(cls, prim: Usd.Prim) -> tuple[list[dict], list[dict]]:
        array_instances = set(usd_utils.get_instances(prim, cls._ARRAY_API))
        field_instances = set(usd_utils.get_instances(prim, cls._FIELD_API))
        expression_instances = {
            name
            for name in usd_utils.get_instances(prim, cls._EXPRESSION_API)
            if bool(cae.ArrayExpressionAPI(prim, name).GetEnabledAttr().Get())
        }

        field_rows = [cls._build_field_row(prim, name) for name in sorted(field_instances)]
        field_rows.extend(cls._build_expression_row(prim, name) for name in sorted(expression_instances))
        array_rows = [cls._build_array_row(prim, name) for name in sorted(array_instances - field_instances)]
        return field_rows, array_rows

    @staticmethod
    def _get_attr_value(prim: Usd.Prim, attr_name: str, default: str = "") -> str:
        attr = prim.GetAttribute(attr_name)
        if not attr:
            return default
        value = attr.Get()
        return str(value) if value is not None else default

    @staticmethod
    def _has_temporal_values(prim: Usd.Prim, instance_name: str) -> bool:
        return bool(cae_simdata.get_array_time_samples(prim, instance_name))

    @classmethod
    def _build_field_row(cls, prim: Usd.Prim, instance_name: str) -> dict:
        field_name = cls._get_attr_value(prim, f"omni:sci:field:{instance_name}:name", instance_name)
        association = cls._get_attr_value(prim, f"omni:sci:field:{instance_name}:association", "none")
        temporal = "Y" if cls._has_temporal_values(prim, instance_name) else "N"
        return {
            "instance_name": instance_name,
            "field_name": field_name,
            "association": association,
            "temporal": temporal,
        }

    @classmethod
    def _build_array_row(cls, prim: Usd.Prim, instance_name: str) -> dict:
        temporal = "Y" if cls._has_temporal_values(prim, instance_name) else "N"
        return {
            "instance_name": instance_name,
            "field_name": instance_name,
            "association": "-",
            "temporal": temporal,
        }

    @classmethod
    def _build_expression_row(cls, prim: Usd.Prim, instance_name: str) -> dict:
        api = cae.ArrayExpressionAPI(prim, instance_name)
        field_name = str(api.GetDisplayNameAttr().Get() or instance_name)
        return {
            "instance_name": instance_name,
            "field_name": field_name,
            "association": "inferred",
            "temporal": "derived",
        }

    @staticmethod
    def _property_label_style():
        return get_style()["Label::label"]

    @classmethod
    def _property_header_style(cls):
        style = cls._property_label_style().copy()
        style["font"] = "${fonts}/OpenSans-SemiBold.ttf"
        return style

    @classmethod
    def _build_column_header(cls):
        style = cls._property_header_style()
        with ui.HStack(height=LABEL_HEIGHT, spacing=HORIZONTAL_SPACING):
            for column in cls._COLUMNS:
                ui.Label(column["label"], width=ui.Fraction(column["weight"]), style=style)

    @staticmethod
    def _build_header_rule():
        ui.Line(height=1, style={"color": 0xFF555555})

    @classmethod
    def _build_row(cls, row: dict, on_selected):
        style = cls._property_label_style()
        with ui.HStack(height=LABEL_HEIGHT, spacing=HORIZONTAL_SPACING):
            for column in cls._COLUMNS:
                value = row.get(column["key"], "")
                ui.Label(
                    value,
                    width=ui.Fraction(column["weight"]),
                    style=style,
                    tooltip=value,
                    mouse_pressed_fn=lambda *_, instance=row["instance_name"]: on_selected(instance),
                )

    @classmethod
    def build_items(cls, field_rows: list[dict], array_rows: list[dict], on_selected):
        with ui.VStack(spacing=2, height=0):
            cls._build_column_header()
            cls._build_header_rule()

            for row in field_rows:
                cls._build_row(row, on_selected)

            for row in array_rows:
                cls._build_row(row, on_selected)


class OmniSciPropertiesWidget(SchemaPropertiesWidget):
    """Properties widget for OmniSci* and OmniCgns* API schemas.

    OmniSciArrayAPI and OmniSciFieldAPI instances with the same instance name are
    merged into a single UI group labelled ``"{Instance} [Array]"``.
    """

    _SCHEMA_UI_GROUPS: dict[str, str] = {
        "OmniSciArrayAPI": "Array",
        "OmniSciFieldAPI": "Array",
    }

    def __init__(self, title: str):
        super().__init__(title)
        self._array_section_field_rows = []
        self._array_section_array_rows = []
        self._array_details_section = None
        self._array_details_frame = None

    def on_new_payload(self, payload):
        if self._array_details_section:
            self._array_details_section.destroy()
            self._array_details_section = None
        self._array_details_frame = None

        if not super().on_new_payload(payload):
            return False

        self._array_section_field_rows = []
        self._array_section_array_rows = []
        self._array_details_section = None
        self._array_details_frame = None

        if len(self._payload) == 1:
            stage = omni.usd.get_context().get_stage()
            prim = stage.GetPrimAtPath(self._payload[0]) if stage else None
            if prim:
                self._array_section_field_rows, self._array_section_array_rows = _OmniSciArraysSection.collect_rows(
                    prim
                )
                details_section = OmniSciArrayDetailsSection(prim)
                if details_section.has_arrays:
                    self._array_details_section = details_section

        return True

    def clean(self):
        if self._array_details_section:
            self._array_details_section.destroy()
            self._array_details_section = None
        self._array_details_frame = None
        super().clean()

    def _accepts_schema(self, api_schema: str) -> bool:
        return api_schema.startswith("OmniSci") or api_schema.startswith("OmniCgns")

    def _schema_ui_group(self, api_schema: str) -> str | None:
        return self._SCHEMA_UI_GROUPS.get(api_schema)

    def build_items(self):
        if self._array_section_field_rows or self._array_section_array_rows:
            _, stack, _ = self._build_framestack("", UiDisplayGroup("Arrays", False))
            with stack:
                _OmniSciArraysSection.build_items(
                    self._array_section_field_rows,
                    self._array_section_array_rows,
                    self._on_array_selected,
                )
        if self._array_details_section:
            self._array_details_frame, stack, _ = self._build_framestack("", UiDisplayGroup("Array Details", True))
            with stack:
                self._array_details_section.build_items()
        super().build_items()

    def _on_array_selected(self, instance_name: str):
        if not self._array_details_section or not self._array_details_section.select_instance(instance_name):
            return
        if self._array_details_frame is not None:
            self._array_details_frame.collapsed = False


class CaeGeomPrimSchemeDelegate(GeomPrimSchemeDelegate):
    """A custom scheme delegate that inserts CAE, RTWT, and OmniSci widgets
    before the "geometry" widget (or after "path", or at the front as a fallback).

    Usage::

        property_window.register_scheme_delegate("prim", "xformable_prim", CaeGeomPrimSchemeDelegate())
    """

    # Widget names to inject, in display order.
    _CAE_WIDGETS = ["cae", "rtwt", "omni_sci"]

    def get_widgets(self, payload) -> list[str]:
        widgets = super().get_widgets(payload)
        if "geometry" in widgets:
            idx = widgets.index("geometry")
        elif "path" in widgets:
            idx = widgets.index("path") + 1
        else:
            return self._CAE_WIDGETS + widgets
        widgets[idx:idx] = self._CAE_WIDGETS
        return widgets
