"""Database models and persistence layer for AI Autonomous Lead Generation Engine."""

from ast import literal_eval
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
    update,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(30))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    review_needed_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="preview")  # preview, approved, discarded
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    phone_number: Mapped[str] = mapped_column(String(40), index=True)
    raw_phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    locality: Mapped[str] = mapped_column(String(120), default="")
    budget: Mapped[str] = mapped_column(String(60), default="")
    bhk: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    validation_status: Mapped[str] = mapped_column(
        String(40), default="valid"
    )  # valid, duplicate, invalid, review_needed, opted_out
    validation_message: Mapped[str] = mapped_column(String(255), default="")
    is_dnd: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    project_name: Mapped[str] = mapped_column(String(150), default="Krishna's AI Property - Wakad")
    objective: Mapped[str] = mapped_column(
        String(255), default="New Launch Awareness & Lead Qualification"
    )
    batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_name: Mapped[str] = mapped_column(
        String(100), default="Priya - Residential Advisory Executive"
    )
    language: Mapped[str] = mapped_column(String(40), default="en-IN")
    window_start: Mapped[str] = mapped_column(String(10), default="09:30")
    window_end: Mapped[str] = mapped_column(String(10), default="19:30")
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    retry_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    assigned_sales_team: Mapped[str] = mapped_column(String(120), default="Wakad Sales Desk")
    follow_up_policy: Mapped[str] = mapped_column(
        String(255), default="Immediate CRM alert & site visit slot reservation"
    )
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(
        String(30), default="draft"
    )  # draft, approved, running, paused, completed, cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    contact_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    phone_number: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str] = mapped_column(String(120), default="")
    locality: Mapped[str] = mapped_column(String(120), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(
        String(40), default="pending"
    )  # pending, calling, completed, failed, dnd_blocked, no_answer, busy, retry_scheduled
    call_outcome: Mapped[str] = mapped_column(String(50), default="")
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    call_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    phone_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120), default="")
    area: Mapped[str] = mapped_column(String(120), default="")
    budget: Mapped[str] = mapped_column(String(60), default="")
    bhk: Mapped[str] = mapped_column(String(60), default="")
    purpose: Mapped[str] = mapped_column(String(60), default="")  # self-use, investment
    timeline: Mapped[str] = mapped_column(String(60), default="")
    financing: Mapped[str] = mapped_column(String(60), default="")
    amenities: Mapped[str] = mapped_column(String(255), default="")
    site_visit_interest: Mapped[bool] = mapped_column(Boolean, default=False)
    interest_status: Mapped[str] = mapped_column(
        String(50), default="unknown"
    )  # Hot, Warm, Cold, Not Interested, Callback Requested, Do Not Call, No Answer, Busy
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_breakdown: Mapped[str] = mapped_column(Text, default="{}")
    summary: Mapped[str] = mapped_column(Text, default="")
    extracted_requirements: Mapped[str] = mapped_column(Text, default="{}")
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    next_action: Mapped[str] = mapped_column(Text, default="")
    assigned_salesperson: Mapped[str] = mapped_column(String(120), default="Rohit Verma (Wakad Sales Desk)")
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CallSummary(Base):
    __tablename__ = "call_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str] = mapped_column(String(80), default="")
    call_mode: Mapped[str] = mapped_column(String(30), default="telephony_simulated")  # browser_demo, telephony_simulated, telephony_live
    transcript: Mapped[str] = mapped_column(Text, default="")
    agent_response: Mapped[str] = mapped_column(Text, default="")
    interest_status: Mapped[str] = mapped_column(String(50), default="unknown")
    objections: Mapped[str] = mapped_column(Text, default="")
    questions_asked: Mapped[str] = mapped_column(Text, default="")
    call_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class OutboundCall(Base):
    __tablename__ = "outbound_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    phone_number: Mapped[str] = mapped_column(String(40))
    provider_call_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_status: Mapped[str] = mapped_column(String(40), default="initiated")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    recording_url: Mapped[str] = mapped_column(String(255), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class BrowserSession(Base):
    __tablename__ = "browser_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    transcript: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_category: Mapped[str] = mapped_column(String(30), default="Insufficient Data")
    follow_up: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_name: Mapped[str] = mapped_column(String(150), default="Krishna's AI Property - Wakad")
    meeting_type: Mapped[str] = mapped_column(
        String(50), default="Site Visit"
    )  # Site Visit, Office Meeting, Video Consultation
    requested_date: Mapped[str] = mapped_column(String(30))
    requested_time: Mapped[str] = mapped_column(String(30))
    confirmed_date_time: Mapped[str | None] = mapped_column(String(60), nullable=True)
    assigned_salesperson: Mapped[str] = mapped_column(
        String(120), default="Rohit Verma (Senior Property Specialist)"
    )
    status: Mapped[str] = mapped_column(
        String(30), default="confirmed"
    )  # confirmed, pending, rescheduled, cancelled, completed
    customer_notes: Mapped[str] = mapped_column(Text, default="")
    confirmation_code: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(80))  # e.g., CAMPAIGN_LAUNCHED, DND_REGISTERED
    entity_type: Mapped[str] = mapped_column(String(50))  # Campaign, Contact, Lead, Call
    entity_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class DndEntry(Base):
    __tablename__ = "dnd_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(150), default="Customer opted out during AI call")
    source: Mapped[str] = mapped_column(String(50), default="customer_request")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def create_tables() -> None:
    Base.metadata.create_all(engine)
    if str(engine.url).startswith('sqlite'):
        import sqlite3
        db_path = str(engine.url).replace('sqlite:///', '')
        if db_path and Path(db_path).exists():
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            def get_cols(table):
                cur.execute(f'PRAGMA table_info({table})')
                return {row[1] for row in cur.fetchall()}
            try:
                lead_cols = get_cols('leads')
                leads_to_add = [
                    ('contact_id', 'INTEGER'),
                    ('campaign_id', 'INTEGER'),
                    ('email', 'VARCHAR(120) DEFAULT ""'),
                    ('budget', 'VARCHAR(60) DEFAULT ""'),
                    ('bhk', 'VARCHAR(60) DEFAULT ""'),
                    ('purpose', 'VARCHAR(60) DEFAULT ""'),
                    ('timeline', 'VARCHAR(60) DEFAULT ""'),
                    ('financing', 'VARCHAR(60) DEFAULT ""'),
                    ('amenities', 'VARCHAR(255) DEFAULT ""'),
                    ('site_visit_interest', 'BOOLEAN DEFAULT 0'),
                    ('score', 'INTEGER'),
                    ('score_breakdown', 'TEXT DEFAULT "{}"'),
                    ('extracted_requirements', 'TEXT DEFAULT "{}"'),
                    ('evidence', 'TEXT DEFAULT "{}"'),
                    ('next_action', 'TEXT DEFAULT ""'),
                    ('assigned_salesperson', 'VARCHAR(120) DEFAULT "Rohit Verma (Wakad Sales Desk)"'),
                    ('created_at', 'DATETIME'),
                ]
                for col, col_type in leads_to_add:
                    if col not in lead_cols:
                        cur.execute(f'ALTER TABLE leads ADD COLUMN {col} {col_type}')
                
                call_cols = get_cols('call_summaries')
                calls_to_add = [
                    ('campaign_id', 'INTEGER'),
                    ('session_id', 'VARCHAR(80) DEFAULT ""'),
                    ('call_mode', 'VARCHAR(30) DEFAULT "telephony_simulated"'),
                    ('objections', 'TEXT DEFAULT ""'),
                    ('questions_asked', 'TEXT DEFAULT ""'),
                    ('call_duration_seconds', 'INTEGER DEFAULT 0'),
                ]
                for col, col_type in calls_to_add:
                    if col not in call_cols:
                        cur.execute(f'ALTER TABLE call_summaries ADD COLUMN {col} {col_type}')
                
                outbound_cols = get_cols('outbound_calls')
                outbound_to_add = [
                    ('provider', 'VARCHAR(40) DEFAULT "mock"'),
                    ('campaign_id', 'INTEGER'),
                    ('call_status', 'VARCHAR(40) DEFAULT "initiated"'),
                    ('duration_seconds', 'INTEGER DEFAULT 0'),
                    ('recording_url', 'VARCHAR(255) DEFAULT ""'),
                    ('error_message', 'TEXT DEFAULT ""'),
                    ('answered_at', 'DATETIME'),
                    ('ended_at', 'DATETIME'),
                ]
                for col, col_type in outbound_to_add:
                    if col not in outbound_cols:
                        cur.execute(f'ALTER TABLE outbound_calls ADD COLUMN {col} {col_type}')
                con.commit()
            except Exception:
                pass
            finally:
                con.close()



