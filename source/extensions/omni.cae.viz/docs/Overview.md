# CAE Visualization Extension - Technical Overview

## Purpose

`omni.cae.viz` executes schema-authored visualization operators. An authored
operator is ordinary USD geometry with `CaeVizOperatorAPI`, one algorithm API,
and the input-selection APIs needed by that algorithm. The extension discovers
those prims, evaluates them with SimData, and authors the resulting geometry or
volume state back onto the same prim.

## Active data model

Scientific datasets use the OmniSci schemas supplied by `omni.cae.schema` and
the native OpenUSD file-format plugins:

- an `OmniSciDataset` prim represents a dataset;
- `OmniSciArrayAPI:<instance>` stores each lazily loaded array; and
- `OmniSciFieldAPI:<instance>` describes the field association and name.

`CaeVizDatasetSelectionAPI:<role>` relates an operator to a dataset prim.
The `CaeVizDatasetAxisymmetricRepresentationAPI:<role>` configures
the angular cells and degree-based revolution range for a matching axisymmetric
dataset input. FLASH AMR is the initial supported model and uses concrete Kit
defaults when this schema is absent.
The experimental `CaeVizDatasetDualAPI:<role>` marker requests a dual
representation for the matching selection when Kit has registered support for
that data model. When both schemas are applied, the authored axisymmetric
settings configure the dual representation.
The experimental `CaeVizIndeXAxisymmetricVolumeAPI` selects the dedicated
`IndeXAxisymmetricVolume` operator for axisymmetric data. The visible volume is
one multi-attribute NanoVDB: a coarse first attribute establishes the revolved
3D sampling domain, and its NVIDIA IndeX shader searches native
`(radius, axial)` refinement attributes from finest to coarsest. Each FLASH leaf
remains at its native AMR refinement, without angular replication or
coarse-block prolongation. FLASH AMR is the initial supported model.
`CaeVizFieldSelectionAPI:<role>` selects fields by OmniSci API instance name in
its `fieldNames` attribute. The older `CaeDataSet`, `CaeFieldArray`, and field
`target` relationship model is supported only by extensions under
`source/legacy_extensions`.

## Evaluation flow

1. Native file-format plugins open a supported asset as an OmniSci dataset and
   register lazy array values.
2. Commands in `create_commands.py` author an output prim and apply the required
   OmniCaeViz APIs.
3. The extension discovers enabled operator prims and resolves their named
   dataset and field inputs.
4. SimData operators perform face and iso-surface extraction, slicing, glyph generation,
   stream tracing, subsetting, or voxelization on the requested device.
5. The result is authored as standard USD mesh, points, curves, instancing, or
   volume data for normal Hydra rendering.

Operator temporal and dependency APIs control evaluation order and time-aware
updates. Dataset temporal traits let the runtime avoid recomputing static
topology or geometry.

## Main components

- `extension.py` owns startup, shutdown, and stage integration.
- `create_commands.py` contains commands for authoring operator recipes.
- the operator modules implement the OmniCaeViz algorithms using SimData.
- shared helpers in `omni.cae.core` provide traversal, array conversion,
  caching, commands, and progress reporting.

The framework includes faces, iso-surfaces, planar slices, points, glyphs, streamlines,
NanoVDB voxelization, NVIDIA IndeX volume integration including direct
axisymmetric sampling, dataset subsets, field
mapping and thresholding, and automation APIs for colormaps and volume shaders.

Iso-surface operators select their scalar input through
`CaeVizFieldSelectionAPI:contour`. Cell-associated contour and output fields are
averaged onto points by the shared input-dataset pipeline and cached before the
triangular surface is extracted. Generated surface datasets are cached by input
state and timecode, and empty results hide the output mesh until renderable
geometry is produced again. The generated topology is recomputed at dataset
timesteps rather than interpolated between samples.

Planar-slice operators use their prim translation as the interactive plane
position. Direction mode selects a free plane whose normal is transformed local
+Y, an axis-aligned plane, or a two- or three-plane combination. SimData extracts
colored triangular surfaces directly from intersected volume cells, batching
multi-plane modes into one request. The runtime publishes them through alternating
RT buffers so incomplete topology updates are never exposed to the renderer.

