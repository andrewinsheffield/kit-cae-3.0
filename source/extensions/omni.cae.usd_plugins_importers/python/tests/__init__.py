# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import inspect
import tempfile
from pathlib import Path

import omni.cae.usd_plugins_importers as importers
import omni.client.utils as clientutils
import omni.kit.test
from omni.cae.testing import get_test_data_path, new_stage, wait_for_update
from omni.cae.usd_plugins_importers import _registry, import_to_stage
from omni.cae.usd_plugins_importers._importers import (
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
from pxr import Usd, UsdUtils

EARLIEST_TIME = Usd.TimeCode.EarliestTime()


def _list_op_items(list_op):
    if list_op is None:
        return []

    items = []
    for attr_name in ("explicitItems", "prependedItems", "appendedItems", "addedItems"):
        items.extend(getattr(list_op, attr_name, []) or [])
    return items


def _payload_asset_path(prim):
    items = _list_op_items(prim.GetMetadata("payload"))
    if not items:
        return None
    return items[0].assetPath


def _expected_asset_path(path: str) -> str:
    return clientutils.make_file_url_if_possible(clientutils.normalize_url(path))


def _authored_format_arg_attr_names(prim):
    return [
        attr.GetName()
        for attr in prim.GetAttributes()
        if attr.GetName().startswith("omni:cae:format:") and attr.HasAuthoredValueOpinion()
    ]


def _authored_api_schema_names(prim):
    root_layer = prim.GetStage().GetRootLayer()
    for prim_spec in prim.GetPrimStack():
        if prim_spec.layer == root_layer:
            return {str(schema) for schema in _list_op_items(prim_spec.GetInfo("apiSchemas"))}
    return set()


def _write_test_ply(path: Path) -> None:
    path.write_text(
        """ply
format ascii 1.0
element vertex 4
property float x
property float y
property float z
element face 4
property list uchar int vertex_indices
end_header
0 0 0
1 0 0
0.5 1 0
0.5 0.5 1
3 0 1 2
3 0 1 3
3 1 2 3
3 0 2 3
""",
        encoding="utf-8",
    )


class TestUsdPluginsImporters(omni.kit.test.AsyncTestCase):
    def test_import_to_stage_signature_accepts_format_args(self):
        parameters = inspect.signature(import_to_stage).parameters

        self.assertEqual(tuple(parameters)[:2], ("path", "prim_path"))
        self.assertEqual(parameters["path"].kind, inspect.Parameter.POSITIONAL_ONLY)
        self.assertEqual(parameters["args"].kind, inspect.Parameter.VAR_KEYWORD)

    def test_package_exports_only_top_level_import_to_stage(self):
        self.assertEqual(set(importers.__all__), {"Extension", "import_to_stage"})
        self.assertFalse(hasattr(importers, "cgns_import_to_stage"))
        self.assertFalse(hasattr(importers, "npz_import_to_stage"))

    def test_registry_dispatches_by_extension(self):
        expected = {
            "example.cgns": CGNSAssetImporter,
            "example.dem": EDEMAssetImporter,
            "example.flash": FlashAssetImporter,
            "example.case": EnSightAssetImporter,
            "example.encas": EnSightAssetImporter,
            "example.egrid": EGRIDAssetImporter,
            "example.grdecl": GRDECLAssetImporter,
            "example.data": GRDECLAssetImporter,
            "example.init": INITAssetImporter,
            "example.npz": NPZAssetImporter,
            "example.npy": NPZAssetImporter,
            "example.nvdb": NanoVDBAssetImporter,
            "example.foam": OpenFoamAssetImporter,
            "example.unrst": UNRSTAssetImporter,
            "example.vtk": VTKAssetImporter,
            "example.vti": VTKAssetImporter,
            "example.vtr": VTKAssetImporter,
            "example.vts": VTKAssetImporter,
            "example.vtp": VTKAssetImporter,
            "example.vtu": VTKAssetImporter,
            "example.stl": TrimeshAssetImporter,
            "example.ply": TrimeshAssetImporter,
            "example.3mf": TrimeshAssetImporter,
        }

        for path, importer_type in expected.items():
            self.assertIs(_registry.find_importer_type(path.upper()), importer_type)

        self.assertIsNone(_registry.find_importer_type("example.txt"))
        self.assertIsNone(_registry.find_importer_type("example.off"))
        self.assertIsNone(_registry.find_importer_type("example.pvcm"))

    def test_vtk_importer_selects_schema_by_extension(self):
        importer = VTKAssetImporter()

        self.assertEqual(importer._schema_api("example.vtk"), "OmniSciFileFormatArgsVtkAPI")
        self.assertEqual(importer._schema_api("example.vti"), "OmniSciFileFormatArgsVtkAPI")
        self.assertEqual(importer._schema_api("example.vtu?cache=false"), "OmniSciFileFormatArgsVtkAPI")

    def test_numpy_importer_selects_schema_by_extension(self):
        importer = NPZAssetImporter()

        self.assertEqual(importer._schema_api("example.npz"), "OmniSciFileFormatArgsNpzAPI")
        self.assertEqual(importer._schema_api("example.npy"), "OmniSciFileFormatArgsNpyAPI")
        self.assertEqual(importer._schema_api("example.npy?allowPickle=true"), "OmniSciFileFormatArgsNpyAPI")

    def test_reservoir_importers_select_schema_by_extension(self):
        self.assertEqual(EGRIDAssetImporter()._schema_api("example.egrid"), "OmniSciFileFormatArgsEgridAPI")
        self.assertEqual(GRDECLAssetImporter()._schema_api("example.grdecl"), "OmniSciFileFormatArgsGrdeclAPI")
        self.assertEqual(GRDECLAssetImporter()._schema_api("example.data"), "OmniSciFileFormatArgsGrdeclAPI")
        self.assertEqual(INITAssetImporter()._schema_api("example.init"), "OmniSciFileFormatArgsInitAPI")
        self.assertEqual(UNRSTAssetImporter()._schema_api("example.unrst"), "OmniSciFileFormatArgsUnrstAPI")

    def test_python_backed_importers_use_python_schema(self):
        self.assertEqual(NanoVDBAssetImporter()._schema_api("example.nvdb"), "OmniSciFileFormatArgsPythonAPI")
        self.assertEqual(TrimeshAssetImporter()._schema_api("example.stl"), "OmniSciFileFormatArgsPythonAPI")

    def assert_payload_prim(
        self,
        prim,
        source_path: str,
        expected_authored_api: str,
        expected_composed_apis: set[str] | None = None,
    ):
        self.assertTrue(prim)
        self.assertTrue(prim.HasAuthoredPayloads())
        self.assertFalse(prim.HasAuthoredReferences())
        self.assertEqual(_list_op_items(prim.GetMetadata("references")), [])

        payload_path = _payload_asset_path(prim)
        self.assertEqual(payload_path, _expected_asset_path(source_path))
        self.assertNotIn("SDF_FORMAT_ARGS", payload_path)
        self.assertNotIn("rootName=", payload_path)

        self.assertEqual(_authored_api_schema_names(prim), {expected_authored_api})
        applied_schemas = {str(schema) for schema in prim.GetAppliedSchemas()}
        expected_apis = {expected_authored_api}
        if expected_composed_apis is not None:
            expected_apis.update(expected_composed_apis)
        self.assertTrue(expected_apis.issubset(applied_schemas))
        self.assertEqual(_authored_format_arg_attr_names(prim), [])

    async def _stage_from_importer(self, importer, path: str):
        result = await importer.convert_assets([path], import_as_reference=False)
        stage_id = next(iter(result.values()))
        return UsdUtils.StageCache.Get().Find(Usd.StageCache.Id.FromString(stage_id))

    async def test_cgns_applies_schema_and_payload(self):
        path = get_test_data_path("StaticMixer.cgns")
        importer = CGNSAssetImporter()

        stage = await self._stage_from_importer(importer, path)
        root = stage.GetDefaultPrim()

        self.assert_payload_prim(
            root,
            path,
            "OmniSciFileFormatArgsCgnsAPI",
            {
                "OmniSciFileFormatArgsAPI",
                "OmniSciFileFormatArgsTimeAPI",
            },
        )
        self.assertTrue(stage.GetPrimAtPath(f"{root.GetPath()}/Base/StaticMixer/B1_P3"))

    async def test_npz_import_to_stage_applies_schema_and_payload(self):
        path = get_test_data_path("disk_out_ref.npz")
        async with new_stage() as stage:
            prim = await import_to_stage(path, "/World/disk_out_ref_npz")
            await wait_for_update()

            self.assert_payload_prim(
                prim,
                path,
                "OmniSciFileFormatArgsNpzAPI",
                {
                    "OmniSciFileFormatArgsAPI",
                },
            )

            payload_path = _payload_asset_path(prim)
            prim.GetAttribute("omni:cae:format:npz:schema").Set("None")
            await wait_for_update()
            self.assertEqual(_payload_asset_path(prim), payload_path)
            self.assertEqual(str(prim.GetAttribute("omni:cae:format:npz:schema").Get()), "None")
            self.assertFalse(prim.HasAuthoredReferences())

    async def test_npz_import_to_stage_reads_raw_arrays(self):
        path = get_test_data_path("StaticMixer.npz")
        async with new_stage():
            prim = await import_to_stage(path, "/World/StaticMixer_npz", schema="None")
            await wait_for_update()

            pressure = prim.GetAttribute("omni:sci:array:Pressure:value")
            self.assertTrue(pressure)
            self.assertEqual(len(pressure.Get(EARLIEST_TIME)), 2786)
            self.assertFalse(prim.GetAttribute("omni:sci:array:Missing:value"))

    async def test_npz_import_to_stage_reads_cgns_vector_fields(self):
        path = get_test_data_path("disk_out_ref.npz")
        async with new_stage() as stage:
            await import_to_stage(path, "/World/disk_out_ref_npz", schema="CGNS")
            await wait_for_update()

            section = stage.GetPrimAtPath("/World/disk_out_ref_npz/Base/Zone/Section")
            flow_solution = stage.GetPrimAtPath("/World/disk_out_ref_npz/Base/Zone/FlowSolution")
            self.assertTrue(section)
            self.assertTrue(flow_solution)

            temp = flow_solution.GetAttribute("omni:sci:array:Temp:value")
            velocity = flow_solution.GetAttribute("omni:sci:array:V:value")
            connectivity = section.GetAttribute("omni:sci:array:elementConnectivity:value")
            self.assertTrue(temp)
            self.assertTrue(velocity)
            self.assertTrue(connectivity)
            self.assertEqual(str(velocity.GetTypeName()), "double3[]")
            self.assertEqual(len(temp.Get(EARLIEST_TIME)), 8499)
            self.assertEqual(len(velocity.Get(EARLIEST_TIME)), 8499)
            self.assertEqual(len(velocity.Get(EARLIEST_TIME)[0]), 3)

    async def test_nvdb_import_to_stage_authors_nanovdb_sample(self):
        path = get_test_data_path("headsq.nvdb")
        async with new_stage():
            prim = await import_to_stage(path, "/World/headsq_nvdb")
            await wait_for_update()

            self.assert_payload_prim(
                prim,
                path,
                "OmniSciFileFormatArgsPythonAPI",
                {
                    "OmniSciFileFormatArgsAPI",
                },
            )
            nanovdb = prim.GetAttribute("omni:sci:array:nanovdb:value")
            self.assertTrue(nanovdb)
            self.assertEqual(str(nanovdb.GetTypeName()), "uint[]")
            self.assertEqual(nanovdb.GetTimeSamples(), [0.0])
            self.assertEqual(prim.GetAttribute("omni:sci:array:nanovdb:device").Get(), "cpu")

    async def test_trimesh_import_to_stage_reads_mesh_arrays(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "tetra.ply"
            _write_test_ply(path)

            async with new_stage():
                prim = await import_to_stage(str(path), "/World/tetra_ply")
                await wait_for_update()

                self.assert_payload_prim(
                    prim,
                    str(path),
                    "OmniSciFileFormatArgsPythonAPI",
                    {
                        "OmniSciFileFormatArgsAPI",
                    },
                )
                points = prim.GetAttribute("omni:sci:array:points:value")
                indices = prim.GetAttribute("omni:sci:array:faceVertexIndices:value")
                counts = prim.GetAttribute("omni:sci:array:faceVertexCounts:value")

                self.assertTrue(points)
                self.assertTrue(indices)
                self.assertTrue(counts)
                self.assertEqual(str(points.GetTypeName()), "float3[]")
                self.assertEqual(str(indices.GetTypeName()), "int[]")
                self.assertEqual(str(counts.GetTypeName()), "int[]")
                self.assertEqual(len(points.Get(EARLIEST_TIME)), 4)
                self.assertEqual(len(points.Get(EARLIEST_TIME)[0]), 3)
                self.assertEqual(len(indices.Get(EARLIEST_TIME)), 12)
                self.assertEqual(list(counts.Get(EARLIEST_TIME)), [3, 3, 3, 3])

    async def test_import_to_stage_sets_format_args_by_property_suffix(self):
        path = get_test_data_path("disk_out_ref.npz")
        async with new_stage():
            prim = await import_to_stage(path, "/World/disk_out_ref_npz", schema="None", cacheMode="none")
            await wait_for_update()

            self.assertEqual(prim.GetAttribute("omni:cae:format:npz:schema").Get(), "None")
            self.assertEqual(prim.GetAttribute("omni:cae:format:cacheMode").Get(), "none")

    async def test_import_to_stage_rejects_unknown_format_args(self):
        path = get_test_data_path("disk_out_ref.npz")
        async with new_stage():
            with self.assertRaisesRegex(ValueError, "Unsupported CAE file-format argument"):
                await import_to_stage(path, "/World/disk_out_ref_npz", bogus=True)

    async def test_vtk_import_to_stage_applies_schema_and_payload(self):
        path = get_test_data_path("headsq.vti")
        async with new_stage() as stage:
            prim = await import_to_stage(path, "/World/headsq_vti")
            await wait_for_update()

            self.assert_payload_prim(
                prim,
                path,
                "OmniSciFileFormatArgsVtkAPI",
                {
                    "OmniSciFileFormatArgsAPI",
                    "OmniSciFileFormatArgsStreamingAPI",
                },
            )

    async def test_import_to_stage_rejects_unsupported_format(self):
        with self.assertRaisesRegex(ValueError, "Supported formats"):
            await import_to_stage("unsupported.txt", "/World/unsupported")
