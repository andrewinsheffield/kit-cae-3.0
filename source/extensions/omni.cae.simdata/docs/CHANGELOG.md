# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.9.0]

- Updated the experimental `warp-simdata` runtime and moved its distribution
  from a Python package index to Packman.

## [1.8.0]

- Added a provider interface for materializing virtual raw scientific arrays
  and reporting their time samples without requiring field semantics.
- Routed array expressions through the raw-array provider registry so virtual
  native dependencies supplied by file-format extensions compose normally.

## [1.7.0]

- Updated the experimental `warp-simdata` runtime.
- Updated the experimental `warp-simdata` runtime for batched multi-plane
  slice extraction.

## [1.6.0]

- Updated the experimental `warp-simdata` runtime to fix false-positive point
  containment in concave polyhedra during voxelization and probing.
- Updated the experimental `warp-simdata` runtime for scoped scientific-array
  value resolution and resolver-provided vector dtype preservation.
- Added experimental, versioned, lazily evaluated scientific-array expressions
  with scalar and vector math, dependency diagnostics, device selection, temporal and
  representation-independent raw-array caching, and normal field
  discovery/loading.
- Added `zeros_like`, `ones_like`, and `full_like` for creating `float32`
  constants that preserve a reference field's tuple and component layout.
- Native and derived scalar fields can be combined into vector selections for
  operators, and shared derived dependencies are reused across requests.
- Expressions now resolve at the raw scientific-array `:value` boundary before
  adapter-specific representation transforms. Recursive derived dependencies
  therefore remain compact for FLASH and are expanded only with the final field.
- Expressions are scoped to the prim that owns their scientific arrays; CGNS
  expressions are consequently authored on `FlowSolution` prims rather than
  zone or element operator-input prims.
- Added authored axisymmetric FLASH representation resolution, including angular-cell
  and angle-range overrides shared by native and dual representations.
- Reduced the default full-revolution FLASH representation from 256 to 32 angular cells.
- FLASH defaults now resolve to concrete representation values so equivalent operator requests
  reuse the representation-aware converted-dataset cache.

## [1.5.0]

- Added experimental dual-representation capability discovery and representation-aware dataset and
  field loading. FLASH AMR inputs currently resolve to the axisymmetric dual representation.
- Updated the experimental `warp-simdata` runtime.

## [1.4.0]

- Updated the `warp-simdata` runtime with axisymmetric FLASH AMR dataset and field adapters.
- Configured the FLASH representation for a full revolution with 256 angular cells,
  source dimension 0 as radius, and source dimension 1 as the cylinder axis.

## [1.3.0]

- Split the monolithic `commands.py` into focused `mesh_commands` and `omnisci_commands` modules,
  keeping mesh and USD-plugin-backed dataset command registration separate.
- Added an `OmniSciDatasetConvertToSimDataSet` command and `GetAvailableFields` generic command for
  discovering field metadata on USD-plugin-backed datasets.
- `ConvertToSimDataSet.invoke` now returns a shallow copy of the cached dataset to prevent callers
  from mutating cached state.
- Switched runtime imports from `omni.cae.data` to `omni.cae.core` to match the new core/legacy split.
- Moved the legacy delegate-backed converter commands into `omni.cae.simdata.legacy` (`omnisci_commands`
  remains here for current USD-plugin-backed datasets).

## [1.2.0]

- Added `CaeSidsUnstructuredGetField` to remap cell-centered CGNS fields from sibling NFACE_n volume cells
  onto NGON_n faces, so face-based visualization can color by volume cell data.

## [1.1.1]

- Added explicit runtime dependencies for Kit commands and USD stage-update APIs used during extension startup.
- Updated package wording to describe SimData processing operators.

## [1.1.0]

- `ConvertToSimDataSet.invoke` now stores results via `cache.put_ex` with a `PrimWatch`-based invalidation guard
  instead of a plain dict-key cache entry, ensuring precise invalidation when the source prim changes.

## [1.0.0]

- Initial version.
