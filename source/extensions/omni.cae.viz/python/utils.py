# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from logging import Logger, getLogger
from typing import Iterator

import numpy as np
import omni.cae.simdata as cae_simdata
import warp as wp
import warp_simdata as simdata
from omni.cae.core import array_utils, cache, progress, usd_utils
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from omni.stageupdate import get_stage_update_interface
from pxr import Gf, OmniSci, Sdf, Tf, Usd, UsdGeom, UsdShade
from usdrt import Sdf as SdfRT
from usdrt import Usd as UsdRT
from usdrt import UsdGeom as UsdGeomRT
from usdrt import Vt as VtRT
from warp_simdata.data_models.custom import element_subset as simdata_data_models_element_subset
from warp_simdata.data_models.custom import voronoi_point_cloud as simdata_data_models_voronoi_point_cloud
from warp_simdata.data_models.vtk import image_data as simdata_data_models_vtk_image_data
from warp_simdata.operators import element_field as simdata_element_field
from warp_simdata.operators import element_in_box as simdata_element_in_box
from warp_simdata.operators import node_field as simdata_node_field
from warp_simdata.operators import node_splats as simdata_node_splats
from warp_simdata.operators import voxelization as simdata_voxelization

logger = getLogger(__name__)

_VOXELIZATION_FIELD_CENTERINGS = {"cell", "point"}
_POINT_CLOUD_DATA_MODEL_APIS = {
    "CaeVizDatasetGaussianSplattingAPI": "gaussian",
    "CaeVizDatasetVoronoiPointCloudAPI": "voronoi",
}

__all__ = [
    "RtSubPrimGuard",
    "apply_field_mapping",
    "edit_context",
    "get_available_fields",
    "get_input_dataset",
    "get_selected_dataset_prims",
    "get_selected_datasets",
    "get_selected_field",
    "get_temporal_traits",
    "is_attr_locked",
    "log_runtime_warnings",
    "process_configure_xac_shader_apis",
    "process_configure_xac_shader_apis_temporal",
    "process_field_selection_apis",
    "process_rescale_range_apis",
    "process_widths",
    "set_array_attribute",
    "write_glyph_display_color",
]


@contextmanager
def log_runtime_warnings(target_logger: Logger, operation: str) -> Iterator[None]:
    """Route Python runtime warnings through Kit's warning log channel."""
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", RuntimeWarning)
        try:
            yield
        finally:
            for caught_warning in caught_warnings:
                target_logger.warning("%s: %s", operation, caught_warning.message)


class RtSubPrimGuard:
    """Keeps a fixed set of RT sub-prims in sync with a primary USD prim.

    Mirrors visibility and deactivation state from the primary prim onto the
    sub-prims and removes the sub-prims when the primary prim is deleted.

    Usage
    -----
    Call ``RtSubPrimGuard.register(primary_prim, rt_stage, sub_prim_paths)``
    once per primary prim — typically in an operator's ``exec`` method.
    The guard is self-contained and manages its own lifetime.

    Class Attributes
    ----------------
    _registry : dict[str, RtSubPrimGuard]
        Live guards keyed by primary prim path string.  Kept as a class
        attribute so that all guards share a single collection and
        ``clear_all`` can revoke them in one call.
    _stage_sub : StageUpdateNode or None
        Stage-update subscription that fires ``clear_all`` on every stage
        attach and detach.  Created lazily the first time a guard is
        instantiated and intentionally never released (it must outlive all
        guards).
    """

    _registry: dict[str, "RtSubPrimGuard"] = {}
    _stage_sub = None

    @staticmethod
    def register(primary_prim: Usd.Prim, rt_stage, sub_prim_paths: list) -> None:
        """Register a guard for *primary_prim*, no-op if already registered."""
        key = primary_prim.GetPath().pathString
        if key not in RtSubPrimGuard._registry:
            RtSubPrimGuard._registry[key] = RtSubPrimGuard(primary_prim, rt_stage, sub_prim_paths)

    @staticmethod
    def clear_all() -> None:
        """Revoke all active guards and clear the registry.

        Automatically called on stage attach and detach via ``_stage_sub``
        so that guards from the previous stage do not linger.
        """
        for guard in RtSubPrimGuard._registry.values():
            guard._listener.Revoke()
        RtSubPrimGuard._registry.clear()

    def __init__(self, primary_prim: Usd.Prim, rt_stage, sub_prim_paths: list):
        # Lazily create the stage-update subscription the first time any guard is
        # instantiated.  The node fires clear_all() on both attach (new stage
        # opened) and detach (stage closed) so that guards referencing prims from
        # the previous stage are revoked before any new guards are registered.
        # The subscription is stored on the class and intentionally never released:
        # it must remain alive for the entire session so that every future stage
        # transition is handled, even after the registry has been emptied.
        if RtSubPrimGuard._stage_sub is None:
            RtSubPrimGuard._stage_sub = get_stage_update_interface().create_stage_update_node(
                "cae.viz.rt_sub_prim_guards",
                on_attach_fn=lambda *_: RtSubPrimGuard.clear_all(),
                on_detach_fn=lambda: RtSubPrimGuard.clear_all(),
            )

        self._prim = primary_prim
        self._prim_path = primary_prim.GetPath()
        self._rt_stage = rt_stage
        self._sub_prim_paths = [SdfRT.Path(str(p)) for p in sub_prim_paths]
        self._imageable = UsdGeom.Imageable(primary_prim)
        self._listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self, primary_prim.GetStage())

    def __call__(self, notice, stage):
        # Visibility attribute changed on this prim or an ancestor.
        for path in notice.GetChangedInfoOnlyPaths():
            if path.name == "visibility" and self._prim_path.HasPrefix(path.GetPrimPath()):
                self._apply(self._prim.IsValid() and self._imageable.ComputeVisibility() != UsdGeom.Tokens.invisible)
                return
        # Structural resync — covers deactivation or deletion of this prim or an ancestor.
        for path in notice.GetResyncedPaths():
            if self._prim_path.HasPrefix(path):
                if not self._prim.IsValid():
                    self._remove_sub_prims()
                    self._listener.Revoke()
                    RtSubPrimGuard._registry.pop(self._prim_path.pathString, None)
                else:
                    self._apply(
                        self._prim.IsActive() and self._imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
                    )
                return

    def _apply(self, active: bool) -> None:
        for path in self._sub_prim_paths:
            prim = self._rt_stage.GetPrimAtPath(path)
            if prim:
                prim.CreateAttribute("_worldVisibility", SdfRT.ValueTypeNames.Bool).Set(active)
                prim.GetAttribute("visibility").Set(
                    UsdGeomRT.Tokens.inherited if active else UsdGeomRT.Tokens.invisible
                )

    def _remove_sub_prims(self) -> None:
        for path in self._sub_prim_paths:
            if self._rt_stage.GetPrimAtPath(path):
                self._rt_stage.RemovePrim(path)


def edit_context(prim: Usd.Prim):
    """
    Returns the edit context for the given prim.
    For operators that update PXR USD prims (rather that UsdRt USD prims),
    the changes made by operators are typically not applied on the root layer but instead
    are applied on the session layer. This ensures that the changes don't clobber the root layer stage
    exports and also are not accidentally overridden by the user.

    Usage:

        with edit_context(prim):
            prim.GetAttribute("someAttr").Set("new_value")


    Caution:

        Never use `await` while an edit context is active. In general any long running operations should be
        avoided while an edit context is active. It's best to scope things such that the edit context is active
        only while updating properties on Prim and is deactivated as soon as the operation is complete.
    """
    stage = prim.GetStage()
    return Usd.EditContext(stage, stage.GetEditTargetForLocalLayer(stage.GetSessionLayer()))


def is_attr_locked(attr: Usd.Attribute) -> bool:
    """
    Returns True if the attribute is locked, False otherwise.
    """
    if not attr:
        raise ValueError("Attribute is None")
    if attr.HasCustomDataKey("omni:kit:locked") and attr.GetCustomDataByKey("omni:kit:locked"):
        return True
    return False


