# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Direct, native-resolution FLASH axisymmetric rendering for NVIDIA IndeX.

This operator renders a two-dimensional FLASH AMR field as a three-dimensional
axisymmetric volume without first constructing a revolved mesh or resampling
the field onto a dense, uniformly refined 3D grid. It is intentionally isolated
from the standard IndeX volume operator because its data representation,
importer contract, and shader lookup are specific to axisymmetric AMR.

Representation
--------------

The public :class:`UsdVol.Volume` is a single multi-attribute NanoVDB scene
element. Its attributes have distinct roles:

``attribute 0``
    A small, constant-valued 3D grid covering the exact revolved bounding box.
    It gives IndeX a regular spatial domain through which to ray march. Its
    values do not represent the selected field and the XAC shader never uses
    them for color. Its spacing targets :data:`DOMAIN_RESOLUTION` cells across
    the longest dimension (integer index alignment can add a boundary cell), so
    this carrier has negligible storage compared with the field data.

``attributes 1..N``
    Sparse NanoVDB grids containing the native FLASH leaf cells, grouped by
    refinement level from finest to coarsest. Each grid is one voxel thick and
    is indexed in ``(radius, axial, 0)`` coordinates at that level's native
    spacing. Inactive space has a NaN background, which lets the shader
    distinguish "this level has no leaf here" from a valid field value.

The level attributes remain on the same public volume as the domain attribute;
there are no hidden carrier volumes or extra IndeX scene slots.

Build and sampling path
-----------------------

Only FLASH leaf bounds, leaf indices, cell dimensions, and the selected scalar
field are requested. Topology and geometry are not loaded. Analytical
axisymmetric fields are unwrapped to their compact source field before
materialization, so the temporary array contains the original 2D block values,
not angularly replicated values. Leaves are classified by their authored cell
spacing and copied once into the corresponding sparse NanoVDB. Coarse leaves
are neither prolonged to the finest level nor otherwise resampled.

For every ray sample, ``axisymmetric_volume.xac`` maps object-space position
``(x, y, z)`` to ``(sqrt(x*x + z*z), y)``. It probes attributes 1..N with
nearest-neighbor filtering, finest first, and accepts the first non-NaN value.
The selected value is then passed to the volume's colormap. This produces a
revolution around the scene Y axis. The shader evaluates ``atan2(z, x)`` and
discards samples outside the requested minimum and maximum angles. Angular
cells are not materialized or consulted because the field is analytically
axisymmetric and therefore has no angular tessellation.

The ray step is ``finest_native_spacing * samplingDistanceScale``. It controls
rendering cost and sampling quality only; it does not change the NanoVDB
resolution. Smaller values take more samples and generally reveal finer
features, while larger values render faster and can skip thin structures.

Ownership, caching, and updates
-------------------------------

Preparation reads compact metadata and field values on the CPU and builds the
NanoVDB grids on CUDA device 0. :class:`AxisymmetricVolumeCompute` exposes every
grid to the device requested by IndeX through DLPack, copying only when the
renderer uses a different CUDA device. Each snapped dataset sample has its own
time-scoped cache entry containing the native NanoVDB grids, their rendering
contract, and the DLPack adoption objects that keep buffers alive. Revisiting a
sample therefore re-adopts its cached grids instead of rebuilding them. A
process-wide monotonically increasing generation and weak generation lookup
let the asynchronous loader find the exact cached payload without
reconstructing its USD time-code cache key. They also reject a delayed loader
callback after structural invalidation has replaced or released a cached
payload.
The currently rendered payload also has a separate retention entry, so clearing
the temporal cache cannot release its buffers before the replacement adoption
has completed.

The first visit to a snapped dataset sample builds its lookup. Temporal ticks
select the cached entry and restore its extent, refinement-level shader
parameters, and loader generation; this matters when bounds or AMR levels vary
over time. This path does not interpolate between field samples.
Reconfiguration briefly disables compositing and authors the complete importer
and shader contract in one USD change block before enabling the volume again.

Current contract and limitations
--------------------------------

* FLASH AMR is the only supported source model and ``colors`` must select a
  scalar field.
