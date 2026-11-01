import os

import pytest

from backend.speech.tts import TextToSpeech


if os.getenv("RUN_LIVE_SPEECH_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_SPEECH_TESTS=1 to run the live TTS test",
        allow_module_level=True,
    )

tts = TextToSpeech()

output_file = tts.synthesize(
    text="Hello! I am your AI voice assistant. How can I help you today?",
    language_code="en-IN",
    output_file="agent_response.wav",
)

print("Speech generated successfully.")
print("Audio file:", output_file)