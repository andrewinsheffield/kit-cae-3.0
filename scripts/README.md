# Example Scripts

Sample scripts demonstrating Kit-CAE data import, visualization, and processing
workflows. Each script can be executed on launch:

```bash
./repo.sh launch -n omni.cae.kit -- --exec scripts/<script_name>.py
```

## CGNS — StaticMixer.cgns

| Script | Description |
|--------|-------------|
| `example_bounding_box.py` | Bounding box creation around an imported dataset |
| `example_faces.py` | Surface mesh face visualization with field coloring |
| `example_glyphs.py` | Glyph (arrow) rendering with multi-field mapping |
| `example_iso_surface.py` | Temperature iso-surface extraction with field coloring |
| `example_planar_slice.py` | Geometry-based axis-aligned planar slices |
| `example_points.py` | Point cloud with field-based sizing |
| `example_slice.py` | IndeX volume-plane slicing on an irregular grid |
| `example_streamlines.py` | Streamline tracing through a velocity field |
| `example_volume.py` | Volume rendering of a scalar field |
| `example_nvdb_slice.py` | NanoVDB slicing with animation |

## CGNS — hex_timesteps.cgns

| Script | Description |
|--------|-------------|
| `example_temporal_interpolation.py` | Temporal interpolation on a time-varying hex mesh |

## FLASH — axisymmetric_wavelet.flash

| Script | Description |
|--------|-------------|
| `example_flash_axisymmetric_volume.py` | Direct axisymmetric rendering of native-resolution FLASH AMR |
| `example_flash_iso_surface.py` | Iso-surface extraction from reconstructed axisymmetric FLASH topology |
| `example_flash_planar_slice.py` | Geometry-based planar slices through reconstructed FLASH topology |

The FLASH examples use the checked-in synthetic wavelet dataset and its `dens`
field by default. Set `FLASH_DATASET` or `FLASH_FIELD` to override either.
The volume example also accepts `FLASH_SAMPLING_DISTANCE_SCALE`; the iso-surface
example accepts `FLASH_ISO_VALUE`; and both reconstructed-topology examples
accept `FLASH_ANGULAR_CELLS`. Use `FLASH_SLICE_MODE` to select the planar-slice
direction mode.

## NumPy — disk_out_ref.npz

| Script | Description |
|--------|-------------|
| `example_npz_flow.py` | Flow simulation with smoke injection |
| `example_npz_point_cloud.py` | Point cloud with Gaussian splatting |
| `example_npz_streamlines.py` | Streamlines from NumPy arrays |

## VTK — headsq.vti

```bash
./repo.sh launch -n omni.cae.kit -- --exec scripts/example_headsq_vti.py
```

| Script | Description |
|--------|-------------|
| `example_headsq_vti.py` | Native VTI import with volume rendering and ROI |

## Developer Notes

These scripts are tested as part of the
[`omni.cae.bundle`](../source/extensions/omni.cae.bundle/python/tests/test_examples.py)
extension. If adding a new script, ensure that a test has been added for that
script in `omni.cae.bundle`.
