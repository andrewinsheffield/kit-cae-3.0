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

from logging import getLogger

import omni.ext

logger = getLogger(__name__)


def _load_usd_plugins():
    try:
        import cae_openusd_plugins
    except Exception:
        logger.exception("Failed to import cae_openusd_plugins; check that extension.toml exposes lib/python")
        return None

    try:
        plugin_dir = cae_openusd_plugins.register_usd_plugins()
    except Exception:
        logger.exception("Failed to register CAE USD plugins")
        return None

    logger.info("Registered CAE USD plugins from '%s'", plugin_dir)
    return cae_openusd_plugins


class Extension(omni.ext.IExt):
    def on_startup(self, ext_id):
        logger.info("starting extension %s", ext_id)
        self._cae_openusd_plugins = _load_usd_plugins()

    def on_shutdown(self):
        self._cae_openusd_plugins = None
        logger.info("shutting down")
