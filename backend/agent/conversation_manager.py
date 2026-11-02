
def detect_spoken_language(text: str, current_lang: str = "en-IN") -> str:
    """Detect whether customer is speaking English, Hindi, or Marathi."""
    lowered = text.casefold()

    # Marathi markers
    marathi_markers = [
        "नमस्कार", "आहे", "नाही", "पाहिजे", "कधी", "कुठे", "किती", "जमेल", "बघायला",
        "होय", "सांगा", "मला", "आपण", "शनिवारी", "रविवारी", "किंमत", "खोली", "जागा",
        "काय", "फ्लॅट", "घर", "नको", "चालू", "येतो", "येता", "येईल", "घेणार"
    ]
    if any(m in text for m in marathi_markers) or any(m in lowered for m in ("namaskar", "aahe", "pahije", "kiti", "jamel", "mala", "kadhi", "baghayla", "shaniwari", "raviwari")):
        return "mr-IN"

    # Hindi markers
    hindi_markers = [
        "नमस्ते", "है", "नहीं", "चाहिए", "कब", "कहाँ", "कितना", "बताइए", "मुझे",
        "शनिवार", "रविवार", "विजिट", "कीमत", "देखना", "बात", "समय", "ज़रूर",
        "फ्लैट", "बजट", "लाख", "करोड़", "रुपये", "आऊंगा", "आएंगे", "करना"
    ]
    if any(h in text for h in hindi_markers) or any(h in lowered for h in ("namaste", "chahiye", "kitna", "bataiye", "mujhe", "aunga", "shanivar", "ravivar", "kimat", "dekhna", "baat")):
        return "hi-IN"

    # Default to current or English
    if any(c in text for c in "abcdefghijklmnopqrstuvwxyz"):
        return current_lang if current_lang in ("hi-IN", "mr-IN") and len(text.split()) <= 2 else "en-IN"

    return current_lang

"""Real-Time AI Sales Conversation Engine with LLM dialogue and structured state tracking."""

from dataclasses import dataclass, field
import logging
import os
import re
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from sarvamai import SarvamAI

from backend.config import SARVAM_API_KEY, SARVAM_FALLBACK_API_KEY
from backend.crm import KnowledgeBase

logger = logging.getLogger(__name__)
load_dotenv()


PROJECT_KNOWLEDGE_FACTS = """
PROJECT FACTS: Krishna's AI Property - Wakad, Pune
- Location: Near Wakad Bridge, Hinjawadi Link Road, Pimpri-Chinchwad, Pune, Maharashtra 411057.
- Proximity: 5 minutes from Hinjawadi IT Park Phase 1, connected via Mumbai-Pune Expressway and Aundh-Ravet Road.
- Inventory & Indicative Pricing:
  * 1 BHK: approximately 550 sq.ft. carpet, indicative starting from INR 48 Lakhs.
  * 2 BHK: approximately 850 sq.ft. carpet, indicative starting from INR 72 Lakhs.
  * 3 BHK: approximately 1,150 sq.ft. carpet, indicative starting from INR 98 Lakhs.
- Amenities: Grand clubhouse, modern fitness center/gym, swimming pool, landscaped meditation gardens, children's adventure play area, covered visitor parking, 24/7 security with CCTV surveillance, and high-speed elevators.
- Commercial Note: Indicative pricing and possession dates must be confirmed by an authorized sales specialist.
- Site Visits: Open all 7 days from 10:00 AM to 06:30 PM with golf cart tours and sample flat viewings.
"""


