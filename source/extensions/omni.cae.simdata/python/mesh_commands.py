# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from logging import getLogger

import numpy as np
import warp as wp
import warp_simdata as simdata
from pxr import Gf, Usd, UsdGeom
from warp_simdata.data_models.custom import surface_mesh

from .command_types import ConvertToSimDataSet

logger = getLogger(__name__)


class UsdGeomMeshConvertToSimDataSet(ConvertToSimDataSet):
    """Convert a UsdGeomMesh into a SimData surface mesh dataset."""

    def _apply_xform(self, mesh: UsdGeom.Mesh, coords: np.ndarray, timeCode: Usd.TimeCode) -> np.ndarray:
        _xform_cache = UsdGeom.XformCache(Usd.TimeCode.EarliestTime())
        matrix: Gf.Matrix4d = _xform_cache.GetLocalTransformation(mesh.GetPrim())[0]
        if matrix:
            coords_h = np.hstack([coords, np.ones((coords.shape[0], 1))])
            coords_h = coords_h @ matrix
            coords = coords_h[:, :3]
        return coords

    async def do(self) -> simdata.Dataset:
        logger.info("executing %s.do()", self.__class__.__name__)

        mesh = UsdGeom.Mesh(self.dataset)

        np_coords = np.asarray(mesh.GetPointsAttr().Get(self.timeCode)).astype(np.float32, copy=False).reshape(-1, 3)
        np_coords = self._apply_xform(mesh, np_coords, self.timeCode)
        points = wp.array(np_coords, dtype=wp.vec3f, device=self.device, copy=False)
        del np_coords

        np_face_vertex_counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(self.timeCode)).astype(
            np.int32, copy=False
        )
        np_face_vertex_indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(self.timeCode)).astype(
            np.int32, copy=False
        )
        face_vertex_counts = wp.array(np_face_vertex_counts, dtype=wp.int32, device=self.device, copy=False)
        face_vertex_indices = wp.array(np_face_vertex_indices, dtype=wp.int32, device=self.device, copy=False)

        return surface_mesh.create_dataset(
            points=points,
            face_vertex_indices=face_vertex_indices,
            face_vertex_counts=face_vertex_counts,
        )
