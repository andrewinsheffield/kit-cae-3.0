# Omni CAE Data [omni.cae.data]

> Deprecated compatibility extension. Active USD-plugin based workflows should use `omni.cae.core`,
> `omni.cae.usd_plugins`, `omni.cae.simdata`, and `omni.cae.viz` instead.

This extension introduces the concept of **Data Delegate**.
The Data Delegate API provides an extensible mechanism to add support for handling `CaeFieldArray` prim and its subtypes. Data Delegate
has two sets of APIs: APIs to access raw data referenced by a `CaeFieldArray` prim, and APIs to register delegates that can handle the
*reading* of raw data referenced by a subtype of `CaeFieldArray`.

Dataset conversion and visualization processing are handled by `omni.cae.simdata` and the SimData-backed operators in `omni.cae.viz`.
