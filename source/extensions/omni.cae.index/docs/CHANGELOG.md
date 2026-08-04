# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.1.0]

- Replaced VDB `IFieldArray` adoption in the Python bindings with DLPack-based buffer adoption,
  removing the legacy data-extension coupling for IndeX VDB importers.
- Dropped the `rtx.hydra.readTransformsFromFabricInRenderDelegate` runtime setting that the IndeX
  bundle previously relied on.

## [1.0.1]

- Updated documentation to point CAE visualization operator users to `omni.cae.viz`.

## [1.0.0]

- Initial version, split from `omni.cae.algorithms.index`.
- Provides IndeX Python bindings (`_omni_cae_index`) and generic Python-based importers
  (`PythonImporter`) and compute tasks (`PythonComputeTask`).
