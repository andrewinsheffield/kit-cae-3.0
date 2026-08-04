# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Planar surface extraction backed by ``warp_simdata.operators.slice``."""

import hashlib
from logging import getLogger

import numpy as np
from omni.cae.core import cache, progress, usd_utils
from omni.cae.schema import viz as cae_viz
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
from usdrt import Gf as GfRt
from usdrt import Rt
from usdrt import Sdf as SdfRt
from usdrt import UsdGeom as UsdGeomRt
from usdrt import Vt as VtRt
from warp_simdata.operators import slice as simdata_slice

from . import utils as viz_utils
from .create_commands import bind_material, create_material, get_surface_shader, setup_mdl_colormap, setup_mdl_opacity
from .execution_context import ExecutionContext
from .faces import populate_surface_mesh
from .operator import operator

logger = getLogger(__name__)

_OUTPUT_ROOT = SdfRt.Path("/CaePlanarSlice")
_OUTPUT_BUFFER_COUNT = 2
_PLANE_SLOT_COUNT = 3
_COLOR_FIELD = "colors"
_OPACITY_FIELD = "opacity"
_MATERIAL_NAME = "UnlitScalarColor"
_MODE_PLANES: dict[str, tuple[tuple[int, str], ...]] = {
    "free": ((0, ""),),
    "x": ((0, "x"),),
    "y": ((1, "y"),),
    "z": ((2, "z"),),
    "xy": ((0, "x"), (1, "y")),
    "xz": ((0, "x"), (2, "z")),
    "yz": ((1, "y"), (2, "z")),
    "xyz": ((0, "x"), (1, "y"), (2, "z")),
}
_AXIS_NORMALS: dict[str, np.ndarray] = {
    "x": np.array([1.0, 0.0, 0.0]),
    "y": np.array([0.0, 1.0, 0.0]),
    "z": np.array([0.0, 0.0, 1.0]),
}


def _compute_plane(xform) -> tuple[np.ndarray, np.ndarray]:
    """Return the plane origin and unit normal represented by ``xform``."""
    matrix = np.asarray(xform, dtype=np.float64)
    origin = matrix[3, :3]
    normal = matrix[1, :3]
    normal_length = np.linalg.norm(normal)
    if not np.isfinite(normal_length) or normal_length == 0.0:
        raise usd_utils.QuietableException("Planar slice transform has an invalid +Y axis")
    return origin, normal / normal_length


def _output_path(prim_path: str, plane_slot: int, buffer_slot: int) -> SdfRt.Path:
    digest = hashlib.sha512(prim_path.encode()).hexdigest()[:8]
    return SdfRt.Path(f"{_OUTPUT_ROOT}/slice_{digest}_{plane_slot}_{buffer_slot}")


def _output_paths(prim_path: str) -> list[SdfRt.Path]:
    return [
        _output_path(prim_path, plane_slot, buffer_slot)
        for plane_slot in range(_PLANE_SLOT_COUNT)
        for buffer_slot in range(_OUTPUT_BUFFER_COUNT)
    ]


def _plane_center_and_normal(axis: str, local_matrix) -> tuple[np.ndarray, np.ndarray]:
    """Return the shared plane center and either the free or cardinal normal."""
    if not axis:
        return _compute_plane(local_matrix)
    return np.asarray(local_matrix, dtype=np.float64)[3, :3], _AXIS_NORMALS[axis]


def _set_output_visibility(output_prim, visible: bool) -> None:
    output_prim.CreateAttribute("_worldVisibility", SdfRt.ValueTypeNames.Bool).Set(visible)
    UsdGeomRt.Mesh(output_prim).CreateVisibilityAttr().Set(
        UsdGeomRt.Tokens.inherited if visible else UsdGeomRt.Tokens.invisible
    )


def _prepare_output_prim(rt_stage, output_path: SdfRt.Path, material_path: Sdf.Path):
    """Create one transform-independent RT mesh used as a geometry buffer."""
    if not rt_stage.GetPrimAtPath(_OUTPUT_ROOT):
        rt_stage.DefinePrim(_OUTPUT_ROOT, "Scope")

    output_prim = rt_stage.GetPrimAtPath(output_path)
    created = not output_prim
    if created:
        output_prim = rt_stage.DefinePrim(output_path, "Mesh")
    boundable = Rt.Boundable(output_prim)
    output_prim.CreateAttribute("purpose", SdfRt.ValueTypeNames.Token, False).Set(UsdGeomRt.Tokens.default_)
    UsdGeomRt.Mesh(output_prim).CreateDoubleSidedAttr().Set(True)
    if created:
        boundable.CreateFabricHierarchyLocalMatrixAttr().Set(GfRt.Matrix4d(1.0))
        boundable.CreateFabricHierarchyWorldMatrixAttr().Set(GfRt.Matrix4d(1.0))
        # Fabric's Hydra delegate only discovers meshes with valid topology.
        # Seed each hidden buffer before its first real slice is available.
        output_mesh = UsdGeomRt.Mesh(output_prim)
        output_mesh.CreatePointsAttr().Set(VtRt.Vec3fArray([(0.0, 0.0, 0.0)] * 3))
        output_mesh.CreateFaceVertexCountsAttr().Set(VtRt.IntArray([3]))
        output_mesh.CreateFaceVertexIndicesAttr().Set(VtRt.IntArray([0, 1, 2]))
        boundable.CreateWorldExtentAttr().Set(GfRt.Range3d(GfRt.Vec3d(0.0), GfRt.Vec3d(0.0)))
        _set_output_visibility(output_prim, False)

    output_prim.CreateRelationship("material:binding").SetTargets([SdfRt.Path(str(material_path))])
    return output_prim


