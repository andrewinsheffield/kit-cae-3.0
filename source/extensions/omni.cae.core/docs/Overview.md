# Overview

`omni.cae.core` contains active CAE utility modules used by USD-plugin backed
workflows:

- array conversion helpers for NumPy, Warp, DLPack, and UsdRT arrays
- USD schema traversal and time-sample helpers
- cache and progress helpers used by SimData and visualization operators
- command helpers shared by CAE extensions

Legacy Data Delegate APIs, `CaeFieldArray` wrappers, and delegate-backed array
loading remain in `source/legacy_extensions/omni.cae.data`.
