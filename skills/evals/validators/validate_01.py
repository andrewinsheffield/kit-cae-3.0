"""
Eval 01 Validator: Import & Inspect
Runs inside Kit-CAE via --exec. Imports StaticMixer.cgns, discovers fields,
and validates that the expected fields are present with correct metadata.
"""

import asyncio
import json
import os
import sys

import numpy as np
import omni.kit.app
import omni.usd
from omni.cae.core import array_utils, usd_utils
from omni.cae.testing import wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import OmniSci, Usd

# Ground truth for StaticMixer.cgns
# Velocity is stored as a 3-component vector; CGNS delegate may split components
# (Velocity_0, Velocity_1, Velocity_2) or keep them as a single field (Velocity).
# We check for at least one Velocity-related field.
EXPECTED_SCALAR_FIELDS = {
    "Eddy_Viscosity": {"dtype_contains": "float"},
    "Pressure": {"dtype_contains": "float"},
    "Temperature": {"dtype_contains": "float"},
}
EXPECTED_VELOCITY_PREFIX = "Velocity"


async def main():
    app = omni.kit.app.get_app()
    checks = []

    try:
        # Import
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
        cgns_path = os.path.join(data_dir, "StaticMixer.cgns")
        await import_to_stage(cgns_path, "/World/StaticMixer")
        await wait_for_update(20)
        checks.append({"name": "import_success", "pass": True, "detail": "StaticMixer.cgns imported"})
    except Exception as e:
        checks.append({"name": "import_success", "pass": False, "detail": str(e)})
        _emit_result("01_import_inspect", checks)
        _shutdown(app)
        return

    stage = get_context().get_stage()

    # Discover OmniSci datasets and field instances.
    try:
        datasets = [prim for prim in stage.Traverse() if prim.IsA(OmniSci.Dataset)]
        dataset_fields = [(dataset, usd_utils.get_instances(dataset, "OmniSciFieldAPI")) for dataset in datasets]
        data_fields = sorted({name for _, names in dataset_fields for name in names})

        checks.append(
            {
                "name": "fields_discovered",
                "pass": len(data_fields) > 0,
                "detail": f"Found {len(data_fields)} data fields",
            }
        )

        # Check each expected scalar field
        field_names_found = data_fields
        for expected_name, expected_props in EXPECTED_SCALAR_FIELDS.items():
            found = expected_name in field_names_found
            checks.append(
                {
                    "name": f"field_{expected_name}",
                    "pass": found,
                    "detail": f"{'Found' if found else 'Missing'}: {expected_name}",
                }
            )

        # Check for Velocity field (may be single vector or split components)
        vel_fields = [n for n in field_names_found if n.startswith(EXPECTED_VELOCITY_PREFIX)]
        has_velocity = len(vel_fields) > 0
        checks.append(
            {
                "name": "field_Velocity",
                "pass": has_velocity,
                "detail": f"{'Found' if has_velocity else 'Missing'}: {vel_fields if vel_fields else 'no Velocity* fields'}",
            }
        )

    except Exception as e:
        checks.append({"name": "fields_discovered", "pass": False, "detail": str(e)})

    # Validate field metadata (dtype, shape) using data API
    try:
        for dataset, field_names in dataset_fields:
            for field_name in field_names:
                if field_name not in EXPECTED_SCALAR_FIELDS:
                    continue
                attr = dataset.GetAttribute(f"omni:sci:array:{field_name}:value")
                value = await asyncio.to_thread(attr.Get, Usd.TimeCode.EarliestTime())
                farray = np.asarray(value)
                dtype_str = str(farray.dtype)
                expected = EXPECTED_SCALAR_FIELDS[field_name]
                dtype_ok = expected["dtype_contains"] in dtype_str
                checks.append(
                    {
                        "name": f"metadata_{field_name}",
                        "pass": dtype_ok,
                        "detail": f"dtype={dtype_str} ndim={farray.ndim} shape={farray.shape}",
                    }
                )
                # Check ranges are finite
                ranges = array_utils.get_componentwise_ranges(farray)
                has_range = len(ranges) > 0 and all(r[0] <= r[1] for r in ranges)
                checks.append(
                    {
                        "name": f"range_{field_name}",
                        "pass": has_range,
                        "detail": f"range={ranges[0] if ranges else 'N/A'}",
                    }
                )
    except Exception as e:
        checks.append({"name": "metadata_validation", "pass": False, "detail": str(e)})

    _emit_result("01_import_inspect", checks)
    _shutdown(app)


def _emit_result(eval_name, checks):
    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    result = {
        "eval": eval_name,
        "pass": all(c["pass"] for c in checks),
        "score": round(passed / total * 100) if total > 0 else 0,
        "checks": checks,
    }
    print(f"\nEVAL_RESULT_BEGIN\n{json.dumps(result, indent=2)}\nEVAL_RESULT_END")


def _shutdown(app):
    async def _do_shutdown():
        app.post_quit()
        for _ in range(10):
            await app.next_update_async()
        os._exit(0)

    asyncio.ensure_future(_do_shutdown())


if __name__ == "__main__":
    asyncio.ensure_future(main())
