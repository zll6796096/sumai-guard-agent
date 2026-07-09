# Gemini Integration

## Overview

SumaiGuard Agent uses the Google GenAI SDK (`google-genai`) to analyze home photos for elderly fall/slip/trip risks. Gemini provides risk candidates via structured JSON output; the deterministic rule engine controls all action routing afterward.

## SDK

- Package: `google-genai>=0.6.0`
- Client: `genai.Client(api_key=...)`
- Model: Configurable via `GEMINI_MODEL` (default: `gemini-2.5-flash`)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (empty) | API key from Google AI Studio |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model name |
| `MOCK_MODE` | `true` | Skip Gemini when true |
| `REQUIRE_REAL_GEMINI` | `false` | Sets strict production mode where mock fallback is disabled |
| `ANALYSIS_TIMEOUT` | `120` | Timeout in seconds |

## Prompt Design

The vision prompt instructs Gemini to:

1. Analyze one home photo for elderly fall/slip/trip risks.
2. Identify only risks **visible** in the image.
3. Use `room_hint` as weak context (correctable).
4. Return strict JSON with the `VisionResult` schema.
5. Never say "違反" — use cautious phrases instead:
   - リスクがあります
   - 該当する可能性があります
   - 専門確認が必要です
6. Never claim exact measurements.
7. Never invent objects not visible in the photo.
8. Never produce final renovation/medical/insurance/construction judgment.

### Structured Output

The API call uses `response_mime_type="application/json"` to enforce JSON output:

```python
config=types.GenerateContentConfig(response_mime_type="application/json")
```

## Bbox Normalization

Gemini sometimes returns bbox coordinates in different ranges. The service handles:

### Normal Range (0–1)
Values already in 0–1 are used as-is.

### 0–1000 Range
If any bbox value is > 1.0 but all values are ≤ 1000, divide by 1000:

```
{x: 100, y: 200, w: 500, h: 300} → {x: 0.1, y: 0.2, w: 0.5, h: 0.3}
```

### Invalid Values
- Negative values → clamped to 0.0
- Values > 1.0 (after normalization) → clamped to 1.0
- Zero-size boxes → replaced with minimum visible size
- Missing bbox → safe default with `needs_human_confirmation=true`

## Fallback Behavior (Only when REQUIRE_REAL_GEMINI=false)

When strict mode is disabled (`REQUIRE_REAL_GEMINI=false`), the service falls back to mock mode (with explicit warnings) when:

| Condition | Fallback Reason |
|-----------|----------------|
| `MOCK_MODE=true` | Configured mock mode |
| `GEMINI_API_KEY` empty | No API key |
| JSON decode error | `gemini_json_decode_error` |
| Unexpected JSON type | `gemini_unexpected_json_type` |
| Request timeout | `gemini_timeout` |
| Any API exception | `gemini_error: <type>: <message>` |

Fallback:
- Returns valid mock findings for the requested room type.
- Logs the fallback reason.
- Sets the mode to `gemini_fallback(reason)` in the response.

### Strict Mode Behavior (When REQUIRE_REAL_GEMINI=true)

If `REQUIRE_REAL_GEMINI=true` is set:
- Mock mode fallback is completely disabled.
- If the Gemini API key is missing or any call fails, the backend immediately throws a `GeminiUnavailableError` and returns `503 Service Unavailable` with `{"error": "gemini_unavailable"}`.
- If a non-home image is uploaded, it returns `is_home_environment=false`, 0 findings, and `overall_risk_level=low` without fallback.

## Pydantic Validation

All findings are validated through `RiskFinding` and `BoundingBox` Pydantic models:

- `BoundingBox`: x, y, w, h all `ge=0.0, le=1.0`
- `RiskFinding`: severity `ge=1, le=5`, confidence `ge=0.0, le=1.0`
- Invalid individual findings are skipped (logged as `gemini_finding_parse_error`)

## Rule Engine Boundary

**Critical**: Gemini may identify visible risks, but it **cannot override** the deterministic rule engine:

- Family actions remain no-cost only.
- Care manager actions remain purchase/rental/welfare-equipment only.
- Contractor actions remain construction/on-site confirmation only.
- Action routing is controlled by `demo_rules.yaml` and the `RuleEngine` class.

## Logging

Structured JSON logs include:

| Field | Description |
|-------|-------------|
| `analysis_id` | Correlation ID for the request |
| `mode` | `mock`, `gemini`, or `gemini_fallback` |
| `model` | Gemini model name |
| `latency_ms` | Time taken in milliseconds |
| `finding_count` | Number of findings returned |
| `fallback_reason` | Why fallback occurred (if applicable) |

Never logged: image bytes, API keys.

## Smoke Test

```bash
GEMINI_API_KEY=your-key ./scripts/smoke_real_gemini.sh
```

This script:
1. Leverages the python runner `scripts/smoke_real_gemini.py`.
2. Validates home environment checks using hallway sample image.
3. Validates non-home environment checks using generated solid color image.
4. Validates that strict mode works and correctly rejects mock data.
5. Never prints the API key.

## Testing

```bash
python -m pytest apps/sumai_agent/tests -v
```

Tests cover:
- Strict mode HTTP 503 error responses when Gemini is unavailable.
- Home environment detection (returns is_home_environment=True).
- Non-home environment detection (returns is_home_environment=False).
- Empty findings fallback text rendering on action lists.
- Confidence thresholding (<0.45 discarded; 0.45-0.60 keeps only known risk + needs human confirm; unknown risk needs >=0.75).
- Valid JSON parsing and bbox normalizations.