def _set_output_parent_transform(
    output_prim,
    prim: Usd.Prim,
    xform_cache: UsdGeom.XformCache,
) -> Gf.Matrix4d:
    """Place the flat RT output mesh in the control prim's parent space."""
    parent = prim.GetParent()
    parent_transform = Gf.Matrix4d(1.0)
    if parent and parent.IsValid() and not parent.IsPseudoRoot():
        parent_transform = xform_cache.GetLocalToWorldTransform(parent)
    matrix = np.asarray(parent_transform, dtype=np.float64)
    Rt.Boundable(output_prim).CreateFabricHierarchyLocalMatrixAttr().Set(GfRt.Matrix4d(*matrix.flatten().tolist()))
    return parent_transform


def _update_output_extent(output_prim, surface_dataset, parent_transform: Gf.Matrix4d) -> None:
    bounds = surface_dataset.get_bounds()
    local_extent = Gf.Range3d(Gf.Vec3d(*bounds[0]), Gf.Vec3d(*bounds[1]))
    world_extent = Gf.BBox3d(local_extent, parent_transform).ComputeAlignedRange()
    Rt.Boundable(output_prim).CreateWorldExtentAttr().Set(
        GfRt.Range3d(
            GfRt.Vec3d(*world_extent.GetMin()),
            GfRt.Vec3d(*world_extent.GetMax()),
        )
    )


def _ensure_slice_material(prim: Usd.Prim) -> Usd.Prim:
    """Create and bind the geometry material, including for older authored stages."""
    slice_material = prim.GetChild("Materials").GetChild(_MATERIAL_NAME)
    if not slice_material:
        slice_material = create_material(
            _MATERIAL_NAME,
            prim.GetStage(),
            prim.GetPath().AppendChild("Materials").AppendChild(_MATERIAL_NAME),
        )
        setup_mdl_colormap(slice_material, "cae/colormaps/gist_rainbow.png")

    setup_mdl_opacity(slice_material, prim)

    if shader := get_surface_shader(slice_material, "mdl"):
        domain_attr = shader.CreateInput("domain", Sdf.ValueTypeNames.Float2)
        if domain_attr.Get() is None:
            domain_attr.Set((0, -1))
        includes_rel = cae_viz.RescaleRangeAPI(prim, "colors").CreateIncludesRel()
        domain_path = domain_attr.GetAttr().GetPath()
        if domain_path not in includes_rel.GetTargets():
            includes_rel.AddTarget(domain_path)

    bound_material = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
    if not bound_material or bound_material.GetPrim().GetPath() != slice_material.GetPath():
        bind_material(UsdGeom.Mesh(prim), slice_material)
    return slice_material