* Only leaf blocks are stored. Radial and axial cells must be square, refinement
  spacings must be integral multiples of the finest spacing, and at most
  :data:`MAX_REFINEMENT_LEVELS` distinct levels are supported.
* Dataset subsetting and voxelization APIs are rejected because either would
  replace the native leaf layout this operator is designed to preserve.
* Temporal caching retains one native 2D payload for every visited snapped
  sample until structural invalidation or prim deletion. Per sample, memory
  grows with the native leaf cells plus sparse NanoVDB tile overhead, rather
  than with a finest-resolution 3D grid or an angular replication factor.
"""

import math
import threading
import weakref
from dataclasses import dataclass
from logging import getLogger
from typing import Any

import numpy as np
import warp as wp
from omni.cae.core import array_utils, cache, progress, usd_utils
from omni.cae.schema import viz as cae_viz
from omni.usd import get_context
from pxr import Gf, Sdf, Usd, UsdShade, UsdVol, Vt

from . import utils as viz_utils
from .execution_context import ExecutionContext
from .operator import operator

logger = getLogger(__name__)
MAX_REFINEMENT_LEVELS = 8
DOMAIN_RESOLUTION = 8


@operator(priority=10, supports_temporal=True, tick_on_time_change=True)
class IndeXAxisymmetricVolume:
    """Render native FLASH AMR leaves through one multi-attribute VDB."""

    prim_type = "Volume"
    api_schemas = {
        "CaeVizIndeXVolumeAPI",
        "CaeVizIndeXAxisymmetricVolumeAPI",
        "CaeVizDatasetSelectionAPI:source",
    }
    optional_api_schemas = {
        "CaeVizFieldSelectionAPI",
        "CaeVizRescaleRangeAPI",
    }

    async def exec(self, prim: Usd.Prim, device: str, context: ExecutionContext) -> None:
        logger.info(
            "IndeXAxisymmetricVolume.exec - reason: %s, timecode: %s, raw: %s",
            context.reason.value,
            context.timecode,
            context.raw_timecode,
        )
        if device != "cpu":
            logger.info("Preparing direct axisymmetric volume input on CPU instead of %s", device)
            device = "cpu"
        if prim.HasAPI(cae_viz.DatasetSubsetAPI, "source") or prim.HasAPI(cae_viz.DatasetVoxelizationAPI, "source"):
            raise usd_utils.QuietableException(
                "Direct axisymmetric volume rendering cannot be combined with dataset subsetting or voxelization."
            )

        if context.is_full_rebuild_needed():
            with _volume_compute_lock:
                cache.remove(_state_cache_key(str(prim.GetPath())))

        source_dataset = await viz_utils.get_input_dataset(
            prim,
            "source",
            timeCode=context.timecode,
            device=device,
            needs_topology=False,
            needs_geometry=False,
        )
        if len(source_dataset.get_field_names()) == 0:
            raise usd_utils.QuietableException("No fields selected. At least one field is required.")
        api = cae_viz.IndeXAxisymmetricVolumeAPI(prim)
        try:
            with progress.ProgressContext("Executing SimData [axisymmetric lookup]"):
                await prepare(
                    prim,
                    source_dataset,
                    context.timecode,
                    float(api.GetSamplingDistanceScaleAttr().Get()),
                )
        except ValueError as exc:
            raise usd_utils.QuietableException(str(exc)) from exc
        viz_utils.process_rescale_range_apis(prim, source_dataset)

    def deactivate(self, prim: Usd.Prim) -> None:
        with _volume_compute_lock:
            cache.remove(_state_cache_key(str(prim.GetPath())))
            cache.remove(_active_state_cache_key(str(prim.GetPath())))
        with viz_utils.edit_context(prim):
            prim.GetAttribute("nvindex:composite").Set(False)

    async def on_time_changed(self, prim: Usd.Prim, device: str, context: ExecutionContext) -> None:
        """Select and re-adopt the cached payload for a revisited time sample."""
        with _volume_compute_lock:
            state = cache.get(_state_cache_key(str(prim.GetPath())), timeCode=context.timecode)
        if state is None:
            logger.info(
                "Rebuilding evicted axisymmetric lookup for %s at %s.",
                prim.GetPath(),
                context.timecode,
            )
            await self.exec(prim, device, context)
            return

        loader = UsdShade.Shader(prim.GetChild("Material").GetChild("DataLoader"))
        active_generation = loader.GetInput("params_generation").Get()
        if active_generation == state.generation:
            return

        api = cae_viz.IndeXAxisymmetricVolumeAPI(prim)
        with Sdf.ChangeBlock():
            with viz_utils.edit_context(prim):
                prim.GetAttribute("nvindex:composite").Set(False)
                configure_volume(
                    prim,
                    state.spec,
                    state.generation,
                    context.timecode,
                    float(api.GetSamplingDistanceScaleAttr().Get()),
                )


@dataclass(frozen=True)
class LookupLevelSpec:
    """Diagnostics for one native FLASH refinement-level attribute."""

    spacing: float
    block_count: int
    native_cells: int
    nanovdb_voxels: int


@dataclass(frozen=True)
class LookupSpec:
    """Description of the multi-attribute VDB authored for one field sample."""

    levels: tuple[LookupLevelSpec, ...]
    native_spacing: float
    render_bounds: tuple[float, float, float, float]
    angle_range: tuple[float, float]
    domain_spacing: float
    domain_dims: tuple[int, int, int]
    domain_nanovdb_voxels: int


@dataclass
class _VolumeState:
    """Renderer payload and lifetime state for one prim and time sample."""

    volumes: tuple[wp.Volume, ...]
    spec: LookupSpec
    generation: int
    retained_objects: tuple[Any, ...]


_volume_compute_lock = threading.Lock()
_volume_generation = 0
_volume_states: weakref.WeakValueDictionary[int, _VolumeState] = weakref.WeakValueDictionary()


def _state_cache_key(state_key: str) -> str:
    return f"[viz:index_axisymmetric_volume]::{state_key}"


def _active_state_cache_key(state_key: str) -> str:
    return f"[viz:index_axisymmetric_volume_active]::{state_key}"


@wp.kernel
def _store_native_blocks(
    volume: wp.uint64,
    values: wp.array3d(dtype=wp.float32),
    origins: wp.array2d(dtype=wp.int32),
):
    block, j, i = wp.tid()
    wp.volume_store_f(
        volume,
        origins[block, 0] + i,
        origins[block, 1] + j,
        0,
        values[block, j, i],
    )


@wp.kernel
def _store_domain_proxy(
    volume: wp.uint64,
    index_min_x: int,
    index_min_y: int,
    index_min_z: int,
):
    i, j, k = wp.tid()
    wp.volume_store_f(volume, i + index_min_x, j + index_min_y, k + index_min_z, 1.0)


def classify_flash_refinement_levels(
    block_bounds: np.ndarray,
    field_values: np.ndarray,
    cell_dims: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Validate FLASH leaves and classify them by native cell spacing.

    The returned ``spacings`` are ordered finest to coarsest, and
    ``assignments`` maps every input leaf to an entry in that array. This
    function classifies only; it performs no refinement or value resampling.
    """
    bounds = np.ascontiguousarray(block_bounds, dtype=np.float32)
    values = np.ascontiguousarray(field_values, dtype=np.float32)
    cell_nx, cell_ny = (int(value) for value in cell_dims)
    if cell_nx <= 0 or cell_ny <= 0:
        raise ValueError(f"Expected positive FLASH cell dimensions, got {cell_dims}.")
    if bounds.ndim != 2 or bounds.shape[1] != 4:
        raise ValueError(f"Expected block bounds shaped (N, 4), got {bounds.shape}.")
    if bounds.shape[0] == 0:
        raise ValueError("Direct axisymmetric rendering requires at least one FLASH leaf block.")
    if not np.all(np.isfinite(bounds)):
        raise ValueError("FLASH leaf bounds must contain only finite values.")
    if values.shape != (bounds.shape[0], cell_ny, cell_nx):
        raise ValueError(f"Expected field values shaped {(bounds.shape[0], cell_ny, cell_nx)}, got {values.shape}.")
    radial_spacing = (bounds[:, 1] - bounds[:, 0]) / cell_nx
    axial_spacing = (bounds[:, 3] - bounds[:, 2]) / cell_ny
    if np.any(radial_spacing <= 0.0) or np.any(axial_spacing <= 0.0):
        raise ValueError("FLASH leaf bounds must have positive radial and axial extents.")
    if not np.allclose(radial_spacing, axial_spacing, rtol=1e-4, atol=0.0):
        raise ValueError("Direct axisymmetric rendering requires square radial/axial FLASH cells.")
    finest = float(np.min(radial_spacing))
    ratios = np.rint(radial_spacing / finest).astype(np.int32)
    if not np.allclose(radial_spacing, finest * ratios, rtol=1e-4, atol=0.0):
        raise ValueError("FLASH leaf spacings are not integral multiples of the finest spacing.")
    unique_ratios, assignments = np.unique(ratios, return_inverse=True)
    spacings = finest * unique_ratios.astype(np.float32)
    if spacings.size > MAX_REFINEMENT_LEVELS:
        raise ValueError(
            f"Direct axisymmetric rendering supports at most {MAX_REFINEMENT_LEVELS} refinement levels, "
            f"got {spacings.size}."
        )
    return bounds, values, spacings, assignments


