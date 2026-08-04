# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

__all__ = [
    "get_cache_mode",
    "get_downconvert_64bit",
    "override_setting",
    "SettingsKeys",
]

from carb.settings import get_settings


class SettingsKeys:
    CACHE_MODE = "/persistent/exts/omni.cae.core/cacheMode"
    DOWN_CONVERT_64BIT = "/persistent/exts/omni.cae.core/downConvert64Bit"

    # Non-persistent warp config overrides (set in kit .toml / launch args, not persisted).
    WARP_SKIP_BLACKWELL_PTX_OVERRIDE = "/exts/omni.cae.core/warp/skipBlackwellPtxOverride"
    WARP_MODE = "/exts/omni.cae.core/warp/mode"
    WARP_VERIFY_FP = "/exts/omni.cae.core/warp/verifyFp"
    WARP_VERIFY_CUDA = "/exts/omni.cae.core/warp/verifyCuda"
    WARP_VERBOSE = "/exts/omni.cae.core/warp/verbose"
    WARP_VERBOSE_WARNINGS = "/exts/omni.cae.core/warp/verboseWarnings"
    WARP_PTX_TARGET_ARCH = "/exts/omni.cae.core/warp/ptxTargetArch"
    WARP_MAX_UNROLL = "/exts/omni.cae.core/warp/maxUnroll"
    WARP_CUDA_OUTPUT = "/exts/omni.cae.core/warp/cudaOutput"


def get_cache_mode() -> str:
    return get_settings().get_as_string(SettingsKeys.CACHE_MODE)


def get_downconvert_64bit() -> bool:
    return get_settings().get_as_bool(SettingsKeys.DOWN_CONVERT_64BIT)


class override_setting:
    """Temporarily override a Carb setting and restore it on exit."""

    def __init__(self, setting_key: str, value):
        self.setting_key = setting_key
        self.new_value = value
        self.old_value = None
        self.settings = get_settings()

    def __enter__(self):
        self.old_value = self.settings.get(self.setting_key)
        self.settings.set(self.setting_key, self.new_value)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.old_value is not None:
            self.settings.set(self.setting_key, self.old_value)
        else:
            self.settings.destroy_item(self.setting_key)
        return False