def log_audit(action: str, entity_type: str, entity_id: str, details: str = "") -> None:
    with SessionLocal() as session:
        log = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
        )
        session.add(log)
        session.commit()


# --- Contact & Import Batch Helpers ---

def create_import_batch(
    filename: str,
    file_type: str,
    total_rows: int,
    valid_rows: int,
    duplicate_rows: int,
    invalid_rows: int,
    review_needed_rows: int,
    status: str = "preview",
) -> ImportBatch:
    with SessionLocal() as session:
        batch = ImportBatch(
            filename=filename,
            file_type=file_type,
            total_rows=total_rows,
            valid_rows=valid_rows,
            duplicate_rows=duplicate_rows,
            invalid_rows=invalid_rows,
            review_needed_rows=review_needed_rows,
            status=status,
        )
        session.add(batch)
        session.commit()
        session.refresh(batch)
        log_audit("IMPORT_BATCH_CREATED", "ImportBatch", str(batch.id), f"File: {filename}, Total: {total_rows}")
        return batch


def get_import_batches() -> list[ImportBatch]:
    with SessionLocal() as session:
        return list(session.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())))


def get_contacts(batch_id: int | None = None) -> list[Contact]:
    with SessionLocal() as session:
        stmt = select(Contact)
        if batch_id is not None:
            stmt = stmt.where(Contact.batch_id == batch_id)
        return list(session.scalars(stmt.order_by(Contact.id.asc())))


