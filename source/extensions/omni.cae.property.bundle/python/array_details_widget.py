# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Array Details section for the OmniSci property panel.

The selected dataset prim carries arrays as multiple-apply API schema instances
(``OmniSciArrayAPI:<instance>`` / ``OmniSciFieldAPI:<instance>``). This section
adds a dropdown to pick one array instance and inspect its metadata.

Cheap metadata (name, association, device, dtype) is read directly from USD
attributes and shown immediately on selection. Heavy metadata (shape, range,
scalar stats and histogram) requires materializing the array payload and is only
computed when the user clicks "Compute Details".

See ``docs/design/array_details_property_panel.md`` for the full design.
"""

__all__ = ["OmniSciArrayDetailsSection"]

import asyncio
import logging

import carb.eventdispatcher
import numpy as np
import omni.cae.simdata as cae_simdata
import omni.timeline
import omni.ui as ui
import omni.usd
from omni.cae.core import array_utils, progress, usd_utils
from omni.cae.schema import cae
from omni.cae.viz import settings as viz_settings
from omni.kit.window.property.style import get_style
from pxr import Usd

logger = logging.getLogger(__name__)

_ARRAY_API = "OmniSciArrayAPI"
_FIELD_API = "OmniSciFieldAPI"
_EXPRESSION_API = "CaeArrayExpressionAPI"

# Heavy metadata cache keyed by (prim_path, instance) so re-selecting an already
# computed array is instant. Each entry records the effective time sample used to
# compute it; entries from another sample remain visible but are clearly marked
# obsolete. Only small derived metadata is cached here (shape, component-wise
# ranges, and per-component stats/histograms); the materialized array itself is
# kept on the section instance so it is released when the payload changes and the
# section is recreated.
_DETAILS_CACHE: dict[tuple[str, str], dict] = {}

# Combo index 0 always maps to "Magnitude" for multi-component arrays; index i
# maps to component (i - 1). For scalar arrays a single entry is stored under 0.
_MAGNITUDE_INDEX = 0


def _component_options(ncomps: int) -> list[str]:
    """ComboBox labels for an ``ncomps``-component array (empty when scalar)."""
    if ncomps <= 1:
        return []
    if ncomps <= 4:
        axes = ["X", "Y", "Z", "W"][:ncomps]
    else:
        axes = [f"[{i}]" for i in range(ncomps)]
    return ["Magnitude", *axes]


def _instance_label(prim: Usd.Prim, instance: str) -> str:
    """Field name for *instance* if a field API exists, else the instance name."""
    if prim.HasAPI(cae.ArrayExpressionAPI, instance):
        display_name = cae.ArrayExpressionAPI(prim, instance).GetDisplayNameAttr().Get()
        if display_name:
            return str(display_name)
    attr = prim.GetAttribute(f"omni:sci:field:{instance}:name")
    value = attr.Get() if attr else None
    return str(value) if value else instance


class OmniSciArrayDetailsSection:
    """Dropdown-driven per-array metadata inspector for a single OmniSci prim."""

    def __init__(self, prim: Usd.Prim):
        self._prim_path = str(prim.GetPath())
        # (instance, label) pairs for every OmniSciArrayAPI instance on the prim.
        self._instances = self._collect_instances(prim)
        self._selected_index = 0

        self._selected_component = _MAGNITUDE_INDEX
        self._body_frame = None
        self._selection_model = None
        # Raw materialized array for the selected instance, kept on the instance
        # (not the global cache) so it is released on payload change. Used to
        # recompute the histogram for a user-specified range.
        self._loaded_array = None
        self._hist_min_field = None
        self._hist_max_field = None
        self._histogram_chart_frame = None
        self._current_histogram = None

        # Heavy reads remain opt-in, but timeline changes immediately rebuild the
        # body so results from another time sample are clearly marked obsolete.
        self._timeline = omni.timeline.get_timeline_interface()
        self._timeline_subscription = None
        self._request_generation = 0
        self._observed_time_sample = (
            self._get_effective_time_sample(self._instances[self._selected_index][0]) if self._instances else None
        )
        if self._instances and self._timeline:
            self._timeline_subscription = carb.eventdispatcher.get_eventdispatcher().observe_event(
                observer_name="OmniSciArrayDetailsSection_Timeline",
                filter=self._timeline.get_event_key(),
                event_name=omni.timeline.GLOBAL_EVENT_CURRENT_TIME_TICKED,
                on_event=self._on_timeline_event,
            )

    def destroy(self):
        """Release event subscriptions and invalidate pending computations."""
        self._request_generation += 1
        self._timeline_subscription = None
        self._timeline = None
        self._loaded_array = None
        self._body_frame = None
        self._selection_model = None

    # -- discovery ---------------------------------------------------------

    @staticmethod
    def _collect_instances(prim: Usd.Prim) -> list[tuple[str, str]]:
        expression_instances = [
            name
            for name in usd_utils.get_instances(prim, _EXPRESSION_API)
            if bool(cae.ArrayExpressionAPI(prim, name).GetEnabledAttr().Get())
        ]
        instances = [
            *usd_utils.get_instances(prim, _ARRAY_API),
            *expression_instances,
        ]
        return [(name, _instance_label(prim, name)) for name in sorted(set(instances))]

    @property
    def has_arrays(self) -> bool:
        return bool(self._instances)

    def _get_prim(self) -> Usd.Prim | None:
        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(self._prim_path) if stage else None
        return prim if prim and prim.IsValid() else None

    def _get_current_time_code(self) -> Usd.TimeCode:
        timeline = self._timeline or omni.timeline.get_timeline_interface()
        if not timeline:
            return Usd.TimeCode.Default()
        return Usd.TimeCode(round(timeline.get_current_time() * timeline.get_time_codes_per_seconds()))

    def _get_effective_time_sample(self, instance: str) -> float | None:
        prim = self._get_prim()
        if not prim:
            return None
        return cae_simdata.effective_array_time_sample(
            prim,
            instance,
            self._get_current_time_code(),
        )

    def _on_timeline_event(self, _event):
        if not self._instances:
            return

        instance, _ = self._instances[self._selected_index]
        current_time_sample = self._get_effective_time_sample(instance)
        if current_time_sample == self._observed_time_sample:
            return

        self._observed_time_sample = current_time_sample
        # Prevent a read started for the previous sample from publishing after
        # the timeline moves to another effective sample.
        self._request_generation += 1

        cached = _DETAILS_CACHE.get((self._prim_path, instance))
        if cached is None:
            return

        # Rebuild on every effective-sample transition. This both marks details
        # obsolete when moving away and removes the warning when moving back.
        self._rebuild_body()

    # -- cheap metadata ----------------------------------------------------

    def _cheap_metadata(self, prim: Usd.Prim, instance: str) -> dict:
        def attr_value(name: str, default: str) -> str:
            attr = prim.GetAttribute(name)
            value = attr.Get() if attr else None
            return str(value) if value is not None else default

        if prim.HasAPI(cae.ArrayExpressionAPI, instance):
            api = cae.ArrayExpressionAPI(prim, instance)
            return {
                "name": str(api.GetDisplayNameAttr().Get() or instance),
                "association": "inferred",
                "device": str(api.GetComputeDeviceAttr().Get() or "auto"),
                "type": "float32 (derived)",
            }

        value_attr = prim.GetAttribute(f"omni:sci:array:{instance}:value")
        # GetTypeName() resolves from the lazy attribute's registered type
        # metadata without triggering the (expensive) value loader.
        type_name = str(value_attr.GetTypeName()) if value_attr else "?"

        return {
            "name": attr_value(f"omni:sci:field:{instance}:name", instance),
            "association": attr_value(f"omni:sci:field:{instance}:association", "-"),
            "device": attr_value(f"omni:sci:array:{instance}:device", "?"),
            "type": type_name,
        }

    # -- heavy metadata ----------------------------------------------------

    async def _compute_details(self, instance: str):
        prim = self._get_prim()
        if not prim:
            return

        attr = prim.GetAttribute(f"omni:sci:array:{instance}:value")
        is_expression = prim.HasAPI(cae.ArrayExpressionAPI, instance)
        if not is_expression and not attr:
            logger.warning("Array '%s' has no value attribute on %s", instance, self._prim_path)
            return

        time_code = self._get_current_time_code()
        time_sample = cae_simdata.effective_array_time_sample(prim, instance, time_code)
        self._request_generation += 1
        request_generation = self._request_generation

        label = next((label for name, label in self._instances if name == instance), instance)
        with progress.ProgressContext(f"Computing array details [{label}]") as ctx:
            if is_expression:
                expression_api = cae.ArrayExpressionAPI(prim, instance)
                device = str(expression_api.GetComputeDeviceAttr().Get() or "auto")
            else:
                device_attr = prim.GetAttribute(f"omni:sci:array:{instance}:device")
                device = str(device_attr.Get() or "cpu") if device_attr else "cpu"
            if device == "auto":
                device = viz_settings.get_default_device_for_auto()
            value = await asyncio.to_thread(
                cae_simdata.materialize_array,
                prim,
                instance,
                device=device,
                time_code=time_code,
            )
            if request_generation != self._request_generation:
                return
            if value is None:
                logger.warning("Array '%s' has no value on %s", instance, self._prim_path)
                return

            farray = value.numpy() if hasattr(value, "numpy") else np.asarray(value)
            ctx.notify(0.5)

            is_float = farray.dtype.kind == "f"

            def fmt(val):
                return f"{val:,.3f}" if is_float else f"{int(val):,}"

            ncomps = 1 if farray.ndim == 1 else farray.shape[-1]
            formatted_dims = ", ".join(str(dim) for dim in farray.shape)
            metadata = {
                "shape": f"ndim {farray.ndim}, shape ({formatted_dims})",
                "elements": farray.shape[0] if farray.ndim >= 1 else 1,
                "ncomps": ncomps,
            }

            ranges = array_utils.get_componentwise_ranges(farray)
            if ncomps == 1:
                metadata["range"] = f"[{fmt(ranges[0][0])}, {fmt(ranges[0][1])}]"
            else:
                metadata["range"] = "\n".join(f"    {i}: [{fmt(lo)}, {fmt(hi)}]" for i, (lo, hi) in enumerate(ranges))

            # Precompute stats for every selectable scalar (magnitude + each
            # component for vectors; the single distribution for scalars). These
            # extra histogram passes are negligible next to the array read, and
            # caching them lets the component dropdown switch instantly without
            # holding the raw array in the global cache.
            keys = [_MAGNITUDE_INDEX] if ncomps == 1 else range(_MAGNITUDE_INDEX, ncomps + 1)
            component_stats = {}
            for key in keys:
                stats = array_utils.get_scalar_stats(self._reduce_to_scalar(key, farray), num_bins=32)
                component_stats[key] = {
                    "stats": {k: stats[k] for k in ("min", "max", "mean", "median", "q1", "q2", "q3", "q4")},
                    "histogram": {"counts": stats["counts"], "bin_edges": stats["bin_edges"]},
                }
            metadata["component_stats"] = component_stats

            # Verify the sample again before publishing: selection and timeline
            # events may have arrived while the payload was materializing.
            if request_generation != self._request_generation or time_sample != self._get_effective_time_sample(
                instance
            ):
                return

            self._loaded_array = farray
            _DETAILS_CACHE[(self._prim_path, instance)] = {
                "metadata": metadata,
                "time_code": time_code.GetValue(),
                "time_sample": time_sample,
            }
            self._selected_component = _MAGNITUDE_INDEX
            self._rebuild_body()

    def _reduce_to_scalar(self, component_index: int, array=None):
        """Reduce ``self._loaded_array`` to a 1-D scalar for the given component.

        Index ``0`` is the L2 magnitude for vectors; index ``i`` selects
        component ``i - 1``. Scalar arrays are returned as-is. Component slices
        are NumPy views and the magnitude runs in a Warp kernel, so neither
        copies the source payload.
        """
        arr = self._loaded_array if array is None else array
        if arr.ndim == 1:
            return arr
        if arr.shape[-1] == 1:
            return arr.reshape(-1)
        if component_index == _MAGNITUDE_INDEX:
            return array_utils.get_magnitude(arr)
        return arr[:, component_index - 1]

    def _on_compute_clicked(self):
        instance, _ = self._instances[self._selected_index]

        async def compute_details():
            try:
                await self._compute_details(instance)
            except Exception:
                logger.exception(
                    "Unable to compute details for array '%s' on %s",
                    instance,
                    self._prim_path,
                )

        asyncio.ensure_future(compute_details())

    # -- selection ---------------------------------------------------------

    def _select_index(self, selected_index: int):
        if selected_index == self._selected_index:
            return
        self._request_generation += 1
        self._selected_index = selected_index
        instance, _ = self._instances[self._selected_index]
        self._observed_time_sample = self._get_effective_time_sample(instance)
        self._selected_component = _MAGNITUDE_INDEX
        self._loaded_array = None
        self._rebuild_body()

    def select_instance(self, instance: str) -> bool:
        """Select an array by instance name without materializing its value."""
        selected_index = next((index for index, item in enumerate(self._instances) if item[0] == instance), None)
        if selected_index is None:
            return False

        if self._selection_model is not None:
            if self._selection_model.get_value_as_int() != selected_index:
                self._selection_model.set_value(selected_index)
        self._select_index(selected_index)
        return True

    def _on_selection_changed(self, model, _item=None):
        self._select_index(model.get_item_value_model().get_value_as_int())

    def _on_component_changed(self, model, _item=None):
        self._selected_component = model.get_item_value_model().get_value_as_int()
        self._rebuild_body()

    # -- UI ----------------------------------------------------------------

    def build_items(self):
        if not self._instances:
            return

        style = get_style()["Label::label"]
        with ui.VStack(spacing=5, height=0):
            with ui.HStack(height=0, spacing=8):
                ui.Label("Array:", width=55, style=style, height=0)
                combo = ui.ComboBox(self._selected_index, *[label for _, label in self._instances])
                self._selection_model = combo.model.get_item_value_model()
                combo.model.add_item_changed_fn(self._on_selection_changed)

            # Use set_build_fn/rebuild rather than clear()+rebuild so the body can
            # be refreshed from ComboBox callbacks: omni.ui forbids clearing a
            # container during an event or draw, which a synchronous rebuild hits.
            self._body_frame = ui.Frame(height=0, build_fn=self._build_body)

    def _rebuild_body(self):
        if self._body_frame is not None:
            self._body_frame.rebuild()

    def _build_body(self):
        prim = self._get_prim()
        if not prim:
            return

        instance, _ = self._instances[self._selected_index]
        cheap = self._cheap_metadata(prim, instance)
        cached = _DETAILS_CACHE.get((self._prim_path, instance))
        current_time_sample = self._get_effective_time_sample(instance)
        cached_is_stale = cached is not None and cached["time_sample"] != current_time_sample

        label_style = {"font_size": 12, "color": 0xFF999999}
        value_style = {"font_size": 12, "color": 0xFFCCCCCC}

        def info_row(label: str, value: str):
            with ui.HStack(height=0, spacing=4):
                ui.Label(label, width=90, style=label_style, height=0)
                ui.Label(value, style=value_style, height=0, word_wrap=True, tooltip=value)

        with ui.VStack(spacing=3, height=0):
            info_row("Name:", cheap["name"])
            info_row("Association:", cheap["association"])
            info_row("Device:", cheap["device"])
            info_row("Type:", cheap["type"])

            ui.Spacer(height=4)
            ui.Line(height=1, style={"color": 0xFF555555})
            ui.Spacer(height=4)

            if cached is None:
                ui.Button(
                    "Compute Details",
                    height=22,
                    clicked_fn=self._on_compute_clicked,
                    tooltip="Read the array payload to compute shape, range, stats and histogram.",
                )
                return

            if cached_is_stale:
                cached_sample = cached["time_sample"]
                cached_label = f"{cached_sample:g}" if cached_sample is not None else "default"
                current_label = f"{current_time_sample:g}" if current_time_sample is not None else "default"
                ui.Label(
                    f"Obsolete: details are from time sample {cached_label}; current sample is {current_label}.",
                    style={"font_size": 12, "color": 0xFF66BFFF},
                    height=0,
                    word_wrap=True,
                )
                ui.Spacer(height=4)

            metadata = cached["metadata"]
            if cached["time_sample"] is not None:
                info_row("Time Sample:", f"{cached['time_sample']:g}")
            info_row("Shape:", metadata["shape"])
            info_row("Range:", metadata["range"])

            ui.Spacer(height=2)
            ui.Button(
                "Refresh Details",
                height=22,
                clicked_fn=self._on_compute_clicked,
                tooltip="Re-read the array payload at the current timeline time.",
            )
            ui.Spacer(height=4)

            component_stats = metadata["component_stats"]
            ncomps = metadata["ncomps"]
            if ncomps > 1:
                options = _component_options(ncomps)
                if self._selected_component >= len(options):
                    self._selected_component = _MAGNITUDE_INDEX
                with ui.HStack(height=0, spacing=4):
                    ui.Label("Component:", width=90, style=label_style, height=0)
                    combo = ui.ComboBox(self._selected_component, *options)
                    combo.model.add_item_changed_fn(self._on_component_changed)
                ui.Spacer(height=4)

            entry = component_stats.get(self._selected_component) or component_stats[_MAGNITUDE_INDEX]
            self._build_stats_table(entry["stats"])
            ui.Spacer(height=4)
            self._build_histogram(entry["histogram"])

    @staticmethod
    def _format_axis_value(val):
        if abs(val) >= 1e6 or (abs(val) < 1e-2 and val != 0):
            return f"{val:.2e}"
        return f"{val:.3g}"

    def _build_stats_table(self, stats: dict):
        fmt = self._format_axis_value
        label_style = {"font_size": 12, "color": 0xFF999999}
        value_style = {"font_size": 12, "color": 0xFFCCCCCC}

        def stat_row(name: str, value: str):
            with ui.HStack(height=0, spacing=4):
                ui.Label(name, width=90, style=label_style, height=0)
                ui.Label(value, style=value_style, height=0)

        with ui.VStack(spacing=2, height=0):
            stat_row("Range:", f"[{fmt(stats['min'])}, {fmt(stats['max'])}]")
            stat_row("Mean:", fmt(stats["mean"]))
            stat_row("Median:", fmt(stats["median"]))
            ui.Spacer(height=2)
            for name, key in [("Q1", "q1"), ("Q2", "q2"), ("Q3", "q3"), ("Q4", "q4")]:
                lo, hi = stats[key]
                stat_row(f"{name}:", f"[{fmt(lo)}, {fmt(hi)}]")

    def _build_histogram(self, histogram: dict):
        style = get_style()["Label::label"]
        label_style = {"font_size": 12, "color": 0xFF999999}

        with ui.VStack(spacing=4, height=0):
            ui.Label("Histogram Range:", style=style)
            with ui.HStack(height=0, spacing=4):
                ui.Label("Min:", width=30, style=label_style)
                self._hist_min_field = ui.FloatField(height=20, width=ui.Fraction(1))
                self._hist_min_field.model.set_value(float(histogram["bin_edges"][0]))
                self._hist_min_field.model.add_end_edit_fn(self._on_hist_range_changed)
                ui.Label("Max:", width=30, style=label_style)
                self._hist_max_field = ui.FloatField(height=20, width=ui.Fraction(1))
                self._hist_max_field.model.set_value(float(histogram["bin_edges"][-1]))
                self._hist_max_field.model.add_end_edit_fn(self._on_hist_range_changed)

            ui.Spacer(height=2)
            self._current_histogram = histogram
            # set_build_fn/rebuild so the chart can be refreshed from the float
            # field end-edit callbacks without clearing a container mid-event.
            self._histogram_chart_frame = ui.Frame(height=0, build_fn=self._build_histogram_chart)

    def _on_hist_range_changed(self, _=None):
        if self._loaded_array is None or self._hist_min_field is None:
            return
        try:
            hist_min = float(self._hist_min_field.model.get_value_as_string())
            hist_max = float(self._hist_max_field.model.get_value_as_string())
        except ValueError:
            return
        if hist_min >= hist_max:
            return
        scalar = self._reduce_to_scalar(self._selected_component)
        self._current_histogram = array_utils.compute_histogram(
            scalar, num_bins=32, range_min=hist_min, range_max=hist_max
        )
        if self._histogram_chart_frame is not None:
            self._histogram_chart_frame.rebuild()

    def _build_histogram_chart(self):
        histogram = self._current_histogram
        if histogram is None:
            return

        counts = histogram["counts"]
        bin_edges = histogram["bin_edges"]
        max_count = max(counts) if counts else 0
        bar_height = 80
        fmt = self._format_axis_value
        axis_style = {"font_size": 11, "color": 0xFF999999}

        with ui.VStack(spacing=2, height=0):
            with ui.ZStack(height=bar_height):
                ui.Rectangle(style={"background_color": 0xFF1E1E1E, "border_radius": 2})
                with ui.HStack(spacing=1, content_clipping=True):
                    for i, count in enumerate(counts):
                        h = int((count / max_count) * bar_height) if max_count > 0 else 0
                        lo, hi = bin_edges[i], bin_edges[i + 1]
                        tooltip = f"[{fmt(lo)}, {fmt(hi)})\nCount: {count:,}"
                        with ui.VStack():
                            ui.Spacer()
                            if h > 0:
                                ui.Rectangle(
                                    height=h,
                                    tooltip=tooltip,
                                    style={"background_color": 0xFF4A90D9, "border_radius": 1},
                                )
                            else:
                                ui.Rectangle(height=1, tooltip=tooltip, style={"background_color": 0x00000000})

            mid_val = (bin_edges[0] + bin_edges[-1]) / 2
            with ui.HStack(height=0):
                ui.Label(fmt(bin_edges[0]), style=axis_style, height=0)
                ui.Spacer()
                ui.Label(fmt(mid_val), style=axis_style, height=0, alignment=ui.Alignment.CENTER)
                ui.Spacer()
                ui.Label(fmt(bin_edges[-1]), style=axis_style, height=0, alignment=ui.Alignment.RIGHT_CENTER)
