# Derived Arrays for Visualization

Array Expressions define lazy scalar or vector arrays that participate in
field discovery and visualization selection like native fields. Use them for
array-level transformations before binding an operator:

```python
from omni.cae.schema import cae

velocity = cae.ArrayExpressionAPI.Apply(array_owner_prim, "velocity")
velocity.CreateExpressionAttr().Set("vec3(vel_x, vel_y, vel_z)")
velocity.CreateDisplayNameAttr().Set("Velocity")
velocity.CreateComputeDeviceAttr().Set("auto")
velocity.CreateEnabledAttr().Set(True)
velocity.CreateLanguageVersionAttr().Set(1)

speed = cae.ArrayExpressionAPI.Apply(array_owner_prim, "speed")
speed.CreateExpressionAttr().Set("magnitude(velocity)")
speed.CreateEnabledAttr().Set(True)
speed.CreateLanguageVersionAttr().Set(1)
```

Bind the expression instance name exactly as a native field:

```python
cae_viz.FieldSelectionAPI(operator, "colors").CreateFieldNamesAttr().Set(
    ["speed"]
)
```

Useful expressions include:

```text
velocity = vec3(vel_x, vel_y, vel_z)
speed = magnitude(velocity)
positive_pressure = max(pressure, 0)
visible_fraction = if(ge(volume_fraction, 1e-4), volume_fraction, 0)
blanking = zeros_like(density)
```

Critical rules:

- Author the expression on the prim that owns all dependency arrays. For CGNS,
  this is commonly a FlowSolution prim, not the zone or element dataset prim.
- All dependencies must have compatible tuple counts and associations.
- Version 1 materializes scalar or 2/3/4-component `float32` arrays.
- Expressions may depend on other enabled expressions, but cycles and native
  field-name collisions are invalid.
- The language is not Python. It supports a fixed expression grammar and
  allowlisted functions.
- It has no dataset topology, connectivity, neighborhood inspection,
  association conversion, gradients, divergence, or other spatial derivatives.
- Time and device are part of evaluation and cache identity.

Invalid expressions remain editable but are omitted from field discovery.
Inspect Array Expression diagnostics before debugging the visualization.

Full language reference:
`source/extensions/omni.cae.simdata/docs/ArrayExpressionLanguage.md`.
