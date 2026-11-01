"""Provider-neutral outbound call boundary backed by backend.telephony."""

from backend.telephony import (
    CallRequest,
    CallResult,
    get_telephony_status,
    initiate_outbound_call,
    validate_phone_number,
)


def provider_status() -> dict:
    """Check readiness of the configured provider."""
    status = get_telephony_status()
    return {
        "provider": status["active_provider"],
        "mode": status["mode"],
        "ready": status["ready"],
        "message": status["message"],
        "missing_configuration": status.get("missing_configuration", []),
        "supported_providers": status.get("supported_providers", {}),
    }


def initiate_call(request: CallRequest) -> CallResult:
    """Initiate an outbound call through the active telephony provider."""
    return initiate_outbound_call(request)
