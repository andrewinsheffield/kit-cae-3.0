-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: LicenseRef-NvidiaProprietary
--
-- NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
-- property and proprietary rights in and to this material, related
-- documentation and any modifications thereto. Any use, reproduction,
-- disclosure or distribution of this material and related documentation
-- without an express license agreement from NVIDIA CORPORATION or
--  its affiliates is strictly prohibited.

local ext = get_current_extension_info()

project_ext (ext)

repo_build.prebuild_link {
    { "docs", ext.target_dir.."/docs" },
    { "python", ext.target_dir.."/omni/cae/core" },
}

project_ext_bindings {
    ext = ext,
    project_name = "omni.cae.core.python",
    module = "_omni_cae_core",
    src = "bindings/python",
    target_subdir = "omni/cae/core"
}
    add_usd({"usd", "sdf", "vt", "usdUtils"})
    add_cae_usd_schemas({"omniCae"})
    filter { "system:windows" }
        -- Suppress USD header warnings that Kit treats as errors under MSVC.
        disablewarnings { "4244", "4251", "4305" }
    filter { "system:linux" }
        disablewarnings { "error=deprecated-declarations", "error=cpp", "deprecated" }
    filter {}
