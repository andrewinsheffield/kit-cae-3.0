# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Iso-surface visualization operator."""

from logging import getLogger

import warp_simdata as simdata
from omni.cae.core import cache, progress, usd_utils
from omni.cae.schema import viz as cae_viz
from pxr import Usd
from warp_simdata.operators import iso_surface as simdata_iso_surface

from . import utils as viz_utils
from .execution_context import ExecutionContext
from .faces import populate_surface_mesh
from .operator import operator

logger = getLogger(__name__)


@operator()
class IsoSurface:
    """Extract and render a triangular iso-surface from a scalar field."""

    prim_type: str = "Mesh"
    api_schemas: set[str] = {
        "CaeVizIsoSurfaceAPI",
        "CaeVizDatasetSelectionAPI:source",
        "CaeVizFieldSelectionAPI:contour",
        "CaeVizFieldSelectionAPI:colors",
    }
    optional_api_schemas: set[str] = {
        "CaeVizDatasetAxisymmetricRepresentationAPI:source",
        "CaeVizDatasetDualAPI:source",
        "CaeVizDatasetTemporalCharacteristicsAPI:source",
        "CaeVizFieldSelectionAPI",
        "CaeVizFieldMappingAPI",
    }

    async def exec(self, prim: Usd.Prim, device: str, context: ExecutionContext):
        field_instances = usd_utils.get_instances(prim, "CaeVizFieldSelectionAPI")
        source_dataset = await viz_utils.get_input_dataset(
            prim,
            "source",
            timeCode=context.timecode,
            device=device,
            required_fields={"contour"},
            field_associations={name: simdata.AssociationType.NODE for name in field_instances},
        )
        iso_value = cae_viz.IsoSurfaceAPI(prim).GetIsoValueAttr().Get(context.timecode)
        output_fields = [name for name in field_instances if name != "contour" and source_dataset.has_field(name)]

        logger.info(
            "[cae.viz.iso_surface] executing prim=%s time=%s device=%s iso_value=%s",
            prim.GetPath(),
            context.timecode,
            device,
            iso_value,
        )
        cache_key = f"omni.cae.viz.iso_surface.IsoSurface:surface:{prim.GetPath()}:{device}"
        if context.is_full_rebuild_needed():
            cache.remove(cache_key)
        surface_dataset = cache.get(cache_key, timeCode=context.timecode)
        if surface_dataset is None:
            logger.info(
                "[cae.viz.iso_surface] computing prim=%s time=%s device=%s iso_value=%s",
                prim.GetPath(),
                context.timecode,
                device,
                iso_value,
            )
            with progress.ProgressContext("Executing SimData [iso_surface]"):
                with viz_utils.log_runtime_warnings(logger, "SimData iso-surface"):
                    surface_dataset = simdata_iso_surface.compute(
                        source_dataset,
                        "contour",
                        iso_value,
                        field_names=output_fields,
                    )
            cache.put_ex(
                cache_key,
                surface_dataset,
                prims=[cache.PrimWatch(prim, on="resync")],
                timeCode=context.timecode,
                force=True,
            )
        else:
            logger.debug(
                "[cae.viz.iso_surface] cache-hit prim=%s time=%s device=%s iso_value=%s",
                prim.GetPath(),
                context.timecode,
                device,
                iso_value,
            )

        if surface_dataset is None or surface_dataset.get_num_nodes() == 0 or surface_dataset.get_num_elems() == 0:
            raise usd_utils.QuietableException("No iso-surface generated")

        viz_utils.process_rescale_range_apis(prim, surface_dataset)
        await populate_surface_mesh(
            prim,
            surface_dataset,
            exclude_fields={"contour", "element_idx"},
        )
