#!/usr/bin/env python3
"""Query statistics for OmniSci arrays in a native scientific asset.

Environment variables:
    CAE_STATS_FILE      Required path to a supported file.
    CAE_STATS_FIELDS    Optional comma-separated OmniSci field instance names.
    CAE_STATS_SCHEMA    Optional NPZ interpretation: Point Cloud, CGNS, or None.

Run inside Kit-CAE:
    CAE_STATS_FILE=/path/to/data.cgns ./repo.sh launch -n omni.cae.kit -- \
        --exec skills/cae-core/scripts/query_stats.py --no-window
"""

import asyncio
import json
import os

import numpy as np
import omni.kit.app
from omni.cae.core import array_utils, usd_utils
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import OmniSci, Usd


async def main():
    app = omni.kit.app.get_app()
    file_path = os.environ.get("CAE_STATS_FILE", "")
    if not file_path or not os.path.isfile(file_path):
        print(f"ERROR: CAE_STATS_FILE not set or file not found: {file_path!r}")
        await _quit(app, 1)
        return

    import_args = {}
    if file_path.lower().endswith(".npz") and (schema := os.environ.get("CAE_STATS_SCHEMA")):
        import_args["schema"] = schema

    print(f"Importing {file_path}...")
    await import_to_stage(file_path, "/World/StatsTarget", **import_args)
    for _ in range(10):
        await app.next_update_async()

    stage = get_context().get_stage()
    datasets = [prim for prim in stage.Traverse() if prim.IsA(OmniSci.Dataset)]
    requested = {name.strip() for name in os.environ.get("CAE_STATS_FIELDS", "").split(",") if name.strip()}

    result = {
        "file": file_path,
        "datasets": [str(prim.GetPath()) for prim in datasets],
        "fields": {},
    }

    for dataset in datasets:
        for field_name in usd_utils.get_instances(dataset, "OmniSciFieldAPI"):
            if requested and field_name not in requested:
                continue
            key = f"{dataset.GetPath()}#{field_name}"
            result["fields"][key] = await _field_info(dataset, field_name)

    print("STATS_BEGIN")
    print(json.dumps(result, indent=2, default=str))
    print("STATS_END")
    await _quit(app, 0)


async def _field_info(dataset: Usd.Prim, field_name: str) -> dict:
    info = {"dataset": str(dataset.GetPath()), "field": field_name}
    attr = dataset.GetAttribute(f"omni:sci:array:{field_name}:value")
    if not attr:
        return {**info, "error": "Missing OmniSci array value attribute"}

    try:
        value = await asyncio.to_thread(attr.Get, Usd.TimeCode.EarliestTime())
        if value is None:
            return {**info, "error": "Array has no value"}
        array = np.asarray(value)
        info.update(
            dtype=str(array.dtype),
            shape=list(array.shape),
            ranges=[
                {"component": index, "min": bounds[0], "max": bounds[1]}
                for index, bounds in enumerate(array_utils.get_componentwise_ranges(array))
            ],
        )
        if array.ndim == 1 or array.shape[-1] == 1:
            info["statistics"] = array_utils.get_scalar_stats(array, num_bins=32)
        else:
            info["statistics"] = "Vector field; use a component or magnitude for scalar statistics"
    except Exception as error:
        info["error"] = str(error)
    return info


async def _quit(app, exit_code: int):
    app.post_quit(exit_code)
    for _ in range(10):
        await app.next_update_async()
    os._exit(exit_code)


if __name__ == "__main__":
    asyncio.ensure_future(main())
