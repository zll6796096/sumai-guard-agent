#!/usr/bin/env bash
set -euo pipefail

# Deploy both sumai-agent and sumai-web to Cloud Run.
# Requires: gcloud CLI, GOOGLE_CLOUD_PROJECT env var.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================="
echo "  SumaiGuard Agent — Cloud Run Deploy"
echo "========================================="
echo ""

echo "Step 1/2: Deploying sumai-agent..."
echo ""
bash "$ROOT_DIR/scripts/deploy_sumai_agent.sh"

echo ""
echo "Step 2/2: Deploying sumai-web..."
echo ""
bash "$ROOT_DIR/scripts/deploy_sumai_web.sh"

echo ""
echo "========================================="
echo "  Deployment Complete"
echo "========================================="
echo ""
bash "$ROOT_DIR/scripts/check_cloudrun.sh"
