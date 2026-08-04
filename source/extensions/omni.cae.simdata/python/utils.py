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
    "get_dataset",
    "pass_fields",
    "probe_fields",
    "fetch_data",
    "lerp_dataset",
]
from logging import getLogger
from typing import Any

import numpy as np
import warp as wp
import warp_simdata as simdata
import warp_simdata.operators.probe
from omni.cae.core import progress, usd_utils
from pxr import Usd

from .command_types import ConvertToSimDataSet

logger = getLogger(__name__)


def fetch_data(dataset: simdata.Dataset, field_name: str) -> np.ndarray:
    """
    Fetches field data from a dataset as a NumPy array.

    Parameters
    ----------
    dataset : simdata.Dataset
        The dataset to fetch the field data from
    field_name : str
        The name of the field to fetch the data from

    Returns
    -------
    np.ndarray
        The field data as a NumPy array
    """
    if not dataset.has_field(field_name):
        raise ValueError(f"Field '{field_name}' not found in dataset.")

    field = dataset.get_field(field_name)
    return field.to_array().numpy()


async def get_dataset(
    dataset_prim: Usd.Prim,
    timeCode: Usd.TimeCode,
    device: str,
    needs_topology: bool,
    needs_geometry: bool,
    representation: Any = None,
) -> simdata.Dataset:
    """
    Internal utility to build a dataset from a dataset prim.

    Parameters
    ----------
    dataset_prim : Usd.Prim
        The prim from which to build the dataset
    timeCode : Usd.TimeCode
        The time code for which to fetch the dataset
    device : str
        The device on which to load the dataset
    needs_topology : bool
        Whether the dataset needs topology information
    needs_geometry : bool
        Whether the dataset needs geometry information

    Returns
    -------
    simdata.Dataset
        The loaded dataset
    """
    # snap time-code to nearest time sample needed for dataset without fields.
    # this ensures that for datasets where only the fields are time-varying, we don't bother
    # geometry/topology fetching for the timesteps.
    timeCode = usd_utils.snap_time_code_to_prim(dataset_prim, timeCode, traverse_field_relationships=False)
    return await ConvertToSimDataSet.invoke(
        dataset_prim, device, timeCode, needs_topology, needs_geometry, representation=representation
    )


def probe_fields(
    source_dataset: simdata.Dataset,
    target_dataset: simdata.Dataset,
    *,
    fields: set[str] | None = None,
    exclude_fields: set[str] | None = None,
) -> simdata.Dataset:
    """
    Utility to probe fields from a source dataset onto a target dataset based on matching associations and topology.

    Parameters
    ----------
    source_dataset : simdata.Dataset
        The source dataset containing fields to probe from
    target_dataset : simdata.Dataset
        The target dataset to probe fields onto
    fields : set[str], optional
        A set of field names to probe. If empty, all fields from the source dataset are probed, by default set()
    exclude_fields : set[str], optional
        A set of field names to exclude from probing. If empty, no fields are excluded, by default set()
    Returns
    -------
    simdata.Dataset
        The target dataset with probed fields added
    """
    fields = fields or set()
    exclude_fields = exclude_fields or set()
    for field_name in source_dataset.get_field_names():
        if fields and field_name not in fields:
            logger.debug(f"Field '{field_name}' not in specified fields to probe; skipping.")
        elif field_name in exclude_fields:
            logger.debug(f"Field '{field_name}' in exclude fields; skipping.")
        elif target_dataset.has_field(field_name):
            logger.debug(f"Field '{field_name}' already exists in target dataset; skipping probe.")
        else:
            with progress.ProgressContext("Executing SimData [probe]"):
                target_dataset = simdata.operators.probe.compute(
                    source_dataset, field_name, target_dataset, output_field_name=field_name
                )
    return target_dataset


@simdata.cached
def _get_extract_elements_kernel(field_model: simdata.FieldModel, indices_model: simdata.FieldModel, dtype: Any):
    """
    Get a kernel to extract elements from a field based on indices.
    """

    @wp.kernel(enable_backward=False, module="unique")
    def extract_elements_kernel(
        field: field_model.FieldHandle, indices: indices_model.FieldHandle, result: wp.array(dtype=dtype)
    ):
        tid = wp.tid()
        idx = indices_model.FieldAPI.get(indices, tid)
        result[tid] = field_model.FieldAPI.get(field, idx)

    return extract_elements_kernel


