# CAE SimData [omni.cae.simdata]

This extension adds support for data processing operators using the SimData library.

The active SimData extension registers USD-plugin backed `OmniSciDataset` adapters.
Legacy delegate-backed `CaeDataSet` converters now live in
`omni.cae.simdata.legacy`.

Kit defaults axisymmetric FLASH AMR conversion to a full-revolution representation with 32
angular cells, source dimension 0 as radius, and source dimension 1
as the cylinder axis. Visualization operators may override the angular cells and degree-based
angle range with `CaeVizDatasetAxisymmetricRepresentationAPI:<role>`; native and dual conversion
use the same authored settings.
