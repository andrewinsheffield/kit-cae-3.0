# CAE Property Bundle

This extension adds Property panel editors and inspectors for OmniSci datasets
and OmniCaeViz operators.

It provides:

- an arrays summary and opt-in **Array Details** inspector;
- time-aware component ranges, statistics, and histograms;
- an editor for visualization field-name bindings; and
- an operator-pipeline view for inspecting visualization dependencies.

Heavy array payloads are never read merely by opening the Property panel. Select
an array and use **Compute Details** when values are needed; use **Refresh
Details** after the effective time sample changes.

See [Overview](Overview.md) for the component layout and lazy-loading contract.
