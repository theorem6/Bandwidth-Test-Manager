#!/usr/bin/env python3
"""Provider-abstracted voice operations — implement per carrier (Bandwidth, Telnyx, Twilio)."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional

from voice_domain import PortOrderStatus, VoiceProvider


class VoiceProviderAdapter(ABC):
    """Boundary for emergency provisioning, porting, and inbound webhooks."""

    @abstractmethod
    def provision_emergency_address(
        self,
        voice_provider_account_external_id: str,
        service_location_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or update carrier emergency address; return provider ids and status."""

    @abstractmethod
    def create_port_order(
        self,
        voice_provider_account_external_id: str,
        order_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit LNP / port-in; return provider order id and initial status."""

    @abstractmethod
    def handle_webhook(
        self,
        provider: VoiceProvider | str,
        raw_body: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Parse signed webhook; return normalized events (port transitions, 911 validation, etc.)."""


class StubVoiceProviderAdapter(VoiceProviderAdapter):
    """No outbound HTTP — for tests and Phase 0 wiring."""

    def provision_emergency_address(
        self,
        voice_provider_account_external_id: str,
        service_location_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "stub": True,
            "voice_provider_account_external_id": voice_provider_account_external_id,
            "provider_address_id": "stub-addr-1",
            "validation_status": "pending",
        }

    def create_port_order(
        self,
        voice_provider_account_external_id: str,
        order_payload: dict[str, Any],
    ) -> dict[str, Any]:
        tns = order_payload.get("telephone_numbers_e164") or []
        return {
            "ok": True,
            "stub": True,
            "voice_provider_account_external_id": voice_provider_account_external_id,
            "provider_order_id": "stub-port-1",
            "status": PortOrderStatus.SUBMITTED.value,
            "telephone_numbers_e164": tns,
        }

    def handle_webhook(
        self,
        provider: VoiceProvider | str,
        raw_body: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        prov = provider.value if isinstance(provider, VoiceProvider) else str(provider)
        parsed: Any
        try:
            parsed = json.loads(raw_body) if raw_body.strip() else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw_body[:2000]}
        return {
            "ok": True,
            "stub": True,
            "provider": prov,
            "parsed": parsed if isinstance(parsed, dict) else {"data": parsed},
            "header_keys": sorted(headers.keys()),
        }


def get_default_adapter() -> VoiceProviderAdapter:
    return StubVoiceProviderAdapter()
