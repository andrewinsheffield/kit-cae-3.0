# Iso-Surface Visualization

Use an iso-surface to extract triangular geometry where a scalar field equals a
chosen value. Query the field range first and choose an iso-value inside it.

```python
iso_path = "/World/CAE/IsoSurface"
await execute_command(
    "CreateCaeVizIsoSurface",
    dataset_path=dataset_path,
    prim_path=iso_path,
)

iso = stage.GetPrimAtPath(iso_path)
cae_viz.IsoSurfaceAPI(iso).CreateIsoValueAttr().Set(float(iso_value))
cae_viz.FieldSelectionAPI(iso, "contour").CreateFieldNamesAttr().Set(
    [contour_field]
)
cae_viz.FieldSelectionAPI(iso, "colors").CreateFieldNamesAttr().Set(
    [color_field]
)
await wait_for_update()
```

`contour` must resolve to one scalar field. Point- and cell-associated fields
are supported; cell values are averaged onto points before extraction. The
optional `colors` field is reconstructed and interpolated onto the generated
surface.

For time-varying data, generated topology is recomputed at dataset samples. It
is not interpolated between samples. An iso-value that produces no points or
triangles intentionally hides the output until a later execution becomes
renderable.

For supported axisymmetric FLASH data, the create command authors the matching
axisymmetric and dual representation requests automatically. Adjust the
axisymmetric representation only after command creation:

```python
representation = cae_viz.DatasetAxisymmetricRepresentationAPI(iso, "source")
representation.CreateAngularCellsAttr().Set(32)
representation.CreateMinimumAngleAttr().Set(0.0)
representation.CreateMaximumAngleAttr().Set(180.0)
```

Repository examples:

- `scripts/example_iso_surface.py`
- `scripts/example_flash_iso_surface.py`
