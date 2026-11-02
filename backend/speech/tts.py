import base64
import logging
import os
from sarvamai import SarvamAI

from backend.config import SARVAM_API_KEY, SARVAM_FALLBACK_API_KEY

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {"en-IN", "hi-IN", "mr-IN", "bn-IN", "ta-IN", "te-IN", "gu-IN", "kn-IN", "ml-IN", "od-IN", "pa-IN"}


class TextToSpeech:
    """Convert agent responses into spoken audio using Sarvam Bulbul."""

    def __init__(self, api_key: str | None = None):
        self.primary_key = api_key or SARVAM_API_KEY
        self.fallback_key = SARVAM_FALLBACK_API_KEY
        self.client = SarvamAI(api_subscription_key=self.primary_key or self.fallback_key)
        self.fallback_client = (
            SarvamAI(api_subscription_key=self.fallback_key)
            if (self.fallback_key and self.fallback_key != self.primary_key)
            else None
        )

    def _convert_tts(self, **kwargs):
        try:
            return self.client.text_to_speech.convert(**kwargs)
        except Exception as e:
            if self.fallback_client and ("403" in str(e) or "invalid_api_key" in str(e) or "authentication" in str(e).lower()):
                logger.warning(f"Sarvam TTS primary key failed ({e}), using fallback key")
                return self.fallback_client.text_to_speech.convert(**kwargs)
            raise

    def synthesize(
        self,
        text: str,
        language_code: str = "en-IN",
        output_file: str = "agent_response.wav",
        speaker: str = "shubh",
    ) -> str:
        """Convert text into speech and save it as an audio file."""
        language_code = language_code if language_code in SUPPORTED_LANGUAGES else "en-IN"
        audio = self._convert_tts(
            text=text,
            model="bulbul:v3",
            language_code=language_code,
            speaker=speaker,
        )

        from sarvamai.play import save
        save(audio, output_file)
        return output_file

    def synthesize_bytes(
        self,
        text: str,
        language_code: str = "en-IN",
        speaker: str = "shubh",
        sample_rate: int = 8000,
        codec: str = "linear16",
    ) -> bytes:
        """Synthesize text to raw audio bytes (linear16, wav, or mulaw) without disk I/O."""
        if not text or not text.strip():
            return b""

        language_code = language_code if language_code in SUPPORTED_LANGUAGES else "en-IN"

        try:
            audio = self._convert_tts(
                text=text.strip(),
                model="bulbul:v3",
                language_code=language_code,
                speaker=speaker,
                speech_sample_rate=sample_rate,
                output_audio_codec=codec,
            )

            if not getattr(audio, "audios", None):
                return b""

            chunks = [base64.b64decode(chunk) for chunk in audio.audios]
            return b"".join(chunks)

        except Exception as e:
            logger.error(f"Sarvam TTS synthesis error: {e}")
            raise