#!/usr/bin/env bash
set -euo pipefail

# Deploy sumai-agent to Cloud Run.
# Requires: gcloud CLI, GOOGLE_CLOUD_PROJECT env var.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${REGION:-asia-northeast1}"
SERVICE_NAME="sumai-agent"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"

echo "========================================="
echo "  Deploying $SERVICE_NAME"
echo "  Project:  $PROJECT"
echo "  Region:   $REGION"
echo "  Model:    $GEMINI_MODEL"
echo "========================================="

# Build env vars string
ENV_VARS="MOCK_MODE=false,GEMINI_MODEL=${GEMINI_MODEL},LOG_LEVEL=INFO"

# Add GEMINI_API_KEY if set (via env var)
if [ -n "${GEMINI_API_KEY:-}" ]; then
    ENV_VARS="${ENV_VARS},GEMINI_API_KEY=${GEMINI_API_KEY}"
    echo "  API Key:  Set via env var"
else
    echo "  API Key:  Not set (will use mock mode on Cloud Run)"
    echo "  Tip:      Set GEMINI_API_KEY or use Secret Manager:"
    echo "            gcloud run services update $SERVICE_NAME --region $REGION \\"
    echo "              --set-secrets=GEMINI_API_KEY=gemini-api-key:latest"
fi

echo ""

gcloud run deploy "$SERVICE_NAME" \
    --project "$PROJECT" \
    --source apps/sumai_agent \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "$ENV_VARS" \
    --memory 1Gi \
    --cpu 1 \
    --timeout 120

echo ""
echo "✅ $SERVICE_NAME deployed."
AGENT_URL=$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "   URL: $AGENT_URL"
echo "   Health: curl $AGENT_URL/healthz"
