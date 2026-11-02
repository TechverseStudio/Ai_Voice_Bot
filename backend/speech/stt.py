import io
import logging
import os
import wave
from typing import BinaryIO, Union

from sarvamai import SarvamAI

from backend.config import SARVAM_API_KEY, SARVAM_FALLBACK_API_KEY

logger = logging.getLogger(__name__)


class SpeechToText:
    """Speech-to-text service powered by Sarvam AI Saaras."""

    def __init__(self, api_key: str | None = None):
        self.primary_key = api_key or SARVAM_API_KEY
        self.fallback_key = SARVAM_FALLBACK_API_KEY
        self.client = SarvamAI(api_subscription_key=self.primary_key or self.fallback_key)
        self.fallback_client = (
            SarvamAI(api_subscription_key=self.fallback_key)
            if (self.fallback_key and self.fallback_key != self.primary_key)
            else None
        )

    def _call_stt(self, file_tuple, model, language_code):
        try:
            return self.client.speech_to_text.transcribe(
                file=file_tuple,
                model=model,
                language_code=language_code,
                mode="transcribe",
            )
        except Exception as e:
            if self.fallback_client and ("403" in str(e) or "invalid_api_key" in str(e) or "authentication" in str(e).lower()):
                logger.warning(f"Sarvam STT primary key failed ({e}), using fallback key")
                return self.fallback_client.speech_to_text.transcribe(
                    file=file_tuple,
                    model=model,
                    language_code=language_code,
                    mode="transcribe",
                )
            raise

    def transcribe(
        self,
        audio_source: Union[str, bytes, BinaryIO],
        language_code: str = "unknown",
        model: str = "saaras:v3",
    ) -> dict[str, str]:
        """Convert audio file path, raw bytes, or stream into transcribed text and language."""
        if isinstance(audio_source, str):
            if not os.path.exists(audio_source):
                raise FileNotFoundError(f"Audio file '{audio_source}' not found")
            with open(audio_source, "rb") as f:
                file_tuple = (os.path.basename(audio_source), f.read(), "audio/wav")
                response = self._call_stt(file_tuple, model, language_code)
        elif isinstance(audio_source, bytes):
            file_tuple = ("audio.wav", audio_source, "audio/wav")
            response = self._call_stt(file_tuple, model, language_code)
        else:
            data = audio_source.read()
            file_tuple = ("audio.wav", data, "audio/wav")
            response = self._call_stt(file_tuple, model, language_code)

        return {
            "text": getattr(response, "transcript", "") or "",
            "language": getattr(response, "language_code", language_code) or language_code,
        }

    def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
        language_code: str = "unknown",
    ) -> dict[str, str]:
        """Convert raw linear PCM bytes (s16le) to WAV container in memory and transcribe."""
        if not pcm_bytes:
            return {"text": "", "language": language_code}

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)

        return self.transcribe(buf.getvalue(), language_code=language_code)