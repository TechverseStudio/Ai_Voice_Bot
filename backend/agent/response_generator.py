"""
Generate customer-facing responses based on
the detected intent and selected action.
"""


class ResponseGenerator:
    """Generate responses for the AI voice agent."""

    def generate(self, intent: str, action: str) -> str:
        """Generate a response based on intent and action."""

        responses = {
            "PRODUCT_INQUIRY": (
                "Sure, I can help you with information about our "
                "products and services. What would you like to know?"
            ),
            "PURCHASE_INTENT": (
                "Great! I can help you with your purchase. "
                "Which product or plan are you interested in?"
            ),
            "BOOK_APPOINTMENT": (
                "Sure, I can help you schedule an appointment. "
                "What date and time would you prefer?"
            ),
            "CANCEL_APPOINTMENT": (
                "I can help you cancel your appointment. "
                "Please provide your appointment details."
            ),
            "COMPLAINT": (
                "I'm sorry you're facing this issue. "
                "Please tell me a little more about the problem."
            ),
            "REFUND_REQUEST": (
                "I can help you with your refund request. "
                "Please provide your order details."
            ),
            "ORDER_STATUS": (
                "Sure, I can help you check your order status. "
                "Please provide your order ID."
            ),
            "HUMAN_SUPPORT": (
                "Certainly. I'll connect you with a customer support agent."
            ),
        }

        return responses.get(
            intent,
            "I'm sorry, I didn't understand that. Could you please repeat?"
        )