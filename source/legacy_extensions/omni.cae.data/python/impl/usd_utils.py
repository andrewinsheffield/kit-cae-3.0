# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Legacy Data Delegate USD helpers.

The generic USD traversal helpers live in :mod:`omni.cae.core.usd_utils`.
This module keeps only the pieces that need the deprecated Data Delegate
registry to fetch ``CaeFieldArray`` data from legacy stages.
"""

import asyncio
from logging import getLogger

from omni.cae.core import array_utils, progress
from omni.cae.core import usd_utils as _core_usd_utils
from omni.cae.core.usd_utils import *  # noqa: F403
from omni.cae.schema import cae
from pxr import Usd

from .. import get_data_delegate_registry
from .bindings import IFieldArray

logger = getLogger(__name__)

__all__ = [
    *_core_usd_utils.__all__,
    "get_array",
    "get_arrays",
    "get_array_from_relationship",
    "get_vecN_from_relationship",
]


@async_quietable  # noqa: F405
async def get_array(prim: Usd.Prim, timeCode: Usd.TimeCode = Usd.TimeCode.Default()) -> IFieldArray:
    """Fetch a legacy ``CaeFieldArray`` through the Data Delegate registry."""
    if not prim:
        raise QuietableException("Invalid prim %s" % prim)  # noqa: F405

    if not prim.IsA(cae.FieldArray):
        raise QuietableException("FieldArray prim expected at %s" % prim)  # noqa: F405

    registry = get_data_delegate_registry()
    label = f".../{prim.GetParent().GetName()}/{prim.GetName()}"
    with progress.ProgressContext(f"Fetching array for {label}"):
        array: IFieldArray = await registry.get_field_array_async(prim, timeCode)

    if array is None:
        raise QuietableException("Failed to fetch array for %s" % prim)  # noqa: F405
    logger.info("Got array %s (device_ordinal=%d)", prim, array.device_id)
    return array


@progress.progress_context("Fetching arrays")
async def get_arrays(prims: list[Usd.Prim], timeCode: Usd.TimeCode = Usd.TimeCode.Default()) -> list[IFieldArray]:
    """Fetch multiple legacy ``CaeFieldArray`` prims through the registry."""
    arrays = []
    for idx, prim in enumerate(prims):
        with progress.ProgressContext(
            f"Fetching array {idx} of {len(prims)}", shift=idx / len(prims), scale=1.0 / len(prims)
        ):
            arrays.append(await get_array(prim, timeCode))
    return arrays


@async_quietable  # noqa: F405
@progress.progress_context("Fetching arrays from relationship")
async def _get_arrays_from_relationship(
    prim: Usd.Prim, relName: str, timeCode=Usd.TimeCode.Default()
) -> list[IFieldArray]:
    targets = get_target_prims(prim, relName)  # noqa: F405
    return await get_arrays(targets, timeCode)


@async_quietable  # noqa: F405
async def get_array_from_relationship(prim: Usd.Prim, relName: str, timeCode=Usd.TimeCode.Default()) -> IFieldArray:
    target = get_target_prim(prim, relName)  # noqa: F405
    return await get_array(target, timeCode)


@async_quietable  # noqa: F405
async def get_vecN_from_relationship(
    prim: Usd.Prim, relName: str, numComponents: int, timeCode=Usd.TimeCode.Default()
) -> IFieldArray:
    arrays = await _get_arrays_from_relationship(prim, relName, timeCode)
    return await _assemble_vecN_arrays(arrays, numComponents)


async def _assemble_vecN_arrays(arrays: list[IFieldArray], numComponents: int) -> IFieldArray:
    if len(arrays) == 1 and arrays[0].ndim == 2 and arrays[0].shape[1] == numComponents:
        return arrays[0]
    if len(arrays) == 1 and arrays[0].ndim == 1 and numComponents == 1:
        return arrays[0]
    if len(arrays) == numComponents:
        array = await asyncio.to_thread(array_utils.column_stack, arrays)
        if array.ndim == 2 and array.shape[1] == numComponents:
            return array
        raise QuietableException(  # noqa: F405
            f"Failed to assemble vecN array: expected shape (_, {numComponents}), got {array.shape}"
        )
    raise QuietableException(f"Failed to fetch {numComponents} components")  # noqa: F405
