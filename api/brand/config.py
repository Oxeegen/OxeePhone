"""Brand configuration for OxeePhone.

Flags default to the OxeePhone behaviour and can be flipped per deployment via
environment variables (useful for debugging against upstream behaviour).
"""

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BrandConfig:
    product_name: str
    api_description: str
    mcp_server_name: str
    # Cut every call to Dograh-hosted services (Model Proxy Service at
    # services.dograh.com: managed keys, billing, voices catalog, managed SIP,
    # template generation, recording transcription, document processing).
    disable_dograh_services: bool
    # Cut PostHog and Sentry, whatever ENABLE_TELEMETRY / keys say.
    disable_telemetry: bool


BRAND = BrandConfig(
    product_name="OxeePhone",
    api_description="API for the OxeePhone voice agent platform",
    mcp_server_name="oxeephone",
    disable_dograh_services=_env_flag("OXEE_DISABLE_DOGRAH_SERVICES", True),
    disable_telemetry=_env_flag("OXEE_DISABLE_TELEMETRY", True),
)