def save_contacts(contacts_data: list[dict[str, Any]], batch_id: int) -> list[Contact]:
    created = []
    with SessionLocal() as session:
        for item in contacts_data:
            contact = Contact(
                batch_id=batch_id,
                name=item.get("name", "").strip(),
                phone_number=item.get("phone_number", "").strip(),
                raw_phone=item.get("raw_phone", "").strip(),
                email=item.get("email", "").strip(),
                locality=item.get("locality", "").strip(),
                budget=item.get("budget", "").strip(),
                bhk=item.get("bhk", "").strip(),
                notes=item.get("notes", "").strip(),
                validation_status=item.get("validation_status", "valid"),
                validation_message=item.get("validation_message", ""),
                is_dnd=item.get("is_dnd", False),
            )
            session.add(contact)
            created.append(contact)
        session.commit()
        for contact in created:
            session.refresh(contact)
    return created


def update_contact(contact_id: int, updates: dict[str, Any]) -> Contact:
    with SessionLocal() as session:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise ValueError(f"Contact {contact_id} not found")
        for key, value in updates.items():
            if hasattr(contact, key):
                setattr(contact, key, value)
        session.commit()
        session.refresh(contact)
        return contact


# --- Campaign Helpers ---

def create_campaign(
    name: str,
    project_name: str,
    objective: str,
    batch_id: int | None,
    agent_name: str,
    language: str,
    window_start: str,
    window_end: str,
    max_attempts: int,
    retry_interval_minutes: int,
    assigned_sales_team: str,
    follow_up_policy: str,
    concurrency_limit: int = 2,
    contact_ids: list[int] | None = None,
) -> Campaign:
    with SessionLocal() as session:
        campaign = Campaign(
            name=name,
            project_name=project_name,
            objective=objective,
            batch_id=batch_id,
            agent_name=agent_name,
            language=language,
            window_start=window_start,
            window_end=window_end,
            max_attempts=max_attempts,
            retry_interval_minutes=retry_interval_minutes,
            assigned_sales_team=assigned_sales_team,
            follow_up_policy=follow_up_policy,
            concurrency_limit=concurrency_limit,
            status="draft",
        )
        session.add(campaign)
        session.commit()
        session.refresh(campaign)

        # Attach contacts if supplied or fetch from batch
        if contact_ids:
            contacts = list(session.scalars(select(Contact).where(Contact.id.in_(contact_ids))))
        elif batch_id:
            contacts = list(
                session.scalars(
                    select(Contact).where(
                        Contact.batch_id == batch_id,
                        Contact.validation_status.in_(("valid", "approved")),
                        Contact.is_dnd == False,
                    )
                )
            )
        else:
            contacts = []

        for c in contacts:
            cc = CampaignContact(
                campaign_id=campaign.id,
                contact_id=c.id,
                name=c.name,
                phone_number=c.phone_number,
                email=c.email,
                locality=c.locality,
                max_attempts=max_attempts,
                status="pending",
            )
            session.add(cc)
        session.commit()
        log_audit("CAMPAIGN_CREATED", "Campaign", str(campaign.id), f"Name: {name}, Contacts: {len(contacts)}")
        return campaign


