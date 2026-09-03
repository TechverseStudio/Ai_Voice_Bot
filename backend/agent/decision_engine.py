"""
Decision engine for the AI voice agent.

Converts customer intent into an agent action.
"""


class DecisionEngine:
    """Decide what the voice agent should do."""

    def decide(self, intent: str) -> str:
        """Return an action based on the detected intent."""

        decisions = {
            "PRODUCT_INQUIRY": "PROVIDE_PRODUCT_INFORMATION",
            "PURCHASE_INTENT": "START_SALES_FLOW",
            "BOOK_APPOINTMENT": "SCHEDULE_APPOINTMENT",
            "CANCEL_APPOINTMENT": "CANCEL_APPOINTMENT",
            "COMPLAINT": "HANDLE_COMPLAINT",
            "REFUND_REQUEST": "START_REFUND_PROCESS",
            "ORDER_STATUS": "CHECK_ORDER_STATUS",
            "HUMAN_SUPPORT": "ESCALATE_TO_HUMAN",
        }

        return decisions.get(intent, "ASK_FOR_CLARIFICATION")