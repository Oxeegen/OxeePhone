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
    # OxeePhone release (semver), independent of the Dograh base version in
    # pyproject.toml / package.json. Keep in line with ui/src/brand/brand.ts.
    version: str
    api_description: str
    mcp_server_name: str
    # Cut every call to Dograh-hosted services (Model Proxy Service at
    # services.dograh.com: managed keys, billing, voices catalog, managed SIP,
    # template generation, recording transcription, document processing).
    disable_dograh_services: bool
    # Cut PostHog and Sentry, whatever ENABLE_TELEMETRY / keys say.
    disable_telemetry: bool
    # Model configuration is BYOK pipeline only, every service on the
    # self-hosted OpenAI-compatible provider ("speaches", shown as Local Models).
    local_models_only: bool
    # Persist what the call-detail page needs: recording start marker,
    # per-turn latency breakdown, interruption flag on bot messages.
    call_insights: bool
    # Per-agent start/stop speaking plans (see brand/speaking_plan.py).
    speaking_plan: bool
    # Agent versions page: origin/author of each version, diffs, restore
    # (see brand/versions.py).
    version_history: bool
    # Automatic fixes of analysis findings, tested by text simulation
    # (see brand/fixes.py, brand/simulation.py).
    agent_fixes: bool
    # Browser stays on the page's origin (LAN IP, VPN name…): TURN and
    # recording URLs follow the request when it comes through the OxeePhone
    # proxy; CORS_ALLOWED_ORIGINS also applies in OSS mode (see brand/origin.py).
    same_origin: bool
    # Look for upstream's Cloudflare quick tunnel (service `cloudflared`, profile
    # `tunnel`). Off in the OxeePhone overlay: without that service the lookup
    # waits on DNS for seconds and /health (hence the UI) looks down.
    cloudflared_tunnel: bool


BRAND = BrandConfig(
    product_name="OxeePhone",
    version="0.8.1",
    api_description="API for the OxeePhone voice agent platform",
    mcp_server_name="oxeephone",
    disable_dograh_services=_env_flag("OXEE_DISABLE_DOGRAH_SERVICES", True),
    disable_telemetry=_env_flag("OXEE_DISABLE_TELEMETRY", True),
    local_models_only=_env_flag("OXEE_LOCAL_MODELS_ONLY", True),
    call_insights=_env_flag("OXEE_CALL_INSIGHTS", True),
    speaking_plan=_env_flag("OXEE_SPEAKING_PLAN", True),
    version_history=_env_flag("OXEE_VERSION_HISTORY", True),
    agent_fixes=_env_flag("OXEE_AGENT_FIXES", True),
    same_origin=_env_flag("OXEE_SAME_ORIGIN", True),
    cloudflared_tunnel=_env_flag("OXEE_CLOUDFLARED_TUNNEL", True),
)
