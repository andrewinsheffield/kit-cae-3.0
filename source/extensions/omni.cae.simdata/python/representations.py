# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Resolve authored visualization representation requests for USD datasets."""

import math

from omni.cae.schema import viz as cae_viz
from pxr import OmniSciFlash, Usd
from warp_simdata.usd.adapters import flash as flash_adapter
from warp_simdata.usd.types import AxisymmetricDualRepresentation, AxisymmetricRepresentation


def _flash_representation(
    dataset_prim: Usd.Prim,
    options_prim: Usd.Prim | None = None,
    instance_name: str = "",
    *,
    dual: bool = False,
) -> AxisymmetricRepresentation | None:
    if not dataset_prim or not dataset_prim.HasAPI(OmniSciFlash.AmrAPI):
        return None

    default = flash_adapter.DEFAULT_REPRESENTATION
    angular_cells = default.angular_cells
    minimum_angle = math.degrees(default.angle_range[0])
    maximum_angle = math.degrees(default.angle_range[1])

    if (
        options_prim
        and instance_name
        and options_prim.HasAPI(cae_viz.DatasetAxisymmetricRepresentationAPI, instance_name)
    ):
        api = cae_viz.DatasetAxisymmetricRepresentationAPI(options_prim, instance_name)
        angular_cells = int(api.GetAngularCellsAttr().Get())
        minimum_angle = float(api.GetMinimumAngleAttr().Get())
        maximum_angle = float(api.GetMaximumAngleAttr().Get())

    if angular_cells < 3:
        raise ValueError("Angular Cells must be at least 3.")
    if not math.isfinite(minimum_angle) or not math.isfinite(maximum_angle):
        raise ValueError("Minimum Angle and Maximum Angle must be finite.")
    if minimum_angle < 0.0 or maximum_angle > 360.0 or maximum_angle <= minimum_angle:
        raise ValueError("Angles must satisfy 0 <= Minimum Angle < Maximum Angle <= 360 degrees.")

    representation_type = AxisymmetricDualRepresentation if dual else AxisymmetricRepresentation
    return representation_type(
        angular_cells=angular_cells,
        radial_dimension=default.radial_dimension,
        axial_dimension=default.axial_dimension,
        angle_range=(math.radians(minimum_angle), math.radians(maximum_angle)),
    )


def resolve_representation(
    dataset_prim: Usd.Prim,
    options_prim: Usd.Prim | None = None,
    instance_name: str = "",
    *,
    dual: bool = False,
) -> AxisymmetricRepresentation | None:
    """Resolve the concrete representation requested for ``dataset_prim``.

    FLASH always resolves to a concrete representation, including when no
    authored options override Kit's defaults. Other dataset models currently
    use their adapter-native representation and return ``None``.
    """
    return _flash_representation(dataset_prim, options_prim, instance_name, dual=dual)


def get_dual_representation(dataset_prim: Usd.Prim) -> AxisymmetricDualRepresentation | None:
    """Return the adapter representation for a dual-capable dataset, or ``None``."""
    representation = resolve_representation(dataset_prim, dual=True)
    return representation if isinstance(representation, AxisymmetricDualRepresentation) else None


def supports_dual_representation(dataset_prim: Usd.Prim) -> bool:
    """Return whether Kit has a dual-representation adapter for ``dataset_prim``."""
    return get_dual_representation(dataset_prim) is not None
