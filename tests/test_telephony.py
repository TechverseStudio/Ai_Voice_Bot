"""Automated Test Suite for Telephony Integration and Webhook Processing."""

import os
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from backend.crm import (
    create_tables,
    create_or_update_lead,
    get_outbound_calls,
    save_outbound_call,
    update_outbound_call_status,
)
from backend.telephony import (
    CallRequest,
    CallResult,
    CallStatusUpdate,
    get_configured_provider_name,
    get_provider,
    get_telephony_status,
    initiate_outbound_call,
    process_webhook,
    validate_phone_number,
)
from backend.telephony.exotel import ExotelProvider
from backend.telephony.mock import MockProvider
from backend.telephony.twilio import TwilioProvider
from backend.web import app


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()


@pytest.fixture
def client():
    return TestClient(app)


def test_phone_number_validation():
    """Verify strict E.164 and Indian mobile number validation."""
    # Valid Indian formats
    assert validate_phone_number("9876543210") == "+919876543210"
    assert validate_phone_number("+919876543210") == "+919876543210"
    assert validate_phone_number("09876543210") == "+919876543210"
    assert validate_phone_number("+91 98765 43210") == "+919876543210"
    assert validate_phone_number("91-9876543210") == "+919876543210"

    # Invalid formats
    with pytest.raises(ValueError, match="Invalid phone number"):
        validate_phone_number("12345")

    with pytest.raises(ValueError, match="Invalid phone number"):
        validate_phone_number("invalid-phone")


def test_mock_provider_lifecycle():
    """Verify mock provider simulation lifecycle."""
    provider = MockProvider()
    ready, msg, missing = provider.is_ready()
    assert ready is True
    assert missing == []

    req = CallRequest(
        phone_number="9876543210",
        customer_name="Vikram Joshi",
        campaign_id=1,
    )
    result = provider.initiate_call(req)
    assert result.success is True
    assert result.provider == "mock"
    assert result.provider_call_id.startswith("mock-")
    assert result.status == "simulated_accepted"


def test_exotel_provider_readiness_and_config():
    """Verify Exotel readiness checks and missing configuration reporting."""
    provider = ExotelProvider()
    with patch.dict(os.environ, {}, clear=True):
        ready, msg, missing = provider.is_ready()
        assert ready is False
        assert "EXOTEL_API_KEY" in missing
        assert "EXOTEL_ACCOUNT_SID" in missing
        assert "EXOTEL_CALLER_ID" in missing

    with patch.dict(os.environ, {
        "EXOTEL_ACCOUNT_SID": "test_sid",
        "EXOTEL_API_KEY": "test_key",
        "EXOTEL_API_TOKEN": "test_token",
        "EXOTEL_CALLER_ID": "08012345678",
    }):
        ready, msg, missing = provider.is_ready()
        assert ready is True
        assert missing == []


def test_twilio_provider_readiness_and_config():
    """Verify Twilio readiness checks and missing configuration reporting."""
    provider = TwilioProvider()
    with patch.dict(os.environ, {}, clear=True):
        ready, msg, missing = provider.is_ready()
        assert ready is False
        assert "TWILIO_ACCOUNT_SID" in missing
        assert "TWILIO_AUTH_TOKEN" in missing
        assert "TWILIO_PHONE_NUMBER" in missing

    with patch.dict(os.environ, {
        "TWILIO_ACCOUNT_SID": "AC_test_sid",
        "TWILIO_AUTH_TOKEN": "test_auth_token",
        "TWILIO_PHONE_NUMBER": "+12025550199",
    }):
        ready, msg, missing = provider.is_ready()
        assert ready is True
        assert missing == []


def test_exotel_status_callback_parsing():
    """Verify Exotel webhook status callback parsing."""
    provider = ExotelProvider()
    payload = {
        "CallSid": "exo_call_12345",
        "Status": "completed",
        "DialCallDuration": "45",
        "RecordingUrl": "https://s3.amazonaws.com/exo_rec_12345.mp3",
    }
    update = provider.parse_status_callback(payload)
    assert update.provider == "exotel"
    assert update.provider_call_id == "exo_call_12345"
    assert update.status == "completed"
    assert update.duration_seconds == 45
    assert update.recording_url == "https://s3.amazonaws.com/exo_rec_12345.mp3"


