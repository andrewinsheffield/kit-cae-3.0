# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Staged, reorderable editor for dataset preprocessing pipelines on CAE operators."""

__all__ = ["CaeOperatorPipelinesSection"]

from dataclasses import dataclass
from functools import lru_cache
from logging import getLogger

import omni.ui as ui
from omni.kit.property.usd import widgets as _usd_widgets
from omni.kit.window.property.style import get_style
from omni.kit.window.property.templates import HORIZONTAL_SPACING, LABEL_HEIGHT
from pxr import Sdf, Usd

logger = getLogger(__name__)

_OPERATOR_SCHEMA = "CaeVizOperatorAPI"
_DATASET_SELECTION_SCHEMA = "CaeVizDatasetSelectionAPI"

_PIPELINE_SCHEMAS = {
    "CaeVizDatasetAxisymmetricRepresentationAPI": "Axisymmetric Representation",
    "CaeVizDatasetDualAPI": "Dataset Dual",
    "CaeVizDatasetTransformingAPI": "Dataset Transforming",
    "CaeVizDatasetSubsetAPI": "Dataset Subset",
    "CaeVizDatasetGaussianSplattingAPI": "Gaussian Splatting",
    "CaeVizDatasetVoxelizationAPI": "Dataset Voxelization",
    "CaeVizDatasetTemporalTraitsAPI": "Temporal Traits",
}
_PIPELINE_SCHEMA_ORDER = tuple(_PIPELINE_SCHEMAS)


@lru_cache()
def _get_plus_glyph():
    return ui.get_custom_glyph_code("${glyphs}/menu_context.svg")


@dataclass(frozen=True)
class _Pipeline:
    schema: str
    instance: str

    @property
    def token(self) -> str:
        return f"{self.schema}:{self.instance}"


def _split_applied_schema(applied_schema) -> tuple[str, str]:
    schema, sep, instance = str(applied_schema).partition(":")
    return schema, instance if sep else ""


def _is_pipeline_token(token: str) -> bool:
    schema, instance = _split_applied_schema(token)
    return bool(instance) and schema in _PIPELINE_SCHEMAS


def _pipeline_label(pipeline: _Pipeline) -> str:
    return _PIPELINE_SCHEMAS.get(pipeline.schema, pipeline.schema)


@lru_cache()
def _schema_documentation(api_schema: str) -> str:
    try:
        registry = Usd.SchemaRegistry()
        defn = registry.FindAppliedAPIPrimDefinition(api_schema)
        defn = defn or registry.FindConcretePrimDefinition(api_schema)
        if defn:
            doc = defn.GetDocumentation()
            if doc:
                return doc.strip()
    except Exception:
        logger.exception("Failed to read schema documentation for %s", api_schema)
    return api_schema


def _pipeline_tooltip(pipeline: _Pipeline) -> str:
    return f"{pipeline.token}\n\n{_schema_documentation(pipeline.schema)}"


def _instance_label(instance_name: str) -> str:
    return f"{instance_name[0].upper()}{instance_name[1:]}" if instance_name else ""


def _identifier_instance(instance_name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in instance_name)


def _dedupe(tokens: list[str]) -> list[str]:
    result = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        result.append(token)
        seen.add(token)
    return result


def _create_explicit_token_list_op(tokens: list[str]):
    try:
        return Sdf.TokenListOp.CreateExplicit(tokens)
    except AttributeError:
        list_op = Sdf.TokenListOp()
        list_op.explicitItems = tokens
        return list_op


def _collect_pipelines(prim: Usd.Prim) -> list[_Pipeline]:
    pipelines = []
    for applied_schema in prim.GetAppliedSchemas():
        schema, instance = _split_applied_schema(applied_schema)
        if instance and schema in _PIPELINE_SCHEMAS:
            pipelines.append(_Pipeline(schema, instance))
    return pipelines


def _collect_dataset_selection_instances(prim: Usd.Prim) -> list[str]:
    instances = []
    for applied_schema in prim.GetAppliedSchemas():
        schema, instance = _split_applied_schema(applied_schema)
        if schema == _DATASET_SELECTION_SCHEMA and instance:
            instances.append(instance)
    return instances


