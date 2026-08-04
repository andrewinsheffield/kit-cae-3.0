# CAE USD Plugins Importers

Asset importer extension that provides importers for all file formats supplied by `omni.cae.usd_plugins`:

| Format | Extension | File-format arguments API |
|---|---|---|
| CGNS | `.cgns` | `OmniSciFileFormatArgsCgnsAPI` |
| EDEM | `.dem` | `OmniSciFileFormatArgsEdemAPI` |
| EnSight | `.case` / `.encas` | `OmniSciFileFormatArgsEnSightAPI` |
| FLASH AMR | `.flash` | `OmniSciFileFormatArgsFlashAPI` |
| EGRID | `.egrid` | `OmniSciFileFormatArgsEgridAPI` |
| GRDECL | `.grdecl` / `.data` | `OmniSciFileFormatArgsGrdeclAPI` |
| INIT | `.init` | `OmniSciFileFormatArgsInitAPI` |
| UNRST | `.unrst` | `OmniSciFileFormatArgsUnrstAPI` |
| NPZ | `.npz` | `OmniSciFileFormatArgsNpzAPI` |
| NPY | `.npy` | `OmniSciFileFormatArgsNpyAPI` |
| NanoVDB | `.nvdb` | `OmniSciFileFormatArgsPythonAPI` |
| OpenFOAM | `.foam` | `OmniSciFileFormatArgsOpenFoamAPI` |
| VTK | `.vtk` / `.vti` / `.vtr` / `.vts` / `.vtp` / `.vtu` | `OmniSciFileFormatArgsVtkAPI` |
| Trimesh | `.stl` / `.ply` / `.3mf` | `OmniSciFileFormatArgsPythonAPI` |

Each importer integrates with the Omniverse Asset Importer UI using default file-format
arguments. For programmatic use, call the package-level async dispatcher:

```python
from omni.cae.usd_plugins_importers import import_to_stage

await import_to_stage(path, prim_path)
```

The dispatcher selects the appropriate importer from the file extension.
