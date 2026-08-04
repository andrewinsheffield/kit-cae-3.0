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
from typing import Any, List, NamedTuple

import warp_simdata as simdata
import warp_simdata.usd as simdata_usd
from omni.cae.core import cache, commands, usd_utils
from omni.kit.commands import Command
from pxr import Usd
from warp_simdata.usd import utils as simusd_utils


class ConvertToSimDataSet(Command):
    """
    Command to convert a USD Prim representing a CAE DataSet into a simdata.DataSet.
    When introducing any new data model, one must provide a way to register the
    data model with SimData so that it can be processed by the operators provided by SimData.
    """

    def __init__(
        self,
        dataset: Usd.Prim,
        device: str,
        timeCode: Usd.TimeCode,
        needs_topology: bool,
        needs_geometry: bool,
        representation: Any = None,
    ) -> None:
        self._dataset = dataset
        self._device = device
        self._timeCode = timeCode
        self._needs_topology = needs_topology
        self._needs_geometry = needs_geometry
        self._representation = representation

    @property
    def dataset(self) -> Usd.Prim:
        """The CAE dataset prim to convert."""
        return self._dataset

    @property
    def device(self) -> str:
        """Device to use for SimData processing (e.g., 'cpu', 'cuda', 'gpu')."""
        return self._device

    @property
    def timeCode(self) -> Usd.TimeCode:
        """Time code for data retrieval."""
        return self._timeCode

    @property
    def needs_topology(self) -> bool:
        """Whether the dataset needs topology information."""
        return self._needs_topology

    @property
    def needs_geometry(self) -> bool:
        """Whether the dataset needs geometry information."""
        return self._needs_geometry

    @property
    def representation(self) -> Any:
        """Adapter-specific representation requested for the dataset."""
        return self._representation

    @classmethod
    async def invoke(
        cls,
        dataset: Usd.Prim,
        device: str,
        timeCode: Usd.TimeCode,
        needs_topology: bool,
        needs_geometry: bool,
        representation: Any = None,
    ) -> simdata.Dataset:
        """
        Convert a CAE dataset to a SimData DataSet.

        Args:
            dataset: The prim to convert
            device: Device to use for SimData processing (e.g., 'cpu', 'cuda', 'gpu')
            timeCode: Time code for data retrieval
            needs_topology: Whether the dataset needs topology information
            needs_geometry: Whether the dataset needs geometry information
            representation: Optional adapter-specific dataset representation
        Returns:
            A simdata.DataSet object
        """
        cache_key = (
            f"[simdata:ConvertToSimDataSet]::{dataset.GetPath()}::{device}::"
            f"{needs_topology}::{needs_geometry}::{representation!r}"
        )
        if simdata_dataset := cache.get(cache_key, timeCode=timeCode):
            return simdata_dataset

        simdata_dataset = await commands.execute(
            cls.__name__,
            dataset,
            dataset=dataset,
            device=device,
            timeCode=timeCode,
            needs_topology=needs_topology,
            needs_geometry=needs_geometry,
            representation=representation,
        )
        if simdata_dataset:
            cache.put_ex(
                cache_key,
                simdata_dataset,
                prims=[cache.PrimWatch(dataset)],
                timeCode=timeCode,
            )
        # shallow copy the cached dataset to prevent accidental modifications to the cached version.
        return simdata_dataset.shallow_copy() if simdata_dataset else None

    async def do(self) -> simdata.Dataset:
        """
        Execute the command to convert a CAE dataset to a SimData DataSet.

        This is a base implementation that should be overridden by subclasses
        for specific dataset types.

        Returns:
            A simdata.DataSet object
        """
        raise NotImplementedError(
            f"Conversion to SimData DataSet not implemented for dataset type: {self.dataset.GetTypeName()}. "
            f"Please implement a subclass of ConvertToSimDataSet for this dataset type."
        )


class FieldInfo(NamedTuple):
    """Name, label, and association for an available field on a dataset prim."""

    name: str
    label: str
    association: simdata.AssociationType


