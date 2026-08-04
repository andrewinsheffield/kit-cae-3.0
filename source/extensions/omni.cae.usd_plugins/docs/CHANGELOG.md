# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.4.0]

### Changed

- Updated the bundled prebuilt `cae_openusd_plugins` runtime.
- Made the Warp runtime available to the lazy NanoVDB array reader.

## [1.3.0]

### Added
- Added resolver-backed loading for self-contained and explicitly linked
  datasets, allowing file formats such as CGNS to load through app-provided
  OpenUSD asset resolvers.

### Changed
- Updated the bundled prebuilt `cae_openusd_plugins` runtime.
- Directory-scanning dataset layouts now report unsupported non-filesystem
  assets clearly instead of relying on scheme-specific clients.

## [1.2.0]

### Added
- Added native FLASH AMR schema and file-format support.

### Changed
- Updated the bundled prebuilt `cae_openusd_plugins` runtime.
- Narrowed Trimesh support to STL, PLY, and 3MF files.

### Removed
- Removed the ParaView color-map schema and file-format plugin.

## [1.1.0]

### Changed
- Updated the bundled prebuilt `cae_openusd_plugins` runtime.

## [1.0.0]

### Added
- Initial release.
- Packaged USD file-format plugin libraries directly under `usd/plugin`, with plugin resources kept under
  `usd/plugin/<plugin>/resources`, matching the standalone CAE USD plugin package layout.
- Bundled USD file-format plugins for CGNS, EDEM, EnSight, NPZ (as its own plugin), NanoVDB, OpenFOAM,
  Trimesh, VTK, and ColorMap formats.
- Added Eclipse reservoir INIT and UNRST file-format plugins with associated `OmniSciReservoirDataset`
  schemas.
- Added `pcp` dependencies on every file-format plugin so composition arc errors no longer occur when
  loading layers that reference these formats through payloads or references.
- Trimesh plugin's `plugInfo.json` now points at its real source location, fixing a Windows runtime
  registration warning.

### Changed
- Kit-CAE now stages the prebuilt `cae_openusd_plugins` Packman package from `_build/target-deps`
  instead of building these native plugins and OmniSci schemas from a source submodule.
