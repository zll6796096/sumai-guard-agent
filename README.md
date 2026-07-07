# SumaiGuard Agent / 親の家 安全チェックAI

Preventive elderly home safety AI agent for local POC use.

## Problem

Families often notice risky areas in a parent's home only after a fall or near-miss. A single photo can start a safer conversation if the risks are made visible and next actions are separated clearly.

## Target Users

- Adult children checking an elderly parent's home.
- Families preparing a conversation with a care manager.
- Demo reviewers evaluating whether photo-based safety triage is useful.

## POC Boundary

Implemented:

- Local FastAPI backend.
- Local Gradio frontend.
- One-photo upload or camera input.
- Optional room hint.
- Mock mode without Gemini credentials.
- Gemini integration path when credentials are available.
- Red-box risk annotation.
- Deterministic rule mapping into three action tiers.
- Japanese markdown reports.

Not implemented:

- Cloud deployment.
- Authentication.
- User accounts.
- Persistent storage.
- Full RAG or vector DB.
- PDF report download.
- Elderly profile questionnaire.
- Medical, care-level, insurance, or construction judgment.
- Exact measurements from one photo.

Future deployment will be done later with Antigravity/Cloud Run.

## Screens

1. First screen: photo upload/take-photo input, optional room hint, shooting guidance, and `AIで安全チェック`.
2. Result screen: total risk, red-box annotated photo, current vs improvement image, risk details, three action-card markdown sections, and re-check button.

## Architecture

Two local services:

- `sumai-agent`: FastAPI AI agent on `http://localhost:8080`
- `sumai-web`: Gradio web app on `http://localhost:8081`

Flow:

`Browser -> sumai-web -> sumai-agent -> image intake -> Gemini/mock vision -> rule engine -> visual renderer -> reports`

See [docs/architecture.md](docs/architecture.md).

## Local Run Commands

Docker Compose:

```bash
cp .env.example .env
./scripts/local_demo.sh
```

Manual backend:

```bash
cd apps/sumai_agent
python -m venv .venv
.venv/bin/pip install -r requirements.txt
MOCK_MODE=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Manual frontend:

```bash
cd apps/sumai_web
python -m venv .venv
.venv/bin/pip install -r requirements.txt
SUMAI_AGENT_URL=http://localhost:8080 MOCK_MODE=true .venv/bin/python app.py
```

## Environment Variables

- `MOCK_MODE`: default `true`. Forces deterministic mock vision when true.
- `GEMINI_API_KEY`: optional. Leave empty for mock mode.
- `GEMINI_MODEL`: default `gemini-2.5-flash`.
- `SUMAI_AGENT_URL`: frontend backend URL, default `http://localhost:8080`.
- `SUMAI_WEB_PORT`: frontend local port, default `8081`.
- `LOG_LEVEL`: default `INFO`.

Never hardcode secrets.

## Mock Mode

Mock mode returns deterministic visible-risk findings by room hint. It powers local demos and tests without Gemini credentials.

The backend also falls back to mock mode when `GEMINI_API_KEY` is missing.

## Demo Flow

1. Open `http://localhost:8081`.
2. Upload a 玄関 or 浴室 photo.
3. Click `AIで安全チェック`.
4. Show red boxes and basis.
5. Show the three action tiers.
6. Click `対策後の写真でもう一度チェック` to restart the re-check loop.

## Tests

```bash
python -m pytest apps/sumai_agent/tests
docker compose config
```

`scripts/test_all.sh` also imports the frontend module when frontend dependencies are installed.
