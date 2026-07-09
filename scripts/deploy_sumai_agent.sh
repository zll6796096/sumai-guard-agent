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

# Check for GEMINI_API_KEY and set ENV_VARS
if [ -n "${GEMINI_API_KEY:-}" ]; then
    ENV_VARS="MOCK_MODE=false,REQUIRE_REAL_GEMINI=true,GEMINI_MODEL=${GEMINI_MODEL},LOG_LEVEL=INFO,GEMINI_API_KEY=${GEMINI_API_KEY}"
    echo "  API Key:  Set via env var"
else
    echo "❌ Error: GEMINI_API_KEY is required for production deployment but is not set."
    echo "   Please set the GEMINI_API_KEY environment variable before deploying."
    exit 1
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