def process_rescale_range_apis(prim: Usd.Prim, dataset: simdata.Dataset):
    """
    Processes the CaeVizRescaleRangeAPI schemas on the given prim and rescales the range of the attributes specified in the schemas.
    For every instance of CaeVizRescaleRangeAPI, the range of the attributes specified in the 'includes' relationship are rescaled
    to the range of the field specified in the instance name. The rescaling is done using the 'rescaleMode' attribute.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to process
    dataset : simdata.Dataset
        The dataset to obtain the field ranges from
    """
    stage = prim.GetStage()

    instance_names = set(usd_utils.get_instances(prim, "CaeVizRescaleRangeAPI"))
    for instance_name in instance_names:
        rescale_range_api = cae_viz.RescaleRangeAPI(prim, instance_name)
        rescale_mode = rescale_range_api.GetRescaleModeAttr().Get()

        if rescale_mode == cae_viz.Tokens.disable:
            continue

        include_targets = rescale_range_api.GetIncludesRel().GetForwardedTargets()
        min_include_targets = rescale_range_api.GetMinIncludesRel().GetForwardedTargets()
        max_include_targets = rescale_range_api.GetMaxIncludesRel().GetForwardedTargets()
        enable_include_targets = rescale_range_api.GetEnableIncludesRel().GetForwardedTargets()

        # filter all include targes to only consider attribute paths and then fetch those attributes from the stage
        attrs = [stage.GetAttributeAtPath(target) for target in include_targets if target.IsPrimPropertyPath()]

        # filter to only include attributes that can represent a float2
        attrs = [attr for attr in attrs if attr and attr.GetTypeName() == Sdf.ValueTypeNames.Float2]

        min_attrs = [stage.GetAttributeAtPath(target) for target in min_include_targets if target.IsPrimPropertyPath()]
        min_attrs = [attr for attr in min_attrs if attr and attr.GetTypeName() == Sdf.ValueTypeNames.Float]

        max_attrs = [stage.GetAttributeAtPath(target) for target in max_include_targets if target.IsPrimPropertyPath()]
        max_attrs = [attr for attr in max_attrs if attr and attr.GetTypeName() == Sdf.ValueTypeNames.Float]

        enable_attrs = [
            stage.GetAttributeAtPath(target) for target in enable_include_targets if target.IsPrimPropertyPath()
        ]
        enable_attrs = [attr for attr in enable_attrs if attr and attr.GetTypeName() == Sdf.ValueTypeNames.Bool]

        # filter to remove locked attributes i.e. attributes that have the "omni:kit:locked" custom data key set to True
        attrs = [attr for attr in attrs if not is_attr_locked(attr)]
        min_attrs = [attr for attr in min_attrs if not is_attr_locked(attr)]
        max_attrs = [attr for attr in max_attrs if not is_attr_locked(attr)]
        enable_attrs = [attr for attr in enable_attrs if not is_attr_locked(attr)]

        # if there are no attributes to process, skip
        if not attrs and not min_attrs and not max_attrs and not enable_attrs:
            continue

        # if the field is not present, set the enable attributes to False
        if not dataset.has_field(instance_name):
            for attr in enable_attrs:
                attr.Set(False)
            continue

        field = dataset.get_field(instance_name)
        range_min, range_max = field.get_range()  # for vectors, this returns the magnitude range
        for attr in attrs:
            if rescale_mode == cae_viz.Tokens.clamp:
                logger.info(f"Clamping range of attribute {attr.GetPath()} to ({range_min}, {range_max})")
                attr.Set((range_min, range_max))
            elif rescale_mode == cae_viz.Tokens.grow:
                cur_val = attr.Get()
                if cur_val is not None and cur_val[0] <= cur_val[1]:
                    v_min = min(cur_val[0], range_min)
                    v_max = max(cur_val[1], range_max)
                else:
                    v_min = range_min
                    v_max = range_max
                logger.info(f"Growing range of attribute {attr.GetPath()} to ({v_min}, {v_max})")
                attr.Set((v_min, v_max))

        for attr in min_attrs:
            if rescale_mode == cae_viz.Tokens.clamp:
                logger.info(f"Clamping range of attribute {attr.GetPath()} to {range_min}")
                attr.Set(range_min)
            elif rescale_mode == cae_viz.Tokens.grow:
                cur_val = attr.Get()
                if cur_val is not None and cur_val <= range_min:
                    v_min = range_min
                else:
                    v_min = cur_val
                logger.info(f"Growing range of attribute {attr.GetPath()} to {v_min}")
                attr.Set(v_min)

        for attr in max_attrs:
            if rescale_mode == cae_viz.Tokens.clamp:
                logger.info(f"Clamping range of attribute {attr.GetPath()} to {range_max}")
                attr.Set(range_max)
            elif rescale_mode == cae_viz.Tokens.grow:
                cur_val = attr.Get()
                if cur_val is not None and cur_val >= range_max:
                    v_max = range_max
                else:
                    v_max = cur_val
                logger.info(f"Growing range of attribute {attr.GetPath()} to {v_max}")
                attr.Set(v_max)

        for attr in enable_attrs:
            attr.Set(True)


def process_configure_xac_shader_apis(prim: Usd.Prim, dataset: simdata.Dataset) -> float | None:
    """
    Processes the CaeVizConfigureXACShaderAPI schemas on the given prim and configures the XAC shader based on the field.

    For every instance of CaeVizConfigureXACShaderAPI, the voxel size and sample mode are configured based on the
    field type. The voxel size is configured based on the voxel size of the nvdb field specified in the
    instance name. The sample mode is configured based on the field type.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to process
    dataset : simdata.Dataset
        The dataset to obtain the field ranges from

    Returns
    -------
    float | None
        The suggested voxel size for IndeX rendering, None if not applicable

    Notes
    -----
    For NanoVDB volumes, the suggested voxel size is returned. For other volumes, None is returned.
    The value returned is the minimum voxel size of all the fields specified in the CaeVizConfigureXACShaderAPI instances.
    """
    stage = prim.GetStage()

    instance_names = set(usd_utils.get_instances(prim, "CaeVizConfigureXACShaderAPI"))
    index_voxel_size = None
    for instance_name in instance_names:
        if not dataset.has_field(instance_name):
            continue

        field = dataset.get_field(instance_name)
        if field.dtype not in [wp.float32, wp.vec3f]:
            logger.warning(
                "Automatic configuration of XAC shader is only supported for float32 and vec3f fields currently."
            )
            continue

        if hasattr(field.get_data(), "get_voxel_size"):
            voxel_size = field.get_data().get_voxel_size()
            voxel_size = np.array(voxel_size, dtype=np.float32).tolist()
            index_voxel_size = (
                min(index_voxel_size, min(voxel_size)) if index_voxel_size is not None else min(voxel_size)
            )
        else:
            voxel_size = [1.0, 1.0, 1.0]

        mode = 0 if field.dtype == wp.float32 else 1

        configure_xac_shader_api = cae_viz.ConfigureXACShaderAPI(prim, instance_name)

        for voxel_size_include in configure_xac_shader_api.GetVoxelSizeIncludesRel().GetForwardedTargets():
            attr = stage.GetAttributeAtPath(voxel_size_include)
            if attr and is_attr_locked(attr):
                continue
            elif attr and attr.GetTypeName() == Sdf.ValueTypeNames.Float3:
                attr.Set(tuple(voxel_size))
            else:
                logger.warning(
                    f"Invalid attribute type for voxel size include {voxel_size_include}: {attr.GetTypeName()}"
                )

        for sample_mode_include in configure_xac_shader_api.GetSampleModeIncludesRel().GetForwardedTargets():
            attr = stage.GetAttributeAtPath(sample_mode_include)
            if attr and is_attr_locked(attr):
                continue
            elif attr and attr.GetTypeName() == Sdf.ValueTypeNames.Int:
                attr.Set(int(mode))
            else:
                logger.warning(
                    f"Invalid attribute type for sample mode include {sample_mode_include}: {attr.GetTypeName()}"
                )

    return index_voxel_size


def process_configure_xac_shader_apis_temporal(
    prim: Usd.Prim, timecode: Usd.TimeCode, next_timecode: Usd.TimeCode, raw_timecode: Usd.TimeCode
):
    """
    Updates XAC shader temporal interpolation parameters.

    This function configures the shader parameters needed for field interpolation:
    - attrib_idx: int2 with (current_idx, next_idx) - set next to -1 to disable interpolation
    - time_codes: float3 with (current, next, raw) time code values

    Parameters
    ----------
    prim : Usd.Prim
        The volume prim to configure
    timecode : Usd.TimeCode
        Current snapped timecode (from get_bracketing_time_samples_for_prim)
    next_timecode : Usd.TimeCode or None
        Next bracketing timecode for interpolation (None if not available)
    raw_timecode : Usd.TimeCode
        Original timeline timecode before snapping
    """
    # Check if field interpolation is enabled
    enable_field_interpolation = (
        prim.HasAPI(cae_viz.OperatorTemporalAPI)
        and cae_viz.OperatorTemporalAPI(prim).GetEnableFieldInterpolationAttr().Get()
    )

    # Get field selection instances to determine attribute indices
    instance_names = usd_utils.get_instances(prim, "CaeVizFieldSelectionAPI")
    num_fields = len(instance_names)

    # Calculate time code values
    current_tc = float(timecode.GetValue())
    next_tc = float(next_timecode.GetValue()) if next_timecode else current_tc
    raw_tc = float(raw_timecode.GetValue())

    time_codes = Gf.Vec3f(current_tc, next_tc, raw_tc)

    stage = prim.GetStage()
    xac_instance_names = usd_utils.get_instances(prim, "CaeVizConfigureXACShaderAPI")
    for xac_instance_name in xac_instance_names:
        if xac_instance_name not in instance_names:
            logger.warning(
                f"CaeVizConfigureXACShaderAPI instance {xac_instance_name} not found in CaeVizFieldSelectionAPI instances"
            )
            continue

        # Calculate attribute indices
        current_attrib_idx = instance_names.index(xac_instance_name)

        # Set next to -1 to disable interpolation, or +num_fields to enable it
        next_attrib_idx = current_attrib_idx + num_fields if (enable_field_interpolation and next_timecode) else -1
        attrib_idx = Gf.Vec2i(current_attrib_idx, next_attrib_idx)

        xac_instance = cae_viz.ConfigureXACShaderAPI(prim, xac_instance_name)
        for attrib_idx_include in xac_instance.GetAttribIdxIncludesRel().GetForwardedTargets():
            attr = stage.GetAttributeAtPath(attrib_idx_include)
            if attr and is_attr_locked(attr):
                continue
            elif attr and attr.GetTypeName() == Sdf.ValueTypeNames.Int2:
                attr.Set(attrib_idx)

        for time_codes_include in xac_instance.GetTimeCodesIncludesRel().GetForwardedTargets():
            attr = stage.GetAttributeAtPath(time_codes_include)
            if attr and is_attr_locked(attr):
                continue
            elif attr and attr.GetTypeName() == Sdf.ValueTypeNames.Float3:
                attr.Set(time_codes)