def _compose_api_schema_order(prim: Usd.Prim, pipelines: list[_Pipeline]) -> list[str]:
    pipeline_tokens = [pipeline.token for pipeline in pipelines]
    non_pipeline_tokens = [str(schema) for schema in prim.GetAppliedSchemas() if not _is_pipeline_token(str(schema))]

    ordered_tokens = []
    inserted = False
    for token in non_pipeline_tokens:
        ordered_tokens.append(token)
        if token == _OPERATOR_SCHEMA:
            ordered_tokens.extend(pipeline_tokens)
            inserted = True

    if not inserted:
        ordered_tokens.extend(pipeline_tokens)

    return _dedupe(ordered_tokens)


def _author_api_schema_order(prim: Usd.Prim, pipelines: list[_Pipeline]):
    ordered_tokens = _compose_api_schema_order(prim, pipelines)
    with Sdf.ChangeBlock():
        token_list_op = _create_explicit_token_list_op(ordered_tokens)
        if prim.SetMetadata("apiSchemas", token_list_op) is False:
            raise RuntimeError(f"Failed to set apiSchemas on {prim.GetPath()}")


def _author_api_schema_order_with_api_calls(prim: Usd.Prim, pipelines: list[_Pipeline]):
    remove_api = getattr(prim, "RemoveAPI", None)
    if remove_api is None:
        raise RuntimeError("Usd.Prim.RemoveAPI is not available")

    with Sdf.ChangeBlock():
        for pipeline in _collect_pipelines(prim):
            remove_api(pipeline.schema, pipeline.instance)
        for pipeline in reversed(pipelines):
            prim.ApplyAPI(pipeline.schema, pipeline.instance)


class _PipelineItem(ui.AbstractItem):
    def __init__(self, pipeline: _Pipeline):
        super().__init__()
        self.pipeline = pipeline


class _PipelineListModel(ui.AbstractItemModel):
    def __init__(self, pipelines: list[_Pipeline], changed_fn):
        super().__init__()
        self._changed_fn = changed_fn
        self._items: list[_PipelineItem] = []
        self.set_pipelines(pipelines, notify=False)

    @property
    def pipelines(self) -> list[_Pipeline]:
        return [item.pipeline for item in self._items]

    def set_pipelines(self, pipelines: list[_Pipeline], notify: bool = True):
        self._items = [_PipelineItem(pipeline) for pipeline in pipelines]
        self._item_changed(None)
        if notify:
            self._changed_fn()

    def add_pipeline(self, pipeline: _Pipeline):
        if pipeline in self.pipelines:
            return
        self._items.append(_PipelineItem(pipeline))
        self._item_changed(None)
        self._changed_fn()

    def remove_item(self, item: _PipelineItem):
        try:
            self._items.remove(item)
        except ValueError:
            return
        self._item_changed(None)
        self._changed_fn()

    def index(self, item: _PipelineItem) -> int:
        return self._items.index(item)

    def get_item_children(self, item):
        return [] if item else self._items

    def get_item_value_model_count(self, item):
        return 1

    def get_item_value_model(self, item, column_id):
        return None

    def get_drag_mime_data(self, item):
        return str(self.index(item))

    def drop_accepted(self, target_item, source, drop_location=-1):
        try:
            self._items.index(source)
        except ValueError:
            return False
        return not target_item and drop_location >= 0

    def drop(self, target_item, source, drop_location=-1):
        try:
            source_index = self._items.index(source)
        except ValueError:
            return
        if source_index == drop_location:
            return

        item = self._items.pop(source_index)
        if drop_location > len(self._items):
            self._items.append(item)
        else:
            if source_index < drop_location:
                drop_location -= 1
            self._items.insert(drop_location, item)
        self._item_changed(None)
        self._changed_fn()


