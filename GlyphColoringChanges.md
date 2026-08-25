# Changes made by Andrew Hobbs (ahobbs@astecindustries.com) June 23, 2026 with assistance by
# Claude

# Glyph (PointInstancer) Per-Instance Coloring — Implementation Notes

This document summarises the changes made to implement correct per-instance coloring for
the **Glyphs** (`CaeVizGlyphsAPI`) operator, including the root-cause analysis that drove
the design, and the final architecture used.

---

## Background — Why Per-Instance Primvars Don't Work

`UsdGeom.PointInstancer` supports per-instance primvars (e.g. `primvars:colors`,
`primvars:displayColor`) on the instancer itself.  However, empirical testing with the
NVIDIA RTX renderer in Kit confirmed that **the renderer does not forward per-instance
PointInstancer primvars into the prototype's MDL shader context**.  Regardless of the
primvar name, type, or how it is written (USD session layer, USDRT/Fabric), the
prototype shader only sees its own constant primvars — never the per-instance values on
the PointInstancer.

This rules out the approach used by the Points/Mesh operators (writing a per-vertex
`primvars:colors` array and letting the MDL shader read it via
`scene::data_lookup_float("colors", ...)`).

---

## Solution — Multi-Prototype Binning

The canonical USD mechanism for per-instance variation on a `PointInstancer` is
`protoIndices`: each prototype can be a distinct prim with different constant properties,
and the instancer selects one prototype per instance.

### Architecture

**N = 32 prototype Xforms** are created under `Prototypes/` when the Glyphs operator is
first built (`CreateCaeVizGlyphs` command).  Each prototype carries a constant
`primvars:displayColor` that encodes a **grayscale scalar**:

```
prototype i  →  displayColor = (i/(N-1),  i/(N-1),  i/(N-1))
```

Prototype 0 → `(0, 0, 0)` (black), prototype 31 → `(1, 1, 1)` (white).

At operator execution time (`write_glyph_display_color`), each instance is assigned to a
prototype bin based on its normalised field value:

```python
normalised  = clamp((field[i] - domain_min) / (domain_max - domain_min), 0, 1)
proto_index = clamp(floor(normalised * N), 0, N-1)
```

The `protoIndices` array is written via **USDRT/Fabric only** (not USD session layer) to
avoid conflicting with the Fabric state maintained for positions, scales, and
orientations.

The MDL **ScalarColor** shader (`basic.mdl`, `use_vertex_color = true`) then:

1. Reads the prototype's constant `displayColor` via
   `scene::data_lookup_color("displayColor", color(0))`.
2. Extracts the scalar with `math::luminance(rgb)` — which equals `r` when `r == g == b`.
3. Performs the same LUT texture lookup used by the Points operator:
   `tex::lookup_color(lut, float2(scalar, 0), wrap_clamp, wrap_clamp)`.

This makes **LUT changes update automatically at render time** — the MDL shader
re-evaluates the texture lookup with no Python recomputation needed.

**Domain changes** require recomputing `protoIndices` (step above), which requires
operator re-execution (see Controller section below).

---

## Files Changed

### `source/extensions/omni.cae.viz/material_library/cae/mdl/basic.mdl`

**ScalarColor material — `use_vertex_color` path rewritten.**

Previously when `use_vertex_color = true` the shader read `displayColor` and output it
directly as the surface tint, bypassing the LUT entirely.

New behaviour:

```mdl
float proto_scalar = math::luminance(scene::data_lookup_color("displayColor", color(0.0f)));
float field_scalar = use_coloring ?
    (scene::data_lookup_float("colors", 0.0f) - domain.x) / (domain.y - domain.x) : 1.0f;

float lut_t = use_vertex_color ? proto_scalar : field_scalar;

color final_color = tex::texture_isvalid(lut) && (use_vertex_color || use_coloring) ?
    tex::lookup_color(lut, float2(lut_t, 0.0f), tex::wrap_clamp, tex::wrap_clamp) : color(lut_t);
```

Both the glyph path (`use_vertex_color = true`) and the standard scalar path
(`use_vertex_color = false`, `enable_coloring = true`) now go through the same
`tex::lookup_color` call.

---

### `source/extensions/omni.cae.viz/python/create_commands.py`

**Prototype display colors changed from rainbow to grayscale encoding.**