def apply_field_mapping(prim: Usd.Prim, field_name: str, f_array):
    """
    Apply field mapping to an array if FieldMappingAPI is present.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to check for FieldMappingAPI
    field_name : str
        The name of the field/instance
    f_array : array-like
        The array to remap

    Returns
    -------
    array-like
        The remapped array, or the original array if no mapping is present or if mapping is invalid
    """
    if prim.HasAPI(cae_viz.FieldMappingAPI, field_name):
        field_mapping_api = cae_viz.FieldMappingAPI(prim, field_name)
        fm_domain = field_mapping_api.GetDomainAttr().Get()
        fm_range = field_mapping_api.GetRangeAttr().Get()
        if fm_domain and fm_range and fm_domain[0] <= fm_domain[1]:
            return array_utils.remap_array(f_array, tuple(fm_domain), tuple(fm_range))
        elif fm_domain:
            logger.error(f"Invalid domain {fm_domain} for field {field_name}")
    return f_array


def process_field_selection_apis(
    prim: Usd.Prim,
    dataset: simdata.Dataset,
    *,
    include_fields: set[str] | None = None,
    exclude_fields: set[str] | None = None,
    output_prim_rt: UsdRT.Prim | None = None,
):
    """
    Processes the CaeVizFieldSelectionAPI schemas on the given prim and populates the primvars based on the fields.

    For every instance of CaeVizFieldSelectionAPI, the primvars are populated based on the fields specified in the
    instance name.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to process
    dataset : simdata.Dataset
        The dataset to populate the primvars into
    include_fields : set[str], optional
        A set of field names to include even if FieldSelectionAPI is not present for them.
    exclude_fields : set[str], optional
        A set of field names to exclude from processing
    output_prim_rt : UsdRT.Prim, optional
        RT prim that receives the generated primvars. Defaults to the RT
        counterpart of ``prim``.
    """
    include_fields = include_fields or set()
    exclude_fields = exclude_fields or set()
    prim_rt = usd_utils.get_prim_rt(prim) if output_prim_rt is None else output_prim_rt
    pv_api = UsdGeomRT.PrimvarsAPI(prim_rt)

    instance_names = set(usd_utils.get_instances(prim, "CaeVizFieldSelectionAPI"))

    for field_name in dataset.get_field_names():
        if field_name in exclude_fields:
            continue

        if field_name not in instance_names and field_name not in include_fields:
            continue

        field = dataset.get_field(field_name)
        if field.association == simdata.AssociationType.NODE:
            interpolation = UsdGeomRT.Tokens.vertex
        elif field.association == simdata.AssociationType.ELEMENT:
            interpolation = UsdGeomRT.Tokens.uniform
        else:
            raise ValueError(f"Unsupported association type {field.association} for primvar {field_name}")

        f_array = cae_simdata.fetch_data(dataset, field_name)
        assert f_array is not None, f"Field {field_name} not found or cannot be passed as primvar"

        if f_array.ndim > 2:
            logger.error(f"Unsupported array shape {f_array.shape} for primvar {field_name}")
            continue

        # process field mapping API if present
        f_array = apply_field_mapping(prim, field_name, f_array)

        array_dtype = array_utils.get_numpy_dtype(f_array)
        nb_comps = f_array.shape[1] if f_array.ndim > 1 else 1
        if nb_comps == 1:
            if array_dtype in [np.float32, np.float64]:
                pv_type = SdfRT.ValueTypeNames.FloatArray
            elif array_dtype in [np.int32, np.int64]:
                pv_type = SdfRT.ValueTypeNames.IntArray
            else:
                logger.error(f"Unsupported dtype {f_array.dtype} for primvar {field_name}")
                continue
        elif nb_comps == 3:
            if array_dtype in [np.float32, np.float64]:
                pv_type = SdfRT.ValueTypeNames.Float3Array
            elif array_dtype in [np.int32, np.int64]:
                pv_type = SdfRT.ValueTypeNames.Int3Array
            else:
                logger.error(f"Unsupported dtype {f_array.dtype} for primvar {field_name}")
                continue
        else:
            logger.warning(f"Unsupported number of components {nb_comps} for primvar {field_name}")
            continue

        logger.info(f"Creating primvar {field_name} with shape {f_array.shape} and dtype {f_array.dtype}")
        if not pv_api.GetPrimvar(field_name).GetAttr():
            pv = pv_api.CreatePrimvar(field_name, pv_type, interpolation)
        else:
            pv = pv_api.GetPrimvar(field_name)
            pv.SetInterpolation(interpolation)

        set_array_attribute(pv.GetAttr(), f_array)


def process_widths(prim: Usd.Prim, dataset: simdata.Dataset, fixed_width: float):
    if prim.HasAPI(cae_viz.FieldSelectionAPI, "widths") and dataset.has_field("widths"):
        return  # widths are/will-be passed as primvar by process_field_selection_apis

    prim_rt = usd_utils.get_prim_rt(prim)
    pv_api = UsdGeomRT.PrimvarsAPI(prim_rt)

    # Once a primvar is created, USDRT doesn't like changing its interpolation type.
    # So, as soon as CaeFieldSelectionAPI:widths is specified, we always use vertex interpolation.
    # Otherwise, we always use constant interpolation regardless of whether constant or vertex-specific
    # widths are being used.
    if prim.HasAPI(cae_viz.FieldSelectionAPI, "widths"):
        pv = pv_api.CreatePrimvar("widths", SdfRT.ValueTypeNames.FloatArray, UsdGeomRT.Tokens.vertex)
        widths = wp.full((dataset.get_num_nodes(), 1), fixed_width, dtype=wp.float32, device=dataset.device)
        set_array_attribute(pv.GetAttr(), widths)
    else:
        pv = pv_api.CreatePrimvar("widths", SdfRT.ValueTypeNames.FloatArray, UsdGeomRT.Tokens.constant)
        widths = wp.array([fixed_width], dtype=wp.float32, device=dataset.device)
        set_array_attribute(pv.GetAttr(), widths)


async def get_available_fields(stage, prim_path) -> list[cae_simdata.FieldInfo]:
    """Return sorted FieldInfo objects common to all datasets reachable from *prim_path*.

    Walks the ``CaeVizDatasetSelectionAPI:source:target`` relationship on the prim
    and calls ``GetAvailableFields.invoke()`` on each target dataset prim.  Returns
    only the fields that appear in every target (intersection), sorted by name.
    When multiple targets agree on the field name but differ in association, the
    association from the first target that introduced the field is used.

    Parameters
    ----------
    stage:
        The USD stage.
    prim_path:
        Path of the operator prim (``Sdf.Path`` or path string).
    """
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        return []
    source_rel = prim.GetRelationship("cae:viz:dataset_selection:source:target")
    if not source_rel:
        return []

    # Collect per-target dicts: name -> FieldInfo
    per_target: list[dict[str, cae_simdata.FieldInfo]] = []
    for target_path in source_rel.GetTargets():
        target = stage.GetPrimAtPath(target_path)
        if not target:
            continue
        fields = {fi.name: fi for fi in await cae_simdata.GetAvailableFields.invoke(target)}
        per_target.append(fields)

    if not per_target:
        return []

    # Intersect on field name; keep FieldInfo from the first dict that has it
    common_names = set(per_target[0].keys())
    for fields in per_target[1:]:
        common_names &= fields.keys()

    return sorted(
        (per_target[0][name] for name in common_names),
        key=lambda fi: fi.name,
    )


def _get_selected_dataset_prims(prim: Usd.Prim, instance_name: str) -> list[Usd.Prim]:
    """Return dataset prims targeted by CaeVizDatasetSelectionAPI:<instance_name>."""
    if not prim.HasAPI(cae_viz.DatasetSelectionAPI, instance_name):
        raise ValueError(
            f"Prim {prim.GetPath()} does not have CaeVizDatasetSelectionAPI with instance name '{instance_name}'"
        )

    ds_api = cae_viz.DatasetSelectionAPI(prim, instance_name)
    target_rel = ds_api.GetTargetRel()
    target_paths = target_rel.GetTargets() if target_rel else []
    if not target_paths:
        raise usd_utils.QuietableException(
            f"No target prims found for DatasetSelectionAPI:{instance_name} at {ds_api.GetPath()}"
        )

    stage = prim.GetStage()
    dataset_prims = []
    for target_path in target_paths:
        dataset_prim = stage.GetPrimAtPath(target_path)
        if not dataset_prim:
            raise usd_utils.QuietableException(
                f"Missing target prim at path {target_path} for DatasetSelectionAPI:{instance_name} at {ds_api.GetPath()}"
            )
        dataset_prims.append(dataset_prim)
    return dataset_prims


def get_selected_dataset_prims(prim: Usd.Prim, instance_name: str) -> list[Usd.Prim]:
    """Return dataset prims targeted by CaeVizDatasetSelectionAPI:<instance_name>."""
    return _get_selected_dataset_prims(prim, instance_name)


