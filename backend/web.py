
import asyncio
import audioop
import base64
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4
import wave

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
import numpy as np
from pydantic import BaseModel

from backend.telephony import (
    CallRequest,
    CallResult,
    get_provider,
    get_telephony_status,
    initiate_outbound_call,
    process_webhook,
    validate_phone_number,
)
from backend.crm import (
    update_outbound_call_status,
    get_outbound_calls,
    save_outbound_call,
)

logger = logging.getLogger(__name__)


def _resample_pcm_8k_to_16k(pcm_8k: bytes) -> bytes:
    """Upsample 8kHz 16-bit linear PCM (Exotel/telephony) to 16kHz for Sarvam Saaras STT."""
    if not pcm_8k:
        return b""
    try:
        samples = np.frombuffer(pcm_8k, dtype=np.int16)
        return np.repeat(samples, 2).tobytes()
    except Exception:
        try:
            return audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)[0]
        except Exception:
            return pcm_8k


def _resample_pcm_16k_to_8k(pcm_16k: bytes) -> bytes:
    """Downsample 16kHz 16-bit linear PCM to 8kHz for Exotel telephony stream."""
    if not pcm_16k:
        return b""
    try:
        samples = np.frombuffer(pcm_16k, dtype=np.int16)
        return samples[::2].tobytes()
    except Exception:
        try:
            return audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
        except Exception:
            return pcm_16k


def _calculate_pcm_rms(pcm_bytes: bytes) -> float:
    """Calculate RMS energy of 16-bit linear PCM chunk for voice activity detection."""
    if not pcm_bytes:
        return 0.0
    try:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    except Exception:
        return 0.0


def _wav_to_mulaw_payload(wav_bytes: bytes) -> str:
    """Convert WAV audio bytes (16-bit PCM) into 8kHz mulaw base64 for Twilio streaming."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            framerate = wf.getframerate()
            sampwidth = wf.getsampwidth()
            channels = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())

        # Convert to mono if needed
        if channels > 1:
            frames = audioop.tomono(frames, sampwidth, 1, 1)

        # Resample to 8kHz if needed
        if framerate != 8000:
            frames, _ = audioop.ratecv(frames, sampwidth, 1, framerate, 8000, None)

        # Convert 16-bit PCM to 8-bit mulaw
        mulaw = audioop.lin2ulaw(frames, sampwidth)
        return base64.b64encode(mulaw).decode("ascii")
    except Exception as e:
        logger.warning(f"Audio conversion to mulaw failed: {e}")
        return ""


def _mulaw_to_pcm16k(mulaw_bytes: bytes) -> bytes:
    """Convert 8kHz mulaw audio bytes from telephony stream into 16kHz linear PCM for Sarvam STT."""
    try:
        pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
        return _resample_pcm_8k_to_16k(pcm_8k)
    except Exception as e:
        logger.warning(f"Mulaw to PCM conversion failed: {e}")
        return b""


async def _synthesize_audio(text: str, language: str = "en-IN") -> bytes:
    """Synthesize text to audio using Sarvam Bulbul TTS (in-memory)."""
    def run_synth() -> bytes:
        try:
            return tts.synthesize_bytes(text, language_code=language, sample_rate=16000, codec="wav")
        except Exception as e:
            logger.warning(f"TTS synthesis exception: {e}")
            return b""
    return await asyncio.to_thread(run_synth)


async def _synthesize_audio_pcm(text: str, language: str = "en-IN", sample_rate: int = 8000) -> bytes:
    """Synthesize text to raw 16-bit linear PCM bytes (s16le) for Exotel using Sarvam Bulbul."""
    def run_synth() -> bytes:
        try:
            return tts.synthesize_bytes(text, language_code=language, sample_rate=sample_rate, codec="linear16")
        except Exception as e:
            logger.warning(f"TTS linear16 synthesis error: {e}")
            return b""
    return await asyncio.to_thread(run_synth)


async def _synthesize_audio_mulaw(text: str, language: str = "en-IN") -> str:
    """Synthesize text to 8kHz mulaw base64 payload for Twilio using Sarvam Bulbul."""
    def run_synth() -> str:
        try:
            mulaw_bytes = tts.synthesize_bytes(text, language_code=language, sample_rate=8000, codec="mulaw")
            if mulaw_bytes:
                return base64.b64encode(mulaw_bytes).decode("ascii")
            return ""
        except Exception as e:
            logger.warning(f"TTS mulaw synthesis error: {e}")
            return ""
    return await asyncio.to_thread(run_synth)


async def _transcribe_pcm(pcm_16k: bytes, language: str = "unknown") -> tuple[str, str]:
    """Transcribe 16kHz linear PCM buffer using Sarvam Saaras STT (in-memory)."""
    def run_stt() -> tuple[str, str]:
        try:
            res = stt.transcribe_pcm(pcm_16k, sample_rate=16000, language_code=language)
            return res.get("text", ""), res.get("language", language)
        except Exception as e:
            logger.warning(f"STT transcribe exception: {e}")
            return "", language
    return await asyncio.to_thread(run_stt)


"""FastAPI application for AI Autonomous Lead Generation Engine."""

import asyncio
import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from backend.analysis import analyze_conversation
from backend.agent.conversation_manager import ConversationManager
from backend.campaign_engine import CampaignEngine
from backend.config import SARVAM_API_KEY
from backend.crm import (
    KnowledgeBase,
    create_tables,
    create_import_batch,
    get_import_batches,
    get_contacts,
    save_contacts,
    update_contact,
    create_campaign,
    get_campaigns,
    get_campaign,
    update_campaign_status,
    get_campaign_contacts,
    get_leads,
    get_lead_by_id,
    get_lead_by_phone,
    create_lead,
    create_or_update_lead,
    export_leads,
    get_appointments,
    create_appointment,
    update_appointment,
    get_dnd_entries,
    add_dnd_entry,
    is_phone_dnd,
    get_campaign_analytics,
    create_browser_session,
    finish_browser_session,
    get_browser_sessions,
    save_call,
    save_outbound_call,
    update_browser_session_status,
    SessionLocal,
    AuditLog,
    select,
)
from backend.importer import process_contact_document
from backend.outbound import CallRequest, initiate_call, provider_status
from backend.scheduler import validate_and_book_appointment, reschedule_site_visit, cancel_site_visit
from backend.speech.stt import SpeechToText
from backend.speech.tts import TextToSpeech
from sarvamai import AsyncSarvamAI
from sarvamai.types import RealtimeAudioInput
from sarvamai.types.realtime_transcript_final import RealtimeTranscriptFinal

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Autonomous Lead Generation Engine")

stt = SpeechToText()
tts = TextToSpeech()
knowledge = KnowledgeBase()
conversation_manager = ConversationManager()
campaign_engine = CampaignEngine()
async_sarvam = AsyncSarvamAI(api_subscription_key=SARVAM_API_KEY) if SARVAM_API_KEY else None


@app.on_event("startup")
def startup() -> None:
    create_tables()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html_path = Path(__file__).with_name("web.html")
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>AI Autonomous Lead Generation Engine</h1>"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "system": "AI Autonomous Lead Generation Engine",
        "speech_to_text": "configured",
        "text_to_speech": "configured",
        "conversational_llm": "configured (Sarvam 105B)",
        "knowledge_documents": len(knowledge.documents),
        "telephony": provider_status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ==========================================
# 1. Contact Import & Processing APIs
# ==========================================

@app.post("/api/contacts/upload")
async def upload_contacts(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload Excel, CSV, PDF, Word, or TXT file and return validation preview."""
    suffix = Path(file.filename or "contacts.csv").suffix.lower()
    if suffix not in [".xlsx", ".xls", ".csv", ".docx", ".pdf", ".txt"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix}'. Supported: .xlsx, .xls, .csv, .pdf, .docx, .txt",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_doc:
        temp_path = temp_doc.name
        temp_doc.write(await file.read())

    try:
        parsed = process_contact_document(temp_path, file.filename or f"contacts{suffix}")
        summary = parsed["summary"]

        # Persist batch record and extracted contacts
        batch = create_import_batch(
            filename=summary["filename"],
            file_type=summary["file_type"],
            total_rows=summary["total_rows"],
            valid_rows=summary["valid_rows"],
            duplicate_rows=summary["duplicate_rows"],
            invalid_rows=summary["invalid_rows"],
            review_needed_rows=summary["review_needed_rows"],
            status="preview",
        )
        saved = save_contacts(parsed["rows"], batch_id=batch.id)

        # Return rows with assigned contact DB ids
        return_rows = []
        for contact_obj, row_dict in zip(saved, parsed["rows"]):
            d = dict(row_dict)
            d["id"] = contact_obj.id
            d["batch_id"] = batch.id
            return_rows.append(d)

        return {
            "batch_id": batch.id,
            "summary": summary,
            "rows": return_rows,
        }
    except Exception as e:
        logger.exception("Document parsing failed")
        raise HTTPException(status_code=422, detail=f"Failed to process document: {str(e)}") from e
    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@app.post("/api/contacts/load-sample")
