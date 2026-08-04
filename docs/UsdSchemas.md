# Scientific Data Schemas

Kit-CAE uses OpenUSD schemas and file-format plugins to expose scientific data
without converting source files. The active data model is the `OmniSci` schema
family supplied by the prebuilt `cae_openusd_plugins` runtime. Kit-CAE also ships
older `OmniCae` schemas for compatibility with existing stages.

## Active data model: OmniSci

The active model keeps a dataset and its arrays on one prim:

- `OmniSciDataset` is the typed prim that represents a mesh, grid, point cloud,
  field collection, or another scientific dataset.
- `OmniSciArrayAPI:<name>` is a multiple-apply API schema. Its `value` attribute
  contains the array and may be populated lazily by a USD file-format plugin.
- `OmniSciFieldAPI:<name>` adds field semantics such as the display name and
  point/cell association to the matching array instance.

For example, an `OmniSciDataset` carrying coordinates and pressure can expose
both arrays directly on the dataset prim:

```usda
def OmniSciDataset "Fluid" (
    prepend apiSchemas = [
        "OmniSciArrayAPI:points",
        "OmniSciArrayAPI:pressure",
        "OmniSciFieldAPI:pressure"
    ]
)
{
    float3[] omni:sci:array:points:value
    float[] omni:sci:array:pressure:value
    string omni:sci:field:pressure:name = "Pressure"
    token omni:sci:field:pressure:association = "cell"
}
```

The file-format plugin can register the array attributes and defer reading their
values until an application calls `UsdAttribute.Get()`. Because the values use
standard USD attribute resolution, consumers do not need a Kit-specific data
access registry.

### Format and data-model schemas

Formats add API schemas to `OmniSciDataset` prims instead of introducing a new
typed field-array prim for every storage format. The packaged runtime currently
provides schema families for:

- common CAE mesh and point-cloud models;
- CGNS zones, grid coordinates, flow solutions, and element sections;
- EDEM particle datasets;
- EnSight pieces and parts;
- FLASH AMR datasets;
- OpenFOAM poly meshes and boundary patches;
- Eclipse reservoir corner-point grids and cell properties;
- VTK image, rectilinear, structured, unstructured, and polydata datasets;
- file-format arguments, including time and streaming controls.

Enable `omni.cae.usd_plugins` before importing these modules from `pxr`:

```python
from pxr import OmniSci, OmniSciCae, OmniSciCgns

dataset = OmniSci.Dataset.Get(stage, "/World/Fluid")
mesh_api = OmniSciCae.MeshAPI(dataset.GetPrim())
```

The exact schema set is versioned with `cae_openusd_plugins`, not with the
Kit-CAE-owned schema source tree.

## File-format arguments and payload import

`omni.cae.usd_plugins_importers` creates a payload prim that references the
native source file. It applies the matching `OmniSciFileFormatArgs*` API schemas
to author import options without copying the source data.

```python
from omni.cae.usd_plugins_importers import import_to_stage

await import_to_stage("simulation.cgns", "/World/Simulation")
```

USD then opens the native asset through the registered file-format plugin. See
the [importer format matrix](../source/extensions/omni.cae.usd_plugins_importers/docs/README.md)
for supported extensions and the [format onboarding guide](./FormatOnboarding.md)
for adding a format.

## Visualization schemas

The `OmniCaeViz` schema family is owned by Kit-CAE and describes processing and
visualization operators. A `CaeVizDatasetSelectionAPI:<role>` relationship points
to an input dataset. For an `OmniSciDataset`, a
`CaeVizFieldSelectionAPI:<role>.fieldNames` attribute selects one or more
`OmniSciFieldAPI` instance names. Each selected field normally has a matching
`OmniSciArrayAPI` instance with the same name.

```usda
def Mesh "Surface" (
    prepend apiSchemas = [
        "CaeVizOperatorAPI",
        "CaeVizFacesAPI",
        "CaeVizDatasetSelectionAPI:source",
        "CaeVizFieldSelectionAPI:colors"
    ]
)
{
    rel cae:viz:dataset_selection:source:target = </World/Fluid>
    token[] cae:viz:field_selection:colors:fieldNames = ["pressure"]
}
```

See [CAE Viz Schemas](./CaeVizSchemas.md) for the full operator model.

## Legacy compatibility model

Stages created before the OmniSci transition may use `CaeDataSet` prims with
child `CaeFieldArray` prims and relationships between them. Array values in that
model are loaded through the legacy Data Delegate API.

The compatibility implementation lives under `source/legacy_extensions` and is
not the recommended starting point for new formats or applications. Its detailed
references remain available in:

- [Legacy Omni CAE schemas](./CaeSchemas.md)
- [Legacy Data Delegate API](./DataDelegate.md)

The active visualization runtime accepts both models where compatibility is
implemented, but new examples and integrations should use OmniSci.

## Ownership and registration

| Surface | Owner | Registration extension |
|---|---|---|
| `OmniSci*` and format schemas | `cae_openusd_plugins` package | `omni.cae.usd_plugins` |
| `OmniSciFileFormatArgs*` | `cae_openusd_plugins` package | `omni.cae.usd_plugins` |
| `OmniCaeViz` | Kit-CAE `source/schemas/shared` | `omni.cae.schema` |
| Legacy `OmniCae` / `OmniCaeSids` | Kit-CAE `source/schemas/shared` | `omni.cae.schema` |

`omni.cae.schema` registers the Kit-CAE-owned plugin tree. The
`omni.cae.usd_plugins` extension stages and registers the prebuilt plugin tree,
adds its Python directory to the active `pxr` namespace, and makes the native
file formats available to USD.
