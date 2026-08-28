# Changes made by Andrew Hobbs (ahobbs@astecindustries.com) August 25, 2026 with assistance by

# Claude

# Glyph (PointInstancer) Per-Instance Coloring — Implementation Notes

This document describes the per-instance coloring implementation for the **Glyphs**
(`CaeVizGlyphsAPI`) operator, including the root-cause analysis that drove the design and
the final architecture.

---

## Background — Why Per-Instance Primvars Don't Work

`UsdGeom.PointInstancer` supports per-instance primvars (e.g. `primvars:colors`,
`primvars:displayColor`) on the instancer itself. However, empirical testing with the
NVIDIA RTX renderer in Kit confirmed that **the renderer does not forward per-instance
PointInstancer primvars into the prototype's MDL shader context**. Regardless of the
primvar name, type, or how it is written (USD session layer, USDRT/Fabric), the prototype
shader only sees its own constant primvars — never the per-instance values on the
PointInstancer.

This rules out the approach used by the Points operator (writing a per-vertex
`primvars:colors` array and letting the MDL shader read it via
`scene::data_lookup_float("colors", ...)`).

---

## Solution — Multi-Prototype Binning with a Shared Master

The canonical USD mechanism for per-instance variation on a `PointInstancer` is
`protoIndices`: each prototype is a distinct prim with different constant properties, and
the instancer selects one prototype per instance.

### Architecture

**N = 32 prototype Xforms** (`GLYPH_NUM_PROTOTYPES`) are created under
`<PointInstancer>/Prototypes/` when the Glyphs operator is first built
(`CreateCaeVizGlyphs` command). Each prototype selects a distinct
**grayscale scalar** encoded as ``primvars:displayColor`` authored on the
prototype's composed Gprim(s):

```
prototype i  →  displayColor = (i/(N-1),  i/(N-1),  i/(N-1))
```

Prototype 0 → `(0, 0, 0)` (black), prototype 31 → `(1, 1, 1)` (white).

The shape geometry is authored **once** under a shared `class` prim
`GeomMaster`, and each of the 32 Xforms adds an internal reference to it.
`primvars:displayColor` is authored as a **local `over` on the composed
Gprim descendant path** of each Xform — putting the primvar directly on
the shaded prim, so the MDL shader's ``scene::data_lookup_color`` finds
it without relying on primvar inheritance from the Xform root or
native-instancing semantics.

```
PointInstancer
├── (positions / orientations / scales / protoIndices / prototypes rel)
├── Materials/ScalarColor
└── Prototypes (over)
    ├── GeomMaster (class)                 ← shape authored ONCE
    │   └── Sphere / Cone / Arrow-parts / <Custom template ref as `over`>
    ├── Xform_00 (def, references GeomMaster)
    │   └── <gprim_name> (over)            ← composed Gprim + local primvar
    │       primvars:displayColor = (0/31,  0/31,  0/31)
    ├── Xform_01 (def, references GeomMaster)
    │   └── <gprim_name> (over)
    │       primvars:displayColor = (1/31,  1/31,  1/31)
    ...
    └── Xform_31 (def, references GeomMaster)
        └── <gprim_name> (over)
            primvars:displayColor = (31/31, 31/31, 31/31)
```

Key layout rules:

- **`over` on the `Prototypes/` container** — UsdImaging reliably prunes
  prototype targets in this conventional under-PointInstancer location
  from normal scene traversal, so the wrappers only materialize as
  PointInstancer instances (never at world origin).
- **`class` on `GeomMaster`** — excluded from render traversal, but its
  descendants still compose through `AddInternalReference` into every
  Xform. Only one authored copy of the geometry exists in the layer.
- **`over` on the per-bin Gprim path** — USD composition merges the
  local primvar into the reference-composed Gprim, so the shader sees
  a unique `displayColor` on each of the 32 shaded prototypes.
- **No `SetInstanceable(True)`** — earlier attempts marked each Xform as
  a native instance to dedupe geometry, but native instancing moves the
  shaded Gprim into a shared master whose ancestor chain does not
  include the instance root, so per-bin primvars on the Xform were
  invisible to the shader. Authoring the primvar directly on the
  composed Gprim descendant removes any dependence on inheritance or
  instancing behavior; the trade-off is 32 rprims per operator instead
  of one (fine in practice because the multi-Gprim guard keeps each
  prototype small).

**Custom template rule.** The picked template must resolve to a single
Gprim. `_author_prototype_geometry` accepts either a `UsdGeom.Gprim`
directly or a scope with exactly one Gprim descendant, and rejects
anything else with a message naming the offending descendants. This
prevents the pathology where a scope (e.g. EDEM `ParticleTypes`)
composes multiple sub-Gprims under each Xform and every particle draws
every child at every instance point.

