"""
Speech-to-Text service using Sarvam AI.
"""

from sarvamai import SarvamAI

from backend.config import SARVAM_API_KEY


class SpeechToText:
    """Speech-to-text service powered by Sarvam AI."""

    def __init__(self):
        self.client = SarvamAI(api_subscription_key=SARVAM_API_KEY)

    def transcribe(self, audio_file_path: str) -> str:
        """Convert an audio file into text using Sarvam AI."""

        with open(audio_file_path, "rb") as audio_file:
            response = self.client.speech_to_text.transcribe(
                file=audio_file,
                model="saaras:v3",
            )

        return response.transcript