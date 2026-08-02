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
- FastAPI web service serving an embedded Japanese HTML/CSS/vanilla JavaScript UI.
- One-photo upload or camera input.
- Six-place capture guidance for the entrance, hallway, bathroom, toilet, bedroom, and kitchen.
- Mock mode without Gemini credentials.
- Gemini vision with structured JSON output and Pydantic validation.
- Red-box risk annotation with Japanese risk labels.
- Current-risk and improvement images stacked vertically.
- Deterministic rule mapping into three action tiers.
- Japanese markdown reports.
- Japanese text-only PDF export of the current safety advice.
- Cloud Run deployment scripts.
- GitHub Actions CI/CD.
- Structured JSON logging.

Not implemented:

- Authentication or user accounts.
- Persistent storage.
- Full RAG or vector DB.
- Elderly profile questionnaire.
- Medical, care-level, insurance, or construction judgment.
- Exact measurements from one photo.

## Architecture

Two services:

- `sumai-agent`: FastAPI AI agent on `http://localhost:8080`
- `sumai-web`: FastAPI web service with an embedded HTML/CSS/vanilla JavaScript UI on `http://localhost:8081`

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

3. Run the E2E strict smoke test verifying home/non-home validation:

```bash
GEMINI_API_KEY=your-key-here ./scripts/smoke_real_gemini.sh
```

4. For Docker Compose:

```bash
MOCK_MODE=false GEMINI_API_KEY=your-key-here docker compose up --build
```

### Strict Production Mode

By default, the backend allows fallback to mock data when Gemini is unavailable. For strict production demos, set:
```bash
export REQUIRE_REAL_GEMINI=true
```
In strict mode:
- Mock mode fallback is completely disabled.
- If the Gemini API key is missing or calls fail, the backend returns `503 Service Unavailable` with `{"error": "gemini_unavailable"}`.
- Image classification detects non-home environments (`is_home_environment=false`), resulting in 0 risks and no actions.
- Low model detection scores (< 0.45) are discarded; unknown risks require a score >= 0.75. The compatible `confidence` API field is uncalibrated and is not a correctness probability.

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
| `REQUIRE_REAL_GEMINI` | `false` | Sets strict production mode where mock fallback is disabled |
| `GEMINI_API_KEY` | (empty) | Gemini API key. Leave empty for mock mode |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `SUMAI_AGENT_URL` | `http://localhost:8080` | Backend URL for frontend |
| `SUMAI_WEB_PORT` | `8081` | Frontend local port |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `ANALYSIS_TIMEOUT` | `120` | Gemini API timeout in seconds |
| `GOOGLE_CLOUD_PROJECT` | (required for deploy) | GCP project ID |

Never hardcode secrets.

## Developer Debug & Status APIs

### Status Endpoint (`/status`)
Retrieve the backend service configuration by querying `/status`:
```json
{
  "status": "ok",
  "mock_mode": false,
  "require_real_gemini": true,
  "has_gemini_api_key": true,
  "gemini_model": "gemini-2.5-flash",
  "mock_allowed": false
}
```

### Debug Query Parameter (`?debug=1`)
Open the frontend web application with `?debug=1` appended to the URL (e.g., `http://localhost:8081/?debug=1` or your Cloud Run URL).
This enables the developer debug panel on both the Result and Suggestions screens, displaying:
- **Mode**: Whether analysis was performed via Gemini, local mock, or fallback.
- **Analysis ID**: Unique identifier for tracking request logs.
- **Model**: The exact Gemini model used.
- **Findings Count**: Total number of findings after uncalibrated model-score thresholding.
- **Is Home Environment**: True/False indicating home interior classification.

## Mock Mode vs Gemini Mode

| Feature | Mock Mode | Gemini Mode |
|---------|-----------|-------------|
| API Key needed | No | Yes |
| Analysis source | Deterministic fixtures | Real Gemini AI |
| Speed | Instant | 3-15 seconds |
| Findings | Room-specific fixtures | Photo-specific |
| Offline use | Yes | No |
| Cost | Free | API usage cost |
| Strict Fallback | None (returns error if REQUIRE_REAL_GEMINI=true) | Mock data (only if REQUIRE_REAL_GEMINI=false) |

The backend falls back to mock mode on error **only** if `REQUIRE_REAL_GEMINI=false`:
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

# E2E Smoke test (requires API key)
GEMINI_API_KEY=your-key ./scripts/smoke_real_gemini.sh
```

## Demo Flow

1. Open the app (`http://localhost:8081` or the Cloud Run web URL).
2. Use the six-place grid as capture guidance, then click **カメラで撮影** (Camera) or **ライブラリから選択** (Library) on Screen 1 (Home).
3. Selecting a photo moves directly to Screen 2 and starts analysis, showing the photo, progress indicators, and `写真確認中` while it runs.
4. **Screen 2: Visual Diagnosis Result** appears. Review the annotated **危険提示** image and the **改善イメージ** below it.
5. Click **点検・修繕提案を見る** to transition to **Screen 3: 点検・修繕提案**. Review the three collapsed action cards and detailed risk basis.
6. Click **ホームに戻る** to return to Screen 1 with a clean state.

See [docs/demo_script.md](docs/demo_script.md) for the full 3-minute demo script.

## Hackathon Requirements Checklist

- [x] Single photo input
- [x] Red-box annotated risk image
- [x] Vertically stacked current-risk and improvement images
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
- The Japanese text-only PDF does not include photos, is not stored, and is not a professional inspection, medical/care, insurance, legal, construction, or quotation document.
- No user accounts or persistent history.

## Documentation

- [Architecture](docs/architecture.md)
- [Risk Policy](docs/risk_policy.md)
- [Demo Script](docs/demo_script.md)
- [Product Decisions](docs/decisions.md)
- [Cloud Run Deployment](docs/cloudrun_deployment.md)
- [Gemini Integration](docs/gemini_integration.md)
