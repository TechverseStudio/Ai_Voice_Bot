"""Comprehensive Acceptance Test Suite for AI Autonomous Lead Generation Engine."""

import asyncio
from pathlib import Path
import pytest

from backend.analysis import analyze_conversation
from backend.agent.conversation_manager import ConversationManager
from backend.campaign_engine import CampaignEngine
from backend.crm import (
    Appointment,
    SessionLocal,
    create_campaign,
    create_import_batch,
    create_tables,
    get_appointments,
    get_campaign,
    get_campaign_analytics,
    get_campaign_contacts,
    get_contacts,
    get_dnd_entries,
    get_leads,
    is_phone_dnd,
    save_contacts,
)
from backend.importer import normalize_and_validate_phone, process_contact_document
from backend.scheduler import validate_and_book_appointment


@pytest.fixture(autouse=True)
def setup_db():
    create_tables()


def test_1_and_2_document_parsing_and_phone_normalization():
    """Verify criteria 1 & 2: Excel extraction, Indian mobile normalization, and duplicate detection."""
    sample_path = Path("data/sample_contacts.xlsx")
    assert sample_path.exists(), "Sample contacts file must exist"

    result = process_contact_document(str(sample_path), "sample_contacts.xlsx")
    summary = result["summary"]
    rows = result["rows"]

    assert summary["total_rows"] == 8
    assert summary["valid_rows"] == 5
    assert summary["duplicate_rows"] == 1
    assert summary["invalid_rows"] == 1
    assert summary["review_needed_rows"] == 1

    # Verify normalization format (+91XXXXXXXXXX)
    valid_row = next(r for r in rows if r["validation_status"] == "valid")
    assert valid_row["phone_number"].startswith("+91")
    assert len(valid_row["phone_number"]) == 13

    # Verify duplicate detection
    dup_row = next(r for r in rows if r["validation_status"] == "duplicate")
    assert "Duplicate" in dup_row["validation_message"]

    # Verify invalid detection
    invalid_row = next(r for r in rows if r["validation_status"] == "invalid")
    assert "Dummy" in invalid_row["validation_message"] or "Invalid" in invalid_row["validation_message"]


def test_3_contact_preview_and_approval():
    """Verify criteria 3: Batch creation and contact preview approval."""
    batch = create_import_batch(
        filename="sample_contacts.xlsx",
        file_type="xlsx",
        total_rows=8,
        valid_rows=5,
        duplicate_rows=1,
        invalid_rows=1,
        review_needed_rows=1,
        status="approved",
    )
    assert batch.id > 0
    assert batch.status == "approved"


def test_4_create_campaign():
    """Verify criteria 4: Campaign creation with business constraints."""
    campaign = create_campaign(
        name="Acceptance Test Wakad Drive",
        project_name="Krishna's AI Property - Wakad",
        objective="New Launch Awareness & Lead Qualification",
        batch_id=1,
        agent_name="Priya - Residential Advisory Executive",
        language="en-IN",
        window_start="09:30",
        window_end="19:30",
        max_attempts=2,
        retry_interval_minutes=60,
        assigned_sales_team="Wakad Central Sales Desk",
        follow_up_policy="Immediate CRM alert",
        concurrency_limit=2,
    )
    assert campaign.id > 0
    assert campaign.status == "draft"


def test_5_to_13_autonomous_calling_and_qualification():
    """Verify criteria 5 to 13:

    - Natural conversation
    - Interest understanding
    - BHK, budget, locality collection
    - Qualified lead creation
    - Call summary generation
    - Site visit arrangement and slot validation
    """
    cm = ConversationManager()
    session = cm.get_or_create_session(customer_name="Rajesh Kulkarni")

    # Step 6: Opening
    greeting = cm.generate_opening_greeting(session)
    assert "Priya" in greeting
    assert "Krishna's AI Property" in greeting

    # Step 7 & 8: Interest & requirements
    resp1, intent1, facts1 = cm.process_turn(
        session.session_id,
        "Yes, I have two minutes. I am looking to buy a 2 BHK apartment near Wakad.",
    )
    assert facts1.get("bhk") == "2 BHK"

    # Step 8: Budget & Site visit inquiry
    resp2, intent2, facts2 = cm.process_turn(
        session.session_id,
        "My budget is around 75 lakhs. Can I visit this Saturday at 11 AM?",
    )
    assert facts2.get("site_visit_interest") is True

    # Step 9 & 10: Analysis and Lead Creation
    transcript = f"Agent: {greeting}\nCustomer: Yes I am looking for 2 BHK near Wakad.\nAgent: {resp1}\nCustomer: My budget is around 75 lakhs. Can I visit this Saturday at 11 AM?\nAgent: {resp2}"
    analysis = analyze_conversation(transcript, customer_name_fallback="Rajesh Kulkarni")

    assert analysis["category"] == "Hot"
    assert analysis["score"] >= 70
    assert analysis["requirements"]["site_visit_interest"] is True
    assert analysis["requirements"]["preferred_meeting_date"] == "Saturday"

    # Step 11, 12, 13: Appointment slot validation & confirmation
    with SessionLocal() as s:
        s.query(Appointment).filter(Appointment.lead_id == 1).delete()
        s.commit()

    booking = validate_and_book_appointment(
        lead_id=1,
        requested_date_raw="Saturday",
        requested_time_raw="11 AM",
        project_name="Krishna's AI Property - Wakad",
    )
    assert booking["status"] == "confirmed"
    assert booking["confirmation_code"].startswith("VISIT-")
    assert booking["assigned_salesperson"] != ""


def test_14_and_15_crm_display_and_campaign_analytics():
    """Verify criteria 14 & 15: Leads, Appointments, and Campaign Analytics."""
    analytics = get_campaign_analytics()
    assert "total_uploaded_contacts" in analytics
    assert "calls_connected" in analytics
    assert "qualified_leads" in analytics
    assert "site_visits_confirmed" in analytics
    assert "conversion_rate" in analytics

    leads = get_leads()
    assert len(leads) >= 1

    appts = get_appointments()
    assert len(appts) >= 1
