-- SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: LicenseRef-NvidiaProprietary
--
-- NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
-- property and proprietary rights in and to this material, related
-- documentation and any modifications thereto. Any use, reproduction,
-- disclosure or distribution of this material and related documentation
-- without an express license agreement from NVIDIA CORPORATION or
--  its affiliates is strictly prohibited.

local ext = get_current_extension_info()
local cae_openusd_plugins = "%{root}/_build/target-deps/cae_openusd_plugins"
local package_licenses = "%{root}/_build/PACKAGE-LICENSES"

-- Extension wrapper around the prebuilt cae_openusd_plugins Packman package.
-- Keep the package install-tree layout intact so its Python bootstrap resolves
-- the extension root as the runtime prefix.
project_ext(ext)
    repo_build.prebuild_link {
        { "docs", ext.target_dir.."/docs" },
        { "python", ext.target_dir.."/omni/cae/usd_plugins" },
        { cae_openusd_plugins.."/plugin", ext.target_dir.."/plugin" },
        { cae_openusd_plugins.."/lib", ext.target_dir.."/lib" },
        -- project_ext links PACKAGE-LICENSES/dependencies to the repo-wide
        -- package license aggregate. Add dependency licenses to that aggregate
        -- instead of creating a nested link under the extension directory.
        { cae_openusd_plugins.."/PACKAGE-LICENSES", package_licenses.."/cae_openusd_plugins" },
    }
    repo_build.prebuild_copy {
        { cae_openusd_plugins.."/cae-package-metadata.env", ext.target_dir.."/cae-package-metadata.env" },
    }