def load_sample_contacts() -> dict[str, Any]:
    """Load pre-configured sample Excel file for immediate evaluation."""
    sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_contacts.xlsx"
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail="Sample contacts file not found")

    parsed = process_contact_document(str(sample_path), "sample_contacts.xlsx")
    summary = parsed["summary"]

    batch = create_import_batch(
        filename="sample_contacts.xlsx",
        file_type="xlsx",
        total_rows=summary["total_rows"],
        valid_rows=summary["valid_rows"],
        duplicate_rows=summary["duplicate_rows"],
        invalid_rows=summary["invalid_rows"],
        review_needed_rows=summary["review_needed_rows"],
        status="approved",
    )
    saved = save_contacts(parsed["rows"], batch_id=batch.id)

    return_rows = []
    for contact_obj, row_dict in zip(saved, parsed["rows"]):
        d = dict(row_dict)
        d["id"] = contact_obj.id
        d["batch_id"] = batch.id
        return_rows.append(d)

    return {
        "batch_id": batch.id,
        "summary": summary,
        "rows": return_rows,
    }


@app.get("/api/contacts/batches")
def get_batches() -> list[dict[str, Any]]:
    return [
        {
            "id": b.id,
            "filename": b.filename,
            "file_type": b.file_type,
            "total_rows": b.total_rows,
            "valid_rows": b.valid_rows,
            "duplicate_rows": b.duplicate_rows,
            "invalid_rows": b.invalid_rows,
            "review_needed_rows": b.review_needed_rows,
            "status": b.status,
            "created_at": b.created_at.isoformat(),
        }
        for b in get_import_batches()
    ]


@app.get("/api/contacts")
def list_contacts(batch_id: int | None = None) -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "batch_id": c.batch_id,
            "name": c.name,
            "phone_number": c.phone_number,
            "raw_phone": c.raw_phone,
            "email": c.email,
            "locality": c.locality,
            "budget": c.budget,
            "bhk": c.bhk,
            "notes": c.notes,
            "validation_status": c.validation_status,
            "validation_message": c.validation_message,
            "is_dnd": c.is_dnd,
        }
        for c in get_contacts(batch_id)
    ]