def get_campaigns() -> list[Campaign]:
    with SessionLocal() as session:
        return list(session.scalars(select(Campaign).order_by(Campaign.created_at.desc())))


def get_campaign(campaign_id: int) -> Campaign | None:
    with SessionLocal() as session:
        return session.get(Campaign, campaign_id)


def update_campaign_status(campaign_id: int, status: str) -> Campaign:
    with SessionLocal() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")
        campaign.status = status
        if status == "approved" and not campaign.approved_at:
            campaign.approved_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(campaign)
        log_audit(f"CAMPAIGN_STATUS_{status.upper()}", "Campaign", str(campaign_id), f"Status set to {status}")
        return campaign


def get_campaign_contacts(campaign_id: int) -> list[CampaignContact]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(CampaignContact).where(CampaignContact.campaign_id == campaign_id).order_by(CampaignContact.id.asc())
            )
        )


def update_campaign_contact_status(
    cc_id: int,
    status: str,
    outcome: str = "",
    session_id: str | None = None,
    lead_id: int | None = None,
    next_retry: datetime | None = None,
) -> None:
    with SessionLocal() as session:
        cc = session.get(CampaignContact, cc_id)
        if cc:
            cc.status = status
            cc.attempts += 1
            cc.last_call_at = datetime.now(timezone.utc)
            if outcome:
                cc.call_outcome = outcome
            if session_id:
                cc.call_session_id = session_id
            if lead_id:
                cc.lead_id = lead_id
            if next_retry:
                cc.next_retry_at = next_retry
            session.commit()


# --- Lead & CRM Helpers ---

def get_leads() -> list[Lead]:
    with SessionLocal() as session:
        return list(session.scalars(select(Lead).order_by(Lead.updated_at.desc())))


def get_lead_by_id(lead_id: int) -> Lead | None:
    with SessionLocal() as session:
        return session.get(Lead, lead_id)


def get_lead_by_phone(phone_number: str) -> Lead | None:
    with SessionLocal() as session:
        return session.scalar(select(Lead).where(Lead.phone_number == phone_number))


