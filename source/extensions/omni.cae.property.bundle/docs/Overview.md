# Overview

`omni.cae.property.bundle` customizes the Kit Property panel for the active
OmniSci and OmniCaeViz schemas.

## Scientific-array properties

When exactly one OmniSci prim containing scientific arrays is selected, the bundle shows:

- **Arrays**, a cheap summary of the applied array and field instances;
- **Array Details**, an inspector for device, type, shape, component ranges,
  statistics, and an interactive histogram; and
- time-sample status, including a warning when computed details belong to an
  older effective sample.

Experimental Array Expressions use their standard instance schema group in the Property
panel. Expression properties provide native/derived array and function completion.
Valid enabled expressions are listed in Arrays and Array Details exactly like
native arrays; disabled or invalid expressions remain editable in their schema
group so they can be repaired or re-enabled.

Only schema metadata is read initially. Array values are materialized on a
worker thread after **Compute Details** or **Refresh Details** is pressed, so
opening the panel and scrubbing the timeline do not cause file reads.

## Visualization properties

The **Field Names** editor manages `CaeVizFieldSelectionAPI` bindings using
OmniSci field instance names. The **Operator Pipeline** section exposes the
selected visualization operator's inputs and dependencies.

The focused implementations live in `array_details_widget.py`,
`array_expression_widget.py`,
`field_names_widget.py`, and `operator_pipelines_widget.py`;
`property_widget.py` assembles them into the Property panel.
