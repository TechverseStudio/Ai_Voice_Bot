""" Speech-to-text service.
Responsible for converting customer audio into text."""

class SpeechToText:
    """Base interface for sppech -to-text providers."""

    def transcribe(self,audio_data: bytes)-> str:
        """It is used to convert the audio data into text.
        this methid will be implemented using an stt provider"""

        raise NotImplementedError