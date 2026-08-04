# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import ctypes
from logging import getLogger
from typing import Any, Union

import numpy as np
import warp as wp
from usdrt import Vt as VtRT
from warp.types import vector

from .typing import FieldArrayLike

logger = getLogger(__name__)


def _to_warp_vector_dtype(length: int, scalar_dtype: Any) -> Any:
    suffix_by_dtype_name = (
        ("int8", "b"),
        ("uint8", "ub"),
        ("int16", "s"),
        ("uint16", "us"),
        ("int32", "i"),
        ("uint32", "ui"),
        ("int64", "l"),
        ("uint64", "ul"),
        ("float16", "h"),
        ("float32", "f"),
        ("float64", "d"),
    )

    for dtype_name, suffix in suffix_by_dtype_name:
        if scalar_dtype == getattr(wp, dtype_name, None):
            vector_dtype = getattr(wp, f"vec{length}{suffix}", None)
            if vector_dtype is not None:
                return vector_dtype
            break

    return vector(length=length, dtype=scalar_dtype)


_WARP_TO_NUMPY_DTYPE = {
    wp.int8: np.dtype(np.int8),
    wp.int16: np.dtype(np.int16),
    wp.int32: np.dtype(np.int32),
    wp.int64: np.dtype(np.int64),
    wp.uint8: np.dtype(np.uint8),
    wp.uint16: np.dtype(np.uint16),
    wp.uint32: np.dtype(np.uint32),
    wp.uint64: np.dtype(np.uint64),
    wp.float16: np.dtype(np.float16),
    wp.float32: np.dtype(np.float32),
    wp.float64: np.dtype(np.float64),
}


def get_device(array: FieldArrayLike) -> Any:
    if isinstance(array, wp.array):
        return array.device
    elif hasattr(array, "__cuda_array_interface__"):
        # FIXME: we'll need to fix this to work correctly for multi-gpu
        return wp.get_cuda_device(0)
    elif hasattr(array, "__array_interface__"):
        return wp.get_device("cpu")
    raise RuntimeError("Cannot determine device %s!" % type(array))


def _to_warp_dtype(array: FieldArrayLike) -> Any:
    """
    Returns a Warp dtype object suitable for passing to ``wp.array``.

    One-dimensional inputs return the matching scalar Warp dtype. Two-dimensional
    inputs with multiple components return a Warp vector dtype whose length
    matches the second dimension and whose scalar type matches the input dtype.
    """
    if isinstance(array, wp.array):
        return array.dtype
    elif isinstance(array, np.ndarray):
        scalar_dtype = wp.dtype_from_numpy(array.dtype)
    elif hasattr(array, "dtype"):
        scalar_dtype = wp.dtype_from_numpy(np.dtype(array.dtype))
    else:
        raise RuntimeError("Cannot determine warp_dtype!")

    if array.ndim == 2 and array.shape[1] > 1:
        return _to_warp_vector_dtype(length=array.shape[1], scalar_dtype=scalar_dtype)
    return scalar_dtype


def _to_numpy_dtype(array: FieldArrayLike) -> np.dtype:
    if isinstance(array, wp.array):
        type_args = getattr(array.dtype, "_wp_type_args_", None)
        scalar_dtype = type_args.get("dtype") if type_args else array.dtype
        if scalar_dtype in _WARP_TO_NUMPY_DTYPE:
            return _WARP_TO_NUMPY_DTYPE[scalar_dtype]
        return array.numpy().dtype
    if hasattr(array, "dtype"):
        return np.dtype(array.dtype)
    return np.asarray(array).dtype


def get_numpy_dtype(array: FieldArrayLike) -> np.dtype:
    """Return the scalar NumPy dtype for a NumPy or Warp-backed array."""
    return _to_numpy_dtype(array)


def _to_warp_cast_dtype(array: wp.array, dtype: np.dtype) -> Any:
    scalar_dtype = wp.dtype_from_numpy(dtype)
    type_args = getattr(array.dtype, "_wp_type_args_", None)
    if type_args:
        return _to_warp_vector_dtype(length=type_args["length"], scalar_dtype=scalar_dtype)
    return scalar_dtype


def as_warp_array(array: FieldArrayLike) -> Union[wp.array, None]:
    """
    Returns a zero-copied warp.array from any object that supports
    the CUDA Array Interface or NumPy Array Interface.

    The returned array is hosted on the same device as the input array since
    this function does not copy the array.
    """
    if array is None:
        return None

    if isinstance(array, wp.array):
        return array

    return wp.array(data=array, copy=False, dtype=_to_warp_dtype(array), device=get_device(array))


