---
name: cae-visualization
description: >
  Visualize and analyze simulation data using NVIDIA Kit-CAE (Omniverse). Supports
  native CAE USD-plugin formats including CGNS, VTK, EnSight Gold, OpenFOAM, NumPy,
  EDEM, NanoVDB, FLASH AMR, Eclipse reservoir data, and Trimesh assets. Covers volume
  rendering, faces, geometry and volume slices, iso-surfaces, streamlines, glyphs,
  points, flow animation, field-driven opacity, derived arrays, dataset representations,
  ROI processing, field statistics, multi-domain composition, and time-varying
  animation. Triggers on any request involving simulation post-processing, CAE
  visualization, scientific data rendering, or field data analysis.
depends:
  - cae-core
version: "3.0.0"
metadata:
  author: "NVIDIA"
  tags:
    - kit-cae
    - cae
    - visualization
    - cgns
    - vtk
    - ensight
    - openfoam
    - volume-rendering
    - streamlines
    - colormap
    - iso-surface
    - flash
    - reservoir
---

# CAE Visualization

Set up and render simulation data visualizations using Kit-CAE.

Workflow: data inspection → import → visualization setup → framing → output.
For clean render-product capture (images/movies without UI), see `cae-capture`.

## Purpose

Use schema-authored `omni.cae.viz` operators, format-agnostic OmniSci stage
discovery, optional dataset representations, and native or derived arrays.

## Prerequisites

`cae-core` (loaded automatically as a dependency). Native format plugins,
including VTK, are available in the standard application.

## Instructions

Follow the workflow in order: Inspect (`## 1. Inspect`) → Query field statistics
(`## 2. Query Field Statistics`) → Choose input processing and representation
(`## 3. Choose Input Processing`) → Choose visualization (`## 4. Choose
Visualization`) → Write and run a script (`## 5. Write & Run Script`).

## Limitations

IndeX-backed volume rendering, including direct axisymmetric FLASH volume
rendering, requires an IndeX license. Geometry-based `PlanarSlice` and
`IsoSurface` extraction do not. Time-varying playback requires the source
format to expose time samples (see `cae-core/references/formats.md`). Array
Expressions are array-level only: they do not provide topology, connectivity,
gradients, or spatial derivatives.

## Incremental Visualization Rule

When building or debugging a visualization, prove each layer visually before
adding the next:

1. Import data and confirm fields.
2. Create one static visualization operator and capture a frame.
3. Set color domain and capture again.
4. Add hiding or composition changes and confirm the operator still renders.
5. Add camera animation.
6. Add data, seed, or slice animation.
7. Capture start, midpoint, transition, and end frames.

Do not debug animation until the static visualization renders correctly.

## Dependencies

- `cae-core/SKILL.md` — Preflight, Z-up, launch commands, critical rules
- `cae-core/references/kit-cae-api.md` — **All viz commands, field binding, stage discovery, statistics, script template**
- `cae-core/references/formats.md` — Per-format import signatures and stage paths
- `cae-core/references/extensibility.md` — Custom format onboarding
- `references/iso-surfaces.md` — Iso-value extraction and output coloring
- `references/opacity-mapping.md` — Independent color and opacity mapping
- `references/derived-arrays.md` — Array Expressions for visualization inputs
- `references/dataset-representations.md` — FLASH axisymmetric, dual, and direct volume paths
- `references/roi-and-subsetting.md` — Interactive ROI processing

*Always run the preflight checklist from `cae-core/SKILL.md` first.*

## 1. Inspect (MANDATORY for unknown data)

Never guess field names. For vague requests, inspect first, present fields in
engineering terms, and ask what to visualize.

```bash
# VTK files:
CAE_INSPECT_FILE=<file> ./repo.sh launch -n omni.cae.kit -- \
    --exec skills/cae-core/scripts/inspect_vtk.py --no-window

# CGNS files:
CAE_INSPECT_FILE=<file> ./repo.sh launch -n omni.cae.kit -- \
    --exec skills/cae-core/scripts/inspect_cgns.py --no-window
```

For other formats: import into Kit-CAE, then use Stage Discovery from `kit-cae-api.md`.

## 2. Query Field Statistics

Same data as the UI's CAE Insights panel. See `kit-cae-api.md` § Field Statistics
for inline API usage, or run the batch script:

```bash
CAE_STATS_FILE=<file> ./repo.sh launch -n omni.cae.kit -- \
    --exec skills/cae-core/scripts/query_stats.py --no-window
```

Use statistics to choose meaningful colormap ranges and validate data.

## 3. Choose Input Processing

Choose representation and preprocessing before choosing the output operator.
These APIs apply to a matching `DatasetSelectionAPI` role, normally `"source"`.

| Need | API / workflow | Notes |
|------|----------------|-------|
| Derived scalar/vector field | `CaeArrayExpressionAPI:<name>` | Lazy array-level expressions; see `references/derived-arrays.md` |
| Mesh region of interest | `DatasetSubsetAPI:source` | Cell selection by ROI bounds; see `references/roi-and-subsetting.md` |
| Voxelized region of interest | `DatasetVoxelizationAPI:source` | Limits the voxelized input using an ROI |
| Point cloud as logical cells | `DatasetVoronoiPointCloudAPI:source` | Treats source points as Voronoi seeds |
| Revolved FLASH mesh | `DatasetAxisymmetricRepresentationAPI:source` | Controls angular cells and angle range |
| FLASH dual topology | `DatasetDualAPI:source` | Automatically authored for supported iso-surface/slice workflows |
| Direct FLASH volume | `CreateCaeVizVolume` type=`axisymmetric` | Compact native-resolution IndeX path |

Do not author representation APIs speculatively. Inspect the dataset model, then
use the capability-specific workflow in `references/dataset-representations.md`.

## 4. Choose Visualization

| Type | Command | Use for |
|------|---------|---------|
| Faces | `CreateCaeVizFaces` | Surface extraction, boundaries |
| Iso Surface | `CreateCaeVizIsoSurface` | Triangular surface at a scalar iso-value |
| Volume (VDB) | `CreateCaeVizVolume` type=vdb | Structured grids, large datasets, point clouds |
| Volume (irregular) | `CreateCaeVizVolume` type=irregular | Unstructured grids with cell topology |
| Volume (axisymmetric) | `CreateCaeVizVolume` type=axisymmetric | Direct FLASH AMR rendering without revolved geometry |
| Geometry Planar Slice | `CreateCaeVizPlanarSlice` | Independent extracted triangles; no IndeX license |
| IndeX Volume Slice | `CreateCaeVizVolumeSlice` | Slice attached to an existing volume operator |
| Streamlines | `CreateCaeVizStreamlines` | Flow paths (needs velocity field) |
| Glyphs | `CreateCaeVizGlyphs` | Vector arrows/cones/spheres |
| Points | `CreateCaeVizPoints` | Point clouds, node inspection |
| Bounding Box | `CreateCaeVizBoundingBox` | Wireframe bounds, ROI, framing |
| Flow | Flow API | Animated smoke/particle flow |

Use a geometry planar slice when the user wants extracted cross-sections,
multi-plane output, or a license-free slice. Use a volume slice when the user
already has an IndeX volume and wants renderer-side probing.

Full command syntax and field binding: `kit-cae-api.md` § Visualization Commands.

## 5. Write & Run Script

Use the script template from `kit-cae-api.md` § Script Template.

```bash
cd <kit-cae-dir>
./repo.sh launch -n omni.cae.kit -- --exec scripts/<script>.py --no-window
```

## Mid-session imports (streaming / long-lived sessions)

`import_to_stage`, `execute_command`, and the field-binding APIs are all safe
to call **after Kit has started**, not just at script init. This is what makes
streaming load-on-demand workflows possible:

- A long-lived listener (see `cae-streaming/scripts/serve.py`) registers a
  request handler with `omni.kit.livestream.messaging`.
- On request, it `await`s the importer and viz commands inline.
- Multiple imports can pile up in the same stage (`/World/<name1>`,
  `/World/<name2>`); each one is independent.

> **Long-lived listeners must NOT use the `os._exit(0)` shutdown template**
> from `cae-core/SKILL.md` § "Script shutdown (MANDATORY)". That template is
> for one-shot capture scripts; it'll terminate the listener as soon as the
> first request returns. Streaming listeners loop on
> `await app.next_update_async()` until the app is asked to quit.

Full streaming setup (template `.kit`, launcher, wire protocol, handler
patterns): `cae-streaming/SKILL.md`.

## Color Mapping

### Field Binding