`_sample_rainbow_colors` (which produced actual RGB colors by sampling the LUT at
creation time) was removed.  The `_create_prototypes` loop now computes inline:

```python
n = GLYPH_NUM_PROTOTYPES
colors = [Gf.Vec3f(i / max(n - 1, 1), i / max(n - 1, 1), i / max(n - 1, 1)) for i in range(n)]
```

These fixed grayscale scalars are written once at operator creation time and never need
to be updated — the MDL shader handles the colour mapping at render time.

The block comment on `GLYPH_NUM_PROTOTYPES` and `_create_prototypes` was updated to
document the new design.

---

### `source/extensions/omni.cae.viz/python/utils.py`

**LUT sampling helpers removed; `write_glyph_display_color` simplified.**

Three helper functions that were introduced to sample the LUT PNG and update prototype
display colors at Python level are no longer needed and were removed:

- `_resolve_lut_asset_path`
- `_sample_lut_image`
- `_update_prototype_display_colors`

`write_glyph_display_color` was simplified to:

1. Early-return if the prim is not a `PointInstancer` or has no `colors` field.
2. Validate the multi-prototype layout (warns and returns if `num_protos < 2`, directing
   the user to re-create the operator).
3. Resolve the bound MDL shader and read `enable_coloring` / `domain`.
4. Self-heal: ensure `use_vertex_color = True` on the shader (covers operators created
   before this fix).
5. If coloring is disabled or the domain is degenerate, write all-zero `protoIndices`
   (routes all instances to prototype 0).
6. Fetch the `colors` field, reduce vector fields to magnitude (matching
   `RescaleRangeAPI`), compute normalised bin indices, and write `protoIndices` via
   USDRT/Fabric.

The LUT lookup is now entirely MDL-side; Python only needs to write `protoIndices`.

---

### `source/extensions/omni.cae.viz/python/controller.py`

**Import additions and glyph shader change detection.**

#### Imports

`UsdShade` and `Gf` added to the `from pxr import ...` line (needed by the new methods).

#### `_last_execution_cache` initialisation

Two new keys added to the per-prim cache entry:

```python
"glyph_shader_domain": None,   # last-seen Gf.Vec2f domain from the bound shader
"glyph_shader_lut": None,      # last-seen LUT asset path string
```

#### Cache update in `_execute_operator` `finally` block

After each execution context, `_read_glyph_shader_state(prim)` is called and its result
is stored in the cache so the next sync can compare.

#### `_build_execution_context` — structural change check

One additional OR condition appended:

```python
structural_change = structural_change or self._has_glyph_shader_changed(prim, last_execution)
```

#### New method: `_read_glyph_shader_state(prim)`

Reads `inputs:domain` and `inputs:lut` from the MDL shader bound to a
`PointInstancer` prim.  Returns `(None, None)` for non-PointInstancer prims or if no
bound shader is found.  Exceptions are silently caught so it never raises during the
sync loop.

#### New method: `_has_glyph_shader_changed(prim, last_execution)`

Compares the current shader domain and LUT against the values stored in
`last_execution`.  Returns `True` (and updates the cache) when either value has
changed.  This causes the controller to force operator re-execution, which recomputes
`protoIndices` against the new domain.

**Why this is necessary:** The bound material's shader prim does not carry any `^Cae`
schema, so the `ChangeTracker` (which only monitors operator-prim property changes) does
not see edits to `inputs:domain` or `inputs:lut`.  Without this check, adjusting the
domain in the property panel had no visible effect on glyph colours.

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
       ├─ normalises field values: t = (v - min) / (max - min)
       ├─ bins: proto_index = floor(t * N)   (clamped to [0, N-1])
       └─ writes protoIndices via USDRT

                RTX render loop
                      │
                      ▼
        For each glyph instance i:
          prototype = Xform_{proto_index[i]}
          displayColor = (proto_index[i]/(N-1), ...)   ← grayscale scalar
          MDL ScalarColor shader:
            scalar = math::luminance(displayColor)
            color  = LUT.sample(scalar)                ← current LUT texture
```

When the **LUT PNG is changed**: the MDL shader automatically re-evaluates at the next
render frame with no operator re-execution required.

When the **domain is changed**: the controller's `_has_glyph_shader_changed` check fires
on the next sync, triggering operator re-execution, which recomputes `protoIndices` for
the new range.
