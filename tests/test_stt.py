from backend.speech.stt import SpeechToText


stt = SpeechToText()

text = stt.transcribe("test_audio.wav")

print("Transcription:")
print(text)