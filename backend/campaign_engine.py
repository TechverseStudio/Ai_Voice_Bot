"""Autonomous Outbound Calling Engine with Queue-Based Concurrency and Business Safety."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import uuid4

from backend.analysis import analyze_conversation
from backend.agent.conversation_manager import ConversationManager
from backend.crm import (
    Campaign,
    CampaignContact,
    create_or_update_lead,
    get_campaign,
    get_campaign_contacts,
    is_phone_dnd,
    log_audit,
    save_call,
    save_outbound_call,
    update_campaign_contact_status,
    update_campaign_status,
    SessionLocal,
)
from backend.telephony import (
    CallRequest,
    get_configured_provider_name,
    get_provider,
    initiate_outbound_call,
)
from backend.scheduler import validate_and_book_appointment

logger = logging.getLogger(__name__)


class CampaignEngine:
    """Manages queue-based autonomous outbound calling campaigns."""

    def __init__(self) -> None:
        self.active_tasks: dict[int, asyncio.Task] = {}
        self.paused_campaigns: set[int] = set()
        self.conversation_manager = ConversationManager()
        self.live_events: list[dict[str, Any]] = []

    def get_live_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.live_events[-limit:]

    def log_event(self, campaign_id: int, event_type: str, message: str, data: dict | None = None) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "campaign_id": campaign_id,
            "event_type": event_type,
            "message": message,
            "data": data or {},
        }
        self.live_events.append(event)
        if len(self.live_events) > 200:
            self.live_events = self.live_events[-200:]
        logger.info(f"[Campaign {campaign_id}] {event_type}: {message}")

    def is_within_calling_window(self, campaign: Campaign, bypass_for_test: bool = False) -> tuple[bool, str]:
        """Verify local time satisfies permitted calling window (e.g. 09:30 to 19:30)."""
        if bypass_for_test:
            return True, "Permitted test mode bypass"

        now = datetime.now()
        current_time_str = now.strftime("%H:%M")

        window_start = campaign.window_start or "09:30"
        window_end = campaign.window_end or "19:30"

        if window_start <= current_time_str <= window_end:
            return True, f"Current time {current_time_str} is within calling window ({window_start} - {window_end})"
        else:
            return False, f"Current time {current_time_str} is outside permitted calling window ({window_start} - {window_end})"

    async def start_campaign(self, campaign_id: int, bypass_window_for_test: bool = True) -> dict[str, Any]:
        """Launch an approved campaign in background queue worker."""
        campaign = get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign.status in ("running",):
            return {"status": "already_running", "message": "Campaign is already running"}

        # Ensure approved status before launch
        if campaign.status == "draft":
            update_campaign_status(campaign_id, "approved")

        update_campaign_status(campaign_id, "running")
        if campaign_id in self.paused_campaigns:
            self.paused_campaigns.remove(campaign_id)

        self.log_event(campaign_id, "CAMPAIGN_LAUNCHED", f"Campaign '{campaign.name}' launched")
        log_audit("CAMPAIGN_STARTED", "Campaign", str(campaign_id), f"Name: {campaign.name}")

        task = asyncio.create_task(self._process_campaign_queue(campaign_id, bypass_window_for_test))
        self.active_tasks[campaign_id] = task

        return {"status": "started", "campaign_id": campaign_id, "message": f"Campaign '{campaign.name}' is running"}

    def pause_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Pause a running campaign."""
        self.paused_campaigns.add(campaign_id)
        update_campaign_status(campaign_id, "paused")
        self.log_event(campaign_id, "CAMPAIGN_PAUSED", f"Campaign {campaign_id} paused by operator")
        log_audit("CAMPAIGN_PAUSED", "Campaign", str(campaign_id), "Operator pause")
        return {"status": "paused", "campaign_id": campaign_id}

    def resume_campaign(self, campaign_id: int, bypass_window_for_test: bool = True) -> dict[str, Any]:
        """Resume a paused campaign."""
        if campaign_id in self.paused_campaigns:
            self.paused_campaigns.remove(campaign_id)
        update_campaign_status(campaign_id, "running")
        self.log_event(campaign_id, "CAMPAIGN_RESUMED", f"Campaign {campaign_id} resumed")
        log_audit("CAMPAIGN_RESUMED", "Campaign", str(campaign_id), "Operator resume")

        if campaign_id not in self.active_tasks or self.active_tasks[campaign_id].done():
            task = asyncio.create_task(self._process_campaign_queue(campaign_id, bypass_window_for_test))
            self.active_tasks[campaign_id] = task

        return {"status": "resumed", "campaign_id": campaign_id}

    def stop_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Stop and complete a campaign."""
        if campaign_id in self.active_tasks:
            self.active_tasks[campaign_id].cancel()
        if campaign_id in self.paused_campaigns:
            self.paused_campaigns.remove(campaign_id)
        update_campaign_status(campaign_id, "completed")
        self.log_event(campaign_id, "CAMPAIGN_STOPPED", f"Campaign {campaign_id} stopped")
        log_audit("CAMPAIGN_STOPPED", "Campaign", str(campaign_id), "Operator stop")
        return {"status": "stopped", "campaign_id": campaign_id}

    async def _process_campaign_queue(self, campaign_id: int, bypass_window_for_test: bool) -> None:
        """Main queue-based background processing loop with concurrency and safety controls."""
        try:
            campaign = get_campaign(campaign_id)
            if not campaign:
                return

            semaphore = asyncio.Semaphore(campaign.concurrency_limit or 2)
            contacts = get_campaign_contacts(campaign_id)

            self.log_event(
                campaign_id,
                "QUEUE_INITIALIZED",
                f"Queue initialized with {len(contacts)} contacts. Concurrency: {campaign.concurrency_limit}",
            )

            for cc in contacts:
                # Handle pause
                while campaign_id in self.paused_campaigns:
                    await asyncio.sleep(2)

                # Fetch fresh status
                if cc.status in ("completed", "dnd_blocked", "max_retries_reached"):
                    continue

                # 1. Calling Window Check
                in_window, window_msg = self.is_within_calling_window(campaign, bypass_window_for_test)
                if not in_window:
                    self.log_event(campaign_id, "WINDOW_RESTRICTION", window_msg)
                    update_campaign_contact_status(
                        cc.id,
                        status="retry_scheduled",
                        outcome="outside_window",
                        next_retry=datetime.now(timezone.utc) + timedelta(minutes=60),
                    )
                    continue

                # 2. DND & Consent Check
                if is_phone_dnd(cc.phone_number):
                    self.log_event(campaign_id, "DND_BLOCKED", f"Contact {cc.name} ({cc.phone_number}) blocked by DND Registry")
                    update_campaign_contact_status(cc.id, status="dnd_blocked", outcome="dnd_opt_out")
                    continue

                # 3. Maximum Attempts Check
                if cc.attempts >= campaign.max_attempts:
                    self.log_event(campaign_id, "MAX_RETRIES", f"Contact {cc.name} reached max attempts ({campaign.max_attempts})")
                    update_campaign_contact_status(cc.id, status="max_retries_reached", outcome="unreachable")
                    continue

                # 4. Process Call with Semaphore Concurrency Control
                async with semaphore:
                    await self._execute_autonomous_call(campaign, cc)

                # Rate limiting delay between calls (1-2 seconds)
                await asyncio.sleep(1.5)

            update_campaign_status(campaign_id, "completed")
            self.log_event(campaign_id, "CAMPAIGN_COMPLETED", f"All eligible contacts in campaign {campaign_id} processed")

        except asyncio.CancelledError:
            self.log_event(campaign_id, "CAMPAIGN_CANCELLED", "Queue processor task cancelled")
        except Exception as e:
            logger.exception(f"Campaign queue error: {e}")
            self.log_event(campaign_id, "CAMPAIGN_ERROR", str(e))

    async def _execute_autonomous_call(self, campaign: Campaign, cc: CampaignContact) -> None:
        """Conducts an intelligent real-time conversational call with a contact."""
        session_id = str(uuid4())
        phone = cc.phone_number
        name = cc.name or "Prospective Buyer"

        update_campaign_contact_status(cc.id, status="calling", session_id=session_id)
        self.log_event(
            campaign.id,
            "CALL_CONNECTING",
            f"Dialing {name} ({phone}) via {campaign.agent_name}...",
            {"contact_id": cc.id, "phone": phone, "session_id": session_id},
        )

        # Check Telephony Provider mode (exotel / twilio vs mock)
        provider_name = get_configured_provider_name()
        if provider_name != "mock":
            provider = get_provider(provider_name)
            ready, msg, missing = provider.is_ready()
            if not ready:
                self.log_event(
                    campaign.id,
                    "CALL_FAILED",
                    f"Telephony provider '{provider_name}' is not configured: {msg}. Missing: {missing}",
                    {"missing_config": missing, "phone": phone},
                )
                update_campaign_contact_status(cc.id, status="failed", outcome=f"Provider unconfigured: {msg}")
                return

            try:
                call_req = CallRequest(
                    phone_number=phone,
                    campaign_id=campaign.id,
                    customer_name=name,
                    context={"agent_name": campaign.agent_name, "project_name": campaign.project_name},
                )
                result = initiate_outbound_call(call_req)
                save_outbound_call(
                    lead_id=None,
                    phone_number=phone,
                    provider_call_id=result.provider_call_id,
                    status=result.status,
                    message=result.message,
                    provider=result.provider,
                    campaign_id=campaign.id,
                )
                self.log_event(
                    campaign.id,
                    "CALL_INITIATED",
                    f"Real phone call placed via {result.provider} (Sid: {result.provider_call_id}) to {phone}",
                    {"provider_call_id": result.provider_call_id, "status": result.status},
                )
                update_campaign_contact_status(cc.id, status="calling", session_id=result.provider_call_id)
                return
            except Exception as ex:
                logger.exception(f"Error initiating real outbound call: {ex}")
                self.log_event(
                    campaign.id,
                    "CALL_FAILED",
                    f"Carrier error dialing {phone}: {ex}",
                )
                update_campaign_contact_status(cc.id, status="failed", outcome=f"Carrier error: {ex}")
                return

        await asyncio.sleep(1.0)  # Call connection handshake

        # Build realistic customer response scenario based on contact notes/locality
        dialogue_turns = self._generate_scenario_for_contact(name, cc.locality, cc.phone_number)
        transcript_lines = []

        # Opening Greeting
        session = self.conversation_manager.get_or_create_session(
            session_id=session_id,
            customer_name=name,
            agent_name=campaign.agent_name.split("-")[0].strip(),
            language=campaign.language,
        )
        opening = self.conversation_manager.generate_opening_greeting(session)
        transcript_lines.append(f"Agent ({campaign.agent_name}): {opening}")

        for cust_input in dialogue_turns:
            transcript_lines.append(f"Customer ({name}): {cust_input}")
            agent_reply, intent, facts = self.conversation_manager.process_turn(session_id, cust_input)
            transcript_lines.append(f"Agent ({campaign.agent_name}): {agent_reply}")

            if session.is_concluded:
                break
            await asyncio.sleep(0.5)

        full_transcript = chr(10).join(transcript_lines)

        # 5. Post-Call Intelligence & Requirement Extraction
        analysis = analyze_conversation(
            full_transcript,
            customer_name_fallback=name,
            locality_fallback=cc.locality,
        )

        category = analysis["category"]
        score = analysis["score"]
        reqs = analysis["requirements"]
        summary = analysis["summary"]

        self.log_event(
            campaign.id,
            "CALL_COMPLETED",
            f"Call finished with {name}. Outcome: {category} (Score: {score})",
            {"score": score, "category": category, "summary": summary},
        )

        # 6. Create / Update CRM Lead
        is_opt_out = category in ("Do Not Call", "do_not_call")
        lead = create_or_update_lead(
            name=name,
            phone_number=phone,
            area=reqs.get("preferred_locality") or cc.locality or "Pune",
            budget=reqs.get("budget") or "",
            bhk=reqs.get("bhk") or "",
            purpose=reqs.get("property_purpose") or "",
            timeline=reqs.get("buying_timeline") or "",
            financing=reqs.get("financing_requirement") or "",
            amenities=reqs.get("amenities_preferred") or "",
            site_visit_interest=reqs.get("site_visit_interest") or False,
            interest_status=category,
            score=score,
            score_breakdown=analysis.get("score_breakdown"),
            summary=summary,
            extracted_requirements=reqs,
            evidence=analysis.get("evidence"),
            next_action=analysis.get("next_action") or "",
            assigned_salesperson=campaign.assigned_sales_team,
            campaign_id=campaign.id,
            contact_id=cc.contact_id,
            opt_out=is_opt_out,
        )

        # 7. Save Call Summary
        save_call(
            lead_id=lead.id,
            transcript=full_transcript,
            agent_response=analysis.get("next_action") or "",
            interest_status=category,
            campaign_id=campaign.id,
            session_id=session_id,
            call_mode="telephony_simulated",
            objections="; ".join(analysis.get("objections", [])),
            questions_asked="; ".join(analysis.get("questions_asked", [])),
            call_duration_seconds=75,
        )

        # 8. Automatic Site Visit Scheduling if confirmed
        if reqs.get("site_visit_interest"):
            req_date = reqs.get("preferred_meeting_date") or "Saturday"
            req_time = reqs.get("preferred_meeting_time") or "11:00 AM"
            booking = validate_and_book_appointment(
                lead_id=lead.id,
                requested_date_raw=req_date,
                requested_time_raw=req_time,
                project_name=campaign.project_name,
                customer_notes=f"Auto-booked during AI Campaign '{campaign.name}'",
                campaign_id=campaign.id,
            )
            self.log_event(
                campaign.id,
                "SITE_VISIT_BOOKED",
                f"Site visit confirmed for {name}: {booking['date']} at {booking['time']} ({booking['confirmation_code']})",
                booking,
            )

        # 9. Update Campaign Contact
        update_campaign_contact_status(
            cc.id,
            status="completed",
            outcome=category,
            session_id=session_id,
            lead_id=lead.id,
        )

    def _generate_scenario_for_contact(self, name: str, locality: str, phone: str) -> list[str]:
        """Generate realistic conversational turns based on customer characteristics."""
        last_digit = int(phone[-1]) if phone and phone[-1].isdigit() else 5

        # Variety of realistic real estate prospect scenarios
        if last_digit in (0, 1):
            # Hot Buyer: 2 BHK, 75L, wants Saturday visit at 11 AM
            return [
                f"Hello Priya. Yes, I am {name}. I have two minutes.",
                f"I am actively looking for a 2 BHK flat near {locality or 'Wakad'} for self-use.",
                "My budget is around 75 Lakhs and I want to purchase within 2 months. Can I visit this Saturday at 11 AM to see the sample flat?",
            ]
        elif last_digit in (2, 3):
            # Hot Buyer: 3 BHK, 95L, wants Sunday visit
            return [
                f"Hi. Yes, speaking. Tell me about the project.",
                "We are a family of four looking for a 3 BHK apartment with gym and swimming pool.",
                "Our budget is around 95 Lakhs. We can come for a site visit this Sunday morning at 11:30 AM.",
            ]
        elif last_digit in (4, 5):
            # Warm Buyer: 1 BHK investment, exploring pricing
            return [
                "Yes, I have time. Tell me.",
                "I am looking for a 1 BHK as an investment near Hinjawadi IT Park. What is the starting price?",
                "48 Lakhs sounds reasonable. Please send the brochure and floor plans on WhatsApp. I will decide on a visit next week.",
            ]
        elif last_digit in (6,):
            # Callback Requested
            return [
                "I am driving right now and cannot talk. Please call me back tomorrow afternoon.",
            ]
        elif last_digit in (7,):
            # Not Interested
            return [
                "No thank you, I have already purchased a flat in Baner last month. Not interested.",
            ]
        else:
            # Warm Buyer: 2 BHK with location inquiry
            return [
                "Yes, hello. What project is this?",
                "How far is the property from Wakad Bridge and Hinjawadi IT Park Phase 1?",
                "Okay, sounds good. I will consider a visit this weekend.",
            ]
