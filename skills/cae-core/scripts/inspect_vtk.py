#!/usr/bin/env python3
"""Inspect a VTK asset through the native OpenUSD file-format plugin.

Usage from the Kit-CAE repository root:
    CAE_INSPECT_FILE=/path/to/file.vti ./repo.sh launch -n omni.cae.kit -- \
        --exec skills/cae-core/scripts/inspect_vtk.py --no-window
"""

import asyncio
import json
import os

import omni.kit.app
from omni.cae.core import usd_utils
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import OmniSci


async def main():
    app = omni.kit.app.get_app()
    file_path = os.environ.get("CAE_INSPECT_FILE", "")
    if not file_path or not os.path.isfile(file_path):
        print(f"ERROR: CAE_INSPECT_FILE not set or file not found: {file_path!r}")
        await _quit(app, 1)
        return

    await import_to_stage(file_path, "/World/InspectTarget")
    for _ in range(10):
        await app.next_update_async()

    print("INSPECT_BEGIN")
    print(json.dumps(_describe_stage(), indent=2))
    print("INSPECT_END")
    await _quit(app, 0)


def _describe_stage():
    stage = get_context().get_stage()
    result = {"datasets": []}
    for dataset in (prim for prim in stage.Traverse() if prim.IsA(OmniSci.Dataset)):
        fields = []
        for name in usd_utils.get_instances(dataset, "OmniSciFieldAPI"):
            fields.append(
                {
                    "name": name,
                    "association": dataset.GetAttribute(f"omni:sci:field:{name}:association").Get(),
                    "type": str(dataset.GetAttribute(f"omni:sci:array:{name}:value").GetTypeName()),
                }
            )
        result["datasets"].append({"path": str(dataset.GetPath()), "fields": fields})
    return result


async def _quit(app, exit_code):
    app.post_quit(exit_code)
    for _ in range(10):
        await app.next_update_async()
    os._exit(exit_code)


if __name__ == "__main__":
    asyncio.ensure_future(main())
