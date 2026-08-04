# Omni CAE Schema [omni.cae.schema]

This internal extension registers the Kit-CAE-owned `OmniCaeViz` schemas and the
legacy `OmniCae` compatibility schemas. It also provides their Python bindings.
The USD schema plugins are discovered and registered at startup by
`omni/cae/schema/extension.py`.

Schemas supplied by other USD plugin packages are imported directly from `pxr` after their provider extension is
enabled; they are not re-exported from `omni.cae.schema`. In particular, the
active `OmniSci*` scientific-data schemas come from `omni.cae.usd_plugins`.

See the repository's [Scientific Data Schemas](../../../../docs/UsdSchemas.md)
guide for schema ownership and the active-versus-legacy boundary.