def _validate_selected_dataset_prim_types(dataset_prims: list[Usd.Prim]) -> None:
    if all(ds_prim.IsA(cae.DataSet) for ds_prim in dataset_prims):
        return
    if all(ds_prim.IsA(OmniSci.Dataset) for ds_prim in dataset_prims):
        return
    if all(ds_prim.IsA(UsdGeom.Mesh) for ds_prim in dataset_prims):
        return
    raise ValueError(
        "Mixing CaeDataSet, OmniSciDataset, and UsdGeomMesh prims in the same DatasetSelectionAPI is not supported. "
        f"Found prims: {[p.GetPath() for p in dataset_prims]}"
    )


async def get_selected_datasets(
    prim: Usd.Prim,
    instance_name: str,
    *,
    timeCode: Usd.TimeCode,
    device: str,
    needs_topology: bool = True,
    needs_geometry: bool = True,
) -> list[simdata.Dataset]:
    """
    Returns the selected datasets for the given instance name.
    This handles dataset prims of both types CaeDataSet or OmniSciDataset.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to get the selected dataset from
    instance_name : str
        The instance name of the DatasetSelectionAPI
    timeCode : Usd.TimeCode
        The time code to get the dataset for
    device : str
        The device to get the dataset for
    needs_topology : bool, optional
        Whether the dataset needs topology information, by default True
    needs_geometry : bool, optional
        Whether the dataset needs geometry information, by default True

    Returns
    -------
    list[simdata.Dataset]
        The selected datasets
    """

    # TODO: this should handle CaeVizDatasetTransformingAPI instances as well and return a transformed dataset.
    # SimData should add support for a data model for xformed datasets.

    cache_key = (
        f"[viz:get_selected_dataset]::{instance_name}:{prim.GetPath()}::{device}::{needs_topology}::{needs_geometry}"
    )
    if cached := cache.get(cache_key, timeCode=timeCode):
        return [dataset.shallow_copy() for dataset in cached]

    dataset_prims = _get_selected_dataset_prims(prim, instance_name)
    _validate_selected_dataset_prim_types(dataset_prims)

    datasets = []
    for dataset_prim in dataset_prims:
        if not dataset_prim:
            continue
        dataset = await cae_simdata.get_dataset(
            dataset_prim, timeCode, device=device, needs_topology=needs_topology, needs_geometry=needs_geometry
        )
        datasets.append(dataset)

    prim_watches = []
    prim_watches.extend(cache.PrimWatch(p) for p in dataset_prims)
    prim_watches.append(cache.PrimWatch(prim, on="delete"))
    prim_watches.append(cache.PrimWatch(prim, on="any", schemas=[(cae_viz.DatasetSelectionAPI, instance_name)]))
    cache.put_ex(cache_key, datasets, prims=prim_watches, timeCode=timeCode)
    return [dataset.shallow_copy() for dataset in datasets]


def _resolve_selected_field_names(
    prim: Usd.Prim, dataset_prim: Usd.Prim, f_selection_api: cae_viz.FieldSelectionAPI, timeCode: Usd.TimeCode
) -> list[str]:
    """Resolve FieldSelectionAPI targets to field names on a selected dataset prim."""
    if dataset_prim.IsA(OmniSci.Dataset):
        field_names = f_selection_api.GetFieldNamesAttr().Get(timeCode)
        return [str(name) for name in field_names] if field_names else []
    if not dataset_prim.IsA(cae.DataSet):
        raise ValueError(
            f"Unsupported dataset prim type {dataset_prim.GetTypeName()} for FieldSelectionAPI at "
            f"{f_selection_api.GetPath()}. Expected CaeDataSet or OmniSciDataset."
        )

    target_rel = f_selection_api.GetTargetRel()
    dataset_field_rels = sorted(
        str(rel.GetName()) for rel in dataset_prim.GetRelationships() if str(rel.GetName()).startswith("field:")
    )
    field_prims = usd_utils.get_target_prims(prim, target_rel.GetName())

    field_names = []
    for field_prim in field_prims:
        try:
            field_names.append(usd_utils.get_field_name(dataset_prim, field_prim))
        except usd_utils.QuietableException as exc:
            logger.error(
                f"FieldSelectionAPI target {field_prim.GetPath()} on {prim.GetPath()} is not a valid field "
                f"on selected dataset {dataset_prim.GetPath()}. Available dataset fields: {dataset_field_rels}"
            )
            raise

    return field_names


def _apply_field_selection_mode(
    field: simdata.Field, f_selection_api: cae_viz.FieldSelectionAPI, prim: Usd.Prim, timeCode: Usd.TimeCode
) -> simdata.Field:
    """Apply CaeVizFieldSelectionAPI mode to a loaded SimData field."""
    selection_mode = f_selection_api.GetModeAttr().Get(timeCode)
    if selection_mode == cae_viz.Tokens.unchanged:
        return field
    if selection_mode == cae_viz.Tokens.vector_magnitude:
        return simdata.Field.from_field(field, magnitude=True) if simdata.utils.is_vector_dtype(field.dtype) else field
    if selection_mode == cae_viz.Tokens.selected_component:
        component_index = f_selection_api.GetComponentIndexAttr().Get(timeCode)
        if not simdata.utils.is_vector_dtype(field.dtype):
            if component_index != 0:
                logger.warning(
                    f"Component index {component_index} is not supported for scalar fields on prim {prim.GetPath()}."
                )
            return field

        nb_components = simdata.utils.get_vector_length(field.dtype)
        if component_index < 0 or component_index >= nb_components:
            raise ValueError(
                f"Component index {component_index} out of range for field dtype {field.dtype}. "
                f"Vector length is {nb_components}."
            )
        return simdata.Field.from_field(field, component=component_index)
    raise ValueError(f"Unsupported FieldSelectionAPI mode '{selection_mode}'.")


async def _get_selected_field(
    prim: Usd.Prim,
    dataset_prim: Usd.Prim,
    instance_name: str,
    *,
    timeCode: Usd.TimeCode,
    device: str,
    representation=None,
) -> simdata.Field:
    """Load a field described by CaeVizFieldSelectionAPI:<instance_name>."""
    if not prim.HasAPI(cae_viz.FieldSelectionAPI, instance_name):
        raise ValueError(
            f"Prim {prim.GetPath()} does not have CaeVizFieldSelectionAPI with instance name '{instance_name}'"
        )

    f_selection_api = cae_viz.FieldSelectionAPI(prim, instance_name)
    field_names = _resolve_selected_field_names(prim, dataset_prim, f_selection_api, timeCode)
    if not field_names:
        raise usd_utils.QuietableException(
            f"No target field names found for FieldSelectionAPI at {f_selection_api.GetPath()}"
        )
    field = await cae_simdata.GetField.invoke(
        dataset_prim, field_names, device=device, timeCode=timeCode, representation=representation
    )
    return _apply_field_selection_mode(field, f_selection_api, prim, timeCode)


async def get_selected_field(
    prim: Usd.Prim, dataset_prim: Usd.Prim, instance_name: str, *, timeCode: Usd.TimeCode, device: str
) -> simdata.Field:
    """Load a field described by CaeVizFieldSelectionAPI:<instance_name>."""
    return await _get_selected_field(prim, dataset_prim, instance_name, timeCode=timeCode, device=device)


async def _add_selected_fields(
    dataset: simdata.Dataset,
    dataset_prim: Usd.Prim,
    prim: Usd.Prim,
    timeCode: Usd.TimeCode,
    required_instances: set[str] | None = None,
    representation=None,
) -> simdata.Dataset:
    """Populate selected fields onto a loaded dataset."""
    required_instances = required_instances or set()
    instance_names = usd_utils.get_instances(prim, "CaeVizFieldSelectionAPI")
    for name in required_instances:
        if name not in instance_names:
            raise usd_utils.QuietableException(f"Required field '{name}' not found on prim {prim.GetPath()}")

    for instance_name in instance_names:
        try:
            field = await _get_selected_field(
                prim,
                dataset_prim,
                instance_name,
                timeCode=timeCode,
                device=dataset.device,
                representation=representation,
            )
            dataset.add_field(instance_name, field)
        except usd_utils.QuietableException as exc:
            if instance_name in required_instances:
                raise
            logger.info(f"Skipping optional field '{instance_name}' due to error: {exc}")
    return dataset


@dataclass(frozen=True)
class VoxelizationParameters:
    min_ijk: wp.vec3i
    max_ijk: wp.vec3i
    voxel_size: wp.vec3f
    field_centering: str


def _get_voxelization_field_centering(nvdb_api: cae_viz.DatasetVoxelizationAPI, timeCode: Usd.TimeCode) -> str:
    attr = nvdb_api.GetFieldCenteringAttr()
    field_centering = str(attr.Get(timeCode) if attr and attr.IsValid() else None)
    if field_centering not in _VOXELIZATION_FIELD_CENTERINGS:
        raise ValueError(f"Unsupported voxelization field centering: {field_centering}")
    return field_centering


def _get_voxelization_output_association(field_centering: str) -> simdata.AssociationType:
    if field_centering == "point":
        return simdata.AssociationType.NODE
    if field_centering == "cell":
        return simdata.AssociationType.ELEMENT
    raise ValueError(f"Unsupported voxelization field centering: {field_centering}")