def create_or_update_lead(
    name: str,
    phone_number: str,
    area: str = "",
    budget: str = "",
    bhk: str = "",
    purpose: str = "",
    timeline: str = "",
    financing: str = "",
    amenities: str = "",
    site_visit_interest: bool = False,
    interest_status: str = "Warm",
    score: int | None = None,
    score_breakdown: dict | None = None,
    summary: str = "",
    extracted_requirements: dict | None = None,
    evidence: dict | None = None,
    next_action: str = "",
    assigned_salesperson: str = "Rohit Verma (Wakad Sales Desk)",
    campaign_id: int | None = None,
    contact_id: int | None = None,
    opt_out: bool = False,
) -> Lead:
    with SessionLocal() as session:
        lead = session.scalar(select(Lead).where(Lead.phone_number == phone_number))
        if lead is None:
            lead = Lead(
                name=name,
                phone_number=phone_number,
                area=area,
                budget=budget,
                bhk=bhk,
                purpose=purpose,
                timeline=timeline,
                financing=financing,
                amenities=amenities,
                site_visit_interest=site_visit_interest,
                interest_status=interest_status,
                score=score,
                score_breakdown=json.dumps(score_breakdown or {}),
                summary=summary,
                extracted_requirements=json.dumps(extracted_requirements or {}),
                evidence=json.dumps(evidence or {}),
                next_action=next_action,
                assigned_salesperson=assigned_salesperson,
                campaign_id=campaign_id,
                contact_id=contact_id,
                opt_out=opt_out,
            )
            session.add(lead)
        else:
            if name:
                lead.name = name
            if area:
                lead.area = area
            if budget:
                lead.budget = budget
            if bhk:
                lead.bhk = bhk
            if purpose:
                lead.purpose = purpose
            if timeline:
                lead.timeline = timeline
            if financing:
                lead.financing = financing
            if amenities:
                lead.amenities = amenities
            lead.site_visit_interest = site_visit_interest or lead.site_visit_interest
            lead.interest_status = interest_status
            if score is not None:
                lead.score = score
            if score_breakdown:
                lead.score_breakdown = json.dumps(score_breakdown)
            if summary:
                lead.summary = summary
            if extracted_requirements:
                lead.extracted_requirements = json.dumps(extracted_requirements)
            if evidence:
                lead.evidence = json.dumps(evidence)
            if next_action:
                lead.next_action = next_action
            if assigned_salesperson:
                lead.assigned_salesperson = assigned_salesperson
            if opt_out:
                lead.opt_out = True
            lead.updated_at = datetime.now(timezone.utc)

        session.commit()
        session.refresh(lead)
        log_audit("LEAD_SAVED", "Lead", str(lead.id), f"Status: {interest_status}, Score: {score}")
        return lead


def create_lead(name: str, area: str, phone_number: str) -> Lead:
    return create_or_update_lead(name=name, phone_number=phone_number, area=area)


def save_call(
    lead_id: int,
    transcript: str,
    agent_response: str,
    interest_status: str,
    campaign_id: int | None = None,
    session_id: str = "",
    call_mode: str = "telephony_simulated",
    objections: str = "",
    questions_asked: str = "",
    call_duration_seconds: int = 0,
) -> CallSummary:
    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} was not found")
        lead.interest_status = interest_status
        lead.summary = f"Latest call ({interest_status}): {transcript[:120]}..."
        if interest_status == "do_not_call" or interest_status == "Do Not Call":
            lead.opt_out = True
            add_dnd_entry(lead.phone_number, "Customer requested DND during call", "ai_call")
        
        call_item = CallSummary(
            lead_id=lead_id,
            campaign_id=campaign_id,
            session_id=session_id,
            call_mode=call_mode,
            transcript=transcript,
            agent_response=agent_response,
            interest_status=interest_status,
            objections=objections,
            questions_asked=questions_asked,
            call_duration_seconds=call_duration_seconds,
        )
        session.add(call_item)
        session.commit()
        session.refresh(call_item)
        return call_item


def save_outbound_call(
    lead_id: int | None,
    phone_number: str,
    provider_call_id: str,
    status: str,
    message: str = "",
    provider: str = "mock",
    campaign_id: int | None = None,
) -> OutboundCall:
    with SessionLocal() as session:
        call = OutboundCall(
            lead_id=lead_id if lead_id is not None else 0,
            phone_number=phone_number,
            provider_call_id=provider_call_id,
            status=status,
            message=message,
            provider=provider,
            campaign_id=campaign_id,
            call_status=status,
        )
        session.add(call)
        session.commit()
        session.refresh(call)
        log_audit("CALL_INITIATED", "OutboundCall", str(call.id), f"Provider: {provider}, CallSid: {provider_call_id}")
        return call


