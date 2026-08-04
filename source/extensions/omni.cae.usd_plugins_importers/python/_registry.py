# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import omni.client.utils as clientutils
from pxr import Usd

from ._importers import (
    CGNSAssetImporter,
    EDEMAssetImporter,
    EGRIDAssetImporter,
    EnSightAssetImporter,
    FlashAssetImporter,
    GRDECLAssetImporter,
    INITAssetImporter,
    NanoVDBAssetImporter,
    NPZAssetImporter,
    OpenFoamAssetImporter,
    TrimeshAssetImporter,
    UNRSTAssetImporter,
    VTKAssetImporter,
)
from ._payload_importer import PayloadImporter

IMPORTER_TYPES: tuple[type[PayloadImporter], ...] = (
    CGNSAssetImporter,
    EDEMAssetImporter,
    FlashAssetImporter,
    EnSightAssetImporter,
    EGRIDAssetImporter,
    GRDECLAssetImporter,
    INITAssetImporter,
    NPZAssetImporter,
    NanoVDBAssetImporter,
    OpenFoamAssetImporter,
    UNRSTAssetImporter,
    VTKAssetImporter,
    TrimeshAssetImporter,
)


def create_importers() -> list[PayloadImporter]:
    return [importer_type() for importer_type in IMPORTER_TYPES]


def find_importer_type(path: str) -> type[PayloadImporter] | None:
    extension = _path_extension(path)
    for importer_type in IMPORTER_TYPES:
        if extension in importer_type.file_extensions:
            return importer_type
    return None


def supported_format_descriptions() -> str:
    descriptions = []
    for importer_type in IMPORTER_TYPES:
        descriptions.extend(importer_type.importer_filter_descriptions)
    return ", ".join(descriptions)


async def import_to_stage(path: str, /, prim_path: str, **args) -> Usd.Prim:
    """Import a supported CAE file into the active USD stage at the given prim path."""
    normalized_path = clientutils.normalize_url(path)
    importer_type = find_importer_type(normalized_path)
    if importer_type is None:
        raise ValueError(
            f"No CAE USD plugin importer is registered for '{path}'. "
            f"Supported formats: {supported_format_descriptions()}"
        )
    return importer_type().import_to_stage(normalized_path, prim_path, **args)


def _path_extension(path: str) -> str:
    path = path.split("?", 1)[0].split("#", 1)[0]
    for importer_type in IMPORTER_TYPES:
        for extension in importer_type.file_extensions:
            if path.lower().endswith(extension):
                return extension
    return ""