def _get_voxelization_parameters(
    prim: Usd.Prim, instance_name: str, data_bounds: Gf.Range3d, timeCode: Usd.TimeCode
) -> VoxelizationParameters:
    """
    Returns the voxelization parameters for the given prim and data bounds.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to get the voxelization parameters from
    instance_name : str
        The instance name of the DatasetVoxelizationAPI
    data_bounds : Gf.Range3d
        The bounds of the data to voxelize
    timeCode : Usd.TimeCode
        The time code to get the voxelization parameters for

    Returns
    -------
    VoxelizationParameters
        The voxelization parameters
    """
    if data_bounds.IsEmpty():
        raise ValueError("Data bounds are empty. Data bounds must be specified.")

    nvdb_api = cae_viz.DatasetVoxelizationAPI(prim, instance_name)
    field_centering = _get_voxelization_field_centering(nvdb_api, timeCode)

    # if ROI is specified, intersect the data bounds with the ROI bounds
    if roi_prim := usd_utils.get_target_prim(prim, nvdb_api.GetRoiRel().GetName(), quiet=True):
        if roi_bounds := usd_utils.get_bounds(roi_prim, timeCode, quiet=True):
            data_bounds.IntersectWith(roi_bounds)
            if data_bounds.IsEmpty():
                raise ValueError(
                    "Data bounds are empty after intersecting with ROI bounds. ROI may not intersect with data bounds."
                )

    data_bounds = np.array([data_bounds.GetMin(), data_bounds.GetMax()], dtype=np.float32)

    inflate_bounds = nvdb_api.GetInflateBoundsAttr().Get(timeCode)
    if inflate_bounds > 0:
        size = data_bounds[1] - data_bounds[0]
        inflation = size * inflate_bounds * 0.01
        data_bounds[0] -= inflation * 0.5
        data_bounds[1] += inflation * 0.5

    vox_size_mode = nvdb_api.GetVoxelSizeModeAttr().Get(timeCode)
    if vox_size_mode == cae_viz.Tokens.maxResolution:
        max_resolution = int(nvdb_api.GetMaxResolutionAttr().Get(timeCode))
        min_bounds = data_bounds[0]
        max_bounds = data_bounds[1]
        bounds_range = max_bounds - min_bounds

        # Start with initial voxel size based on max_resolution
        voxel_size = np.max(bounds_range) / max_resolution

        # Iteratively compute ijk bounds and adjust voxel_size if needed
        max_iterations = 10
        for iteration in range(max_iterations):
            # Compute ijk bounds using floor/ceil
            # Volume will extend from [voxel_size * ijk_min] to [voxel_size * ijk_max]
            ijk_min_float = min_bounds / voxel_size
            ijk_max_float = max_bounds / voxel_size

            ijk_min_arr = np.floor(ijk_min_float).astype(int)
            ijk_max_arr = np.ceil(ijk_max_float).astype(int)

            # Pad if bounds exactly align with voxel boundaries
            for i in range(3):
                if np.isclose(ijk_min_float[i], ijk_min_arr[i]):
                    ijk_min_arr[i] -= 1
                if np.isclose(ijk_max_float[i], ijk_max_arr[i]):
                    ijk_max_arr[i] += 1

            # Check dimensions (number of cells = ijk_max - ijk_min)
            dims = ijk_max_arr - ijk_min_arr
            max_dim = np.max(dims)

            if max_dim <= max_resolution:
                # Success! Verify that the volume encloses the bounds
                # Volume extends from [voxel_size * ijk_min] to [voxel_size * ijk_max]
                volume_min = voxel_size * ijk_min_arr
                volume_max = voxel_size * ijk_max_arr

                # Check enclosure with a small tolerance for floating point errors
                tolerance = 1e-6 * voxel_size
                if not np.all(volume_min <= min_bounds + tolerance):
                    raise RuntimeError(
                        f"Volume min {volume_min} does not enclose bounds min {min_bounds}\n"
                        f"  voxel_size={voxel_size}, ijk_min={ijk_min_arr}"
                    )
                if not np.all(volume_max >= max_bounds - tolerance):
                    raise RuntimeError(
                        f"Volume max {volume_max} does not enclose bounds max {max_bounds}\n"
                        f"  voxel_size={voxel_size}, ijk_max={ijk_max_arr}"
                    )

                break

            # Need to increase voxel_size to reduce dimensions
            scale_factor = max_dim / max_resolution
            voxel_size *= scale_factor * 1.01  # Add 1% margin to ensure convergence
        else:
            raise RuntimeError(f"Failed to compute valid voxelization parameters after {max_iterations} iterations")

        ijk_min = wp.vec3i(*ijk_min_arr.tolist())
        ijk_max = wp.vec3i(*ijk_max_arr.tolist())

        return VoxelizationParameters(ijk_min, ijk_max, wp.vec3f(voxel_size, voxel_size, voxel_size), field_centering)

    elif vox_size_mode == cae_viz.Tokens.voxelSize:
        voxel_size = nvdb_api.GetVoxelSizeAttr().Get(timeCode)
        voxel_size = np.array(voxel_size, dtype=np.float32)
        ijk_min = wp.vec3i(np.floor(data_bounds[0] / voxel_size).astype(int))
        ijk_max = wp.vec3i(np.ceil(data_bounds[1] / voxel_size).astype(int))
        return VoxelizationParameters(ijk_min, ijk_max, wp.vec3f(voxel_size), field_centering)
    else:
        raise ValueError(f"Unsupported NanoVDB voxel size mode: {vox_size_mode}")


def _get_dataset_point_cloud_model(prim: Usd.Prim, instance_name: str, *, warn: bool = True) -> str | None:
    """
    Return the point-cloud data model API selected for ``instance_name``.

    Gaussian splatting and Voronoi point-cloud conversion are mutually exclusive
    point-cloud dataset models. If both are applied, USD's applied API schema
    order decides which one wins. Gaussian is only processed when voxelization is
    also applied, since its radius is derived from the voxel size.
    """
    matches = []
    for applied_schema in prim.GetAppliedSchemas():
        schema_name, sep, applied_instance = applied_schema.partition(":")
        if not sep or applied_instance != instance_name:
            continue
        if model := _POINT_CLOUD_DATA_MODEL_APIS.get(schema_name):
            matches.append((schema_name, model))

    # Fall back to HasAPI if applied-schema metadata is unexpectedly unavailable.
    if not matches:
        if prim.HasAPI(cae_viz.DatasetGaussianSplattingAPI, instance_name):
            matches.append(("CaeVizDatasetGaussianSplattingAPI", "gaussian"))
        if prim.HasAPI(cae_viz.DatasetVoronoiPointCloudAPI, instance_name):
            matches.append(("CaeVizDatasetVoronoiPointCloudAPI", "voronoi"))

    if len(matches) > 1 and warn:
        logger.warning(
            "Multiple point-cloud data model APIs are applied to %s for dataset instance '%s' (%s). "
            "Using %s because it appears first in the applied API schema order.",
            prim.GetPath(),
            instance_name,
            ", ".join(schema_name for schema_name, _ in matches),
            matches[0][0],
        )

    return matches[0][1] if matches else None


