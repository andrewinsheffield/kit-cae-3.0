# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

__all__ = ["Extension"]

from omni.ext import IExt
from omni.kit.property.bundle import GeomPrimSchemeDelegate
from omni.kit.window.property import get_window

from .property_widget import (
    CaeGeomPrimSchemeDelegate,
    CaePropertiesWidget,
    OmniSciPropertiesWidget,
    RtwtPropertiesWidget,
)


class Extension(IExt):

    def on_startup(self, ext_id):
        if property_window := get_window():
            property_window.register_widget("prim", "cae", CaePropertiesWidget("CAE"))
            property_window.register_widget("prim", "rtwt", RtwtPropertiesWidget("RTWT"))
            property_window.register_widget("prim", "omni_sci", OmniSciPropertiesWidget("Omni Scientific"))
            property_window.register_scheme_delegate("prim", "xformable_prim", CaeGeomPrimSchemeDelegate())

    def on_shutdown(self):
        if property_window := get_window():
            property_window.unregister_widget("prim", "omni_sci")
            property_window.unregister_widget("prim", "rtwt")
            property_window.unregister_widget("prim", "cae")
            # restore the default GeomPrimSchemeDelegate
            property_window.register_scheme_delegate("prim", "xformable_prim", GeomPrimSchemeDelegate())
