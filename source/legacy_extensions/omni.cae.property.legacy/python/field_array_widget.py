# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import asyncio
import logging

import omni.timeline
import omni.ui as ui
import omni.usd
from omni.cae.core import array_utils
from omni.cae.data import usd_utils as legacy_usd_utils
from omni.cae.schema import cae
from omni.kit.window.property.style import get_style
from omni.kit.window.property.templates import SimplePropertyWidget
from pxr import Usd

logger = logging.getLogger(__name__)

_FIELD_ARRAY_METADATA_CACHE = {}


class CaeFieldArrayPropertiesWidget(SimplePropertyWidget):
    """Property widget for deprecated delegate-backed CaeFieldArray prims."""

    def __init__(self, title: str = "Field Array"):
        super().__init__(title, collapsed=False)
        self._metadata = {}
        self._info_labels = {}
        self._stats_frame = None
        self._histogram_frame = None
        self._histogram_chart_frame = None
        self._scalar_farray = None
        self._hist_min_field = None
        self._hist_max_field = None

    def on_new_payload(self, payload) -> bool:
        if not super().on_new_payload(payload):
            return False

        if not payload or len(payload) == 0:
            return False

        if len(payload) > 1:
            return False

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return False

        prim_path = self._payload[0]
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsA(cae.FieldArray):
            return False

        self._metadata = {}
        prim_path_str = str(prim.GetPath())
        if prim_path_str in _FIELD_ARRAY_METADATA_CACHE:
            self._metadata = _FIELD_ARRAY_METADATA_CACHE[prim_path_str].copy()
            logger.info("Restored cached metadata for %s", prim_path_str)

        return True

    async def _fetch_metadata(self, prim_path_str: str):
        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(prim_path_str) if stage else None
        if not prim:
            return {}

        timeline = omni.timeline.get_timeline_interface()
        time_code = Usd.TimeCode(round(timeline.get_current_time() * timeline.get_time_codes_per_seconds()))
        farray = await legacy_usd_utils.get_array(prim, time_code)
        if not farray:
            return {}

        metadata = {}
        metadata["device"] = str(array_utils.get_device(farray))
        metadata["type"] = farray.dtype.name

        formatted_dims = [str(dim) for dim in farray.shape]
        metadata["shape"] = f"\n\tndim: {farray.ndim}\n\tshape: ({', '.join(formatted_dims)})"

        ranges = array_utils.get_componentwise_ranges(farray)
        is_float = farray.dtype.kind == "f"

        def format_value(val):
            return f"{val:,.3f}" if is_float else f"{int(val):,}"

        is_scalar = farray.ndim == 1 or farray.shape[-1] == 1
        if is_scalar:
            metadata["range"] = f"({format_value(ranges[0][0])}, {format_value(ranges[0][1])})"
        else:
            component_ranges = [
                f"\t{i}:\t({format_value(ranges[i][0])}, {format_value(ranges[i][1])})" for i in range(len(ranges))
            ]
            metadata["range"] = "\n" + "\n".join(component_ranges)

        if is_scalar:
            self._scalar_farray = farray
            scalar_stats = array_utils.get_scalar_stats(farray, num_bins=32)
            metadata["stats"] = {
                "min": scalar_stats["min"],
                "max": scalar_stats["max"],
                "mean": scalar_stats["mean"],
                "median": scalar_stats["median"],
                "q1": scalar_stats["q1"],
                "q2": scalar_stats["q2"],
                "q3": scalar_stats["q3"],
                "q4": scalar_stats["q4"],
            }
            metadata["histogram"] = {
                "counts": scalar_stats["counts"],
                "bin_edges": scalar_stats["bin_edges"],
            }
        else:
            self._scalar_farray = None

        return metadata

    def _on_refresh_clicked(self):
        asyncio.ensure_future(self._async_refresh())

    async def _async_refresh(self):
        for label in self._info_labels.values():
            label.text = "(Fetching...)"

        prim_path_str = str(self._payload[0])
        self._metadata = await self._fetch_metadata(prim_path_str)
        _FIELD_ARRAY_METADATA_CACHE[prim_path_str] = self._metadata.copy()
        logger.info("Cached metadata for %s", prim_path_str)
        self._update_info_labels()

    def _update_info_labels(self):
        metadata = self._metadata
        if "device" in self._info_labels:
            self._info_labels["device"].text = f"Device: {metadata.get('device', '(TBD)')}"
        if "type" in self._info_labels:
            self._info_labels["type"].text = f"Type: {metadata.get('type', '(TBD)')}"
        if "shape" in self._info_labels:
            self._info_labels["shape"].text = f"Size: {metadata.get('shape', '(TBD)')}"
        if "range" in self._info_labels:
            if "stats" in metadata:
                self._info_labels["range"].text = ""
            else:
                self._info_labels["range"].text = f"Range: {metadata.get('range', '(TBD)')}"
        self._build_stats_table()
        self._build_histogram()

    @staticmethod
    def _format_axis_value(val):
        if abs(val) >= 1e6 or (abs(val) < 1e-2 and val != 0):
            return f"{val:.2e}"
        return f"{val:.3g}"

    def _on_hist_range_changed(self, _=None):
        if self._scalar_farray is None or self._hist_min_field is None:
            return
        try:
            hist_min = float(self._hist_min_field.model.get_value_as_string())
            hist_max = float(self._hist_max_field.model.get_value_as_string())
        except ValueError:
            return
        if hist_min >= hist_max:
            return
        result = array_utils.compute_histogram(self._scalar_farray, num_bins=32, range_min=hist_min, range_max=hist_max)
        self._metadata["histogram"] = result
        self._build_histogram_chart()

    def _build_stats_table(self):
        if self._stats_frame is None:
            return

        self._stats_frame.clear()

        if "stats" not in self._metadata:
            return

        stats = self._metadata["stats"]
        fmt = self._format_axis_value
        label_style = {"font_size": 12, "color": 0xFF999999}
        value_style = {"font_size": 12, "color": 0xFFCCCCCC}

        with self._stats_frame:
            with ui.VStack(spacing=2, height=0):
                with ui.HStack(height=0, spacing=4):
                    ui.Label("Range:", width=55, style=label_style, height=0)
                    ui.Label(f"[{fmt(stats['min'])}, {fmt(stats['max'])}]", style=value_style, height=0)
                with ui.HStack(height=0, spacing=4):
                    ui.Label("Mean:", width=55, style=label_style, height=0)
                    ui.Label(fmt(stats["mean"]), style=value_style, height=0)
                with ui.HStack(height=0, spacing=4):
                    ui.Label("Median:", width=55, style=label_style, height=0)
                    ui.Label(fmt(stats["median"]), style=value_style, height=0)
                ui.Spacer(height=2)
                for name, key in [("Q1", "q1"), ("Q2", "q2"), ("Q3", "q3"), ("Q4", "q4")]:
                    lo, hi = stats[key]
                    with ui.HStack(height=0, spacing=4):
                        ui.Label(f"{name}:", width=55, style=label_style, height=0)
                        ui.Label(f"[{fmt(lo)}, {fmt(hi)}]", style=value_style, height=0)

    def _build_histogram(self):
        if self._histogram_frame is None:
            return

        self._histogram_frame.clear()

        if "histogram" not in self._metadata:
            return

        style = get_style()["Label::label"]
        label_style = {"font_size": 12, "color": 0xFF999999}

        with self._histogram_frame:
            with ui.VStack(spacing=4, height=0):
                ui.Label("Histogram Range:", style=style)
                with ui.HStack(height=0, spacing=4):
                    ui.Label("Min:", width=30, style=label_style)
                    self._hist_min_field = ui.FloatField(height=20, width=ui.Fraction(1))
                    self._hist_min_field.model.set_value(float(self._metadata["histogram"]["bin_edges"][0]))
                    self._hist_min_field.model.add_end_edit_fn(self._on_hist_range_changed)
                    ui.Label("Max:", width=30, style=label_style)
                    self._hist_max_field = ui.FloatField(height=20, width=ui.Fraction(1))
                    self._hist_max_field.model.set_value(float(self._metadata["histogram"]["bin_edges"][-1]))
                    self._hist_max_field.model.add_end_edit_fn(self._on_hist_range_changed)

                ui.Spacer(height=2)

                self._histogram_chart_frame = ui.Frame(height=0)
                self._build_histogram_chart()

    def _build_histogram_chart(self):
        if self._histogram_chart_frame is None:
            return

        self._histogram_chart_frame.clear()

        hist = self._metadata.get("histogram")
        if not hist:
            return

        counts = hist["counts"]
        bin_edges = hist["bin_edges"]
        max_count = max(counts) if counts else 0
        bar_height = 80
        fmt = self._format_axis_value
        axis_style = {"font_size": 11, "color": 0xFF999999}

        with self._histogram_chart_frame:
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
                                    ui.Rectangle(
                                        height=1,
                                        tooltip=tooltip,
                                        style={"background_color": 0x00000000},
                                    )

                median_val = (bin_edges[0] + bin_edges[-1]) / 2
                with ui.HStack(height=0):
                    ui.Label(fmt(bin_edges[0]), style=axis_style, height=0)
                    ui.Spacer()
                    ui.Label(fmt(median_val), style=axis_style, height=0, alignment=ui.Alignment.CENTER)
                    ui.Spacer()
                    ui.Label(fmt(bin_edges[-1]), style=axis_style, height=0, alignment=ui.Alignment.RIGHT_CENTER)

    def build_items(self):
        style = get_style()["Label::label"]

        with ui.VStack(spacing=5, height=0):
            with ui.HStack(height=0, spacing=10):
                with ui.VStack(spacing=3, width=ui.Fraction(1)):
                    self._info_labels["device"] = ui.Label("Device: (TBD)", word_wrap=True, height=0, style=style)
                    self._info_labels["type"] = ui.Label("Type: (TBD)", word_wrap=True, height=0, style=style)
                    self._info_labels["shape"] = ui.Label("Shape: (TBD)", word_wrap=True, height=0, style=style)
                    self._info_labels["range"] = ui.Label("", word_wrap=True, height=0, style=style)
                self._stats_frame = ui.Frame(width=ui.Fraction(1), height=0)

            self._histogram_frame = ui.Frame(height=0)

            ui.Spacer(height=5)

            ui.Button("Refresh", height=20, clicked_fn=self._on_refresh_clicked)
            self._update_info_labels()
