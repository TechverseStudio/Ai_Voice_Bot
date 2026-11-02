"""Automated Test Suite for Telephony Integration and Webhook Processing."""

import base64
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


def test_api_exotel_voicebot_endpoint(client):
    """Verify Exotel Voicebot Applet dynamic URL resolution returns wss:// stream endpoint."""
    resp = client.get("/api/telephony/exotel/voicebot-endpoint")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "/ws/telephony/exotel/stream" in data["url"]

    # Also test POST method as Exotel flows can invoke GET or POST
    resp_post = client.post("/api/telephony/exotel/voicebot-endpoint")
    assert resp_post.status_code == 200
    assert "/ws/telephony/exotel/stream" in resp_post.json()["url"]


def test_exotel_initiate_call_payload():
    """Verify Exotel initiate_call constructs valid v1 connect payload with customer From and ExoPhone CallerId."""
    provider = ExotelProvider()
    with patch.dict(os.environ, {
        "EXOTEL_ACCOUNT_SID": "acc_12345",
        "EXOTEL_API_KEY": "key_12345",
        "EXOTEL_API_TOKEN": "token_12345",
        "EXOTEL_CALLER_ID": "08047190000",
        "AGENTSTREAM_PUBLIC_URL": "https://voice.sample.app",
    }):
        req = CallRequest(
            phone_number="9876543210",
            lead_id=42,
            campaign_id=7,
            customer_name="Aditi Rao",
        )
        with patch("httpx.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "Call": {
                    "Sid": "exo_call_99999",
                    "Status": "queued",
                    "DateCreated": "2026-11-01 20:00:00",
                }
            }

            result = provider.initiate_call(req)
            assert result.success is True
            assert result.provider == "exotel"
            assert result.provider_call_id == "exo_call_99999"

            # Check that httpx.post was called with expected Exotel Voice v1 parameters
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["auth"] == ("key_12345", "token_12345")
            form_data = call_kwargs["data"]
            assert form_data["From"] == "09876543210"  # Normalized for Exotel
            assert form_data["CallerId"] == "08047190000"
            assert form_data["CallType"] == "trans"
            assert "https://voice.sample.app/api/telephony/exotel/voicebot-endpoint" in form_data["Url"]


def test_exotel_webhook_basic_auth_verification():
    """Verify Basic Auth signature verification on incoming Exotel webhooks."""
    provider = ExotelProvider()
    import base64
    valid_creds = base64.b64encode(b"test_key:test_token").decode("ascii")

    with patch.dict(os.environ, {
        "EXOTEL_ACCOUNT_SID": "test_sid",
        "EXOTEL_API_KEY": "test_key",
        "EXOTEL_API_TOKEN": "test_token",
    }):
        # Valid Basic Auth
        assert provider.verify_webhook_signature(
            {"authorization": f"Basic {valid_creds}"}, b""
        ) is True

        # Invalid Basic Auth
        invalid_creds = base64.b64encode(b"test_key:wrong_token").decode("ascii")
        assert provider.verify_webhook_signature(
            {"authorization": f"Basic {invalid_creds}"}, b""
        ) is False

        # Custom header token
        assert provider.verify_webhook_signature(
            {"x-exotel-token": "test_token"}, b""
        ) is True


def test_exotel_agentstream_websocket_greeting_and_flow(client):
    """Verify Exotel AgentStream WebSocket handles start, delivers s16le PCM greeting, and completes call."""
    import base64
    call_sid = f"exo_ws_{uuid4().hex[:8]}"

    # Pre-register outbound call record in DB
    save_outbound_call(
        lead_id=None,
        phone_number="+919876543210",
        provider_call_id=call_sid,
        status="initiated",
        provider="exotel",
    )

    # Mock synthesize_bytes to return fast dummy 8kHz s16le audio
    with patch("backend.web.tts.synthesize_bytes") as mock_synth:
        # Return 3200 bytes of s16le PCM (0.2s of audio)
        mock_synth.return_value = b"\x10\x00" * 1600

        with client.websocket_connect("/ws/telephony/exotel/stream") as ws:
            # 1. Send start event matching Exotel AgentStream specification
            ws.send_json({
                "event": "start",
                "stream_sid": "stream_exo_001",
                "start": {
                    "account_sid": "acc_test",
                    "call_sid": call_sid,
                    "stream_sid": "stream_exo_001",
                    "custom_parameters": {
                        "customer_name": "Rohan Deshmukh",
                    },
                    "media_format": {
                        "encoding": "audio/x-raw",
                        "format": "s16le",
                        "sample_rate": 8000,
                        "channels": 1,
                    },
                },
            })

            # 2. Expect at least one media frame containing s16le audio greeting
            received_msg = ws.receive_json()
            assert received_msg["event"] == "media"
            assert received_msg["stream_sid"] == "stream_exo_001"
            assert "payload" in received_msg["media"]
            raw_pcm = base64.b64decode(received_msg["media"]["payload"])
            assert len(raw_pcm) > 0

            # 3. Send stop event
            ws.send_json({
                "event": "stop",
                "stream_sid": "stream_exo_001",
            })

    # Verify call status was updated to completed in DB
    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == call_sid]
    assert len(matched) == 1
    assert matched[0].call_status == "completed"


