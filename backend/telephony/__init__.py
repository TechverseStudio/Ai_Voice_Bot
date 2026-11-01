"""Telephony integration package for AI Autonomous Outbound Calling."""

from backend.telephony.base import (
    BaseTelephonyProvider,
    CallRequest,
    CallResult,
    CallStatusUpdate,
    validate_phone_number,
)
from backend.telephony.manager import (
    get_configured_provider_name,
    get_provider,
    get_telephony_status,
    initiate_outbound_call,
    process_webhook,
)

__all__ = [
    "BaseTelephonyProvider",
    "CallRequest",
    "CallResult",
    "CallStatusUpdate",
    "validate_phone_number",
    "get_configured_provider_name",
    "get_provider",
    "get_telephony_status",
    "initiate_outbound_call",
    "process_webhook",
]