def test_twilio_status_callback_parsing():
    """Verify Twilio webhook status callback parsing."""
    provider = TwilioProvider()
    payload = {
        "CallSid": "CA_twilio_call_9999",
        "CallStatus": "in-progress",
        "CallDuration": "0",
    }
    update = provider.parse_status_callback(payload)
    assert update.provider == "twilio"
    assert update.provider_call_id == "CA_twilio_call_9999"
    assert update.status == "in_progress"


def test_outbound_call_database_tracking():
    """Verify database persistence and state transitions for outbound calls."""
    lead = create_or_update_lead(
        name="Pooja Sharma",
        phone_number="9876500001",
        area="Wakad",
    )

    call_sid = f"test_sid_{uuid4().hex[:8]}"
    call = save_outbound_call(
        lead_id=lead.id,
        phone_number="+919876500001",
        provider_call_id=call_sid,
        status="initiated",
        provider="exotel",
    )
    assert call.id is not None
    assert call.call_status == "initiated"

    # Update status to answered / in_progress
    updated = update_outbound_call_status(
        provider_call_id=call_sid,
        status="answered",
    )
    assert updated is not None
    assert updated.call_status == "answered"
    assert updated.answered_at is not None

    # Update status to completed
    final = update_outbound_call_status(
        provider_call_id=call_sid,
        status="completed",
        duration_seconds=55,
        recording_url="https://storage.exotel.com/rec001.mp3",
    )
    assert final.call_status == "completed"
    assert final.duration_seconds == 55
    assert final.recording_url == "https://storage.exotel.com/rec001.mp3"
    assert final.ended_at is not None


def test_api_telephony_status_endpoint(client):
    """Verify /api/telephony/status inspects provider readiness."""
    resp = client.get("/api/telephony/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_provider" in data
    assert "supported_providers" in data
    assert "exotel" in data["supported_providers"]
    assert "twilio" in data["supported_providers"]
    assert "mock" in data["supported_providers"]


def test_api_telephony_call_validation_and_dnd(client):
    """Verify /api/telephony/call checks lead existence, phone format, and DND suppression."""
    # Non-existent lead
    resp = client.post("/api/telephony/call", json={"lead_id": 999999})
    assert resp.status_code == 404

    # DND opted out lead
    opt_out_lead = create_or_update_lead(
        name="DND Customer",
        phone_number="9876599999",
        opt_out=True,
    )
    resp = client.post("/api/telephony/call", json={"lead_id": opt_out_lead.id})
    assert resp.status_code == 409
    assert "Do Not Call" in resp.json()["detail"]


def test_api_telephony_exotel_webhook(client):
    """Verify Exotel webhook status callback endpoint updates call records."""
    exo_sid = f"exo_web_{uuid4().hex[:8]}"
    call = save_outbound_call(
        lead_id=None,
        phone_number="+919876543211",
        provider_call_id=exo_sid,
        status="ringing",
        provider="exotel",
    )

    resp = client.post(
        "/api/telephony/webhook/exotel/status",
        data={
            "CallSid": exo_sid,
            "Status": "completed",
            "DialCallDuration": "60",
            "RecordingUrl": "https://rec.exotel.com/123.mp3",
        },
    )
    assert resp.status_code == 200

    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == exo_sid]
    assert len(matched) == 1
    assert matched[0].call_status == "completed"
    assert matched[0].duration_seconds == 60


def test_api_telephony_twilio_webhook(client):
    """Verify Twilio webhook status callback endpoint updates call records."""
    twilio_sid = f"CA_web_{uuid4().hex[:8]}"
    call = save_outbound_call(
        lead_id=None,
        phone_number="+919876543212",
        provider_call_id=twilio_sid,
        status="initiated",
        provider="twilio",
    )

    resp = client.post(
        "/api/telephony/webhook/twilio/status",
        data={
            "CallSid": twilio_sid,
            "CallStatus": "completed",
            "CallDuration": "82",
        },
    )
    assert resp.status_code == 200

    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == twilio_sid]
    assert len(matched) == 1
    assert matched[0].call_status == "completed"
    assert matched[0].duration_seconds == 82
