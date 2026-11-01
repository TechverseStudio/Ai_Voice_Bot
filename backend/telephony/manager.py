"""Telephony Manager: Provider Registry & Lifecycle Controller."""

import logging
import os
from typing import Any

from backend.config import TELEPHONY_PROVIDER
from backend.telephony.base import (
    BaseTelephonyProvider,
    CallRequest,
    CallResult,
    CallStatusUpdate,
)
from backend.telephony.exotel import ExotelProvider
from backend.telephony.mock import MockProvider
from backend.telephony.twilio import TwilioProvider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, BaseTelephonyProvider] = {
    "exotel": ExotelProvider(),
    "twilio": TwilioProvider(),
    "mock": MockProvider(),
}


def get_configured_provider_name() -> str:
    """Read TELEPHONY_PROVIDER from environment, defaulting to 'mock'."""
    return os.getenv("TELEPHONY_PROVIDER", TELEPHONY_PROVIDER or "mock").strip().lower()


def get_provider(provider_name: str | None = None) -> BaseTelephonyProvider:
    """Retrieve the selected or default telephony provider."""
    name = (provider_name or get_configured_provider_name()).strip().lower()
    provider = PROVIDERS.get(name)
    if not provider:
        logger.warning(f"Unknown provider '{name}', falling back to mock provider")
        return PROVIDERS["mock"]
    return provider


def get_telephony_status() -> dict[str, Any]:
    """Inspect readiness of the active provider and list alternative adapters."""
    active_name = get_configured_provider_name()
    active_provider = get_provider(active_name)
    ready, message, missing = active_provider.is_ready()

    providers_summary = {}
    for name, prov in PROVIDERS.items():
        is_r, msg, miss = prov.is_ready()
        providers_summary[name] = {"ready": is_r, "message": msg, "missing": miss}

    return {
        "active_provider": active_name,
        "ready": ready,
        "message": message,
        "missing_configuration": missing,
        "mode": "simulation" if active_name == "mock" else "real",
        "supported_providers": providers_summary,
    }


def initiate_outbound_call(request: CallRequest) -> CallResult:
    """Initiate an outbound call via the active telephony provider."""
    provider = get_provider()
    ready, message, _ = provider.is_ready()
    if not ready:
        raise RuntimeError(f"Telephony provider '{provider.provider_name}' is not ready: {message}")
    return provider.initiate_call(request)


def process_webhook(
    provider_name: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    body: bytes,
) -> CallStatusUpdate:
    """Authenticate and parse provider webhook status updates."""
    provider = get_provider(provider_name)
    if not provider.verify_webhook_signature(headers, body):
        raise ValueError(f"Invalid webhook signature for provider '{provider_name}'")
    return provider.parse_status_callback(payload)
