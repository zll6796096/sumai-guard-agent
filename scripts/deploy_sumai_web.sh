#!/usr/bin/env bash
set -euo pipefail

# Deploy sumai-web to Cloud Run.
# Requires: gcloud CLI, GOOGLE_CLOUD_PROJECT env var.
# The sumai-agent service must be deployed first.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${REGION:-asia-northeast1}"
SERVICE_NAME="sumai-web"
AGENT_SERVICE="sumai-agent"

echo "========================================="
echo "  Deploying $SERVICE_NAME"
echo "  Project:  $PROJECT"
echo "  Region:   $REGION"
echo "========================================="

# Fetch the deployed agent URL
echo "Fetching $AGENT_SERVICE URL..."
AGENT_URL=$(gcloud run services describe "$AGENT_SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null || echo "")

if [ -z "$AGENT_URL" ]; then
    echo "ERROR: Could not fetch $AGENT_SERVICE URL."
    echo "Deploy the agent first: ./scripts/deploy_sumai_agent.sh"
    exit 1
fi

echo "  Agent URL: $AGENT_URL"
echo ""

gcloud run deploy "$SERVICE_NAME" \
    --project "$PROJECT" \
    --source apps/sumai_web \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "SUMAI_AGENT_URL=${AGENT_URL},SUMAI_WEB_PORT=8080,MOCK_MODE=false,LOG_LEVEL=INFO,REQUIRE_REAL_GEMINI=${REQUIRE_REAL_GEMINI:-false}" \
    --memory 1Gi \
    --cpu 1 \
    --timeout 120

echo ""
echo "✅ $SERVICE_NAME deployed."
WEB_URL=$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "   URL: $WEB_URL"
echo "   Open in browser: $WEB_URL"
