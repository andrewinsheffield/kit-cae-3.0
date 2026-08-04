# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Custom property panel widget for the token[] fieldNames attribute on CaeVizFieldSelectionAPI.

Mirrors the sdf_asset_path_array_builder pattern: a TreeView of editable rows with drag-to-
reorder, a suggestions button and a remove button per row, plus an "Add Field…" button that
adds an empty editable row.
"""

__all__ = ["build_field_names_widget"]

import asyncio
from functools import lru_cache
from typing import List

import omni.ui as ui
from omni.cae.viz.utils import get_available_fields
from omni.kit.property.usd import widgets as _usd_widgets
from omni.kit.property.usd.usd_attribute_model import UsdAttributeModel
from omni.kit.property.usd.usd_property_widget_builder import UsdPropertiesWidgetBuilder
from omni.kit.window.property.templates import HORIZONTAL_SPACING, LABEL_HEIGHT
from pxr import Sdf, Usd, Vt


@lru_cache()
def _get_plus_glyph():
    return ui.get_custom_glyph_code("${glyphs}/menu_context.svg")


async def _get_common_available_fields(stage: Usd.Stage, prim_paths: List[Sdf.Path]):
    per_prim_fields = await asyncio.gather(*(get_available_fields(stage, prim_path) for prim_path in prim_paths))
    if not per_prim_fields:
        return []

    per_prim_by_name = [{field_info.name: field_info for field_info in fields} for fields in per_prim_fields]
    common_names = set(per_prim_by_name[0])
    for fields in per_prim_by_name[1:]:
        common_names &= fields.keys()

    return sorted((per_prim_by_name[0][name] for name in common_names), key=lambda field_info: field_info.name)


# ---------------------------------------------------------------------------
# Single-entry model — one element of the token[] array
# ---------------------------------------------------------------------------


class _TokenArraySingleEntryModel(UsdAttributeModel):
    """A UsdAttributeModel that exposes a single index of a token[] attribute.

    Analogous to SdfAssetPathArrayAttributeSingleEntryModel.
    """

    def __init__(
        self,
        stage: Usd.Stage,
        attribute_paths: List[Sdf.Path],
        index: int,
        self_refresh: bool,
        metadata: dict,
    ):
        self._index = index
        super().__init__(stage, attribute_paths, self_refresh, metadata)

    @property
    def index(self) -> int:
        return self._index

    def get_value_as_string(self, elide_big_array=True) -> str:
        self._update_value()
        if self._value is None or self._index >= len(self._value):
            return ""
        return str(self._value[self._index])

    def get_value(self):
        self._update_value()
        if self._value is None or self._index >= len(self._value):
            return ""
        return str(self._value[self._index])

    def set_value(self, value, comp: int = -1):
        self._update_value()
        if self._value is None or self._index >= len(self._value):
            return
        vec = list(self._value)
        vec[self._index] = str(value)
        super().set_value(Vt.TokenArray(vec))


# ---------------------------------------------------------------------------
# Tree item — wraps a single-entry model
# ---------------------------------------------------------------------------


class _FieldNameItem(ui.AbstractItem):
    """Single row in the TreeView; analogous to SdfAssetPathItem."""

    def __init__(self, model: _TokenArraySingleEntryModel):
        super().__init__()
        self.model = model

    def destroy(self):
        if self.model:
            self.model.clean()
            self.model = None


# ---------------------------------------------------------------------------
# Item model — manages the flat list of entries
# ---------------------------------------------------------------------------


class _TokenArrayItemModel(ui.AbstractItemModel):
    """AbstractItemModel for a token[] attribute; analogous to SdfAssetPathArrayAttributeItemModel.

    The parent UsdPropertiesWidget calls clean(), _set_dirty(), and _on_usd_changed() on this
    object; those calls are forwarded to the inner UsdAttributeModel and each entry model.
    """

    def __init__(
        self,
        stage: Usd.Stage,
        attribute_paths: List[Sdf.Path],
        self_refresh: bool,
        metadata: dict,
        delegate,
    ):
        super().__init__()
        self._delegate = delegate  # keep alive so TreeView doesn't GC it
        self._value_model = UsdAttributeModel(stage, attribute_paths, False, metadata)
        self._entries: List[_FieldNameItem] = []
        self._repopulate_entries(self._value_model.get_value())

    # -- public interface expected by UsdPropertiesWidget --

    @property
    def value_model(self) -> UsdAttributeModel:
        return self._value_model

    def clean(self):
        self._delegate = None
        for e in self._entries:
            e.destroy()
        self._entries.clear()
        if self._value_model:
            self._value_model.clean()
            self._value_model = None

    def get_value(self, *args, **kwargs):
        return self._value_model.get_value(*args, **kwargs)

    def set_value(self, *args, **kwargs):
        return self._value_model.set_value(*args, **kwargs)

    # -- AbstractItemModel interface --

    def get_item_children(self, item):
        return [] if item else self._entries

    def get_item_value_model_count(self, item):
        return 1

    def get_item_value_model(self, item, column_id):
        """Returns (entry_model, full_array_model) for use by the delegate."""
        return (item.model, self._value_model)

    def get_drag_mime_data(self, item):
        return str(item.model.index)

    def drop_accepted(self, target_item, source, drop_location=-1):
        try:
            self._entries.index(source)
        except ValueError:
            return False
        return not target_item and drop_location >= 0

    def drop(self, target_item, source, drop_location=-1):
        try:
            src_id = self._entries.index(source)
        except ValueError:
            return
        if src_id == drop_location:
            return
        value = list(self._value_model.get_value())
        moved = value[src_id]
        del value[src_id]
        if drop_location > len(value):
            value.append(moved)
        else:
            if src_id < drop_location:
                drop_location -= 1
            value.insert(drop_location, moved)
        self._value_model.set_value(Vt.TokenArray(value))

    # -- USD change forwarding --

    def _on_usd_changed(self, *args, **kwargs):  # pylint: disable=protected-access
        self._value_model._on_usd_changed(*args, **kwargs)
        for e in self._entries:
            e.model._on_usd_changed(*args, **kwargs)

    def _set_dirty(self, *args, **kwargs):  # pylint: disable=protected-access
        self._value_model._set_dirty(*args, **kwargs)
        new_value = self._value_model.get_value()
        if new_value is None or len(new_value) != len(self._entries):
            self._repopulate_entries(new_value or [])
        else:
            for e in self._entries:
                e.model._set_dirty(*args, **kwargs)

    # -- internal --

    def _repopulate_entries(self, value):
        for e in self._entries:
            e.destroy()
        self._entries.clear()
        attr_paths = self._value_model.get_attribute_paths()
        stage = self._value_model.stage
        metadata = self._value_model.metadata
        for i in range(len(value)):
            entry_model = _TokenArraySingleEntryModel(stage, attr_paths, i, False, metadata)
            self._entries.append(_FieldNameItem(entry_model))
        self._item_changed(None)


# ---------------------------------------------------------------------------
# Delegate — renders each row
# ---------------------------------------------------------------------------


class _FieldNameDelegate(ui.AbstractItemDelegate):
    """TreeView delegate for token[] field-name rows; analogous to SdfAssetPathDelegate."""

    def __init__(self, attr_name: str, widget_kwargs: dict, stage: Usd.Stage, prim_paths: List[Sdf.Path]):
        super().__init__()
        self._attr_name = attr_name
        self._widget_kwargs = widget_kwargs
        self._stage = stage
        self._prim_paths = list(prim_paths)

    def build_branch(self, model, item, column_id, level, expanded):
        pass

    def build_widget(self, model, item, column_id, level, expanded):
        with ui.VStack():
            ui.Spacer(height=2)
            with ui.ZStack():
                ui.Rectangle(name="backdrop")
                frame = ui.Frame(
                    height=0,
                    spacing=5,
                    style={
                        "Frame": {"margin_width": 2, "margin_height": 2},
                        "Button": {"background_color": 0x0},
                    },
                )
                with frame:
                    (entry_model, value_model) = model.get_item_value_model(item, column_id)
                    with ui.HStack(spacing=HORIZONTAL_SPACING, width=ui.Percent(100)):
                        # drag-to-reorder grab area (three vertical lines)
                        with ui.VStack(spacing=0, height=ui.Percent(100), width=0):
                            ui.Spacer()
                            with ui.HStack(
                                identifier=(f"token_array_{self._attr_name}" f"[{entry_model.index}].reorder_grab"),
                                height=LABEL_HEIGHT,
                            ):
                                for _ in range(3):
                                    ui.Line(width=3, alignment=ui.Alignment.H_CENTER, name="grab")
                            ui.Spacer()

                        with ui.HStack(content_clipping=1):
                            ui.StringField(
                                model=entry_model,
                                height=LABEL_HEIGHT,
                                width=ui.Fraction(1),
                                **self._widget_kwargs,
                            )

                            ui.Spacer(width=HORIZONTAL_SPACING)

                            # Suggestions button

                            def _show_suggestions(em=entry_model):
                                async def _async(em=em):
                                    suggestions = await _get_common_available_fields(self._stage, self._prim_paths)
                                    if not suggestions:
                                        return
                                    self._menu = ui.Menu("Field suggestions")
                                    with self._menu:
                                        for field_info in suggestions:
                                            ui.MenuItem(
                                                (
                                                    f"{field_info.name} ({field_info.label})"
                                                    if field_info.label != field_info.name
                                                    else field_info.name
                                                ),
                                                triggered_fn=lambda n=field_info.name, m=em: m.set_value(n),
                                            )
                                    self._menu.show()

                                asyncio.ensure_future(_async())

                            dropdown_style = {
                                "image_url": "resources/glyphs/arrow_down.svg",
                                "margin": 0,
                                "padding": 0,
                            }
                            ui.Button(
                                "",
                                width=16,
                                height=ui.Percent(100),
                                fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,
                                clicked_fn=_show_suggestions,
                                style=dropdown_style,
                                tooltip="Choose from available fields",
                                identifier=f"token_array_{self._attr_name}[{entry_model.index}].suggestions",
                            )
                            ui.Spacer(width=HORIZONTAL_SPACING)

                            remove_style = {
                                "image_url": str(_usd_widgets.ICON_PATH.joinpath("remove.svg")),
                                "margin": 0,
                                "padding": 0,
                            }
                            ui.Button(
                                "",
                                width=12,
                                height=ui.Percent(100),
                                fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,
                                clicked_fn=lambda idx=entry_model.index, vm=value_model: vm.set_value(
                                    Vt.TokenArray(list(vm.get_value())[:idx] + list(vm.get_value())[idx + 1 :])
                                ),
                                name="remove",
                                style=remove_style,
                                tooltip="Remove",
                                identifier=f"token_array_{self._attr_name}[{entry_model.index}].remove",
                            )
            ui.Spacer(height=2)


# ---------------------------------------------------------------------------
# Builder function — called as prop.build_fn by CaePropertiesWidget
# ---------------------------------------------------------------------------


def build_field_names_widget(
    stage: Usd.Stage,
    attr_name: str,
    metadata: dict,
    property_type,
    prim_paths: List[Sdf.Path],
    additional_label_kwargs=None,
    additional_widget_kwargs=None,
):
    """Build a token[] widget for fieldNames that mirrors sdf_asset_path_array_builder.

    - Each existing value is shown as an editable row with a drag handle, a suggestions button
      (populated on click with fields common to all selected prims), and a remove button.
    - "Add Field…" always adds an empty editable row.
    """
    widget_kwargs = {"name": "models"}
    if additional_widget_kwargs:
        widget_kwargs.update(additional_widget_kwargs)

    attribute_paths = [p.AppendProperty(attr_name) for p in prim_paths]
    delegate = _FieldNameDelegate(attr_name, widget_kwargs, stage, prim_paths)
    item_model = _TokenArrayItemModel(stage, attribute_paths, False, metadata, delegate)

    models = []
    with ui.HStack(spacing=HORIZONTAL_SPACING):
        label = UsdPropertiesWidgetBuilder.create_label(attr_name, metadata, additional_label_kwargs)

        with ui.VStack():
            tree_frame = ui.HStack(spacing=HORIZONTAL_SPACING, content_clipping=1)
            with tree_frame:
                with ui.Frame(height=0):
                    tree_view = ui.TreeView(
                        item_model,
                        delegate=delegate,
                        root_visible=False,
                        header_visible=False,
                        drop_between_items=True,
                        style={
                            "TreeView:selected": {"background_color": 0x00},
                            "TreeView": {"background_color": 0xFFFFFFFF},
                        },
                    )
                    tree_view.identifier = f"token_array_{attr_name}"
                ui.Spacer(width=12)

            with ui.HStack(spacing=HORIZONTAL_SPACING, height=LABEL_HEIGHT):
                with ui.ZStack():

                    def _add_entry():
                        val = list(item_model.get_value() or [])
                        val.append("")
                        item_model.set_value(Vt.TokenArray(val))

                    button = ui.Button(
                        f"{_get_plus_glyph()} Add Field",
                        clicked_fn=_add_entry,
                    )
                    button.identifier = f"token_array_{attr_name}.add_field"
                    mixed_overlay = UsdPropertiesWidgetBuilder.create_mixed_text_overlay(content_clipping=1)

                def _on_value_changed(m):
                    value = m.get_value()
                    tree_frame.visible = not m.is_ambiguous() and bool(value)
                    button.visible = not m.is_ambiguous()

                item_model.value_model.add_value_changed_fn(_on_value_changed)
                _on_value_changed(item_model.value_model)

                UsdPropertiesWidgetBuilder.create_control_state(
                    item_model.value_model,
                    value_widget=tree_view,
                    mixed_overlay=mixed_overlay,
                    label=label,
                    **widget_kwargs,
                )

    models.append(item_model)
    return models
