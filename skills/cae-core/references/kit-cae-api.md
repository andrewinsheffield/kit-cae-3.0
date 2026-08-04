# Kit-CAE API Reference

Use the active OmniSci and USD-plugin APIs below. Do not import
`omni.cae.data`, `omni.cae.importer.<format>`, or a per-format Data Delegate;
those belong to the legacy compatibility stack.

## Standard imports

```python
import omni.kit.app
import omni.usd
from omni.cae.core import array_utils, usd_utils
from omni.cae.core.commands import execute_command
from omni.cae.schema import cae, viz as cae_viz
from omni.cae.testing import frame_prims, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context
from pxr import Gf, OmniSci, Usd, UsdGeom, UsdShade
```

The application bundle enables `omni.cae.usd_plugins`, which registers the
packaged schema modules in the `pxr` namespace.

## Import native data

Every supported format uses the same async dispatcher:

```python
dataset_root = await import_to_stage(path, "/World/Simulation")
```

File-format options are passed by USD attribute base name:

```python
# CGNS time mapping
await import_to_stage(
    cgns_path,
    "/World/Simulation",
    scale=2.0,
    offset=0.0,
    source="TimeStep",
)

# NPZ interpretation
await import_to_stage(npz_path, "/World/Cloud", schema="Point Cloud")
await import_to_stage(npz_path, "/World/Mesh", schema="CGNS")
```

Unknown arguments raise `ValueError` and list the accepted names. See
`formats.md` for the registered extensions.

## Discover datasets and fields

Do not hard-code a field child prim: OmniSci fields are multiple-apply API
instances on the dataset prim.

```python
stage = get_context().get_stage()

datasets = [
    prim
    for prim in stage.Traverse()
    if prim.IsA(OmniSci.Dataset)
]

for dataset in datasets:
    field_names = usd_utils.get_instances(dataset, "OmniSciFieldAPI")
    print(dataset.GetPath(), field_names)
```

Format plugins may produce several dataset prims for one source asset. Inspect
applied schemas and choose the prim whose data model matches the operation:

```python
for prim in datasets:
    print(prim.GetPath(), prim.GetAppliedSchemas())
```

## Select fields on an operator

Dataset selection remains a relationship. OmniSci field selection uses the
`fieldNames` token array:

```python
operator = stage.GetPrimAtPath(operator_path)

cae_viz.DatasetSelectionAPI(operator, "source").GetTargetRel().SetTargets(
    [dataset_path]
)
cae_viz.FieldSelectionAPI(operator, "colors").CreateFieldNamesAttr().Set(
    ["Pressure"]
)
```

Several scalar instances can form a vector:

```python
cae_viz.FieldSelectionAPI(operator, "velocities").CreateFieldNamesAttr().Set(
    ["VelocityX", "VelocityY", "VelocityZ"]
)
```

For one vector-valued array, pass its single instance name.

## Create visualization operators

All creation commands are asynchronous:

```python
await execute_command(
    "CreateCaeVizBoundingBox",
    dataset_paths=[dataset_path],
    prim_path="/World/CAE/Bounds",
)

await execute_command(
    "CreateCaeVizFaces",
    dataset_path=dataset_path,
    prim_path="/World/CAE/Faces",
)
cae_viz.FieldSelectionAPI(
    stage.GetPrimAtPath("/World/CAE/Faces"), "colors"
).CreateFieldNamesAttr().Set(["Temperature"])

await wait_for_update()
```

The bounding-box command takes `dataset_paths` (a list). Dataset-bound
operators take `dataset_path` (one string).

### Volume

```python
volume_path = "/World/CAE/Volume"
await execute_command(
    "CreateCaeVizVolume",
    dataset_path=dataset_path,
    prim_path=volume_path,
    type="vdb",  # or "irregular" for a cell mesh
)
cae_viz.FieldSelectionAPI(
    stage.GetPrimAtPath(volume_path), "colors"
).CreateFieldNamesAttr().Set(["Pressure"])
```

- `vdb` voxelizes the selected dataset and also supports point clouds.
- `irregular` requires cell topology and uses the IndeX irregular-volume path.
- `axisymmetric` selects the direct FLASH AMR IndeX path.

### Direct axisymmetric FLASH volume

```python
volume_path = "/World/CAE/AxisymmetricVolume"
await execute_command(
    "CreateCaeVizVolume",
    dataset_path=dataset_path,
    prim_path=volume_path,
    type="axisymmetric",
)
volume = stage.GetPrimAtPath(volume_path)
cae_viz.FieldSelectionAPI(volume, "colors").CreateFieldNamesAttr().Set(
    ["dens"]
)
cae_viz.IndeXAxisymmetricVolumeAPI(
    volume
).CreateSamplingDistanceScaleAttr().Set(1.0)
```

This experimental path requires NVIDIA IndeX. It samples compact native FLASH
AMR levels without creating revolved geometry. Apply
`DatasetAxisymmetricRepresentationAPI:source` to author a partial angular
range; `angularCells` does not tessellate the direct path.

### Iso-surface