```python
cae_viz.FieldSelectionAPI(viz_prim, "colors").CreateFieldNamesAttr().Set([field_name])
```

Three modes: scalar (N,1) → by value; vector (N,3) → by magnitude; three
separate scalars → Kit-CAE interprets as vector, colors by magnitude.

### Independent Surface Opacity

Faces, Points, Glyphs, Iso Surfaces, Streamlines, and Planar Slices can bind an
independent scalar through `FieldSelectionAPI:opacity`. This is separate from
volume transfer-function alpha and separate from the `colors` field:

```python
cae_viz.FieldSelectionAPI(viz_prim, "opacity").CreateFieldNamesAttr().Set(
    ["VolumeFraction"]
)
```

Configure its own domain, LUT, multiplier, and auto-rescale behavior. A
texture-enabled Colormap publishes distinct dynamic color and opacity URLs.
See `references/opacity-mapping.md`.

### Colormap & Domain

For Faces, Points, Glyphs, Streamlines — set via shader:

```python
shader = UsdShade.Shader(stage.GetPrimAtPath(f"{viz_path}/Materials/ScalarColor/Shader"))
shader.GetInput("domain").Set(Gf.Vec2f(min_val, max_val))
shader.GetInput("lut").Set("cae/colormaps/afmhot.png")  # built-in: afmhot, cividis, gist_gray, gist_rainbow
```

### Custom Transfer Function (Volumes / Slices)

For full control over color AND opacity. The Colormap prim is typically at
`{vol_path}/Material/Colormap`:

```python
from pxr import Gf, Vt

colormap_prim = stage.GetPrimAtPath(f"{vol_path}/Material/Colormap")

rgba_points = Vt.Vec4fArray([
    Gf.Vec4f(0.02, 0.01, 0.08, 0.0),    # transparent void
    Gf.Vec4f(0.10, 0.15, 0.35, 0.01),   # faint blue haze
    Gf.Vec4f(0.80, 0.45, 0.05, 0.10),   # warm orange
    Gf.Vec4f(1.00, 0.98, 0.90, 0.85),   # bright core
])
x_points = Vt.FloatArray([0.0, 0.2, 0.6, 1.0])  # normalized positions

colormap_prim.GetAttribute("rgbaPoints").Set(rgba_points)
colormap_prim.GetAttribute("xPoints").Set(x_points)
colormap_prim.GetAttribute("colormapSource").Set("rgbaPoints")  # REQUIRED after setting points
```

**Domain** (value range mapping to [0,1]):

```python
colormap_prim.GetAttribute("domain").Set(Gf.Vec2f(float(min_val), float(max_val)))
```

**Boundary mode rule** (volume vs slice — *most of the time*):

- Volume → `"clampToTransparent"` (out-of-range voxels disappear; lets surrounding ops show through).
- Slice → `"clampToEdge"` (out-of-range pixels show the boundary color; no transparent holes).

> **Important:** `clampToTransparent` only acts on voxels *outside* the
> domain. Inside the domain, alpha is whatever you stamped on
> `rgbaPoints`. A volume colormap with α=1.0 on every stop renders as a
> fully opaque block regardless of `clampToTransparent` — the
> "purple-cube" failure mode. Always taper alpha across stops (low for
> air / background, mid for soft tissue, high for dense regions); or
> bind a separate alpha control via `ConfigureXACShaderAPI`.

Source defaults are the OPPOSITE for both, so always set explicitly:

```python
vol_cm.GetAttribute("domainBoundaryMode").Set("clampToTransparent")
slice_cm.GetAttribute("domainBoundaryMode").Set("clampToEdge")
```

**Tips:** Use 6–10 control points for rich gradients. Keep low-density regions
mostly transparent (alpha < 0.05). Set domain min above zero to clip noise.

### Colormap Domain Tuning (CRITICAL)

A volume that appears flat-colored (all one hue) almost always means the colormap
domain doesn't match the actual data range. This is the #1 cause of bad-looking
volumes.

**Always query actual data statistics before setting domain:**

```python
import asyncio
import numpy as np
from omni.cae.core import array_utils

array_attr = dataset_prim.GetAttribute(f"omni:sci:array:{field_name}:value")
value = await asyncio.to_thread(array_attr.Get, Usd.TimeCode.EarliestTime())
farray = np.asarray(value)
ranges = array_utils.get_componentwise_ranges(farray)
min_val, max_val = float(ranges[0][0]), float(ranges[0][1])
print(f"Field range: [{min_val}, {max_val}]")
```