def build_flash_lookup(dataset, prim: Usd.Prim, timecode: Usd.TimeCode) -> tuple[LookupSpec, int]:
    """Build the domain and native-level attributes for one FLASH field sample.

    The resulting state contains the coarse 3D domain first, followed by one
    sparse, one-voxel-thick NanoVDB for each native refinement level. The
    returned generation identifies this exact payload to the asynchronous
    IndeX loader.
    """
    flash = getattr(dataset.handle, "flash", None)
    if flash is None:
        raise ValueError("Direct axisymmetric volume rendering currently supports FLASH AMR datasets only.")
    if not dataset.has_field("colors"):
        raise ValueError("Direct axisymmetric volume rendering requires the 'colors' field selection.")

    all_bounds = np.asarray(flash.block_bounds.numpy(), dtype=np.float32)
    leaf_indices = np.asarray(flash.leaf_block_indices.numpy(), dtype=np.int32)
    cell_dims = (int(flash.cell_dims.x), int(flash.cell_dims.y))
    field = dataset.get_field("colors")
    field_data = field.get_data()
    # FLASH representation fields are analytical. Do not materialize the
    # represented field, which has an angularly expanded logical length;
    # unwrap and materialize only its compact source-block values.
    source_field = field_data[0] if isinstance(field_data, tuple) else field
    all_values = np.asarray(source_field.to_array().numpy(), dtype=np.float32)
    expected_value_count = all_bounds.shape[0] * cell_dims[0] * cell_dims[1]
    if all_values.size != expected_value_count:
        raise ValueError(
            "Direct axisymmetric rendering requires one scalar value per native FLASH cell; "
            f"expected {expected_value_count} values, got {all_values.size}."
        )
    all_values = all_values.reshape(all_bounds.shape[0], -1)
    leaf_bounds = all_bounds[leaf_indices]
    leaf_values = all_values[leaf_indices].reshape(leaf_indices.size, cell_dims[1], cell_dims[0])
    leaf_bounds, leaf_values, spacings, assignments = classify_flash_refinement_levels(
        leaf_bounds, leaf_values, cell_dims
    )
    device = wp.get_cuda_device(0)
    volumes = []
    level_specs = []
    cell_nx, cell_ny = cell_dims
    ii, jj = np.meshgrid(
        np.arange(cell_nx, dtype=np.int32),
        np.arange(cell_ny, dtype=np.int32),
    )
    for level, spacing in enumerate(spacings):
        mask = assignments == level
        if not np.any(mask):
            raise RuntimeError(f"Internal error: native refinement level {level} has no leaf blocks.")
        bounds = leaf_bounds[mask]
        values = np.ascontiguousarray(leaf_values[mask])
        origins = np.rint(np.column_stack((bounds[:, 0], bounds[:, 2])) / spacing).astype(np.int32)
        voxel_points = np.empty((bounds.shape[0], cell_ny, cell_nx, 3), dtype=np.int32)
        voxel_points[..., 0] = origins[:, None, None, 0] + ii
        voxel_points[..., 1] = origins[:, None, None, 1] + jj
        voxel_points[..., 2] = 0
        volume = wp.Volume.allocate_by_tiles(
            wp.array(np.ascontiguousarray(voxel_points.reshape(-1, 3)), dtype=wp.int32, device=device),
            voxel_size=float(spacing),
            bg_value=float("nan"),
            device=device,
        )
        wp.launch(
            _store_native_blocks,
            dim=(bounds.shape[0], cell_ny, cell_nx),
            inputs=[
                volume.id,
                wp.array(values, dtype=wp.float32, device=device),
                wp.array(origins, dtype=wp.int32, device=device),
            ],
            device=device,
        )
        volumes.append(volume)
        level_specs.append(
            LookupLevelSpec(
                spacing=float(spacing),
                block_count=int(bounds.shape[0]),
                native_cells=int(values.size),
                nanovdb_voxels=int(volume.get_voxel_count()),
            )
        )
    render_bounds = (
        float(np.min(leaf_bounds[:, 0])),
        float(np.max(leaf_bounds[:, 1])),
        float(np.min(leaf_bounds[:, 2])),
        float(np.max(leaf_bounds[:, 3])),
    )
    radial_max = max(abs(render_bounds[0]), abs(render_bounds[1]))
    domain_min = np.asarray((-radial_max, render_bounds[2], -radial_max), dtype=np.float32)
    domain_max = np.asarray((radial_max, render_bounds[3], radial_max), dtype=np.float32)
    domain_spacing = float(np.max(domain_max - domain_min) / DOMAIN_RESOLUTION)
    if not math.isfinite(domain_spacing) or domain_spacing <= 0.0:
        raise ValueError("Direct axisymmetric rendering requires non-empty finite bounds.")
    domain_index_min = np.floor(domain_min / domain_spacing).astype(np.int32)
    domain_index_max = np.ceil(domain_max / domain_spacing).astype(np.int32) - 1
    domain_dims_array = domain_index_max - domain_index_min + 1
    domain_volume = wp.Volume.allocate(
        min=domain_index_min.tolist(),
        max=domain_index_max.tolist(),
        voxel_size=domain_spacing,
        bg_value=1.0,
        device=device,
    )
    wp.launch(
        _store_domain_proxy,
        dim=tuple(int(value) for value in domain_dims_array),
        inputs=[
            domain_volume.id,
            int(domain_index_min[0]),
            int(domain_index_min[1]),
            int(domain_index_min[2]),
        ],
        device=device,
    )
    wp.synchronize_device(device)
    spec = LookupSpec(
        levels=tuple(level_specs),
        native_spacing=float(spacings[0]),
        render_bounds=render_bounds,
        angle_range=(
            float(flash.angle_min),
            float(flash.angle_min + flash.angle_step * flash.angular_cells),
        ),
        domain_spacing=domain_spacing,
        domain_dims=tuple(int(value) for value in domain_dims_array),
        domain_nanovdb_voxels=int(domain_volume.get_voxel_count()),
    )
    state_key = str(prim.GetPath())
    with _volume_compute_lock:
        global _volume_generation
        _volume_generation += 1
        generation = _volume_generation
        state = _VolumeState(
            volumes=(domain_volume, *volumes),
            spec=spec,
            generation=generation,
            retained_objects=(),
        )
        _volume_states[generation] = state
        cache.put_ex(
            _state_cache_key(state_key),
            state,
            prims=[cache.PrimWatch(prim, on="delete")],
            force=True,
            timeCode=timecode,
        )
    logger.info(
        "Built one axisymmetric self-VDB for %s: %d native level attributes, %d cells, "
        "%d level voxels, %d domain voxels",
        state_key,
        len(spec.levels),
        sum(level.native_cells for level in spec.levels),
        sum(level.nanovdb_voxels for level in spec.levels),
        spec.domain_nanovdb_voxels,
    )
    return spec, generation