def test_sarvam_speech_pipeline_buffers():
    """Verify SpeechToText and TextToSpeech work with in-memory buffers."""
    from backend.speech.stt import SpeechToText
    from backend.speech.tts import TextToSpeech
    import numpy as np

    stt = SpeechToText()
    tts = TextToSpeech()

    # Empty buffer handling
    assert stt.transcribe_pcm(b"")["text"] == ""

    # Mock Sarvam client convert and transcribe
    dummy_audio_bytes = np.zeros(1600, dtype=np.int16).tobytes()
    b64_dummy = base64.b64encode(dummy_audio_bytes).decode("ascii")

    with patch.object(tts.client.text_to_speech, "convert") as mock_convert:
        class DummyTTSResp:
            audios = [b64_dummy]
        mock_convert.return_value = DummyTTSResp()

        res_bytes = tts.synthesize_bytes("Hello", language_code="en-IN", sample_rate=8000, codec="linear16")
        assert res_bytes == dummy_audio_bytes

    with patch.object(stt.client.speech_to_text, "transcribe") as mock_transcribe:
        class DummySTTResp:
            transcript = "Looking for 2 BHK"
            language_code = "en-IN"
        mock_transcribe.return_value = DummySTTResp()

        res_dict = stt.transcribe_pcm(dummy_audio_bytes, sample_rate=16000)
        assert res_dict["text"] == "Looking for 2 BHK"
        assert res_dict["language"] == "en-IN"


def test_inbound_exotel_voicebot_dynamic_endpoint(client):
    """Verify Exotel Voicebot dynamic endpoint parses inbound caller query params, creates lead, and returns wss:// URL."""
    exo_sid = f"exo_in_{uuid4().hex[:8]}"
    resp = client.get(
        "/api/telephony/exotel/voicebot-endpoint",
        params={
            "CallSid": exo_sid,
            "From": "9876543210",
            "To": "09513886363",
            "Direction": "incoming",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "/ws/telephony/exotel/stream" in data["url"]
    assert f"call_sid={exo_sid}" in data["url"]
    assert "direction=inbound" in data["url"]

    # Verify call record was created
    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == exo_sid]
    assert len(matched) == 1
    assert matched[0].lead_id > 0


def test_inbound_exotel_passthru_endpoint(client):
    """Verify Exotel Passthru Applet endpoint registers caller before stream."""
    call_sid = f"exo_pass_{uuid4().hex[:8]}"
    resp = client.post(
        "/api/telephony/exotel/passthru",
        data={
            "CallSid": call_sid,
            "From": "9876543222",
            "To": "09513886363",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "OK"

    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == call_sid]
    assert len(matched) == 1


def test_inbound_twilio_voice_webhook(client):
    """Verify Twilio Inbound Voice Webhook returns TwiML with Stream and registers caller."""
    tw_sid = f"CA_in_{uuid4().hex[:8]}"
    resp = client.post(
        "/api/telephony/twilio/inbound",
        data={
            "CallSid": tw_sid,
            "From": "+919876543233",
            "To": "+12025550199",
        },
    )
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert "<Connect>" in resp.text
    assert "<Stream" in resp.text
    assert 'name="direction" value="inbound"' in resp.text

    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == tw_sid]
    assert len(matched) == 1


def test_inbound_call_simulation(client):
    """Verify end-to-end inbound call simulation endpoint."""
    resp = client.post(
        "/api/telephony/inbound/simulate",
        json={
            "caller_phone": "9876543244",
            "customer_speech": "Hello, I want details on 2 BHK flats in Wakad under 75 lakhs.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "Thank you for calling" in data["greeting"]
    assert "call_summary_id" in data
    assert data["lead_id"] > 0


def test_inbound_exotel_agentstream_websocket_greeting(client):
    """Verify Exotel AgentStream delivers an INBOUND greeting ('Thank you for calling') and creates lead."""
    call_sid = f"exo_in_ws_{uuid4().hex[:8]}"

    with patch("backend.web.tts.synthesize_bytes") as mock_synth:
        mock_synth.return_value = b"\x10\x00" * 1600

        with client.websocket_connect(f"/ws/telephony/exotel/stream?call_sid={call_sid}&from=9876543255&direction=inbound") as ws:
            ws.send_json({
                "event": "start",
                "stream_sid": "stream_in_exo_99",
                "start": {
                    "account_sid": "acc_test",
                    "call_sid": call_sid,
                    "stream_sid": "stream_in_exo_99",
                    "direction": "inbound",
                    "from": "+919876543255",
                    "to": "09513886363",
                    "media_format": {
                        "encoding": "audio/x-raw",
                        "format": "s16le",
                        "sample_rate": 8000,
                        "channels": 1,
                    },
                },
            })

            # Check greeting synthesized
            mock_synth.assert_called()
            synthesized_text = mock_synth.call_args.args[0] if mock_synth.call_args.args else mock_synth.call_args.kwargs.get("text", "")
            assert "Thank you for calling" in synthesized_text

            received_msg = ws.receive_json()
            assert received_msg["event"] == "media"

            ws.send_json({
                "event": "stop",
                "stream_sid": "stream_in_exo_99",
            })

    calls = get_outbound_calls()
    matched = [c for c in calls if c.provider_call_id == call_sid]
    assert len(matched) == 1
    assert matched[0].call_status == "completed"

