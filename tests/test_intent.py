from models.intent_classifier import IntentClassifier


classifier = IntentClassifier()

test_messages = [
    "मला माझ्या ऑर्डरची माहिती हवी आहे.",
    "माझी ऑर्डर कुठे आहे?",
    "मला प्रीमियम प्लॅन खरेदी करायचा आहे.",
    "मुझे अपना पैसा वापस चाहिए",
    "मुझे किसी इंसान से बात करनी है",
    "I want to buy the premium plan",
    "Where is my package?",
]


for message in test_messages:
    intent = classifier.predict(message)

    print(f"\nCustomer: {message}")
    print(f"Predicted intent: {intent}")