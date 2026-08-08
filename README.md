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
- Legacy Cloud Run deployment scripts retained for local/history reference only.
- GitHub Actions CI plus a legacy deployment workflow that is not a release path.
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

- Agent health: http://localhost:8080/health
- Web: http://localhost:8081

Local mock mode needs no Google or Firebase credentials. The defaults keep
`MOCK_MODE=true`, `REQUIRE_REAL_GEMINI=false`, `APP_CHECK_REQUIRED=false`, and
`PUBLIC_WEB_ANALYSIS_ENABLED=true` so both services remain usable locally.
Docker Compose publishes both services on `127.0.0.1` by default. Setting
`SUMAI_BIND_ADDRESS=0.0.0.0` is an explicit LAN opt-in and is unsafe while
`APP_CHECK_REQUIRED=false` and `PUBLIC_WEB_ANALYSIS_ENABLED=true`. Do not use
this LAN opt-in with real Gemini.

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

## HTTP Contract

Native clients use `POST /api/v1/analyze`; `/analyze` is compatibility-only and
must not be used by new native or release integrations. The multipart `image`
part must declare `image/jpeg` or `image/png`. Send a sanitized JPEG or PNG and
label it accurately. Pillow decodes the supplied pixels and the intake strips
metadata, but the service does not independently magic-sniff and reject every
other encoded format when a file is mislabeled.

10 MiB (10,485,760 bytes) is the image file-part byte limit, enforced during
orchestrator upload reads after App Check; it is not a limit on the entire
multipart request. The decoded-image guard separately permits at most
25,000,000 decoded source pixels.

Release probes are `GET /health` for agent liveness and `GET /ready` for
readiness. The agent readiness JSON status is `ready`; the web readiness JSON
status is `ok`. `/healthz` is a local compatibility alias. The public web
service exposes `GET /privacy` and `GET /support`.

Analysis failures use only the following flat JSON contract. Responses do not
expose provider payloads, tokens, exception strings, image content, or debug
metadata.

| HTTP | Code | Exact response shape |
|---:|---|---|
| 400 | `INVALID_IMAGE` | `{"error":"INVALID_IMAGE","message":"画像を確認できませんでした。JPEGまたはPNGを選んでください。"}` |
| 401 | `APP_CHECK_INVALID` | `{"error":"APP_CHECK_INVALID","message":"アプリの確認に失敗しました。もう一度お試しください。"}` |
| 413 | `IMAGE_TOO_LARGE` | `{"error":"IMAGE_TOO_LARGE","message":"画像が大きすぎます。別の写真を選んでください。"}` |
| 429 | `SERVICE_LIMITED` | `{"error":"SERVICE_LIMITED","message":"現在アクセスが集中しています。時間をおいてお試しください。"}` |
| 503 | `GEMINI_UNAVAILABLE` | `{"error":"GEMINI_UNAVAILABLE","message":"現在解析を利用できません。時間をおいてお試しください。"}` |
| 500 | `INTERNAL_ERROR` | `{"error":"INTERNAL_ERROR","message":"解析を完了できませんでした。時間をおいてお試しください。"}` |

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

### Strict Production Configuration

The repository defaults are intentionally local-safe. A production candidate
must use strict Gemini, require App Check, and disable public browser photo
analysis:

```bash
export REQUIRE_REAL_GEMINI=true
export APP_CHECK_REQUIRED=true
export FIREBASE_APP_ID='1:<PROJECT_NUMBER>:ios:<APP_ID_HASH>'
export PUBLIC_WEB_ANALYSIS_ENABLED=false
export MOCK_MODE=false
```

The placeholder above shows the exact iOS Firebase App ID shape; replace every
angle-bracket field from owner-approved Firebase configuration and never commit
the resulting ID. Firebase Admin initialization must run with Application
Default Credentials (ADC) capable of verifying tokens for the configured
Firebase project. Do not put credentials in `.env.example`, Compose defaults,
the repository, or logs.

The Python Firebase Admin SDK verifies ordinary App Check tokens and the
expected app identity, but does not consume tokens for single-use or replay
protection. App Check is abuse mitigation, not user authentication, and it does
not create an account or per-user history. Configure the App Check token TTL to
30 minutes in the Firebase console, not in Python. This source change neither
performs nor confirms that console action.

In strict Gemini mode:

- Mock mode fallback is completely disabled.
- A missing Gemini key or a non-quota strict provider failure returns
  `503 GEMINI_UNAVAILABLE`.
