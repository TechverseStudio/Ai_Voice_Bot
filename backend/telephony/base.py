"""Base Telephony Provider Abstraction for Outbound AI Phone Calling."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any


@dataclass(frozen=True)
class CallRequest:
    phone_number: str
    lead_id: int | None = None
    campaign_id: int | None = None
    caller_id: str | None = None
    customer_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallResult:
    provider_call_id: str
    status: str
    provider: str
    message: str
    success: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallStatusUpdate:
    provider_call_id: str
    status: str  # queued, initiating, ringing, answered, in_progress, completed, failed, busy, no_answer
    duration_seconds: int = 0
    recording_url: str = ""
    error_message: str = ""
    provider: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)


def validate_phone_number(phone_number: str) -> str:
    """Normalize and validate standard E.164 phone number, handling Indian formats."""
    cleaned = re.sub(r"[^\d+]", "", phone_number or "")
    digits = cleaned.lstrip("+")
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise ValueError(f"Invalid phone number '{phone_number}'. Must contain 8 to 15 digits.")
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return f"+{digits}" if not cleaned.startswith("+") else cleaned


class BaseTelephonyProvider(ABC):
    """Abstract interface for carrier and telephony providers (Exotel, Twilio, Mock)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the telephony provider (e.g., 'exotel', 'twilio', 'mock')."""
        pass

    @abstractmethod
    def is_ready(self) -> tuple[bool, str, list[str]]:
        """Check configuration readiness.

        Returns:
            (ready: bool, message: str, missing_keys: list[str])
        """
        pass

    @abstractmethod
    def initiate_call(self, request: CallRequest) -> CallResult:
        """Initiate an outbound phone call to an actual mobile number."""
        pass

    @abstractmethod
    def terminate_call(self, provider_call_id: str) -> bool:
        """Hang up an active call."""
        pass

    @abstractmethod
    def verify_webhook_signature(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify authenticity of webhook notifications from the provider."""
        pass

    @abstractmethod
    def parse_status_callback(self, payload: dict[str, Any]) -> CallStatusUpdate:
        """Map provider-specific webhook payload into unified CallStatusUpdate."""
        pass
