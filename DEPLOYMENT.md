# Deployment notes

Deploy the FastAPI application behind HTTPS. The browser realtime endpoint
must be exposed as secure WebSocket (`wss://`). Use PostgreSQL for shared
multi-user CRM data and configure `DATABASE_URL`.

Do not enable real telephony until provider credentials, verified caller ID,
public AgentStream URL, customer consent, opt-out handling, retention, and
provider trial permissions are verified.