class _PipelineDelegate(ui.AbstractItemDelegate):
    def __init__(self, model: _PipelineListModel, instance_name: str):
        super().__init__()
        self._model = model
        self._identifier_instance = _identifier_instance(instance_name)

    def build_branch(self, model, item, column_id, level, expanded):
        pass

    def build_widget(self, model, item, column_id, level, expanded):
        pipeline = item.pipeline
        label_style = get_style()["Label::label"]

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
                    with ui.HStack(spacing=HORIZONTAL_SPACING, width=ui.Percent(100)):
                        with ui.VStack(spacing=0, height=ui.Percent(100), width=0):
                            ui.Spacer()
                            with ui.HStack(
                                identifier=(
                                    f"cae_operator_pipelines[{self._identifier_instance}]"
                                    f"[{self._model.index(item)}].reorder_grab"
                                ),
                                height=LABEL_HEIGHT,
                            ):
                                for _ in range(3):
                                    ui.Line(width=3, alignment=ui.Alignment.H_CENTER, name="grab")
                            ui.Spacer()

                        ui.Label(
                            _pipeline_label(pipeline),
                            width=ui.Fraction(2),
                            height=LABEL_HEIGHT,
                            style=label_style,
                            tooltip=_pipeline_tooltip(pipeline),
                        )

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
                            clicked_fn=lambda item=item: self._model.remove_item(item),
                            name="remove",
                            style=remove_style,
                            tooltip="Remove",
                            identifier=(
                                f"cae_operator_pipelines[{self._identifier_instance}]"
                                f"[{self._model.index(item)}].remove"
                            ),
                        )
            ui.Spacer(height=2)