def _analyze_array_expression_prim(prim: Usd.Prim):
    from . import array_expressions

    native_fields = array_expressions.local_native_fields(prim)
    return native_fields, array_expressions.describe_array_expressions(prim, native_fields)


async def get_array_expression_descriptions(prim: Usd.Prim):
    """Return static validation and dependency information for authored expressions."""
    return _analyze_array_expression_prim(prim)[1]


def get_prim_fields(prim: Usd.Prim) -> List[FieldInfo]:
    """Return native and valid derived fields owned directly by *prim*."""
    from . import array_expressions

    native_fields, descriptions = _analyze_array_expression_prim(prim)
    array_expressions.sync_array_expression_companions(prim, descriptions)
    fields = [FieldInfo(item.name, item.label, item.association) for item in native_fields]
    existing_names = {field.name for field in fields}
    for description in descriptions:
        if description.valid and description.name not in existing_names:
            fields.append(
                FieldInfo(
                    description.name,
                    description.display_name,
                    description.association,
                )
            )
    return fields


async def get_prim_field(
    prim: Usd.Prim,
    field_name_or_names: str | list[str],
    device: str,
    timeCode: Usd.TimeCode,
) -> simdata.Field:
    """Load fields directly from their prim-local raw scientific arrays."""
    from . import array_expressions

    names = field_name_or_names if isinstance(field_name_or_names, list) else [field_name_or_names]
    native_fields, descriptions = _analyze_array_expression_prim(prim)
    array_expressions.sync_array_expression_companions(prim, descriptions)
    resolver = array_expressions.create_array_value_resolver(
        prim,
        native_names={field.name for field in native_fields},
        time_code=timeCode,
    )
    try:
        with simdata_usd.scoped_sci_array_value_resolver(resolver):
            return await asyncio.to_thread(
                simusd_utils.get_sci_field,
                prim,
                names,
                device=device,
                time_code=timeCode,
            )
    except (ValueError, array_expressions.ArrayExpressionError) as exc:
        raise usd_utils.QuietableException(f"Failed to load scientific field on {prim.GetPath()}: {exc}") from exc


class GetAvailableFields(Command):
    """
    Command to retrieve the available fields on a USD dataset prim.

    Returns a list of FieldInfo(name, label, association) named tuples describing
    each field found on the prim.  When introducing a new data model, register
    a subclass named <SchemaTypeName>GetAvailableFields via omni.kit.commands.
    """

    def __init__(self, dataset: Usd.Prim) -> None:
        self._dataset = dataset

    @property
    def dataset(self) -> Usd.Prim:
        return self._dataset

    @classmethod
    async def _invoke_native(cls, dataset: Usd.Prim) -> List[FieldInfo]:
        return await commands.execute(cls.__name__, dataset, dataset=dataset)

    @classmethod
    async def invoke(cls, dataset: Usd.Prim) -> List[FieldInfo]:
        """
        Return the available fields for *dataset*.
        Returns an empty list when no implementation is found.
        """
        from . import array_expressions

        array_expression_prims = array_expressions.array_expression_prims(dataset)
        analyses = []
        for prim in array_expression_prims:
            _, descriptions = _analyze_array_expression_prim(prim)
            array_expressions.sync_array_expression_companions(prim, descriptions)
            analyses.append((prim, descriptions))

        native_fields = await cls._invoke_native(dataset)
        expression_names = {
            description.name for _, descriptions in analyses for description in descriptions if description.valid
        }
        native_fields = [field for field in native_fields if field.name not in expression_names]
        fields = list(native_fields)
        existing_names = {field.name for field in fields}
        for _, descriptions in analyses:
            for description in descriptions:
                if not description.valid:
                    continue
                if description.name not in existing_names:
                    fields.append(
                        FieldInfo(
                            description.name,
                            description.display_name,
                            description.association,
                        )
                    )
                    existing_names.add(description.name)
        return fields

    def do(self) -> List[FieldInfo]:
        raise NotImplementedError(
            f"GetAvailableFields not implemented for dataset type: {self.dataset.GetTypeName()}. "
            f"Please implement a subclass of GetAvailableFields for this dataset type."
        )