At operator execution time (`write_glyph_display_color`), each instance is assigned to a
prototype bin based on its normalised field value:

```python
normalised  = clip((field[i] - domain_min) / (domain_max - domain_min), 0, 1)
proto_index = clip(floor(normalised * N), 0, N-1)
```

The `protoIndices` array is written via **USDRT/Fabric only** (not the USD session layer)
to avoid conflicting with the Fabric state maintained for positions, scales, and
orientations. The array is 1-D `(N,)` `int32` — matching
`UsdGeom.PointInstancer.protoIndices`.

The MDL **ScalarColor** shader (`basic.mdl`, `use_vertex_color = true`) then:

1. Reads the prototype's constant `displayColor` via
   `scene::data_lookup_color("displayColor", color(0))`.
2. Extracts the scalar with `math::luminance(rgb)` — which equals `r` when `r == g == b`.
3. Performs the same LUT texture lookup used by the Points operator:
   `tex::lookup_color(lut, float2(scalar, 0), wrap_clamp, wrap_clamp)`.

This makes **LUT changes update automatically at render time** — the MDL shader
re-evaluates the texture lookup with no Python recomputation needed.

**Domain changes** require recomputing `protoIndices`, which requires operator
re-execution (see Controller section below).

---

## Files Changed

### `source/extensions/omni.cae.viz/material_library/cae/mdl/basic.mdl`

**`ScalarColor` material — added `use_vertex_color` and rewrote the coloring let-block.**

New signature adds a uniform bool `use_vertex_color = false`. The let-block:

```mdl
bool use_coloring    = (domain.x < domain.y) && enable_coloring;
float field          = scene::data_lookup_float("colors", 0.0f);
float field_norm     = use_coloring ? (field - domain.x) / (domain.y - domain.x) : 1.0f;
float proto_scalar   = math::luminance(scene::data_lookup_color("displayColor", color(0.0f)));
float lut_t          = use_vertex_color ? proto_scalar : field_norm;
bool  lut_active     = use_vertex_color || use_coloring;

color final_color = tex::texture_isvalid(lut) && lut_active ?
    tex::lookup_color(lut, float2(lut_t, 0.0f), tex::wrap_clamp, tex::wrap_clamp) : color(lut_t);
```

Both the glyph path (`use_vertex_color = true`) and the standard per-vertex scalar path
(`use_vertex_color = false`, `enable_coloring = true`) now go through the same
`tex::lookup_color` call.

---

### `source/extensions/omni.cae.viz/python/create_commands.py`

**Added `GLYPH_NUM_PROTOTYPES = 32` module constant** with a block comment explaining the
per-instance-primvar limitation and the multi-prototype workaround.

**`CreateCaeVizGlyphs.do()`** creates the prototype hierarchy under an
`over` child of the PointInstancer (`<primT>/Prototypes`) — the
conventional under-PointInstancer location that UsdImaging reliably
prunes from normal scene traversal. `use_vertex_color = True` is set on
the bound shader:

```python
protosPrim = stage.OverridePrim(primT.GetPath().AppendChild("Prototypes"))
primT.CreatePrototypesRel().SetTargets(self._create_prototypes(protosPrim))
...
shader.CreateInput("use_vertex_color", Sdf.ValueTypeNames.Bool).Set(True)
```

**`_create_prototypes(protosPrim)`** authors the shape geometry once
under a `class`-spec `GeomMaster` prim (via `stage.CreateClassPrim`),
receives the list of Gprim child names from
`_author_prototype_geometry`, and for each of the N Xforms adds an
internal reference to `GeomMaster` and authors a local `over` at
`Xform_i/<gprim_child_name>` with a constant grayscale
`primvars:displayColor`. Authoring on the composed Gprim descendant
guarantees the primvar lives on the shaded prim itself — no reliance on
primvar inheritance or native-instancing behavior.

**`_author_prototype_geometry(stage, parent_path)`** authors the shape
geometry into `GeomMaster` and returns the list of direct child names
that resolve to Gprims. For built-in shapes: `["Sphere"]`, `["Cone"]`,
`["Cylinder", "Cone"]`. For `Custom`: validates that the picked
template is a Gprim or a scope with exactly one Gprim descendant (else
raises with a message naming the offending descendants), then authors
an intermediate `over` inside `GeomMaster` that internally references
the template. `over` (not `def`) is used for the ref-carrying spec so
the referenced Gprim's typeName wins during composition rather than
being overridden by a locally authored `Xform`.

The previous single-prototype `_create_prototype` helper is removed.

---

### `source/extensions/omni.cae.viz/python/utils.py`

**New public function `write_glyph_display_color(prim, dataset)`** (added to `__all__`).

Responsibilities:

