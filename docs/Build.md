# Build Instructions

This document provides detailed instructions for building Kit-CAE on Windows and Linux platforms.

## Prerequisites

### Windows

Visual Studio 2019 or 2022, along with the corresponding Windows SDK and build tools for C++ applications, must be installed on your system.

### Linux

Standard development tools including GCC/Clang compiler toolchain.

## Building Kit-CAE

### Quick Start

**On Windows:**

```sh
repo.bat build -r
```

**On Linux:**

```sh
./repo.sh build -r
```

Schema source code is automatically generated during fetch and compiled during build.

### Configuration Options

On Windows, you can edit [repo.toml](../repo.toml) to set `vs_version = "vs2019"` or `vs_version = "vs2022"` to select a specific Visual Studio version, or pass it on the command line:

```sh
repo.bat --set-token vs_version=vs2022 build -r
```

Use `./repo.sh --help` or `./repo.sh [tool] --help` to view all available build options.

## Optional Dependencies

Legacy extensions rely on external Python packages that are not bundled with
Kit-CAE. Install these dependencies only when working with stages created in
Kit-CAE 2.0 or earlier.

### Packages

| Package | Version | Used by | Purpose |
|---------|---------|---------|---------|
| vtk | 9.6.2 | `omni.cae.delegate.vtk` | Legacy VTK delegate |
| h5py | 3.16.0 | `omni.cae.delegate.edem` | Legacy EDEM delegate |
| lz4 | 4.4.5 | `omni.cae.delegate.vtk` | Legacy compressed VTU reader |

Current stages use native OpenUSD file-format plugins, including the VTK and
EDEM readers included in the default build, and do not require these packages.

### Installation

After building with `repo.bat build -rx` on Windows or `./repo.sh build -rx`
on Linux, install the optional packages into the staged Python runtime:

```sh
# On Windows
repo.bat pip_download

# On Linux
./repo.sh pip_download
```

The command installs the versions pinned in `tools/deps/requirements.txt`.
Relaunch the application afterward; no additional launch flags are required.

## Selecting Kit SDK Version

Kit-CAE can be built against different versions of the Omniverse Kit SDK. Available versions are managed in `tools/kit-versions.json`.

### Interactive Selection

```sh
# On Linux
./repo.sh select_kit_version

# On Windows
repo.bat select_kit_version
```

This displays available Kit versions and prompts you to select one. Your selection is saved to `.kit_selection.json`.

### Non-Interactive Selection

```sh
# Select a specific version
./repo.sh select_kit_version --version 110.1.2

# Use default version
./repo.sh select_kit_version --default

# Use tracked version (ideal for CI/CD)
./repo.sh select_kit_version --auto
```

### Clean Builds After Version Changes

**After changing Kit SDK versions, you must perform clean builds:**

```sh
# On Linux
./repo.sh build -r -x # or use -rx, instead of -r -x

# On Windows
repo.bat build -r -x  # or use -rx, instead of -r -x
```

These commands:
- `build -x`: Perform a clean build of all extensions

For additional details see [Selecting Kit SDK Version](./SelectKitVersion.md).

## Using Local Dependency Builds

Normal builds download `warp_simdata` and `cae_openusd_plugins` from Packman. To
test locally built versions instead, point Kit-CAE at the Packman packages
produced by their sibling repositories:

```sh
# Linux
export KIT_CAE_WARP_SIMDATA_PACKAGE=/absolute/path/to/warp_simdata@<version>.zip
export KIT_CAE_OPENUSD_PLUGINS_PACKAGE=/absolute/path/to/cae_openusd_plugins@<version>.zip
./repo.sh build -rx
```

```bat
:: Windows Command Prompt
set KIT_CAE_WARP_SIMDATA_PACKAGE=C:\absolute\path\to\warp_simdata@<version>.zip
set KIT_CAE_OPENUSD_PLUGINS_PACKAGE=C:\absolute\path\to\cae_openusd_plugins@<version>.zip
repo.bat build -rx
```

Both overrides are optional and may be used independently. The normal dependency
fetch still runs first. Afterward, Kit-CAE extracts each local package under
`_build/local-deps` and redirects its corresponding `_build/target-deps` path to
the extracted package. This makes a normal build, including schema generation and
extension staging, consume the local artifacts. Restart any running Kit process
after rebuilding because already imported Python modules are not reloaded in
place.

Use a clean build (`build -rx`) whenever either variable is set, changed, or unset.
The clean removes `_build`, ensuring repo pip and Packman caches cannot leave the
previous dependency payload staged. Incremental builds are safe while the override
values remain unchanged.

Use a `cae_openusd_plugins` package built for the selected Kit SDK's OpenUSD
version, Python ABI, platform, and C++ ABI. The package must be the ZIP artifact
produced by the sibling repository's CPack/Packman package build, not its install
directory. Kit-CAE compares the package metadata with the published package selected
by the normal fetch and stops before staging if the package name, OpenUSD variant or
version, Python ABI, or platform does not match.

Unset the variables to return to published dependencies:

```sh
unset KIT_CAE_WARP_SIMDATA_PACKAGE KIT_CAE_OPENUSD_PLUGINS_PACKAGE
./repo.sh build -rx
```

On Windows, use `set KIT_CAE_WARP_SIMDATA_PACKAGE=` and
`set KIT_CAE_OPENUSD_PLUGINS_PACKAGE=` before running `repo.bat build -rx`. No
source-controlled dependency pins are changed.
