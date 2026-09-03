from models.intent_classifier import IntentClassifier


classifier = IntentClassifier()


test_messages = [
    "I want to buy your premium plan",
    "Where is my package?",
    "I am very unhappy with your service",
    "Please connect me to a human",
]


for message in test_messages:
    intent = classifier.predict(message)

    print(f"\nCustomer: {message}")
    print(f"Predicted intent: {intent}")
    