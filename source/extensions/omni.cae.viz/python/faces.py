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
Faces operator for extracting and rendering cell faces from datasets.

This module provides the Faces operator which extracts all cell faces from a volumetric
dataset using the simdata.operators.element_faces operator and populates a UsdGeomMesh prim
with the resulting surface mesh.

The operator is similar to the Points operator but works with cell faces rather than points.
"""

from logging import getLogger
from typing import Any

import omni.cae.simdata as cae_simdata
import warp_simdata as simdata
from omni.cae.core import cache, progress, usd_utils
from omni.cae.schema import viz as cae_viz
from pxr import Usd
from usdrt import Usd as UsdRT
from usdrt import UsdGeom as UsdGeomRT
from usdrt import Vt as VtRT
from warp_simdata.data_models.custom import surface_mesh as simdata_surface_mesh
from warp_simdata.operators import element_faces as simdata_element_faces

from . import utils as viz_utils
from .execution_context import ExecutionContext
from .operator import operator

logger = getLogger(__name__)
import warp as wp


async def populate_surface_mesh(
    prim: Usd.Prim,
    surface_dataset: simdata.Dataset,
    update_points_attr: bool = True,
    update_faces_attrs: bool = True,
    update_primvars: bool = True,
    exclude_fields: set[str] | None = None,
    output_prim_rt: UsdRT.Prim | None = None,
):
    """Populate a UsdGeomMesh from a SimData surface-mesh dataset."""
    output_prim_rt = usd_utils.get_prim_rt(prim) if output_prim_rt is None else output_prim_rt
    prim_rt = UsdGeomRT.Mesh(output_prim_rt)

    if update_points_attr:
        viz_utils.set_array_attribute(prim_rt.CreatePointsAttr(), surface_dataset.handle.points)

    if update_faces_attrs:
        viz_utils.set_array_attribute(prim_rt.CreateFaceVertexCountsAttr(), surface_dataset.handle.face_vertex_counts)
        viz_utils.set_array_attribute(prim_rt.CreateFaceVertexIndicesAttr(), surface_dataset.handle.face_vertex_indices)

    if update_primvars:
        viz_utils.process_field_selection_apis(
            prim,
            surface_dataset,
            exclude_fields=exclude_fields,
            output_prim_rt=output_prim_rt,
        )


@operator()
class Faces:
    """
    Operator for extracting and rendering cell faces from volumetric datasets.

    This version does not handle temporal interpolation.
    """

    prim_type: str = "Mesh"
    api_schemas: set[str] = {
        "CaeVizFacesAPI",
        "CaeVizDatasetSelectionAPI:source",
        "CaeVizFieldSelectionAPI:colors",
    }

    optional_api_schemas: set[str] = {
        "CaeVizDatasetTemporalCharacteristicsAPI:source",
        "CaeVizFieldSelectionAPI",
        "CaeVizFieldMappingAPI",
    }

    async def _exec_internal(self, prim: Usd.Prim, device: str, context: ExecutionContext):
        source_dataset = await viz_utils.get_input_dataset(prim, "source", timeCode=context.timecode, device=device)
        external_only = cae_viz.FacesAPI(prim).GetExternalOnlyAttr().Get()

        if context.is_temporal_update():
            # for temporal update, we will attempt to skip unnecessary updates to
            # UsdGeom.Mesh prim if we have been provided some additional metadata.
            update_faces_attrs = viz_utils.get_temporal_traits(prim, "source", "topology") != "static"
            update_points_attr = viz_utils.get_temporal_traits(prim, "source", "geometry") != "static"
        else:
            # for non-temporal update (e.g. initial creation, or when we know we need a full rebuild), we will update everything
            update_faces_attrs = True
            update_points_attr = True

        logger.debug(
            "[cae.viz.faces][time] exec prim=%s reason=%s time=%s raw=%s next=%s device=%s "
            "source_model=%s external_only=%s update_points=%s update_faces=%s",
            prim.GetPath(),
            context.reason.value,
            context.timecode,
            context.raw_timecode,
            context.next_time_code,
            device,
            getattr(source_dataset, "data_model", None),
            external_only,
            update_points_attr,
            update_faces_attrs,
        )

        # Extract cell faces to create a surface mesh (if needed)
        cache_key = f"omni.cae.viz.faces.Faces:mesh:{prim.GetPath()}"

        # if updates are not needed, check if we have the faces data cached already and skip recomputation if so
        faces_dataset: simdata.Dataset | None = None
        if not (update_faces_attrs or update_points_attr):
            # we use earliest timecode on purpose.
            faces_dataset = cache.get(cache_key, timeCode=Usd.TimeCode.EarliestTime())
            logger.debug(
                "[cae.viz.faces][time] static-mesh-cache prim=%s hit=%s key=%s",
                prim.GetPath(),
                faces_dataset is not None,
                cache_key,
            )

        if faces_dataset is None:
            if source_dataset.data_model == simdata_surface_mesh.DataModel:
                logger.debug(
                    "[cae.viz.faces][time] using source surface mesh prim=%s time=%s",
                    prim.GetPath(),
                    context.timecode,
                )
                faces_dataset = source_dataset
            else:
                logger.info(
                    "[cae.viz.faces][time] computing element_faces prim=%s time=%s raw=%s external_only=%s",
                    prim.GetPath(),
                    context.timecode,
                    context.raw_timecode,
                    external_only,
                )
                with progress.ProgressContext("Executing SimData [element_faces]"):
                    faces_dataset = simdata_element_faces.compute(source_dataset, external_only=external_only)
            # we use earliest timecode on purpose.
            cache.put_ex(
                cache_key,
                faces_dataset,
                prims=[cache.PrimWatch(prim, on="resync")],
                timeCode=Usd.TimeCode.EarliestTime(),
            )
        else:
            logger.debug(
                "[cae.viz.faces][time] reusing cached surface mesh prim=%s time=%s",
                prim.GetPath(),
                context.timecode,
            )

        faces_dataset = cae_simdata.pass_fields(
            source_dataset, faces_dataset.shallow_copy(), exclude_fields={"element_idx", "node_idx"}
        )

        # Process rescale range APIs which depend on input dataset.
        viz_utils.process_rescale_range_apis(prim, source_dataset)
        return faces_dataset, update_points_attr, update_faces_attrs, True

    async def exec(self, prim: Usd.Prim, device: str, context: ExecutionContext):
        faces_dataset, update_points_attr, update_faces_attrs, update_primvars = await self._exec_internal(
            prim, device, context
        )
        await self.populate_mesh(
            prim, faces_dataset, update_points_attr, update_faces_attrs, update_primvars=update_primvars
        )

    async def populate_mesh(
        self,
        prim: Usd.Prim,
        faces_dataset: simdata.Dataset,
        update_points_attr: bool,
        update_faces_attrs: bool,
        update_primvars: bool,
    ):
        await populate_surface_mesh(
            prim,
            faces_dataset,
            update_points_attr,
            update_faces_attrs,
            update_primvars,
            exclude_fields={"element_idx", "node_idx"},
        )


@operator(supports_temporal=True, tick_on_time_change=True)
class FacesWithTemporalInterpolation(Faces):
    """
    Face operator with temporal interpolation support.
    """

    prim_type: str = "Mesh"
    api_schemas: set[str] = Faces.api_schemas.union(
        {
            "CaeVizOperatorTemporalAPI",
        }
    )
    optional_api_schemas: set[str] = Faces.optional_api_schemas

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._using_temporal_interpolation = False
        self._update_points_attr = True
        self._update_faces_attrs = True
        self._update_primvars = True

    async def exec(self, prim: Usd.Prim, device: str, context: ExecutionContext):
        self._using_temporal_interpolation = cae_viz.OperatorTemporalAPI(prim).GetEnableFieldInterpolationAttr().Get()
        if not self._using_temporal_interpolation:
            # If interpolation is not enabled, just execute the base implementation.
            return await super().exec(prim, device, context)

        faces_dataset, update_points_attr, update_faces_attrs, update_primvars = await self._exec_internal(
            prim, device, context
        )

        cache_key = f"omni.cae.viz.faces.FacesWithTemporalInterpolation:{prim.GetPath()}"
        if context.is_full_rebuild_needed():
            cache.remove(cache_key)

        # for temporal interpolation we force push cache.
        cache.put_ex(
            cache_key, faces_dataset, timeCode=context.timecode, prims=[cache.PrimWatch(prim, on="resync")], force=True
        )
        self._update_points_attr = update_points_attr
        self._update_faces_attrs = update_faces_attrs
        self._update_primvars = update_primvars

    async def on_time_changed(self, prim: Usd.Prim, device: str, context: ExecutionContext):
        cache_key = f"omni.cae.viz.faces.FacesWithTemporalInterpolation:{prim.GetPath()}"
        faces_dataset = cache.get(cache_key, timeCode=context.timecode)
        logger.debug(
            "[cae.viz.faces][time] tick prim=%s time=%s raw=%s next=%s current_cache_hit=%s",
            prim.GetPath(),
            context.timecode,
            context.raw_timecode,
            context.next_time_code,
            faces_dataset is not None,
        )
        if faces_dataset is None:
            return
        if context.next_time_code and context.next_time_code != context.timecode:
            next_faces_dataset = cache.get(cache_key, timeCode=context.next_time_code)
            logger.debug(
                "[cae.viz.faces][time] tick-next prim=%s next=%s next_cache_hit=%s",
                prim.GetPath(),
                context.next_time_code,
                next_faces_dataset is not None,
            )
            if next_faces_dataset is None:
                return
            factor = (context.raw_timecode.GetValue() - context.timecode.GetValue()) / (
                context.next_time_code.GetValue() - context.timecode.GetValue()
            )
            logger.debug(
                "[cae.viz.faces][time] interpolating prim=%s time=%s next=%s factor=%s",
                prim.GetPath(),
                context.timecode,
                context.next_time_code,
                factor,
            )
            faces_dataset = cae_simdata.lerp_dataset(
                faces_dataset,
                next_faces_dataset,
                factor,
                fields=usd_utils.get_instances(prim, "CaeVizFieldSelectionAPI"),
            )

        await self.populate_mesh(
            prim, faces_dataset, self._update_points_attr, self._update_faces_attrs, self._update_primvars
        )
