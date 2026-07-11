# Cloud Run Deployment Guide

## Prerequisites

1. Google Cloud project with billing enabled.
2. `gcloud` CLI installed and authenticated (`gcloud auth login`).
3. Cloud Run API enabled:
   ```bash
   gcloud services enable run.googleapis.com --project YOUR_PROJECT_ID
   ```
4. (Optional) Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

## Quick Deploy

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GEMINI_API_KEY=your-key-here  # optional

./scripts/deploy_all_cloudrun.sh
```

This deploys both services in order:
1. `sumai-agent` → FastAPI backend
2. `sumai-web` → FastAPI web service serving the embedded HTML/CSS/vanilla JavaScript frontend (with agent URL auto-configured)

## Individual Deployment

### Deploy Agent Only

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
./scripts/deploy_sumai_agent.sh
```

### Deploy Web Only

Requires agent to be deployed first (fetches URL automatically):

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
./scripts/deploy_sumai_web.sh
```

## Check Status

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
./scripts/check_cloudrun.sh
```

## Secrets Management

### Option 1: Environment Variables (hackathon/quick setup)

Set `GEMINI_API_KEY` before running deploy scripts:

```bash
export GEMINI_API_KEY=your-key-here
./scripts/deploy_sumai_agent.sh
```

### Option 2: Secret Manager (recommended for production)

```bash
# Create secret
echo -n "your-api-key" | gcloud secrets create gemini-api-key \
    --data-file=- --project YOUR_PROJECT_ID

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding gemini-api-key \
    --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --project YOUR_PROJECT_ID

# Update service to use secret
gcloud run services update sumai-agent \
    --region asia-northeast1 \
    --set-secrets=GEMINI_API_KEY=gemini-api-key:latest \
    --project YOUR_PROJECT_ID
```

## GitHub Actions Deployment

See `.github/workflows/deploy-cloudrun.yml`.

Required GitHub Secrets:

| Secret | Description |
|--------|-------------|
| `GCP_PROJECT_ID` | Google Cloud project ID |
| `GCP_SA_KEY` | Service account JSON key with Cloud Run Admin role |
| `GEMINI_API_KEY` | (Optional) Gemini API key |

### Create a Service Account for CI/CD

```bash
PROJECT_ID=your-project-id

# Create service account
gcloud iam service-accounts create github-actions \
    --display-name="GitHub Actions" \
    --project $PROJECT_ID

# Grant roles
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser"

# Create key
gcloud iam service-accounts keys create key.json \
    --iam-account=github-actions@${PROJECT_ID}.iam.gserviceaccount.com

# Add key.json contents as GCP_SA_KEY secret in GitHub repo settings
# Then delete the key file
rm key.json
```

## Configuration

### Cloud Run Service Settings

| Setting | Agent | Web |
|---------|-------|-----|
| Memory | 1 GiB | 1 GiB |
| CPU | 1 | 1 |
| Timeout | 120s | 120s |
| Auth | Unauthenticated | Unauthenticated |
| Region | asia-northeast1 | asia-northeast1 |

### Environment Variables on Cloud Run

| Variable | Agent | Web |
|----------|-------|-----|
| `MOCK_MODE` | `false` | `false` |
| `GEMINI_API_KEY` | Set via env/secret | — |
| `GEMINI_MODEL` | `gemini-2.5-flash` | — |
| `SUMAI_AGENT_URL` | — | Auto-set from agent URL |
| `SUMAI_WEB_PORT` | — | `8080` |
| `LOG_LEVEL` | `INFO` | `INFO` |

## Troubleshooting

### Agent health check fails

```bash
curl -s https://sumai-agent-XXXX.asia-northeast1.run.app/healthz
```

Check:
- Service is deployed: `gcloud run services list --region asia-northeast1`
- Logs: `gcloud run services logs read sumai-agent --region asia-northeast1 --limit 50`

### Web can't reach agent

- Verify `SUMAI_AGENT_URL` is set correctly on the web service.
- Redeploy web: `./scripts/deploy_sumai_web.sh`

### Gemini returns mock results on Cloud Run

- Check `GEMINI_API_KEY` is set: healthz should show `mock_mode: false`.
- Check logs for `gemini_fallback` entries.

### Cold start is slow

Cloud Run cold starts can take 5-10 seconds. Use minimum instances to avoid:

```bash
gcloud run services update sumai-agent --min-instances 1 --region asia-northeast1
```

Note: This increases cost.
