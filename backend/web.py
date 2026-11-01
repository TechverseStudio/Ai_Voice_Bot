
def _wav_to_mulaw_payload(wav_bytes: bytes) -> str:
    """Convert WAV audio bytes (16-bit PCM) into 8kHz mulaw base64 for telephony streaming."""
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
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        return pcm_16k
    except Exception as e:
        logger.warning(f"Mulaw to PCM conversion failed: {e}")
        return b""


async def _synthesize_audio(text: str, language: str = "en-IN") -> bytes:
    """Synthesize text to WAV audio using Sarvam TTS."""
    def run_synth() -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            path = tf.name
        try:
            tts.synthesize(text, language, path)
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"TTS synthesis exception: {e}")
            return b""
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
    return await asyncio.to_thread(run_synth)


async def _transcribe_pcm(pcm_16k: bytes) -> str:
    """Transcribe 16kHz linear PCM audio buffer."""
    def run_stt() -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            path = tf.name
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm_16k)
            result = stt.transcribe(path)
            return result.get("text", "")
        except Exception as e:
            logger.warning(f"STT transcribe exception: {e}")
            return ""
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
    return await asyncio.to_thread(run_stt)

import audioop
import io
import wave
from fastapi import Request
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

"""FastAPI application for AI Autonomous Lead Generation Engine."""

import asyncio
import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
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
    create_lead,
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


@app.websocket("/ws/telephony/stream")
async def telephony_media_stream(websocket: WebSocket) -> None:
    """Bidirectional WebSocket audio stream for live telephony calls (Twilio / Exotel Stream)."""
    await websocket.accept()
    stream_sid = None
    call_sid = None
    lead_id = None
    campaign_id = None
    customer_name = "there"
    session_id = str(uuid4())
    transcript_parts: list[str] = []
    audio_buffer = bytearray()

    try:
        async for message_text in websocket.iter_text():
            msg = json.loads(message_text)
            event = msg.get("event")

            if event == "connected":
                logger.info("Telephony audio stream connected")

            elif event == "start":
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid")
                custom_params = start_data.get("customParameters", {})
                lead_id = int(custom_params.get("lead_id")) if custom_params.get("lead_id") else None
                campaign_id = int(custom_params.get("campaign_id")) if custom_params.get("campaign_id") else None
                customer_name = custom_params.get("customer_name") or "there"

                if call_sid:
                    update_outbound_call_status(call_sid, "in_progress")

                # Initialize AI conversation session
                session = conversation_manager.get_or_create_session(
                    session_id=session_id,
                    lead_id=lead_id,
                    customer_name=customer_name,
                )
                opening = conversation_manager.generate_opening_greeting(session)
                transcript_parts.append(f"Agent: {opening}")

                # Send AI opening greeting as audio to caller!
                audio_wav = await _synthesize_audio(opening, session.language)
                if audio_wav and stream_sid:
                    mulaw_payload = _wav_to_mulaw_payload(audio_wav)
                    if mulaw_payload:
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": mulaw_payload},
                        })

            elif event == "media":
                media_data = msg.get("media", {})
                payload = media_data.get("payload", "")
                if payload:
                    try:
                        mulaw_bytes = base64.b64decode(payload)
                        audio_buffer.extend(mulaw_bytes)
                    except Exception:
                        pass

                    # Process audio buffer chunks (~1.5s of speech = 12000 bytes at 8kHz)
                    if len(audio_buffer) >= 12000:
                        pcm_16k = _mulaw_to_pcm16k(bytes(audio_buffer))
                        audio_buffer.clear()

                        transcribed = await _transcribe_pcm(pcm_16k)
                        if transcribed and len(transcribed.strip()) >= 2:
                            transcript_parts.append(f"Customer: {transcribed}")

                            # Interruption handling: clear phone playback buffer
                            if stream_sid:
                                await websocket.send_json({"event": "clear", "streamSid": stream_sid})

                            # Generate intelligent AI response in customer's language
                            session = conversation_manager.get_or_create_session(session_id)
                            reply_text, intent, facts = conversation_manager.process_turn(session_id, transcribed)
                            transcript_parts.append(f"Agent: {reply_text}")

                            # Synthesize and stream AI voice response to the caller
                            reply_wav = await _synthesize_audio(reply_text, session.language)
                            if reply_wav and stream_sid:
                                mulaw_resp = _wav_to_mulaw_payload(reply_wav)
                                if mulaw_resp:
                                    await websocket.send_json({
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": mulaw_resp},
                                    })

            elif event == "stop":
                logger.info(f"Telephony stream ended for CallSid: {call_sid}")
                if call_sid:
                    update_outbound_call_status(call_sid, "completed")
                break

    except WebSocketDisconnect:
        logger.info("Telephony stream WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Telephony stream error: {e}")
    finally:
        # Save transcript & post-call intelligence
        if transcript_parts and lead_id:
            full_transcript = chr(10).join(transcript_parts)
            analysis = analyze_conversation(full_transcript, customer_name)
            create_or_update_lead(
                name=customer_name,
                phone_number="",
                interest_status=analysis["category"],
                score=analysis["score"],
                summary=analysis["summary"],
                extracted_requirements=analysis["requirements"],
                evidence=analysis["evidence"],
                next_action=analysis["next_action"],
                campaign_id=campaign_id,
            )
            save_call(
                lead_id=lead_id,
                transcript=full_transcript,
                agent_response=analysis["next_action"],
                interest_status=analysis["category"],
                campaign_id=campaign_id,
                call_mode="telephony_live",
            )
            if analysis["requirements"].get("site_visit_interest"):
                validate_and_book_appointment(
                    lead_id=lead_id,
                    requested_date_raw=analysis["requirements"].get("preferred_meeting_date", "Saturday"),
                    requested_time_raw=analysis["requirements"].get("preferred_meeting_time", "11:00 AM"),
                    campaign_id=campaign_id,
                )