async def get_input_dataset(
    prim: Usd.Prim,
    instance_name: str,
    *,
    timeCode: Usd.TimeCode,
    device: str,
    needs_topology: bool = True,
    needs_geometry: bool = True,
    needs_fields: bool = True,
    required_fields: set[str] | None = None,
    field_associations: dict[str, simdata.AssociationType] | None = None,
) -> simdata.Dataset:
    """
    Returns the input dataset for the given instance name, applying any relevant API schemas on the prim
    for preparing the input dataset.

    This function automatically handles:
    - Loading the dataset specified by DatasetSelectionAPI
    - Applying DatasetGaussianSplattingAPI transformations (if present)
    - Applying DatasetVoronoiPointCloudAPI transformations (if present)
    - Applying DatasetVoxelizationAPI transformations (if present)
    - Applying DatasetTransformingAPI transformations (if present)
    - Loading all fields specified by FieldSelectionAPI instances
    - Converting selected fields to caller-required associations

    Caching:
    --------
    Results are cached based on prim path and instance name. The cache is automatically invalidated when:
    - The prim or any of its properties change
    - Any of the dataset prims change
    - The cache mode setting changes

    Note: The cache invalidation is prim-level. Any change to the prim (including unrelated properties)
    will invalidate the cache. This ensures correctness but may result in more cache misses than a
    fine-grained state-based approach.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to get the input dataset from
    instance_name : str
        The instance name of the DatasetSelectionAPI
    timeCode : Usd.TimeCode
        The time code to get the input dataset for
    device : str
        The device to get the input dataset for
    needs_topology : bool, optional
        Whether the caller needs access to dataset topology information, by default True
    needs_geometry : bool, optional
        Whether the caller needs access to dataset geometry information, by default True
    needs_fields : bool, optional
        Whether the caller needs access to dataset fields, by default True
    required_fields : set[str], optional
        A set of field selection instance names that are required; if fetching these fields fails, an exception is raised.
    field_associations : dict[str, simdata.AssociationType], optional
        Required output association for selected field instances. Node-to-element and
        element-to-node conversions use the corresponding Warp SimData averaging
        operator after the dataset pipeline has been applied.

    Returns
    -------
    simdata.Dataset
        The input dataset with all requested transformations and fields applied

    Raises
    ------
    ValueError
        If the prim does not have a DatasetSelectionAPI with the given instance name
    """
    if not prim.HasAPI(cae_viz.DatasetSelectionAPI, instance_name):
        raise ValueError(
            f"Prim {prim.GetPath()} does not have CaeVizDatasetSelectionAPI with instance name '{instance_name}'"
        )
    required_fields = set(required_fields or [])
    field_associations = dict(field_associations or {})
    supported_associations = {simdata.AssociationType.NODE, simdata.AssociationType.ELEMENT}
    invalid_associations = set(field_associations.values()) - supported_associations
    if invalid_associations:
        raise ValueError(f"Unsupported requested field associations: {invalid_associations}")
    if field_associations and not needs_fields:
        raise ValueError("field_associations requires needs_fields=True")

    # Compute effective topology/geometry requirements up front so the cache key reflects
    # the actual computation rather than the caller's (possibly weaker) request.
    has_transforming = prim.HasAPI(cae_viz.DatasetTransformingAPI, instance_name)
    point_cloud_model = _get_dataset_point_cloud_model(prim, instance_name)
    has_gaussian_point_cloud_model = point_cloud_model == "gaussian"
    has_voronoi_point_cloud_model = point_cloud_model == "voronoi"
    has_point_cloud_model = has_gaussian_point_cloud_model or has_voronoi_point_cloud_model
    has_voxelization = prim.HasAPI(cae_viz.DatasetVoxelizationAPI, instance_name)
    has_subset = prim.HasAPI(cae_viz.DatasetSubsetAPI, instance_name)

    if has_transforming or has_voronoi_point_cloud_model or (has_voxelization and has_gaussian_point_cloud_model):
        needs_geometry = True

    if has_voxelization and not has_point_cloud_model:
        # We need topology for voxelization to work, but not if a point-cloud data model is also applied.
        needs_topology = True

    if has_subset:
        # Subsetting operates on cells, so topology and geometry are both required.
        needs_topology = True
        needs_geometry = True

    if field_associations:
        # Association conversion traverses element topology in both directions.
        needs_topology = True

    # If a point-cloud data model is applied, needs_fields is true, and we have any non-vertex
    # centered fields, then we need topology.
    if (has_voronoi_point_cloud_model or (has_voxelization and has_gaussian_point_cloud_model)) and (
        not needs_topology
    ):
        # TODO: make this actually check for non-vertex centered fields
        needs_topology = True

    dataset_prims = _get_selected_dataset_prims(prim, instance_name)
    logger.debug(
        "[cae.viz.utils][dataset] selected prim=%s instance=%s targets=%s time=%s",
        prim.GetPath(),
        instance_name,
        [str(p.GetPath()) for p in dataset_prims if p],
        timeCode,
    )
    _validate_selected_dataset_prim_types(dataset_prims)

    dual_requested = prim.HasAPI(cae_viz.DatasetDualAPI, instance_name)
    axisymmetric_options_authored = prim.HasAPI(cae_viz.DatasetAxisymmetricRepresentationAPI, instance_name)
    if dual_requested or axisymmetric_options_authored:
        if len(dataset_prims) != 1:
            raise usd_utils.QuietableException(
                "An authored dataset representation requires exactly one selected dataset."
            )

    try:
        representations = [
            cae_simdata.resolve_representation(dataset_prim, prim, instance_name, dual=dual_requested)
            for dataset_prim in dataset_prims
        ]
    except ValueError as exc:
        raise usd_utils.QuietableException(str(exc)) from exc

    if dual_requested or axisymmetric_options_authored:
        if not representations or representations[0] is None:
            request_name = "a dual" if dual_requested else "an axisymmetric"
            raise usd_utils.QuietableException(
                f"Dataset {dataset_prims[0].GetPath()} does not support {request_name} representation."
            )

    required_fields_key = ",".join(sorted(required_fields)) if needs_fields else ""
    field_associations_key = ",".join(
        f"{name}={association.name}" for name, association in sorted(field_associations.items())
    )
    cache_key = (
        f"[viz:get_input_dataset]::{instance_name}:{prim.GetPath()}::{device}::"
        f"{needs_topology}::{needs_geometry}::{needs_fields}::{required_fields_key}::"
        f"{field_associations_key}::{point_cloud_model or 'none'}::"
        f"{tuple(repr(representation) for representation in representations)}"
    )
    ds = cache.get(cache_key, timeCode=timeCode)
    if ds:
        logger.debug(
            "[cae.viz.utils][dataset] cache-hit prim=%s instance=%s time=%s device=%s key=%s",
            prim.GetPath(),
            instance_name,
            timeCode,
            device,
            cache_key,
        )
        return ds
    logger.debug(
        "[cae.viz.utils][dataset] cache-miss prim=%s instance=%s time=%s device=%s "
        "needs_topology=%s needs_geometry=%s needs_fields=%s required_fields=%s key=%s",
        prim.GetPath(),
        instance_name,
        timeCode,
        device,
        needs_topology,
        needs_geometry,
        needs_fields,
        sorted(required_fields),
        cache_key,
    )

    datasets = [
        (
            await cae_simdata.get_dataset(
                dataset_prim,
                timeCode,
                device=device,
                needs_topology=needs_topology,
                needs_geometry=needs_geometry,
                representation=representation,
            )
        ).shallow_copy()
        for dataset_prim, representation in zip(dataset_prims, representations)
        if dataset_prim
    ]
    try:
        dataset = simdata.DatasetCollection.from_datasets(datasets) if len(datasets) > 1 else datasets[0]
    except ValueError as exc:
        raise ValueError(
            f"Failed to create DatasetCollection from datasets for DatasetSelectionAPI at {prim.GetPath()} "
            f"with instance name '{instance_name}': {exc}"
        ) from exc

    if needs_fields:
        if len(datasets) > 1:
            raise NotImplementedError("Field selection from multiple datasets is not supported yet.")
        dataset = await _add_selected_fields(
            dataset,
            dataset_prims[0],
            prim,
            timeCode,
            required_fields,
            representation=representations[0],
        )

    if has_voronoi_point_cloud_model:
        dataset = await _process_dataset_voronoi_point_cloud(dataset, prim, instance_name, timeCode)
    elif has_gaussian_point_cloud_model and not has_voxelization:
        logger.warning(
            "Ignoring %s on %s for dataset instance '%s' because Gaussian splatting requires "
            "CaeVizDatasetVoxelizationAPI to derive a voxel-sized splat radius.",
            "CaeVizDatasetGaussianSplattingAPI",
            prim.GetPath(),
            instance_name,
        )
    if has_subset:
        dataset = await _process_dataset_subset(dataset, prim, instance_name, timeCode)
    if has_voxelization:
        voxelization_point_cloud_model = "gaussian" if has_gaussian_point_cloud_model else None
        dataset = await _process_dataset_voxelization(
            dataset, prim, instance_name, timeCode, voxelization_point_cloud_model
        )
    if has_transforming:
        dataset = await _process_dataset_transforming(dataset, prim, instance_name, timeCode)

    for field_name, requested_association in field_associations.items():
        if not dataset.has_field(field_name):
            continue
        field = dataset.get_field(field_name)
        if field.association == requested_association:
            continue
        if requested_association == simdata.AssociationType.NODE:
            with progress.ProgressContext("Executing SimData [node_field]"):
                dataset = simdata_node_field.compute(dataset, field_name, output_field_name=field_name)
        else:
            with progress.ProgressContext("Executing SimData [element_field]"):
                dataset = simdata_element_field.compute(dataset, field_name, output_field_name=field_name)

    prim_watches = []
    # if any dataset prim changes, this cache becomes invalid.
    prim_watches.extend(cache.PrimWatch(p) for p in dataset_prims)
    # if the prim itself is deleted or its schema composition changes (API added/removed), this cache becomes invalid.
    prim_watches.append(cache.PrimWatch(prim, on="delete"))
    prim_watches.append(cache.PrimWatch(prim, on="resync"))
    # if any dataset-pipeline schema property changes, this cache becomes invalid.
    prim_watches.append(
        cache.PrimWatch(
            prim,
            on="any",
            schemas=[
                (cae_viz.DatasetSelectionAPI, instance_name),
                (cae_viz.DatasetAxisymmetricRepresentationAPI, instance_name),
                (cae_viz.DatasetDualAPI, instance_name),
                (cae_viz.DatasetTransformingAPI, instance_name),
                (cae_viz.DatasetGaussianSplattingAPI, instance_name),
                (cae_viz.DatasetVoronoiPointCloudAPI, instance_name),
                (cae_viz.DatasetVoxelizationAPI, instance_name),
                (cae_viz.DatasetSubsetAPI, instance_name),
            ],
        )
    )
    if needs_fields:
        # if any field selection property changes, this cache becomes invalid.
        for field_inst in usd_utils.get_instances(prim, "CaeVizFieldSelectionAPI"):
            prim_watches.append(cache.PrimWatch(prim, on="any", schemas=[(cae_viz.FieldSelectionAPI, field_inst)]))
            field_api = cae_viz.FieldSelectionAPI(prim, field_inst)
            field_prims = usd_utils.get_target_prims(
                field_api.GetPrim(), field_api.GetTargetRel().GetName(), quiet=True
            )
            prim_watches.extend(cache.PrimWatch(p) for p in field_prims)
    # Subset/Voxelization derive their box from the ROI prim's world transform. The schema watches
    # above catch roi-rel retargeting but not xform edits on the ROI itself, so watch the ROI prim
    # directly. on="any" covers xformOp:* updates as well as geometry-defining attrs (extent, size,
    # points) on the ROI prim.
    if has_subset:
        subset_api = cae_viz.DatasetSubsetAPI(prim, instance_name)
        roi_prim = usd_utils.get_target_prim(prim, subset_api.GetRoiRel().GetName(), quiet=True)
        if roi_prim and roi_prim.IsValid():
            prim_watches.append(cache.PrimWatch(roi_prim, on="any"))
    if has_voxelization:
        nvdb_api = cae_viz.DatasetVoxelizationAPI(prim, instance_name)
        roi_prim = usd_utils.get_target_prim(prim, nvdb_api.GetRoiRel().GetName(), quiet=True)
        if roi_prim and roi_prim.IsValid():
            prim_watches.append(cache.PrimWatch(roi_prim, on="any"))
    cache.put_ex(cache_key, dataset, prims=prim_watches, timeCode=timeCode)
    return dataset


