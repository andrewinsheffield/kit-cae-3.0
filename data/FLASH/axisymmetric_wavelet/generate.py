# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Generate a small, deterministic axisymmetric FLASH PARAMESH series.

The scalar field follows the analytic function used by VTK's
``vtkRTAnalyticSource``.  A thresholded form creates a compact isovolume whose
oscillating boundary changes over time.  AMR blocks follow that boundary with
progressively deeper, 2:1-balanced refinement.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

ROOT_BLOCKS = (4, 8)
CELLS_PER_BLOCK = (8, 8)
DOMAIN = (0.0, 1.0, -1.0, 1.0)
ISO_VALUE = 135.0
REFINEMENT_BAND = 42.0
SNAPSHOTS = (
    # maximum level, radial frequency, axial frequency, phase
    (2, 30.0, 20.0, 0.00),
    (3, 45.0, 25.0, 0.55),
    (4, 60.0, 30.0, 1.10),
)

BlockKey = tuple[int, int, int]


@dataclass(frozen=True)
class SnapshotParameters:
    maximum_level: int
    radial_frequency: float
    axial_frequency: float
    phase: float


def _block_bounds(key: BlockKey) -> tuple[float, float, float, float]:
    level, radial_index, axial_index = key
    scale = 1 << (level - 1)
    radial_blocks = ROOT_BLOCKS[0] * scale
    axial_blocks = ROOT_BLOCKS[1] * scale
    radial_min, radial_max, axial_min, axial_max = DOMAIN
    radial_width = (radial_max - radial_min) / radial_blocks
    axial_width = (axial_max - axial_min) / axial_blocks
    return (
        radial_min + radial_index * radial_width,
        radial_min + (radial_index + 1) * radial_width,
        axial_min + axial_index * axial_width,
        axial_min + (axial_index + 1) * axial_width,
    )


def _children(key: BlockKey) -> tuple[BlockKey, BlockKey, BlockKey, BlockKey]:
    level, radial_index, axial_index = key
    child_level = level + 1
    return (
        (child_level, 2 * radial_index, 2 * axial_index),
        (child_level, 2 * radial_index + 1, 2 * axial_index),
        (child_level, 2 * radial_index, 2 * axial_index + 1),
        (child_level, 2 * radial_index + 1, 2 * axial_index + 1),
    )


def _wavelet(radius, axial, parameters: SnapshotParameters):
    """Evaluate a two-dimensional slice of VTK's RT analytic function."""
    radius = np.asarray(radius)
    axial = np.asarray(axial)
    scaled_axial = 0.5 * axial
    center_axial = 0.08 * math.sin(parameters.phase)
    radial_term = radius
    axial_term = scaled_axial - center_axial
    gaussian = 255.0 * np.exp(-(radial_term**2 + axial_term**2) / (2.0 * 0.38**2))
    radial_wave = 10.0 * np.sin(parameters.radial_frequency * radius + parameters.phase)
    axial_wave = 18.0 * np.sin(parameters.axial_frequency * scaled_axial - 0.5 * parameters.phase)
    return gaussian + radial_wave + axial_wave + 5.0


def _near_isosurface(key: BlockKey, parameters: SnapshotParameters) -> bool:
    radial_min, radial_max, axial_min, axial_max = _block_bounds(key)
    radial = np.linspace(radial_min, radial_max, 9, dtype=np.float64)
    axial = np.linspace(axial_min, axial_max, 9, dtype=np.float64)
    rr, zz = np.meshgrid(radial, axial, indexing="xy")
    phi = _wavelet(rr, zz, parameters) - ISO_VALUE
    return bool((phi.min() <= 0.0 <= phi.max()) or np.min(np.abs(phi)) < REFINEMENT_BAND)


def _refine(nodes: set[BlockKey], internal: set[BlockKey], key: BlockKey) -> None:
    if key in internal:
        return
    internal.add(key)
    nodes.update(_children(key))


def _initial_hierarchy(parameters: SnapshotParameters) -> tuple[set[BlockKey], set[BlockKey]]:
    roots = {
        (1, radial_index, axial_index)
        for axial_index in range(ROOT_BLOCKS[1])
        for radial_index in range(ROOT_BLOCKS[0])
    }
    nodes = set(roots)
    internal: set[BlockKey] = set()

    def visit(key: BlockKey) -> None:
        if key[0] >= parameters.maximum_level or not _near_isosurface(key, parameters):
            return
        _refine(nodes, internal, key)
        for child in _children(key):
            visit(child)

    for root in sorted(roots):
        visit(root)
    return nodes, internal