def update_outbound_call_status(
    provider_call_id: str,
    status: str,
    duration_seconds: int = 0,
    recording_url: str = "",
    error_message: str = "",
) -> OutboundCall | None:
    with SessionLocal() as session:
        call = session.scalar(select(OutboundCall).where(OutboundCall.provider_call_id == provider_call_id))
        if not call:
            return None
        call.call_status = status
        call.status = status
        if duration_seconds:
            call.duration_seconds = duration_seconds
        if recording_url:
            call.recording_url = recording_url
        if error_message:
            call.error_message = error_message
        if status in ("answered", "in_progress") and not call.answered_at:
            call.answered_at = datetime.now(timezone.utc)
        if status in ("completed", "failed", "busy", "no_answer"):
            call.ended_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(call)
        log_audit(f"CALL_STATUS_{status.upper()}", "OutboundCall", str(call.id), f"CallSid: {provider_call_id}, Duration: {duration_seconds}s")
        return call


def get_outbound_calls(campaign_id: int | None = None, lead_id: int | None = None) -> list[OutboundCall]:
    with SessionLocal() as session:
        stmt = select(OutboundCall)
        if campaign_id is not None:
            stmt = stmt.where(OutboundCall.campaign_id == campaign_id)
        if lead_id is not None:
            stmt = stmt.where(OutboundCall.lead_id == lead_id)
        return list(session.scalars(stmt.order_by(OutboundCall.created_at.desc())))


# --- Browser Sessions ---

def create_browser_session(lead_id: int) -> BrowserSession:
    with SessionLocal() as session:
        item = BrowserSession(session_id=str(uuid4()), lead_id=lead_id)
        item.status = "connecting"
        session.add(item)
        session.commit()
        session.refresh(item)
        return item


def update_browser_session_status(
    session_id: str,
    status: str,
    message: str = "",
) -> BrowserSession:
    with SessionLocal() as session:
        item = session.scalar(
            select(BrowserSession).where(BrowserSession.session_id == session_id)
        )
        if item is None:
            raise ValueError(f"Browser session {session_id} was not found")
        item.status = status
        if message:
            item.follow_up = message
        if status in {"failed", "cancelled"}:
            item.ended_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(item)
        return item


def finish_browser_session(
    session_id: str,
    status: str,
    transcript: str,
    summary: str,
    requirements: str,
    score: int | None,
    score_category: str,
    follow_up: str,
) -> BrowserSession:
    with SessionLocal() as session:
        item = session.scalar(
            select(BrowserSession).where(BrowserSession.session_id == session_id)
        )
        if item is None:
            raise ValueError(f"Browser session {session_id} was not found")
        item.status = status
        item.transcript = transcript
        item.summary = summary
        item.requirements = requirements
        item.score = score
        item.score_category = score_category
        item.follow_up = follow_up
        item.ended_at = datetime.now(timezone.utc)
        
        lead = session.get(Lead, item.lead_id)
        if lead is not None and transcript:
            lead.summary = summary
            lead.score = score
            lead.interest_status = score_category
            try:
                extracted = json.loads(requirements) if isinstance(requirements, str) and requirements.startswith("{") else literal_eval(requirements)
            except Exception:
                extracted = {}
            if not lead.name and extracted.get("name"):
                lead.name = extracted["name"]
            if not lead.area and extracted.get("location"):
                lead.area = extracted["location"]
            if extracted.get("bhk"):
                lead.bhk = str(extracted["bhk"])
            if extracted.get("budget"):
                lead.budget = str(extracted["budget"])
            if extracted.get("site_visit"):
                lead.site_visit_interest = True
        session.commit()
        session.refresh(item)
        return item


def get_browser_sessions() -> list[BrowserSession]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(BrowserSession).order_by(BrowserSession.started_at.desc())
            )
        )


# --- Appointment Scheduling Helpers ---

def create_appointment(
    lead_id: int,
    requested_date: str,
    requested_time: str,
    project_name: str = "Krishna's AI Property - Wakad",
    meeting_type: str = "Site Visit",
    assigned_salesperson: str = "Rohit Verma (Senior Property Specialist)",
    customer_notes: str = "",
    status: str = "confirmed",
    campaign_id: int | None = None,
) -> Appointment:
    confirmation_code = f"VISIT-{uuid4().hex[:6].upper()}"
    with SessionLocal() as session:
        appt = Appointment(
            lead_id=lead_id,
            campaign_id=campaign_id,
            project_name=project_name,
            meeting_type=meeting_type,
            requested_date=requested_date,
            requested_time=requested_time,
            confirmed_date_time=f"{requested_date} at {requested_time}" if status == "confirmed" else None,
            assigned_salesperson=assigned_salesperson,
            status=status,
            customer_notes=customer_notes,
            confirmation_code=confirmation_code,
        )
        session.add(appt)
        session.commit()
        session.refresh(appt)
        log_audit("APPOINTMENT_CREATED", "Appointment", str(appt.id), f"Lead: {lead_id}, Slot: {requested_date} {requested_time}")
        return appt


