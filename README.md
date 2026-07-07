# SumaiGuard Agent / 親の家 安全チェックAI

Preventive elderly home safety AI agent. One photo in, visible safety risks out.

## Problem

Families often notice risky areas in a parent's home only after a fall or near-miss. A single photo can start a safer conversation if the risks are made visible and next actions are separated clearly.

## Target Users

- Adult children checking an elderly parent's home.
- Families preparing a conversation with a care manager.
- Demo reviewers evaluating whether photo-based safety triage is useful.

## POC Boundary

Implemented:

- FastAPI backend with Gemini AI integration.
- Gradio frontend with Japanese UI.
- One-photo upload or camera input.
- Optional room hint.
- Mock mode without Gemini credentials.
- Gemini vision with structured JSON output and Pydantic validation.
- Red-box risk annotation with R1/R2/R3 labels.
- Current vs improvement side-by-side image.
- Deterministic rule mapping into three action tiers.
- Japanese markdown reports.
- Cloud Run deployment scripts.
- GitHub Actions CI/CD.
- Structured JSON logging.

Not implemented:

- Authentication or user accounts.
- Persistent storage.
- Full RAG or vector DB.
- PDF report download.
- Elderly profile questionnaire.
- Medical, care-level, insurance, or construction judgment.
- Exact measurements from one photo.

## Architecture

Two services:

- `sumai-agent`: FastAPI AI agent on `http://localhost:8080`
- `sumai-web`: Gradio web app on `http://localhost:8081`

Flow:

```
Browser -> sumai-web -> sumai-agent -> image intake -> Gemini/mock vision -> rule engine -> visual renderer -> reports
```

See [docs/architecture.md](docs/architecture.md).

## Quick Start

### Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build
```

- Agent: http://localhost:8080/healthz
- Web: http://localhost:8081

### Manual Backend

```bash
cd apps/sumai_agent
python -m venv .venv
.venv/bin/pip install -r requirements.txt
MOCK_MODE=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Manual Frontend

```bash
cd apps/sumai_web
python -m venv .venv
.venv/bin/pip install -r requirements.txt
SUMAI_AGENT_URL=http://localhost:8080 MOCK_MODE=true .venv/bin/python app.py
```

## Gemini Setup

To use real Gemini analysis instead of mock mode:

1. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Set the environment variable:

```bash
export GEMINI_API_KEY=your-key-here
export MOCK_MODE=false
```

3. Run the smoke test:

```bash
GEMINI_API_KEY=your-key-here ./scripts/smoke_gemini.sh
```

4. For Docker Compose:

```bash
MOCK_MODE=false GEMINI_API_KEY=your-key-here docker compose up --build
```

See [docs/gemini_integration.md](docs/gemini_integration.md) for details.

## Cloud Run Deployment

### Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI installed and authenticated
- Cloud Run API enabled

### Deploy

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GEMINI_API_KEY=your-key-here  # optional

# Deploy both services
./scripts/deploy_all_cloudrun.sh

# Or individually
./scripts/deploy_sumai_agent.sh
./scripts/deploy_sumai_web.sh

# Check status
./scripts/check_cloudrun.sh
```

### Secret Manager (recommended for production)

```bash
# Create secret
echo -n "your-api-key" | gcloud secrets create gemini-api-key --data-file=-

# Update service to use secret
gcloud run services update sumai-agent --region asia-northeast1 \
  --set-secrets=GEMINI_API_KEY=gemini-api-key:latest
```

See [docs/cloudrun_deployment.md](docs/cloudrun_deployment.md) for full guide.

## GitHub Actions

### CI (Automatic)

Runs on push and pull_request to `main`:
- Python 3.12 backend tests
- Frontend import check
- Docker compose config validation

### Deploy (Manual)

Trigger via GitHub Actions → "Deploy to Cloud Run" → Run workflow.

Required GitHub Secrets:

| Secret | Description |
|--------|-------------|
| `GCP_PROJECT_ID` | Google Cloud project ID |
| `GCP_SA_KEY` | Service account JSON key |
| `GEMINI_API_KEY` | (Optional) Gemini API key |

Alternative: Use Workload Identity Federation instead of `GCP_SA_KEY`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_MODE` | `true` | Forces deterministic mock vision when true |
| `GEMINI_API_KEY` | (empty) | Gemini API key. Leave empty for mock mode |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `SUMAI_AGENT_URL` | `http://localhost:8080` | Backend URL for frontend |
| `SUMAI_WEB_PORT` | `8081` | Frontend local port |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `ANALYSIS_TIMEOUT` | `120` | Gemini API timeout in seconds |
| `GOOGLE_CLOUD_PROJECT` | (required for deploy) | GCP project ID |

Never hardcode secrets.

## Mock Mode vs Gemini Mode

| Feature | Mock Mode | Gemini Mode |
|---------|-----------|-------------|
| API Key needed | No | Yes |
| Analysis source | Deterministic fixtures | Real Gemini AI |
| Speed | Instant | 3-15 seconds |
| Findings | Room-specific fixtures | Photo-specific |
| Offline use | Yes | No |
| Cost | Free | API usage cost |
| Badge | 🟢 MOCK MODE | 🔴 GEMINI MODE |

The backend also falls back to mock mode when:
- `GEMINI_API_KEY` is missing
- Gemini returns malformed JSON
- Gemini request times out
- Any Gemini API error occurs

## Tests

```bash
# Run all backend tests
python -m pytest apps/sumai_agent/tests -v

# Full test suite (backend + frontend import + docker)
./scripts/test_all.sh

# Docker compose validation
docker compose config

# Gemini smoke test (requires API key)
GEMINI_API_KEY=your-key ./scripts/smoke_gemini.sh
```

## Demo Flow

1. Open the app (`http://localhost:8081` or the Cloud Run web URL).
2. Upload or take a photo on the first screen (入力画面 / photo capture screen).
3. Choose an optional room hint (such as 玄関 or 浴室).
4. Click `AIで安全チェック`.
5. The result screen (診断結果画面 / analysis result screen) appears, showing the visual risks and three action cards.
6. Click the re-check button (`対策後の写真でもう一度チェック` or `別の写真をチェック`) to return to the first screen with a clean state.

See [docs/demo_script.md](docs/demo_script.md) for the full 3-minute demo script.

## Hackathon Requirements Checklist

- [x] Single photo input
- [x] Red-box annotated risk image
- [x] Side-by-side current vs improvement image
- [x] Risk details with evidence and basis
- [x] Three action cards (家族/ケアマネ/専門施工)
- [x] Watermark: コミュニケーション用イメージ｜施工図ではありません
- [x] Japanese UI
- [x] Mock mode for offline demo
- [x] Gemini integration for real analysis
- [x] Cloud Run deployment
- [x] GitHub Actions CI/CD
- [x] No elderly questionnaire
- [x] No authentication/user accounts
- [x] No persistent storage
- [x] Clear disclaimers

## Known Limitations

- Single photo only; no multi-photo comparison.
- Bbox accuracy depends on Gemini model quality.
- No exact measurements from photos.
- Improvement image is a deterministic overlay, not a realistic rendering.
- Cloud Run cold start may take 5-10 seconds.
- No PDF report download.
- No user accounts or persistent history.

## Documentation

- [Architecture](docs/architecture.md)
- [Risk Policy](docs/risk_policy.md)
- [Demo Script](docs/demo_script.md)
- [Product Decisions](docs/decisions.md)
- [Cloud Run Deployment](docs/cloudrun_deployment.md)
- [Gemini Integration](docs/gemini_integration.md)