def _share_face(lhs: BlockKey, rhs: BlockKey) -> bool:
    lr0, lr1, lz0, lz1 = _block_bounds(lhs)
    rr0, rr1, rz0, rz1 = _block_bounds(rhs)
    tolerance = 1.0e-12
    radial_touch = abs(lr1 - rr0) < tolerance or abs(rr1 - lr0) < tolerance
    axial_overlap = min(lz1, rz1) - max(lz0, rz0) > tolerance
    axial_touch = abs(lz1 - rz0) < tolerance or abs(rz1 - lz0) < tolerance
    radial_overlap = min(lr1, rr1) - max(lr0, rr0) > tolerance
    return (radial_touch and axial_overlap) or (axial_touch and radial_overlap)


def _balance_hierarchy(
    nodes: set[BlockKey],
    internal: set[BlockKey],
    maximum_level: int,
) -> None:
    """Refine coarse leaves until face-adjacent leaves differ by at most one level."""
    while True:
        leaves = sorted(nodes - internal)
        refine: set[BlockKey] = set()
        for index, lhs in enumerate(leaves):
            for rhs in leaves[index + 1 :]:
                if abs(lhs[0] - rhs[0]) > 1 and _share_face(lhs, rhs):
                    refine.add(lhs if lhs[0] < rhs[0] else rhs)
        refine = {key for key in refine if key[0] < maximum_level}
        if not refine:
            return
        for key in refine:
            _refine(nodes, internal, key)


def _same_level_neighbor(key: BlockKey, side: int) -> BlockKey | None:
    level, radial_index, axial_index = key
    scale = 1 << (level - 1)
    radial_blocks = ROOT_BLOCKS[0] * scale
    axial_blocks = ROOT_BLOCKS[1] * scale
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    radial_index += offsets[side][0]
    axial_index += offsets[side][1]
    if radial_index < 0 or radial_index >= radial_blocks or axial_index < 0 or axial_index >= axial_blocks:
        return None
    return (level, radial_index, axial_index)


