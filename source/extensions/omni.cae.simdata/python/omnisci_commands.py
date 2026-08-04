# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SimData command implementations for prims typed as :class:`OmniSciDataset`.

This module registers subclasses of the generic
:class:`.command_types.ConvertToSimDataSet`, :class:`.command_types.GetAvailableFields`,
and :class:`.command_types.GetField` commands for the ``OmniSciDataset`` schema
family. Each subclass is a thin shim that delegates to the :mod:`simdata.usd`
adapter registry, which knows how to read grid, topology, and field data from
the prim's applied USD schemas (CGNS, CAE, etc.).

Using a single set of schema-agnostic commands here lets the ``omni.cae.simdata``
extension support every prim-type ``simdata.usd`` can adapt to without growing a
per-schema command module for each one.

Exceptions raised by the adapter layer are normalized into
:class:`omni.cae.core.usd_utils.QuietableException` so that upstream command
consumers can render user-friendly errors with the offending prim path
attached.
"""

import asyncio
from logging import getLogger

import warp_simdata as simdata
import warp_simdata.usd
from omni.cae.core import usd_utils

from .command_types import ConvertToSimDataSet, FieldInfo, GetAvailableFields, GetField

logger = getLogger(__name__)


def _wrap_as_quietable_error(dataset, exc: Exception):
    message = f"{exc}"
    if dataset and dataset.IsValid():
        message = f"{message} [dataset={dataset.GetPath()}]"
    raise usd_utils.QuietableException(message) from exc


class OmniSciDatasetConvertToSimDataSet(ConvertToSimDataSet):
    """Convert an OmniSciDataset prim into SimData via :mod:`simdata.usd`."""

    async def do(self):
        logger.info("executing %s.do()", self.__class__.__name__)
        try:
            adapter_kwargs = {"representation": self.representation} if self.representation is not None else {}
            return await asyncio.to_thread(
                simdata.usd.dataset_from_prim,
                self.dataset,
                device=self.device,
                time_code=self.timeCode,
                **adapter_kwargs,
            )
        except Exception as exc:
            _wrap_as_quietable_error(self.dataset, exc)


class OmniSciDatasetGetAvailableFields(GetAvailableFields):
    """Return available fields for an OmniSciDataset prim via :mod:`simdata.usd`."""

    async def do(self):
        logger.info("executing %s.do()", self.__class__.__name__)
        try:
            field_infos = simdata.usd.list_fields(self.dataset)
        except simdata.usd.UnsupportedPrimError:
            return []
        except Exception as exc:
            _wrap_as_quietable_error(self.dataset, exc)

        return [
            FieldInfo(name=field_info.name, label=field_info.label, association=field_info.association)
            for field_info in field_infos
        ]


class OmniSciDatasetGetField(GetField):
    """Load a field from an OmniSciDataset prim via :mod:`simdata.usd`."""

    async def do(self):
        logger.info("executing %s.do()", self.__class__.__name__)
        try:
            field_names = self.field_names[0] if len(self.field_names) == 1 else self.field_names
            adapter_kwargs = {"representation": self.representation} if self.representation is not None else {}
            return await asyncio.to_thread(
                simdata.usd.field_from_prim,
                self.dataset,
                field_names,
                device=self.device,
                time_code=self.timeCode,
                **adapter_kwargs,
            )
        except Exception as exc:
            _wrap_as_quietable_error(self.dataset, exc)