def get_appointments(lead_id: int | None = None) -> list[Appointment]:
    with SessionLocal() as session:
        stmt = select(Appointment)
        if lead_id is not None:
            stmt = stmt.where(Appointment.lead_id == lead_id)
        return list(session.scalars(stmt.order_by(Appointment.created_at.desc())))


def update_appointment(
    appt_id: int,
    status: str,
    new_date: str | None = None,
    new_time: str | None = None,
    notes: str = "",
) -> Appointment:
    with SessionLocal() as session:
        appt = session.get(Appointment, appt_id)
        if appt is None:
            raise ValueError(f"Appointment {appt_id} not found")
        appt.status = status
        if new_date:
            appt.requested_date = new_date
        if new_time:
            appt.requested_time = new_time
        if new_date and new_time:
            appt.confirmed_date_time = f"{new_date} at {new_time}"
        if notes:
            appt.customer_notes = f"{appt.customer_notes} | {notes}".strip(" |")
        session.commit()
        session.refresh(appt)
        log_audit(f"APPOINTMENT_{status.upper()}", "Appointment", str(appt_id), f"Status: {status}")
        return appt


# --- DND Registry Helpers ---

def add_dnd_entry(phone_number: str, reason: str = "Customer requested opt-out", source: str = "customer_request") -> DndEntry:
    with SessionLocal() as session:
        existing = session.scalar(select(DndEntry).where(DndEntry.phone_number == phone_number))
        if existing:
            return existing
        entry = DndEntry(phone_number=phone_number, reason=reason, source=source)
        session.add(entry)
        # Also mark all matching contacts and leads as opt-out
        session.execute(update(Contact).where(Contact.phone_number == phone_number).values(is_dnd=True, validation_status="opted_out"))
        session.execute(update(Lead).where(Lead.phone_number == phone_number).values(opt_out=True, interest_status="Do Not Call"))
        session.commit()
        session.refresh(entry)
        log_audit("DND_REGISTERED", "DndEntry", str(entry.id), f"Phone: {phone_number}")
        return entry


def is_phone_dnd(phone_number: str) -> bool:
    with SessionLocal() as session:
        entry = session.scalar(select(DndEntry).where(DndEntry.phone_number == phone_number))
        if entry is not None:
            return True
        lead = session.scalar(select(Lead).where(Lead.phone_number == phone_number, Lead.opt_out == True))
        return lead is not None


def get_dnd_entries() -> list[DndEntry]:
    with SessionLocal() as session:
        return list(session.scalars(select(DndEntry).order_by(DndEntry.created_at.desc())))


# --- Campaign Analytics ---

