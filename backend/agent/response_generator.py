"""
Generate multilingual customer-facing responses.
"""


class ResponseGenerator:
    """Generate responses based on intent, action, and language."""

    def generate(
        self,
        intent: str,
        action: str,
        language: str = "en-IN",
    ) -> str:
        """Generate a response in the customer's language."""

        responses = {
            "en-IN": {
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
            },

            "mr-IN": {
                "PRODUCT_INQUIRY": (
                    "नक्की. मी तुम्हाला आमच्या उत्पादनांची आणि "
                    "सेवांची माहिती देऊ शकतो. तुम्हाला काय जाणून घ्यायचे आहे?"
                ),
                "PURCHASE_INTENT": (
                    "नक्की. मी तुम्हाला खरेदी करण्यात मदत करू शकतो. "
                    "तुम्हाला कोणते उत्पादन किंवा प्लॅन घ्यायचा आहे?"
                ),
                "BOOK_APPOINTMENT": (
                    "नक्की. मी तुमची अपॉइंटमेंट बुक करण्यात मदत करू शकतो. "
                    "तुम्हाला कोणती तारीख आणि वेळ हवी आहे?"
                ),
                "CANCEL_APPOINTMENT": (
                    "मी तुमची अपॉइंटमेंट रद्द करण्यात मदत करू शकतो. "
                    "कृपया तुमची अपॉइंटमेंटची माहिती द्या."
                ),
                "COMPLAINT": (
                    "तुम्हाला या समस्येला सामोरे जावे लागत आहे याबद्दल मला वाईट वाटते. "
                    "कृपया समस्येबद्दल थोडी अधिक माहिती द्या."
                ),
                "REFUND_REQUEST": (
                    "मी तुम्हाला रिफंड मिळवण्यात मदत करू शकतो. "
                    "कृपया तुमच्या ऑर्डरची माहिती द्या."
                ),
                "ORDER_STATUS": (
                    "नक्की. मी तुमच्या ऑर्डरचा स्टेटस तपासण्यात मदत करू शकतो. "
                    "कृपया तुमचा ऑर्डर आयडी द्या."
                ),
                "HUMAN_SUPPORT": (
                    "नक्की. मी तुमचा कॉल कस्टमर सपोर्ट एजंटकडे ट्रान्सफर करतो."
                ),
            },

            "hi-IN": {
                "PRODUCT_INQUIRY": (
                    "ज़रूर। मैं आपको हमारे उत्पादों और सेवाओं के बारे में "
                    "जानकारी दे सकता हूँ। आप क्या जानना चाहते हैं?"
                ),
                "PURCHASE_INTENT": (
                    "ज़रूर। मैं आपकी खरीदारी में मदद कर सकता हूँ। "
                    "आप कौन सा प्रोडक्ट या प्लान खरीदना चाहते हैं?"
                ),
                "BOOK_APPOINTMENT": (
                    "ज़रूर। मैं आपकी अपॉइंटमेंट बुक करने में मदद कर सकता हूँ। "
                    "आप किस तारीख और समय को पसंद करेंगे?"
                ),
                "CANCEL_APPOINTMENT": (
                    "मैं आपकी अपॉइंटमेंट रद्द करने में मदद कर सकता हूँ। "
                    "कृपया अपनी अपॉइंटमेंट की जानकारी दें।"
                ),
                "COMPLAINT": (
                    "आपको इस समस्या का सामना करना पड़ रहा है, इसका मुझे अफसोस है। "
                    "कृपया समस्या के बारे में थोड़ी और जानकारी दें।"
                ),
                "REFUND_REQUEST": (
                    "मैं आपके रिफंड में मदद कर सकता हूँ। "
                    "कृपया अपने ऑर्डर की जानकारी दें।"
                ),
                "ORDER_STATUS": (
                    "ज़रूर। मैं आपके ऑर्डर का स्टेटस चेक करने में मदद कर सकता हूँ। "
                    "कृपया अपना ऑर्डर आईडी बताएं।"
                ),
                "HUMAN_SUPPORT": (
                    "ज़रूर। मैं आपकी कॉल कस्टमर सपोर्ट एजेंट को ट्रांसफर करता हूँ।"
                ),
            },
        }

        language_responses = responses.get(
            language,
            responses["en-IN"],
        )

        return language_responses.get(
            intent,
            language_responses.get(
                "HUMAN_SUPPORT",
                "Please contact customer support.",
            ),
        )