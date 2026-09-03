"""
Text-to-Speech service using Sarvam AI.
"""

from sarvamai import SarvamAI

from backend.config import SARVAM_API_KEY


class TextToSpeech:
    """Convert agent responses into spoken audio."""

    def __init__(self):
        self.client = SarvamAI(
            api_subscription_key=SARVAM_API_KEY
        )

    def synthesize(
        self,
        text: str,
        language_code: str = "en-IN",
        output_file: str = "agent_response.wav",
    ) -> str:
        """
        Convert text into speech and save it as an audio file.
        """

        audio = self.client.text_to_speech.convert(
            text=text,
            model="bulbul:v3",
            language_code=language_code,
            speaker="shubh",
        )

        from sarvamai.play import save

        save(audio, output_file)

        return output_file