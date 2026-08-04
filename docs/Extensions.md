# Extensions Overview

Kit-CAE is composed of modular Omniverse extensions organised into the following categories.
This catalog covers every `config/extension.toml` under `source/extensions` and
`source/legacy_extensions`.

| Category | Extensions |
|----------|-----------|
| [USD Schemas](#usd-schemas) | `omni.cae.schema`, schemas supplied by `omni.cae.usd_plugins` |
| [Data Infrastructure](#data-infrastructure) | `omni.cae.core`, `omni.cae.simdata` |
| [USD File Formats & Importers](#usd-file-formats--importers) | `omni.cae.usd_plugins`, `omni.cae.usd_plugins_importers` |
| [Visualization](#visualization) | `omni.cae.viz`, `omni.cae.index` |
| [UI](#ui) | `omni.cae.context_menu`, `omni.cae.property.bundle`, `omni.cae.widget.stage_icons` |
| [Utilities](#utilities) | `omni.cae.bundle`, `omni.cae.exVars`, `omni.cae.startup`, `omni.cae.testing`, `omni.cae.pip_prebundle` |
| [Legacy Compatibility](#legacy-compatibility) | `omni.cae.legacy.bundle`, `omni.cae.data`, `omni.cae.simdata.legacy`, `omni.cae.property.legacy`, `omni.cae.delegate.*` |
| [Legacy Native Libraries](#legacy-native-libraries) | `omni.cae.cgns_libs`, `omni.cae.hdf5_libs` |

---

## USD Schemas

#### [`omni.cae.schema`](../source/extensions/omni.cae.schema/)

Loads the Kit-CAE-owned visualization and compatibility schemas into Omniverse. USD plugins must be registered early during initialisation; this extension registers its `usd/plugin` root at startup, where the top-level `plugInfo.json` includes each plugin's `resources` directory.

The active scientific-data schemas (`OmniSciDataset`, `OmniSciArrayAPI`, `OmniSciFieldAPI`, and format-specific APIs) are supplied by the prebuilt runtime registered by `omni.cae.usd_plugins`. The older `CaeDataSet` and `CaeFieldArray` schemas remain available for legacy stages. See [Scientific Data Schemas](./UsdSchemas.md) for the boundary between the two models.

---

## Data Infrastructure

#### [`omni.cae.core`](../source/extensions/omni.cae.core/)

Shared active Python utilities for USD traversal, array conversion, progress reporting, command helpers, cache invalidation, and Warp initialization. Active USD-plugin and SimData/Viz workflows depend on this extension instead of the deprecated Data Delegate API.

#### [`omni.cae.simdata`](../source/extensions/omni.cae.simdata/)

Provides Warp SimData-backed data processing operators used by `omni.cae.viz` for visualization operations such as streamlines, face extraction, point splats, and voxelization.

---

## Legacy Compatibility

These extensions live under `source/legacy_extensions` and support old
`CaeDataSet` / `CaeFieldArray` stages. New workflows should use the active
OmniSci extensions described above.

### Compatibility runtime and UI

#### [`omni.cae.legacy.bundle`](../source/legacy_extensions/omni.cae.legacy.bundle/)

Convenience bundle for the deprecated Data Delegate runtime, legacy SimData
converters, legacy Property widgets, and all legacy file delegates. Enable this
only for stages that still require delegate-backed field arrays.

#### [`omni.cae.data`](../source/legacy_extensions/omni.cae.data/)

Deprecated compatibility extension providing the **Data Delegate API** for legacy stages. New file-format and lazy-loading work belongs in `omni.cae.usd_plugins` and active consumers should use `omni.cae.core`.

#### [`omni.cae.simdata.legacy`](../source/legacy_extensions/omni.cae.simdata.legacy/)

Deprecated SimData converter commands for legacy datasets. The active
`omni.cae.simdata` extension handles OmniSci datasets directly.

#### [`omni.cae.property.legacy`](../source/legacy_extensions/omni.cae.property.legacy/)

Deprecated Property window widgets for inspecting delegate-backed
`CaeDataSet` and `CaeFieldArray` prims.

### File delegates

The following extensions register per-format array readers with
`omni.cae.data`.

#### [`omni.cae.delegate.cgns`](../source/legacy_extensions/omni.cae.delegate.cgns/)

Reads data from `CaeCgnsFieldArray` prims — field arrays stored in CGNS (`.cgns`) files.

#### [`omni.cae.delegate.hdf5`](../source/legacy_extensions/omni.cae.delegate.hdf5/)

Reads data from `CaeHdf5FieldArray` prims — field arrays stored in HDF5 files.

#### [`omni.cae.delegate.npz`](../source/legacy_extensions/omni.cae.delegate.npz/)

Reads data from `CaeNumPyFieldArray` prims — field arrays stored in NumPy `.npy` / `.npz` files. Pure-Python implementation.

#### [`omni.cae.delegate.nvdb`](../source/legacy_extensions/omni.cae.delegate.nvdb/)

Reads NanoVDB (`.nvdb`) volumes referenced by legacy CAE field-array prims.

#### [`omni.cae.delegate.vtk`](../source/legacy_extensions/omni.cae.delegate.vtk/)

Reads data from VTK field arrays stored in `.vti`, `.vtu`, `.vts`, `.vtp`, and `.vtk` files.

#### [`omni.cae.delegate.ensight`](../source/legacy_extensions/omni.cae.delegate.ensight/)

Reads data from EnSight Gold datasets.

#### [`omni.cae.delegate.openfoam`](../source/legacy_extensions/omni.cae.delegate.openfoam/)

Reads data from OpenFOAM mesh and field files.

#### [`omni.cae.delegate.trimesh`](../source/legacy_extensions/omni.cae.delegate.trimesh/)

Reads surface mesh formats (STL, OBJ, PLY, OFF, GLTF/GLB, and others) via the `trimesh` Python library.

#### [`omni.cae.delegate.edem`](../source/legacy_extensions/omni.cae.delegate.edem/)

Reads EDEM particle simulation datasets from HDF5 files.

---

## USD File Formats & Importers

#### [`omni.cae.usd_plugins`](../source/extensions/omni.cae.usd_plugins/)

Registers the CAE USD schema and file-format plugin runtime. The extension stages the prebuilt
`cae_openusd_plugins` Packman package from `_build/target-deps/cae_openusd_plugins`, preserving its
`plugin/usd` and `lib/python` install-tree layout so the package's Python bootstrap can register
the plugin root and extend the active `pxr` namespace. This extension replaces the retired
standalone `omni.cae.file_format.cgns` extension.

The packaged runtime provides direct USD loading for CGNS, EDEM, EnSight, Eclipse reservoir, FLASH
AMR, NumPy, NanoVDB, OpenFOAM, VTK, and Trimesh files.

#### [`omni.cae.usd_plugins_importers`](../source/extensions/omni.cae.usd_plugins_importers/)

Adds asset-importer entries and the shared `import_to_stage(path, prim_path, **args)` helper for
files handled by `omni.cae.usd_plugins`. Importers author payload prims plus matching
`OmniSciFileFormatArgs*` API schemas so the source file remains in its native format. This extension
replaces the retired per-format `omni.cae.importer.*` extensions.

---

## Visualization

#### [`omni.cae.viz`](../source/extensions/omni.cae.viz/)

The **CAE visualization operator runtime**. Monitors the USD stage for prims with `CaeVizOperatorAPI` applied, then executes the corresponding visualization algorithm — surface extraction, streamlines, points, glyphs, or volume rendering. Algorithms write their results back as standard USD geometry prims so any Hydra renderer can display them.

See [CAE Viz Schemas](./CaeVizSchemas.md) for the full schema reference and authoring guide.

#### [`omni.cae.index`](../source/extensions/omni.cae.index/)

Provides NVIDIA IndeX Python bindings and generic compute tasks for IndeX-based volume rendering. Used by the `CaeVizIndeXVolumeAPI` operator in `omni.cae.viz`.

---

## UI

#### [`omni.cae.context_menu`](../source/extensions/omni.cae.context_menu/)

Adds CAE-specific entries to the Stage widget context menu, giving users one-click access to common CAE operations (e.g. adding visualization operators to a dataset prim).

#### [`omni.cae.property.bundle`](../source/extensions/omni.cae.property.bundle/)

Custom property panel widgets for CAE schema attributes — provides richer UI controls (e.g. colour pickers, range sliders) instead of generic USD property editors.

#### [`omni.cae.widget.stage_icons`](../source/extensions/omni.cae.widget.stage_icons/)

Custom icons for active `OmniSciDataset` prims and legacy CAE prim types in the Stage widget.

---

## Utilities

#### [`omni.cae.bundle`](../source/extensions/omni.cae.bundle/)

Meta-extension that depends on the active Kit-CAE extensions. Enabling this
single extension brings in the current CAE stack — useful as the single
dependency in application `.kit` files. Legacy compatibility extensions are
not enabled by this bundle.

#### [`omni.cae.exVars`](../source/extensions/omni.cae.exVars/)

Reads `expressionVariables` from the command line and injects them into all session layers at stage load. Useful for parameterising USD files (e.g. data paths) at launch time without editing assets.

#### [`omni.cae.startup`](../source/extensions/omni.cae.startup/)

Opens the USD file configured by `exts."omni.cae.startup".usdFile` after RTX
delivers its first frame. This allows automated launches to defer stage loading
until the renderer is ready.

#### [`omni.cae.testing`](../source/extensions/omni.cae.testing/)

Shared testing utilities and fixtures for Kit-CAE extension test suites.

#### [`omni.cae.pip_prebundle`](../source/extensions/omni.cae.pip_prebundle/)

Bundles Python pip packages required by other CAE extensions so they are available offline without a live pip install.

---

## Legacy Native Libraries

These internal extensions live under `source/legacy_extensions` and ship compiled native libraries
needed only by the legacy data delegates. They have no public Python API. Active file-format support
comes from `omni.cae.usd_plugins` and does not depend on these extensions.

| Extension | Libraries provided |
|-----------|-------------------|
| [`omni.cae.cgns_libs`](../source/legacy_extensions/omni.cae.cgns_libs/) | CGNS C library |
| [`omni.cae.hdf5_libs`](../source/legacy_extensions/omni.cae.hdf5_libs/) | HDF5 C library |
