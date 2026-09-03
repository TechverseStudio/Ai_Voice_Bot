import soundfile as sf


input_file = "test_audio.wav"
output_file = "test_audio_fixed.wav"

audio, sample_rate = sf.read(input_file)

print("Original sample rate:", sample_rate)
print("Audio shape:", audio.shape)

sf.write(
    output_file,
    audio,
    sample_rate,
    subtype="PCM_16",
)

print("Fixed audio created:", output_file)