# Launch Instructions

This document describes how to launch Kit-CAE and run sample scripts.

## Launching the Application

### Basic Launch

After building (see [Build Instructions](./Build.md)), launch the application:

```sh
# On Windows
repo.bat launch -n omni.cae.kit

# On Linux
./repo.sh launch -n omni.cae.kit
```

### Launching the legacy VTK Python variant

The default application opens VTK files through the native OpenUSD plugin. The
VTK application variant is retained for legacy compatibility workflows that
import the VTK Python package:

```sh
# On Windows
repo.bat launch -n omni.cae_vtk.kit

# On Linux
./repo.sh launch -n omni.cae_vtk.kit
```

Install the optional packages first; see
[Optional Dependencies](./Build.md#optional-dependencies). This is not required
for normal `.vtk`, `.vti`, `.vtr`, `.vts`, `.vtp`, or `.vtu` imports.

## Running Sample Scripts

Kit-CAE includes several sample scripts demonstrating various features. Scripts are located in the [scripts](../scripts/) directory.

### Running Scripts

Run sample scripts with the default application:

```sh
# On Linux
./repo.sh launch -n omni.cae.kit -- --exec scripts/example_bounding_box.py

# On Windows
repo.bat launch -n omni.cae.kit -- --exec scripts/example_bounding_box.py
```

### VTI Volume Example

The VTI volume example uses the native OpenUSD VTK file-format plugin and does
not require the optional VTK Python package:

```sh
# On Linux
./repo.sh launch -n omni.cae.kit -- --exec scripts/example_headsq_vti.py

# On Windows
repo.bat launch -n omni.cae.kit -- --exec scripts/example_headsq_vti.py
```

### Available Sample Scripts

Browse the [scripts](../scripts/) directory to see all available examples, including:
- Bounding box calculations
- Streamline generation
- Data visualization workflows
- And more...

## User Guide

For step-by-step instructions on using Kit-CAE features and workflows, refer to the [Online User Guide](https://docs.omniverse.nvidia.com/guide-kit-cae/latest/index.html).
