from models.intent_classifier import IntentClassifier
from backend.agent.decision_engine import DecisionEngine
from backend.agent.response_generator import ResponseGenerator


classifier = IntentClassifier()
decision_engine = DecisionEngine()
response_generator = ResponseGenerator()


test_messages = [
    "I want to buy your premium plan",
    "Where is my package?",
    "I want my money back",
    "Please connect me to a human",
]


for message in test_messages:
    intent = classifier.predict(message)
    action = decision_engine.decide(intent)
    response = response_generator.generate(intent, action)

    print("\nCustomer:", message)
    print("Intent:", intent)
    print("Action:", action)
    print("Agent:", response)