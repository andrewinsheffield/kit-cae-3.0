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

import ctypes
import os
import sys
from logging import getLogger
from pathlib import Path

import omni.ext
from omni.kit.app import get_app
from pxr import Plug, Usd  # noqa: F401 -- Usd import ensures base class wrappers exist for schema modules

logger = getLogger(__name__)


def _plugin_sort_key(plugin):
    name = plugin.name
    return (0 if name == "omniCae" else 1, name)


def _path_is_under(path, root):
    """Return true when path is inside root, after normalizing both paths."""
    try:
        resolved_path = Path(path).resolve()
        resolved_root = Path(root).resolve()
    except OSError:
        resolved_path = Path(path).absolute()
        resolved_root = Path(root).absolute()

    try:
        resolved_path.relative_to(resolved_root)
        return True
    except ValueError:
        if sys.platform != "win32":
            return False

    # Windows paths can differ only by case depending on how USD registered the
    # plugin. Normalize as a fallback so selection stays stable.
    try:
        path_str = os.path.normcase(str(resolved_path))
        root_str = os.path.normcase(str(resolved_root))
        return os.path.commonpath([path_str, root_str]) == root_str
    except ValueError:
        return False


def _get_schema_plugins(plugin_dir, registered_plugins):
    """Return the USD schema plugins that belong to this extension.

    RegisterPlugins() returns the plugins it registered during this call, but
    it can return an empty list if the same plugInfo files were registered
    earlier. Preloading is still required in that case, so fall back to the USD
    registry and select plugins whose resolved library path lives under this
    extension's usd/plugin directory.
    """
    registered = list(registered_plugins)

    # RegisterPlugins() may return only the plugins newly registered by this
    # call. If another extension or an earlier startup pass already registered
    # one of these plugInfo files, recover it from USD's registry as well.
    registry_plugins = [plugin for plugin in Plug.Registry().GetAllPlugins() if _path_is_under(plugin.path, plugin_dir)]

    plugins_by_key = {}
    for plugin in registered + registry_plugins:
        plugins_by_key.setdefault((plugin.name, str(Path(plugin.path).resolve())), plugin)

    return list(plugins_by_key.values())


def _preload_registered_plugin_libraries(plugins):
    """Preload schema plugin libraries without invoking USD's plugin loader.

    Registering a USD plugin only makes its plugInfo metadata discoverable. The
    actual schema library is normally loaded lazily by USD when a type from that
    plugin is needed. That is too late for native Kit plugins such as
    omni.cae.data.plugin, which have direct dynamic-library dependencies on
    generated schema libraries like omniCae.so.

    Do not call PlugPlugin.Load() here. In this Kit packaging layout USD tries
    to import generated Python modules as usd.python.pxr.<SchemaName>, which is
    not the import path used by these extensions and produces noisy warnings.
    Loading the library by absolute path gives the platform loader the resident
    shared library it needs without asking USD to import Python wrappers.

    On Linux, RTLD_GLOBAL is important: it lets later native plugin loads
    resolve DT_NEEDED entries such as omniCae.so by SONAME against the schema
    library already loaded here. On Windows, these flags are ignored by ctypes,
    but loading the DLL by absolute path is still useful as an explicit preload.
    Keep the returned CDLL handles alive for the lifetime of the extension so
    the loader does not release the libraries early.
    """
    handles = []
    mode = getattr(os, "RTLD_NOW", 0) | getattr(os, "RTLD_GLOBAL", 0)
    for plugin in sorted(plugins, key=_plugin_sort_key):
        if plugin.isLoaded:
            logger.info("USD schema plugin '%s' is already loaded from '%s'", plugin.name, plugin.path)
            continue

        logger.info("Preloading USD schema plugin library '%s' from '%s'", plugin.name, plugin.path)
        try:
            handles.append(ctypes.CDLL(plugin.path, mode=mode))
        except OSError as exc:
            logger.error(
                "Failed to preload USD schema plugin library '%s' from '%s': %s", plugin.name, plugin.path, exc
            )

    return handles


def _load_usd_plugins(ext_id):
    plugin_dir = Path(get_app().get_extension_manager().get_extension_path(ext_id)) / "usd" / "plugin"

    handles = []
    if not plugin_dir.is_dir():
        logger.error("USD schema plugin directory does not exist: '%s'", plugin_dir)
        return handles

    # On Windows, loading a schema DLL by absolute path does not automatically
    # make sibling schema DLLs available for dependency resolution. Schema DLLs
    # are packaged directly under usd/plugin, so add that root before the
    # explicit preloads below and before generated Python bindings are imported.
    # This lets dependencies such as `omniCaeViz.dll -> omniCae.dll` and
    # bindings such as `lib/python/pxr/OmniCaeViz/_omniCaeViz.pyd ->
    # omniCaeViz.dll` resolve against the packaged schema libraries.
    #
    # Keep the returned add_dll_directory() handles alive for the lifetime of
    # the extension; dropping them removes the directories from the DLL search
    # path.
    if sys.platform == "win32":
        logger.info("Adding schema DLL search path '%s'", plugin_dir)
        handles.append(os.add_dll_directory(str(plugin_dir)))

    logger.info("Registering USD plugins from '%s'", plugin_dir)
    result = Plug.Registry().RegisterPlugins(str(plugin_dir))
    plugins = _get_schema_plugins(plugin_dir, result)
    if not plugins:
        logger.error("Failed to find registered USD schema plugins under '%s'", plugin_dir)

    handles.extend(_preload_registered_plugin_libraries(plugins))

    return handles


class Extension(omni.ext.IExt):
    def on_startup(self, extId):
        logger.info("starting extension %s", extId)
        # Keep both DLL directory handles and preloaded library handles alive
        # for the extension lifetime.
        self._handles = _load_usd_plugins(extId)

    def on_shutdown(self):
        self._handles = []
        logger.info("shutting down")