async def _process_dataset_transforming(
    dataset: simdata.Dataset, prim: Usd.Prim, instance_name: str, timeCode: Usd.TimeCode
) -> simdata.Dataset:
    """
    Processes the dataset transforming API on the dataset.

    Parameters
    ----------
    dataset : simdata.Dataset
        The dataset to process
    prim : Usd.Prim
        The prim to process
    instance_name : str
    """
    assert prim.HasAPI(
        cae_viz.DatasetTransformingAPI, instance_name
    ), f"Prim {prim.GetPath()} does not have CaeVizDatasetTransformingAPI with instance name '{instance_name}'"
    transforming_api = cae_viz.DatasetTransformingAPI(prim, instance_name)
    return dataset


async def _process_dataset_subset(
    dataset: simdata.Dataset, prim: Usd.Prim, instance_name: str, timeCode: Usd.TimeCode
) -> simdata.Dataset:
    """
    Processes the dataset subset API on the dataset by selecting cells whose
    geometry relates to the ROI's axis-aligned bounds according to the API's
    'mode' attribute. Uses the element_in_box operator to build the subset.
    """
    assert prim.HasAPI(
        cae_viz.DatasetSubsetAPI, instance_name
    ), f"Prim {prim.GetPath()} does not have CaeVizDatasetSubsetAPI with instance name '{instance_name}'"

    subset_api = cae_viz.DatasetSubsetAPI(prim, instance_name)
    roi_prim = usd_utils.get_target_prim(prim, subset_api.GetRoiRel().GetName(), quiet=True)
    if roi_prim is None:
        logger.info("No ROI specified for DatasetSubsetAPI on %s; skipping subsetting.", prim.GetPath())
        return dataset

    roi_bounds = usd_utils.get_bounds(roi_prim, timeCode, quiet=True)
    if not roi_bounds or roi_bounds.IsEmpty():
        logger.info("ROI for DatasetSubsetAPI on %s has empty bounds; skipping subsetting.", prim.GetPath())
        return dataset

    inflate_bounds = subset_api.GetInflateBoundsAttr().Get(timeCode)
    if inflate_bounds and inflate_bounds > 0:
        bounds_min = np.array(roi_bounds.GetMin(), dtype=np.float32)
        bounds_max = np.array(roi_bounds.GetMax(), dtype=np.float32)
        inflation = (bounds_max - bounds_min) * inflate_bounds * 0.01
        bounds_min -= inflation * 0.5
        bounds_max += inflation * 0.5
        roi_bounds = Gf.Range3d(Gf.Vec3d(*bounds_min.tolist()), Gf.Vec3d(*bounds_max.tolist()))

    mode = subset_api.GetModeAttr().Get(timeCode)
    box_min = wp.vec3f(*roi_bounds.GetMin())
    box_max = wp.vec3f(*roi_bounds.GetMax())
    with progress.ProgressContext("Executing SimData [element_in_box]"):
        indices = simdata_element_in_box.compute_indices(dataset, box_min, box_max, mode=mode)
    ds = simdata_data_models_element_subset.create_dataset(dataset, indices)
    ds.add_field("element_idx", simdata.Field.from_array(indices, association=simdata.AssociationType.ELEMENT))
    ds = cae_simdata.pass_fields(dataset, ds, exclude_fields={"element_idx"})
    ds.remove_field("element_idx")
    return ds


async def _add_dataset_fields_as_node_fields(
    source_dataset: simdata.Dataset, point_dataset: simdata.Dataset
) -> simdata.Dataset:
    """Copy all fields from ``source_dataset`` onto ``point_dataset`` as node fields."""
    for field_name in source_dataset.get_field_names():
        with progress.ProgressContext("Executing SimData [node_field]"):
            tmp_dataset = simdata_node_field.compute(source_dataset, field_name, output_field_name="_node_field")
        point_dataset.add_field(field_name, tmp_dataset.get_field("_node_field"))
    return point_dataset


async def _process_dataset_gaussian_splatting(
    dataset: simdata.Dataset, prim: Usd.Prim, instance_name: str, timeCode: Usd.TimeCode, voxel_size: wp.vec3f
) -> simdata.Dataset:
    """
    Processes the dataset gaussian splatting API on the dataset.

    Parameters
    ----------
    dataset : simdata.Dataset
        The dataset to process
    prim : Usd.Prim
        The prim to process
    instance_name : str
    voxel_size : wp.vec3f
        The voxel size to use for the gaussian splatting
    """
    assert prim.HasAPI(
        cae_viz.DatasetGaussianSplattingAPI, instance_name
    ), f"Prim {prim.GetPath()} does not have CaeVizDatasetGaussianSplattingAPI with instance name '{instance_name}'"
    api = cae_viz.DatasetGaussianSplattingAPI(prim, instance_name)
    radius_factor = api.GetRadiusFactorAttr().Get(timeCode)
    radius = radius_factor * min(voxel_size)
    logger.info(f"Gaussian splatting radius: {radius:.3f}")
    sharpness = api.GetSharpnessAttr().Get(timeCode)
    with progress.ProgressContext("Executing SimData [node_splats]"):
        splatted_dataset = simdata_node_splats.compute(dataset, radius, sharpness)
    return await _add_dataset_fields_as_node_fields(dataset, splatted_dataset)


async def _process_dataset_voronoi_point_cloud(
    dataset: simdata.Dataset, prim: Usd.Prim, instance_name: str, timeCode: Usd.TimeCode
) -> simdata.Dataset:
    """
    Processes the dataset Voronoi point-cloud API on the dataset.

    Each source point becomes a Voronoi seed with one implicit logical cell.
    """
    assert prim.HasAPI(
        cae_viz.DatasetVoronoiPointCloudAPI, instance_name
    ), f"Prim {prim.GetPath()} does not have CaeVizDatasetVoronoiPointCloudAPI with instance name '{instance_name}'"

    logger.info("Converting dataset to Voronoi point cloud")
    with progress.ProgressContext("Executing SimData [node_splats]"):
        point_dataset = simdata_node_splats.compute(dataset, radius=0.0, sharpness=1.0)
    with progress.ProgressContext("Creating SimData [voronoi_point_cloud]"):
        voronoi_dataset = simdata_data_models_voronoi_point_cloud.create_dataset(point_dataset.handle.points)
    return await _add_dataset_fields_as_node_fields(dataset, voronoi_dataset)


async def _process_dataset_voxelization(
    dataset: simdata.Dataset, prim: Usd.Prim, instance_name: str, timeCode: Usd.TimeCode, point_cloud_model: str | None
) -> simdata.Dataset:
    """
    Processes the dataset voxelization API on the dataset.

    Parameters
    ----------
    dataset : simdata.Dataset
        The dataset to process
    prim : Usd.Prim
        The prim to process
    instance_name : str
    """
    # If no point-cloud conversion is needed and every field is already a NanoVDB
    # volume, skip the entire voxelization pipeline.
    if point_cloud_model is None:
        field_names = dataset.get_field_names()
        if field_names and all(isinstance(dataset.get_field(fn).get_data(), wp.Volume) for fn in field_names):
            logger.info(f"Skipping voxelization for dataset at {prim.GetPath()} since all fields are already volumes")
            return dataset

    with progress.ProgressContext("Executing SimData [compute bounds]"):
        data_bounds = dataset.get_bounds()
    data_bounds_r3d = Gf.Range3d(
        (data_bounds[0][0], data_bounds[0][1], data_bounds[0][2]),
        (data_bounds[1][0], data_bounds[1][1], data_bounds[1][2]),
    )
    vox_params = _get_voxelization_parameters(prim, instance_name, data_bounds_r3d, timeCode)

    if point_cloud_model == "gaussian":
        # We need to voxelize the dataset after Gaussian splatting.
        dataset = await _process_dataset_gaussian_splatting(
            dataset, prim, instance_name, timeCode, vox_params.voxel_size
        )
    elif point_cloud_model == "voronoi":
        # We need to voxelize the dataset after Voronoi point-cloud conversion.
        dataset = await _process_dataset_voronoi_point_cloud(dataset, prim, instance_name, timeCode)
    elif point_cloud_model is not None:
        raise ValueError(f"Unsupported point-cloud data model: {point_cloud_model}")

    voxelized_dataset = None
    for field_name in dataset.get_field_names():
        # TODO process CaeFieldThresholdingAPI on the field to customize tiles for the generated NanoVDB field.
        with progress.ProgressContext("Executing SimData [voxelization]"):
            vds = simdata_voxelization.compute(
                dataset,
                field_name,
                min_ijk=vox_params.min_ijk,
                max_ijk=vox_params.max_ijk,
                voxel_size=vox_params.voxel_size,
                use_nanovdb=True,
                output_field_name=field_name,
                output_mask_field_name="cae_mask" if voxelized_dataset is None else None,
                output_association=_get_voxelization_output_association(vox_params.field_centering),
            )
        if voxelized_dataset is None:
            voxelized_dataset = vds
        else:
            voxelized_dataset.add_field(field_name, vds.get_field(field_name))

    if voxelized_dataset is None:
        logger.info(f"No fields were voxelized for dataset at {prim.GetPath()}")

        # So we need to create a voxel grid without any fields.
        result_extent_max = (
            vox_params.max_ijk + wp.vec3i(1, 1, 1) if vox_params.field_centering == "cell" else vox_params.max_ijk
        )
        voxelized_dataset = simdata_data_models_vtk_image_data.create_dataset(
            origin=wp.vec3f(0.0),
            spacing=wp.vec3f(*vox_params.voxel_size),
            extent_min=vox_params.min_ijk,
            extent_max=result_extent_max,
            device=dataset.device,
        )

    return voxelized_dataset


