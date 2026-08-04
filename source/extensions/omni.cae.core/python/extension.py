# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import logging

import warp as wp
from omni.ext import IExt

logger = logging.getLogger(__name__)


class Extension(IExt):
    def on_startup(self, ext_id):
        from . import cache

        self._ext_id = ext_id
        cache._initialize()
        self.initialize_warp()

    def on_shutdown(self):
        from . import cache

        cache._finalize()

    def initialize_warp(self):
        from carb.settings import get_settings

        from .settings import SettingsKeys

        # Required for SimData.
        wp.config.enable_vector_component_overwrites = True
        wp.init()

        settings = get_settings()

        if not wp.is_cuda_available():
            logger.info("CUDA is not available; skipping CUDA-specific Warp configuration.")
            return

        cuda_device = wp.get_cuda_device()
        cuda_arch = cuda_device.arch
        if cuda_arch >= 100:
            if not settings.get_as_bool(SettingsKeys.WARP_SKIP_BLACKWELL_PTX_OVERRIDE):
                logger.info(
                    "Blackwell GPU detected (arch %d): forcing wp.config.cuda_output='ptx', ptx_target_arch=90",
                    cuda_arch,
                )
                wp.config.cuda_output = "ptx"
                wp.config.ptx_target_arch = 90
            else:
                logger.info(
                    "Blackwell GPU detected (arch %d): skipping PTX override (skipBlackwellPtxOverride is set)",
                    cuda_arch,
                )

        _WARP_CONFIG_SETTINGS = (
            (SettingsKeys.WARP_MODE, "mode"),
            (SettingsKeys.WARP_VERIFY_FP, "verify_fp"),
            (SettingsKeys.WARP_VERIFY_CUDA, "verify_cuda"),
            (SettingsKeys.WARP_VERBOSE, "verbose"),
            (SettingsKeys.WARP_VERBOSE_WARNINGS, "verbose_warnings"),
            (SettingsKeys.WARP_PTX_TARGET_ARCH, "ptx_target_arch"),
            (SettingsKeys.WARP_MAX_UNROLL, "max_unroll"),
            (SettingsKeys.WARP_CUDA_OUTPUT, "cuda_output"),
        )
        for setting_key, config_attr in _WARP_CONFIG_SETTINGS:
            value = settings.get(setting_key)
            if value is not None:
                logger.info(
                    "Applying warp config override: wp.config.%s = %r (from %s)", config_attr, value, setting_key
                )
                setattr(wp.config, config_attr, value)
