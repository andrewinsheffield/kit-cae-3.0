# Axisymmetric FLASH wavelet fixture

This directory contains a deterministic, synthetic FLASH PARAMESH HDF5 series
for axisymmetric visualization tests and examples. It contains no simulation
or production-derived data.

The generator samples a two-dimensional form of VTK's RT analytic Wavelet
function. The `dens` field thresholds that function into a compact isovolume.
Its oscillating exterior changes over three timesteps while AMR refinement
increases from two to four possible leaf levels and remains 2:1 balanced.

Each block has the same `(nxb, nyb, nzb) = (8, 8, 1)` logical shape as the
reference FLASH workload. The HDF5 files include the complete source hierarchy,
including internal blocks, leaf blocks, one-based PARAMESH GIDs, block bounds,
coordinates, sizes, scalar metadata, and the `dens` and `wave` fields.

Regenerate the files with a Python environment containing NumPy and h5py:

```console
python data/FLASH/axisymmetric_wavelet/generate.py
```

Render the thresholded field in Kit:

```console
./repo.sh launch -n omni.cae.kit -- \
  --exec ./scripts/example_flash_axisymmetric_volume.py
```