def configure_volume(
    prim: Usd.Prim,
    spec: LookupSpec,
    generation: int,
    timecode: Usd.TimeCode,
    sampling_distance_scale: float,
) -> None:
    """Author the IndeX importer, ray-step, and XAC contract on the public prim.

    Attribute zero establishes ray-march coverage. Shader parameters describe
    the native spacing of attributes one through ``N``; the actual buffers are
    supplied later by :class:`AxisymmetricVolumeCompute`.
    """
    if not math.isfinite(sampling_distance_scale) or sampling_distance_scale <= 0.0:
        raise ValueError("Sampling Distance Scale must be a positive finite number.")
    volume = UsdVol.Volume(prim)
    radial_max = max(abs(spec.render_bounds[0]), abs(spec.render_bounds[1]))
    volume.CreateExtentAttr().Set(
        [
            Gf.Vec3f(-radial_max, spec.render_bounds[2], -radial_max),
            Gf.Vec3f(radial_max, spec.render_bounds[3], radial_max),
        ]
    )
    prim.GetAttribute("nvindex:type").Set("vdb")
    prim.SetCustomDataByKey(
        "nvindex.renderSettings:samplingDistance",
        Vt.Float(spec.native_spacing * sampling_distance_scale),
    )
    importer = prim.GetChild("Importer")
    importer.SetCustomDataByKey(
        "nvindex.importerSettings",
        {
            "importer": Vt.Token("nv::index::plugin::openvdb_integration.NanoVDB_empty_init_importer"),
            "nb_attributes": Vt.Int(len(spec.levels) + 1),
        },
    )
    loader = UsdShade.Shader(prim.GetChild("Material").GetChild("DataLoader"))
    loader.CreateInput("module_name", Sdf.ValueTypeNames.String).Set("omni.cae.viz.index_axisymmetric_volume")
    loader.CreateInput("class_name", Sdf.ValueTypeNames.String).Set("AxisymmetricVolumeCompute")
    loader.CreateInput("enabled", Sdf.ValueTypeNames.Bool).Set(True)
    loader.CreateInput("is_gpu_operation", Sdf.ValueTypeNames.Bool).Set(True)
    loader.CreateInput("params_state_key", Sdf.ValueTypeNames.Token).Set(str(prim.GetPath()))
    loader.CreateInput("params_time_code", Sdf.ValueTypeNames.String).Set(str(timecode))
    loader.CreateInput("params_generation", Sdf.ValueTypeNames.Int).Set(generation)

    material = UsdShade.Material(prim.GetChild("Material"))
    # Reconfigure the shader created with the volume rather than replacing the
    # material output with a newly introduced shader. IndeX may already have
    # registered this scene element before the field selection is authored.
    shader = UsdShade.Shader(material.GetPrim().GetChild("VolumeShader"))
    shader.SetSourceAsset("cae/xac/axisymmetric_volume.xac", "xac")
    colormap_output = material.GetPrim().GetChild("Colormap").GetAttribute("outputs:colormap")
    shader.CreateInput("colormap", Sdf.ValueTypeNames.Token).ConnectToSource(colormap_output.GetPath())
    for old_parameter in (
        "inputs:voxel_size",
        "inputs:mode",
        "inputs:attrib_idx",
        "inputs:time_codes",
        "inputs:lookup_voxel_size",
        "inputs:lookup_angle_range",
        *(f"inputs:slot_{level}" for level in range(MAX_REFINEMENT_LEVELS)),
    ):
        shader.GetPrim().RemoveProperty(old_parameter)
    spacings = [level.spacing for level in spec.levels]
    spacings.extend([0.0] * (MAX_REFINEMENT_LEVELS - len(spacings)))
    for name, value, parameter_index in (
        ("lookup_voxel_sizes_0_3", Gf.Vec4f(*spacings[:4]), 0),
        ("lookup_voxel_sizes_4_7", Gf.Vec4f(*spacings[4:]), 1),
        ("lookup_level_count", len(spec.levels), 2),
        ("lookup_angle_range", Gf.Vec2f(*spec.angle_range), 3),
    ):
        if name == "lookup_level_count":
            value_type = Sdf.ValueTypeNames.Int
        elif name == "lookup_angle_range":
            value_type = Sdf.ValueTypeNames.Float2
        else:
            value_type = Sdf.ValueTypeNames.Float4
        parameter = shader.CreateInput(name, value_type).GetAttr()
        parameter.Set(value)
        parameter.SetCustomDataByKey("nvindex.param", parameter_index)
    material.CreateOutput("nvindex:volume", Sdf.ValueTypeNames.Token).ConnectToSource(
        shader.CreateOutput("volume", Sdf.ValueTypeNames.Token)
    )
    prim.GetAttribute("nvindex:composite").Set(True)