def get_campaign_analytics(campaign_id: int | None = None) -> dict[str, Any]:
    with SessionLocal() as session:
        # Contacts stats
        if campaign_id:
            campaign = session.get(Campaign, campaign_id)
            batch_id = campaign.batch_id if campaign else None
        else:
            batch_id = None

        total_contacts_query = select(func.count(Contact.id))
        valid_contacts_query = select(func.count(Contact.id)).where(Contact.validation_status.in_(("valid", "approved")))
        
        if batch_id:
            total_contacts = session.scalar(total_contacts_query.where(Contact.batch_id == batch_id)) or 0
            valid_contacts = session.scalar(valid_contacts_query.where(Contact.batch_id == batch_id)) or 0
        else:
            total_contacts = session.scalar(total_contacts_query) or 0
            valid_contacts = session.scalar(valid_contacts_query) or 0

        # Campaign contacts stats
        cc_stmt = select(CampaignContact)
        if campaign_id:
            cc_stmt = cc_stmt.where(CampaignContact.campaign_id == campaign_id)
        c_contacts = list(session.scalars(cc_stmt))
        
        eligible_contacts = len([c for c in c_contacts if c.status not in ("dnd_blocked",)]) if c_contacts else valid_contacts
        calls_attempted = sum(c.attempts for c in c_contacts) if c_contacts else 0
        calls_connected = len([c for c in c_contacts if c.status == "completed" or c.call_outcome != ""])
        no_answer_calls = len([c for c in c_contacts if c.call_outcome in ("no_answer", "busy", "No Answer", "Busy")])

        # Leads stats
        lead_stmt = select(Lead)
        if campaign_id:
            lead_stmt = lead_stmt.where(Lead.campaign_id == campaign_id)
        leads = list(session.scalars(lead_stmt))

        hot_leads = len([l for l in leads if l.interest_status == "Hot"])
        warm_leads = len([l for l in leads if l.interest_status == "Warm"])
        cold_leads = len([l for l in leads if l.interest_status == "Cold"])
        not_interested = len([l for l in leads if l.interest_status in ("Not Interested", "not_interested", "Do Not Call", "do_not_call")])
        callback_requests = len([l for l in leads if "callback" in (l.interest_status or "").lower()])
        interested_customers = hot_leads + warm_leads
        qualified_leads = hot_leads + warm_leads

        # Appointments stats
        appt_stmt = select(Appointment)
        if campaign_id:
            appt_stmt = appt_stmt.where(Appointment.campaign_id == campaign_id)
        appts = list(session.scalars(appt_stmt))
        site_visits_requested = len(appts)
        site_visits_confirmed = len([a for a in appts if a.status == "confirmed"])

        conversion_rate = round((qualified_leads / calls_connected * 100), 1) if calls_connected > 0 else 0.0

        return {
            "total_uploaded_contacts": total_contacts,
            "valid_contacts": valid_contacts,
            "eligible_contacts": eligible_contacts,
            "calls_attempted": calls_attempted,
            "calls_connected": calls_connected,
            "no_answer_calls": no_answer_calls,
            "interested_customers": interested_customers,
            "qualified_leads": qualified_leads,
            "hot_leads": hot_leads,
            "warm_leads": warm_leads,
            "cold_leads": cold_leads,
            "callback_requests": callback_requests,
            "not_interested_contacts": not_interested,
            "site_visits_requested": site_visits_requested,
            "site_visits_confirmed": site_visits_confirmed,
            "conversion_rate": conversion_rate,
        }


def export_leads(path: str) -> str:
    rows = [
        {
            "ID": lead.id,
            "Name": lead.name,
            "Phone Number": lead.phone_number,
            "Email": lead.email,
            "Locality": lead.area,
            "BHK": lead.bhk,
            "Budget": lead.budget,
            "Purpose": lead.purpose,
            "Timeline": lead.timeline,
            "Interest Status": lead.interest_status,
            "Score": lead.score,
            "Site Visit Booked": "Yes" if lead.site_visit_interest else "No",
            "Next Recommended Action": lead.next_action,
            "Assigned Salesperson": lead.assigned_salesperson,
            "Summary": lead.summary,
            "Last Updated": lead.updated_at.strftime("%Y-%m-%d %H:%M") if lead.updated_at else "",
        }
        for lead in get_leads()
    ]
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


class KnowledgeBase:
    def __init__(self, directory: str = "data/knowledge"):
        directory = str(Path(__file__).resolve().parents[1] / directory)
        files = sorted(Path(directory).glob("*.md")) + sorted(
            Path(directory).glob("*.txt")
        )
        self.documents = [file.read_text(encoding="utf-8") for file in files]
        self.vectorizer = TfidfVectorizer()
        self.matrix = (
            self.vectorizer.fit_transform(self.documents)
            if self.documents
            else None
        )

    def search(self, question: str, limit: int = 2) -> str:
        if self.matrix is None:
            return ""
        scores = (self.vectorizer.transform([question]) @ self.matrix.T).toarray()[0]
        indexes = scores.argsort()[::-1][:limit]
        return "\n\n".join(self.documents[index] for index in indexes if scores[index] > 0)
