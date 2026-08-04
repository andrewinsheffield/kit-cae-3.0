# Changelog

All notable changes to the CAE Extension Bundle will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [3.1.0]

- Reorganized dependencies for the new layered architecture: pulls in `omni.cae.usd_plugins`
  (load-ordered alongside the schemas), `omni.cae.core`, and `omni.cae.usd_plugins_importers`,
  and drops the per-format `omni.cae.data`, `omni.cae.file_format.cgns`, `omni.cae.delegate.*`,
  `omni.cae.importer.*`, and `omni.cae.index` direct dependencies — those flow in through the
  USD-plugin importers and core stacks instead.
- Dropped the bundled `rtx.hydra.readTransformsFromFabricInRenderDelegate` setting that the IndeX
  bundle previously required.

## [3.0.0]

- Removed dependencies on legacy CAE extensions. The bundle now loads the current schema, data delegate, DAV, importer,
  delegate, visualization, and UI stack only.
- Updated bundled settings text for RT-backed visualization operators.

## [2.1.0]

- Added dependency on `omni.cae.startup` so the bundled apps pick up the optional startup-USD-file behaviour.

## [2.0.0]

- Added dependency on `omni.cae.viz`.
- Added example scripts to the extension package along with testing for those example scripts.

## [1.0.0]

- Initial release of `omni.cae.bundle` extension
