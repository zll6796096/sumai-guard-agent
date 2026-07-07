#!/usr/bin/env bash
set -euo pipefail

# Check Cloud Run deployment status.
# Requires: gcloud CLI, GOOGLE_CLOUD_PROJECT env var.

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${REGION:-asia-northeast1}"

echo "========================================="
echo "  SumaiGuard Agent — Cloud Run Status"
echo "  Project: $PROJECT"
echo "  Region:  $REGION"
echo "========================================="
echo ""

# Agent
AGENT_URL=$(gcloud run services describe sumai-agent --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null || echo "NOT DEPLOYED")
echo "Agent:"
echo "  URL: $AGENT_URL"
if [[ "$AGENT_URL" != "NOT DEPLOYED" ]]; then
    echo "  Health check:"
    HEALTH=$(curl -s --max-time 10 "$AGENT_URL/healthz" 2>/dev/null || echo '{"status":"unreachable"}')
    echo "    $HEALTH"
else
    echo "  ⚠️  Not deployed. Run: ./scripts/deploy_sumai_agent.sh"
fi

echo ""

# Web
WEB_URL=$(gcloud run services describe sumai-web --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null || echo "NOT DEPLOYED")
echo "Web:"
echo "  URL: $WEB_URL"
if [[ "$WEB_URL" != "NOT DEPLOYED" ]]; then
    echo "  Open in browser: $WEB_URL"
else
    echo "  ⚠️  Not deployed. Run: ./scripts/deploy_sumai_web.sh"
fi

echo ""
echo "========================================="
echo "  To open the demo:"
echo "  1. Open the Web URL above in your browser."
echo "  2. Upload a home photo (玄関, 浴室, etc.)."
echo "  3. Click 'AIで安全チェック' to analyze."
echo "========================================="
