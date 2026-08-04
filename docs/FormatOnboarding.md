# Onboarding a Scientific Data Format

Kit-CAE opens native scientific assets through OpenUSD file-format plugins. A
format integration has two distinct parts:

1. **CAE OpenUSD Plugins** defines the USD data contract and implements the
   reader that exposes the native file as an `OmniSciDataset` stage.
2. **Kit-CAE** registers the packaged plugin runtime and optionally adds a File
   > Import entry that authors a payload prim with typed file-format arguments.

The old `CaeFieldArray` + Data Delegate + per-format importer architecture is a
legacy compatibility path. Do not use it for new formats.

## Choose the integration depth

| Goal | Work required |
|---|---|
| Open the native asset through `Usd.Stage.Open()` | File-format plugin and any required schemas |
| Expose the format in Kit-CAE's File > Import UI | File-format plugin plus a `PayloadImporter` registration |
| Process the dataset with Kit-CAE visualization operators | An `OmniSciCae` mesh or point-cloud data model and a Warp SimData adapter |
| Distribute the integration with Kit-CAE | Publish a compatible `cae_openusd_plugins` package and update Kit-CAE's package pin |

Keep these boundaries independent. An OpenUSD reader must not depend on Kit,
and the Kit importer must not parse or copy heavy source data.

## 1. Specify the conceptual data mapping

Before writing a reader, document the observable USD stage contract:

- source concepts and supported capability boundaries;
- prim hierarchy and default prim;
- typed prims and applied API schemas;
- array instance names, value types, shapes, indexing, and associations;
- coordinate, topology, and field conventions;
- time samples and simulation-time units;
- file-format arguments;
- lazy-loading and fidelity guarantees;
- unsupported source features.

Use `OmniSciDataset` for a scientific dataset. Store each logical array as a
matching pair of multiple-apply APIs on the dataset prim:

```usda
def OmniSciDataset "Example" (
    prepend apiSchemas = [
        "OmniSciArrayAPI:points",
        "OmniSciArrayAPI:temperature",
        "OmniSciFieldAPI:temperature",
        "OmniSciCaePointCloudAPI"
    ]
)
{
    float3[] omni:sci:array:points:value
    float[] omni:sci:array:temperature:value
    string omni:sci:field:temperature:name = "Temperature"
    token omni:sci:field:temperature:association = "vertex"
}
```

Prefer a format-specific API schema when the source domain needs additional
metadata. Introduce a typed prim only when the prim has a stable identity that
consumers need to query with `IsA`.

## 2. Add schemas to CAE OpenUSD Plugins

The active `OmniSci*` schemas are owned by the `cae_openusd_plugins` package,
not Kit-CAE's `source/schemas` tree. In a CAE OpenUSD Plugins checkout:

1. Add `source/schemas/<library>/schema.usda`.
2. Register it with `cae_add_schema()` in `source/schemas/CMakeLists.txt`.
3. Test generated types, property names, defaults, and Python imports.
4. Add the schema to the package's schema index and conceptual mapping.

Kit-CAE's `source/schemas/shared` tree is reserved for Kit-owned visualization
schemas and legacy compatibility schemas.

## 3. Implement the file-format plugin

Implement a read-only `SdfFileFormat` plugin in CAE OpenUSD Plugins. Use a
native C++ reader when the format requires native libraries, byte-range access,
record indexing, or tightly controlled memory behavior. Use the shared Python
file-format base only when a stable Python decoder can separate inexpensive
structure discovery from value materialization.

The reader should:

1. Parse enough metadata to build the stage structure.
2. Author typed prims, applied schemas, and inexpensive scalar metadata.
3. Register large array attributes with their final USD types.
4. Defer loading each large value until `UsdAttribute.Get()` requests it.
5. Materialize a requested value directly into its final `VtArray` storage.

Register the format's extensions and flat arguments in `plugInfo.json`. Add a
typed `OmniSciFileFormatArgs<Format>API` when an option should be authored on a
payload prim. Parser controls should be uniform attributes; internal mechanics
should remain internal.

### File-format validation

Test the installed plugin tree, not only the build tree:

