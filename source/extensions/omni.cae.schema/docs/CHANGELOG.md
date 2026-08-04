# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.5.0]

- Added the experimental `CaeVizIndeXAxisymmetricVolumeAPI` schema for direct
  native-coordinate NVIDIA IndeX rendering of axisymmetric volumes, with a ray
  sampling control that defaults to the finest native cell spacing.
- Removed the obsolete `textureResolution` property from `CaeVizPlanarSliceAPI`.
  The direction modes remain available and now drive geometry extraction rather
  than texture-based slicing.

## [2.4.0]

- Added the experimental multiple-apply `CaeArrayExpressionAPI` schema for
  versioned, named, lazily evaluated scientific arrays on any array-owning prim,
  including enabled state, display name, and compute-device selection.
- Added `CaeVizDatasetAxisymmetricRepresentationAPI`, a multiple-apply schema for
  configuring angular cells and a degree-based angular range on a selected dataset input.
- Set the default axisymmetric representation to 32 angular cells.

## [2.3.0]

- Added `CaeVizDatasetDualAPI`, a multiple-apply API schema that requests a dual representation for
  the corresponding selected dataset instance.

## [2.2.0]

- Added `CaeVizDatasetVoronoiPointCloudAPI`, a multiple-apply API schema that marks a selected
  dataset instance for conversion to an implicit Voronoi point-cloud model.
- Added `CaeVizIsoSurfaceAPI`, a single-apply API schema for `UsdGeomMesh` operators with an
  `isoValue` attribute controlling triangular iso-surface extraction.

## [2.1.0]

- Reworked extension startup to register this extension's bundled USD plugin schemas from its
  `usd/plugin` root. Generated schema modules are imported through the shared `pxr` namespace package.
- Removed the runtime dependency on `omni.cae.usd_plugins`; schemas supplied by that packaged
  extension, such as `OmniSciReservoir`, should be imported directly from `pxr` after enabling
  their provider extension.
- Added a templated `pxr_init.py` (used during schema codegen) so each generated namespace becomes a
  proper `pxr` sub-package without ad-hoc patching.
- Added a `CaeVizColormap` annotation attribute used by viz operators to look up their preferred colormap.

## [2.0.0]

- Removed the dependency on the obsolete legacy algorithms schema extension. `omni.cae.schema` now loads only the
  current shared and format schemas packaged in this extension.
- Updated schema packaging to keep native libraries directly under `usd/plugin` and generated Python bindings under
  `lib/python`, matching the standalone CAE USD plugin package layout.

## [1.6.0]

- Added `CaeVizDatasetSubsetAPI` multi-apply API schema. Restricts an operator's input dataset to cells
  inside an ROI prim's axis-aligned bounds. Attributes: `roi` (relationship to an ROI prim), `mode`
  (token: `all`/`any`/`centroid` — selects cells whose vertices are all-inside, any-inside, or whose
  centroid is inside, respectively), and `inflateBounds` (int percentage to inflate the ROI bounds
  before the test).

## [1.5.0]

- Moved generated schema Python modules under the `pxr` namespace so they can be imported as
  `from pxr import OmniCae, OmniCaeSids, OmniCaeVtk, ...`, matching the convention used by the
  USD schemas shipped by Pixar.
- Added a local `pxr/__init__.py` (using `pkgutil.extend_path`) that turns `pxr` into a namespace
  package so these schema modules are discovered alongside the `pxr` package shipped by USD.
- Updated `omni/cae/schema/*.py` wrappers to import from the `pxr.OmniCae*` packages.

## [1.4.0]

- Reworked schema packaging to keep generated USD artifacts under `usd/`, with USD plugin resources and
  native libraries under `usd/plugin/<SchemaName>`.
- Moved generated schema Python modules under the shared `usd/python/` tree and simplified
  `config/extension.toml` to use a single shared Python module path instead of per-schema entries.
- Removed schema `[[native.library]]` entries from `config/extension.toml`; schema plugins are now discovered and
  registered at startup by `omni/cae/schema/extension.py`.
- Updated startup loading to discover copied USD plugins from the built extension root instead of relying on a
  hardcoded schema list or source-tree-relative paths.

## [1.3.0]

- Added `CaeVizColormapTextureAPI` single-apply API schema. Carries a `cae:viz:colormapTexture:identifier`
  string attribute (set to a UUID at prim creation) used by `ColormapTextureManager` to name dynamic textures
  stably under USD composition.

## [1.2.0]

- Added `CaeVizPlanarSliceAPI` single-apply API schema for `UsdGeomMesh` prims representing a planar slice.
  Attributes: `textureResolution` (int2, default 512×512) and `mode`
  (token: `free`/`x`/`y`/`z`/`xy`/`xz`/`yz`/`xyz`).

## [1.1.0]

- Added `OmniCaeViz` schemas.

## [1.0.0] - 2024-11-09

- Initial version.
