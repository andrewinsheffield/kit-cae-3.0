# Overview

This internal extension brings the Kit-CAE-owned `OmniCaeViz` schemas and the
legacy `OmniCae` schema family into Omniverse. The USD schema plugins are
registered at startup from the extension's `usd/plugin` root by
`omni/cae/schema/extension.py`.

The schema Python modules are published under the `pxr` namespace (matching Pixar's USD schema
convention), so they can also be imported directly, e.g.
`from pxr import OmniCae, OmniCaeSids, OmniCaeViz`.

Schemas supplied by other USD plugin packages are not re-exported from
`omni.cae.schema`. Enable `omni.cae.usd_plugins` and import active scientific
data schemas from `pxr`, for example `from pxr import OmniSci,
OmniSciReservoir`. New datasets should use this OmniSci model.

The following example is specifically for a legacy `CaeDataSet` stage:

```py
from omni.cae.schema import cae, sids
from pxr import Usd

# to check if a prim is a CaeDataSet
prim: Usd.Prim = ...
if prim.IsA(cae.DataSet):
    ds = cae.DataSet(prim)
    # ....

# to check if a prim has
if prim.HasAPI(sids.UnstructuredAPI):
    sidsApi = sids.UnstructuredAPI(prim):
    ...
else:
   sids.UnstructuredAPI.Apply(prim)

```