```python
iso_path = "/World/CAE/IsoSurface"
await execute_command(
    "CreateCaeVizIsoSurface",
    dataset_path=dataset_path,
    prim_path=iso_path,
)
iso = stage.GetPrimAtPath(iso_path)
cae_viz.IsoSurfaceAPI(iso).CreateIsoValueAttr().Set(float(iso_value))
cae_viz.FieldSelectionAPI(iso, "contour").CreateFieldNamesAttr().Set(
    ["Temperature"]
)
cae_viz.FieldSelectionAPI(iso, "colors").CreateFieldNamesAttr().Set(
    ["Pressure"]
)
```

The `contour` selection is scalar. Point- and cell-associated contour fields
are supported; cell values are averaged onto points before extraction. The
optional `colors` field is interpolated onto the generated triangle mesh.
Supported FLASH datasets receive axisymmetric and dual representation requests
from the create command.

### Geometry-based planar slice

```python
slice_path = "/World/CAE/PlanarSlice"
await execute_command(
    "CreateCaeVizPlanarSlice",
    dataset_path=dataset_path,
    prim_path=slice_path,
    type="standard",  # or "nanovdb"
)
planar_slice = stage.GetPrimAtPath(slice_path)
cae_viz.PlanarSliceAPI(planar_slice).CreateModeAttr().Set("xyz")
cae_viz.FieldSelectionAPI(
    planar_slice, "colors"
).CreateFieldNamesAttr().Set(["Temperature"])
```

The result is extracted triangle geometry and does not require IndeX. Modes are
`free`, `x`, `y`, `z`, `xy`, `xz`, `yz`, and `xyz`. The operator prim's
translation positions every plane. In `free` mode, transformed local `+Y` is
the plane normal.

### Points and glyphs

```python
points_path = "/World/CAE/Points"
await execute_command(
    "CreateCaeVizPoints", dataset_path=dataset_path, prim_path=points_path
)
points = stage.GetPrimAtPath(points_path)
cae_viz.FieldSelectionAPI(points, "colors").CreateFieldNamesAttr().Set(
    ["Temperature"]
)
cae_viz.FieldSelectionAPI(points, "widths").CreateFieldNamesAttr().Set(
    ["VelocityX", "VelocityY", "VelocityZ"]
)

glyphs_path = "/World/CAE/Glyphs"
await execute_command(
    "CreateCaeVizGlyphs",
    dataset_path=dataset_path,
    prim_path=glyphs_path,
    shape="Arrow",
)
glyphs = stage.GetPrimAtPath(glyphs_path)
cae_viz.FieldSelectionAPI(glyphs, "orientations").CreateFieldNamesAttr().Set(
    ["VelocityX", "VelocityY", "VelocityZ"]
)
```

### Streamlines

```python
streamlines_path = "/World/CAE/Streamlines"
seed_path = "/World/CAE/Seeds"

await execute_command(
    "CreateCaeVizStreamlines",
    dataset_path=dataset_path,
    prim_path=streamlines_path,
    type="standard",
)
await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=seed_path)

streamlines = stage.GetPrimAtPath(streamlines_path)
cae_viz.DatasetSelectionAPI(streamlines, "seeds").GetTargetRel().SetTargets(
    [seed_path]
)
cae_viz.FieldSelectionAPI(
    streamlines, "velocities"
).CreateFieldNamesAttr().Set(["VelocityX", "VelocityY", "VelocityZ"])
cae_viz.FieldSelectionAPI(streamlines, "colors").CreateFieldNamesAttr().Set(
    ["Temperature"]
)
```

### Planar and volume slices

- `CreateCaeVizPlanarSlice(dataset_path=..., type="standard"|"nanovdb")`
  creates independent extracted triangle geometry.
- `CreateCaeVizVolumeSlice(volume_path=..., shape=...)` creates a slice of an
  existing IndeX volume operator; color field selection remains on the source
  volume.

## Independent opacity mapping

Faces, Points, Glyphs, Iso Surfaces, Streamlines, and Planar Slices author an
independent opacity selection:

```python
cae_viz.FieldSelectionAPI(operator, "opacity").CreateFieldNamesAttr().Set(
    ["VolumeFraction"]
)

shader = UsdShade.Shader(shader_prim)
shader.GetInput("opacity_domain").Set(
    Gf.Vec2f(float(opacity_min), float(opacity_max))
)
shader.GetInput("opacity_lut").Set(
    "dynamic://cae_opacitymap_<colormap_identifier>"
)
shader.GetInput("opacity").Set(0.8)
shader.GetInput("enable_opacity").Set(True)

cae_viz.RescaleRangeAPI(
    operator, "opacity"
).CreateRescaleModeAttr().Set("disable")
```

When authoring a fixed domain, explicitly enable opacity before disabling
auto-rescale; disabled rescaling does not toggle material enable inputs. Inspect
the operator material to locate `shader_prim`; material paths differ by
operator. A texture-enabled Colormap publishes
`dynamic://cae_colormap_<identifier>` for color and
`dynamic://cae_opacitymap_<identifier>` for alpha-derived opacity.

## Dataset representations and ROI processing

