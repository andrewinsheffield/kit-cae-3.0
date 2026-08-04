# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [3.4.0]

### Added
- Added **CAE Sources > Colormap** for directly creating a texture-ready
  Colormap prim.
- Added **Copy Opacity LUT Texture URL** alongside the explicitly named
  **Copy Color LUT Texture URL** action. Field-selection suggestions now
  include `opacity` for MDL-shaded visualization operators.
- Added the experimental **axisymmetric** volume type, which authors
  `CaeVizIndeXAxisymmetricVolumeAPI` instead of a subset or voxelization recipe.
- Added experimental **Add API > CAE > Array Expression** authoring with identifier validation for
  authoring named derived arrays on scientific-array owner prims.
- Array expressions can be applied directly to untyped scientific-field owner
  prims such as CGNS `FlowSolution` prims.
- Adding an API now rebuilds the current Property panel immediately so the new schema frame appears
  without changing the prim selection.
- Added **Add API > CAE > Dataset Axisymmetric Representation** for configuring a selected
  dataset input's angular cells and angle range.

### Changed
- Renamed **Add API > CAE > Colormap Texture** to **Colormap Textures
  (Color + Opacity)** to reflect the two dynamic textures it publishes.

### Fixed
- **Volume Slice** is now shown only for a single `UsdVolVolume` prim; `OmniSciDataset` inputs must
  first be converted with **CAE Operators > Volume**.
- Context-menu eligibility now consistently handles mixed CAE/OmniSci dataset selections, rejects
  partially invalid selections, and supports OmniSci datasets in Flow dataset actions.
- **Add API > CAE > Colormap Texture** is now limited to `Colormap` prims and refreshes the Property
  panel after applying the API. Add API entries are hidden when no prim is selected.

## [3.3.0]

### Added
- Added **Add API > CAE > Dataset Dual** for explicitly requesting a dual representation on an
  existing dataset-selection instance.

## [3.2.0]

### Added
- **Add API > CAE > Dataset Voronoi Point Cloud** context menu entry: applies
  `CaeVizDatasetVoronoiPointCloudAPI` to a selected prim with instance-name suggestions from
  existing `CaeVizDatasetSelectionAPI` applications.
- **CAE Operators > Iso Surface** context menu entry: creates an iso-surface mesh for each selected
  CAE or OmniSci dataset.

## [3.1.0]

### Added
- Operator and **Add API** context menu entries now accept `OmniSciDataset` prims authored by the
  USD plugins (alongside existing `CaeDataSet`-typed prims), so reservoir, NPZ, and other plugin-backed
  datasets can be visualized directly.

### Fixed
- Type-acceptance checks now guard `Usd.Prim.IsA` against prim types that are not registered with the
  current schema registry, so menus no longer raise on stages that reference unknown CAE types.

## [3.0.0]

### Removed
- Removed legacy algorithm and legacy Flow context menus. The extension now exposes only the current CAE source,
  visualization operator, Flow, LUT, and API authoring actions.

## [2.4.0]

### Added
- **Add API > CAE > Dataset Subset** context menu entry: applies `CaeVizDatasetSubsetAPI` to a selected
  prim. Instance-name suggestions come from existing `CaeVizDatasetSelectionAPI` applications, matching
  the other per-selection dataset APIs.

## [2.3.0]

### Changed
- **Copy LUT Texture URL** now only appears for `Colormap` prims that have `CaeVizColormapTextureAPI` applied
  (previously shown for all `Colormap` prims).

### Added
- **Add API > CAE > Colormap Texture** context menu entry: applies `CaeVizColormapTextureAPI` to a selected
  `Colormap` prim and stamps a stable UUID identifier used by `ColormapTextureManager` to publish the dynamic
  LUT texture.

## [2.2.0]

### Added
- **Copy LUT Texture URL** context menu entry: right-clicking a `Colormap` prim in the stage now shows a
  *Copy LUT Texture URL* option that copies the `dynamic://` texture URL for that prim to the clipboard.

## [2.1.0]

- Added `OperatorsPlanarSlice` context menu action for creating a `PlanarSlice` operator on selected CAE datasets.
  Opens a dialog to choose between `standard` (mesh-based probe) and `nanovdb` (voxelized) execution types.
- `TypeSelectionDialog` API updated: `options`/`default_index`/`field_label` constructor arguments replaced by a
  `selections` list of `(label, choices)` pairs, enabling multi-field configuration dialogs.

## [2.0.0]

- Refactored to add support for CAE Operator. All CAE Algorithm specific options
  are marked as legacy and are only shown when legacy UI is enabled through settings.

## [1.0.0]

- Initial version.
