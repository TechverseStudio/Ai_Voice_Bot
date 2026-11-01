from backend.agent.real_estate import RealEstateConversation
from backend import web


KNOWLEDGE = open("data/knowledge/krishnas-ai-property.md", encoding="utf-8").read()


def test_real_estate_conversation_remembers_bhk_and_answers_relevant_questions():
    conversation = RealEstateConversation()
    greeting, _ = conversation.reply("Hello, my name is Harsh.", KNOWLEDGE)
    flats, _ = conversation.reply("I want to know about flats.", KNOWLEDGE)
    price, _ = conversation.reply("I want a 2 BHK.", KNOWLEDGE)
    amenities, _ = conversation.reply("What amenities are available?", KNOWLEDGE)

    assert "order" not in greeting.lower()
    assert "1 BHK" in flats and "2 BHK" in flats
    assert "850 square feet" in price
    assert "children's play area" in amenities


def test_real_estate_conversation_returns_short_grounded_location_answer():
    conversation = RealEstateConversation()
    response, intent = conversation.reply("Where is the project located?", KNOWLEDGE)

    assert intent == "location"
    assert "Wakad Bridge" in response
    assert len(response) < 300
    assert "Agent rules" not in response


def test_voice_reply_returns_generated_audio_bytes(monkeypatch):
    def fake_synthesize(text, language, output_file):
        open(output_file, "wb").write(b"RIFF-test-audio")

    monkeypatch.setattr(web.tts, "synthesize", fake_synthesize)
    response, audio = web.asyncio.run(
        web._create_voice_reply("What amenities are available?", "en-IN")
    )

    assert "children's play area" in response
    assert audio == b"RIFF-test-audio"
