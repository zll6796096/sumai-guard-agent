#!/usr/bin/env bash
set -euo pipefail

# Smoke test for Gemini API integration.
# Requires GEMINI_API_KEY env var. Never prints the key.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "ERROR: GEMINI_API_KEY is not set."
    echo "Usage: GEMINI_API_KEY=your-key ./scripts/smoke_gemini.sh"
    exit 1
fi

echo "GEMINI_API_KEY is set (not printing value)."
echo "Model: ${GEMINI_MODEL:-gemini-2.5-flash}"

# Generate a small synthetic test image if no sample exists
SAMPLE_IMAGE="apps/sumai_web/assets/samples/genkan_sample.png"
if [ ! -f "$SAMPLE_IMAGE" ]; then
    echo "Generating synthetic test image..."
    python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGB', (200, 150), (236, 232, 224))
draw = ImageDraw.Draw(img)
draw.rectangle((20, 80, 180, 140), fill=(200, 190, 170))
draw.rectangle((20, 75, 180, 80), fill=(160, 140, 120))
draw.text((60, 10), 'genkan', fill=(100, 100, 100))
img.save('$SAMPLE_IMAGE')
print('Generated test image: $SAMPLE_IMAGE')
"
fi

# Start backend temporarily in background
echo "Starting backend with MOCK_MODE=false..."
MOCK_MODE=false GEMINI_API_KEY="$GEMINI_API_KEY" GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}" \
    python3 -m uvicorn app.main:app --host 127.0.0.1 --port 9090 \
    --app-dir apps/sumai_agent &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:9090/healthz > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

HEALTH=$(curl -s http://127.0.0.1:9090/healthz 2>/dev/null || echo '{"status":"unreachable"}')
echo "Health: $HEALTH"

# Call analyze endpoint with the test image
echo ""
echo "Calling /analyze with real Gemini..."
RESPONSE=$(curl -s -X POST http://127.0.0.1:9090/analyze \
    -F "image=@$SAMPLE_IMAGE;type=image/png" \
    -F "room_hint=genkan" \
    -F "mock=false" \
    2>/dev/null || echo '{"error":"request_failed"}')

# Extract key fields (without jq dependency)
MODE=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('mode','unknown'))" <<< "$RESPONSE" 2>/dev/null || echo "parse_error")
FINDINGS=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(len(d.get('findings',[])))" <<< "$RESPONSE" 2>/dev/null || echo "0")
RISK=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('overall_risk_level','unknown'))" <<< "$RESPONSE" 2>/dev/null || echo "unknown")
ANALYSIS_ID=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('analysis_id','unknown'))" <<< "$RESPONSE" 2>/dev/null || echo "unknown")

echo ""
echo "========================================="
echo "  Smoke Test Results"
echo "========================================="
echo "  Mode:          $MODE"
echo "  Analysis ID:   $ANALYSIS_ID"
echo "  Findings:      $FINDINGS"
echo "  Risk Level:    $RISK"
echo "========================================="

if [[ "$MODE" == *"gemini"* ]]; then
    echo "✅ Real Gemini API was used."
elif [[ "$MODE" == "mock" ]]; then
    echo "⚠️  Mock mode was used (Gemini may not have been reachable)."
else
    echo "❌ Unknown mode: $MODE"
fi

# Clean up
kill $BACKEND_PID 2>/dev/null || true
wait $BACKEND_PID 2>/dev/null || true
echo ""
echo "Backend stopped. Smoke test complete."