def as_numpy_array(array: FieldArrayLike) -> np.ndarray:
    if array is None:
        return None
    elif isinstance(array, np.ndarray):
        return array
    elif isinstance(array, wp.array):
        return array.numpy()
    else:
        device = get_device(array)
        if device.is_cpu:
            return np.asarray(array)
        else:
            return wp.array(array, copy=False, device=device).numpy()


def get_nanovdb_dlpack_array(volume: wp.Volume) -> wp.array:
    """
    Return a DLPack-exporting Warp array that aliases a NanoVDB grid buffer.

    Do not use ``wp.Volume.array()`` for this path: it exposes the grid as one
    ``uint8`` element per byte, which can overflow element-count limits for large
    NanoVDB buffers. NanoVDB buffers are 8-byte aligned, so this helper aliases
    the same storage as ``uint64`` and attaches a no-op deleter that keeps the
    source volume alive while DLPack consumers hold the exported array.
    """
    buf = ctypes.c_void_p(0)
    size = ctypes.c_uint64(0)
    volume.runtime.core.wp_volume_get_buffer_info(volume.id, ctypes.byref(buf), ctypes.byref(size))
    if not buf.value:
        raise RuntimeError("NanoVDB volume has a null grid buffer.")

    def hold_volume(_ptr: int, _size: int, _volume: wp.Volume = volume) -> None:
        pass

    assert size.value % 8 == 0, "NanoVDB grid buffer size must be 8-byte aligned."
    return wp.array(ptr=buf.value, dtype=wp.uint64, shape=size.value // 8, device=volume.device, deleter=hold_volume)


def get_nanovdb_array(volume: wp.Volume) -> wp.array:
    """Return a Warp array aliasing a NanoVDB grid buffer as ``uint64`` values."""
    return get_nanovdb_dlpack_array(volume)


def column_stack(arrays: list[FieldArrayLike]) -> FieldArrayLike:

    if len(arrays) == 0:
        return None

    if len(arrays) == 1:
        return arrays[0]

    device = get_device(arrays[0])

    if not all(get_device(a) == device for a in arrays):
        raise ValueError("All arrays must be on the same device")

    if device.is_cpu:
        return np.column_stack([as_numpy_array(array) for array in arrays])
    else:
        raise RuntimeError("Not implemented yet!")


def compute_quaternions_from_directions(directions: FieldArrayLike) -> np.ndarray:
    assert (
        directions.ndim == 2 and directions.shape[1] == 3
    ), f"Expected shape (N, 3), got {directions.shape}, {directions.dtype}"

    directions = as_numpy_array(directions).astype(np.float32, copy=False)

    # Normalize direction vectors
    norms = np.linalg.norm(directions, axis=1, keepdims=True)
    mask = norms != 0

    inv_norms = np.divide(1.0, norms, out=np.zeros_like(norms), where=mask)
    half_vecs = directions * inv_norms
    half_vecs[:, 0] += 1.0

    half_norms = np.linalg.norm(half_vecs, axis=1, keepdims=True)
    half_vecs = np.divide(half_vecs, half_norms, out=np.zeros_like(half_vecs), where=(half_norms != 0))

    sine_axis = np.zeros_like(half_vecs)
    sine_axis[:, 1] = -half_vecs[:, 2]
    sine_axis[:, 2] = half_vecs[:, 1]
    cos_angle = half_vecs[:, 0]

    # note the stackign order. this is the order expected for Vt.QuathArrayFromBuffer
    return np.column_stack((sine_axis, cos_angle))


def get_scalar_array(array_or_arrays: Union[FieldArrayLike, list[FieldArrayLike]]) -> FieldArrayLike:
    """Return a 1 component array. For multipe components arrays, this returns its magnitude."""

    if array_or_arrays is None:
        raise ValueError("Input array cannot be None!")

    if isinstance(array_or_arrays, list):
        np_array = as_numpy_array(column_stack(array_or_arrays))
    else:
        np_array = as_numpy_array(array_or_arrays)

    if np_array.ndim == 1:
        return np_array
    elif np_array.ndim == 2 and np_array.shape[1] == 1:
        return np_array.ravel()
    elif np_array.ndim == 2 and np_array.shape[1] > 1:
        # compute magnitudes
        return np.linalg.norm(np_array, axis=1)
    else:
        raise ValueError(f"Cannot convert array of shape {np_array.shape} to scalar array!")


@wp.func
def _remap_value(
    v: Any, domain_min: wp.float32, domain_max: wp.float32, data_range_min: wp.float32, data_range_max: wp.float32
) -> Any:
    cast_domain_min = type(v)(domain_min)
    cast_domain_max = type(v)(domain_max)
    v = wp.clamp(v, cast_domain_min, cast_domain_max)
    f32_normalized_v = wp.float32(v - cast_domain_min) / wp.float32(cast_domain_max - cast_domain_min)
    f32_out_v = f32_normalized_v * (data_range_max - data_range_min) + data_range_min
    return type(v)(f32_out_v)


@wp.func
def _remap_value_vector(
    v: Any, domain_min: wp.float32, domain_max: wp.float32, data_range_min: wp.float32, data_range_max: wp.float32
) -> Any:
    for comp in range(v.shape[1]):
        v[comp] = _remap_value(v[comp], domain_min, domain_max, data_range_min, data_range_max)
    return v


@wp.kernel
def _remap_array_kernel_scalar(
    input: wp.array(dtype=Any),
    domain_min: wp.float32,
    domain_max: wp.float32,
    data_range_min: wp.float32,
    data_range_max: wp.float32,
    output: wp.array(dtype=Any),
):
    tid = wp.tid()
    in_v = input[tid]
    output[tid] = _remap_value(in_v, domain_min, domain_max, data_range_min, data_range_max)


@wp.kernel
def _remap_array_kernel_vector(
    input: wp.array(dtype=Any),
    domain_min: wp.float32,
    domain_max: wp.float32,
    data_range_min: wp.float32,
    data_range_max: wp.float32,
    output: wp.array(dtype=Any),
):
    tid = wp.tid()
    output[tid] = _remap_value_vector(input[tid], domain_min, domain_max, data_range_min, data_range_max)


def remap_array(array: FieldArrayLike, domain: tuple[float, float], data_range: tuple[float, float]) -> FieldArrayLike:
    """
    Remaps an array from one domain to another. The values in array are clamped to the domain before remapping.
    If the domain is invalid (domain[0] >= domain[1]), the array is returned unchanged.
    """
    if domain[0] > domain[1]:
        logger.error(f"Invalid domain {domain}.")
        return array

    if array.ndim > 2:
        raise ValueError(f"Unsupported array of shape {array.shape}!")

    in_array = wp.array(array, copy=False, device=get_device(array))
    out_array = wp.zeros_like(in_array, device=in_array.device)
    wp.launch(
        _remap_array_kernel_scalar if in_array.ndim == 1 else _remap_array_kernel_vector,
        dim=in_array.shape[0],
        inputs=[in_array, domain[0], domain[1], data_range[0], data_range[1]],
        outputs=[out_array],
        device=in_array.device,
    )

    return out_array


def to_vtrt_array_with_buffer(array: FieldArrayLike):
    """
    Converts an array-like object to a UsdRT.Array and its backing CPU buffer.

    VtRT arrays constructed from Python buffers alias those buffers. Return the
    buffer with the VtRT array so callers can keep it alive until the VtRT
    consumer has copied the data.
    """
    # VtRT.Array only reliably accepts ndarray here. GPU arrays are explicitly
    # copied through CPU to match the old IFieldArray path.
    cupy_or_np_array = as_numpy_array(array)
    shape = cupy_or_np_array.shape
    dtype = cupy_or_np_array.dtype
    ndim = cupy_or_np_array.ndim

    def as_vtrt_array(vtrt_array_type, buffer: np.ndarray, dtype: np.dtype | None = None):
        vtrt_buffer = buffer
        if dtype is not None:
            # VtRT's int/uint arrays require C int buffer formats ("i"/"I").
            # On Windows, np.int32/uint32 can expose C long formats instead.
            # np.intc/uintc have the same itemsize, so view the data with the
            # C-int dtype metadata rather than copying the values.
            dtype = np.dtype(dtype)
            if vtrt_buffer.dtype.char != dtype.char:
                if vtrt_buffer.dtype.itemsize != dtype.itemsize:
                    raise ValueError(f"Cannot reinterpret {vtrt_buffer.dtype} as {dtype}")
                vtrt_buffer = vtrt_buffer.view(dtype)

        if not vtrt_buffer.flags.c_contiguous:
            # VtRT consumes a flat C-style span. Non-contiguous input has no
            # zero-copy representation for that API, so this is the one case
            # where we intentionally materialize a contiguous buffer.
            raise ValueError("VtRT arrays require contiguous buffers! Please ensure the input array is contiguous.")

        return vtrt_array_type(vtrt_buffer), vtrt_buffer

    if ndim == 1 or ndim == 2 and shape[1] == 1:
        if hasattr(cupy_or_np_array, "reshape"):
            cupy_or_np_array = cupy_or_np_array.reshape(-1, 1)

        # scalar array
        match dtype:
            case np.int32:
                return as_vtrt_array(VtRT.IntArray, cupy_or_np_array, np.intc)
            case np.int64:
                return as_vtrt_array(VtRT.Int64Array, cupy_or_np_array)
            case np.uint32:
                return as_vtrt_array(VtRT.UIntArray, cupy_or_np_array, np.uintc)
            case np.uint64:
                return as_vtrt_array(VtRT.UInt64Array, cupy_or_np_array)
            case np.float32:
                return as_vtrt_array(VtRT.FloatArray, cupy_or_np_array)
            case np.float64:
                return as_vtrt_array(VtRT.DoubleArray, cupy_or_np_array)
            case _:
                raise ValueError(f"Unsupported dtype {dtype} for scalar array of shape {shape}!")
    elif ndim == 2 and shape[1] == 2:
        # vector array
        match dtype:
            case np.int32:
                return as_vtrt_array(VtRT.Int2Array, cupy_or_np_array, np.intc)
            case np.uint32:
                return as_vtrt_array(VtRT.UInt2Array, cupy_or_np_array, np.uintc)
            case np.float32:
                return as_vtrt_array(VtRT.Vec2fArray, cupy_or_np_array)
            case np.float64:
                return as_vtrt_array(VtRT.Vec2dArray, cupy_or_np_array)
            case _:
                raise ValueError(f"Unsupported dtype {dtype} for vector array of shape {shape}!")
    elif ndim == 2 and shape[1] == 3:
        # vector array
        match dtype:
            case np.int32:
                return as_vtrt_array(VtRT.Vec3iArray, cupy_or_np_array, np.intc)
            case np.float32:
                return as_vtrt_array(VtRT.Vec3fArray, cupy_or_np_array)
            case np.float64:
                return as_vtrt_array(VtRT.Vec3dArray, cupy_or_np_array)
            case _:
                raise ValueError(f"Unsupported dtype {dtype} for vector array of shape {shape}!")
    elif ndim == 2 and shape[1] == 4:
        # vector array
        match dtype:
            case np.int32:
                return as_vtrt_array(VtRT.Vec4iArray, cupy_or_np_array, np.intc)
            case np.float32:
                return as_vtrt_array(VtRT.Vec4fArray, cupy_or_np_array)
            case np.float64:
                return as_vtrt_array(VtRT.Vec4dArray, cupy_or_np_array)
            case _:
                raise ValueError(f"Unsupported dtype {dtype} for vector array of shape {shape}!")
    else:
        raise ValueError(f"Unsupported array of shape {shape}!")


def to_vtrt_array(array: FieldArrayLike):
    """
    Converts an array-like object to a UsdRT.Array.

    Callers that immediately pass the result to VtRT/Fabric APIs should prefer
    to_vtrt_array_with_buffer() and keep the returned buffer alive through that
    call.
    """
    vt_array, _buffer = to_vtrt_array_with_buffer(array)
    return vt_array


@wp.kernel
def _as_type_kernel_scalar(
    input: wp.array(dtype=Any),
    output: wp.array(dtype=Any),
    ndim: int,
):
    tid = wp.tid()
    output[tid] = type(output[tid])(input[tid])


@wp.kernel
def _as_type_kernel_vector(
    input: wp.array(dtype=Any),
    output: wp.array(dtype=Any),
    ncomponents: int,
):
    tid = wp.tid()
    for i in range(ncomponents):
        output[tid][i] = type(output[tid][i])(input[tid][i])


def as_type(array: FieldArrayLike, dtype: np.dtype) -> FieldArrayLike:
    if _to_numpy_dtype(array) == np.dtype(dtype):
        return array

    wp_array = as_warp_array(array)
    assert wp_array.ndim in [1, 2], f"Expected array of ndim 1 or 2, got {wp_array.ndim}"
    new_wp_array = wp.zeros(dtype=_to_warp_cast_dtype(wp_array, dtype), shape=wp_array.shape, device=wp_array.device)
    wp.launch(
        _as_type_kernel_scalar if wp_array.ndim == 1 else _as_type_kernel_vector,
        dim=wp_array.shape[0],
        inputs=[wp_array, new_wp_array, wp_array.shape[1] if wp_array.ndim == 2 else 0],
        device=wp_array.device,
    )
    return new_wp_array


@wp.kernel(enable_backward=False)
def _histogram_kernel(
    data: wp.array(dtype=Any),
    counts: wp.array(dtype=wp.int32),
    min_val: wp.float64,
    inv_bin_width: wp.float64,
    num_bins: wp.int32,
):
    tid = wp.tid()
    val = wp.float64(data[tid])
    bin_idx = wp.int32((val - min_val) * inv_bin_width)
    # Skip values outside the [min, max) range entirely
    if bin_idx >= wp.int32(0) and bin_idx < num_bins:
        wp.atomic_add(counts, bin_idx, wp.int32(1))


@wp.kernel(enable_backward=False)
def _sum_kernel(
    data: wp.array(dtype=Any),
    result: wp.array(dtype=wp.float64),
):
    tid = wp.tid()
    wp.atomic_add(result, 0, wp.float64(data[tid]))


def get_scalar_stats(array: FieldArrayLike, num_bins: int = 32) -> dict:
    """Compute histogram, mean, and approximate percentiles for a scalar array using Warp.

    Returns a dict with keys: "counts", "bin_edges", "mean", "min", "max",
    "median", "q1", "q2", "q3", "q4" (quartiles as (lo, hi) tuples).
    """
    device = get_device(array)
    wp_array = wp.array(array, copy=False, device=device)

    if wp_array.ndim == 2:
        wp_array = wp_array.reshape((wp_array.shape[0],))

    n = wp_array.shape[0]

    # Get min/max from the existing range utility (already Warp-based)
    ranges = get_componentwise_ranges(array)
    val_min, val_max = ranges[0]

    # Histogram via Warp
    bin_width = (val_max - val_min) / num_bins if val_max > val_min else 1.0
    inv_bin_width = 1.0 / bin_width if bin_width > 0 else 0.0
    wp_counts = wp.zeros((num_bins,), dtype=wp.int32, device=device)
    wp.launch(
        _histogram_kernel,
        dim=n,
        inputs=[wp_array, wp_counts, wp.float64(val_min), wp.float64(inv_bin_width), wp.int32(num_bins)],
        device=device,
    )
    counts = wp_counts.numpy()

    # Bin edges (computed on CPU, trivial)
    bin_edges = np.linspace(val_min, val_max, num_bins + 1)

    # Sum via Warp for mean
    wp_sum = wp.zeros((1,), dtype=wp.float64, device=device)
    wp.launch(_sum_kernel, dim=n, inputs=[wp_array, wp_sum], device=device)
    mean_val = float(wp_sum.numpy()[0]) / n

    # Approximate percentiles from cumulative histogram
    cumsum = np.cumsum(counts).astype(np.float64)

    def _percentile_from_hist(p):
        target = p * n
        idx = np.searchsorted(cumsum, target, side="left")
        idx = min(idx, num_bins - 1)
        # Linear interpolation within the bin
        prev_count = cumsum[idx - 1] if idx > 0 else 0.0
        bin_frac = (target - prev_count) / max(float(counts[idx]), 1.0)
        return float(bin_edges[idx] + bin_frac * bin_width)

    p25 = _percentile_from_hist(0.25)
    p50 = _percentile_from_hist(0.50)
    p75 = _percentile_from_hist(0.75)

    return {
        "counts": counts.tolist(),
        "bin_edges": bin_edges.tolist(),
        "mean": mean_val,
        "min": val_min,
        "max": val_max,
        "median": p50,
        "q1": (val_min, p25),
        "q2": (p25, p50),
        "q3": (p50, p75),
        "q4": (p75, val_max),
    }


def compute_histogram(array: FieldArrayLike, num_bins: int, range_min: float, range_max: float) -> dict:
    """Compute histogram with a specified range using Warp.

    Returns dict with "counts" and "bin_edges".
    """
    device = get_device(array)
    wp_array = wp.array(array, copy=False, device=device)

    if wp_array.ndim == 2:
        wp_array = wp_array.reshape((wp_array.shape[0],))

    n = wp_array.shape[0]
    bin_width = (range_max - range_min) / num_bins if range_max > range_min else 1.0
    inv_bin_width = 1.0 / bin_width if bin_width > 0 else 0.0
    wp_counts = wp.zeros((num_bins,), dtype=wp.int32, device=device)
    wp.launch(
        _histogram_kernel,
        dim=n,
        inputs=[wp_array, wp_counts, wp.float64(range_min), wp.float64(inv_bin_width), wp.int32(num_bins)],
        device=device,
    )

    return {
        "counts": wp_counts.numpy().tolist(),
        "bin_edges": np.linspace(range_min, range_max, num_bins + 1).tolist(),
    }


def _get_componentwise_ranges_kernel(ndim: int, ncomps: int):
    if wp.static(ndim == 1):

        # scalar array
        @wp.kernel(enable_backward=False)
        def _componentwise_ranges_kernel_scalar(
            input: wp.array(dtype=Any),
            output: wp.array(dtype=Any),
        ):
            tid = wp.tid()
            v = input[tid]
            wp.atomic_min(output, 0, v)
            wp.atomic_max(output, 1, v)

        return _componentwise_ranges_kernel_scalar
    else:

        @wp.kernel(enable_backward=False)
        def _componentwise_ranges_kernel_vector(
            input: wp.array(ndim=2, dtype=Any),
            output: wp.array(ndim=2, dtype=Any),
        ):
            tid = wp.tid()
            for comp in range(wp.static(ncomps)):
                v = input[tid][comp]
                wp.atomic_min(output, 0, comp, v)
                wp.atomic_max(output, 1, comp, v)

        return _componentwise_ranges_kernel_vector


def _get_magnitude_kernel(ncomps: int):
    @wp.kernel(enable_backward=False)
    def _magnitude_kernel(
        input: wp.array(ndim=2, dtype=Any),
        output: wp.array(dtype=wp.float64),
    ):
        tid = wp.tid()
        acc = wp.float64(0.0)
        for comp in range(wp.static(ncomps)):
            v = wp.float64(input[tid][comp])
            acc += v * v
        output[tid] = wp.sqrt(acc)

    return _magnitude_kernel


def get_magnitude(array: FieldArrayLike) -> wp.array:
    """Return per-element L2 magnitudes of a vector array as a scalar Warp array.

    For an array of shape ``(N, C)`` this returns a length-``N`` ``float64`` Warp
    array where each entry is ``sqrt(sum_c v[c]**2)``. Scalar (1-D) inputs are
    returned unchanged as a zero-copied Warp array. The computation runs in a
    Warp kernel so it stays on the array's device and scales to large fields.
    """
    wp_array = wp.array(array, copy=False, device=get_device(array))

    if wp_array.ndim == 1:
        return wp_array
    if wp_array.ndim != 2:
        raise ValueError(f"Unsupported array of shape {wp_array.shape}!")

    ncomps = wp_array.shape[1]
    output = wp.zeros(wp_array.shape[0], dtype=wp.float64, device=wp_array.device)
    wp.launch(
        _get_magnitude_kernel(ncomps),
        dim=wp_array.shape[0],
        inputs=[wp_array],
        outputs=[output],
        device=wp_array.device,
    )
    return output


def get_componentwise_ranges(array: FieldArrayLike) -> list[tuple[float, float]]:
    """
    Get the component-wise ranges of an array. For scalar arrays, this returns a list with a single tuple.
    For vector arrays, this returns a list of tuples corresponding to the range of each component.
    """
    wp_array = wp.array(array, copy=False, device=get_device(array))

    if wp_array.ndim == 1:
        ncomps = 1
    elif wp_array.ndim == 2:
        ncomps = wp_array.shape[1]
    else:
        raise ValueError(f"Unsupported array of shape {wp_array.shape}!")

    kernel = _get_componentwise_ranges_kernel(wp_array.ndim, ncomps)

    zero_val = wp_array[0:1].numpy()
    wp_ranges = wp.array(np.concatenate((zero_val, zero_val), axis=0), device=wp_array.device)
    wp.launch(kernel, dim=wp_array.shape[0], inputs=[wp_array], outputs=[wp_ranges], device=wp_array.device)

    np_ranges = wp_ranges.numpy()
    ranges = []
    for comp in range(ncomps):
        comp_min = np_ranges[0][comp].item() if ncomps > 1 else np_ranges[0].item()
        comp_max = np_ranges[1][comp].item() if ncomps > 1 else np_ranges[1].item()
        ranges.append((comp_min, comp_max))

    return ranges