- A recognized provider quota or rate-limit failure returns
  `429 SERVICE_LIMITED`.
- Image classification detects non-home environments (`is_home_environment=false`), resulting in 0 risks and no actions.
- Low model detection scores (< 0.45) are discarded; unknown risks require a score >= 0.75. The compatible `confidence` API field is uncalibrated and is not a correctness probability.

See [docs/gemini_integration.md](docs/gemini_integration.md) for details.

## Candidate And Release Boundary

The release path keeps source, CI, candidate, device, promotion, production,
archive, review, release, and storefront gates separate. Passing one gate does
not imply any later gate:

1. **Source and exact-head CI:** tests must bind to the exact source SHA.
2. **Cloud Build candidate:** Cloud Build tests the source, builds agent and web
   images, resolves each immutable digest, and deploys tagged candidate
   revisions at 0% production traffic. Production predecessors must remain
   unchanged. Sanitized candidate evidence binds the SHA, build, digests,
   revisions, resource versions, service-account identities, and predecessor
   revisions without request bodies, images, tokens, report content, or
   credentials.
3. **Candidate security:** the agent uses `APP_CHECK_REQUIRED=true` and
   `REQUIRE_REAL_GEMINI=true`; App Check before reading the multipart body keeps
   an unattested upload from being consumed. The web candidate uses
   `PUBLIC_WEB_ANALYSIS_ENABLED=false`. The local mock mode remains available for
   credential-free local work and is not production evidence.
4. **Device:** a real iPhone must produce current App Attest evidence against
   the exact candidate revision using the approved synthetic sample.
5. **Separate promotion checkpoint:**
   `scripts/promote-verified-candidate.sh` has default dry-run behavior and
   validates both candidate evidence and real-device App Attest evidence.
   Apply mode uses dual confirmation: `SUMAI_PROMOTE_APPLY=true` plus the exact
   `SUMAI_PROMOTE_CONFIRM` phrase. It revalidates identity before mutation,
   uses the Cloud Run Admin API with `resourceVersion` compare-and-swap
   semantics, and performs ownership-aware rollback. Promotion evidence is a
   separate artifact.
6. **Apple:** archive/signing, TestFlight processing, App Review submission,
   approval, manual release, propagation, and storefront visibility remain
   independent gates after backend promotion.

Direct legacy deployment paths are retired: direct/source `gcloud run deploy`,
service update/replace, and traffic mechanics fail closed, and the retired
source-deployment workflow is not an App Store release path. The compatibility
wrappers remain operational: `scripts/deploy_sumai_agent.sh` and
`scripts/deploy_sumai_web.sh` reject partial arguments and delegate to
`scripts/deploy_all_cloudrun.sh`. That paired entrypoint submits one paired
candidate-only Cloud Build only after all required inputs, clean exact
`main`/`origin/main` state, and approved WIF or otherwise valid `gcloud`
authentication are available.
This is an external candidate deployment. It changes no production traffic,
but it creates external 0% candidate revisions and therefore requires explicit
authorization.

`scripts/check_cloudrun.sh` is now a strict read-only inspector. All four
targets are mandatory and explicit:

```bash
GOOGLE_CLOUD_PROJECT=owner-approved-project SUMAI_REGION=owner-approved-region SUMAI_AGENT_SERVICE=owner-approved-agent-service SUMAI_WEB_SERVICE=owner-approved-web-service ./scripts/check_cloudrun.sh
```

The inspector describes only the two named services and performs safe GET
probes for agent `/health` and `/ready`, plus web `/`, `/ready`, `/privacy`, and
`/support`. It requires agent `/ready` to report status `ready` and web `/ready`
to report status `ok`. Each curl invocation ignores user configuration, permits
HTTPS only, and follows no redirects. The inspector prints a bounded runtime
shape summary such as container count, timeout, and concurrency, plus a traffic
and service identity summary. It never prints environment values, secret
references, tokens, or credential/provider details. It cannot deploy, change
traffic, inspect logs, or analyze an image.
See
[docs/cloudrun_deployment.md](docs/cloudrun_deployment.md) for the evidence
workflow and
[the v1.0 release gate](docs/release/sumaiguard-v1.0-app-store-release-gate.md)
for current gate status.

CI runs on pushes and pull requests to `main`:

