# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from omni.ext import IExt
from omni.kit.window.property import get_window

from .field_array_widget import CaeFieldArrayPropertiesWidget


class Extension(IExt):
    def on_startup(self, ext_id):
        if property_window := get_window():
            property_window.register_widget("prim", "cae_field_array", CaeFieldArrayPropertiesWidget("CAE Insights"))

    def on_shutdown(self):
        if property_window := get_window():
            property_window.unregister_widget("prim", "cae_field_array")
