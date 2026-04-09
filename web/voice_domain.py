#!/usr/bin/env python3
"""
Minimal voice / SIP / UC domain model owned by the application.

Bounded contexts: identity & tenancy, numbers, emergency (E911), porting (LNP).
Do not conflate TelephoneNumber.status with E911 readiness — see state machine notes in schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# --- Enums (state machines) ---


class VoiceProvider(str, Enum):
    """Upstream carrier / CPaaS for VoiceProviderAccount."""

    BANDWIDTH = "bandwidth"
    TELNYX = "telnyx"
    TWILIO = "twilio"


class PortOrderStatus(str, Enum):
    """Port-in / LNP order lifecycle — drives UI, email, NOC queues; sync from webhooks."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING = "pending"
    FOC_CONFIRMED = "foc_confirmed"
    ACTIVATED = "activated"
    FAILED = "failed"


class EmergencyAddressValidationStatus(str, Enum):
    """Carrier or PSAP validation for emergency addressing."""

    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    NEEDS_UPDATE = "needs_update"


class TelephoneNumberStatus(str, Enum):
    """Inventory / assignment — do not use 'ported' here as a proxy for 911 complete."""

    INVENTORY = "inventory"
    ASSIGNED = "assigned"
    SUSPENDED = "suspended"


class GeocodeSource(str, Enum):
    ARCGIS = "arcgis"
    MANUAL = "manual"
    CARRIER_VALIDATED = "carrier_validated"


class CnamProfileStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"


# --- Identity & tenancy ---


@dataclass
class Organization:
    """Tenant boundary (your existing tenant)."""

    id: str
    name: str
    display_name: Optional[str] = None


@dataclass
class VoiceProviderAccount:
    """One row per tenant ↔ carrier billing/API boundary (site, subaccount, etc.)."""

    id: str
    organization_id: str
    provider: VoiceProvider
    external_account_id: str
    display_name: Optional[str] = None
    credential_ref: Optional[str] = None  # KMS / Secret Manager reference — never raw secrets


# --- Numbers & voice endpoints ---


@dataclass
class TelephoneNumber:
    e164: str
    organization_id: str
    status: TelephoneNumberStatus
    voice_provider_account_id: str
    provider_tn_id: Optional[str] = None
    rate_center: Optional[str] = None
    lata: Optional[str] = None


@dataclass
class SipTrunk:
    id: str
    organization_id: str
    voice_provider_account_id: str
    provider_trunk_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class VoiceApplication:
    id: str
    organization_id: str
    voice_provider_account_id: str
    provider_app_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class EndUser:
    id: str
    organization_id: str
    external_subject: Optional[str] = None  # IdP / CRM id


@dataclass
class SubscriberVoiceProfile:
    """Links end-user to default TN, 911 profile, device constraints."""

    id: str
    organization_id: str
    end_user_id: str
    default_telephone_number_e164: Optional[str] = None
    emergency_address_id: Optional[str] = None
    device_constraints_json: Optional[str] = None


# --- E911 ---


@dataclass
class ServiceLocation:
    """Normalized install / service address; geocode for UX and QA — PSAP routing stays carrier-side."""

    id: str
    organization_id: str
    street: str = ""
    unit: Optional[str] = None
    city: str = ""
    state: str = ""
    postal: str = ""
    country: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocode_accuracy_m: Optional[float] = None
    geocode_source: Optional[GeocodeSource] = None
    geocode_locator_name: Optional[str] = None
    geocode_score: Optional[float] = None  # low score → human review before carrier


@dataclass
class EmergencyAddress:
    """Carrier-registered emergency address record."""

    id: str
    organization_id: str
    service_location_id: str
    voice_provider_account_id: str
    provider_address_id: Optional[str] = None
    validation_status: EmergencyAddressValidationStatus = EmergencyAddressValidationStatus.PENDING
    last_verified_at: Optional[datetime] = None


