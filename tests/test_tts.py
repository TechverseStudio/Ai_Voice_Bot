from backend.speech.tts import TextToSpeech


tts = TextToSpeech()

output_file = tts.synthesize(
    text="Hello! I am your AI voice assistant. How can I help you today?",
    language_code="en-IN",
    output_file="agent_response.wav",
)

print("Speech generated successfully.")
print("Audio file:", output_file)