"""OxeePhone brand layer (Oxeegen fork of Dograh).

Everything brand-specific on the backend lives in this package. Upstream files
only ever read ``BRAND`` flags from here, so each patch stays a one-line,
clearly-gated change that is easy to re-apply after an upstream merge.
"""

from api.brand.config import BRAND

__all__ = ["BRAND"]