class ContactUpdateRequest(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    validation_status: str | None = None
    notes: str | None = None
    locality: str | None = None


@app.put("/api/contacts/{contact_id}")
def edit_contact(contact_id: int, req: ContactUpdateRequest) -> dict[str, Any]:
    updates = {k: v for k, v in req.dict().items() if v is not None}
    c = update_contact(contact_id, updates)
    return {
        "id": c.id,
        "name": c.name,
        "phone_number": c.phone_number,
        "validation_status": c.validation_status,
        "message": "Contact updated successfully",
    }


# ==========================================
# 2. Campaign Creation & Control APIs
# ==========================================

class CreateCampaignRequest(BaseModel):
    name: str
    project_name: str = "Krishna's AI Property - Wakad"
    objective: str = "New Launch Awareness & Lead Qualification"
    batch_id: int | None = None
    agent_name: str = "Priya - Residential Advisory Executive"
    language: str = "en-IN"
    window_start: str = "09:30"
    window_end: str = "19:30"
    max_attempts: int = 2
    retry_interval_minutes: int = 60
    assigned_sales_team: str = "Wakad Sales Desk"
    follow_up_policy: str = "Immediate CRM alert & site visit slot reservation"
    concurrency_limit: int = 2
    contact_ids: list[int] | None = None


@app.post("/api/campaigns")
def api_create_campaign(req: CreateCampaignRequest) -> dict[str, Any]:
    c = create_campaign(
        name=req.name,
        project_name=req.project_name,
        objective=req.objective,
        batch_id=req.batch_id,
        agent_name=req.agent_name,
        language=req.language,
        window_start=req.window_start,
        window_end=req.window_end,
        max_attempts=req.max_attempts,
        retry_interval_minutes=req.retry_interval_minutes,
        assigned_sales_team=req.assigned_sales_team,
        follow_up_policy=req.follow_up_policy,
        concurrency_limit=req.concurrency_limit,
        contact_ids=req.contact_ids,
    )
    return {
        "id": c.id,
        "name": c.name,
        "status": c.status,
        "message": "Campaign created in Draft status. Explicit launch approval required.",
    }


@app.get("/api/campaigns")
def list_campaigns() -> list[dict[str, Any]]:
    campaigns = get_campaigns()
    res = []
    for c in campaigns:
        contacts = get_campaign_contacts(c.id)
        completed = len([item for item in contacts if item.status == "completed"])
        res.append({
            "id": c.id,
            "name": c.name,
            "project_name": c.project_name,
            "objective": c.objective,
            "agent_name": c.agent_name,
            "language": c.language,
            "window_start": c.window_start,
            "window_end": c.window_end,
            "max_attempts": c.max_attempts,
            "status": c.status,
            "total_contacts": len(contacts),
            "completed_contacts": completed,
            "created_at": c.created_at.isoformat(),
        })
    return res


@app.get("/api/campaigns/live-events")
def get_live_events() -> list[dict[str, Any]]:
    return campaign_engine.get_live_events(limit=50)


@app.get("/api/campaigns/{campaign_id}")
def get_campaign_detail(campaign_id: int) -> dict[str, Any]:
    c = get_campaign(campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    contacts = get_campaign_contacts(c.id)
    return {
        "id": c.id,
        "name": c.name,
        "project_name": c.project_name,
        "objective": c.objective,
        "agent_name": c.agent_name,
        "language": c.language,
        "window_start": c.window_start,
        "window_end": c.window_end,
        "max_attempts": c.max_attempts,
        "assigned_sales_team": c.assigned_sales_team,
        "status": c.status,
        "contacts": [
            {
                "id": cc.id,
                "name": cc.name,
                "phone_number": cc.phone_number,
                "locality": cc.locality,
                "attempts": cc.attempts,
                "status": cc.status,
                "call_outcome": cc.call_outcome,
                "last_call_at": cc.last_call_at.isoformat() if cc.last_call_at else None,
            }
            for cc in contacts
        ],
    }


@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign_api(campaign_id: int) -> dict[str, Any]:
    return await campaign_engine.start_campaign(campaign_id, bypass_window_for_test=True)


@app.post("/api/campaigns/{campaign_id}/pause")
def pause_campaign_api(campaign_id: int) -> dict[str, Any]:
    return campaign_engine.pause_campaign(campaign_id)


@app.post("/api/campaigns/{campaign_id}/resume")
def resume_campaign_api(campaign_id: int) -> dict[str, Any]:
    return campaign_engine.resume_campaign(campaign_id, bypass_window_for_test=True)


@app.post("/api/campaigns/{campaign_id}/stop")
def stop_campaign_api(campaign_id: int) -> dict[str, Any]:
    return campaign_engine.stop_campaign(campaign_id)


@app.get("/api/campaigns/{campaign_id}/analytics")
def get_campaign_analytics_api(campaign_id: int) -> dict[str, Any]:
    return get_campaign_analytics(campaign_id)



# ==========================================
# 3. CRM Leads & Intelligence APIs
# ==========================================

@app.get("/api/leads")
def leads_api() -> list[dict[str, Any]]:
    return [
        {
            "id": lead.id,
            "name": lead.name,
            "phone_number": lead.phone_number,
            "email": lead.email,
            "area": lead.area,
            "budget": lead.budget,
            "bhk": lead.bhk,
            "purpose": lead.purpose,
            "timeline": lead.timeline,
            "financing": lead.financing,
            "amenities": lead.amenities,
            "site_visit_interest": lead.site_visit_interest,
            "interest_status": lead.interest_status,
            "score": lead.score,
            "summary": lead.summary,
            "next_action": lead.next_action,
            "assigned_salesperson": lead.assigned_salesperson,
            "opt_out": lead.opt_out,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        }
        for lead in get_leads()
    ]


@app.get("/api/leads/{lead_id}")
def lead_detail(lead_id: int) -> dict[str, Any]:
    lead = get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    try:
        score_breakdown = json.loads(lead.score_breakdown) if lead.score_breakdown else {}
    except Exception:
        score_breakdown = {}

    try:
        extracted = json.loads(lead.extracted_requirements) if lead.extracted_requirements else {}
    except Exception:
        extracted = {}

    try:
        evidence = json.loads(lead.evidence) if lead.evidence else {}
    except Exception:
        evidence = {}

    appts = get_appointments(lead_id)

    return {
        "id": lead.id,
        "name": lead.name,
        "phone_number": lead.phone_number,
        "email": lead.email,
        "area": lead.area,
        "budget": lead.budget,
        "bhk": lead.bhk,
        "purpose": lead.purpose,
        "timeline": lead.timeline,
        "financing": lead.financing,
        "amenities": lead.amenities,
        "site_visit_interest": lead.site_visit_interest,
        "interest_status": lead.interest_status,
        "score": lead.score,
        "score_breakdown": score_breakdown,
        "summary": lead.summary,
        "extracted_requirements": extracted,
        "evidence": evidence,
        "next_action": lead.next_action,
        "assigned_salesperson": lead.assigned_salesperson,
        "opt_out": lead.opt_out,
        "appointments": [
            {
                "id": a.id,
                "date": a.requested_date,
                "time": a.requested_time,
                "confirmed_date_time": a.confirmed_date_time,
                "status": a.status,
                "confirmation_code": a.confirmation_code,
                "assigned_salesperson": a.assigned_salesperson,
            }
            for a in appts
        ],
    }


@app.post("/api/leads")
def add_lead_api(
    name: str = Form(...),
    area: str = Form(""),
    phone_number: str = Form(...),
) -> dict[str, Any]:
    lead = create_lead(name, area, phone_number)
    return {"id": lead.id, "name": lead.name}


@app.get("/api/leads/export")
def download_leads_api() -> FileResponse:
    output = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    output.close()
    export_leads(output.name)
    return FileResponse(
        output.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="krishnas-ai-property-leads.xlsx",
    )


# ==========================================
# 4. Site Visits & Appointments APIs
# ==========================================

@app.get("/api/appointments")
def list_appointments() -> list[dict[str, Any]]:
    return [
        {
            "id": a.id,
            "lead_id": a.lead_id,
            "campaign_id": a.campaign_id,
            "project_name": a.project_name,
            "meeting_type": a.meeting_type,
            "requested_date": a.requested_date,
            "requested_time": a.requested_time,
            "confirmed_date_time": a.confirmed_date_time,
            "assigned_salesperson": a.assigned_salesperson,
            "status": a.status,
            "confirmation_code": a.confirmation_code,
            "customer_notes": a.customer_notes,
            "created_at": a.created_at.isoformat(),
        }
        for a in get_appointments()
    ]


class BookAppointmentRequest(BaseModel):
    lead_id: int
    requested_date: str
    requested_time: str
    project_name: str = "Krishna's AI Property - Wakad"
    customer_notes: str = ""


@app.post("/api/appointments")
def book_appointment_api(req: BookAppointmentRequest) -> dict[str, Any]:
    return validate_and_book_appointment(
        lead_id=req.lead_id,
        requested_date_raw=req.requested_date,
        requested_time_raw=req.requested_time,
        project_name=req.project_name,
        customer_notes=req.customer_notes,
    )


class RescheduleRequest(BaseModel):
    new_date: str
    new_time: str


@app.post("/api/appointments/{appt_id}/reschedule")
def reschedule_appointment_api(appt_id: int, req: RescheduleRequest) -> dict[str, Any]:
    return reschedule_site_visit(appt_id, req.new_date, req.new_time)


@app.post("/api/appointments/{appt_id}/cancel")
def cancel_appointment_api(appt_id: int, reason: str = "Customer requested cancellation") -> dict[str, Any]:
    return cancel_site_visit(appt_id, reason)


# ==========================================
# 5. Compliance, DND, and Audit APIs
# ==========================================

@app.get("/api/compliance/dnd")
def get_dnd_list() -> list[dict[str, Any]]:
    return [
        {
            "id": d.id,
            "phone_number": d.phone_number,
            "reason": d.reason,
            "source": d.source,
            "created_at": d.created_at.isoformat(),
        }
        for d in get_dnd_entries()
    ]


class DndRegisterRequest(BaseModel):
    phone_number: str
    reason: str = "Customer requested opt-out"


@app.post("/api/compliance/dnd")
def register_dnd_api(req: DndRegisterRequest) -> dict[str, Any]:
    entry = add_dnd_entry(req.phone_number, req.reason, "manual_admin")
    return {"id": entry.id, "phone_number": entry.phone_number, "message": "Phone number added to DND registry"}


@app.get("/api/compliance/audit-logs")
def get_audit_logs() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        logs = list(session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)))
        return [
            {
                "id": log.id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]


@app.get("/api/analytics/overview")
def get_overview_analytics() -> dict[str, Any]:
    return get_campaign_analytics(None)


# ==========================================
# 6. Browser Voice Studio (WebSocket & Demo)
# ==========================================

@app.get("/api/call-history")
def call_history() -> list[dict[str, Any]]:
    return [
        {
            "session_id": item.session_id,
            "lead_id": item.lead_id,
            "status": item.status,
            "started_at": item.started_at.isoformat(),
            "ended_at": item.ended_at.isoformat() if item.ended_at else None,
            "summary": item.summary,
            "score": item.score,
            "score_category": item.score_category,
            "requirements": item.requirements,
            "follow_up": item.follow_up,
        }
        for item in get_browser_sessions()
    ]


class TestCallRequest(BaseModel):
    lead_id: int


@app.post("/api/outbound/test-call")
def outbound_test_call(request: TestCallRequest) -> dict[str, Any]:
    lead_id = request.lead_id
    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead was not found")
    if lead.opt_out or is_phone_dnd(lead.phone_number):
        raise HTTPException(status_code=409, detail="Lead is on the do-not-call list")
    try:
        result = initiate_call(CallRequest(lead.phone_number, lead.id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    call = save_outbound_call(
        lead.id,
        lead.phone_number,
        result.provider_call_id,
        result.status,
        result.message,
    )
    return {
        "id": call.id,
        "provider_call_id": result.provider_call_id,
        "status": result.status,
        "message": result.message,
    }


from backend.agent.real_estate import RealEstateConversation

async def _create_voice_reply(
    text: str,
    language: str = "en-IN",
    session_id: str | None = None,
    conversation: RealEstateConversation | None = None,
) -> tuple[str, bytes]:
    if session_id:
        response_text, _, _ = conversation_manager.process_turn(session_id, text)
    else:
        conversation = conversation or RealEstateConversation()
        response_text, _ = conversation.reply(text, knowledge.search(text))

    def synthesize() -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as response_file:
            response_path = response_file.name
        try:
            tts.synthesize(response_text, language, response_path)
            with open(response_path, "rb") as generated_audio:
                return generated_audio.read()
        finally:
            try:
                os.unlink(response_path)
            except FileNotFoundError:
                pass

    return response_text, await asyncio.to_thread(synthesize)


@app.websocket("/ws/voice")
async def realtime_voice(websocket: WebSocket) -> None:
    await websocket.accept()
    lead_id: int | None = None
    session = None
    session_finalized = False
    transcript_parts: list[str] = []

    try:
        initial_message = await websocket.receive_json()
        if initial_message.get("type") != "start":
            raise ValueError("The first realtime message must be a start message")
        lead_id = int(initial_message["lead_id"])
        session = create_browser_session(lead_id)
        conv_session = conversation_manager.get_or_create_session(
            session_id=session.session_id,
            lead_id=lead_id,
        )
        await websocket.send_json(
            {
                "type": "session_started",
                "session_id": session.session_id,
                "mode": "Browser Demo Studio",
                "status": "connecting",
            }
        )

        if not async_sarvam:
            raise RuntimeError("Sarvam AI subscription key is not configured for realtime speech streaming")

        async with async_sarvam.speech_to_text_realtime_streaming.connect(
            language_code="auto",
            model="saaras:v3-realtime",
            mode="transcribe",
            endpointing="vad",
            encoding="linear16",
            sample_rate="16000",
            silence_duration_ms="700",
        ) as sarvam_socket:
            update_browser_session_status(session.session_id, "active")
            await websocket.send_json({"type": "session_active"})

            async def forward_audio() -> None:
                nonlocal session_finalized
                while True:
                    message = await websocket.receive_json()
                    if message.get("type") == "end":
                        transcript = chr(10).join(transcript_parts)
                        analysis = analyze_conversation(transcript)
                        finish_browser_session(
                            session.session_id,
                            "completed",
                            transcript,
                            analysis["summary"],
                            json.dumps(analysis["requirements"]),
                            analysis["score"],
                            analysis["category"],
                            analysis["follow_up"],
                        )
                        session_finalized = True
                        await websocket.send_json({"type": "session_ended"})
                        return
                    if message.get("type") == "audio":
                        encoded_audio = message.get("audio")
                        if not isinstance(encoded_audio, str) or not encoded_audio:
                            raise ValueError("Realtime audio message is missing audio data")
                        try:
                            base64.b64decode(encoded_audio, validate=True)
                        except ValueError as error:
                            raise ValueError("Realtime audio message is not valid base64") from error
                        await sarvam_socket.send_realtime_audio_input(
                            RealtimeAudioInput(audio=encoded_audio)
                        )

            async def handle_transcripts() -> None:
                while True:
                    event = await sarvam_socket.recv()
                    if isinstance(event, RealtimeTranscriptFinal):
                        transcript_parts.append(f"Customer: {event.text}")
                        language = event.language or "en-IN"
                        response_text, audio = await _create_voice_reply(
                            event.text,
                            language,
                            session.session_id,
                        )
                        transcript_parts.append(f"Agent: {response_text}")
                        if not audio:
                            raise RuntimeError("Text-to-speech returned empty audio")

                        await websocket.send_json(
                            {
                                "type": "transcript",
                                "text": event.text,
                                "speaker": "customer",
                            }
                        )
                        await websocket.send_json(
                            {
                                "type": "response",
                                "text": event.text,
                                "response": response_text,
                                "audio": base64.b64encode(audio).decode("ascii"),
                            }
                        )

            audio_task = asyncio.create_task(forward_audio())
            transcript_task = asyncio.create_task(handle_transcripts())
            done, pending = await asyncio.wait(
                (audio_task, transcript_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception

    except WebSocketDisconnect:
        logger.info("Realtime browser session ended")
        if session is not None and not session_finalized:
            try:
                update_browser_session_status(
                    session.session_id,
                    "cancelled",
                    "Browser connection closed before call was ended normally.",
                )
            except Exception:
                pass
    except Exception as error:
        logger.exception("Realtime voice session failed")
        if session is not None and not session_finalized:
            try:
                update_browser_session_status(
                    session.session_id,
                    "failed",
                    f"Realtime session failed: {error}",
                )
            except Exception:
                pass
        try:
            await websocket.send_json({"type": "error", "message": str(error)})
        except Exception:
            pass


# ==========================================
# Real Telephony & Outbound Calling APIs
# ==========================================

@app.get("/api/telephony/status")
def api_telephony_status() -> dict[str, Any]:
    """Inspect readiness of telephony provider (Exotel, Twilio, Mock)."""
    return get_telephony_status()


class InitiateCallRequest(BaseModel):
    lead_id: int
    phone_number: str | None = None
    campaign_id: int | None = None
    caller_id: str | None = None


@app.post("/api/telephony/call")
def api_initiate_telephony_call(req: InitiateCallRequest) -> dict[str, Any]:
    """Initiate a real outbound telephone call to an actual mobile number."""
    lead = get_lead_by_id(req.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead #{req.lead_id} not found")

    target_phone = req.phone_number or lead.phone_number
    if not target_phone:
        raise HTTPException(status_code=400, detail="Missing destination phone number")

    # DND & Opt-out enforcement
    if lead.opt_out or is_phone_dnd(target_phone):
        raise HTTPException(
            status_code=409,
            detail=f"Call blocked: Phone number {target_phone} is registered on the Do Not Call (DND) list.",
        )

    try:
        call_req = CallRequest(
            phone_number=target_phone,
            lead_id=lead.id,
            campaign_id=req.campaign_id,
            caller_id=req.caller_id,
            customer_name=lead.name,
        )
        result = initiate_outbound_call(call_req)
        
        call_record = save_outbound_call(
            lead_id=lead.id,
            phone_number=target_phone,
            provider_call_id=result.provider_call_id,
            status=result.status,
            message=result.message,
            provider=result.provider,
            campaign_id=req.campaign_id,
        )

        return {
            "success": True,
            "call_id": call_record.id,
            "provider_call_id": result.provider_call_id,
            "provider": result.provider,
            "status": result.status,
            "message": result.message,
        }

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Call initiation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Call initiation failure: {e}") from e


@app.get("/api/telephony/calls")
def api_list_telephony_calls(campaign_id: int | None = None, lead_id: int | None = None) -> list[dict[str, Any]]:
    """List all outbound telephone calls with statuses and durations."""
    return [
        {
            "id": c.id,
            "lead_id": c.lead_id,
            "campaign_id": c.campaign_id,
            "phone_number": c.phone_number,
            "provider_call_id": c.provider_call_id,
            "provider": c.provider,
            "status": c.status,
            "call_status": c.call_status,
            "duration_seconds": c.duration_seconds,
            "recording_url": c.recording_url,
            "error_message": c.error_message,
            "created_at": c.created_at.isoformat(),
        }
        for c in get_outbound_calls(campaign_id, lead_id)
    ]


@app.post("/api/telephony/webhook/exotel/status")
async def exotel_status_webhook(request: Request) -> dict[str, str]:
    """Handle status callback notifications from Exotel."""
    body = await request.body()
    headers = dict(request.headers)
    try:
        form = await request.form()
        payload = dict(form)
    except Exception:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

    logger.info(f"Received Exotel status webhook: {payload}")
    update = process_webhook("exotel", payload, headers, body)
    
    if update.provider_call_id:
        update_outbound_call_status(
            provider_call_id=update.provider_call_id,
            status=update.status,
            duration_seconds=update.duration_seconds,
            recording_url=update.recording_url,
            error_message=update.error_message,
        )
    return {"status": "ok"}


@app.post("/api/telephony/webhook/twilio/status")
async def twilio_status_webhook(request: Request) -> dict[str, str]:
    """Handle status callback notifications from Twilio."""
    body = await request.body()
    headers = dict(request.headers)
    try:
        form = await request.form()
        payload = dict(form)
    except Exception:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

    logger.info(f"Received Twilio status callback: {payload}")
    update = process_webhook("twilio", payload, headers, body)

    if update.provider_call_id:
        update_outbound_call_status(
            provider_call_id=update.provider_call_id,
            status=update.status,
            duration_seconds=update.duration_seconds,
            recording_url=update.recording_url,
            error_message=update.error_message,
        )
    return {"status": "ok"}


@app.post("/api/telephony/webhook/call-connection")
async def call_connection_webhook(request: Request) -> dict[str, str]:
    """Generic call connection webhook."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    call_sid = payload.get("CallSid") or payload.get("provider_call_id")
    if call_sid:
        update_outbound_call_status(call_sid, "answered")
    return {"status": "connected"}


@app.post("/api/telephony/webhook/call-completion")
async def call_completion_webhook(request: Request) -> dict[str, str]:
    """Generic call completion webhook."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    call_sid = payload.get("CallSid") or payload.get("provider_call_id")
    duration = int(payload.get("duration", 0))
    if call_sid:
        update_outbound_call_status(call_sid, "completed", duration_seconds=duration)
    return {"status": "completed"}


@app.api_route("/api/telephony/exotel/voicebot-endpoint", methods=["GET", "POST"])
async def exotel_voicebot_endpoint(request: Request) -> dict[str, str]:
    """Exotel Voicebot Applet Dynamic URL Resolution Endpoint.
    
    When an Exotel call flow enters a Voicebot Applet with dynamic URL routing,
    Exotel hits this endpoint. We return the target wss:// URL for Exotel AgentStream
    enriched with inbound call metadata (CallSid, Caller phone, and Lead ID).
    """
    params = dict(request.query_params)
    if request.method == "POST":
        content_type = request.headers.get("content-type", "").lower()
        if "form" in content_type:
            try:
                form = await request.form()
                params.update(dict(form))
            except Exception:
                pass
        elif "json" in content_type:
            try:
                json_data = await request.json()
                if isinstance(json_data, dict):
                    params.update(json_data)
            except Exception:
                pass

    call_sid = params.get("CallSid") or params.get("Sid") or params.get("call_sid") or ""
    caller_phone = params.get("From") or params.get("CallFrom") or params.get("from") or ""
    to_phone = params.get("To") or params.get("CallTo") or params.get("to") or ""
    direction = params.get("Direction") or params.get("direction") or "inbound"

    lead_id = None
    customer_name = "there"
    if caller_phone:
        try:
            normalized_caller = validate_phone_number(caller_phone)
        except Exception:
            normalized_caller = caller_phone

        lead = get_lead_by_phone(normalized_caller) or get_lead_by_phone(caller_phone)
        if lead:
            lead_id = lead.id
            customer_name = lead.name
        else:
            clean_digits = re.sub(r"[^\d]", "", caller_phone)
            suffix = clean_digits[-4:] if len(clean_digits) >= 4 else "New"
            lead = create_or_update_lead(
                name=f"Inbound Caller ({suffix})",
                phone_number=normalized_caller,
                interest_status="Inquiry",
                summary=f"Inbound call received on ExoPhone {to_phone}",
            )
            lead_id = lead.id
            customer_name = lead.name

        if call_sid:
            calls = get_outbound_calls()
            matched = [c for c in calls if c.provider_call_id == call_sid]
            if not matched:
                save_outbound_call(
                    lead_id=lead_id,
                    phone_number=normalized_caller,
                    provider_call_id=call_sid,
                    status="ringing",
                    message=f"Inbound call from {normalized_caller} to ExoPhone {to_phone}",
                    provider="exotel",
                )

    public_url = os.getenv("AGENTSTREAM_PUBLIC_URL") or os.getenv("PUBLIC_BASE_URL") or ""
    host = request.headers.get("host", "127.0.0.1:8000")

    if public_url:
        ws_base = public_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    else:
        scheme = "wss" if request.url.scheme == "https" else "ws"
        ws_base = f"{scheme}://{host}"

    query_parts = []
    if call_sid:
        query_parts.append(f"call_sid={call_sid}")
    if caller_phone:
        query_parts.append(f"from={caller_phone}")
    if lead_id:
        query_parts.append(f"lead_id={lead_id}")
    query_parts.append("direction=inbound")

    qs = ("?" + "&".join(query_parts)) if query_parts else ""
    ws_url = f"{ws_base}/ws/telephony/exotel/stream{qs}"
    logger.info(f"Exotel Voicebot Dynamic Endpoint queried (CallSid: {call_sid}, Caller: {caller_phone}); responding with WebSocket URL: {ws_url}")
    return {
        "url": ws_url,
        "Url": ws_url,
        "URL": ws_url,
        "stream_url": ws_url,
        "websocket_url": ws_url,
    }


@app.api_route("/api/telephony/exotel/passthru", methods=["GET", "POST"])
@app.api_route("/api/telephony/webhook/exotel/inbound", methods=["GET", "POST"])
async def exotel_passthru_endpoint(request: Request) -> Response:
    """Exotel Passthru Applet endpoint for logging and preparing inbound calls before voicebot."""
    params = dict(request.query_params)
    if request.method == "POST":
        content_type = request.headers.get("content-type", "").lower()
        if "form" in content_type:
            try:
                form = await request.form()
                params.update(dict(form))
            except Exception:
                pass
        elif "json" in content_type:
            try:
                json_data = await request.json()
                if isinstance(json_data, dict):
                    params.update(json_data)
            except Exception:
                pass

    call_sid = params.get("CallSid") or params.get("Sid") or ""
    caller_phone = params.get("From") or params.get("CallFrom") or ""
    to_phone = params.get("To") or params.get("CallTo") or ""

    if caller_phone:
        try:
            normalized_caller = validate_phone_number(caller_phone)
        except Exception:
            normalized_caller = caller_phone

        lead = get_lead_by_phone(normalized_caller) or get_lead_by_phone(caller_phone)
        if not lead:
            clean_digits = re.sub(r"[^\d]", "", caller_phone)
            suffix = clean_digits[-4:] if len(clean_digits) >= 4 else "New"
            lead = create_or_update_lead(
                name=f"Inbound Caller ({suffix})",
                phone_number=normalized_caller,
                interest_status="Inquiry",
                summary=f"Inbound passthru call to ExoPhone {to_phone}",
            )

        if call_sid:
            calls = get_outbound_calls()
            matched = [c for c in calls if c.provider_call_id == call_sid]
            if not matched:
                save_outbound_call(
                    lead_id=lead.id,
                    phone_number=normalized_caller,
                    provider_call_id=call_sid,
                    status="ringing",
                    message=f"Inbound passthru call from {normalized_caller}",
                    provider="exotel",
                )

    return Response(content="OK", media_type="text/plain")


@app.api_route("/api/telephony/twilio/inbound", methods=["GET", "POST"])
@app.api_route("/api/telephony/inbound", methods=["GET", "POST"])
async def twilio_inbound_voice(request: Request) -> Response:
    """Twilio Inbound Voice Webhook returning TwiML stream instruction."""
    params = dict(request.query_params)
    if request.method == "POST":
        content_type = request.headers.get("content-type", "").lower()
        if "form" in content_type:
            try:
                form = await request.form()
                params.update(dict(form))
            except Exception:
                pass
        elif "json" in content_type:
            try:
                json_data = await request.json()
                if isinstance(json_data, dict):
                    params.update(json_data)
            except Exception:
                pass

    call_sid = params.get("CallSid") or f"twilio_in_{uuid4().hex[:8]}"
    caller = params.get("From", "")
    to_num = params.get("To", "")

    lead_id = None
    customer_name = "there"
    if caller:
        try:
            norm_caller = validate_phone_number(caller)
        except Exception:
            norm_caller = caller

        lead = get_lead_by_phone(norm_caller) or get_lead_by_phone(caller)
        if lead:
            lead_id = lead.id
            customer_name = lead.name
        else:
            clean_digits = re.sub(r"[^\d]", "", caller)
            suffix = clean_digits[-4:] if len(clean_digits) >= 4 else "New"
            lead = create_or_update_lead(
                name=f"Inbound Caller ({suffix})",
                phone_number=norm_caller,
                interest_status="Inquiry",
                summary=f"Inbound Twilio call to {to_num}",
            )
            lead_id = lead.id
            customer_name = lead.name

        save_outbound_call(
            lead_id=lead_id,
            phone_number=norm_caller,
            provider_call_id=call_sid,
            status="ringing",
            message=f"Inbound Twilio call from {norm_caller}",
            provider="twilio",
        )

    public_url = os.getenv("PUBLIC_BASE_URL") or os.getenv("AGENTSTREAM_PUBLIC_URL") or ""
    host = request.headers.get("host", "127.0.0.1:8000")
    if public_url:
        ws_base = public_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    else:
        scheme = "wss" if request.url.scheme == "https" else "ws"
        ws_base = f"{scheme}://{host}"

    ws_url = f"{ws_base}/ws/telephony/stream"

    twiml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Response>\n'
        f'    <Connect>\n'
        f'        <Stream url="{ws_url}">\n'
        f'            <Parameter name="call_sid" value="{call_sid}" />\n'
        f'            <Parameter name="caller" value="{caller}" />\n'
        f'            <Parameter name="direction" value="inbound" />\n'
        f'            <Parameter name="lead_id" value="{lead_id or 0}" />\n'
        f'            <Parameter name="customer_name" value="{customer_name}" />\n'
        f'        </Stream>\n'
        f'    </Connect>\n'
        f'</Response>'
    )
    return Response(content=twiml, media_type="application/xml")


class SimulateInboundCallRequest(BaseModel):
    caller_phone: str = "+919876543210"
    customer_name: str | None = None
    customer_speech: str = "Hi, I am looking for a 2 BHK apartment near Hinjawadi under 80 lakhs."
    language: str = "en-IN"


@app.post("/api/telephony/inbound/simulate")
def simulate_inbound_call(req: SimulateInboundCallRequest) -> dict[str, Any]:
    """Simulate an end-to-end inbound customer phone call into the AI voice agent."""
    caller = validate_phone_number(req.caller_phone)
    lead = get_lead_by_phone(caller)
    if not lead:
        clean_digits = re.sub(r"[^\d]", "", caller)
        suffix = clean_digits[-4:] if len(clean_digits) >= 4 else "New"
        lead = create_or_update_lead(
            name=req.customer_name or f"Inbound Lead ({suffix})",
            phone_number=caller,
            interest_status="Inquiry",
            summary="Simulated inbound call enquiry",
        )

    call_sid = f"mock-inbound-{uuid4().hex[:8]}"
    save_outbound_call(
        lead_id=lead.id,
        phone_number=caller,
        provider_call_id=call_sid,
        status="in_progress",
        message="Simulated inbound call",
        provider="mock",
    )

    session = conversation_manager.get_or_create_session(
        session_id=call_sid,
        lead_id=lead.id,
        customer_name=lead.name,
        language=req.language,
    )
    greeting = conversation_manager.generate_opening_greeting(session, is_inbound=True)
    reply, intent, facts = conversation_manager.process_turn(call_sid, req.customer_speech)

    transcript = f"Agent: {greeting}\nCustomer: {req.customer_speech}\nAgent: {reply}"
    analysis = analyze_conversation(transcript, lead.name)

    create_or_update_lead(
        name=lead.name,
        phone_number=caller,
        interest_status=analysis["category"],
        score=analysis["score"],
        summary=analysis["summary"],
        extracted_requirements=analysis["requirements"],
        evidence=analysis["evidence"],
        next_action=analysis["next_action"],
    )
    call_summary = save_call(
        lead_id=lead.id,
        transcript=transcript,
        agent_response=reply,
        interest_status=analysis["category"],
        call_mode="telephony_inbound",
        call_duration_seconds=35,
    )
    update_outbound_call_status(call_sid, "completed", duration_seconds=35)

    return {
        "status": "completed",
        "call_sid": call_sid,
        "caller": caller,
        "lead_id": lead.id,
        "lead_name": lead.name,
        "greeting": greeting,
        "agent_reply": reply,
        "intent": intent,
        "analysis": analysis,
        "call_summary_id": call_summary.id,
    }


async def _handle_telephony_media_stream(websocket: WebSocket, provider_hint: str = "auto") -> None:
    """Unified Bidirectional WebSocket Audio Stream for Exotel AgentStream and Twilio Media Streams."""
    await websocket.accept()
    ws_query = dict(websocket.query_params)
    ws_call_sid = ws_query.get("call_sid") or ws_query.get("CallSid")
    ws_caller = ws_query.get("from") or ws_query.get("From") or ws_query.get("caller") or ws_query.get("CallFrom")
    ws_direction = ws_query.get("direction") or ws_query.get("Direction")
    ws_lead_id = int(ws_query["lead_id"]) if ws_query.get("lead_id") and ws_query["lead_id"].isdigit() else None

    stream_sid = None
    call_sid = None
    lead_id = None
    campaign_id = None
    customer_name = "there"
    caller_phone = ""
    is_inbound = False
    session_id = str(uuid4())
    transcript_parts: list[str] = []
    speech_buffer = bytearray()
    silence_frames = 0
    start_time = datetime.now(timezone.utc)
    is_exotel = (provider_hint == "exotel")

    try:
        async for message_text in websocket.iter_text():
            try:
                msg = json.loads(message_text)
            except Exception:
                continue

            event = msg.get("event")

            if event == "connected":
                logger.info(f"Telephony audio stream connected (provider hint: {provider_hint})")

            elif event == "start":
                start_data = msg.get("start", {})
                stream_sid = (
                    start_data.get("stream_sid")
                    or start_data.get("streamSid")
                    or msg.get("stream_sid")
                    or msg.get("streamSid")
                )
                call_sid = (
                    start_data.get("call_sid")
                    or start_data.get("callSid")
                    or start_data.get("CallSid")
                    or msg.get("call_sid")
                    or ws_call_sid
                    or f"call_{uuid4().hex[:12]}"
                )

                custom_params = start_data.get("custom_parameters") or start_data.get("customParameters") or {}
                if not custom_params and "CustomField" in start_data:
                    try:
                        custom_params = json.loads(start_data["CustomField"])
                    except Exception:
                        pass

                lead_id = int(custom_params.get("lead_id")) if custom_params.get("lead_id") else ws_lead_id
                campaign_id = int(custom_params.get("campaign_id")) if custom_params.get("campaign_id") else None
                customer_name = custom_params.get("customer_name") or ""

                # Check format to confirm Exotel vs Twilio
                media_format = start_data.get("media_format") or start_data.get("mediaFormat") or {}
                encoding = str(media_format.get("encoding", "")).lower()
                fmt = str(media_format.get("format", "")).lower()
                if "raw" in encoding or "s16le" in fmt or "stream_sid" in msg or provider_hint == "exotel":
                    is_exotel = True
                else:
                    is_exotel = False

                # Extract caller phone number from Exotel / Twilio / query params
                caller_phone = (
                    start_data.get("from")
                    or start_data.get("From")
                    or start_data.get("call_from")
                    or start_data.get("CallFrom")
                    or custom_params.get("caller")
                    or custom_params.get("from")
                    or custom_params.get("From")
                    or ws_caller
                    or ""
                )
                if caller_phone:
                    try:
                        caller_phone = validate_phone_number(caller_phone)
                    except Exception:
                        pass

                # Determine direction: Inbound vs Outbound
                direction_str = (
                    start_data.get("direction")
                    or custom_params.get("direction")
                    or ws_direction
                    or ""
                ).lower()

                matched_call = None
                if call_sid:
                    calls = get_outbound_calls()
                    matched = [c for c in calls if c.provider_call_id == call_sid]
                    if matched:
                        matched_call = matched[0]
                        if not lead_id:
                            lead_id = matched_call.lead_id
                            campaign_id = matched_call.campaign_id or campaign_id
                        if not caller_phone and matched_call.phone_number:
                            caller_phone = matched_call.phone_number

                is_inbound = (
                    direction_str in ("inbound", "incoming")
                    or (matched_call is not None and matched_call.message and "inbound" in matched_call.message.lower())
                    or (matched_call is None and not campaign_id)
                )

                # For inbound calls, resolve or create the lead in CRM
                if is_inbound:
                    if caller_phone:
                        existing_lead = get_lead_by_phone(caller_phone)
                        if existing_lead:
                            lead_id = existing_lead.id
                            if not customer_name or customer_name == "there":
                                customer_name = existing_lead.name
                        elif not lead_id:
                            clean_suffix = caller_phone[-4:] if len(caller_phone) >= 4 else "New"
                            new_lead = create_or_update_lead(
                                name=customer_name if customer_name and customer_name != "there" else f"Inbound Caller ({clean_suffix})",
                                phone_number=caller_phone,
                                interest_status="Inquiry",
                                summary="Incoming telephone enquiry",
                            )
                            lead_id = new_lead.id
                            customer_name = new_lead.name
                    elif not lead_id:
                        new_lead = create_or_update_lead(
                            name="Inbound Caller",
                            phone_number=f"+910000{uuid4().hex[:6]}",
                            interest_status="Inquiry",
                            summary="Incoming telephone enquiry (Caller ID hidden)",
                        )
                        lead_id = new_lead.id
                        customer_name = new_lead.name

                    if not matched_call:
                        save_outbound_call(
                            lead_id=lead_id,
                            phone_number=caller_phone or "unknown",
                            provider_call_id=call_sid,
                            status="in_progress",
                            message=f"Inbound call from {caller_phone or 'caller'}",
                            provider="exotel" if is_exotel else "twilio",
                            campaign_id=campaign_id,
                        )

                if call_sid:
                    update_outbound_call_status(call_sid, "in_progress")

                # Initialize AI conversation session
                session = conversation_manager.get_or_create_session(
                    session_id=session_id,
                    lead_id=lead_id,
                    customer_name=customer_name or "there",
                )
                opening = conversation_manager.generate_opening_greeting(session, is_inbound=is_inbound)
                transcript_parts.append(f"Agent: {opening}")

                # Synthesize and send opening greeting to caller
                if is_exotel:
                    opening_pcm = await _synthesize_audio_pcm(opening, session.language, sample_rate=8000)
                    if opening_pcm and stream_sid:
                        # Stream in 100ms chunks (1600 bytes at 8kHz 16-bit mono)
                        for i in range(0, len(opening_pcm), 1600):
                            chunk = opening_pcm[i:i + 1600]
                            await websocket.send_json({
                                "event": "media",
                                "stream_sid": stream_sid,
                                "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                            })
                            await asyncio.sleep(0.01)
                else:
                    opening_mulaw = await _synthesize_audio_mulaw(opening, session.language)
                    if opening_mulaw and stream_sid:
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": opening_mulaw},
                        })

            elif event == "media":
                media_data = msg.get("media", {})
                payload = media_data.get("payload", "")
                if not payload:
                    continue

                try:
                    raw_bytes = base64.b64decode(payload)
                except Exception:
                    continue

                # Convert incoming chunk to 16kHz linear PCM for Sarvam Saaras STT
                if is_exotel:
                    # Exotel streams raw 16-bit linear PCM (s16le) at 8kHz
                    pcm_16k_chunk = _resample_pcm_8k_to_16k(raw_bytes)
                else:
                    # Twilio streams 8kHz mulaw
                    pcm_16k_chunk = _mulaw_to_pcm16k(raw_bytes)

                # Voice Activity Detection (RMS energy calculation)
                rms = _calculate_pcm_rms(pcm_16k_chunk)

                if rms > 300.0:
                    # Caller is speaking! Barge-in / interruption: flush unplayed bot audio
                    if stream_sid and len(speech_buffer) == 0:
                        sid_key = "stream_sid" if is_exotel else "streamSid"
                        await websocket.send_json({"event": "clear", sid_key: stream_sid})

                    speech_buffer.extend(pcm_16k_chunk)
                    silence_frames = 0
                else:
                    # Silence detected
                    if len(speech_buffer) >= 6400:  # ~200ms of user speech already collected
                        silence_frames += 1
                        # If silence persists for ~400ms (approx 4 chunks), user finished their thought
                        if silence_frames >= 4:
                            buffered_pcm = bytes(speech_buffer)
                            speech_buffer.clear()
                            silence_frames = 0

                            session = conversation_manager.get_or_create_session(session_id)
                            transcribed, _ = await _transcribe_pcm(buffered_pcm, session.language)

                            if transcribed and len(transcribed.strip()) >= 2:
                                transcript_parts.append(f"Customer: {transcribed}")

                                # Process turn through conversation engine
                                reply_text, intent, facts = conversation_manager.process_turn(session_id, transcribed)
                                transcript_parts.append(f"Agent: {reply_text}")

                                # Synthesize and stream AI voice response
                                if is_exotel:
                                    reply_pcm = await _synthesize_audio_pcm(reply_text, session.language, sample_rate=8000)
                                    if reply_pcm and stream_sid:
                                        for i in range(0, len(reply_pcm), 1600):
                                            chunk = reply_pcm[i:i + 1600]
                                            await websocket.send_json({
                                                "event": "media",
                                                "stream_sid": stream_sid,
                                                "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                                            })
                                            await asyncio.sleep(0.01)
                                else:
                                    reply_mulaw = await _synthesize_audio_mulaw(reply_text, session.language)
                                    if reply_mulaw and stream_sid:
                                        await websocket.send_json({
                                            "event": "media",
                                            "streamSid": stream_sid,
                                            "media": {"payload": reply_mulaw},
                                        })

            elif event == "stop":
                logger.info(f"Telephony stream ended for CallSid: {call_sid}")
                if call_sid:
                    duration = int((datetime.now(timezone.utc) - start_time).total_seconds())
                    update_outbound_call_status(call_sid, "completed", duration_seconds=duration)
                break

    except WebSocketDisconnect:
        logger.info(f"Telephony stream WebSocket disconnected (CallSid: {call_sid})")
    except Exception as e:
        logger.exception(f"Telephony stream processing error: {e}")
    finally:
        duration = int((datetime.now(timezone.utc) - start_time).total_seconds())
        if call_sid:
            update_outbound_call_status(call_sid, "completed", duration_seconds=duration)

        # Save transcript & post-call intelligence
        if transcript_parts:
            full_transcript = chr(10).join(transcript_parts)
            analysis = analyze_conversation(full_transcript, customer_name)

            target_phone = caller_phone
            if not target_phone and lead_id:
                lead_obj = get_lead_by_id(lead_id)
                if lead_obj and lead_obj.phone_number:
                    target_phone = lead_obj.phone_number

            if lead_id and target_phone:
                create_or_update_lead(
                    name=customer_name if customer_name and customer_name != "there" else f"Caller ({target_phone[-4:] if len(target_phone) >= 4 else 'New'})",
                    phone_number=target_phone,
                    interest_status=analysis["category"],
                    score=analysis["score"],
                    summary=analysis["summary"],
                    extracted_requirements=analysis["requirements"],
                    evidence=analysis["evidence"],
                    next_action=analysis["next_action"],
                    campaign_id=campaign_id,
                )
            if lead_id:
                save_call(
                    lead_id=lead_id,
                    transcript=full_transcript,
                    agent_response=analysis["next_action"],
                    interest_status=analysis["category"],
                    campaign_id=campaign_id,
                    call_mode="telephony_inbound" if is_inbound else "telephony_live",
                    call_duration_seconds=duration,
                )
                if analysis["requirements"].get("site_visit_interest"):
                    validate_and_book_appointment(
                        lead_id=lead_id,
                        requested_date_raw=analysis["requirements"].get("preferred_meeting_date", "Saturday"),
                        requested_time_raw=analysis["requirements"].get("preferred_meeting_time", "11:00 AM"),
                        campaign_id=campaign_id,
                    )
                if analysis["category"] == "Do Not Call":
                    if target_phone:
                        add_dnd_entry(target_phone, f"Customer opt-out in call {call_sid}")


@app.websocket("/ws/telephony/exotel/stream")
async def exotel_telephony_media_stream(websocket: WebSocket) -> None:
    """Dedicated Exotel AgentStream WebSocket endpoint for real-time 16-bit linear PCM audio."""
    await _handle_telephony_media_stream(websocket, provider_hint="exotel")


@app.websocket("/ws/telephony/stream")
async def telephony_media_stream(websocket: WebSocket) -> None:
    """Dual-carrier WebSocket audio stream supporting Exotel AgentStream and Twilio Media Streams."""
    await _handle_telephony_media_stream(websocket, provider_hint="auto")