## Direct axisymmetric volume design

The experimental `CaeVizIndeXAxisymmetricVolumeAPI` selects a dedicated
operator rather than the standard irregular-volume or voxelization paths. Its
purpose is to render a compact FLASH `(radius, axial)` AMR field directly,
without generating revolved geometry, angularly replicating field values, or
resampling every leaf to a finest-resolution 3D grid.

The renderer sees one public multi-attribute NanoVDB volume:

| Attribute | Contents | Purpose |
| --- | --- | --- |
| 0 | A coarse, constant 3D grid covering the revolved bounds | Establishes the regular spatial domain in which IndeX ray marches; it is not field data |
| 1 | Finest native FLASH leaf level | First field lookup |
| 2..N | Successively coarser native leaf levels | Fallback where no finer leaf is active |

Each field level is a sparse grid one voxel thick in its third index dimension.
Its active voxels are the original leaf cells at that level's native radial and
axial spacing. NaN is the inactive background. Consequently, a coarse leaf
occupies coarse voxels instead of being prolonged into many finest-level
voxels. The domain grid targets eight logical cells along its longest dimension
(integer index alignment can add a boundary cell) and contributes only small,
fixed-size overhead. All attributes belong to the same volume; the
implementation does not introduce hidden volume prims or separate IndeX scene
slots.

At an object-space render sample `(x, y, z)`, the XAC shader computes
`radius = sqrt(x*x + z*z)` and uses `(radius, y)` as the 2D lookup coordinate.
It samples native-level attributes with nearest-neighbor filtering from finest
to coarsest. NaN means that the current level has no leaf at that position, so
the first finite value wins and is mapped through the volume colormap. A sample
outside every leaf is discarded. The shader also computes the azimuth around
the volume's local Y axis and discards samples outside the representation's
minimum and maximum angles. The axis belongs to every partial revolution
because its azimuth is undefined. No angular field array exists, and the
authored angular-cell count does not tessellate or replicate the direct field.

The operator requests neither topology nor geometry. For analytical FLASH
representations it materializes only the compact source-block field values,
selects leaf blocks, classifies them by native spacing, and uploads each class
to a sparse NanoVDB attribute. This does copy the native scalar cells into the
renderer payload, but it does not flatten AMR to one resolution, create an
unstructured grid, or create a dense 3D field. Memory therefore scales with the
native 2D leaf cells and NanoVDB tile overhead, rather than the finest 3D
bounding-grid dimensions or an angular replication count.

`samplingDistanceScale` is a rendering-quality control. The authored IndeX ray
step is the finest native cell spacing multiplied by this value. The default is
`1`, which samples once per finest native cell spacing. Reducing it takes more
samples and can preserve thinner features at higher cost; increasing it improves
speed but can miss features. It does not alter lookup coordinates, refinement
levels, or stored resolution. There is no production `lookupScale` control: each
level is indexed using its actual FLASH cell spacing.

The NanoVDBs are built on CUDA device 0 and passed to IndeX through DLPack. If
IndeX requests another CUDA device, the buffers are moved to that device before
adoption. Each visited snapped sample retains its native payload in the temporal
cache, while a separate active entry keeps the currently rendered DLPack
adoption alive until its replacement completes. Every payload receives a
generation number so a delayed loader callback cannot install an older
timestep or field after a newer result. The first visit to a snapped sample
builds its native attributes; revisiting that sample re-adopts the cached
payload. The direct path does not interpolate fields between dataset samples.

The current implementation supports FLASH AMR scalar fields selected as
`colors`, square radial/axial cells, integral refinement ratios, and at most
eight native refinement levels. Subsetting and voxelization are intentionally
incompatible with this path because they would replace the native leaf layout.
The public volume extent covers the full revolved bound even for a partial
angle range; the shader performs the angular clipping. Its coarse domain grid
may conservatively extend beyond that extent due to integer voxel alignment.

See the repository-level
[OmniCaeViz schema reference](../../../../docs/CaeVizSchemas.md) for the full
authoring contract and examples.
