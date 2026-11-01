import os

import pytest

from backend.speech.stt import SpeechToText


if os.getenv("RUN_LIVE_SPEECH_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_SPEECH_TESTS=1 and provide test_audio_fixed.wav for live STT",
        allow_module_level=True,
    )

stt = SpeechToText()

text = stt.transcribe("test_audio_fixed.wav")

print("Transcription:")
print(text)