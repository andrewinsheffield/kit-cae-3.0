# Dataset Representations

Representation APIs configure how a selected scientific dataset is converted
before an operator executes. Apply them using the same instance name as the
matching `DatasetSelectionAPI`, normally `"source"`.

## Axisymmetric FLASH Reconstruction

`DatasetAxisymmetricRepresentationAPI:source` revolves native FLASH
`(radius, axial)` data into a concrete representation. The default is a full
revolution with 32 angular cells.

```python
api = cae_viz.DatasetAxisymmetricRepresentationAPI.Apply(operator, "source")
api.CreateAngularCellsAttr().Set(48)
api.CreateMinimumAngleAttr().Set(0.0)
api.CreateMaximumAngleAttr().Set(180.0)
```

`angularCells` must be at least three. Angles are in degrees and must satisfy
`0 <= minimumAngle < maximumAngle <= 360`.

## Dual Representation

`DatasetDualAPI:source` requests a dual topology when the selected dataset
model supports it. FLASH AMR is the initial supported model. Iso-surface and
planar-slice create commands apply the axisymmetric and dual requests
automatically for supported inputs:

```python
if not operator.HasAPI(cae_viz.DatasetDualAPI, "source"):
    cae_viz.DatasetDualAPI.Apply(operator, "source")
```

Do not assume every dataset supports dual conversion. Prefer the create-command
default or a capability check through `omni.cae.simdata`.

## Direct Axisymmetric Volume

Use the direct path when the desired output is an IndeX volume and avoiding
revolved geometry or finest-level 3-D resampling matters:

```python
await execute_command(
    "CreateCaeVizVolume",
    dataset_path=dataset_path,
    prim_path=volume_path,
    type="axisymmetric",
)
volume = stage.GetPrimAtPath(volume_path)
cae_viz.FieldSelectionAPI(volume, "colors").CreateFieldNamesAttr().Set(
    [field_name]
)
cae_viz.IndeXAxisymmetricVolumeAPI(
    volume
).CreateSamplingDistanceScaleAttr().Set(1.0)
```

This path requires NVIDIA IndeX. It samples compact native-resolution FLASH AMR
levels through an XAC shader. `samplingDistanceScale` controls ray-sampling
quality relative to the finest native cell spacing.

Apply `DatasetAxisymmetricRepresentationAPI:source` to author a partial angular
range for the direct volume. `angularCells` does not tessellate this analytical
path; only the angle range affects clipping.

Repository examples:

- `scripts/example_flash_axisymmetric_volume.py`
- `scripts/example_flash_iso_surface.py`
- `scripts/example_flash_planar_slice.py`