def _extract_elements(field: simdata.Field, indices: simdata.Field) -> wp.array:
    """
    Extract elements from a field based on indices.
    """
    result = wp.zeros(indices.size, dtype=field.dtype, device=field.device)

    kernel = _get_extract_elements_kernel(field.field_model, indices.field_model, field.dtype)
    wp.launch(kernel, dim=indices.size, inputs=[field.handle, indices.handle, result], device=field.device)
    return result


def pass_fields(
    source_dataset: simdata.Dataset,
    target_dataset: simdata.Dataset,
    *,
    fields: set[str] | None = None,
    exclude_fields: set[str] | None = None,
) -> simdata.Dataset:
    """
    Utility to pass fields from a source dataset to a target dataset.
    """
    fields = fields or set()
    exclude_fields = exclude_fields or set()
    node_idx = target_dataset.get_field("node_idx") if target_dataset.has_field("node_idx") else None
    element_idx = target_dataset.get_field("element_idx") if target_dataset.has_field("element_idx") else None
    for field_name in source_dataset.get_field_names():
        if fields and field_name not in fields:
            logger.debug(f"Field '{field_name}' not in specified fields to pass; skipping.")
        elif field_name in exclude_fields:
            logger.debug(f"Field '{field_name}' in exclude fields; skipping.")
        elif target_dataset.has_field(field_name):
            logger.warning(f"Field '{field_name}' already exists in target dataset; skipping pass.")
        else:
            source_field = source_dataset.get_field(field_name)
            if source_field.association == simdata.AssociationType.NODE:
                if node_idx is None:
                    target_dataset.add_field(field_name, source_field)
                else:
                    # Extract node indices from the source field and use them to index the target field.
                    wp_array = _extract_elements(source_field, node_idx)
                    new_field = simdata.Field.from_array(wp_array, node_idx.association)
                    target_dataset.add_field(field_name, new_field)
            elif source_field.association == simdata.AssociationType.ELEMENT:
                if element_idx is None:
                    target_dataset.add_field(field_name, source_field)
                else:
                    # Extract element indices from the source field and use them to index the target field.
                    wp_array = _extract_elements(source_field, element_idx)
                    new_field = simdata.Field.from_array(wp_array, element_idx.association)
                    target_dataset.add_field(field_name, new_field)
            else:
                raise ValueError(f"Unsupported field association type {source_field.association}")
    return target_dataset


@wp.kernel(enable_backward=False, module="unique")
def _lerp_kernel(in1: wp.array(dtype=Any), in2: wp.array(dtype=Any), out: wp.array(dtype=Any), factor: float):
    tid = wp.tid()
    out[tid] = wp.lerp(in1[tid], in2[tid], factor)


@simdata.cached
def _get_lerp_field_kernel(
    field1_model: simdata.FieldModel, field2_model: simdata.FieldModel, result_model: simdata.FieldModel, dtype
):

    ScalarType = simdata.utils.get_scalar_dtype(dtype)
    if simdata.utils.is_integral_dtype(dtype):
        raise NotImplementedError("Interpolation of integral dtypes is not supported yet.")

    @wp.kernel(enable_backward=False, module="unique")
    def lerp_field_kernel(
        in1: field1_model.FieldHandle, in2: field2_model.FieldHandle, out: result_model.FieldHandle, factor: float
    ):
        tid = wp.tid()
        val1 = field1_model.FieldAPI.get(in1, tid)
        val2 = field2_model.FieldAPI.get(in2, tid)
        result = wp.lerp(val1, val2, ScalarType(factor))
        result_model.FieldAPI.set(out, tid, result)

    return lerp_field_kernel


