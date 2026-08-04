# Array Expression Language

Array Expressions are an experimental, versioned language for defining lazy
scientific arrays from arrays on the same USD prim. A valid derived array is
discoverable and loadable like a native array, including from visualization
operator field selectors.

This page is the language reference for `languageVersion = 1`. See the
[SimData Overview](Overview.md) for the authoring and runtime architecture.

## Quick start

Suppose a prim owns the scalar fields `dens`, `bery`, `pressure`, `vel_x`,
`vel_y`, and `vel_z`. Useful derived arrays include:

```text
beryllium_density = dens * bery
liner_density = if(ge(beryllium_density, 1e-4), beryllium_density, 0)
velocity = vec3(vel_x, vel_y, vel_z)
speed = magnitude(velocity)
positive_pressure = max(pressure, 0)
blanking = zeros_like(dens)
```

Expressions may reference native arrays and other enabled derived arrays on
the same prim. For example, `liner_density` depends on the derived
`beryllium_density` array. Dependency order does not matter, but cycles are
invalid.

## Value and layout rules

Version 1 has one numeric type: `float32`. Native inputs are materialized as
`float32`, numeric literals are converted to `float32`, and every result is a
scalar or 2-, 3-, or 4-component `float32` array.

Every expression must ultimately reference at least one field. Field
dependencies establish the result's tuple count and association. All
dependencies must have the same tuple count and association; the language does
not implicitly convert node data to element data or the reverse.

Most operations are component-wise. A scalar broadcasts when combined with a
vector:

```text
velocity * 0.001
velocity + vec3(offset_x, offset_y, offset_z)
clamp(velocity, -1, 1)
```

Two vectors must otherwise have the same component count. `magnitude`, `dot`,
`cross`, and `component` have the explicit vector semantics described below.

Field names must be identifier-shaped names such as `pressure` or
`velocity_1`. Names containing spaces, hyphens, colons, or path separators
cannot be referenced by version 1 expressions.

## Literals and operators

Integer, floating-point, and scientific-notation literals are supported.
Boolean, string, list, tuple, and `None` literals are not supported.

| Syntax | Meaning | Example |
|---|---|---|
| `+value` | Unary identity | `+pressure` |
| `-value` | Unary negation | `-pressure` |
| `left + right` | Component-wise addition | `pressure + 101325` |
| `left - right` | Component-wise subtraction | `temperature - 273.15` |
| `left * right` | Component-wise multiplication | `dens * bery` |
| `left / right` | Component-wise division | `momentum / dens` |
| `left ** right` | Component-wise exponentiation | `radius ** 2` |

Operator precedence follows ordinary mathematical/Python expression
precedence. `**` binds more tightly than unary minus, multiplication and
division bind more tightly than addition and subtraction, and parentheses can
make intent explicit. For example, `-radius ** 2` means `-(radius ** 2)`;
write `(-radius) ** 2` for the other interpretation.

The language does not support infix comparisons such as `pressure > 0`,
boolean operators such as `and` and `or`, or Python's ternary expression. Use
the comparison and conditional functions below.

## Comparison functions

Comparisons operate component-wise and return `0.0` for false or `1.0` for
true.

| Function | Meaning | Example |
|---|---|---|
| `ge(left, right)` | Greater than or equal | `ge(dens, 1e-4)` |
| `gt(left, right)` | Greater than | `gt(pressure, 0)` |
| `le(left, right)` | Less than or equal | `le(temperature, 373.15)` |
| `lt(left, right)` | Less than | `lt(mach, 1)` |
| `eq(left, right)` | Equal | `eq(material_id, 7)` |
| `ne(left, right)` | Not equal | `ne(volume_fraction, 0)` |

Scalar-to-vector broadcasting applies, so `ge(velocity, 0)` returns a
three-component mask. That vector mask cannot be used directly as an `if` or
`where` condition, which must be scalar. Select a component or reduce the
vector first, for example `gt(magnitude(velocity), 10)`.

Exact equality on computed floating-point values is often fragile. Prefer a
tolerance test when appropriate, for example:

```text
le(abs(pressure - reference_pressure), 1e-5)
```

## Conditional functions

| Function | Meaning | Example |
|---|---|---|
| `if(condition, when_true, when_false)` | Select by a scalar condition | `if(ge(dens, 1e-4), dens, 0)` |
| `where(condition, when_true, when_false)` | Equivalent spelling of `if` | `where(gt(pressure, 0), pressure, 0)` |

Zero is false and any nonzero value is true. The condition must be scalar. The
true and false values may be scalar or vector; a scalar branch broadcasts to
the width of a vector branch.

Both branches are evaluated before selection. `if` and `where` are not
short-circuit guards. This expression still evaluates `sqrt(pressure)` for
negative tuples:

```text
if(ge(pressure, 0), sqrt(pressure), 0)
```

Clamp or otherwise sanitize an input before applying a domain-restricted
operation:

```text
sqrt(max(pressure, 0))
```

## Scalar and component-wise math

Unless noted otherwise, these functions accept either a scalar or a vector and
operate independently on every component.

| Function | Meaning | Example |
|---|---|---|
| `abs(value)` | Absolute value | `abs(pressure_delta)` |
| `sqrt(value)` | Square root | `sqrt(max(energy, 0))` |
| `exp(value)` | Natural exponential | `exp(exponent)` |
| `log(value)` | Natural logarithm | `log(max(pressure, 1e-30))` |
| `sin(value)` | Sine, with radians as input | `sin(phase)` |
| `cos(value)` | Cosine, with radians as input | `cos(phase)` |
| `floor(value)` | Round toward negative infinity | `floor(region_coordinate)` |
| `ceil(value)` | Round toward positive infinity | `ceil(region_coordinate)` |
| `min(left, right)` | Component-wise minimum | `min(temperature, 1000)` |
| `max(left, right)` | Component-wise maximum | `max(pressure, 0)` |
| `pow(left, right)` | Component-wise power, equivalent to `**` | `pow(radius, 2)` |
| `clamp(value, minimum, maximum)` | Component-wise clamp | `clamp(volume_fraction, 0, 1)` |

`min` and `max` are not reductions across tuples or vector components. For
example, `max(velocity, 0)` clips each velocity component independently; it
does not find the largest component or the largest value in the array.

The result of `floor` and `ceil` remains `float32`. There are no integer result
arrays in version 1.

## Layout-matched constants

| Function | Meaning | Example |
|---|---|---|
| `zeros_like(reference)` | Fill the reference layout with `0.0` | `zeros_like(velocity)` |
| `ones_like(reference)` | Fill the reference layout with `1.0` | `ones_like(dens)` |
| `full_like(reference, value)` | Fill the reference layout with a literal | `full_like(velocity, -2.5)` |

These functions preserve the reference expression's tuple count, component
count, and association, but always produce `float32`; “like” does not preserve
the native numeric dtype. The `full_like` fill must be a signed numeric literal,
not a field or computed expression:

```text
full_like(pressure, 1e-4)       # valid
full_like(pressure, -2.5)       # valid
full_like(pressure, temperature) # invalid
```

The reference must ultimately depend on a field. `zeros_like(1)` is invalid
because a literal alone has no tuple count or association. A complex derived
reference is allowed, but it may perform unnecessary work when only its layout
is needed. Prefer a direct field with the desired layout where possible.

## Vector functions

| Function | Result | Example |
|---|---|---|
| `vec2(x, y)` | Two-component vector | `vec2(velocity_x, velocity_y)` |
| `vec3(x, y, z)` | Three-component vector | `vec3(velocity_x, velocity_y, velocity_z)` |
| `vec4(x, y, z, w)` | Four-component vector | `vec4(red, green, blue, alpha)` |
| `component(vector, index)` | Selected scalar component | `component(velocity, 2)` |
| `magnitude(value)` | Per-tuple Euclidean magnitude | `magnitude(velocity)` |
| `dot(left, right)` | Per-tuple scalar dot product | `dot(velocity, normal)` |
| `cross(left, right)` | Per-tuple 3-vector cross product | `cross(velocity, normal)` |

Every argument to `vec2`, `vec3`, and `vec4` must be scalar. To rearrange an
existing vector, select its components explicitly:

```text
vec3(component(velocity, 2), component(velocity, 1), component(velocity, 0))
```

`component` uses a zero-based integer literal from `0` through `3`, and the
index must exist in the input vector. Computed indices and negative indices are
not supported.

`dot` requires two vectors with matching component counts. `cross` requires
two three-component vectors. `magnitude` returns a scalar; for a scalar input it
is equivalent to `sqrt(value * value)`.

A normalized vector can be written with a protected denominator:

```text
velocity / max(magnitude(velocity), 1e-12)
```

## Complete authoring example

Each result is a `CaeArrayExpressionAPI:<array_name>` multiple-apply schema
instance on the prim that owns its dependencies:

```usda
def "FlowSolution" (
    prepend apiSchemas = [
        "CaeArrayExpressionAPI:velocity",
        "CaeArrayExpressionAPI:speed",
        "CaeArrayExpressionAPI:fast_velocity"
    ]
)
{
    uniform string cae:array:expression:velocity:expression =
        "vec3(vel_x, vel_y, vel_z)"
    uniform string cae:array:expression:velocity:displayName = "Velocity"
    uniform token cae:array:expression:velocity:computeDevice = "auto"
    uniform bool cae:array:expression:velocity:enabled = true
    uniform int cae:array:expression:velocity:languageVersion = 1

    uniform string cae:array:expression:speed:expression =
        "magnitude(velocity)"
    uniform string cae:array:expression:fast_velocity:expression =
        "if(gt(speed, 10), velocity, 0)"
}
```

The API instance name is the array name used by other expressions and operator
field selections. `displayName` is only the user-facing label.

