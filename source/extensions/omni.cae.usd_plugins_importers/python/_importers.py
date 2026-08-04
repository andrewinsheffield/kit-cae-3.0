# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from ._payload_importer import PayloadImporter


class CGNSAssetImporter(PayloadImporter):
    importer_name = "CAE CGNS Importer"
    file_extensions = (".cgns",)
    importer_filter_descriptions = ["CGNS Files (*.cgns)"]
    schema_api = "OmniSciFileFormatArgsCgnsAPI"


class EDEMAssetImporter(PayloadImporter):
    importer_name = "CAE EDEM Importer"
    file_extensions = (".dem",)
    importer_filter_descriptions = ["EDEM Deck Files (*.dem)"]
    schema_api = "OmniSciFileFormatArgsEdemAPI"


class FlashAssetImporter(PayloadImporter):
    """Importer for axisymmetric FLASH AMR descriptors."""

    importer_name = "CAE FLASH AMR Importer"
    file_extensions = (".flash",)
    importer_filter_descriptions = ["FLASH AMR Files (*.flash)"]
    schema_api = "OmniSciFileFormatArgsFlashAPI"


class EnSightAssetImporter(PayloadImporter):
    importer_name = "CAE EnSight Importer"
    file_extensions = (".case", ".encas")
    importer_filter_descriptions = ["EnSight Gold Files (*.case, *.encas)"]
    schema_api = "OmniSciFileFormatArgsEnSightAPI"


class EGRIDAssetImporter(PayloadImporter):
    importer_name = "CAE EGRID Importer"
    file_extensions = (".egrid",)
    importer_filter_descriptions = ["EGRID Files (*.egrid)"]
    schema_api = "OmniSciFileFormatArgsEgridAPI"


class GRDECLAssetImporter(PayloadImporter):
    importer_name = "CAE GRDECL Importer"
    file_extensions = (".grdecl", ".data")
    importer_filter_descriptions = ["GRDECL Files (*.grdecl, *.data)"]
    schema_api = "OmniSciFileFormatArgsGrdeclAPI"


class INITAssetImporter(PayloadImporter):
    importer_name = "CAE INIT Importer"
    file_extensions = (".init",)
    importer_filter_descriptions = ["INIT Files (*.init)"]
    schema_api = "OmniSciFileFormatArgsInitAPI"


class NPZAssetImporter(PayloadImporter):
    importer_name = "CAE NPZ Importer"
    file_extensions = (".npz", ".npy")
    importer_filter_descriptions = ["NumPy Files (*.npz, *.npy)"]
    schema_api = "OmniSciFileFormatArgsNpzAPI"
    _npy_schema_api = "OmniSciFileFormatArgsNpyAPI"

    def _schema_api(self, path: str) -> str:
        path = path.split("?", 1)[0].split("#", 1)[0].lower()
        if path.endswith(".npy"):
            return self._npy_schema_api
        return self.schema_api


class NanoVDBAssetImporter(PayloadImporter):
    importer_name = "CAE NanoVDB Importer"
    file_extensions = (".nvdb",)
    importer_filter_descriptions = ["NanoVDB Files (*.nvdb)"]
    schema_api = "OmniSciFileFormatArgsPythonAPI"


class OpenFoamAssetImporter(PayloadImporter):
    importer_name = "CAE OpenFOAM Importer"
    file_extensions = (".foam",)
    importer_filter_descriptions = ["OpenFOAM Files (*.foam)"]
    schema_api = "OmniSciFileFormatArgsOpenFoamAPI"


class UNRSTAssetImporter(PayloadImporter):
    importer_name = "CAE UNRST Importer"
    file_extensions = (".unrst",)
    importer_filter_descriptions = ["UNRST Files (*.unrst)"]
    schema_api = "OmniSciFileFormatArgsUnrstAPI"


class VTKAssetImporter(PayloadImporter):
    importer_name = "CAE VTK Importer"
    file_extensions = (".vtk", ".vti", ".vtr", ".vts", ".vtp", ".vtu")
    importer_filter_descriptions = ["VTK Files (*.vtk, *.vti, *.vtr, *.vts, *.vtp, *.vtu)"]
    schema_api = "OmniSciFileFormatArgsVtkAPI"


class TrimeshAssetImporter(PayloadImporter):
    importer_name = "CAE Trimesh Importer"
    file_extensions = (".stl", ".ply", ".3mf")
    importer_filter_descriptions = ["Trimesh Files (*.stl, *.ply, *.3mf)"]
    schema_api = "OmniSciFileFormatArgsPythonAPI"
