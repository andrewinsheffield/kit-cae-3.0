# Format Extensibility

New formats use the active USD-plugin architecture:

| Layer | Owner | Responsibility |
|---|---|---|
| Conceptual data mapping | CAE OpenUSD Plugins | Defines hierarchy, schemas, arrays, time, arguments, and capability limits. |
| `OmniSci*` schemas | CAE OpenUSD Plugins | Describes datasets, arrays, fields, and format-specific semantics. |
| `SdfFileFormat` reader | CAE OpenUSD Plugins | Builds inexpensive stage structure and lazily materializes array values. |
| `PayloadImporter` registration | Kit-CAE | Adds File > Import and the unified `import_to_stage()` dispatch entry. |
| SimData adapter | Warp SimData | Converts supported OmniSci data models for visualization operators. |

Do not create a `CaeFieldArray` subtype, Data Delegate, or
`omni.cae.importer.<format>` extension for a new integration. Those surfaces are
retained only for legacy stages.

## Required contracts

- Arrays live on an `OmniSciDataset` as `OmniSciArrayAPI:<instance>`.
- Field meaning uses the matching `OmniSciFieldAPI:<instance>`.
- Large `value` attributes are registered with their final USD type and loaded
  only when requested.
- Format controls that belong on a payload prim use a typed
  `OmniSciFileFormatArgs*API`.
- Kit's importer authors a payload; it does not parse or copy source data.
- Visualization field selections use `CaeVizFieldSelectionAPI.fieldNames`.

## Kit importer registration

Add a `PayloadImporter` subclass to
`omni.cae.usd_plugins_importers/python/_importers.py` and add it to
`IMPORTER_TYPES` in `_registry.py`:

```python
class ExampleAssetImporter(PayloadImporter):
    importer_name = "CAE Example Importer"
    file_extensions = (".example",)
    importer_filter_descriptions = ["Example Files (*.example)"]
    schema_api = "OmniSciFileFormatArgsExampleAPI"
```

All registered formats then use:

```python
from omni.cae.usd_plugins_importers import import_to_stage

await import_to_stage(path, "/World/Example", **format_args)
```

## Validation

Test plugin registration, stage structure, schemas, lazy values, arguments,
time behavior, importer dispatch, payload authoring, SimData conversion, and at
least one visualization operator. Validate the installed plugin package inside
Kit-CAE with the local artifact workflow in `docs/Build.md`.

See `docs/FormatOnboarding.md` for the complete sequence.
