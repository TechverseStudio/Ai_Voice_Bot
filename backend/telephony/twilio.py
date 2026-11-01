"""Twilio Telephony Provider with Bidirectional WebSocket Media Streams."""

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any
import httpx

from backend.telephony.base import (
    BaseTelephonyProvider,
    CallRequest,
    CallResult,
    CallStatusUpdate,
    validate_phone_number,
)

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "") or os.getenv("TWILIO_CALLER_ID", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "") or os.getenv("AGENTSTREAM_PUBLIC_URL", "")


class TwilioProvider(BaseTelephonyProvider):
    """Twilio provider supporting bidirectional media streams for low-latency AI conversations."""

    @property
    def provider_name(self) -> str:
        return "twilio"

    def is_ready(self) -> tuple[bool, str, list[str]]:
        missing = []
        account_sid = os.getenv("TWILIO_ACCOUNT_SID") or TWILIO_ACCOUNT_SID
        auth_token = os.getenv("TWILIO_AUTH_TOKEN") or TWILIO_AUTH_TOKEN
        phone_number = os.getenv("TWILIO_PHONE_NUMBER") or os.getenv("TWILIO_CALLER_ID") or TWILIO_PHONE_NUMBER

        if not account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not phone_number:
            missing.append("TWILIO_PHONE_NUMBER")

        if missing:
            return (
                False,
                f"Twilio configuration missing required credentials: {', '.join(missing)}",
                missing,
            )
        return True, f"Twilio provider configured (Caller ID: {phone_number})", []

    def initiate_call(self, request: CallRequest) -> CallResult:
        ready, message, missing = self.is_ready()
        if not ready:
            raise RuntimeError(message)

        phone = validate_phone_number(request.phone_number)
        account_sid = os.getenv("TWILIO_ACCOUNT_SID") or TWILIO_ACCOUNT_SID
        auth_token = os.getenv("TWILIO_AUTH_TOKEN") or TWILIO_AUTH_TOKEN
        caller_id = request.caller_id or os.getenv("TWILIO_PHONE_NUMBER") or os.getenv("TWILIO_CALLER_ID") or TWILIO_PHONE_NUMBER
        public_base = os.getenv("PUBLIC_BASE_URL") or os.getenv("AGENTSTREAM_PUBLIC_URL") or PUBLIC_BASE_URL
        api_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"

        # Construct public WebSocket stream URL for bidirectional audio
        public_host = public_base.replace("https://", "").replace("http://", "").rstrip("/")
        ws_url = f"wss://{public_host}/ws/telephony/stream" if public_host else ""

        # TwiML payload: bridges telephone audio into our WebSocket streaming endpoint
        if ws_url:
            twiml = (
                f'<Response>'
                f'<Connect>'
                f'<Stream url="{ws_url}">'
                f'<Parameter name="lead_id" value="{request.lead_id}"/>'
                f'<Parameter name="campaign_id" value="{request.campaign_id or 0}"/>'
                f'<Parameter name="customer_name" value="{request.customer_name}"/>'
                f'</Stream>'
                f'</Connect>'
                f'</Response>'
            )
        else:
            twiml = (
                f'<Response>'
                f'<Say voice="alice">Hello {request.customer_name}, please hold while we connect you to Krishna Property AI assistant.</Say>'
                f'</Response>'
            )

        form_data = {
            "To": phone,
            "From": caller_id,
            "Twiml": twiml,
        }

        if public_base:
            form_data["StatusCallback"] = f"{public_base.rstrip('/')}/api/telephony/webhook/twilio/status"
            form_data["StatusCallbackEvent"] = ["initiated", "ringing", "answered", "completed"]

        try:
            logger.info(f"Initiating Twilio call from {caller_id} to {phone}")
            response = httpx.post(
                api_url,
                data=form_data,
                auth=(account_sid, auth_token),
                timeout=15.0,
            )

            if response.status_code not in (200, 201):
                err_msg = f"Twilio API error (HTTP {response.status_code}): {response.text}"
                logger.error(err_msg)
                raise RuntimeError(err_msg)

            data = response.json()
            call_sid = data.get("sid", "")
            call_status = data.get("status", "queued")

            return CallResult(
                provider_call_id=call_sid,
                status=call_status,
                provider="twilio",
                message=f"Twilio call initiated successfully (SID: {call_sid}, Status: {call_status})",
                raw_response=data,
            )

        except httpx.RequestError as e:
            err_msg = f"Network failure communicating with Twilio API: {str(e)}"
            logger.error(err_msg)
            raise RuntimeError(err_msg) from e

    def terminate_call(self, provider_call_id: str) -> bool:
        if not provider_call_id:
            return False
        api_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls/{provider_call_id}.json"
        try:
            resp = httpx.post(api_url, data={"Status": "completed"}, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=10.0)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Failed to hang up Twilio call {provider_call_id}: {e}")
            return False

    def verify_webhook_signature(self, headers: dict[str, str], body: bytes) -> bool:
        signature = headers.get("x-twilio-signature", "") or headers.get("X-Twilio-Signature", "")
        if not signature or not TWILIO_AUTH_TOKEN:
            return True
        return True

    def parse_status_callback(self, payload: dict[str, Any]) -> CallStatusUpdate:
        call_sid = payload.get("CallSid") or payload.get("sid", "")
        raw_status = (payload.get("CallStatus") or payload.get("Status") or "").lower()

        status_map = {
            "queued": "queued",
            "initiated": "initiating",
            "ringing": "ringing",
            "in-progress": "in_progress",
            "completed": "completed",
            "busy": "busy",
            "no-answer": "no_answer",
            "failed": "failed",
            "canceled": "failed",
        }
        unified_status = status_map.get(raw_status, raw_status)
        duration = int(payload.get("CallDuration") or payload.get("Duration") or 0)
        recording_url = payload.get("RecordingUrl", "")

        return CallStatusUpdate(
            provider_call_id=call_sid,
            status=unified_status,
            duration_seconds=duration,
            recording_url=recording_url,
            provider="twilio",
            raw_payload=payload,
        )
