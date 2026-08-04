# CAE USD Plugins

`omni.cae.usd_plugins` registers the CAE USD schema and file-format plugin runtime used by
Kit-CAE. The extension stages the prebuilt `cae_openusd_plugins` Packman package from
`_build/target-deps/cae_openusd_plugins` instead of building the native plugins inside Kit-CAE.

The packaged runtime keeps its install-tree layout inside the extension:

```text
plugin/usd/     USD schema and file-format plugin libraries and resources
lib/python/     cae_openusd_plugins bootstrap package and pxr schema modules
```

On startup the extension imports `cae_openusd_plugins` from the staged `lib/python` directory and calls
`cae_openusd_plugins.register_usd_plugins()`. That registers `plugin/usd` with USD and extends the active
`pxr` namespace so the packaged `pxr.OmniSci*` schema modules are available.

The runtime provides direct USD loading for CGNS, EDEM, EnSight, Eclipse reservoir, NumPy, NanoVDB,
OpenFOAM, VTK, and Trimesh files. It also provides support for axisymmetric FLASH AMR
datasets through `.flash` descriptor files.
