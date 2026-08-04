# CAE Visualization Extension

This extension provides visualization operators and utilities for CAE (Computer-Aided Engineering) data using the OmniCaeViz USD schemas.

## Overview

The `omni.cae.viz` extension serves as a foundation for CAE visualization capabilities in Omniverse. It works with the OmniCaeViz USD schemas to enable:

- Dataset selection and field visualization
- Glyph-based visualizations (vectors, points)
- Surface extraction and rendering
- Streamline visualization
- Volume rendering
- Voxelization and point cloud processing through SimData operators

## Dependencies

This extension depends on:
- `omni.cae.schema` - Provides the core USD schemas including OmniCaeViz
- `omni.cae.core` - Provides shared USD, array, cache, command, and progress utilities
- `omni.cae.simdata` - Provides the data processing operators used by visualization operators
- `omni.usd` - USD core functionality

## Usage

Import the extension:

```python
import omni.cae.viz
```

The extension automatically initializes when enabled and provides access to visualization utilities and operators.

### Field-driven opacity

Faces, Points, Glyphs, Iso Surfaces, Streamlines, and Planar Slices support an
independent `opacity` field selection. The selected scalar field is rescaled
through the material's **Opacity Domain**, sampled through **Opacity LUT**, and
multiplied by **Opacity** before driving MDL cutout opacity. With no opacity
field selected, these materials remain fully opaque.

A texture-enabled `Colormap` publishes two stable dynamic texture URLs:

- `dynamic://cae_colormap_<identifier>` contains the RGBA color lookup table.
- `dynamic://cae_opacitymap_<identifier>` contains the Colormap alpha channel
  as an opaque grayscale lookup table.

Use the color URL for a material's **Color LUT** and the opacity URL for
**Opacity LUT**. Changing the Colormap points updates both textures.

## API Overview

The extension provides utilities for working with OmniCaeViz schemas:

- **Dataset Selection API**: Apply and manage dataset selections on prims
- **Field Selection API**: Select and configure field arrays for visualization
- **Visualization APIs**: Apply glyph, surface, streamline, and volume APIs to prims

## Development

To extend this extension:

1. Add new operator modules to the `python/` directory
2. Register new commands in `create_commands.py`
3. Update the extension initialization in `extension.py` as needed

## See Also

- [OmniCaeViz Schema Documentation](../../../../docs/CaeVizSchemas.md)
- [CAE Core Extension](../../omni.cae.core/docs/README.md)
- [CAE Schema Extension](../../omni.cae.schema/docs/README.md)
