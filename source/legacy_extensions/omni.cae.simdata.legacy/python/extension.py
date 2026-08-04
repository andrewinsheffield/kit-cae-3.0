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
from omni.kit.commands import register_all_commands_in_module, unregister_module_commands

from . import commands


class Extension(IExt):
    def on_startup(self, ext_id):
        register_all_commands_in_module(commands)

    def on_shutdown(self):
        unregister_module_commands(commands)