class GetField(Command):
    """
    Command to retrieve a named field from a USD dataset prim as a SimData field.

    When introducing a new dataset schema that needs custom field loading behavior,
    register a subclass named <SchemaTypeName>GetField via omni.kit.commands.
    """

    def __init__(
        self,
        dataset: Usd.Prim,
        field_names: list[str],
        device: str,
        timeCode: Usd.TimeCode,
        representation: Any = None,
    ) -> None:
        self._dataset = dataset
        self._field_names = field_names
        self._device = device
        self._timeCode = timeCode
        self._representation = representation

    @property
    def dataset(self) -> Usd.Prim:
        """The dataset prim to load the field from."""
        return self._dataset

    @property
    def field_names(self) -> list[str]:
        """One or more dataset field names to combine into a SimData field."""
        return self._field_names

    @property
    def device(self) -> str:
        """Device to use for SimData field data."""
        return self._device

    @property
    def timeCode(self) -> Usd.TimeCode:
        """Time code for field data retrieval."""
        return self._timeCode

    @property
    def representation(self) -> Any:
        """Adapter-specific representation requested for the field."""
        return self._representation

    @classmethod
    async def _invoke_native(
        cls,
        dataset: Usd.Prim,
        field_name_or_names: str | list[str],
        device: str,
        timeCode: Usd.TimeCode,
        representation: Any = None,
    ) -> simdata.Field:
        return await commands.execute(
            cls.__name__,
            dataset,
            dataset=dataset,
            field_names=field_name_or_names if isinstance(field_name_or_names, list) else [field_name_or_names],
            device=device,
            timeCode=timeCode,
            representation=representation,
        )

    @classmethod
    async def invoke(
        cls,
        dataset: Usd.Prim,
        field_name_or_names: str | list[str],
        device: str,
        timeCode: Usd.TimeCode,
        representation: Any = None,
    ) -> simdata.Field:
        """
        Return the SimData field for one or more field names on *dataset*.

        ``representation`` must match the representation used to load the
        corresponding dataset so adapter-specific field layouts stay aligned.
        """
        from . import array_expressions

        names = field_name_or_names if isinstance(field_name_or_names, list) else [field_name_or_names]
        array_expression_prims = array_expressions.array_expression_prims(dataset, set(names))
        owners = {}
        for prim in array_expression_prims:
            _, descriptions = _analyze_array_expression_prim(prim)
            array_expressions.sync_array_expression_companions(prim, descriptions)
            for name in names:
                if array_expressions.has_array_expression(prim, name):
                    if name in owners and owners[name] != prim:
                        raise ValueError(f"Array expression '{name}' is ambiguous near {dataset.GetPath()}")
                    owners[name] = prim
        derived_names = [name for name in names if name in owners]
        if not derived_names:
            return await cls._invoke_native(dataset, names, device, timeCode, representation)

        try:
            resolvers = {}
            for owner in set(owners.values()):
                local_native_fields, descriptions = _analyze_array_expression_prim(owner)
                owner_names = [name for name in derived_names if owners[name] == owner]
                array_expressions.sync_array_expression_companions(owner, descriptions, owner_names)
                resolvers[str(owner.GetPath())] = array_expressions.create_array_value_resolver(
                    owner,
                    native_names={field.name for field in local_native_fields},
                    time_code=timeCode,
                )

            def resolver(request):
                owner_resolver = resolvers.get(str(request.prim.GetPath()))
                return owner_resolver(request) if owner_resolver else None

            with simdata_usd.scoped_sci_array_value_resolver(resolver):
                return await cls._invoke_native(dataset, names, device, timeCode, representation)
        except (ValueError, array_expressions.ArrayExpressionError) as exc:
            raise usd_utils.QuietableException(
                f"Failed to evaluate array expression '{derived_names[0]}' on {dataset.GetPath()}: {exc}"
            ) from exc

    async def do(self) -> simdata.Field:
        """
        Execute the command to retrieve a field from a dataset prim.
        """
        raise NotImplementedError(
            f"GetField not implemented for dataset type: {self.dataset.GetTypeName()}. "
            f"Please implement a subclass of GetField for this dataset type."
        )
