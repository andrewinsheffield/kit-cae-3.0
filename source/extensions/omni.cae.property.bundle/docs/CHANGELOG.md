# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.6.0]

- Array summary rows now select the corresponding Array Details entry and
  expand the details section.

## [2.5.0]

- Array Details now materializes raw arrays through registered SimData
  providers, enabling details and temporal state for virtual format arrays
  without requiring field semantics or authored USD values.

## [2.4.0]

- Added field/function completion, including constant-like functions, and validation to the
  standard experimental Array Expression schema property group, plus derived arrays in Arrays
  and Array Details.
- Added `CaeVizDatasetAxisymmetricRepresentationAPI` to the Operator Pipeline editor.

## [2.3.0]

- Added `CaeVizDatasetDualAPI` to the Operator Pipeline editor.

## [2.2.1]

- Array details now track the effective timeline sample, clearly mark statistics as obsolete after
  the sample changes while leaving them visible for inspection, and keep a **Refresh Details** action
  available without performing heavy reads during playback or scrubbing.

## [2.2.0]

- Added an **Array Details** section to the OmniSci property widget. A dropdown selects an array
  instance and shows its metadata: cheap fields (name, association, device, dtype) are shown
  immediately, while shape, range, scalar statistics and an interactive histogram are computed
  on demand via a **Compute Details** button (with status-bar progress) so heavy array payloads are
  only read when requested.
- For multi-component (vector) arrays, added a **Component** dropdown to view statistics and the
  histogram for the magnitude (default) or any individual component.

## [2.1.0]

- Added an **Operator Pipeline** editor widget that surfaces the upstream operator graph for a selected
  CAE prim and lets users navigate or edit pipeline stages directly from the Property panel.
- Added a dedicated **Field Names** property widget with multi-select editing, autocomplete from
  available fields, and clearer summary text. Polished field selection controls in the operator
  property widget.
- Polished property field summaries shown on collapsed operator API frames.

## [2.0.0]

- Considerable refactor to present properties for CAE operators to users in a more intuitive fashion.
- Moved the legacy `CaeFieldArray` inspector to `omni.cae.property.legacy`.

## [1.0.0]

- Initial version.