Then set domain to the actual range (or a subset that emphasizes the interesting
region):

```python
colormap_prim.GetAttribute("domain").Set(Gf.Vec2f(min_val, max_val))
```

**For time-varying data**, query statistics at multiple timesteps and use the
global min/max so colors stay consistent across the animation.

**Validation**: After setting domain, verify visually that the render shows
multiple distinct colors across the data range. If it's still flat, the domain
is wrong or the field binding didn't take effect.

### Tight Colormap Domain (percentile / HDR)

Full ranges often contain outliers or large uniform-background regions that wash out the viz. Use a tighter domain.

**Symmetric percentile** — unimodal/symmetric data:
```python
r_min, r_max = np.percentile(np.asarray(farray), [7.5, 92.5])  # 85% of points
```

**HDR (highest-density region)** — skewed data (CT/MRI, sparse fields):
```python
s = np.sort(np.asarray(farray).ravel()); n = len(s); w = int(round(0.85 * n))
i = int(np.argmin(s[w:] - s[: n - w]))
r_min, r_max = float(s[i]), float(s[i + w])
```

HDR = tightest interval covering 85% of points — largest range reduction without losing data. Adjust cutoff (0.85/0.90/0.95) per how aggressively you want to clip. Apply via `colormap_prim.GetAttribute("domain").Set(Gf.Vec2f(r_min, r_max))` and disable auto-rescale (next subsection).

### Disable Auto-Rescale (REQUIRED with custom domains)

```python
if viz_prim.HasAPI(cae_viz.RescaleRangeAPI, "colors"):
    cae_viz.RescaleRangeAPI(viz_prim, "colors").CreateRescaleModeAttr().Set("disable")
```

## Glyph Sizing

Default glyph scale is 1.0. When combining glyphs with volume rendering,
reduce scale so the volume cloud remains visible:

```python
cae_viz.GlyphsAPI(viz_prim).CreateScaleAttr().Set(0.3)  # 30% of default
```

## Visibility Control

```python
UsdGeom.Imageable(prim).MakeInvisible()   # hide
UsdGeom.Imageable(prim).MakeVisible()     # show (clears to inherited)
```

Hide default scene light for self-illuminated volumes:

```python
for prim in stage.Traverse():
    if prim.GetTypeName() in ("DistantLight", "DomeLight", "SphereLight", "RectLight"):
        UsdGeom.Imageable(prim).MakeInvisible()
```

## Time-Varying Data

### Import with Time Mapping

```python
# CGNS / EnSight — scale spaces native steps on the USD timeline
await import_to_stage(path, prim_path, scale=2.0, offset=0.0, source="TimeStep")
```

`scale=2` places steps two time codes apart for temporal interpolation.

The file-format plugin authors time samples on OmniSci array attributes. Do not
mutate payload paths or legacy `fileNames` attributes during playback; drive the
USD timeline and let the operator controller select the effective sample.

### Temporal Interpolation

```python
cae_viz.OperatorTemporalAPI.Apply(viz_prim)
cae_viz.OperatorTemporalAPI(viz_prim).CreateEnableFieldInterpolationAttr().Set(True)
```

### Timeline Control

```python
import omni.timeline
tl = omni.timeline.get_timeline_interface()
tl.set_time_codes_per_second(FPS)
tl.set_current_time(frame / FPS)  # triggers operator re-evaluation
```

Allow 6–10 settle frames after `set_current_time()` for data + render update.

### Fixed Color Range

Lock range for time-varying data — see "Disable Auto-Rescale" above.

Statistics and Array Details are time-aware. When the timeline changes, query
the effective current sample or explicitly refresh stale UI statistics; do not
silently reuse a range from another timestep.

## Multi-Domain Composition

Import multiple datasets (even different formats) into the same stage:

```python
from omni.cae.usd_plugins_importers import import_to_stage

await import_to_stage(struct_file, "/World/structural")
await import_to_stage(cfd_file, "/World/cfd")
# Create operators on each independently
```

### Simulation on Geometry

Open USD geometry, then import simulation data on top:

```python
await omni.usd.get_context().open_stage_async(geometry_usd)
await import_to_stage(thermal_data, "/World/thermal")
```