def lerp_dataset(
    dataset1: simdata.Dataset,
    dataset2: simdata.Dataset,
    t: float,
    *,
    fields: set[str] | None = None,
    exclude_fields: set[str] | None = None,
) -> simdata.Dataset:
    """
    Linearly interpolate between two datasets.

    This function performs linear interpolation (lerp) between two datasets with matching
    topology, interpolating both geometry (points) and field data. Supports both surface
    mesh and point cloud data models.

    Parameters
    ----------
    dataset1 : simdata.Dataset
        The first dataset (at t=0.0) with either surface_mesh or point_cloud data model
    dataset2 : simdata.Dataset
        The second dataset (at t=1.0) with the same data model as dataset1
    t : float
        Interpolation parameter, typically between 0.0 (returns dataset1) and 1.0 (returns dataset2)
    fields : set[str], optional
        A set of field names to interpolate. If empty, all common fields are interpolated, by default set()
    exclude_fields : set[str], optional
        A set of field names to exclude from interpolation, by default set()

    Returns
    -------
    simdata.Dataset
        A new dataset with interpolated geometry and fields

    Raises
    ------
    ValueError
        If datasets don't have matching topology, data models, or devices

    Notes
    -----
    For surface meshes, topology (face connectivity) is preserved from dataset1.
    For point clouds, only point positions and fields are interpolated.
    """
    from warp_simdata.data_models.custom import point_cloud as simdata_point_cloud
    from warp_simdata.data_models.custom import surface_mesh as simdata_surface_mesh

    fields = fields or set()
    exclude_fields = exclude_fields or set()

    # Verify data models match
    if dataset1.data_model != dataset2.data_model:
        raise ValueError(
            f"Data model mismatch: dataset1 is '{dataset1.data_model}', dataset2 is '{dataset2.data_model}'"
        )

    # Verify supported data models
    if dataset1.data_model not in [simdata_surface_mesh.DataModel, simdata_point_cloud.DataModel]:
        raise ValueError(
            f"Unsupported data model '{dataset1.data_model}'. " f"Only 'surface_mesh' and 'point_cloud' are supported."
        )

    if dataset1.get_num_nodes() != dataset2.get_num_nodes():
        raise ValueError(
            f"Point count mismatch: dataset1 has {dataset1.get_num_nodes()} points, "
            f"dataset2 has {dataset2.get_num_nodes()} points"
        )

    # For surface meshes, verify cell count matches
    if dataset1.data_model == simdata_surface_mesh.DataModel:
        if dataset1.get_num_elems() != dataset2.get_num_elems():
            raise ValueError(
                f"Cell count mismatch: dataset1 has {dataset1.get_num_elems()} cells, "
                f"dataset2 has {dataset2.get_num_elems()} cells"
            )

    if dataset1.device != dataset2.device:
        raise ValueError(
            f"Dataset devices mismatch: dataset1 is on {dataset1.device}, " f"dataset2 is on {dataset2.device}"
        )

    if t <= 0.0:
        return dataset1
    elif t >= 1.0:
        return dataset2

    # Interpolate points
    points1 = dataset1.handle.points
    points2 = dataset2.handle.points
    result_points = wp.zeros_like(points1, device=points1.device)
    wp.launch(
        _lerp_kernel,
        dim=points1.shape[0],
        inputs=[points1, points2, result_points, t],
        device=points1.device,
    )

    # Create result dataset based on data model
    if dataset1.data_model == simdata_surface_mesh.DataModel:
        result_dataset = simdata_surface_mesh.create_dataset(
            result_points,
            face_vertex_indices=dataset1.handle.face_vertex_indices,
            face_vertex_offsets=dataset1.handle.face_offsets,
        )
    else:  # point_cloud
        result_dataset = simdata_point_cloud.create_dataset(result_points)

    # Get common fields to interpolate
    fields1 = set(dataset1.get_field_names())
    fields2 = set(dataset2.get_field_names())
    common_fields = fields1.intersection(fields2)

    # Filter fields based on input parameters
    if fields:
        fields_to_lerp = common_fields.intersection(fields)
    else:
        fields_to_lerp = common_fields

    fields_to_lerp = fields_to_lerp - exclude_fields

    # Interpolate fields
    for field_name in fields_to_lerp:
        field1 = dataset1.get_field(field_name)
        field2 = dataset2.get_field(field_name)

        # Verify field associations match
        if field1.association != field2.association:
            logger.warning(f"Field '{field_name}' has different associations; skipping interpolation.")
            continue

        # Verify field sizes match
        if field1.size != field2.size:
            logger.warning(f"Field '{field_name}' has different sizes; skipping interpolation.")
            continue

        if field1.dtype != field2.dtype:
            logger.warning(f"Field '{field_name}' has different dtypes; skipping interpolation.")
            continue

        result_field = simdata.Field.from_array(
            wp.zeros(field1.size, dtype=field1.dtype, device=dataset1.device), field1.association
        )
        # Get field data
        lerp_field_kernel = _get_lerp_field_kernel(
            field1.field_model, field2.field_model, result_field.field_model, field1.dtype
        )
        wp.launch(
            lerp_field_kernel,
            dim=field1.size,
            inputs=[field1.handle, field2.handle, result_field.handle, t],
            device=dataset1.device,
        )

        result_dataset.add_field(field_name, result_field)

    return result_dataset