@operator()
class PlanarSlice:
    """Extract and render the surface where a transform-defined plane crosses a volume."""

    prim_type: str = "Mesh"
    api_schemas: set[str] = {
        "CaeVizOperatorAPI",
        "CaeVizPlanarSliceAPI",
        "CaeVizDatasetSelectionAPI:source",
        "CaeVizDatasetTransformingAPI:self",
        "CaeVizFieldSelectionAPI:colors",
    }
    optional_api_schemas: set[str] = {
        "CaeVizDatasetAxisymmetricRepresentationAPI:source",
        "CaeVizDatasetDualAPI:source",
        "CaeVizDatasetTemporalTraitsAPI:source",
        "CaeVizDatasetVoxelizationAPI:source",
        "CaeVizFieldMappingAPI",
        "CaeVizRescaleRangeAPI",
    }

    def deactivate(self, prim: Usd.Prim) -> None:
        prim_rt = usd_utils.get_prim_rt(prim)
        rt_stage = prim_rt.GetStage()
        for path in _output_paths(prim.GetPath().pathString):
            if output_prim := rt_stage.GetPrimAtPath(path):
                _set_output_visibility(output_prim, False)

    async def exec(self, prim: Usd.Prim, device: str, context: ExecutionContext):
        prim_path = prim.GetPath().pathString
        output_paths = _output_paths(prim_path)
        prim_rt = usd_utils.get_prim_rt(prim)
        rt_stage = prim_rt.GetStage()
        slice_material = _ensure_slice_material(prim)
        output_prims = {
            (plane_slot, buffer_slot): _prepare_output_prim(
                rt_stage,
                _output_path(prim_path, plane_slot, buffer_slot),
                slice_material.GetPath(),
            )
            for plane_slot in range(_PLANE_SLOT_COUNT)
            for buffer_slot in range(_OUTPUT_BUFFER_COUNT)
        }
        viz_utils.RtSubPrimGuard.register(prim, rt_stage, output_paths)

        # The authored mesh is a transform handle. Geometry is published through
        # the RT output buffers so interactive transform edits cannot move stale
        # slice geometry while a replacement is being computed.
        control_mesh_rt = UsdGeomRt.Mesh(prim_rt)
        control_mesh_rt.CreateVisibilityAttr().Set(UsdGeomRt.Tokens.invisible)

        source_dataset = await viz_utils.get_input_dataset(
            prim,
            "source",
            timeCode=context.timecode,
            device=device,
            required_fields={_COLOR_FIELD},
        )
        if not source_dataset.has_field(_COLOR_FIELD):
            raise usd_utils.QuietableException("No colors field selected for planar slice")
        output_fields = [_COLOR_FIELD]
        if source_dataset.has_field(_OPACITY_FIELD):
            output_fields.append(_OPACITY_FIELD)

        viz_utils.process_rescale_range_apis(prim, source_dataset)

        xform_cache = UsdGeom.XformCache(context.timecode)
        local_matrix, _ = xform_cache.GetLocalTransformation(prim)
        mode = cae_viz.PlanarSliceAPI(prim).GetModeAttr().Get() or "free"
        if mode not in _MODE_PLANES:
            logger.warning("Unknown planar-slice direction %r; using 'free'", mode)
        active_planes = _MODE_PLANES.get(mode, _MODE_PLANES["free"])

        logger.info(
            "[cae.viz.slice] computing prim=%s time=%s device=%s mode=%s",
            prim.GetPath(),
            context.timecode,
            device,
            mode,
        )

        active_key = f"omni.cae.viz.slice.PlanarSlice:active-buffer:{prim_path}"
        active_slot = cache.get(active_key)
        target_slot = 0 if active_slot not in range(_OUTPUT_BUFFER_COUNT) else (active_slot + 1) % _OUTPUT_BUFFER_COUNT
        populated_plane_slots: set[int] = set()
        with progress.ProgressContext("Executing SimData [slice]"):
            plane_requests = [
                (plane_slot, *_plane_center_and_normal(axis, local_matrix)) for plane_slot, axis in active_planes
            ]
            with viz_utils.log_runtime_warnings(logger, "SimData slice"):
                surface_datasets = simdata_slice.compute_many(
                    source_dataset,
                    origins=[origin for _, origin, _ in plane_requests],
                    normals=[normal for _, _, normal in plane_requests],
                    field_names=output_fields,
                )
            for (plane_slot, _, _), surface_dataset in zip(
                plane_requests,
                surface_datasets,
                strict=True,
            ):
                if surface_dataset.get_num_nodes() == 0 or surface_dataset.get_num_elems() == 0:
                    continue

                target_prim = output_prims[plane_slot, target_slot]
                await populate_surface_mesh(
                    prim,
                    surface_dataset,
                    exclude_fields={"element_idx"},
                    output_prim_rt=target_prim,
                )
                parent_transform = _set_output_parent_transform(target_prim, prim, xform_cache)
                _update_output_extent(target_prim, surface_dataset, parent_transform)
                populated_plane_slots.add(plane_slot)

        if not populated_plane_slots:
            for output_prim in output_prims.values():
                _set_output_visibility(output_prim, False)
            raise usd_utils.QuietableException("No planar slice generated")

        # Publish the completed buffer before retiring the previous one. Renderer
        # frames therefore see either the previous complete slice or the new one.
        for plane_slot in populated_plane_slots:
            target_prim = output_prims[plane_slot, target_slot]
            _set_output_visibility(target_prim, True)
        for plane_slot in range(_PLANE_SLOT_COUNT):
            for buffer_slot in range(_OUTPUT_BUFFER_COUNT):
                if plane_slot not in populated_plane_slots or buffer_slot != target_slot:
                    output_prim = output_prims[plane_slot, buffer_slot]
                    _set_output_visibility(output_prim, False)

        cache.put_ex(
            active_key,
            target_slot,
            prims=[cache.PrimWatch(prim, on="delete")],
            force=True,
        )
