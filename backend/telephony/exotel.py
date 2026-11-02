"""Exotel Telephony Provider for Outbound AI Phone Calling in India."""

import base64
import json
import logging
import os
import re
from typing import Any
import httpx

from backend.config import (
    AGENTSTREAM_PUBLIC_URL,
    EXOTEL_ACCOUNT_SID,
    EXOTEL_API_TOKEN,
    EXOTEL_BASE_URL,
    EXOTEL_CALLER_ID,
)
from backend.telephony.base import (
    BaseTelephonyProvider,
    CallRequest,
    CallResult,
    CallStatusUpdate,
    validate_phone_number,
)

logger = logging.getLogger(__name__)

EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY", "") or EXOTEL_ACCOUNT_SID
EXOTEL_APPLET_ID = os.getenv("EXOTEL_APPLET_ID", "")
EXOTEL_STATUS_CALLBACK_URL = os.getenv("EXOTEL_STATUS_CALLBACK_URL", "")


class ExotelProvider(BaseTelephonyProvider):
    """Production-ready Exotel integration for Indian telecom calling."""

    @property
    def provider_name(self) -> str:
        return "exotel"

    def is_ready(self) -> tuple[bool, str, list[str]]:
        missing = []
        account_sid = os.environ.get("EXOTEL_ACCOUNT_SID", "").strip()
        api_token = os.environ.get("EXOTEL_API_TOKEN", "").strip()
        caller_id = os.environ.get("EXOTEL_CALLER_ID", "").strip()
        api_key = (os.environ.get("EXOTEL_API_KEY", "") or account_sid).strip()

        if not account_sid:
            missing.append("EXOTEL_ACCOUNT_SID")
        if not api_key:
            missing.append("EXOTEL_API_KEY")
        if not api_token:
            missing.append("EXOTEL_API_TOKEN")
        if not caller_id:
            missing.append("EXOTEL_CALLER_ID")

        base_url = os.environ.get("EXOTEL_BASE_URL", "").strip() or "https://api.exotel.com"

        if missing:
            return (
                False,
                f"Exotel configuration missing required credentials: {', '.join(missing)}",
                missing,
            )
        return True, f"Exotel provider configured (Base URL: {base_url}, Caller ID: {caller_id})", []

    def _normalize_for_exotel(self, phone: str) -> str:
        """Format phone number for Exotel (e.g. 10-digit Indian number or 0XXXXXXXXXX)."""
        cleaned = re.sub(r"[^\d]", "", phone)
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = "0" + cleaned[2:]
        elif len(cleaned) == 10:
            cleaned = "0" + cleaned
        return cleaned

    def initiate_call(self, request: CallRequest) -> CallResult:
        ready, message, missing = self.is_ready()
        if not ready:
            raise RuntimeError(message)

        phone = self._normalize_for_exotel(request.phone_number)
        account_sid = os.getenv("EXOTEL_ACCOUNT_SID") or EXOTEL_ACCOUNT_SID
        api_token = os.getenv("EXOTEL_API_TOKEN") or EXOTEL_API_TOKEN
        caller_id = request.caller_id or os.getenv("EXOTEL_CALLER_ID") or EXOTEL_CALLER_ID
        base_url = (os.getenv("EXOTEL_BASE_URL") or EXOTEL_BASE_URL or "https://api.exotel.com").rstrip("/")
        api_url = f"{base_url}/v1/Accounts/{account_sid}/Calls/connect.json"

        # Determine Flow URL / Voicebot Endpoint
        agent_url = os.getenv("AGENTSTREAM_PUBLIC_URL") or AGENTSTREAM_PUBLIC_URL or os.getenv("PUBLIC_BASE_URL") or ""
        applet_id = os.getenv("EXOTEL_APPLET_ID") or EXOTEL_APPLET_ID

        flow_url = ""
        if agent_url:
            flow_url = f"{agent_url.rstrip('/')}/api/telephony/exotel/voicebot-endpoint"
        elif applet_id:
            flow_url = f"https://my.exotel.com/{account_sid}/exoml/start_voice/{applet_id}"
        else:
            flow_url = f"{base_url}/v1/Accounts/{account_sid}/default_flow"

        status_callback = os.getenv("EXOTEL_STATUS_CALLBACK_URL") or EXOTEL_STATUS_CALLBACK_URL or ""
        if not status_callback and agent_url:
            status_callback = f"{agent_url.rstrip('/')}/api/telephony/webhook/exotel/status"

        custom_payload = {
            "lead_id": request.lead_id,
            "campaign_id": request.campaign_id,
            "customer_name": request.customer_name,
            "metadata": request.metadata,
        }

        # Exotel Voice v1: When connecting customer to an automated URL flow:
        # 'From' is the customer destination phone number, and 'CallerId' is your virtual ExoPhone.
        form_data = {
            "From": phone,
            "CallerId": caller_id,
            "Url": flow_url,
            "CallType": "trans",
            "CustomField": json.dumps(custom_payload),
        }

        if status_callback:
            form_data["StatusCallback"] = status_callback

        api_key = os.getenv("EXOTEL_API_KEY") or EXOTEL_API_KEY or account_sid

        try:
            logger.info(f"Initiating Exotel call to {phone} from CallerId {caller_id} (Account: {account_sid})")
            response = httpx.post(
                api_url,
                data=form_data,
                auth=(api_key, api_token),
                timeout=15.0,
            )

            if response.status_code not in (200, 201):
                err_msg = f"Exotel API error (HTTP {response.status_code}): {response.text}"
                logger.error(err_msg)
                raise RuntimeError(err_msg)

            data = response.json()
            call_obj = data.get("Call", {})
            call_sid = call_obj.get("Sid") or f"exotel-{call_obj.get('DateCreated', '')}"
            call_status = call_obj.get("Status", "queued")

            return CallResult(
                provider_call_id=call_sid,
                status=call_status,
                provider="exotel",
                message=f"Exotel call initiated successfully (SID: {call_sid}, Status: {call_status})",
                raw_response=data,
            )

        except httpx.RequestError as e:
            err_msg = f"Network failure communicating with Exotel API: {str(e)}"
            logger.error(err_msg)
            raise RuntimeError(err_msg) from e

    def terminate_call(self, provider_call_id: str) -> bool:
        if not provider_call_id:
            return False
        account_sid = os.getenv("EXOTEL_ACCOUNT_SID") or EXOTEL_ACCOUNT_SID
        api_token = os.getenv("EXOTEL_API_TOKEN") or EXOTEL_API_TOKEN
        api_key = os.getenv("EXOTEL_API_KEY") or EXOTEL_API_KEY or account_sid
        base_url = (os.getenv("EXOTEL_BASE_URL") or EXOTEL_BASE_URL or "https://api.exotel.com").rstrip("/")
        api_url = f"{base_url}/v1/Accounts/{account_sid}/Calls/{provider_call_id}.json"

        try:
            resp = httpx.post(api_url, data={"Status": "completed"}, auth=(api_key, api_token), timeout=10.0)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Failed to hang up Exotel call {provider_call_id}: {e}")
            return False

    def verify_webhook_signature(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify authenticity of webhook notifications from Exotel (Basic Auth or Token header)."""
        auth_header = headers.get("authorization", "") or headers.get("Authorization", "")
        account_sid = os.getenv("EXOTEL_ACCOUNT_SID") or EXOTEL_ACCOUNT_SID
        api_token = os.getenv("EXOTEL_API_TOKEN") or EXOTEL_API_TOKEN
        api_key = os.getenv("EXOTEL_API_KEY") or EXOTEL_API_KEY or account_sid

        # If no credentials configured yet, allow for testing
        if not api_token:
            return True

        if auth_header.startswith("Basic "):
            try:
                encoded = auth_header.split(" ", 1)[1].strip()
                decoded = base64.b64decode(encoded).decode("utf-8")
                user, pwd = decoded.split(":", 1)
                return (user in (api_key, account_sid)) and (pwd == api_token)
            except Exception:
                return False

        # Exotel custom token or pass-through
        custom_token = headers.get("x-exotel-token", "") or headers.get("x-api-token", "")
        if custom_token:
            return custom_token == api_token

        return True

    def parse_status_callback(self, payload: dict[str, Any]) -> CallStatusUpdate:
        call_sid = payload.get("CallSid") or payload.get("Sid", "")
        raw_status = (payload.get("Status") or payload.get("CallStatus") or "").lower()

        # Map Exotel statuses
        status_map = {
            "queued": "queued",
            "initiated": "initiating",
            "ringing": "ringing",
            "in-progress": "in_progress",
            "in_progress": "in_progress",
            "completed": "completed",
            "busy": "busy",
            "no-answer": "no_answer",
            "failed": "failed",
            "canceled": "failed",
        }
        unified_status = status_map.get(raw_status, "in_progress" if "progress" in raw_status else raw_status)

        duration = int(payload.get("DialCallDuration") or payload.get("Duration") or payload.get("CallDuration") or 0)
        recording_url = payload.get("RecordingUrl", "")

        return CallStatusUpdate(
            provider_call_id=call_sid,
            status=unified_status,
            duration_seconds=duration,
            recording_url=recording_url,
            provider="exotel",
            raw_payload=payload,
        )

