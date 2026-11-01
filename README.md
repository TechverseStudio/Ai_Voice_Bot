# AI Autonomous Lead Generation Engine for Real Estate

Commercial-grade AI Autonomous Outbound Calling and Lead Generation Engine designed for real estate companies.

## Core Business Workflow

```
ONE CONTACT DOCUMENT (.xlsx, .csv, .pdf, .docx, .txt)
   │
   ▼
[1] Smart Contact Ingestion & Normalization (+91 Indian validation, DND check, duplicate detection)
   │
   ▼
[2] Interactive Preview & Manual Review
   │
   ▼
[3] Real Estate AI Campaign Configuration & Approval (calling windows, concurrency, max attempts)
   │
   ▼
[4] Autonomous Outbound Calling Loop (queue-based, rate-limited, DND-enforced)
   │
   ▼
[5] Real-Time AI Sales Conversation (Sarvam 105B LLM, grounded project knowledge, human-like sales rep)
   │
   ▼
[6] Post-Call Intelligence & Requirement Extraction (BHK, budget, locality, purpose, timeline, citations)
   │
   ▼
[7] Intelligent Lead Creation & Explainable Scoring (Hot / Warm / Cold classification)
   │
   ▼
[8] Automatic Meeting & Site Visit Scheduling (slot capacity validation & confirmation codes)
   │
   ▼
[9] Real-Time CRM Dossier & Campaign Analytics Dashboard
```

## Supported File Formats

- **Excel**: `.xlsx`, `.xls`
- **CSV**: `.csv` (auto-detects delimiters and encodings)
- **Word**: `.docx` (tables and text extraction)
- **PDF**: `.pdf` (native text extraction & pdftotext fallback; flags scanned documents for manual review)
- **Text**: `.txt`

Sample files for testing are included in `data/sample_contacts.xlsx` and `data/sample_contacts.csv`.

## Running the Web Portal

Start the server from the repository root:

```bash
PYTHONPATH=. .venv/bin/uvicorn backend.web:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000` in your browser.

## Running Tests

Run the full automated test suite:

```bash
PYTHONPATH=. .venv/bin/pytest
```

Run the specific 15-point acceptance test suite:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_lead_generation_engine.py -v
```

---

# AI Voice Agent

## Local setup

Install the Linux audio libraries once:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv libsndfile1 portaudio19-dev
```

On Linux/macOS, create the environment and install Python dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
```

Set `SARVAM_API_KEY` in `.env`, then run the local voice loop from the
repository root:

```bash
PYTHONPATH=. .venv/bin/python backend/voice_agent.py
```

On Windows PowerShell, use:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.web:app --reload
```

For a browser-based local voice session:

```bash
PYTHONPATH=. .venv/bin/uvicorn backend.web:app --reload
```

Open `http://127.0.0.1:8000` and allow microphone access.
The local demo stores leads and call summaries in SQLite and can export them
to Excel. To use PostgreSQL, start a PostgreSQL server, set
`DATABASE_URL=postgresql+psycopg://...` in `.env`, and restart the app. The
sample property knowledge is in
`data/knowledge/krishnas-ai-property.md`; replace it with verified project
documents before a client demonstration.

Check the backend before testing the microphone:

```bash
curl http://127.0.0.1:8000/api/health
```

The browser demo uses a persistent WebSocket session and Sarvam realtime STT:
click **Start realtime call**, speak naturally, and pause briefly between
sentences. The agent detects the pause, decides the intent, and returns a
spoken response while keeping the session open. Click **Hang up** to end it.
The session is labelled **Browser Demo**, saved in call history, and analyzed
for requirements and an explainable interest score. It is not a mobile-network
call.

Audio uses mono, 16 kHz, signed little-endian 16-bit PCM (`linear16`). The
browser downsamples its microphone stream to 16 kHz before sending frames.

The intent and response pipeline can be tested without an API key:

```bash
PYTHONPATH=. .venv/bin/python tests/test_agent.py
```

## Outbound calls

The portal has a provider-neutral one-lead outbound boundary and a safe mock
mode. Add a lead, select it, and click **Test outbound call**. This records a
`simulated_accepted` call and never dials a phone.

Real phone calls are not enabled in this checkout because the historical
Exotel integration is absent. See [EXOTEL_SETUP.md](./EXOTEL_SETUP.md) for the
required provider configuration and blockers. Calling regular phone numbers
requires a legitimate carrier account; it cannot be permanently free.

A production campaign also needs consent/opt-out handling, rate limits,
retries, calling-hour rules, call recording/privacy controls, verified
project facts, and a human handoff path.