@dataclass
class EmergencyEndpoint:
    """Per device / registration — what the carrier uses for 911 (SIP, AEUI, dynamic, etc.)."""

    id: str
    organization_id: str
    telephone_number_e164: str
    emergency_address_id: str
    voice_provider_account_id: str
    provider_endpoint_id: Optional[str] = None
    pidf_lo_policy_ref: Optional[str] = None


@dataclass
class EmergencyAddressHistory:
    """Append-only audit — regulators and disputes care about history."""

    id: str
    organization_id: str
    emergency_address_id: str
    changed_at: datetime
    changed_by_user_id: Optional[str] = None
    ticket_id: Optional[str] = None
    previous_snapshot: dict[str, Any] = field(default_factory=dict)
    new_snapshot: dict[str, Any] = field(default_factory=dict)


# --- CNAM ---


@dataclass
class CnamProfile:
    """Outbound display — often 1:1 with TelephoneNumber plus optional org default."""

    id: str
    organization_id: str
    telephone_number_e164: Optional[str] = None
    default_name: Optional[str] = None
    presentation_rules: Optional[str] = None
    provider_lidb_order_id: Optional[str] = None
    status: CnamProfileStatus = CnamProfileStatus.PENDING


# --- LNP (porting) ---


@dataclass
class PortOrder:
    """Your order state + carrier references — not full NPAC internals."""

    id: str
    organization_id: str
    status: PortOrderStatus
    telephone_numbers_e164: list[str] = field(default_factory=list)
    losing_carrier_name: Optional[str] = None
    losing_carrier_spid: Optional[str] = None
    foc_target_date: Optional[str] = None
    provider_order_id: Optional[str] = None
    reject_reason_codes: list[str] = field(default_factory=list)


@dataclass
class PortOrderEvent:
    """Webhook / poll events."""

    id: str
    port_order_id: str
    received_at: datetime
    raw_payload_ref: Optional[str] = None
    transition_from: Optional[PortOrderStatus] = None
    transition_to: Optional[PortOrderStatus] = None
    notes: Optional[str] = None


def _enum_values(e: type[Enum]) -> list[str]:
    return [x.value for x in e]