For CGNS, author expressions on the `FlowSolution` prim that owns the arrays,
not on the zone or element prim used as an operator input. The same rule applies
to every format: the expression and all dependencies belong to one prim that
owns scientific arrays.

## Devices, time, and caching

`computeDevice = "auto"` evaluates on the device requested by the consumer.
Set it to `cpu` or an available `cuda:N` to force evaluation there; the result
is transferred to the requesting device if necessary. An unavailable explicit
device produces a load-time error.

Expressions resolve time-varying native and derived dependencies at the
requested time code. Compact scalar results are cached by the canonical
dependency graph, time code, and requested device. Changing the expression,
its dependency graph, the owner prim, time, or device prevents incompatible
cache reuse. Shared dependencies are memoized within one resolver request.

Evaluation occurs on raw scientific arrays before adapter-specific
representation transforms. For example, a compact axisymmetric FLASH graph is
evaluated before revolution into a three-dimensional representation.

## Common pitfalls

### Treating the language as Python

The parser uses Python syntax infrastructure, but the expression is not Python
and is never passed to `eval` or `exec`. Attribute access, indexing, calls to
arbitrary functions, comprehensions, lambdas, assignments, keyword arguments,
and imports are rejected. Use only the syntax and functions documented here.

```text
pressure > 0                 # invalid; use gt(pressure, 0)
math.sqrt(pressure)          # invalid; use sqrt(pressure)
velocity[0]                  # invalid; use component(velocity, 0)
clamp(pressure, min=0, max=1) # invalid; arguments are positional
```

### Mixing associations or tuple counts

Node- and element-associated fields cannot participate in the same expression.
Arrays with different tuple counts also cannot be combined. Convert or select
compatible fields before expression evaluation; version 1 provides no
association or resampling operators.

### Assuming conditionals short-circuit

Both conditional branches are evaluated. Use `max`, `min`, `clamp`, or another
safe transformation to keep inputs in range before division, `sqrt`, or `log`.

### Forgetting vector conditions are invalid

Comparing a vector with a scalar returns a vector mask. Conditions must be
scalar. Use `component`, `magnitude`, or `dot` to form the intended scalar
predicate.

### Expecting native precision or integer output

All inputs and outputs are materialized as `float32`. Large integers and
double-precision values may lose precision, and comparison results are numeric
`0.0`/`1.0` masks rather than booleans.

### Relying on undefined numeric domains

Division by zero, invalid `sqrt` or `log` inputs, overflow, infinity, and NaN
follow Warp and IEEE floating-point behavior. Ordered comparisons with NaN are
false, equality with NaN is false, and inequality with NaN is true. Sanitize
inputs when finite output is required.

### Creating dependency cycles or name collisions

A derived expression may depend on another derived expression, but the graph
must be acyclic. An expression instance name also cannot replace a native field
with the same name. Rename the derived array or its native source.

## Diagnostics

Invalid expressions remain editable in the Property panel but are omitted from
field discovery. Diagnostics include a source position when one is available.

| Code | Meaning | Typical correction |
|---|---|---|
| `E_EMPTY` | The expression is empty | Enter an expression |
| `E_SYNTAX` | The text is not a valid expression | Fix delimiters or punctuation |
| `E_UNSUPPORTED` | Syntax or a function is outside version 1 | Use an allowlisted construct |
| `E_ARITY` | A function has the wrong argument count | Supply the documented positional arguments |
| `E_COMPONENT_INDEX` | A component index is invalid | Use an existing zero-based integer component |
| `E_FILL_VALUE` | `full_like` has a computed fill | Use a signed numeric literal |
| `E_NO_DEPENDENCY` | No field establishes layout | Reference a native or derived field |
| `E_UNKNOWN_FIELD` | A field name cannot be resolved on the owner prim | Check spelling and expression ownership |
| `E_DISABLED_DEPENDENCY` | A referenced derived field is disabled | Enable it or remove the dependency |
| `E_CYCLE` | Derived dependencies form a cycle | Break the recursive dependency |
| `E_COLLISION` | A derived name conflicts with a native field | Rename the expression instance |
| `E_ASSOCIATION` | Dependencies use different associations | Use fields with one association |
| `E_VECTOR_LENGTH` | Vector widths cannot broadcast | Use a scalar or matching vector widths |
| `E_VECTOR_ARGUMENT` | A vector function received the wrong shape | Construct or select the required shape |
| `E_VECTOR_CONDITION` | A conditional received a vector mask | Reduce or select a scalar condition |
| `E_VERSION` | `languageVersion` is unsupported | Set it to `1` |

Tuple-count mismatches and unavailable compute devices are reported when the
array is loaded because they depend on runtime values or configuration.

## Version 1 limitations

Version 1 does not provide reductions across tuples, association conversion,
resampling, arbitrary constants without a field dependency, graph fusion,
persistent authored results, user-defined functions, or access to arbitrary
Python/Warp code.
