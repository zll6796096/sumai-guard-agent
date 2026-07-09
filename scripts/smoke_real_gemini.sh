#!/usr/bin/env bash
# Wrapper shell script to run the Python smoke test.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export SUMAI_AGENT_URL="${SUMAI_AGENT_URL:-http://localhost:8000}"

echo "=================================================="
echo "🚀 Starting E2E smoke tests with real Gemini vision"
echo "   Target URL: $SUMAI_AGENT_URL"
echo "=================================================="

python3 scripts/smoke_real_gemini.py
