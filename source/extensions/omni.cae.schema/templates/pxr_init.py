# OpenUSD installs pxr as a regular Python package whose __path__ only points
# at OpenUSD's own lib/python/pxr directory. CAE schema bindings install as
# sibling pxr subpackages under this extension, so extend the package path
# before importing modules such as `from pxr import OmniCae`.

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