async def prepare(
    prim: Usd.Prim,
    dataset,
    timecode: Usd.TimeCode,
    sampling_distance_scale: float,
) -> LookupSpec:
    """Build and atomically bind the direct-axisymmetric rendering pipeline.

    Compositing is disabled while the existing public volume's loader and
    material are reconfigured, then re-enabled after the complete contract has
    been authored.
    """
    spec, generation = build_flash_lookup(dataset, prim, timecode)
    with Sdf.ChangeBlock():
        with viz_utils.edit_context(prim):
            prim.GetAttribute("nvindex:composite").Set(False)
            configure_volume(prim, spec, generation, timecode, sampling_distance_scale)
    return spec


def _parse_time_code(value: Any) -> Usd.TimeCode:
    """Parse a DataLoader parameter back into its cache time-code key."""
    if isinstance(value, Usd.TimeCode):
        return value
    if value is None or str(value) == str(Usd.TimeCode.EarliestTime()):
        return Usd.TimeCode.EarliestTime()
    return Usd.TimeCode(float(value))


class AxisymmetricVolumeCompute:
    """Adopt all attributes into the public VDB and retain their lifetimes.

    IndeX calls this class through the authored ``DataLoader`` shader. DLPack
    adoption avoids a host round trip and preserves the ordered attribute
    contract: domain first, followed by native levels from finest to coarsest.
    """

    def __init__(self, params: dict):
        self.params = params.copy()

    def launch_compute(self, dst_buffer):
        state_key = str(self.params.get("state_key", ""))
        timecode = _parse_time_code(self.params.get("time_code"))
        generation = int(self.params.get("generation", -1))

        with _volume_compute_lock:
            state = _volume_states.get(generation)
            if state is None:
                logger.warning(
                    "Skipping stale axisymmetric lookup generation %d for %s at %s; "
                    "its cached payload has already been released.",
                    generation,
                    state_key,
                    timecode,
                )
                return
            device_subset = dst_buffer.get_distributed_data_subset().get_device_subset()
            target_device = wp.get_cuda_device(device_subset.get_device_id())
            retained_objects = []
            for attribute, volume in enumerate(state.volumes):
                dlpack_array = array_utils.get_nanovdb_dlpack_array(volume)
                if dlpack_array.device != target_device:
                    dlpack_array = dlpack_array.to(target_device)
                with target_device.context_guard:
                    adoption = device_subset.adopt_dlpack(attribute, dlpack_array)
                retained_objects.extend((adoption, dlpack_array))
            state.retained_objects = tuple(retained_objects)
            prim = get_context().get_stage().GetPrimAtPath(state_key)
            if prim:
                # Keep the currently rendered generation alive independently
                # of the time-scoped cache. Structural invalidation can then
                # clear all samples while this entry retains the old buffers
                # until a replacement has completed adoption.
                active_key = _active_state_cache_key(state_key)
                active_prims = (
                    []
                    if cache.get(active_key, timeCode=Usd.TimeCode.EarliestTime()) is not None
                    else [cache.PrimWatch(prim, on="delete")]
                )
                cache.put_ex(
                    active_key,
                    state,
                    prims=active_prims,
                    force=True,
                    timeCode=Usd.TimeCode.EarliestTime(),
                )
        prim = get_context().get_stage().GetPrimAtPath(state_key)
        if not prim:
            logger.debug("Axisymmetric volume %s was deleted before VDB adoption completed.", state_key)
            return