class CaeOperatorPipelinesSection:
    """Builds the staged API-schema pipeline editor for a single operator prim."""

    def __init__(self, prim: Usd.Prim):
        self._prim = prim
        self._instances = _collect_dataset_selection_instances(prim)
        self._current_pipelines = {
            instance: self._pipelines_for_instance(_collect_pipelines(prim), instance) for instance in self._instances
        }
        self._models = {
            instance: _PipelineListModel(self._current_pipelines[instance], self._on_model_changed)
            for instance in self._instances
        }
        self._delegates = {
            instance: _PipelineDelegate(self._models[instance], instance) for instance in self._instances
        }
        self._menu = None
        self._tree_frames = {}
        self._empty_labels = {}
        self._add_buttons = {}
        self._commit_buttons = {}
        self._discard_buttons = {}

    @staticmethod
    def accepts_prim(prim: Usd.Prim) -> bool:
        return _OPERATOR_SCHEMA in {str(schema) for schema in prim.GetAppliedSchemas()}

    @staticmethod
    def frame_title(instance_name: str) -> str:
        return f"{_instance_label(instance_name)} [Pipelines]"

    @staticmethod
    def _pipelines_for_instance(pipelines: list[_Pipeline], instance_name: str) -> list[_Pipeline]:
        return [pipeline for pipeline in pipelines if pipeline.instance == instance_name]

    @property
    def instance_names(self) -> list[str]:
        return list(self._instances)

    def build_items(self, instance_name: str):
        model = self._models[instance_name]
        delegate = self._delegates[instance_name]
        identifier_instance = _identifier_instance(instance_name)

        with ui.VStack(spacing=2, height=0):
            self._build_header()

            tree_frame = ui.HStack(spacing=HORIZONTAL_SPACING, content_clipping=1)
            self._tree_frames[instance_name] = tree_frame
            with tree_frame:
                with ui.Frame(height=0):
                    tree_view = ui.TreeView(
                        model,
                        delegate=delegate,
                        root_visible=False,
                        header_visible=False,
                        drop_between_items=True,
                        style={
                            "TreeView:selected": {"background_color": 0x00},
                            "TreeView": {"background_color": 0xFFFFFFFF},
                        },
                    )
                    tree_view.identifier = f"cae_operator_pipelines[{identifier_instance}]"
                ui.Spacer(width=12)

            self._empty_labels[instance_name] = ui.Label(
                "No pipelines",
                height=LABEL_HEIGHT,
                style=get_style()["Label::label"],
            )

            with ui.HStack(spacing=HORIZONTAL_SPACING, height=LABEL_HEIGHT):
                self._add_buttons[instance_name] = ui.Button(
                    f"{_get_plus_glyph()} Add",
                    clicked_fn=lambda instance_name=instance_name: self._show_add_menu(instance_name),
                )
                self._add_buttons[instance_name].identifier = f"cae_operator_pipelines[{identifier_instance}].add"
                ui.Spacer()
                self._discard_buttons[instance_name] = ui.Button(
                    "Discard",
                    clicked_fn=lambda instance_name=instance_name: self._discard(instance_name),
                )
                self._discard_buttons[instance_name].identifier = (
                    f"cae_operator_pipelines[{identifier_instance}].discard"
                )
                self._commit_buttons[instance_name] = ui.Button("Commit", clicked_fn=self._commit)
                self._commit_buttons[instance_name].identifier = f"cae_operator_pipelines[{identifier_instance}].commit"

            self._refresh_control_state(instance_name)

    @staticmethod
    def _build_header():
        style = get_style()["Label::label"].copy()
        style["font"] = "${fonts}/OpenSans-SemiBold.ttf"
        with ui.HStack(height=LABEL_HEIGHT, spacing=HORIZONTAL_SPACING):
            ui.Spacer(width=12)
            ui.Label("Pipeline", width=ui.Fraction(1), style=style)
            ui.Spacer(width=12)
        ui.Line(height=1, style={"color": 0xFF555555})

    def _on_model_changed(self):
        self._refresh_control_state()

    def _is_dirty(self, instance_name: str) -> bool:
        return self._models[instance_name].pipelines != self._current_pipelines[instance_name]

    def _has_dirty_pipelines(self) -> bool:
        return any(self._is_dirty(instance) for instance in self._instances)

    def _can_stage(self, pipeline: _Pipeline) -> bool:
        model = self._models[pipeline.instance]
        if pipeline in model.pipelines:
            return False
        if pipeline in self._current_pipelines[pipeline.instance]:
            return True
        try:
            return self._prim.CanApplyAPI(pipeline.schema, pipeline.instance)
        except Exception:
            logger.exception("Failed to validate %s on %s", pipeline.token, self._prim.GetPath())
            return False

    def _available_pipelines(self, instance_name: str) -> list[_Pipeline]:
        candidates = []
        for schema in _PIPELINE_SCHEMA_ORDER:
            pipeline = _Pipeline(schema, instance_name)
            if self._can_stage(pipeline):
                candidates.append(pipeline)
        return candidates

    def _show_add_menu(self, instance_name: str):
        candidates = self._available_pipelines(instance_name)
        if not candidates:
            return

        self._menu = ui.Menu(f"Add {_instance_label(instance_name)} Pipeline")
        with self._menu:
            for pipeline in candidates:
                ui.MenuItem(
                    _pipeline_label(pipeline),
                    triggered_fn=lambda pipeline=pipeline: self._models[pipeline.instance].add_pipeline(pipeline),
                )
        self._menu.show()

    def _discard(self, instance_name: str):
        self._models[instance_name].set_pipelines(self._current_pipelines[instance_name])

    def _commit(self):
        staged_pipelines = self._all_staged_pipelines()
        try:
            _author_api_schema_order(self._prim, staged_pipelines)
        except Exception:
            logger.warning("Falling back to ApplyAPI/RemoveAPI for CAE pipeline commit.", exc_info=True)
            try:
                _author_api_schema_order_with_api_calls(self._prim, staged_pipelines)
            except Exception:
                logger.exception("Failed to commit CAE pipeline changes on %s", self._prim.GetPath())
                return

        self._current_pipelines = {
            instance: self._pipelines_for_instance(staged_pipelines, instance) for instance in self._instances
        }
        self._refresh_control_state()

    def _all_staged_pipelines(self) -> list[_Pipeline]:
        visible_instances = set(self._instances)
        hidden_pipelines = [
            pipeline for pipeline in _collect_pipelines(self._prim) if pipeline.instance not in visible_instances
        ]
        staged_pipelines = []
        for instance in self._instances:
            staged_pipelines.extend(self._models[instance].pipelines)
        return hidden_pipelines + staged_pipelines

    def _refresh_control_state(self, instance_name: str | None = None):
        instances = [instance_name] if instance_name else self._instances
        has_dirty_pipelines = self._has_dirty_pipelines()
        for instance in instances:
            has_pipelines = bool(self._models[instance].pipelines)
            is_dirty = self._is_dirty(instance)

            if tree_frame := self._tree_frames.get(instance):
                tree_frame.visible = has_pipelines
            if empty_label := self._empty_labels.get(instance):
                empty_label.visible = not has_pipelines
            if add_button := self._add_buttons.get(instance):
                add_button.enabled = bool(self._available_pipelines(instance))
            if commit_button := self._commit_buttons.get(instance):
                commit_button.enabled = has_dirty_pipelines
            if discard_button := self._discard_buttons.get(instance):
                discard_button.enabled = is_dirty
