# API

- `GET /api/health` - application and telephony readiness.
- `GET /api/telephony/status` - provider mode and missing configuration.
- `GET /api/leads` - list stored leads.
- `POST /api/leads` - create a lead using multipart fields `name`, `area`,
  and `phone_number`.
- `POST /api/outbound/test-call` - request one test call with JSON
  `{"lead_id": 1}`. In mock mode this creates a `simulated_accepted` call and
  never dials a number.
- `GET /api/leads/export` - download the lead sheet.
- `GET /api/knowledge?question=...` - retrieve configured knowledge context.
- `GET /api/call-history` - list browser demo sessions and analysis.
- `WS /ws/voice` - browser realtime Sarvam STT session. Audio frames are
  base64-encoded mono 16 kHz signed little-endian 16-bit PCM and the provider
  encoding is `linear16`.
