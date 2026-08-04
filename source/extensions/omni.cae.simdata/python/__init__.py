# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.


import math

from warp_simdata.usd.adapters import flash as flash_adapter
from warp_simdata.usd.types import AxisymmetricRepresentation

from .array_expressions import LANGUAGE_VERSION, ArrayExpressionDescription, ArrayExpressionDiagnostic
from .array_values import (
    ArrayValueProvider,
    ArrayValueProviderRegistration,
    effective_array_time_sample,
    get_array_time_samples,
    materialize_array,
    register_array_value_provider,
)
from .command_types import (
    ConvertToSimDataSet,
    FieldInfo,
    GetAvailableFields,
    GetField,
    get_array_expression_descriptions,
    get_prim_field,
    get_prim_fields,
)
from .extension import Extension
from .representations import get_dual_representation, resolve_representation, supports_dual_representation
from .utils import fetch_data, get_dataset, lerp_dataset, pass_fields, probe_fields

# Kit policy for FLASH AMR visualization. Keep the upstream warp-simdata
# default unchanged so applications must opt into this representation.
flash_adapter.DEFAULT_REPRESENTATION = AxisymmetricRepresentation(
    angular_cells=32,
    radial_dimension=0,
    axial_dimension=1,
    angle_range=(0.0, 2.0 * math.pi),
)

__all__ = [
    "ConvertToSimDataSet",
    "FieldInfo",
    "GetAvailableFields",
    "GetField",
    "ArrayExpressionDescription",
    "ArrayExpressionDiagnostic",
    "ArrayValueProvider",
    "ArrayValueProviderRegistration",
    "LANGUAGE_VERSION",
    # Utilities
    "fetch_data",
    "get_dataset",
    "get_array_expression_descriptions",
    "get_array_time_samples",
    "get_prim_field",
    "get_prim_fields",
    "get_dual_representation",
    "lerp_dataset",
    "materialize_array",
    "pass_fields",
    "probe_fields",
    "resolve_representation",
    "register_array_value_provider",
    "supports_dual_representation",
    "effective_array_time_sample",
]