@dataclass
class ConversationSession:
    """Isolated state tracking for a single customer sales call."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    lead_id: int | None = None
    customer_name: str = ""
    agent_name: str = "Priya"
    project_name: str = "Krishna's AI Property - Wakad"
    language: str = "en-IN"
    turn_count: int = 0
    has_introduced: bool = False
    time_permitted: bool = False
    is_concluded: bool = False
    opt_out: bool = False
    facts_collected: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)


class ConversationManager:
    """Manages multi-turn sales conversations using LLM with structured state tracking."""

    def __init__(self) -> None:
        self.knowledge = KnowledgeBase()
        self.sessions: dict[str, ConversationSession] = {}
        self.llm_client = None
        self.fallback_llm_client = None
        if SARVAM_API_KEY:
            try:
                self.llm_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
            except Exception as e:
                logger.warning(f"Could not initialize Sarvam LLM client: {e}")
        if SARVAM_FALLBACK_API_KEY:
            try:
                self.fallback_llm_client = SarvamAI(api_subscription_key=SARVAM_FALLBACK_API_KEY)
            except Exception as e:
                logger.warning(f"Could not initialize Sarvam fallback LLM client: {e}")

    def get_or_create_session(
        self,
        session_id: str | None = None,
        lead_id: int | None = None,
        customer_name: str = "",
        agent_name: str = "Priya",
        language: str = "en-IN",
    ) -> ConversationSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]

        new_id = session_id or str(uuid4())
        session = ConversationSession(
            session_id=new_id,
            lead_id=lead_id,
            customer_name=customer_name or "there",
            agent_name=agent_name,
            language=language,
        )
        self.sessions[new_id] = session
        return session

    def generate_opening_greeting(self, session: ConversationSession, is_inbound: bool = False) -> str:
        """Generate a natural professional sales opening greeting introducing as AI assistant."""
        name_str = f" {session.customer_name}" if session.customer_name and session.customer_name != "there" else ""

        agent_label = session.agent_name or "Priya"
        company_name = session.project_name.split(' - ')[0] if ' - ' in session.project_name else session.project_name

        if is_inbound:
            if session.language == "mr-IN":
                greeting = (
                    f"नमस्कार{name_str}! {company_name} मध्ये कॉल केल्याबद्दल धन्यवाद. मी {agent_label}, आपली एआय प्रॉपर्टी असिस्टंट बोलत आहे. "
                    f"आज मी आपल्याला नवीन प्रीमियम फ्लॅट्सच्या माहितीसाठी कशी मदत करू शकते?"
                )
            elif session.language == "hi-IN":
                greeting = (
                    f"नमस्ते{name_str}! {company_name} में कॉल करने के लिए धन्यवाद। मैं {agent_label}, आपकी एआई प्रॉपर्टी कंसल्टेंट बोल रही हूँ। "
                    f"आज मैं हमारे नए प्रीमियम प्रोजेक्ट के बारे में आपकी क्या सहायता कर सकती हूँ?"
                )
            else:
                greeting = (
                    f"Hello{name_str}! Thank you for calling {company_name}. I am {agent_label}, your AI property assistant. "
                    f"How can I help you find your dream home near Hinjawadi IT Park today?"
                )
        else:
            if session.language == "mr-IN":
                greeting = (
                    f"नमस्कार{name_str}! मी {agent_label}, {company_name} येथून एआय व्हॉईस असिस्टंट बोलत आहे. "
                    f"हिंजवडी आयटी पार्क जवळ आमच्या नवीन प्रीमियम फ्लॅट्सबद्दल माहिती देण्यासाठी कॉल केला आहे. "
                    f"आपल्याकडे दोन मिनिटे वेळ मिळेल का?"
                )
            elif session.language == "hi-IN":
                greeting = (
                    f"नमस्ते{name_str}! मैं {agent_label}, {company_name} से एआई सेल्स असिस्टेंट बोल रही हूँ। "
                    f"हिंजवडी आईटी पार्क के पास हमारे नए प्रीमियम 1, 2 और 3 बीएचके प्रोजेक्ट की जानकारी के लिए कॉल किया है। "
                    f"क्या आपके पास बात करने के लिए दो मिनट का समय है?"
                )
            else:
                greeting = (
                    f"Hello{name_str}! I am {agent_label}, an AI sales assistant representing {company_name}. "
                    f"I am calling regarding your recent enquiry for premium residential homes near Hinjawadi IT Park. "
                    f"Do you have two quick minutes to speak?"
                )
        session.has_introduced = True
        session.history.append({"role": "assistant", "content": greeting})
        return greeting

    def process_turn(self, session_id: str, customer_speech: str) -> tuple[str, str, dict[str, Any]]:
        """Process one conversational turn with dynamic multilingual adaptation.

        Returns:
            (agent_response, intent, extracted_facts)
        """
        session = self.get_or_create_session(session_id)
        session.turn_count += 1
        raw_speech = (customer_speech or "").strip()
        lowered = raw_speech.casefold()

        # Dynamic Language Detection & Switching
        detected_lang = detect_spoken_language(raw_speech, session.language)
        if detected_lang != session.language:
            logger.info(f"[Session {session_id}] Customer switched language: {session.language} -> {detected_lang}")
            session.language = detected_lang

        # Update in-memory dialogue history
        session.history.append({"role": "user", "content": raw_speech})

        # 1. State Tracking: Extract volunteered facts
        self._track_facts(session, lowered, raw_speech)

        # 2. Intent Detection
        intent = self._detect_intent(session, lowered)

        # 3. Handle Critical Deterministic Flows
        if intent == "do_not_call":
            session.is_concluded = True
            session.opt_out = True
            response = (
                "I completely understand and apologize for disturbing you. "
                "I will immediately register your number on our Do Not Call list so you receive no further calls. "
                "Thank you and have a good day."
            )
            session.history.append({"role": "assistant", "content": response})
            return response, intent, session.facts_collected

        if intent == "callback_requested":
            session.is_concluded = True
            response = (
                "Understood. I will not hold you up right now. "
                "Our sales executive will connect with you tomorrow at a more convenient time. Thank you!"
            )
            session.history.append({"role": "assistant", "content": response})
            return response, intent, session.facts_collected

        if intent == "not_interested":
            session.is_concluded = True
            response = (
                "No problem at all! Thank you for letting me know. "
                "If your plans change or you explore properties in Wakad in the future, please feel free to reach out. Have a wonderful day!"
            )
            session.history.append({"role": "assistant", "content": response})
            return response, intent, session.facts_collected

        if intent == "unclear":
            response = "Pardon me, the line was slightly unclear. Could you please repeat that?"
            session.history.append({"role": "assistant", "content": response})
            return response, intent, session.facts_collected

        # 4. Generate Knowledge-Grounded Conversational Response (LLM with grounded prompt)
        response = self._generate_llm_response(session, raw_speech, intent)
        session.history.append({"role": "assistant", "content": response})
        return response, intent, session.facts_collected

    def _track_facts(self, session: ConversationSession, lowered: str, raw: str) -> None:
        """Incrementally update session facts without overwriting with empty data."""
        # BHK
        bhk_m = re.search(r"\b([1-4])\s*(?:bhk|bedroom|bed)\b", lowered)
        if bhk_m:
            session.facts_collected["bhk"] = f"{bhk_m.group(1)} BHK"

        # Budget
        budget_m = re.search(
            r"(?:budget(?: is| of)?|around|under|up to)\s*(?:inr|rs\.?|₹)?\s*([0-9][0-9.,]*)\s*(lakh|lakhs|crore|cr)?",
            lowered,
        )
        if not budget_m:
            budget_m = re.search(r"\b([0-9]{2,3})\s*(?:lakh|lakhs|cr|crore)\b", lowered)
        if budget_m:
            parts = [p for p in budget_m.groups() if p]
            session.facts_collected["budget"] = " ".join(parts).title()

        # Locality
        loc_m = re.search(r"\b(?:in|near|around|at)\s+([A-Za-z][A-Za-z\s]{2,20}?)(?=\s+(?:with|for|and|budget)\b|[,.]|$)", raw, re.I)
        if loc_m:
            loc = loc_m.group(1).strip()
            if loc.lower() not in ("pune", "india", "property", "site", "project", "this"):
                session.facts_collected["locality"] = loc

        # Purpose
        if "investment" in lowered:
            session.facts_collected["purpose"] = "Investment"
        elif any(w in lowered for w in ("self use", "live in", "family", "own stay")):
            session.facts_collected["purpose"] = "Self-Use"

        # Timeline
        for phrase, val in [
            ("immediate", "Immediate"),
            ("this month", "Within 1 Month"),
            ("2 months", "1-2 Months"),
            ("next month", "1-2 Months"),
            ("3 months", "3 Months"),
            ("6 months", "6 Months"),
        ]:
            if phrase in lowered:
                session.facts_collected["timeline"] = val
                break

        # Site Visit Intent & Slot
        if any(w in lowered for w in ("visit", "come over", "see the flat", "sample flat", "site visit")):
            session.facts_collected["site_visit_interest"] = True

        for day in ["saturday", "sunday", "tomorrow", "this weekend", "monday", "friday"]:
            if day in lowered:
                session.facts_collected["site_visit_date"] = day.title()
                break

        time_m = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}|\bmorning\b|\bafternoon\b|\bevening\b)", lowered)
        if not time_m and " at " in lowered:
            time_m = re.search(r"\bat\s+(\d{1,2}(?:\s*(?:am|pm))?)\b", lowered)
        if time_m:
            t_str = time_m.group(1).upper().strip()
            if not any(w in t_str.lower() for w in ["bhk", "bedroom", "month", "lakh", "cr"]):
                session.facts_collected["site_visit_time"] = t_str

    def _detect_intent(self, session: ConversationSession, lowered: str) -> str:
        if any(w in lowered for w in ("do not call", "don't call", "stop calling", "remove my number", "block me")):
            return "do_not_call"
        if any(w in lowered for w in ("call me back", "call later", "busy right now", "in a meeting", "driving")):
            return "callback_requested"
        if any(w in lowered for w in ("not interested", "no need", "wrong number", "already bought")):
            return "not_interested"
        if len(lowered.split()) < 1:
            return "unclear"
        if any(w in lowered for w in ("yes", "sure", "tell me", "okay", "go ahead", "i have time")) and session.turn_count <= 2:
            return "permission_granted"
        if any(w in lowered for w in ("site visit", "visit the property", "visit the site", "can i see")):
            return "book_site_visit"
        if any(w in lowered for w in ("price", "cost", "how much", "rate", "starting price")):
            return "price_inquiry"
        if any(w in lowered for w in ("amenity", "amenities", "pool", "gym", "garden", "parking", "clubhouse")):
            return "amenities_inquiry"
        if any(w in lowered for w in ("where", "location", "address", "how to reach", "route", "hinjawadi", "wakad")):
            return "location_inquiry"
        if any(w in lowered for w in ("bhk", "configuration", "flat size", "carpet area", "options")):
            return "configuration_inquiry"
        return "general_sales_inquiry"

    def _generate_llm_response(self, session: ConversationSession, customer_speech: str, intent: str) -> str:
        """Call Sarvam LLM for natural, human-like sales conversation, with robust grounded fallback."""
        system_prompt = "You are " + session.agent_name + ", real estate sales specialist for Krishna Property Wakad. Customer: " + session.customer_name + ". Rules: 1-3 spoken sentences. Ask ONE question. Ground in project facts: 1 BHK 48L, 2 BHK 72L, 3 BHK 98L, clubhouse, gym, pool, Wakad Hinjawadi link road. Offer site visit this Saturday 11 AM if interested."
        messages = [{"role": "system", "content": system_prompt}]
        for msg in session.history[-6:]:
            messages.append(msg)

        for client in [self.llm_client, self.fallback_llm_client]:
            if not client:
                continue
            try:
                completion = client.chat.completions(
                    model="sarvam-105b-conversations",
                    messages=messages,
                )
                if completion and completion.choices:
                    resp_text = completion.choices[0].message.content.strip()
                    if resp_text:
                        return resp_text
            except Exception as e:
                logger.warning(f"Sarvam LLM call exception with client, trying fallback: {e}")

        # Grounded Fallback Response Generator
        return self._generate_grounded_fallback(session, intent)

    def _generate_grounded_fallback(self, session: ConversationSession, intent: str) -> str:
        bhk = session.facts_collected.get("bhk")
        budget = session.facts_collected.get("budget")
        visit_date = session.facts_collected.get("site_visit_date")
        lang = session.language

        if lang == "mr-IN":
            if intent == "permission_granted":
                return "छान! आमच्याकडे वाकड येथे 1, 2 आणि 3 बीएचके प्रीमियम घरे उपलब्ध आहेत. आपण कोणत्या बीएचकेचा विचार करत आहात?"
            if intent in ("configuration_inquiry", "project_enquiry"):
                return "आमच्याकडे 1 बीएचके 550 चौ.फूट, 2 बीएचके 850 चौ.फूट आणि 3 बीएचके 1150 चौ.फूट कार्पेट एरिया उपलब्ध आहे. आपल्याला कोणता आकार योग्य वाटतो?"
            if intent == "price_inquiry":
                if bhk == "1 BHK":
                    return "आमच्या 1 बीएचकेची अंदाजे किंमत 48 लाखांपासून सुरू होते. आपण स्वतः राहण्यासाठी घेत आहात की गुंतवणुकीसाठी?"
                elif bhk == "3 BHK":
                    return "आमच्या 3 बीएचके लक्झरी फ्लॅटची किंमत 98 लाखांपासून सुरू होते. आपले खरेदीचे नियोजन कधीपर्यंतचे आहे?"
                else:
                    return "आमच्या 2 बीएचकेची अंदाजे किंमत 72 लाख आणि 3 बीएचके 98 लाखांपासून सुरू होते. आपण या शनिवारी सॅम्पल फ्लॅट पाहायला येऊ शकता का?"
            if intent == "amenities_inquiry":
                return "प्रकल्पामध्ये क्लबहाऊस, स्विमिंग पूल, सुसज्ज जिम, लहान मुलांसाठी खेळण्याची जागा आणि 24 तास सुरक्षा उपलब्ध आहे. आपण या शनिवारी बघायला येऊ शकता का?"
            if intent == "location_inquiry":
                return "प्रकल्प वाकड ब्रिजजवळ, हिंजवडी लिंक रोडवर आहे, हिंजवडी आयटी पार्कपासून फक्त 5 मिनिटांच्या अंतरावर. आपण साईट व्हिजिटसाठी कधी येऊ शकाल?"
            if intent == "book_site_visit":
                return "नक्कीच! शनिवार किंवा रविवार कोणता दिवस आपल्यासाठी सोयीचा असेल?"
            if not bhk:
                return "आपल्याला 1, 2 की 3 बीएचके फ्लॅट हवा आहे?"
            if not budget:
                return f"आपली {bhk or '2 BHK'} साठी बजेट मर्यादा किती आहे?"
            return "छान! मी आमच्या अधिकृत विक्री प्रतिनिधीशी चर्चा करून आपली वेळ निश्चित करते. इतर काही माहिती हवी आहे का?"

        elif lang == "hi-IN":
            if intent == "permission_granted":
                return "बहुत बढ़िया! हमारे पास वाकड़ ब्रिज के पास 1, 2 और 3 बीएचके फ्लैट्स उपलब्ध हैं। आप कौन सा कॉन्फ़िगरेशन देख रहे हैं?"
            if intent in ("configuration_inquiry", "project_enquiry"):
                return "हमारे पास 1 बीएचके 550 वर्ग फुट, 2 बीएचके 850 वर्ग फुट और 3 बीएचके 1150 वर्ग फुट उपलब्ध है। आप कौन सा विकल्प पसंद करेंगे?"
            if intent == "price_inquiry":
                if bhk == "1 BHK":
                    return "हमारे 1 बीएचके की शुरुआती कीमत 48 लाख रुपये है। क्या आप रहने के लिए देख रहे हैं या निवेश के लिए?"
                elif bhk == "3 BHK":
                    return "हमारे 3 बीएचके की शुरुआती कीमत 98 लाख रुपये है। आप कब तक खरीदने की योजना बना रहे हैं?"
                else:
                    return "हमारे 2 बीएचके की शुरुआती कीमत 72 लाख रुपये और 3 बीएचके 98 लाख से शुरू होती है। क्या आप इस शनिवार सैंपल फ्लैट देखने आ सकते हैं?"
            if intent == "amenities_inquiry":
                return "प्रोजेक्ट में क्लबहाउस, स्विमिंग पूल, जिम, गार्डन और 24 घंटे सुरक्षा उपलब्ध है। क्या आप शनिवार को विजिट करना चाहेंगे?"
            if intent == "location_inquiry":
                return "प्रोजेक्ट वाकड़ ब्रिज के पास, हिंजवड़ी लिंक रोड पर स्थित है, हिंजवड़ी आईटी पार्क से सिर्फ 5 मिनट। क्या आप इस वीकेंड आ सकते हैं?"
            if intent == "book_site_visit":
                return "बिल्कुल! शनिवार या रविवार, कौन सा दिन आपके लिए सुविधाजनक रहेगा?"
            if not bhk:
                return "आप 1, 2 या 3 बीएचके में से क्या देखना पसंद करेंगे?"
            if not budget:
                return f"आपने {bhk or '2 BHK'} में रुचि दिखाई है। आपका अनुमानित बजट क्या है?"
            return "धन्यवाद! मैं सेल्स टीम के साथ आपका स्लॉट रिज़र्व कर रही हूँ। क्या आप कुछ और जानना चाहते हैं?"

        else:  # en-IN
            if intent == "permission_granted":
                if not bhk:
                    return "Great! We have luxurious 1, 2, and 3 BHK homes near Wakad Bridge with world-class amenities. Which configuration are you currently looking for?"
                else:
                    return f"Wonderful! Our {bhk} residences start at indicative pricing from 72 Lakhs. Would this fit within your targeted budget?"
            if intent in ("configuration_inquiry", "project_enquiry"):
                return "We offer spacious 1 BHK of 550 sq.ft., 2 BHK of 850 sq.ft., and 3 BHK of 1,150 sq.ft. carpet area. Which flat size suits your family best?"
            if intent == "price_inquiry":
                if bhk == "1 BHK":
                    return "Our 1 BHK homes start at an indicative price of INR 48 Lakhs. Would you be buying for self-use or investment?"
                elif bhk == "3 BHK":
                    return "Our 3 BHK luxury homes start at an indicative price of INR 98 Lakhs. What is your planned buying timeline?"
                else:
                    return "Our 2 BHK homes start at an indicative INR 72 Lakhs, and 3 BHK from 98 Lakhs. Final pricing is confirmed by our sales desk. Would you like to schedule a site visit this weekend to see the sample flat?"
            if intent == "amenities_inquiry":
                return "The project features a grand clubhouse, swimming pool, fully equipped gym, landscaped gardens, and dedicated covered parking. Would you like to come see the clubhouse this Saturday?"
            if intent == "location_inquiry":
                return "We are located right on Hinjawadi Link Road near Wakad Bridge, just five minutes from Hinjawadi IT Park Phase 1. Would it be convenient for you to visit the site this weekend?"
            if intent == "book_site_visit":
                if not visit_date:
                    return "Certainly! We have guided site visits and sample flat tours available all weekend. Would Saturday or Sunday suit you better?"
                else:
                    return f"Wonderful, I can arrange Saturday for you. What time would work best for your visit, morning around 11 AM or afternoon?"
            if not bhk:
                return "I would be happy to share more details. Are you looking for a 1, 2, or 3 BHK flat?"
            if not budget:
                return f"I have noted your interest in a {bhk}. What budget range are you comfortable with?"
            if not session.facts_collected.get("site_visit_interest"):
                return "Would you be interested in visiting the project this Saturday to view the sample flat?"
            return "Certainly! Let me confirm the appointment slot with our sales desk so we can reserve your tour. Is there anything else you would like to know?"