- Python 3.12 backend tests
- Frontend import check
- Docker Compose configuration validation

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_MODE` | `true` | Forces deterministic mock vision when true |
| `REQUIRE_REAL_GEMINI` | `false` | Sets strict production mode where mock fallback is disabled |
| `APP_CHECK_REQUIRED` | `false` | Requires a valid App Check token only when explicitly enabled |
| `FIREBASE_APP_ID` | (empty) | Expected iOS Firebase App ID; required when App Check is enabled |
| `MAX_UPLOAD_BYTES` | `10485760` | Maximum accepted upload bytes (10 MiB) |
| `MAX_SOURCE_PIXELS` | `25000000` | Maximum decoded source-image pixel count |
| `PUBLIC_WEB_ANALYSIS_ENABLED` | `true` | Allows local web photo analysis; production must set false |
| `RESULT_MEMO_TTL_SECONDS` | `300` | Process-local semantic memo TTL in seconds |
| `RESULT_MEMO_MAX_ITEMS` | `128` | Process-local semantic memo item bound |
| `SUMAI_BIND_ADDRESS` | `127.0.0.1` | Local Compose published-port bind address |
| `GEMINI_API_KEY` | (empty) | Gemini API key. Leave empty for mock mode |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `SUMAI_AGENT_URL` | `http://localhost:8080` | Backend URL for frontend |
| `SUMAI_WEB_PORT` | `8081` | Frontend local port |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `ANALYSIS_TIMEOUT` | `120` | Gemini API timeout in seconds |
| `GOOGLE_CLOUD_PROJECT` | (empty) | Explicit target for the read-only Cloud Run inspector; never release authorization |
| `SUMAI_REGION` | (empty for inspector) | Required explicit read-only inspection region |
| `SUMAI_AGENT_SERVICE` | (empty for inspector) | Required explicit read-only inspection agent service |
| `SUMAI_WEB_SERVICE` | (empty for inspector) | Required explicit read-only inspection web service |

Never hardcode secrets.

## Privacy And Operator Publication Gates

The structured semantic result, including generated report/advice text, may be
held and reused briefly in the bounded process-local TTL memo. Generated
report/advice text is cached and reused on a memo hit. Annotated and improvement
images are rendered for every request. The uploaded
image bytes, the sanitized PNG, annotated image bytes, and PDF bytes are not
stored in the memo; improvement image bytes are likewise outside it. PDF bytes
are generated on demand and are not persisted or cached. The service does not
persist uploaded images or account history.

The memo has no database or account history, is process-local, not persistent,
not shared across worker processes, and is cleared when the worker process
restarts. Its TTL and maximum item count are environment-configurable. The
operational logs are a separate
surface and may contain safe request metadata, status, timings, and stable error
codes, but must not contain photos, raw model output, reports, App Check tokens,
credentials, or provider exception strings.

Both memo limits are environment-configurable. The memo holds structured
semantic results and generated report/advice text only, never image or PDF
bytes. The release process must observe the deployed memo values before final privacy
publication; source defaults are not evidence of deployed settings.

Cloud Logging retention must be observed in the target environment before
publication; no duration may be inferred from source or invented. An
owner-approved support/operator contact must be confirmed before publication;
do not invent an email address, operator identity, response promise, project
identifier, or public service URL.

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
docker compose --env-file .env.example config

# E2E Smoke test (requires API key)
GEMINI_API_KEY=your-key ./scripts/smoke_real_gemini.sh
```

## Demo Flow

1. Open the local app at `http://localhost:8081`.
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
- [x] Candidate-only Cloud Build source path exists (not deployment evidence)
- [x] GitHub Actions CI exists
- [x] No elderly questionnaire
- [x] No authentication/user accounts
- [x] No persistent storage
- [x] Clear disclaimers

## Known Limitations

- Single photo only; no multi-photo comparison.
- Bbox accuracy depends on Gemini model quality.
- No exact measurements from photos.
- Improvement image is a deterministic overlay, not a realistic rendering.
- The Japanese text-only PDF does not include photos, is not stored, and is not a professional inspection, medical/care, insurance, legal, construction, or quotation document.
- No user accounts or persistent history.

## Documentation

- [Architecture](docs/architecture.md)
- [Risk Policy](docs/risk_policy.md)
- [Demo Script](docs/demo_script.md)
- [Product Decisions](docs/decisions.md)
- [Cloud Run candidate and release evidence](docs/cloudrun_deployment.md)
- [v1.0 App Store release gate](docs/release/sumaiguard-v1.0-app-store-release-gate.md)
- [Gemini Integration](docs/gemini_integration.md)
