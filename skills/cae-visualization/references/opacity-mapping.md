# Independent Field-Driven Opacity

Faces, Points, Glyphs, Iso Surfaces, Streamlines, and Planar Slices can map
opacity from a scalar field independently of their color field.

```python
cae_viz.FieldSelectionAPI(operator, "colors").CreateFieldNamesAttr().Set(
    ["Temperature"]
)
cae_viz.FieldSelectionAPI(operator, "opacity").CreateFieldNamesAttr().Set(
    ["VolumeFraction"]
)
```

Creation commands author `FieldSelectionAPI:opacity`,
`RescaleRangeAPI:opacity`, and these MDL inputs:

- `opacity_domain`: scalar range mapped through the opacity LUT.
- `opacity_lut`: grayscale 1-D lookup texture.
- `opacity`: multiplier applied after the lookup.
- `enable_opacity`: enabled automatically when a valid opacity field is active.

Set the domain and LUT on the operator's MDL shader. Material paths differ by
operator, so inspect the material prim rather than assuming one path:

```python
shader = UsdShade.Shader(shader_prim)
shader.GetInput("opacity_domain").Set(Gf.Vec2f(float(low), float(high)))
shader.GetInput("opacity_lut").Set("cae/colormaps/gist_gray.png")
shader.GetInput("opacity").Set(0.8)
shader.GetInput("enable_opacity").Set(True)

if operator.HasAPI(cae_viz.RescaleRangeAPI, "opacity"):
    cae_viz.RescaleRangeAPI(
        operator, "opacity"
    ).CreateRescaleModeAttr().Set("disable")
```

Explicitly set `enable_opacity` when disabling auto-rescale. Rescale mode
`disable` preserves authored inputs but does not automatically toggle the
material enable input.

A Colormap with `CaeVizColormapTextureAPI` publishes two stable textures:

- `dynamic://cae_colormap_<identifier>` contains the RGBA color LUT.
- `dynamic://cae_opacitymap_<identifier>` contains the Colormap alpha channel
  as an opaque grayscale LUT.

Use the first URL for `lut` and the second for `opacity_lut`. Editing the
Colormap updates both.

This mechanism is separate from volume-rendering transfer-function alpha.
Volumes and volume slices continue to use their Colormap RGBA transfer
function. Validate color and opacity independently by changing only one field
or domain at a time.
