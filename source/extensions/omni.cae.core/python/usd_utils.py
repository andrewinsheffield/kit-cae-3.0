# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
  Module with utilities for making it easier to work with CAE USD prims.
  By design all methods raise exceptions instead of returning empty values or raising errors.
"""

__all__ = [
    "QuietableException",
    "quietable",
    "quietable_with_default",
    "async_quietable",
    "async_quietable_with_default",
    "get_target_prim",
    "get_target_prims",
    "get_attribute",
    "get_prim_pxr",
    "get_prim_rt",
    "get_instances",
    "get_field_name",
    "get_prim_at_path",
    "get_stage_id",
    "get_bounds",
    "get_bracketing_time_samples_for_prim",
    "get_bracketing_time_samples_for_data_set_prim",
    "get_related_data_prims",
    "snap_time_code_to_prim",
    "snap_time_code_to_prims",
    "ChangeTracker",
]

import bisect
import functools
import sys
import weakref
from logging import getLogger
from typing import Union

from omni.cae.schema import cae
from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdUtils
from usdrt import Rt
from usdrt import Usd as UsdRt

logger = getLogger(__name__)


class QuietableException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def quietable(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        quiet = kwargs.pop("quiet", False)
        try:
            return func(*args, **kwargs)
        except QuietableException as e:
            if not quiet:
                raise
            logger.debug("Silenced exception %s", e)
        return None

    return wrapper


def quietable_with_default(val):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            quiet = kwargs.pop("quiet", False)
            try:
                return func(*args, **kwargs)
            except QuietableException as e:
                if not quiet:
                    raise
                logger.debug("Silenced exception %s", e)
            return val

        return wrapper

    return decorator


def async_quietable(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        quiet = kwargs.pop("quiet", False)
        try:
            return await func(*args, **kwargs)
        except QuietableException as e:
            if not quiet:
                raise
            logger.debug("Silenced exception %s", e)
        return None

    return wrapper


def async_quietable_with_default(val):
    async def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            quiet = kwargs.pop("quiet", False)
            try:
                return await func(*args, **kwargs)
            except QuietableException as e:
                if not quiet:
                    raise
                logger.debug("Silenced exception %s", e)
            return val

        return wrapper

    return decorator


@quietable
def _get_target_paths(prim: Usd.Prim, relName: str) -> list[Sdf.Path]:
    if not prim:
        raise QuietableException("Invalid prim: %s" % prim)
    rel = prim.GetRelationship(relName)
    if not rel:
        raise QuietableException("Missing relationship '%s' on '%s'" % (relName, prim))
    targets = rel.GetForwardedTargets()
    if not targets:
        raise QuietableException("Missing targets on '%s" % rel)
    return targets


def get_stage_id(stage: Usd.Stage) -> int:
    """
    Get the stage ID for a USD stage.

    Args:
        stage: The USD stage

    Returns:
        The stage ID as a long int

    Raises:
        QuietableException: If the stage is invalid
    """
    if not stage:
        raise QuietableException("Invalid stage")
    cache = UsdUtils.StageCache.Get()
    return cache.GetId(stage).ToLongInt()


@quietable
def _get_target_path(prim: Usd.Prim, relName: str) -> Sdf.Path:
    targets = _get_target_paths(prim, relName)
    if len(targets) > 1:
        logger.warning("Only first target is being processed on %s.%s", prim, relName)
    return targets[0]


@quietable
def get_target_prim(prim: Usd.Prim, relName: str) -> Usd.Prim:
    path = _get_target_path(prim, relName)
    if tprim := prim.GetStage().GetPrimAtPath(path):
        return tprim
    raise QuietableException(f"Missing target prim at path {path}")


@quietable_with_default([])
def get_target_prims(prim: Usd.Prim, relName: str) -> list[Usd.Prim]:
    paths = _get_target_paths(prim, relName)
    stage = prim.GetStage()
    prims = []
    for p in paths:
        if tprim := stage.GetPrimAtPath(p):
            prims.append(tprim)
        else:
            raise QuietableException(f"Missing target prim at path {p}")
    if not prims:
        raise QuietableException(f"Missing valid targets prim at path {prim}->{relName}")
    return prims


@quietable
def get_attribute(prim: Usd.Prim, attrName: str, timeCode=Usd.TimeCode.Default()) -> any:
    if not prim.HasAttribute(attrName):
        raise QuietableException(f"Missing attribute {prim}.{attrName}")
    attr = prim.GetAttribute(attrName)
    if not attr.HasAuthoredValue() and not attr.HasFallbackValue():
        raise QuietableException(f"Missing authored/default value for attribute {prim}.{attrName}")
    return attr.Get(timeCode.GetValue())


@quietable
def get_prim_pxr(prim: Union[Usd.Prim, UsdRt.Prim]) -> Usd.Prim:
    if prim and isinstance(prim, UsdRt.Prim):
        stage_id = prim.GetStage().GetStageId()
        cache = UsdUtils.StageCache.Get()
        stage: Usd.Stage = cache.Find(cache.Id.FromLongInt(stage_id))
        if not stage:
            raise QuietableException(f"Failed to locate PXR::UsdStage with id {stage_id}")
        return stage.GetPrimAtPath(str(prim.GetPath()))
    elif prim and isinstance(prim, Usd.Prim):
        return prim
    else:
        raise QuietableException(f"Invalid prim {prim}")


@quietable
def get_field_name(dataset_prim: Usd.Prim, field_prim: Usd.Prim) -> str:
    """Returns field relationship name (without the `field:` prefix)"""
    field_prim_path = field_prim.GetPath()

    for rel in dataset_prim.GetRelationships():
        if rel.GetNamespace().startswith("field") and field_prim_path in rel.GetTargets():
            return str(rel.GetName())[len("field:") :]
    raise QuietableException("%s is not a 'field:' on %s" % (field_prim, dataset_prim))


@quietable
def get_prim_at_path(stage: Usd.Stage, path: str):
    prim = stage.GetPrimAtPath(path)
    if not prim:
        raise QuietableException(f"Prim not found at path {path}")
    return prim


@quietable_with_default(Gf.Range3d())
def get_bounds(prim: Usd.Prim, timeCode=Usd.TimeCode.Default()) -> Gf.Range3d:

    if not prim or not prim.IsA(UsdGeom.Boundable):
        raise QuietableException("Prim is not boundable")

    bounds_cache = UsdGeom.BBoxCache(timeCode, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    bounds_cache.SetTime(timeCode)
    bounds: Gf.BBox3d = bounds_cache.ComputeLocalBound(prim)
    return bounds.ComputeAlignedRange()


def _has_prefix(value: str, prefix: str) -> bool:
    return value.startswith(prefix)


def _is_data_dependency_prim(prim: Usd.Prim) -> bool:
    if not prim or not prim.IsValid():
        return False

    if prim.IsA(cae.DataSet) or prim.IsA(cae.FieldArray):
        return True

    type_name = prim.GetTypeName()
    if _has_prefix(type_name, "OmniSci") or _has_prefix(type_name, "OmniCgns"):
        return True

    for schema_name in prim.GetAppliedSchemas():
        schema = str(schema_name)
        if _has_prefix(schema, "OmniSci") or _has_prefix(schema, "OmniCgns"):
            return True

    return False


def _get_native_module():
    from . import _omni_cae_core

    return _omni_cae_core


def get_bracketing_time_samples_for_prim(prim: Usd.Prim, time: float) -> tuple[float, float, bool]:
    """
    Get bracketing time samples for a given prim.

    This recursively traverses prims and relationships to find time samples on
    related scientific data prims, including legacy CAE data prims and
    OmniSci-backed file-format prims.

    Args:
        prim: The UsdPrim to query
        time: The time value to query

    Returns:
        tuple: (lower, upper, has_time_samples) - The lower and upper bracketing time samples,
               and a boolean indicating if time samples exist. When no time samples exist,
               returns EarliestTime for both lower and upper.
    """
    earliest_time = Usd.TimeCode.EarliestTime().GetValue()

    if not prim or not prim.IsValid():
        return (earliest_time, earliest_time, False)

    return _get_native_module().get_bracketing_time_samples_for_prim(
        get_stage_id(prim.GetStage()), str(prim.GetPath()), time
    )


def get_bracketing_time_samples_for_data_set_prim(
    prim: Usd.Prim, time: float, traverse_field_relationships: bool = True
) -> tuple[float, float, bool]:
    """
    Get bracketing time samples for a DataSet prim with optional control over field relationship traversal.

    This recursively traverses prims and relationships to find time samples on
    related scientific data prims, with the option to include or exclude
    field:* relationships.

    Args:
        prim: The DataSet UsdPrim to query (should be an OmniCaeDataSet prim)
        time: The time value to query
        traverse_field_relationships: If True, traverse field:* relationships; if False, skip them.
                                      Defaults to True to match get_bracketing_time_samples_for_prim behavior.

    Returns:
        tuple: (lower, upper, has_time_samples) - The lower and upper bracketing time samples,
               and a boolean indicating if time samples exist. When no time samples exist,
               returns EarliestTime for both lower and upper.
    """
    earliest_time = Usd.TimeCode.EarliestTime().GetValue()

    if not prim or not prim.IsValid():
        return (earliest_time, earliest_time, False)

    return _get_native_module().get_bracketing_time_samples_for_data_set_prim(
        get_stage_id(prim.GetStage()), str(prim.GetPath()), time, traverse_field_relationships
    )


def _collect_related_data_prims(
    prim: Usd.Prim,
    transitive: bool,
    processed_prims: set[Sdf.Path],
    result: list[Usd.Prim],
    rel_names: list[str],
) -> None:
    if not prim or not prim.IsValid():
        return

    prim_path = prim.GetPath()
    if prim_path in processed_prims:
        return
    processed_prims.add(prim_path)

    stage = prim.GetStage()
    if not stage:
        return

    rel_name_set = set(rel_names)
    for rel in prim.GetAuthoredRelationships():
        if rel_name_set and str(rel.GetName()) not in rel_name_set:
            continue

        for target_path in rel.GetForwardedTargets():
            target_prim = stage.GetPrimAtPath(target_path)
            if not _is_data_dependency_prim(target_prim):
                continue

            result.append(target_prim)
            if transitive:
                _collect_related_data_prims(target_prim, transitive, processed_prims, result, [])


def get_related_data_prims(
    prim: Usd.Prim,
    transitive: bool = True,
    include_self: bool = True,
    rel_names: list[str] | None = None,
) -> list[Usd.Prim]:
    """
    Get all related DataSet and FieldArray prims for a given prim.

    This function traverses relationships from the input prim and collects all related prims
    that are either CaeDataSet or CaeFieldArray types. This is useful for cache invalidation
    tracking where changes to related data prims should invalidate cached results.

    Args:
        prim: The starting prim (typically a DataSet or FieldArray)
        transitive: If True, recursively traverse relationship targets; if False, only return
                   immediate relationship targets
        include_self: If True, include the input prim in the result set; if False, only return
                     related prims
        rel_names: If non-empty, only relationships whose name is in this list are followed on
                   the first traversal hop. Subsequent transitive hops follow all relationships
                   freely. Defaults to [] (follow all relationships at every hop).

    Returns:
        List of related DataSet and FieldArray prims

    Example:
        >>> dataset = cae.DataSet.Define(stage, "/Root/DataSet")
        >>> field1 = cae.FieldArray.Define(stage, "/Root/DataSet/Field1")
        >>> field2 = cae.FieldArray.Define(stage, "/Root/DataSet/Field2")
        >>> dataset.GetPrim().CreateRelationship("field:Field1").AddTarget(field1.GetPrim().GetPath())
        >>> dataset.GetPrim().CreateRelationship("field:Field2").AddTarget(field2.GetPrim().GetPath())
        >>> # Get all related prims (including the dataset itself)
        >>> prims = get_related_data_prims(dataset.GetPrim(), transitive=True, include_self=True)
        >>> # prims will contain: [dataset, field1, field2]
        >>> # Get only the field relationships (exclude self)
        >>> fields = get_related_data_prims(dataset.GetPrim(), transitive=False, include_self=False)
        >>> # fields will contain: [field1, field2]
        >>> # Only follow "field:Field1" on the first hop
        >>> prims = get_related_data_prims(dataset.GetPrim(), rel_names=["field:Field1"])
        >>> # prims will contain: [dataset, field1]  (field2 excluded)
    """
    if not prim or not prim.IsValid():
        return []

    result_prims = [prim] if include_self else []
    _collect_related_data_prims(prim, transitive, set(), result_prims, rel_names or [])
    return result_prims


def snap_time_code_to_prim(
    prim: Usd.Prim, time_code: Usd.TimeCode, traverse_field_relationships: bool = True
) -> Usd.TimeCode:
    """
    Snap a time code down to the closest lower time sample for a given prim.

    This function always snaps DOWN to the highest time sample that is <= the query time.
    If no time sample exists <= the query time, returns the first (lowest) available time sample.

    Args:
        prim: The DataSet UsdPrim to query (should be an OmniCaeDataSet prim)
        time_code: The time code to snap
        traverse_field_relationships: If True, traverse field:* relationships; if False, skip them.
                                      Defaults to True.

    Returns:
        Usd.TimeCode: The snapped time code (always <= query time if possible).
                      If no time samples exist, returns EarliestTime.
    """
    if not prim or not prim.IsValid():
        return Usd.TimeCode.EarliestTime()

    time_value = time_code.GetValue()
    lower, upper, has_time_samples = get_bracketing_time_samples_for_data_set_prim(
        prim, time_value, traverse_field_relationships
    )

    if not has_time_samples:
        return Usd.TimeCode.EarliestTime()

    # Always return the lower bracketing time sample (the one <= query time)
    # This ensures we always snap down
    return Usd.TimeCode(lower)


def snap_time_code_to_prims(
    prims: list[Usd.Prim], time_code: Usd.TimeCode, traverse_field_relationships: bool = True
) -> Usd.TimeCode:
    """
    Snap a time code down to the closest lower time sample across multiple prims.

    This function calls snap_time_code_to_prim for each prim to get the snapped time for each,
    then finds the closest lower time code from the set of snapped times.

    Args:
        prims: List of DataSet UsdPrims to query (should be OmniCaeDataSet prims)
        time_code: The time code to snap
        traverse_field_relationships: If True, traverse field:* relationships; if False, skip them.
                                      Defaults to True.

    Returns:
        Usd.TimeCode: The snapped time code (always <= query time if possible).
                      If no prims have time samples, returns EarliestTime.
    """
    if not prims:
        return Usd.TimeCode.EarliestTime()

    time_value = time_code.GetValue()
    snapped_times = []

    # Snap each prim individually
    for prim in prims:
        if not prim or not prim.IsValid():
            continue

        snapped_tc = snap_time_code_to_prim(prim, time_code, traverse_field_relationships)
        if snapped_tc != Usd.TimeCode.EarliestTime():
            snapped_times.append(snapped_tc.GetValue())

    if not snapped_times:
        return Usd.TimeCode.EarliestTime()

    # Build sorted list of all snapped times
    sorted_times = sorted(snapped_times)

    # Find the highest time sample that is <= time_value (snap down)
    i = bisect.bisect_right(sorted_times, time_value)

    if i == 0:
        # All snapped times are > time_value, return the first (lowest) one
        return Usd.TimeCode(sorted_times[0])

    # Get the previous element (the highest one <= time_value)
    # This is the closest lower time sample
    return Usd.TimeCode(sorted_times[i - 1])


def get_instances(prim: Usd.Prim, api_schema_name: str) -> list[str]:
    """
    Given a prim and a multiple-apply API schema name, return the list of instance names
    for the prim that match the given API schema name.

    This is only multiple-apply API schemas. For others, this will simply return an empty list.
    """
    registry = Usd.SchemaRegistry()
    instances = []
    for applied_schema in prim.GetAppliedSchemas():
        schema_name, instance_name = registry.GetTypeNameAndInstance(applied_schema)
        if instance_name and schema_name == api_schema_name:
            instances.append(instance_name)
    return instances


def get_prim_rt(prim: Usd.Prim) -> UsdRt.Prim:
    if not prim:
        return None

    stage = prim.GetStage()
    cache = UsdUtils.StageCache.Get()
    id = cache.GetId(stage)

    stage_ref = ChangeTracker._rt_stage_weakref_map.get(id)
    stage_rt = stage_ref() if stage_ref is not None else None
    if stage_rt is None:
        stage_rt = UsdRt.Stage.Attach(id.ToLongInt())
        ChangeTracker._rt_stage_weakref_map[id] = weakref.ref(stage_rt)

    rt_prim = stage_rt.GetPrimAtPath(str(prim.GetPath()))
    if not rt_prim:
        raise QuietableException(f"Failed to get UsdRt prim for {prim}")
    return rt_prim


class ChangeTracker:
    """
    Helper class that tracks changes to a USD stage. This is simply a wrapper around Rt.ChangeTracker
    that exposes limited API that accepts pxr.Usd prims instead of usdrt.Usd prims.

    This helps us keep algorithm implementations void of any UsdRt dependencies.
    """

    _rt_stage_weakref_map = {}

    def __init__(self, stage: Usd.Stage) -> None:
        cache = UsdUtils.StageCache.Get()
        id = cache.GetId(stage)

        stage_ref = ChangeTracker._rt_stage_weakref_map.get(id)
        stage = stage_ref() if stage_ref is not None else None
        if stage is None:
            stage = UsdRt.Stage.Attach(id.ToLongInt())
            ChangeTracker._rt_stage_weakref_map[id] = weakref.ref(stage)

        self._rt_stage = stage
        self._tracker = Rt.ChangeTracker(self._rt_stage)

    def PrimOrTargetsChanged(self, prim_or_path) -> None:
        self._paths = set()
        return self._PrimOrTargetsChangedInternal(prim_or_path)

    def _PrimOrTargetsChangedInternal(self, prim_or_path) -> None:
        if hasattr(prim_or_path, "GetPath"):
            path = str(prim_or_path.GetPath())
        else:
            path = str(prim_or_path)

        if path in self._paths:
            return False

        self._paths.add(path)

        # recursively check if any of relationship targets have changed
        prim = self._rt_stage.GetPrimAtPath(path)
        if not prim:
            return False

        if self._tracker.PrimChanged(prim):
            logger.info("Prim changed %s", prim)
            logger.info("  changed paths %s", self._tracker.GetChangedAttributes(prim))
            return True

        for rel in prim.GetRelationships():
            for target in rel.GetForwardedTargets():
                if self._PrimOrTargetsChangedInternal(target):
                    return True

        return False

    def PrimChanged(self, prim_or_path) -> None:
        if hasattr(prim_or_path, "GetPath"):
            path = str(prim_or_path.GetPath())
        else:
            path = str(prim_or_path)

        return self._tracker.PrimChanged(path)

    def AttributeChanged(self, attr_or_path) -> None:
        if hasattr(attr_or_path, "GetPath"):
            path = str(attr_or_path.GetPath())
        else:
            path = str(attr_or_path)

        return self._tracker.AttributeChanged(path)

    def ClearChanges(self) -> None:
        return self._tracker.ClearChanges()

    def TrackAttribute(self, attrName: str) -> None:
        return self._tracker.TrackAttribute(str(attrName))

    def TrackSchemaProperties(self, schema_name: str):
        logger.debug(f"{id(self)}: tracking schema properties for {schema_name}")
        registry = Usd.SchemaRegistry()
        defn = registry.FindAppliedAPIPrimDefinition(schema_name) or registry.FindConcretePrimDefinition(schema_name)

        if not defn:
            logger.error(f"Schema {schema_name} not found. Properties will not be tracked.")
            return

        for pname in defn.GetPropertyNames():
            logger.debug(f"{id(self)}: tracking {pname}")
            self.TrackAttribute(pname)

    def TrackCaeFieldArrayProperties(self) -> None:
        registry = Usd.SchemaRegistry()
        baseT: Tf.Type = registry.GetConcreteTypeFromSchemaTypeName("CaeFieldArray")
        assert not baseT.isUnknown

        for t in baseT.GetAllDerivedTypes():
            self.TrackSchemaProperties(registry.GetConcreteSchemaTypeName(t))
