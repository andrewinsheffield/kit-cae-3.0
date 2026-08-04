# Format Reference

All active formats use:

```python
from omni.cae.usd_plugins_importers import import_to_stage

root = await import_to_stage(path, prim_path, **format_args)
```

The destination is a payload prim. The source file-format plugin determines the
children below it, so stage paths vary with the source hierarchy. Always inspect
the resulting `OmniSciDataset` prims and their `OmniSciFieldAPI` instances.

| Format | Extensions | Typed argument API | Notes |
|---|---|---|---|
| CGNS | `.cgns` | `OmniSciFileFormatArgsCgnsAPI` | Supports time mapping and optional base/zone filters. |
| EDEM | `.dem` | `OmniSciFileFormatArgsEdemAPI` | Particle datasets; supports time and streaming arguments. |
| EnSight Gold | `.case`, `.encas` | `OmniSciFileFormatArgsEnSightAPI` | Supports time and streaming arguments. |
| FLASH AMR | `.flash` | `OmniSciFileFormatArgsFlashAPI` | Experimental axisymmetric support in Kit-CAE. |
| EGRID | `.egrid` | `OmniSciFileFormatArgsEgridAPI` | Eclipse reservoir grid. |
| GRDECL | `.grdecl`, `.data` | `OmniSciFileFormatArgsGrdeclAPI` | Eclipse text-deck grid. |
| INIT | `.init` | `OmniSciFileFormatArgsInitAPI` | Reservoir properties; may reference a companion grid. |
| UNRST | `.unrst` | `OmniSciFileFormatArgsUnrstAPI` | Time-varying reservoir results. |
| NumPy | `.npz`, `.npy` | `OmniSciFileFormatArgsNpzAPI`, `OmniSciFileFormatArgsNpyAPI` | NPZ can be interpreted as `Point Cloud`, `CGNS`, or `None`. |
| NanoVDB | `.nvdb` | `OmniSciFileFormatArgsPythonAPI` | Python-backed format plugin. |
| OpenFOAM | `.foam` | `OmniSciFileFormatArgsOpenFoamAPI` | Place an empty `.foam` marker in the case root when needed. |
| VTK | `.vtk`, `.vti`, `.vtr`, `.vts`, `.vtp`, `.vtu` | `OmniSciFileFormatArgsVtkAPI` | Native USD-plugin path does not use a VTK Data Delegate. |
| Trimesh | `.stl`, `.ply`, `.3mf` | `OmniSciFileFormatArgsPythonAPI` | Deliberately limited to these three extensions. |

## Shared arguments

- `cacheMode`: `all`, `static`, or `none`.
- `scale`, `offset`, `source`: time mapping for formats that apply the time API.
- `chunkSize`, `ioThreads`: streaming hints for formats that apply the streaming API.

Examples:

```python
await import_to_stage(cgns_path, "/World/CGNS", source="TimeValue")
await import_to_stage(npz_path, "/World/Cloud", schema="Point Cloud")
await import_to_stage(npz_path, "/World/Mesh", schema="CGNS")
```

Use `usd_utils.get_instances(dataset_prim, "OmniSciFieldAPI")` to discover
field instance names. Never infer fields solely from a remembered stage path.

For a new format, follow `docs/FormatOnboarding.md`.