def _create_hierarchy(parameters: SnapshotParameters):
    nodes, internal = _initial_hierarchy(parameters)
    _balance_hierarchy(nodes, internal, parameters.maximum_level)
    ordered = sorted(nodes, key=lambda key: (key[0], key[2], key[1]))
    block_ids = {key: index + 1 for index, key in enumerate(ordered)}

    gid = np.full((len(ordered), 9), -1, dtype=np.int32)
    node_type = np.ones(len(ordered), dtype=np.int32)
    refinement_level = np.empty(len(ordered), dtype=np.int32)
    bounds = np.zeros((len(ordered), 3, 2), dtype=np.float32)
    coordinates = np.zeros((len(ordered), 3), dtype=np.float32)
    block_size = np.zeros((len(ordered), 3), dtype=np.float32)

    for block_index, key in enumerate(ordered):
        level, radial_index, axial_index = key
        refinement_level[block_index] = level
        for side in range(4):
            neighbor = _same_level_neighbor(key, side)
            if neighbor in block_ids:
                gid[block_index, side] = block_ids[neighbor]
        if level > 1:
            gid[block_index, 4] = block_ids[(level - 1, radial_index // 2, axial_index // 2)]
        if key in internal:
            node_type[block_index] = 2
            gid[block_index, 5:9] = [block_ids[child] for child in _children(key)]

        radial_min, radial_max, axial_min, axial_max = _block_bounds(key)
        bounds[block_index] = (
            (radial_min, radial_max),
            (axial_min, axial_max),
            (0.0, 0.0),
        )
        coordinates[block_index] = (
            0.5 * (radial_min + radial_max),
            0.5 * (axial_min + axial_max),
            0.0,
        )
        block_size[block_index] = (
            radial_max - radial_min,
            axial_max - axial_min,
            0.0,
        )

    return ordered, internal, gid, node_type, refinement_level, bounds, coordinates, block_size


def _create_fields(ordered: list[BlockKey], parameters: SnapshotParameters):
    block_count = len(ordered)
    radial_cells, axial_cells = CELLS_PER_BLOCK
    wave = np.empty((block_count, 1, axial_cells, radial_cells), dtype=np.float32)
    density = np.empty_like(wave)
    normalization = 255.0 + 10.0 + 18.0 + 5.0 - ISO_VALUE

    for block_index, key in enumerate(ordered):
        radial_min, radial_max, axial_min, axial_max = _block_bounds(key)
        radial = radial_min + (np.arange(radial_cells) + 0.5) * (radial_max - radial_min) / radial_cells
        axial = axial_min + (np.arange(axial_cells) + 0.5) * (axial_max - axial_min) / axial_cells
        rr, zz = np.meshgrid(radial, axial, indexing="xy")
        values = _wavelet(rr, zz, parameters)
        wave[block_index, 0] = values
        density[block_index, 0] = np.clip((values - ISO_VALUE) / normalization, 0.0, 1.0)
    return density, wave


def _compound_scalars(names: list[str], values, value_dtype: str):
    dtype = np.dtype([("name", "S512"), ("value", value_dtype)])
    result = np.zeros(len(names), dtype=dtype)
    result["name"] = [name.encode("ascii") for name in names]
    result["value"] = values
    return result


def _sim_info(step: int):
    dtype = np.dtype(
        [
            ("file format version", "<i4"),
            ("setup call", "S400"),
            ("file creation time", "S512"),
            ("flash version", "S512"),
            ("build date", "S512"),
            ("build dir", "S512"),
            ("build machine", "S512"),
            ("cflags", "S400"),
            ("fflags", "S400"),
            ("setup time stamp", "S512"),
            ("build time stamp", "S512"),
        ]
    )
    result = np.zeros(1, dtype=dtype)
    result["file format version"] = 9
    result["setup call"] = b"kit-cae deterministic axisymmetric wavelet fixture"
    result["file creation time"] = f"fixture timestep {step}".encode("ascii")
    result["flash version"] = b"FLASH-compatible synthetic fixture"
    result["build machine"] = b"programmatically generated"
    return result


def _validate_hierarchy(gid: np.ndarray, node_type: np.ndarray) -> None:
    block_count = len(node_type)
    positive = gid[gid > 0]
    if positive.size and int(positive.max()) > block_count:
        raise RuntimeError("GID references a block outside the hierarchy")
    for block_index in range(block_count):
        block_id = block_index + 1
        parent_id = int(gid[block_index, 4])
        children = gid[block_index, 5:9]
        if node_type[block_index] == 1 and np.any(children > 0):
            raise RuntimeError(f"leaf block {block_id} unexpectedly has children")
        if node_type[block_index] == 2 and np.any(children <= 0):
            raise RuntimeError(f"internal block {block_id} does not have four children")
        for child_id in children[children > 0]:
            if int(gid[int(child_id) - 1, 4]) != block_id:
                raise RuntimeError(f"parent/child mismatch for blocks {block_id} and {int(child_id)}")
        if parent_id > 0 and block_id not in gid[parent_id - 1, 5:9]:
            raise RuntimeError(f"child/parent mismatch for blocks {block_id} and {parent_id}")


def _write_snapshot(output: Path, step: int, raw_parameters) -> None:
    parameters = SnapshotParameters(*raw_parameters)
    hierarchy = _create_hierarchy(parameters)
    ordered, internal, gid, node_type, refinement_level, bounds, coordinates, block_size = hierarchy
    density, wave = _create_fields(ordered, parameters)
    _validate_hierarchy(gid, node_type)

    path = output / f"hdf5_plt_cnt_{step:04d}"
    with h5py.File(path, "w") as handle:
        handle.create_dataset(
            "integer scalars",
            data=_compound_scalars(
                ["nxb", "nyb", "nzb", "globalnumblocks", "nstep"],
                [CELLS_PER_BLOCK[0], CELLS_PER_BLOCK[1], 1, len(ordered), step],
                "<i4",
            ),
        )
        handle.create_dataset("real scalars", data=_compound_scalars(["time"], [float(step)], "<f8"))
        handle.create_dataset("sim info", data=_sim_info(step))
        handle.create_dataset("unknown names", data=np.asarray([[b"dens"], [b"wave"]], dtype="S4"))
        handle.create_dataset("gid", data=gid)
        handle.create_dataset("node type", data=node_type)
        handle.create_dataset("refine level", data=refinement_level)
        handle.create_dataset("bounding box", data=bounds)
        handle.create_dataset("coordinates", data=coordinates)
        handle.create_dataset("block size", data=block_size)
        handle.create_dataset("processor number", data=np.zeros(len(ordered), dtype=np.int32))
        handle.create_dataset("dens", data=density)
        handle.create_dataset("wave", data=wave)

    leaf_levels, leaf_counts = np.unique(refinement_level[node_type == 1], return_counts=True)
    summary = ", ".join(f"L{int(level)}={int(count)}" for level, count in zip(leaf_levels, leaf_counts))
    print(
        f"{path.name}: blocks={len(ordered)}, leaves={len(ordered) - len(internal)}, "
        f"leaf levels: {summary}, dens=[{density.min():.3f}, {density.max():.3f}]"
    )


def generate(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for step, parameters in enumerate(SNAPSHOTS):
        _write_snapshot(output, step, parameters)
    descriptor = {
        "format": "flash-paramesh-hdf5",
        "version": 1,
        "pattern": "hdf5_plt_cnt_*",
    }
    (output / "axisymmetric_wavelet.flash").write_text(json.dumps(descriptor, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="output directory (defaults to the directory containing this script)",
    )
    args = parser.parse_args()
    generate(args.output.resolve())


if __name__ == "__main__":
    main()
