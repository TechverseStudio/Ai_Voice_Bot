# Local setup

1. Copy `.env.example` to `.env` and set `SARVAM_API_KEY`.
2. Create a Python 3.10+ virtual environment.
3. Install `requirements.txt`.
4. Start the API.

Linux/macOS:

```text
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
PYTHONPATH=. .venv/bin/uvicorn backend.web:app --reload
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.web:app --reload
```

The default database is SQLite at `data/voice_agent.db`. Set `DATABASE_URL`
to a PostgreSQL URL when a PostgreSQL server is available.

The default telephony provider is `mock`. Mock calls never dial a phone.
