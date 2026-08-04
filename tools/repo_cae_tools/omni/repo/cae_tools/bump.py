# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

r"""
Extends omni.repo.kit_tools.bump to support bumping the package version.
"""
import os

import omni.repo.kit_tools.bump
import omni.repo.man as repo_man
from packaging.version import Version


def bump_version(version, component) -> str:
    ver = Version(version)
    if str(ver) != version:
        raise ValueError(f"Version must use canonical PEP 440 spelling: {version!r}")

    release = ver.release + (0,) * (3 - len(ver.release))
    major, minor, patch = release[:3]

    if component == "prerelease":
        base = f"{major}.{minor}.{patch}"
        if ver.dev is not None:
            new_ver = Version(f"{base}.dev{ver.dev + 1}")
        elif ver.pre is not None:
            phase, number = ver.pre
            new_ver = Version(f"{base}{phase}{number + 1}")
        elif ver.post is None:
            new_ver = Version(f"{base}rc1")
        else:
            raise ValueError(f"Cannot prerelease-bump post release {version!r}")
    elif component == "patch":
        new_ver = Version(f"{major}.{minor}.{patch + 1}")
    elif component == "minor":
        new_ver = Version(f"{major}.{minor + 1}.0")
    elif component == "major":
        new_ver = Version(f"{major + 1}.0.0")
    else:
        raise ValueError(f"Unknown version component {component!r}")

    return str(new_ver)


def bump(options, config):
    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice

    tool_config = config.get("repo_bump", {})
    pkg_version_md = repo_man.resolve_tokens(tool_config.get("pkg_version_md", "${root}/VERSION.md"))
    if not os.path.exists(pkg_version_md):
        print(f"[error] {pkg_version_md} not found!")
        return False

    with open(pkg_version_md, "rt") as f:
        version = f.readline().strip()

    proceed = inquirer.confirm(message=f"Proceed to bump package version from {version}?", default=False).execute()

    if not proceed:
        return

    component = inquirer.select(
        message="Which package version component (X) to bump?",
        choices=[
            Choice(value="prerelease", name="Prerelease (1.0.0rc1 / 1.1.0.dev0)"),
            Choice(value="patch", name="Patch (1.0.1)"),
            Choice(value="minor", name="Minor (1.1.0)"),
            Choice(value="major", name="Major (2.0.0)"),
        ],
        default=None,
    ).execute()

    ver = bump_version(version, component)
    with open(pkg_version_md, "wt") as f:
        f.write(ver)
        print(f"Bumped {pkg_version_md} {version} -> {ver}")


def setup_repo_tool(parser, config):
    # Kit app and extension manifests require SemVer, so leave the standard Kit
    # bump callback in place. The repository package version below uses PEP 440.
    og_bump = omni.repo.kit_tools.bump.setup_repo_tool(parser, config)

    def run_repo_tool(options, config):
        og_bump(options, config)
        bump(options, config)

    return run_repo_tool
