"""Unit and integration test suite for Inbound Calls in AI Voice Real Estate Agent."""

import json
from unittest.mock import patch
from uuid import uuid4
import pytest
from starlette.requests import Request

from backend.agent.conversation_manager import ConversationManager, ConversationSession
from backend.crm import (
    create_tables,
    create_or_update_lead,
    get_lead_by_phone,
    get_outbound_calls,
    update_outbound_call_status,
)
from backend.web import (
    exotel_passthru_endpoint,
    exotel_voicebot_endpoint,
    simulate_inbound_call,
    SimulateInboundCallRequest,
    twilio_inbound_voice,
)


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()


def test_inbound_greeting_generation_multilingual():
    """Verify that inbound opening greetings are polite, welcoming, and acknowledge incoming caller."""
    mgr = ConversationManager()

    # English Inbound
    sess_en = ConversationSession("sess_en", lead_id=1, customer_name="Rohan", language="en-IN")
    greeting_en = mgr.generate_opening_greeting(sess_en, is_inbound=True)
    assert "Thank you for calling" in greeting_en
    assert "Priya" in greeting_en
    assert "Hinjawadi" in greeting_en

    # Hindi Inbound
    sess_hi = ConversationSession("sess_hi", lead_id=2, customer_name="Rohit", language="hi-IN")
    greeting_hi = mgr.generate_opening_greeting(sess_hi, is_inbound=True)
    assert "में कॉल करने के लिए धन्यवाद" in greeting_hi

    # Marathi Inbound
    sess_mr = ConversationSession("sess_mr", lead_id=3, customer_name="Sneha", language="mr-IN")
    greeting_mr = mgr.generate_opening_greeting(sess_mr, is_inbound=True)
    assert "कॉल केल्याबद्दल धन्यवाद" in greeting_mr


def test_get_lead_by_phone_with_prefix_variations():
    """Verify get_lead_by_phone matches exact, 10-digit, 0-prefix, and +91-prefix."""
    lead = create_or_update_lead(
        name="Amol Kulkarni",
        phone_number="+919822012345",
        area="Wakad",
    )

    # Match by exact phone
    assert get_lead_by_phone("+919822012345") is not None
    assert get_lead_by_phone("+919822012345").id == lead.id

    # Match by 10 digits
    assert get_lead_by_phone("9822012345") is not None
    assert get_lead_by_phone("9822012345").name == "Amol Kulkarni"

    # Match by 0-prefixed 11 digits
    assert get_lead_by_phone("09822012345") is not None
    assert get_lead_by_phone("09822012345").id == lead.id


def test_inbound_untracked_call_status_update():
    """Verify update_outbound_call_status auto-creates record for external/inbound calls."""
    call_sid = f"exo_ext_{uuid4().hex[:8]}"
    updated = update_outbound_call_status(
        provider_call_id=call_sid,
        status="completed",
        duration_seconds=42,
        recording_url="https://rec.exotel.com/rec.mp3",
    )
    assert updated is not None
    assert updated.call_status == "completed"
    assert updated.duration_seconds == 42
    assert updated.recording_url == "https://rec.exotel.com/rec.mp3"


def test_exotel_voicebot_dynamic_endpoint_inbound_resolution():
    """Verify Exotel Voicebot dynamic URL resolution handles inbound calls and creates lead."""
    import asyncio
    call_sid = f"exo_in_{uuid4().hex[:8]}"
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/telephony/exotel/voicebot-endpoint",
        "query_string": f"CallSid={call_sid}&From=9822099999&To=09513886363&Direction=incoming".encode("ascii"),
        "headers": [(b"host", b"testserver")],
    }
    req = Request(scope)
    res = asyncio.run(exotel_voicebot_endpoint(req))
    assert "url" in res
    assert "/ws/telephony/exotel/stream" in res["url"]
    assert f"call_sid={call_sid}" in res["url"]
    assert "direction=inbound" in res["url"]

    # Verify inbound call was pre-registered in DB
    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == call_sid]
    assert len(matched) == 1
    assert matched[0].phone_number == "+919822099999"

    # Verify lead was auto-created in CRM
    lead = get_lead_by_phone("9822099999")
    assert lead is not None
    assert "Inbound Caller" in lead.name


def test_exotel_passthru_endpoint_registers_caller():
    """Verify Exotel Passthru Applet endpoint registers caller before stream."""
    import asyncio
    call_sid = f"exo_pass_{uuid4().hex[:8]}"
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/telephony/exotel/passthru",
        "query_string": f"CallSid={call_sid}&From=9822088888&To=09513886363".encode("ascii"),
        "headers": [(b"host", b"testserver")],
    }
    req = Request(scope)
    res = asyncio.run(exotel_passthru_endpoint(req))
    assert res.status_code == 200
    assert res.body == b"OK"

    lead = get_lead_by_phone("9822088888")
    assert lead is not None


def test_twilio_inbound_voice_twiml_generation():
    """Verify Twilio Inbound Voice Webhook returns TwiML with WebSocket stream instruction."""
    import asyncio
    tw_sid = f"CA_in_{uuid4().hex[:8]}"
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/telephony/twilio/inbound",
        "query_string": f"CallSid={tw_sid}&From=%2B919822077777&To=%2B12025550199".encode("ascii"),
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/x-www-form-urlencoded")],
    }
    req = Request(scope)
    res = asyncio.run(twilio_inbound_voice(req))
    assert res.status_code == 200
    assert "application/xml" in res.headers["content-type"]
    body_text = res.body.decode("utf-8")
    assert "<Connect>" in body_text
    assert "<Stream" in body_text
    assert 'name="direction" value="inbound"' in body_text
    assert 'name="caller" value="+919822077777"' in body_text

    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == tw_sid]
    assert len(matched) == 1
    assert matched[0].provider == "twilio"


def test_simulate_inbound_call_pipeline():
    """Verify simulate_inbound_call runs complete pipeline: greeting, speech processing, lead scoring, and call summary."""
    with patch("backend.agent.conversation_manager.ConversationManager.process_turn") as mock_turn:
        mock_turn.return_value = (
            "We have premium 2 BHK flats in Wakad starting from 75 Lakhs. Would you like to schedule a site visit?",
            "inquiry",
            {"bhk": "2 BHK", "locality": "Wakad"},
        )

        res = simulate_inbound_call(SimulateInboundCallRequest(
            caller_phone="9822066666",
            customer_name="Sanjay Patil",
            customer_speech="I want a 2 BHK in Wakad.",
            language="en-IN",
        ))

        assert res["status"] == "completed"
        assert "Thank you for calling" in res["greeting"]
        assert "75 Lakhs" in res["agent_reply"]
        assert res["lead_name"] == "Sanjay Patil"
        assert res["call_summary_id"] > 0

        # Check call summary saved
        lead = get_lead_by_phone("9822066666")
        assert lead is not None
        assert lead.name == "Sanjay Patil"
