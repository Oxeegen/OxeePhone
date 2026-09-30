"""Stand-in for the Dograh Model Proxy Service client.

When ``BRAND.disable_dograh_services`` is on, the MPS singleton is replaced by
this object: any method call fails fast with ``MPSUnavailableError`` instead of
reaching services.dograh.com. Callers already handle that error (it is how an
MPS outage surfaces), so no call site needs to change.
"""

from loguru import logger

from api.errors.mps import MPSUnavailableError


class DisabledMPSClient:
    base_url = ""

    def __getattr__(self, operation: str):
        if operation.startswith("__"):
            raise AttributeError(operation)

        def _disabled(*_args, **_kwargs):
            logger.info(
                "Dograh-hosted service call '{}' blocked (OxeePhone brand)",
                operation,
            )
            raise MPSUnavailableError(operation)

        return _disabled