def get_domain_schema() -> dict[str, Any]:
    """JSON-serializable reference for API and UI (no secrets)."""
    return {
        "bounded_contexts": [
            {"id": "identity_tenancy", "label": "Identity & tenancy", "entities": ["Organization", "VoiceProviderAccount"]},
            {"id": "numbers", "label": "Numbers & voice endpoints", "entities": ["TelephoneNumber", "SipTrunk", "VoiceApplication", "EndUser", "SubscriberVoiceProfile"]},
            {"id": "emergency", "label": "E911", "entities": ["ServiceLocation", "EmergencyAddress", "EmergencyEndpoint", "EmergencyAddressHistory"]},
            {"id": "cnam", "label": "CNAM / display", "entities": ["CnamProfile"]},
            {"id": "porting", "label": "LNP (porting)", "entities": ["PortOrder", "PortOrderEvent"]},
        ],
        "entities": {
            "Organization": "Tenant; maps to your existing organization/tenant record.",
            "VoiceProviderAccount": "Provider enum, external account_id, credential_ref (KMS) — one boundary per tenant↔carrier.",
            "TelephoneNumber": "E.164, org, status, voice_provider_account_id, provider TN id, optional rate center/LATA.",
            "SipTrunk": "Optional origination/termination trunk id per tenant.",
            "VoiceApplication": "Optional voice app / connection id per tenant.",
            "EndUser": "Customer user in your IdP/CRM.",
            "SubscriberVoiceProfile": "Links user to default TN, 911 profile, device constraints.",
            "ServiceLocation": "Normalized address + geocode (lat/lon, accuracy, geocode_source).",
            "EmergencyAddress": "Carrier address record; validation_status; links ServiceLocation.",
            "EmergencyEndpoint": "Per registration 911 binding: TN + EmergencyAddress + optional PIDF-LO.",
            "EmergencyAddressHistory": "Append-only audit: who changed address, old→new, ticket id.",
            "CnamProfile": "Outbound CNAM / LIDB order id and status.",
            "PortOrder": "LNP order state machine + losing carrier + FOC + provider order id.",
            "PortOrderEvent": "Webhook events with payload ref and state transition.",
        },
        "state_machines": {
            "PortOrder.status": _enum_values(PortOrderStatus),
            "EmergencyAddress.validation_status": _enum_values(EmergencyAddressValidationStatus),
            "TelephoneNumber.status": _enum_values(TelephoneNumberStatus),
            "notes": [
                "Do not conflate ported/active numbers with E911 complete — block go-live or warn if 911 not provisioned.",
            ],
        },
        "carrier_comparison": [
            {
                "dimension": "Operator / wholesale",
                "bandwidth": "CLEC-style API; sites/subaccounts for tenant isolation.",
                "telnyx": "SIP + numbers + porting; strong for owned SIP infra.",
                "twilio": "CPaaS; Subaccounts standard for SaaS multi-tenant.",
            },
            {
                "dimension": "E911",
                "bandwidth": "Emergency APIs / structured provisioning.",
                "telnyx": "Dynamic E911; SIP headers — SIP-first.",
                "twilio": "Addresses + Emergency resources; familiar CPaaS model.",
            },
            {
                "dimension": "LNP",
                "bandwidth": "Port-in / number moves in numbers operations.",
                "telnyx": "Porting APIs and portability check first-class.",
                "twilio": "Porting APIs; common in tutorials.",
            },
            {
                "dimension": "CNAM / display",
                "bandwidth": "LIDB-style wholesale flows.",
                "telnyx": "Number / messaging profile style — verify current voice CNAM product.",
                "twilio": "Trust Hub / branded calling adjacent — verify current Voice CNAM vs SHAKEN.",
            },
            {
                "dimension": "Multi-tenant",
                "bandwidth": "Sites 1:1 with org (typical reseller).",
                "telnyx": "Often one account + your RBAC; separate orgs for large tenants.",
                "twilio": "Subaccounts per tenant — battle-tested.",
            },
        ],
        "pragmatic_recommendation": (
            "One primary carrier per environment for numbers + 911 + porting; stay provider-abstracted behind "
            "VoiceProviderAccount and adapters. Twilio: fastest subaccount-per-tenant. Bandwidth: wholesale/sites. "
            "Telnyx: SIP trunking + dynamic E911."
        ),
        "arcgis": {
            "uses": [
                "Geocode ServiceLocation → lat/lon; store locator name and score.",
                "QA: flag low match score or wrong parcel before sending to carrier.",
                "Ops/NOC: map open 911 or port issues (internal dashboard).",
                "PSAP boundaries: often rely on carrier-validated address, not self-drawn polygons.",
            ],
            "note": "ArcGIS improves address UX/quality; PSAP routing on the voice path remains carrier/network.",
        },
        "phased_rollout": [
            {"phase": 0, "scope": "Read-only: inventory TNs from carrier; no 911/LNP yet."},
            {"phase": 1, "scope": "E911: ServiceLocation + carrier emergency address/endpoint; block production voice until validated or waiver."},
            {"phase": 2, "scope": "LNP: portability check + port orders + webhooks."},
            {"phase": 3, "scope": "CNAM + polish (notifications, audit exports)."},
        ],
        "first_build_in_code": [
            "VoiceProviderAccount + adapter interface (provision_emergency_address, create_port_order, handle_webhook).",
            "Webhook endpoint with signature verification + idempotency keys.",
            "Tenant admin UI: TN list, 911 column (✓/⚠), port status.",
        ],
        "enums": {
            "VoiceProvider": _enum_values(VoiceProvider),
            "PortOrderStatus": _enum_values(PortOrderStatus),
            "EmergencyAddressValidationStatus": _enum_values(EmergencyAddressValidationStatus),
            "TelephoneNumberStatus": _enum_values(TelephoneNumberStatus),
            "GeocodeSource": _enum_values(GeocodeSource),
            "CnamProfileStatus": _enum_values(CnamProfileStatus),
        },
    }