- plugin and schema registration;
- `CanRead()` for accepted and rejected inputs;
- default prim and complete stage hierarchy;
- applied schemas and metadata;
- lazy value type, shape, and contents;
- time samples and file-format arguments;
- malformed input and unsupported features;
- clean installed-tree operation.

Opening the native file should require only normal OpenUSD APIs once the plugin
tree is registered:

```python
import cae_openusd_plugins

cae_openusd_plugins.register_usd_plugins()

from pxr import Usd

stage = Usd.Stage.Open("simulation.example")
print(stage.GetDefaultPrim().GetPath())
```

## 4. Add the Kit importer entry

Kit-CAE's `omni.cae.usd_plugins_importers` extension owns one shared payload
importer implementation. A format registration supplies only its UI metadata,
accepted extensions, and typed argument API.

Add a subclass in
`source/extensions/omni.cae.usd_plugins_importers/python/_importers.py`:

```python
from ._payload_importer import PayloadImporter


class ExampleAssetImporter(PayloadImporter):
    importer_name = "CAE Example Importer"
    file_extensions = (".example",)
    importer_filter_descriptions = ["Example Files (*.example)"]
    schema_api = "OmniSciFileFormatArgsExampleAPI"
```

Then add the type to `IMPORTER_TYPES` in `_registry.py` and include the extension
and format name in `config/extension.toml` keywords.

Do not parse the source asset in the Kit importer. The shared implementation
defines a prim, applies the argument schema, authors a payload to the native
asset, and loads it through OpenUSD.

### Programmatic import

All registered formats use one dispatcher:

```python
from omni.cae.usd_plugins_importers import import_to_stage

dataset_prim = await import_to_stage(
    "simulation.example",
    "/World/Simulation",
    # typed file-format arguments use their USD attribute base names
    timeScale=1.0,
)
```

Unknown arguments fail with a list of available names. Keep importer tests for:

- case-insensitive extension dispatch;
- the expected argument API on the payload prim;
- payload asset path and destination prim path;
- supported and rejected argument names;
- File > Import filter descriptions.

## 5. Add SimData conversion when needed

Visualization operators consume Warp SimData datasets. If the new USD schema
matches an existing CAE mesh or point-cloud model, reuse the corresponding
adapter. Otherwise add and test an adapter in `warp-simdata`, then update the
Kit-CAE wheel pin.

An adapter must preserve:

- point and cell topology;
- field association;
- scalar and vector component shapes;
- source time selection;
- device and zero-copy behavior where supported.

Kit-CAE-specific policy belongs in `omni.cae.simdata`; reusable data conversion
belongs in `warp-simdata`.

## 6. Build Kit-CAE with the local package

Build and package CAE OpenUSD Plugins for the same OpenUSD version, Python ABI,
platform, and C++ ABI as the selected Kit SDK. Then use Kit-CAE's local artifact
override:

```sh
export KIT_CAE_OPENUSD_PLUGINS_PACKAGE=/absolute/path/to/cae_openusd_plugins@<version>.zip
./repo.sh build -rx
```

If a new SimData adapter is also required:

```sh
export KIT_CAE_WARP_SIMDATA_PACKAGE=/absolute/path/to/warp_simdata@<version>.zip
./repo.sh build -rx
```

See [Build Instructions](./Build.md#using-local-dependency-builds) for artifact
compatibility checks and how to return to published dependencies.

## 7. Validate the end-to-end workflow

Run the narrowest relevant gates in each repository, then verify the Kit path:

1. Open the native asset directly with `Usd.Stage.Open()`.
2. Inspect the stage without reading heavy array values.
3. Request individual values at default and sampled times.
4. Import the asset into Kit-CAE with `import_to_stage()`.
5. Discover fields from `OmniSciFieldAPI` instances.
6. Create at least one visualization operator using `fieldNames`.
7. Exercise File > Import if a UI entry was added.
8. Run the importer, SimData, visualization, and bundle example tests affected
   by the integration.

Update the format matrix, conceptual mapping, dependency/license documentation,
extension changelogs, and top-level release notes in the same feature change.

## Legacy integrations

Existing `CaeFieldArray` stages and Data Delegates remain documented for
compatibility. If maintaining one, see [Legacy Data Delegate API](./DataDelegate.md)
and [Legacy Omni CAE schemas](./CaeSchemas.md). Do not copy those implementations
to start a new format.