1. Early-return if the prim is not a `PointInstancer`.
2. If the dataset has no `colors` field, reset `protoIndices` to all-zeros (routes every
   instance to prototype 0) so stale bins from a previous run are cleared.
3. Validate the multi-prototype layout: if fewer than 2 prototype targets are wired up,
   log a warning telling the user to re-create the operator and return.
4. Resolve the bound MDL shader (via `UsdShade.MaterialBindingAPI.ComputeBoundMaterial()`
   and `ComputeSurfaceSource("mdl")`) and read `enable_coloring` and `domain`.
5. Self-heal: ensure `inputs:use_vertex_color = True` on the shader (covers operators
   authored before this input existed).
6. If coloring is disabled or the domain is degenerate (`dmin >= dmax`), write all-zero
   `protoIndices` (routes every instance to prototype 0).
7. Fetch the `colors` field, magnitude-reduce vector fields (matching the semantics of
   `RescaleRangeAPI.get_range()` for vectors), compute the normalised bin index array
   as 1-D `(N,)` `int32`, and write `protoIndices` via USDRT/Fabric.

The LUT lookup is entirely MDL-side; Python only needs to write `protoIndices`.

---

### `source/extensions/omni.cae.viz/python/points.py`

**`Glyphs.populate_glyphs`** invokes the new helper after the standard field-selection
processing:

```python
viz_utils.process_field_selection_apis(prim, points_dataset, exclude_fields={"scales", "orientations"})
viz_utils.write_glyph_display_color(prim, points_dataset)
```

No other changes to `points.py`.

---

### `source/extensions/omni.cae.viz/python/controller.py`

**Added shader-domain / LUT change detection for Glyphs prims.**

#### Imports

`UsdShade` added to the `from pxr import ...` line.

#### `_last_execution_cache` initialisation

Two new keys added to the per-prim cache entry:

```python
"glyph_shader_domain": None,   # last-seen Gf.Vec2f domain from the bound shader
"glyph_shader_lut": None,      # last-seen LUT asset path string
```

#### Cache update in the `_execute_operator` `finally` block

After each execution context, `_read_glyph_shader_state(prim)` is called and its result
is stored in the cache so the next sync can compare.

#### `_build_execution_context` — structural change check

One additional OR condition appended:

```python
structural_change = structural_change or self._has_glyph_shader_changed(prim, last_execution)
```

#### New method: `_read_glyph_shader_state(prim)`

Reads `inputs:domain` and `inputs:lut` from the MDL shader bound to a `PointInstancer`
prim. Returns `(None, None)` for non-PointInstancer prims or when no bound shader is
found. Exceptions are silently caught so it never raises during the sync loop.

#### New method: `_has_glyph_shader_changed(prim, last_execution)`

Compares the current shader domain and LUT against the values stored in `last_execution`.
Returns `True` (and updates the cache) when either value has changed. This causes the
controller to force operator re-execution, which recomputes `protoIndices` against the
new domain.

**Why this is necessary:** The bound material's shader prim carries no `Cae` schema, so
the `ChangeTracker` (which only monitors operator-prim property changes) does not see
edits to `inputs:domain` or `inputs:lut`. Without this check, adjusting the domain in the
property panel would have no visible effect on glyph colours.

---

## Data Flow Summary

```
Operator exec triggered
        │
        ▼
process_rescale_range_apis()
  └─ writes current domain to shader inputs:domain
        │
        ▼
populate_glyphs()
  ├─ writes positions / scales / orientations via USDRT
  └─ calls write_glyph_display_color()
       ├─ reads domain from shader
       ├─ normalises field values: t = clip((v - min) / (max - min), 0, 1)
       ├─ bins: proto_index = clip(floor(t * N), 0, N-1)
       └─ writes protoIndices via USDRT

                RTX render loop
                      │
                      ▼
        For each glyph instance i:
          prototype = Xform_{proto_index[i]}
          displayColor = (proto_index[i]/(N-1), ...)     ← grayscale scalar
          Xform composes GeomMaster's geometry via internal reference
          MDL ScalarColor shader (use_vertex_color = true):
            scalar = math::luminance(displayColor)
            color  = LUT.sample(scalar)                  ← current LUT texture
```

- **LUT PNG change** → MDL shader re-samples automatically on the next render frame; no
  operator re-execution required.
- **Domain change** → `_has_glyph_shader_changed` fires on the next sync, forcing
  operator re-execution, which recomputes `protoIndices` for the new range.
- **Number of bins** is controlled by `GLYPH_NUM_PROTOTYPES` at operator-creation time.
  N = 32 gives ~5-bit scalar quantization; increasing N reduces banding at the cost of
  extra USD prims at creation time (runtime cost per instance is unchanged, and the shape
  geometry is authored only once regardless of N).