def set_array_attribute(attr: UsdRT.Attribute, array: array_utils.FieldArrayLike) -> None:
    """
    Sets the attribute value to the given array.
    """
    typename = attr.GetTypeName()
    assert typename.isArray, f"Attribute {attr.GetPath()} is not an array"
    scalar_type = typename.scalarType
    if scalar_type in [SdfRT.ValueTypeNames.Point3f, SdfRT.ValueTypeNames.Vector3f, SdfRT.ValueTypeNames.Float3]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float32), VtRT.Vec3fArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Point3d, SdfRT.ValueTypeNames.Vector3d, SdfRT.ValueTypeNames.Double3]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float64), VtRT.Vec3dArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Float2]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float32), VtRT.Vec2fArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Double2]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float64), VtRT.Vec2dArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Quatf, SdfRT.ValueTypeNames.Float4]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float32), VtRT.Vec4fArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Quatd, SdfRT.ValueTypeNames.Double4]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float64), VtRT.Vec4dArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Quath]:
        # Manually handle here, since we can't use _set_array_attribute because there's
        # no as_type() for half-floats.
        vt_array = VtRT.QuathArray(array_utils.as_numpy_array(array))
        attr.Set(vt_array)
    elif scalar_type in [SdfRT.ValueTypeNames.Float]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float32), VtRT.FloatArray)
    elif scalar_type in [SdfRT.ValueTypeNames.Double]:
        _set_array_attribute(attr, array_utils.as_type(array, np.float64), VtRT.DoubleArray)
    elif scalar_type == SdfRT.ValueTypeNames.Int:
        _set_array_attribute(attr, array_utils.as_type(array, np.int32), VtRT.IntArray)
    elif scalar_type == SdfRT.ValueTypeNames.Int64:
        _set_array_attribute(attr, array_utils.as_type(array, np.int64), VtRT.Int64Array)
    elif scalar_type == SdfRT.ValueTypeNames.UInt:
        _set_array_attribute(attr, array_utils.as_type(array, np.uint32), VtRT.UIntArray)
    elif scalar_type == SdfRT.ValueTypeNames.UInt64:
        _set_array_attribute(attr, array_utils.as_type(array, np.uint64), VtRT.UInt64Array)
    elif scalar_type == SdfRT.ValueTypeNames.Int2:
        _set_array_attribute(attr, array_utils.as_type(array, np.int32), VtRT.Vec2iArray)
    elif scalar_type == SdfRT.ValueTypeNames.Int3:
        _set_array_attribute(attr, array_utils.as_type(array, np.int32), VtRT.Vec3iArray)
    elif scalar_type == SdfRT.ValueTypeNames.Int4:
        _set_array_attribute(attr, array_utils.as_type(array, np.int32), VtRT.Vec4iArray)
    else:
        raise ValueError(f"Unsupported scalar type {scalar_type} for attribute {attr.GetPath()}")


def _set_array_attribute(attr: UsdRT.Attribute, array: array_utils.FieldArrayLike, attr_type) -> None:
    """
    Sets the attribute value to the given UsdRT.Array.
    """
    vt_array, _vt_buffer = array_utils.to_vtrt_array_with_buffer(array)
    # Keep the backing buffer alive until Set() copies it. This matters for
    # Windows int/uint arrays, where we pass a zero-copy intc/uintc view to
    # satisfy VtRT's strict buffer format check.
    attr.Set(vt_array)
    # attr.SyncDataToGpu()


def get_temporal_traits(prim: Usd.Prim, instance_name: str, attr_name: str) -> str:
    """
    Utility to get the temporal traits of a given attribute on a prim. This is used to determine whether
    we need to fetch topology/geometry information for a given prim when processing it.

    Parameters
    ----------
    prim : Usd.Prim
        The prim to get the temporal traits from
    instance_name : str
        The name of the API schema instance that contains the attribute
    attr_name : str
        The name of the attribute to get the temporal traits for
    Returns
    -------
    str
        The temporal traits of the attribute (e.g., "static", "varying", "undefined")
    """

    if not prim.HasAPI(cae_viz.DatasetTemporalTraitsAPI):
        return "undefined"

    temp_char_api = cae_viz.DatasetTemporalTraitsAPI(prim, instance_name)
    if attr_name == "topology":
        return temp_char_api.GetTopologyAttr().Get()
    elif attr_name == "geometry":
        return temp_char_api.GetGeometryAttr().Get()
    else:
        raise ValueError(
            f"Unsupported attribute name '{attr_name}' for temporal traits. Supported attributes are 'topology' and 'geometry'."
        )


def write_glyph_display_color(prim: Usd.Prim, dataset: simdata.Dataset) -> None:
    """Assign each glyph instance to a prototype bin based on the ``colors`` field.

    Per-instance color on a ``PointInstancer`` cannot be delivered via per-instance
    primvars because the RTX renderer does not forward them into the prototype's
    MDL shader context. Instead, the Glyphs operator authors N prototype Xforms
    each carrying a constant grayscale ``primvars:displayColor = (i/(N-1),)*3``;
    the bound MDL ScalarColor shader extracts the scalar via ``math::luminance``
    and does the LUT lookup at render time. This function computes the
    per-instance ``protoIndices`` array that selects the prototype bin from the
    normalised field value.

    LUT changes require no recomputation here (the shader re-samples at render
    time). Domain and ``colors``-field value changes require recomputing the
    bins, which happens on operator re-execution.

    Silent no-ops:
      * ``prim`` is not a ``PointInstancer``.
      * The dataset has no ``colors`` field.
      * Fewer than two prototypes are bound (operator predates the multi-proto
        layout — logs a warning telling the user to recreate the operator).
    """
    if not prim.IsA(UsdGeom.PointInstancer):
        return
    if not dataset.has_field("colors"):
        return

    instancer = UsdGeom.PointInstancer(prim)
    proto_targets = instancer.GetPrototypesRel().GetForwardedTargets()
    num_protos = len(proto_targets)
    if num_protos < 2:
        logger.warning(
            "Glyphs prim %s has %d prototype(s); per-instance coloring requires the "
            "multi-prototype layout. Recreate the Glyphs operator to enable coloring.",
            prim.GetPath(),
            num_protos,
        )
        return

    material_binding = UsdShade.MaterialBindingAPI(prim)
    material = material_binding.ComputeBoundMaterial()[0]
    shader = None
    if material:
        source = material.ComputeSurfaceSource("mdl")
        shader = source[0] if source else None
    if not shader:
        return

    enable_input = shader.GetInput("enable_coloring")
    domain_input = shader.GetInput("domain")
    enable_coloring = bool(enable_input.Get()) if enable_input else False
    domain = domain_input.Get() if domain_input else None

    # Self-heal: legacy operators created before use_vertex_color existed still
    # need it toggled on to route through the multi-prototype path.
    use_vertex_color_input = shader.GetInput("use_vertex_color") or shader.CreateInput(
        "use_vertex_color", Sdf.ValueTypeNames.Bool
    )
    if use_vertex_color_input.Get() is not True:
        use_vertex_color_input.Set(True)

    prim_rt = UsdGeomRT.PointInstancer(usd_utils.get_prim_rt(prim))
    num_instances = dataset.get_num_nodes()

    if not enable_coloring or domain is None or not (domain[0] < domain[1]):
        # Coloring disabled or degenerate domain: route every instance to prototype 0.
        proto_indices = np.zeros((num_instances, 1), dtype=np.int32)
        set_array_attribute(prim_rt.CreateProtoIndicesAttr(), proto_indices)
        return

    f_array = cae_simdata.fetch_data(dataset, "colors")
    arr = array_utils.as_numpy_array(f_array)
    if arr.ndim > 1 and arr.shape[1] > 1:
        # Match RescaleRangeAPI: reduce vector fields to magnitude for coloring.
        arr = np.linalg.norm(arr, axis=1)
    else:
        arr = arr.reshape(-1)

    d_min = float(domain[0])
    d_max = float(domain[1])
    t = np.clip((arr - d_min) / (d_max - d_min), 0.0, 1.0)
    proto_indices = np.clip(np.floor(t * num_protos).astype(np.int32), 0, num_protos - 1)
    proto_indices = proto_indices.reshape(-1, 1)
    set_array_attribute(prim_rt.CreateProtoIndicesAttr(), proto_indices)
