from models.intent_classifier import IntentClassifier
from backend.agent.decision_engine import DecisionEngine


classifier = IntentClassifier()
decision_engine = DecisionEngine()


test_messages = [
    "I want to buy your premium plan",
    "Where is my package?",
    "I want my money back",
    "Please connect me to a human",
]


for message in test_messages:
    intent = classifier.predict(message)
    action = decision_engine.decide(intent)

    print(f"\nCustomer: {message}")
    print(f"Intent: {intent}")
    print(f"Action: {action}")