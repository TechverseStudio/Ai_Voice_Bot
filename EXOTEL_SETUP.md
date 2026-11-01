# Real Outbound AI Telephony Integration Guide (Exotel & Twilio)

## 1. Overview
The AI Voice Real Estate CRM now features a production-ready telephony provider abstraction in `backend/telephony/` supporting:
1. **Exotel Provider** (`backend/telephony/exotel.py`): Official Indian telecom carrier integration utilizing Exotel's v1 REST API (`Calls/connect.json`), virtual ExoPhone caller IDs, and status callback webhooks.
2. **Twilio Provider** (`backend/telephony/twilio.py`): Bidirectional audio media stream standard (`<Connect><Stream>`) delivering sub-second two-way voice streaming over WebSockets.
3. **Mock Provider** (`backend/telephony/mock.py`): Safe local simulation engine for automated tests and demos without carrier charges.

## 2. Configuration & Environment Variables

Add the following to your `.env` file depending on your chosen carrier:

### For Exotel (India Primary Carrier):
```bash
TELEPHONY_PROVIDER=exotel
EXOTEL_ACCOUNT_SID=your_account_sid
EXOTEL_API_KEY=your_api_key
EXOTEL_API_TOKEN=your_api_token
EXOTEL_CALLER_ID=08047192345           # Your verified ExoPhone number
EXOTEL_BASE_URL=https://api.exotel.com # Or regional cluster URL
AGENTSTREAM_PUBLIC_URL=https://your-public-domain.ngrok-free.app
```

### For Twilio:
```bash
TELEPHONY_PROVIDER=twilio
TWILIO_ACCOUNT_SID=ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+12025550199       # E.164 verified caller ID
PUBLIC_BASE_URL=https://your-public-domain.ngrok-free.app
```

## 3. Webhook Endpoints Configured in Application
The application exposes production webhook endpoints for call lifecycle events:
- **Exotel Status Webhook**: `POST /api/telephony/webhook/exotel/status`
- **Twilio Status Webhook**: `POST /api/telephony/webhook/twilio/status`
- **Call Connection Handshake**: `POST /api/telephony/webhook/call-connection`
- **Call Completion Summary**: `POST /api/telephony/webhook/call-completion`
- **Bidirectional WebSocket Audio**: `WSS /ws/telephony/stream`

## 4. India Telecom Regulatory Compliance (TRAI)
1. **Calling Hours**: Automated campaigns enforce TRAI commercial calling hours between **09:30 AM and 07:30 PM IST**. Calls scheduled outside this window are automatically deferred.
2. **DND Suppression**: National Do Not Disturb (DND) / NDNC registry and customer opt-out requests are strictly enforced before dialing.
3. **Opt-Out Handling**: If a prospect states "Do not call me again", "Remove my number", or says "मला कॉल करू नका", the AI engine immediately flags `opt_out=True` in the CRM and stops further outreach.
4. **KYC & ExoPhone Setup**: Exotel requires commercial business KYC verification and an active virtual number (ExoPhone) before outbound calls can be connected to mobile subscribers.

## 5. Live Telephony Readiness Verification
You can check the active status and readiness of providers at any time:
```bash
curl http://localhost:8000/api/telephony/status
```
Response:
```json
{
  "active_provider": "mock",
  "ready": true,
  "message": "Mock provider active (calls are simulated safely for testing)",
  "missing_configuration": [],
  "mode": "simulation",
  "supported_providers": {
    "exotel": {"ready": false, "message": "...", "missing": ["EXOTEL_ACCOUNT_SID", ...]},
    "twilio": {"ready": false, "message": "...", "missing": ["TWILIO_ACCOUNT_SID", ...]},
    "mock": {"ready": true, "message": "...", "missing": []}
  }
}
```
