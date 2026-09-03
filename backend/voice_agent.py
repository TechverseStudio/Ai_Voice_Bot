"""
Complete local voice-agent pipeline.

Microphone -> STT -> Intent -> Decision -> Response -> TTS -> Playback
"""

import winsound

import sounddevice as sd
import soundfile as sf

from backend.speech.stt import SpeechToText
from backend.speech.tts import TextToSpeech
from models.intent_classifier import IntentClassifier
from backend.agent.decision_engine import DecisionEngine
from backend.agent.response_generator import ResponseGenerator


DURATION = 7
SAMPLE_RATE = 16000

INPUT_AUDIO = "user_voice.wav"
OUTPUT_AUDIO = "agent_response.wav"


class VoiceAgent:
    """Complete voice interaction pipeline."""

    def __init__(self):
        self.stt = SpeechToText()
        self.classifier = IntentClassifier()
        self.decision_engine = DecisionEngine()
        self.response_generator = ResponseGenerator()
        self.tts = TextToSpeech()

    def record_voice(self):
        """Record the customer's voice."""

        print("\n🎤 Speak now...")

        audio = sd.rec(
            int(DURATION * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )

        sd.wait()

        sf.write(
            INPUT_AUDIO,
            audio,
            SAMPLE_RATE,
            subtype="PCM_16",
        )

        print("Recording completed.")

    def process(self):
        """Run the complete AI pipeline."""

        # 1. Record customer voice
        self.record_voice()

        # 2. Speech-to-text
        print("\n📝 Converting speech to text...")
        text = self.stt.transcribe(INPUT_AUDIO)

        print("Customer:", text)

        # 3. Intent classification
        print("\n🧠 Detecting intent...")
        intent = self.classifier.predict(text)

        print("Intent:", intent)

        # 4. Decision making
        print("\n⚙️ Selecting action...")
        action = self.decision_engine.decide(intent)

        print("Action:", action)

        # 5. Generate response
        print("\n💬 Generating response...")
        response = self.response_generator.generate(
            intent,
            action,
        )

        print("Agent:", response)

        # 6. Text-to-speech
        print("\n🔊 Generating voice response...")
        self.tts.synthesize(
            text=response,
            language_code="en-IN",
            output_file=OUTPUT_AUDIO,
        )

        print("Response audio generated:", OUTPUT_AUDIO)

        # 7. Automatically play response
        print("\n🔊 Playing response...")
        winsound.PlaySound(
            OUTPUT_AUDIO,
            winsound.SND_FILENAME,
        )

        print("Playback completed.")

        return text, intent, action, response


if __name__ == "__main__":
    agent = VoiceAgent()
    agent.process()