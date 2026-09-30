"""OxeePhone brand gates: Dograh-hosted services and telemetry are cut.

These tests force the brand flags on explicitly, so they hold whatever the
OXEE_* environment of the test run is (upstream tests run with them off).
"""

import dataclasses

import pytest

from api.brand import BRAND
from api.brand.mps import DisabledMPSClient
from api.errors.mps import MPSUnavailableError

BRANDED = dataclasses.replace(
    BRAND, disable_dograh_services=True, disable_telemetry=True
)


def test_disabled_mps_client_blocks_every_operation():
    client = DisabledMPSClient()

    with pytest.raises(MPSUnavailableError) as exc:
        client.create_service_key(name="x")
    assert exc.value.operation == "create_service_key"

    # Sync call sites (validate_service_key) fail the same way.
    with pytest.raises(MPSUnavailableError):
        client.validate_service_key("key")


def test_disabled_mps_client_keeps_dunder_protocol_intact():
    client = DisabledMPSClient()
    assert not hasattr(client, "__aenter__")
    assert client.base_url == ""


async def test_bootstrap_is_a_noop_when_dograh_services_are_cut(monkeypatch):
    from api.services import organization_bootstrap

    monkeypatch.setattr(organization_bootstrap, "BRAND", BRANDED)

    async def _fail(*_args, **_kwargs):
        raise AssertionError("bootstrap must not touch the database or MPS")

    monkeypatch.setattr(organization_bootstrap, "_is_bootstrap_complete", _fail)
    monkeypatch.setattr(
        organization_bootstrap, "get_organization_ai_model_configuration_v2", _fail
    )

    assert (
        await organization_bootstrap.ensure_organization_bootstrapped(
            42, created_by="user"
        )
        is True
    )


def test_posthog_is_never_initialised_when_telemetry_is_cut(monkeypatch):
    from api.services import posthog_client

    monkeypatch.setattr(posthog_client, "BRAND", BRANDED)
    monkeypatch.setattr(posthog_client, "POSTHOG_API_KEY", "phc_test")
    monkeypatch.setattr(posthog_client, "_posthog_client", None)

    assert posthog_client.get_posthog() is None
    # Helpers stay silent no-ops.
    posthog_client.capture_event("user", "event")
