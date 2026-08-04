# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.2.0]

- Added an importer for FLASH AMR `.flash` descriptors.
- Removed the retired ParaView color-map importer.
- Removed `.off` from the Trimesh importer to match the bundled file-format plugin.

## [1.1.0]

- Added importers for NanoVDB and Trimesh-backed surface mesh formats.
- Added importers for Eclipse INIT and UNRST reservoir result files.
- Removed file-format argument controls from importer panels and simplified `import_to_stage` helpers to `path` and `prim_path`.
- Added a package-level `import_to_stage(path, prim_path)` dispatcher and stopped exposing format-specific aliases from the package root.
- Removed module-level `import_to_stage` helpers and centralized importer dispatch/registration metadata.

## [1.0.0]

- Initial version with importers for CGNS, EDEM, EnSight, NPZ, OpenFOAM, VTK, and ColorMap file formats.
