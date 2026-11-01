"""Comprehensive Post-Call Intelligence and Explainable Lead Scoring Engine."""

import re
from typing import Any


def analyze_conversation(
    transcript: str,
    customer_name_fallback: str = "",
    locality_fallback: str = "",
) -> dict[str, Any]:
    """Analyze full call transcript, extract validated requirements, objections,

    evidence citations, explainable score, and lead classification.
    """
    text = transcript.strip()
    lowered = text.casefold()

    if len(lowered) < 10:
        return {
            "score": None,
            "category": "Insufficient Data",
            "score_breakdown": {"reason": "Call ended before meaningful dialogue"},
            "requirements": {
                "customer_name": customer_name_fallback or None,
                "bhk": None,
                "budget": None,
                "preferred_locality": locality_fallback or None,
                "property_purpose": None,
                "buying_timeline": None,
                "current_accommodation": None,
                "financing_requirement": None,
                "amenities_preferred": None,
                "project_interest": "Krishna's AI Property",
                "site_visit_interest": None,
                "preferred_meeting_date": None,
                "preferred_meeting_time": None,
                "follow_up_preference": None,
                "customer_consent": None,
            },
            "evidence": {},
            "objections": [],
            "questions_asked": [],
            "summary": "Call was too short or did not produce substantive speech.",
            "follow_up": "Verify phone reachability and retry only with consent.",
            "next_action": "Check phone number and attempt callback during permitted hours.",
        }

    # 1. Do Not Call / Opt Out Detection
    dnd_match = re.search(
        r"\b(do not call|don't call|stop calling|remove my number|never call|block my number|opt out|dnd)\b",
        lowered,
    )
    if dnd_match:
        return {
            "score": 0,
            "category": "Do Not Call",
            "score_breakdown": {"opt_out_penalty": "Immediate zero score due to DND request"},
            "requirements": {
                "customer_name": customer_name_fallback or None,
                "bhk": None,
                "budget": None,
                "preferred_locality": locality_fallback or None,
                "property_purpose": None,
                "buying_timeline": None,
                "current_accommodation": None,
                "financing_requirement": None,
                "amenities_preferred": None,
                "project_interest": "Krishna's AI Property",
                "site_visit_interest": False,
                "preferred_meeting_date": None,
                "preferred_meeting_time": None,
                "follow_up_preference": "None - Opted Out",
                "customer_consent": False,
            },
            "evidence": {"opt_out": f"Customer stated: '{dnd_match.group(0)}'"},
            "objections": ["Requested permanent removal from calling list"],
            "questions_asked": [],
            "summary": "Customer explicitly requested not to be contacted again. Number registered on DND list.",
            "follow_up": "Do not call. Honour opt-out immediately.",
            "next_action": "Permanent DND registration; contact marked as opted out in CRM.",
        }

    # 2. Callback Requested Detection
    callback_match = re.search(
        r"\b(call me back|call later|busy right now|in a meeting|call tomorrow|call after \d+|callback|driving right now)\b",
        lowered,
    )
    if callback_match and not any(w in lowered for w in ("visit", "buy", "purchase", "bhk")):
        return {
            "score": 30,
            "category": "Callback Requested",
            "score_breakdown": {"callback_bonus": 30, "reason": "Customer volunteered to speak at another time"},
            "requirements": {
                "customer_name": customer_name_fallback or None,
                "bhk": None,
                "budget": None,
                "preferred_locality": locality_fallback or None,
                "property_purpose": None,
                "buying_timeline": None,
                "current_accommodation": None,
                "financing_requirement": None,
                "amenities_preferred": None,
                "project_interest": "Krishna's AI Property",
                "site_visit_interest": None,
                "preferred_meeting_date": None,
                "preferred_meeting_time": None,
                "follow_up_preference": "Callback",
                "customer_consent": True,
            },
            "evidence": {"callback": f"Customer indicated: '{callback_match.group(0)}'"},
            "objections": ["Currently occupied / requested callback"],
            "questions_asked": [],
            "summary": "Customer was occupied and requested a follow-up callback.",
            "follow_up": "Schedule follow-up call at requested time.",
            "next_action": "Create callback reminder on sales desk queue.",
        }

    # 3. Not Interested Detection
    not_interested_match = re.search(
        r"\b(not interested|not looking|no need|already bought|bought another property|wrong number)\b",
        lowered,
    )
    if not_interested_match and not any(w in lowered for w in ("visit", "buy", "bhk", "send details")):
        return {
            "score": 10,
            "category": "Not Interested",
            "score_breakdown": {"not_interested_score": 10, "reason": "Politely declined property offerings"},
            "requirements": {
                "customer_name": customer_name_fallback or None,
                "bhk": None,
                "budget": None,
                "preferred_locality": locality_fallback or None,
                "property_purpose": None,
                "buying_timeline": None,
                "current_accommodation": None,
                "financing_requirement": None,
                "amenities_preferred": None,
                "project_interest": "Krishna's AI Property",
                "site_visit_interest": False,
                "preferred_meeting_date": None,
                "preferred_meeting_time": None,
                "follow_up_preference": "No follow-up",
                "customer_consent": False,
            },
            "evidence": {"disinterest": f"Customer stated: '{not_interested_match.group(0)}'"},
            "objections": ["Not actively in market for real estate purchase"],
            "questions_asked": [],
            "summary": "Customer stated they are currently not interested in purchasing property.",
            "follow_up": "Archive enquiry; no immediate follow-up required.",
            "next_action": "Mark as Not Interested in CRM; retain for future general project announcements.",
        }

    # 4. Extract Customer Requirements with Exact Evidence Citations
    evidence = {}

    # Name
    name = customer_name_fallback or None
    name_m = re.search(r"\b(?:my name is|i am|this is|speaking with)\s+([A-Za-z][A-Za-z\s]{1,30})", text, re.I)
    if name_m:
        extracted_name = name_m.group(1).strip()
        if len(extracted_name.split()) <= 3 and not any(w in extracted_name.lower() for w in ("looking", "interested", "calling")):
            name = extracted_name
            evidence["customer_name"] = name_m.group(0)

    # Configuration / BHK
    bhk = None
    bhk_digit = None
    bhk_m = re.search(r"\b([1-4])\s*(?:bhk|bedroom|bed)?\b", lowered)
    if bhk_m and ("bhk" in lowered or "bedroom" in lowered or "flat" in lowered or "apartment" in lowered):
        bhk_digit = bhk_m.group(1)
        bhk = f"{bhk_digit} BHK"
        evidence["bhk"] = bhk_m.group(0)

    # Budget
    budget = None
    budget_m = re.search(
        r"(?:budget(?:\s+is|\s+of)?|around|under|up to|approx(?:imately)?)\s*(?:inr|rs\.?|₹)?\s*([0-9][0-9.,]*)\s*(lakh|lakhs|crore|crores|cr)?",
        lowered,
    )
    if not budget_m:
        budget_m = re.search(r"\b([0-9]{2,3})\s*(?:lakh|lakhs|cr|crore)\b", lowered)

    if budget_m:
        parts = [p for p in budget_m.groups() if p]
        budget = " ".join(parts).title()
        if not any(unit in budget.lower() for unit in ("lakh", "cr", "crore")):
            budget = f"{budget} Lakhs"
        evidence["budget"] = budget_m.group(0)

    # Preferred Locality
    locality = locality_fallback or None
    loc_m = re.search(
        r"\b(?:in|near|around|at)\s+([A-Za-z][A-Za-z\s]{2,25}?)(?=\s+(?:with|for|and|budget|this|that|locality|road)\b|[,.]|$)",
        text,
        re.I,
    )
    if loc_m:
        cand = loc_m.group(1).strip()
        if cand.lower() not in ("pune", "mumbai", "india", "property", "site", "project", "flats", "this"):
            locality = cand
            evidence["preferred_locality"] = loc_m.group(0)

    # Purpose
    purpose = None
    if "investment" in lowered:
        purpose = "Investment"
        evidence["property_purpose"] = "Customer mentioned: 'investment'"
    elif any(phrase in lowered for phrase in ("self use", "live in", "own stay", "family", "personal")):
        purpose = "Self-Use"
        evidence["property_purpose"] = "Customer mentioned buying for self-use / family"

    # Timeline
    timeline = None
    for pattern, label in [
        (r"\b(immediate|ready to move|this month|within 30 days)\b", "Immediate (<1 month)"),
        (r"\b(next month|1 to 2 months|two months|within 2 months|within 3 months|three months)\b", "1-3 Months"),
        (r"\b(6 months|six months|by end of year|later this year)\b", "3-6 Months"),
        (r"\b(next year|after a year)\b", ">6 Months"),
        (r"\b(this year|within this year)\b", "This Year"),
    ]:
        tm = re.search(pattern, lowered)
        if tm:
            timeline = label
            evidence["buying_timeline"] = tm.group(0)
            break

    # Financing
    financing = None
    if any(phrase in lowered for phrase in ("home loan", "bank loan", "mortgage", "loan required", "loan needed")):
        financing = "Bank Loan Required"
        evidence["financing_requirement"] = "Customer volunteered: home loan needed"
    elif any(phrase in lowered for phrase in ("self funded", "own funds", "no loan", "all cash")):
        financing = "Self-Funded"
        evidence["financing_requirement"] = "Customer volunteered: self-funded"

    # Amenities
    amenities = []
    amenity_keywords = ["gym", "fitness", "swimming pool", "clubhouse", "garden", "play area", "parking", "security", "lift", "balcony"]
    for ak in amenity_keywords:
        if ak in lowered:
            amenities.append(ak.title())
    if amenities:
        evidence["amenities_preferred"] = f"Customer expressed interest in {', '.join(amenities)}"

    # Site Visit Interest & Preferred Slot
    site_visit_interest = False
    site_visit_date = None
    site_visit_time = None

    if any(phrase in lowered for phrase in ("site visit", "visit the property", "visit the site", "come and see", "visit this weekend", "schedule a visit", "book visit", "visit")):
        site_visit_interest = True
        evidence["site_visit_interest"] = "Customer expressed interest in visiting the property"

        # Check date
        for d_cand in ["saturday", "sunday", "tomorrow", "this weekend", "weekend", "monday", "friday"]:
            if d_cand in lowered:
                site_visit_date = d_cand.title()
                evidence["preferred_meeting_date"] = f"Customer requested date: {d_cand}"
                break

        # Check time
        time_m = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\bmorning\b|\bafternoon\b|\bevening\b)", lowered)
        if time_m:
            site_visit_time = time_m.group(0).upper()
            evidence["preferred_meeting_time"] = f"Customer preferred time: {site_visit_time}"

    # Objections
    objections = []
    if any(p in lowered for p in ("price is high", "too expensive", "costly", "out of budget", "budget is less")):
        objections.append("Pricing concern - customer feels indicative rates are higher than target")
    if any(p in lowered for p in ("possession late", "delayed", "when will it complete", "too late")):
        objections.append("Possession timeline concern")
    if any(p in lowered for p in ("traffic", "too far", "far from highway", "location far")):
        objections.append("Location distance concern")
    if any(p in lowered for p in ("carpet area", "small room", "compact")):
        objections.append("Unit dimensions / carpet area verification needed")

    # Questions Asked
    questions = []
    for line in text.splitlines():
        if "?" in line:
            questions.append(line.strip())
    if not questions:
        for q_pattern in [r"(what is the [a-z\s]+)", r"(where is [a-z\s]+)", r"(how much [a-z\s]+)", r"(when is [a-z\s]+)"]:
            qm = re.findall(q_pattern, lowered)
            questions.extend([q.strip() + "?" for q in qm[:2]])

    # 5. Explainable Lead Score Computation (0-100)
    positive = {
        "buying": any(w in lowered for w in ("buy", "purchase", "looking for", "interested in", "want to invest", "planning to take")),
        "budget": bool(budget),
        "requirements": bool(bhk or locality),
        "timeline": bool(timeline),
        "site_visit": bool(site_visit_interest),
        "follow_up": any(w in lowered for w in ("sales representative", "callback", "human", "call me back")),
    }
    score_breakdown = {
        "buying_intent": 25 if positive["buying"] else 0,
        "budget_verified": 20 if positive["budget"] else 0,
        "requirements_clarity": 20 if positive["requirements"] else 0,
        "timeline_stated": 10 if positive["timeline"] else 0,
        "site_visit_intent": 15 if positive["site_visit"] else 0,
        "follow_up_requested": 10 if positive["follow_up"] else 0,
    }
    total_score = sum(score_breakdown.values())

    # Classification
    if total_score >= 70:
        category = "Hot"
        follow_up = "Priority human sales handoff within 1 hour; confirm site visit slot."
        next_action = f"Assign Senior Specialist Rohit Verma. Dispatch brochure & route pin for {site_visit_date or 'weekend'} site visit."
    elif total_score >= 40:
        category = "Warm"
        follow_up = "Send WhatsApp project brochure and floor plan options; follow up in 48 hours."
        next_action = f"Send {bhk or '2/3 BHK'} floor plan PDF & indicative pricing sheet on WhatsApp; invite for weekend open house."
    else:
        category = "Cold"
        follow_up = "Nurture with monthly new-phase development updates."
        next_action = "Add to monthly drip email campaign for Pimpri-Chinchwad real estate launches."

    # Summary
    summary_parts = []
    if name:
        summary_parts.append(f"Spoke with {name}.")
    if bhk and budget:
        summary_parts.append(f"Looking for a {bhk} in {locality or 'Pune'} with budget {budget}.")
    elif bhk:
        summary_parts.append(f"Enquired regarding {bhk} inventory.")
    if purpose:
        summary_parts.append(f"Intended for {purpose.lower()}.")
    if timeline:
        summary_parts.append(f"Buying horizon is {timeline}.")
    if site_visit_interest:
        summary_parts.append(f"Agreed to site visit on {site_visit_date or 'upcoming weekend'} at {site_visit_time or 'convenient slot'}.")
    if objections:
        summary_parts.append(f"Key objection: {objections[0]}.")

    summary = " ".join(summary_parts) if summary_parts else f"Customer interacted regarding project details. Interest score: {total_score}/100."

    return {
        "score": total_score,
        "category": category,
        "score_breakdown": score_breakdown,
        "requirements": {
            "customer_name": name,
            "name": name,
            "bhk": bhk_digit if bhk_digit else (bhk or None),
            "bhk_formatted": bhk,
            "budget": budget,
            "location": locality,
            "preferred_locality": locality,
            "purpose": purpose,
            "property_purpose": purpose,
            "timeline": timeline,
            "buying_timeline": timeline,
            "current_accommodation": None,
            "financing_requirement": financing,
            "amenities_preferred": ", ".join(amenities) if amenities else None,
            "project_interest": "Krishna's AI Property - Wakad",
            "site_visit": "site visit" if site_visit_interest else None,
            "site_visit_interest": site_visit_interest,
            "preferred_meeting_date": site_visit_date,
            "preferred_meeting_time": site_visit_time,
            "follow_up_preference": "Site Visit & WhatsApp" if site_visit_interest else "WhatsApp / Call",
            "customer_consent": True,
        },
        "evidence": evidence,
        "objections": objections,
        "questions_asked": questions,
        "summary": summary,
        "follow_up": follow_up,
        "next_action": next_action,
    }
