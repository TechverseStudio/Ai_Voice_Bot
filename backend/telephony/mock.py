"""Mock Telephony Provider for safe local automated testing."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.telephony.base import (
    BaseTelephonyProvider,
    CallRequest,
    CallResult,
    CallStatusUpdate,
    validate_phone_number,
)


class MockProvider(BaseTelephonyProvider):
    """Safe mock telephony provider for local evaluation without dialing external phones."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def is_ready(self) -> tuple[bool, str, list[str]]:
        return True, "Mock provider is ready for simulation and automated testing.", []

    def initiate_call(self, request: CallRequest) -> CallResult:
        phone = validate_phone_number(request.phone_number)
        call_id = f"mock-{uuid4()}"
        return CallResult(
            provider_call_id=call_id,
            status="simulated_accepted",
            provider="mock",
            message=f"Mock call accepted for lead #{request.lead_id} at {phone[-4:]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            raw_response={"simulated": True, "lead_id": request.lead_id, "phone": phone},
        )

    def terminate_call(self, provider_call_id: str) -> bool:
        return True

    def verify_webhook_signature(self, headers: dict[str, str], body: bytes) -> bool:
        return True

    def parse_status_callback(self, payload: dict[str, Any]) -> CallStatusUpdate:
        call_id = payload.get("CallSid") or payload.get("provider_call_id", "mock-call")
        status = payload.get("status", "completed")
        return CallStatusUpdate(
            provider_call_id=call_id,
            status=status,
            duration_seconds=int(payload.get("duration", 60)),
            raw_payload=payload,
        )