## Point Cloud / AI Surrogate

```python
from omni.cae.usd_plugins_importers import import_to_stage
await import_to_stage(npz_path, "/World/inference", schema="Point Cloud")
```

Gaussian splatting for volumes from point clouds:

```python
cae_viz.DatasetGaussianSplattingAPI(viz_prim, "source").CreateRadiusFactorAttr().Set(5.0)
```

When a downstream cell-based operator needs one logical cell per source point,
apply `DatasetVoronoiPointCloudAPI:source` instead of inventing connectivity.

Kit-CAE uses centimeters (cm) — no automatic unit conversion on import.

`ScalarColor` is lighting-aware. Geometry-based planar slices use
`UnlitScalarColor` so diagnostic scalar colors do not depend on scene lighting.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module vtk` / `h5py` in a legacy workflow | `./repo.sh pip_download` |
| Never built | `./repo.sh build -r` |
| Empty screenshot | Increase wait frames (≥600) |
| `UnboundLocalError` | Move `omni.*` imports to top level |
| Faces `external_only not supported` | Use a surface/boundary dataset |
| Missing velocity field | Verify the OmniSci field instance names and the seed dataset target |
| Iso-surface is empty | Verify contour association/range and choose an iso-value inside the field range; empty output is intentionally hidden |
| Planar slice does not move | Transform the slice operator prim and call `wait_for_update()`; free mode uses transformed local +Y |
| Surface opacity has no effect | Bind a scalar to `FieldSelectionAPI:opacity`, set a valid opacity domain/LUT, and enable opacity mapping |
| Array Expression is absent from field discovery | Check diagnostics, ownership, enabled state, association compatibility, and dependency cycles |
| FLASH result is too coarse | Increase `angularCells` for reconstructed representations; direct axisymmetric volume does not use angular tessellation |
| Resolver asset does not open | Directory-scanning layouts may still require filesystem access; use a self-contained or explicitly linked asset |
| First run slow | Shader cache compilation (~2–3 min) — see preflight |
| Glyphs obscure volume | Reduce glyph scale: `GlyphsAPI(prim).CreateScaleAttr().Set(0.3)` |
| Volume appears uniform | Query field stats, set colormap domain to actual data range |
| Volume too dark | Increase opacity in transfer function mid-range |
| No color variation in volume | Set `colormapSource` to `"rgbaPoints"` or check domain |
| Custom domain overridden | Disable auto-rescale (`RescaleRangeAPI`) |
| `Gf.Vec2f` type error | Cast numpy values with `float()` |
| Point cloud volume empty | Set Gaussian splatting `RadiusFactor` (try 4–8) |
| Volume has flat ambient wash | Hide default scene light (see Visibility) |
| Time-varying data looks static | Verify imported array time samples and drive the timeline rather than mutating payload state. |
| VDB doesn't update per frame | Check `OperatorTemporalAPI`, the effective USD time code, and plugin-authored samples. |
| `UsdExpiredPrimAccessError` after long wait | Controller rebuilt the material prim. Re-fetch `stage.GetPrimAtPath(shader_path).GetAttribute(f"inputs:{name}")` each access instead of caching `shader.GetInput(...)` across `await wait_for_update(...)`. |

## Visual Validation Checklist

Before delivering any visualization, capture viewport images and inspect them.
For animations, inspect at least start, midpoint, transition points, and end.
Do not rely only on transform, keyframe, or log checks. Verify:

1. **Color variation**: The render shows at least 3–4 distinct colors across the
   data range. If it looks monochrome, the colormap domain is wrong.
2. **Time evolution** (for animations): Compare frame 0, middle, and last frame.
   They must look obviously different. If they look the same, data isn't updating.
3. **Camera purpose**: The camera motion should reveal something about the data
   that a static view wouldn't show. Orbit is a fallback, not a default.
4. **Data fills the frame**: The visualization should occupy a significant portion
   of the viewport, not be a tiny speck in the distance.
5. **Contrast**: Light features against dark background (or vice versa). Avoid
   mid-gray-on-mid-gray.
6. **Geometry correctness**: For iso-surfaces and planar slices, confirm the
   extracted geometry changes when the iso-value, direction, or transform changes.
7. **Opacity separation**: If opacity is field-driven, confirm color and opacity
   respond independently by changing one binding or domain at a time.
