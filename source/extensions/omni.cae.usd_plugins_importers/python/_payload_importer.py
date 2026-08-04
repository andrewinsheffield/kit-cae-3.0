# SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from __future__ import annotations

import os.path
import re

import omni.client.utils as clientutils
from omni.kit.tool.asset_importer import AbstractImporterDelegate
from omni.usd import get_context
from pxr import Tf, Usd, UsdUtils


def _apply_schema_api(prim: Usd.Prim, schema_api: str) -> None:
    schema_type = Tf.Type.FindByName(schema_api)
    try:
        if schema_type and prim.ApplyAPI(schema_type):
            return
    except Exception:
        pass

    raise RuntimeError(f"Could not apply USD API schema: {schema_api}")


class PayloadImporter(AbstractImporterDelegate):
    importer_name = "CAE File Importer"
    file_extensions: tuple[str, ...] = ()
    importer_filter_descriptions: list[str] = []
    schema_api: str = ""

    @property
    def name(self):
        return self.importer_name

    @property
    def filter_regexes(self):
        return [rf".*{re.escape(extension)}$" for extension in self.file_extensions]

    @property
    def filter_descriptions(self):
        return self.importer_filter_descriptions

    def show_destination_frame(self):
        return True

    def supports_usd_destination(self):
        return True

    def supports_binary_usd(self):
        return True

    def supports_usd_stage_cache_destination(self):
        return True

    def supports_usd_stage_cache(self):
        return True

    def build_options(self, paths):
        return None

    async def convert_assets(self, paths, **kwargs):
        import_as_reference = kwargs.get("import_as_reference")
        output_folder = kwargs.get("export_folder") or kwargs.get("output_folder")
        output_usd_type = kwargs.get("output_usd_type") or "usda"

        results = {}
        for path in paths:
            normalized_path = clientutils.normalize_url(path)
            if converted_path := await self._convert_asset(
                normalized_path, import_as_reference, output_folder, output_usd_type
            ):
                results[path] = converted_path
        return results

    async def _convert_asset(self, path, import_as_reference, output_folder, output_usd_type):
        path = clientutils.normalize_url(path)

        if import_as_reference:
            output_dir = output_folder if output_folder else os.path.dirname(path)
            output_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(path))[0]}.{output_usd_type}")
            stage = Usd.Stage.CreateNew(output_path)
            self._populate_stage(stage, path, set_default_prim=True)
            stage.Save()
            return output_path

        stage = Usd.Stage.CreateInMemory()
        self._populate_stage(stage, path, set_default_prim=True)
        stage_cache_id = UsdUtils.StageCache.Get().Insert(stage)
        return stage_cache_id.ToString()

    def _default_prim_path(self, path: str) -> str:
        root_name = Tf.MakeValidIdentifier(os.path.basename(path))
        return f"/{root_name}"

    def _schema_api(self, path: str) -> str:
        return self.schema_api

    def import_to_stage(self, path: str, /, prim_path: str, **args) -> Usd.Prim:
        stage = get_context().get_stage()
        if stage is None:
            raise RuntimeError("No active USD stage is available for import.")
        return self._populate_stage(stage, path, prim_path=prim_path, set_default_prim=False, args=args)

    def _populate_stage(self, stage, path, prim_path=None, set_default_prim=False, args=None):
        root = populate_payload_prim(
            stage, path, self._schema_api(path), prim_path or self._default_prim_path(path), args=args
        )
        if set_default_prim:
            stage.SetDefaultPrim(root)
        return root


def _format_arg_attributes(prim: Usd.Prim) -> dict[str, Usd.Attribute]:
    matches = {}
    duplicates = set()
    for attr in prim.GetAttributes():
        arg_name = attr.GetBaseName()
        if arg_name in matches:
            duplicates.add(arg_name)
        matches[arg_name] = attr

    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise RuntimeError(f"Ambiguous CAE file-format argument name(s): {names}")
    return matches


def _set_format_args(prim: Usd.Prim, args: dict | None) -> None:
    if not args:
        return

    attrs = _format_arg_attributes(prim)
    unknown = sorted(set(args).difference(attrs))
    if unknown:
        available = ", ".join(sorted(attrs))
        raise ValueError(
            f"Unsupported CAE file-format argument(s) for {prim.GetPath()}: {', '.join(unknown)}. "
            f"Available arguments: {available}"
        )

    for name, value in args.items():
        if not attrs[name].Set(value):
            raise ValueError(f"Could not set CAE file-format argument '{name}' on {prim.GetPath()}")


def populate_payload_prim(stage: Usd.Stage, path: str, schema_api: str, prim_path: str, args: dict | None = None):
    path = clientutils.normalize_url(path)
    root = stage.DefinePrim(prim_path)
    _apply_schema_api(root, schema_api)
    _set_format_args(root, args)
    root.GetPayloads().AddPayload(clientutils.make_file_url_if_possible(path))
    root.Load()
    return root
