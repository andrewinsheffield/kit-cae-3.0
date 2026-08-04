# ROI and Dataset Subsetting

Use a region-of-interest prim to reduce an operator's input before visualization.
The ROI relationship reads the target prim's axis-aligned world-space bounds.

For a cell-mesh operator:

```python
roi_path = "/World/CAE/ROI"
roi = UsdGeom.Cube.Define(stage, roi_path)
roi.CreateSizeAttr().Set(1.0)
UsdGeom.Xformable(roi).AddTranslateOp().Set(roi_center)
UsdGeom.Xformable(roi).AddScaleOp().Set(roi_scale)

if not operator.HasAPI(cae_viz.DatasetSubsetAPI, "source"):
    cae_viz.DatasetSubsetAPI.Apply(operator, "source")

subset = cae_viz.DatasetSubsetAPI(operator, "source")
subset.CreateRoiRel().SetTargets([roi.GetPath()])
subset.CreateModeAttr().Set("centroid")
subset.CreateInflateBoundsAttr().Set(0)
await wait_for_update()
```

Modes:

- `all`: every cell vertex must be inside.
- `any`: at least one cell vertex must be inside.
- `centroid`: the geometric cell centroid must be inside.

For VDB/voxelized operators, use the matching
`DatasetVoxelizationAPI:source` ROI relationship instead. Creation commands
normally apply the appropriate subset or voxelization API.

Moving, rotating, or scaling the ROI target re-executes dependent operators.
Validate at least two ROI transforms and confirm the rendered subset changes in
both directions. `inflateBounds` expands the ROI bounds by a percentage before
processing.

The visualization bounding-box command is useful for framing but is not the
only valid ROI shape. Any prim with suitable bounds can be targeted.
