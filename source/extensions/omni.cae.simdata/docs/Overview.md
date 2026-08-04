# Overview

This extension provides SimData-based data processing capabilities for CAE workflows.

## Experimental array expressions

The authoring and runtime boundaries are described below.

Any prim that owns `OmniSciFieldAPI` and `OmniSciArrayAPI` instances can author
lazy derived arrays with the multiple-apply
`CaeArrayExpressionAPI:<array_name>` schema. The expression and every native or
derived dependency belong to that same prim. For CGNS this means authoring an
array expression on its `FlowSolution` prim, not on the zone or element prim
used as an operator input. Valid, enabled expressions appear in field selectors
and Array Details. Visualization operators load them through the same
`GetField` interface as native fields, while array-oriented consumers use the
raw-array provider interface described below.

At load time, Kit gives each expression ordinary `OmniSciFieldAPI` and
`OmniSciArrayAPI` metadata on its owner prim with a virtual `:value` attribute.
Warp SimData asks the scoped value resolver for that payload through
`get_sci_array`, exactly where it would otherwise read an authored array.
Dependencies always use the same resolver, so expressions can reference other
expressions. Dataset-specific representation work—such as expanding a compact
FLASH field around an axis—is performed once, after the complete raw expression
graph has evaluated.

## Raw scientific-array providers

`register_array_value_provider()` lets an extension supply virtual
`OmniSciArrayAPI` values without requiring the array to be a field or authoring
its payload into USD. A provider declares whether it owns an array instance,
materializes that raw array for a requested time and device, and reports the
times at which its value changes. Registration returns a lifetime token that
the owning extension closes during shutdown.

`materialize_array()` resolves expression and format-specific providers before
falling back to the authored `omni:sci:array:<instance>:value` attribute.
Dependencies re-enter the same resolver, so expressions can consume virtual
format arrays and other expressions. `get_array_time_samples()` and
`effective_array_time_sample()` expose the corresponding sampling domain to
array-oriented UI without reading the payload.

For example, apply these APIs to the prim that owns the FLASH arrays:

```usda
apiSchemas = [
    "CaeArrayExpressionAPI:beryllium_density",
    "CaeArrayExpressionAPI:liner_density"
]
string cae:array:expression:beryllium_density:expression = "dens * bery"
string cae:array:expression:liner_density:expression =
    "if(ge(beryllium_density, 1e-4), beryllium_density, 0)"
```

`liner_density` can then be selected directly as an iso-surface contour field.
The standard Array Expression schema properties provide field/function
completion and live diagnostics. **Enabled** can be cleared to keep an authored
expression without exposing it as an available field.

### Version 1 language

The complete syntax and function reference, with examples, diagnostics, and
common pitfalls, is available in the
[Array Expression Language](ArrayExpressionLanguage.md) guide.

Field names, decimal numeric literals, parentheses, unary `+`/`-`, and the
operators `+`, `-`, `*`, `/`, and `**` are supported. The function set is:

- comparisons: `ge`, `gt`, `le`, `lt`, `eq`, and `ne`;
- conditionals: `if` and its equivalent spelling `where`;
- scalar/component-wise math: `abs`, `sqrt`, `exp`, `log`, `sin`, `cos`,
  `floor`, `ceil`, `min`, `max`, `pow`, and `clamp`;
- layout-matched constants: `zeros_like`, `ones_like`, and `full_like`; and
- vectors: `vec2`, `vec3`, `vec4`, `component`, `magnitude`, `dot`, and `cross`.

`zeros_like(reference)` and `ones_like(reference)` produce `0.0` and `1.0`
with the reference expression's tuple count, component count, and association.
`full_like(reference, value)` does the same for a signed numeric literal, for
example `full_like(velocity, -2.5)`. As with all version 1 results, the output
type is `float32`; “like” describes field layout rather than numeric dtype.
The reference must ultimately depend on at least one field so tuple count and
association are defined.

All dependencies must have the same field association and tuple count. Scalars
broadcast across vector components; other vector operations require compatible
component counts. `component` uses a zero-based integer literal, and `cross`
requires two three-component values. Implicit association conversion is not
performed.

Inputs and results are materialized as `float32`. Comparisons return `0.0` or
`1.0`, and any other nonzero condition is true. Both branches of `if`/`where`
are evaluated. Division by zero and invalid math domains follow Warp/IEEE
floating-point behavior and may produce infinity or NaN; comparisons with NaN
follow IEEE comparison behavior.

`languageVersion` must be `1`. `computeDevice = "auto"` inherits the requesting
operator device; `cpu` or an available `cuda:N` can be selected explicitly, with
the result transferred back to the requesting device. Compact scalar results
are cached by canonical dependency graph, time code, and requested device,
independently of visualization representation, and are invalidated when the
owner prim changes. All values are memoized within one resolver scope so a
shared derived dependency evaluates once per load.

Invalid expressions are omitted from field discovery and report a diagnostic
code plus source position in the Property panel. Unknown fields, native-name
collisions, disabled dependencies, cycles, unsupported syntax, and association
mismatches are rejected. Authored text is never evaluated as Python code.

A reusable FLASH authoring layer is included at
`data/flash_array_expressions.usda`; sublayer it over a stage whose dataset is
`/World/Flash`, or copy the API properties to the prim that owns the desired
scientific arrays.
