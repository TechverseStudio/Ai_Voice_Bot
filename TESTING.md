# Testing

Run offline tests:

```text
PYTHONPATH=. .venv/bin/python -m pytest -q
```

The STT and TTS tests are live integration tests and are skipped by default.
Run them only when `SARVAM_API_KEY` and the required audio fixture are
available:

```text
RUN_LIVE_SPEECH_TESTS=1 PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_stt.py tests/test_tts.py
```

Automated tests never place real outbound calls. Use mock telephony for
provider-independent testing.
