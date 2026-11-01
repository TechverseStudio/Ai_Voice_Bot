"""Context-aware conversation logic for Krishna's AI Property."""

import re
from dataclasses import dataclass, field


@dataclass
class ConversationState:
    """Facts collected during one conversation."""

    facts: dict[str, str] = field(default_factory=dict)
    greeted: bool = False
    turns: int = 0


class RealEstateConversation:
    """Generate concise, knowledge-grounded real-estate replies."""

    def __init__(self) -> None:
        self.state = ConversationState()

    def reply(self, text: str, knowledge: str) -> tuple[str, str]:
        normalized = text.casefold().strip()
        self.state.turns += 1
        self._remember(normalized)
        intent = self._intent(normalized)

        if intent == "do_not_call":
            return "Understood. I will not contact you again. Thank you.", intent
        if intent == "greeting":
            self.state.greeted = True
            return (
                "Hello! Welcome to Krishna's AI Property. How can I help you today?",
                intent,
            )
        if intent == "site_visit":
            self.state.facts["site_visit_interest"] = "yes"
            return "Certainly. What day would be convenient for your site visit?", intent
        if intent == "human_follow_up":
            self.state.facts["human_follow_up"] = "yes"
            return "Certainly. I can arrange a follow-up from our sales team. What time is convenient?", intent
        if intent == "amenities":
            return self._amenities(knowledge), intent
        if intent == "location":
            return self._location(knowledge), intent
        if intent == "price":
            return self._price(knowledge), intent
        if intent == "area":
            return self._area(knowledge), intent
        if intent == "flat_configuration" and self.state.facts.get("bhk"):
            return self._price(knowledge), intent
        if intent in {"flat_configuration", "project_enquiry"}:
            return self._configurations(knowledge), intent
        if intent == "budget":
            return self._budget_reply(), intent
        if intent == "unclear":
            return "I did not catch that clearly. Could you please repeat your question?", intent
        return (
            "I can help with flats, BHK options, indicative pricing, amenities, "
            "location, or a site visit. What would you like to know?",
            intent,
        )

    def _remember(self, text: str) -> None:
        name = re.search(r"\b(?:my name is|i am|i'm)\s+([a-z][a-z -]{1,40})", text)
        if name:
            self.state.facts["name"] = name.group(1).strip(" .")
        bhk = re.search(r"\b([1234])\s*bhk\b", text)
        if bhk:
            self.state.facts["bhk"] = f"{bhk.group(1)} BHK"
        budget = re.search(
            r"\b(?:budget(?: is| of)?|under|around|up to)\s*(?:inr|rs\.?|₹)?\s*([0-9][0-9.,]*)\s*(lakh|lakhs|crore|cr)?",
            text,
        )
        if budget:
            self.state.facts["budget"] = " ".join(part for part in budget.groups() if part)
        if "investment" in text:
            self.state.facts["purpose"] = "investment"
        elif "self use" in text or "live in" in text:
            self.state.facts["purpose"] = "self-use"
        for timeline in ("this month", "next month", "three months", "six months", "this year", "next year"):
            if timeline in text:
                self.state.facts["timeline"] = timeline
                break

    def _intent(self, text: str) -> str:
        if any(value in text for value in ("stop calling", "do not call", "don't call", "remove my number", "not interested")):
            return "do_not_call"
        if any(value in text for value in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening")) and len(text.split()) <= 12:
            return "greeting"
        if any(value in text for value in ("site visit", "visit the property", "visit the flat", "see the property", "schedule a visit")):
            return "site_visit"
        if any(value in text for value in ("human", "sales representative", "call me back", "callback", "person")):
            return "human_follow_up"
        if any(value in text for value in ("amenit", "play area", "fitness", "garden", "parking", "security", "community hall")):
            return "amenities"
        if any(value in text for value in ("where", "located", "location", "address", "route", "direction", "reach", "near")):
            return "location"
        if any(value in text for value in ("price", "cost", "rate", "how much", "starting", "lakh", "budget")):
            return "budget" if "budget" in text and not any(value in text for value in ("price", "cost", "rate", "how much")) else "price"
        if any(value in text for value in ("area", "square feet", "sq ft", "size", "carpet")):
            return "area"
        if re.search(r"\b[1234]\s*bhk\b", text) or "configuration" in text:
            return "price" if any(value in text for value in ("price", "cost", "rate", "how much")) else "flat_configuration"
        if any(value in text for value in ("flat", "flats", "apartment", "project", "property", "house", "home")):
            return "project_enquiry"
        if len(text.split()) < 2:
            return "unclear"
        if any(value in text for value in ("buy", "purchase", "looking for", "interested")):
            return "project_enquiry"
        return "general"

    @staticmethod
    def _lines(knowledge: str, prefix: str) -> list[str]:
        return [line.strip("- ").strip() for line in knowledge.splitlines() if line.strip().lower().startswith(prefix)]

    def _configurations(self, knowledge: str) -> str:
        options = [
            line.strip("- ").strip()
            for line in knowledge.splitlines()
            if re.match(r"- [1234] BHK:", line)
        ]
        if not options:
            return "I can help with the available BHK options. Which configuration are you considering?"
        labels = [re.match(r"([1234] BHK)", item).group(1) for item in options]
        return f"We have {', '.join(labels)} flat options. Which BHK are you looking for?"

    def _price(self, knowledge: str) -> str:
        bhk = self.state.facts.get("bhk")
        lines = [
            line.strip("- ").strip()
            for line in knowledge.splitlines()
            if re.match(r"- [1234] BHK:", line)
        ]
        selected = next((line for line in lines if bhk and line.startswith(bhk)), None)
        if selected:
            return f"The indicative {selected.rstrip('.')}. Final pricing and availability must be confirmed by an authorised sales representative. Would you like to know about the amenities or location?"
        return "We have indicative pricing for 1, 2, and 3 BHK homes. Which BHK configuration and budget are you considering?"

    def _area(self, knowledge: str) -> str:
        bhk = self.state.facts.get("bhk")
        lines = [line.strip("- ").strip() for line in knowledge.splitlines() if re.match(r"- [1234] BHK:", line)]
        selected = next((line for line in lines if bhk and line.startswith(bhk)), None)
        return f"The indicative {selected}." if selected else "The available homes range from approximately 550 to 1,150 square feet. Which BHK are you considering?"

    @staticmethod
    def _amenities(knowledge: str) -> str:
        match = re.search(r"The sample amenities are ([^.]+)\.", knowledge)
        amenities = " ".join(match.group(1).split()) if match else "a children's play area and fitness room"
        return f"The project information includes {amenities}. Would you like to know anything else about the project?"

    @staticmethod
    def _location(knowledge: str) -> str:
        match = re.search(r"The sample site address is: ([^.]+)\.", knowledge)
        location = " ".join(match.group(1).split()) if match else "Pimpri-Chinchwad, Pune"
        return f"The sample project is located at {location}. Would you be interested in scheduling a site visit?"

    def _budget_reply(self) -> str:
        budget = self.state.facts.get("budget")
        return f"I have noted your budget of {budget}. Which BHK would you prefer?" if budget else "What budget range would you like to consider?"