Representation and preprocessing APIs use the same instance as the matching
dataset selection:

```python
axisymmetric = cae_viz.DatasetAxisymmetricRepresentationAPI.Apply(
    operator, "source"
)
axisymmetric.CreateAngularCellsAttr().Set(48)
axisymmetric.CreateMinimumAngleAttr().Set(0.0)
axisymmetric.CreateMaximumAngleAttr().Set(180.0)

cae_viz.DatasetDualAPI.Apply(operator, "source")
```

Do not apply dual representation to an arbitrary model. Prefer the create
command's supported defaults or check capability through `omni.cae.simdata`.

To restrict a mesh operator to an ROI:

```python
roi = UsdGeom.Cube.Define(stage, "/World/CAE/ROI")
roi.CreateSizeAttr().Set(1.0)
UsdGeom.Xformable(roi).AddTranslateOp().Set(roi_center)
UsdGeom.Xformable(roi).AddScaleOp().Set(roi_scale)

if not operator.HasAPI(cae_viz.DatasetSubsetAPI, "source"):
    cae_viz.DatasetSubsetAPI.Apply(operator, "source")
subset = cae_viz.DatasetSubsetAPI(operator, "source")
subset.CreateRoiRel().SetTargets([roi.GetPath()])
subset.CreateModeAttr().Set("centroid")  # "all", "any", or "centroid"
subset.CreateInflateBoundsAttr().Set(0)
```

Use the corresponding `DatasetVoxelizationAPI:source` ROI relationship for a
voxelized operator. Changing the ROI transform re-executes the dependent
operator.

For a point cloud that must behave as one logical cell per point:

```python
cae_viz.DatasetVoronoiPointCloudAPI.Apply(operator, "source")
```

## Derived arrays

Array Expressions are lazy fields and can be selected by visualization
operators:

```python
velocity = cae.ArrayExpressionAPI.Apply(array_owner_prim, "velocity")
velocity.CreateExpressionAttr().Set("vec3(vel_x, vel_y, vel_z)")
velocity.CreateLanguageVersionAttr().Set(1)
velocity.CreateComputeDeviceAttr().Set("auto")
velocity.CreateEnabledAttr().Set(True)

speed = cae.ArrayExpressionAPI.Apply(array_owner_prim, "speed")
speed.CreateExpressionAttr().Set("magnitude(velocity)")
speed.CreateLanguageVersionAttr().Set(1)
speed.CreateEnabledAttr().Set(True)

cae_viz.FieldSelectionAPI(operator, "colors").CreateFieldNamesAttr().Set(
    ["speed"]
)
```

Author expressions on the prim that owns all dependencies. Version 1 is
array-level and `float32`; it has no topology, association conversion,
connectivity, gradients, or spatial derivatives. See
`source/extensions/omni.cae.simdata/docs/ArrayExpressionLanguage.md`.

## Read an OmniSci array

Array values are standard USD attributes. Calling `Get()` may trigger the lazy
file-format read, so do it off the UI thread for large arrays.

```python
import asyncio
import numpy as np

array_attr = dataset_prim.GetAttribute("omni:sci:array:Pressure:value")
value = await asyncio.to_thread(array_attr.Get, Usd.TimeCode.EarliestTime())
array = np.asarray(value)

ranges = array_utils.get_componentwise_ranges(array)
stats = array_utils.get_scalar_stats(array, num_bins=32)
```

Use the timeline's current USD time code when querying time-varying arrays.

## Time mapping and interpolation

Import-time `scale`, `offset`, and `source` arguments map native simulation
ordinates to USD time codes. To interpolate fields between authored samples:

```python
cae_viz.OperatorTemporalAPI.Apply(operator)
cae_viz.OperatorTemporalAPI(operator).CreateEnableFieldInterpolationAttr().Set(True)
```

Timeline changes do not require mutating payload or array attributes. Change
the timeline time and allow the operator controller to re-execute.

## Visibility and framing

```python
UsdGeom.Imageable(prim).MakeInvisible()
UsdGeom.Imageable(prim).MakeVisible()

await frame_prims([operator_path], zoom=0.9)
await wait_for_update()
```

## Script template

```python
import asyncio

from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.testing import frame_prims, wait_for_update
from omni.cae.usd_plugins_importers import import_to_stage
from omni.usd import get_context


async def main():
    await import_to_stage("<FILE>", "/World/Simulation")
    stage = get_context().get_stage()

    # Inspect the stage and choose an OmniSciDataset prim.
    dataset_path = "<DATASET_PRIM_PATH>"
    faces_path = "/World/CAE/Faces"

    await execute_command(
        "CreateCaeVizFaces", dataset_path=dataset_path, prim_path=faces_path
    )
    cae_viz.FieldSelectionAPI(
        stage.GetPrimAtPath(faces_path), "colors"
    ).CreateFieldNamesAttr().Set(["<FIELD_INSTANCE>"])

    await wait_for_update()
    await frame_prims([faces_path], zoom=0.9)


asyncio.ensure_future(main())
```

Use the tested scripts under `scripts/` as the source of truth for complete
operator examples.
