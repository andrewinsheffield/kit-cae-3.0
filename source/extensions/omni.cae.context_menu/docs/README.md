# Context Menu Extension (omni.cae.context_menu)

This extensions adds Kit-CAE specific context menu actions. These actions use `omni.kit.commands` to handle trigger responses.

The **CAE Sources** menu can create texture-ready Colormap prims. A Colormap
with `CaeVizColormapTextureAPI` exposes separate **Copy Color LUT Texture URL**
and **Copy Opacity LUT Texture URL** actions. MDL-shaded visualization
operators also offer `opacity` as a field-selection instance.
