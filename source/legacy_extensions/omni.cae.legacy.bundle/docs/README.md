# CAE Legacy Data Delegate Bundle

This bundle enables the deprecated `omni.cae.data` Data Delegate extension and
legacy file delegate extensions, including the legacy Property window widgets
for delegate-backed `CaeFieldArray` prims.

Use it only for compatibility with stages that still rely on legacy
`CaeDataSet` / `CaeFieldArray` delegate-backed array loading.

Legacy asset importers and the old standalone CGNS USD file-format plugin have
been removed. Use `omni.cae.usd_plugins` and `omni.cae.usd_plugins_importers`
for supported file loading and import workflows.
