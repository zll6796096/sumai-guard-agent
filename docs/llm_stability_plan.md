# LLM Stability Plan

Review date: 2026-07-13 JST

Scope: how SumaiGuard Agent reduces Gemini/LLM instability and what must be strengthened before government-facing demos or pilots.

## 1. Current Risk

The LLM is useful only as a visible-risk candidate extractor. It is not trusted to decide action tiers, medical meaning, care level, insurance eligibility, subsidy eligibility, or construction feasibility.

Main instability risks:

- Hallucinating objects or risks that are not visible.
- Inferring resident health or gait from room photos.
- Returning malformed JSON or partial fields.
- Producing overconfident bounding boxes.
- Misclassifying non-home images.
- Generating high-confidence but institutionally unsupported recommendations.
- Falling back to mock output during a real demo.

## 2. Current Defenses Found In Repo

| Check item | Current status | Evidence |
|---|---:|---|
| Prompt asks for visible risks only. | Present | `VISION_PROMPT` in `apps/sumai_agent/app/services/gemini_vision.py`. |
| Prompt forbids inventing non-visible objects. | Present | Prompt includes "Do not invent objects" and "Do not invent risk". |
| Prompt forbids exact measurements. | Present | Prompt says never claim exact measurements. |
| Prompt forbids medical/care/insurance/construction final judgment. | Present | Prompt and `DISCLAIMER_JA` state boundaries. |
| Structured JSON output. | Present | Gemini config uses `response_mime_type="application/json"`. |
| Pydantic validation. | Present | `RiskFinding`, `BoundingBox`, `VisionResult` in `apps/sumai_agent/app/models.py`. |
| Deterministic rule engine controls action routing. | Present | `RuleEngine.apply()` and `docs/risk_policy.md`. |
| Confidence thresholds. | Present | Rule engine drops `<0.45`; known `0.45-0.60` is human-confirmation; unknown requires `>=0.75`. |
| Low-confidence marking. | Partial | `needs_human_confirmation` exists, but UI summary is weak. |
| Strict mode returns 503 when key missing/API call fails. | Present for API/key failure | `GeminiVisionService.analyze()` and `main.py` error handling. |
| Strict malformed JSON behavior. | Gap | `parse_vision_json()` returns mock on JSON decode/type errors, including inside strict call path. |
| Logs mode/model/latency/fallback_reason. | Mostly present | Structured logging in `main.py`, `gemini_vision.py`, `orchestrator.py`. |
| Avoid mock/fallback as real demo. | Partial | Debug panel can show mode, but normal UI hides it and frontend local fallback exists. |

## 3. Stability Defense Design

### 1. Input Layer Defense

Current:

- Accepts image uploads only.
- Rejects non-image content type.
- Reads image into memory and strips EXIF by re-encoding PNG.
- Resizes large images to max dimension.

Recommended:

- Add explicit max file size and pixel count.
- Add frontend and backend message for poor photo quality: dark, blurry, too close, no floor/path visible.
- Add room-scope prompt hints, but treat room hint as weak context.
- Add non-home negative tests: outdoor, street, people-only, public facility, document, product close-up, furniture showroom.

### 2. Prompt Layer Defense

Current:

- Visible-only.
- No user profile questions.
- Non-home guard.
- No invented objects.
- No exact measurements.
- Cautious Japanese phrases.

Recommended additions:

- Require each risk to include `visible_evidence_type`: `visible_object`, `visible_missing_feature`, `ambiguous`, or `cannot_determine`.
- Require "cannot determine from this photo" for dimensions, floor friction, wall backing, resident movement, care level,制度 eligibility, and construction feasibility.
- Require `risk_type` to come from an allowed list where possible; unknown risk types must be marked `unknown_visible_risk`.

### 3. Schema Layer Defense

Current:

- Pydantic constrains bbox, severity, confidence.
- Invalid individual findings are skipped.
- Bbox normalization handles 0-1 and 0-1000 coordinate ranges.

Critical gap:

- `parse_vision_json()` falls back to mock on malformed JSON. In strict government-demo mode, this is not acceptable.

Recommended code change:

- Add `strict: bool = False` to `parse_vision_json()`.
- In strict mode, JSON decode/type errors raise `GeminiUnavailableError` instead of returning mock.
- Include parser failure reason in logs without raw image or raw sensitive content.
- Add tests:
  - strict malformed JSON returns HTTP 503.
  - strict unexpected JSON type returns HTTP 503.
  - non-strict malformed JSON may fallback only with `mode=gemini_fallback(...)`, never plain `mock`.

### 4. Rule Engine Layer Defense

Current:

- Deterministic action tier policy exists.
- Family tier blocks purchase/rental/construction/professional wording.
- Care-manager and contractor tiers are separated.
- Professional confirmation notes are injected for high-risk room types.

Recommended:

- Add source IDs to rule definitions: `source_ids: ["MHLW_HOUSING_MOD_TYPES", "CAA_FALL_PREVENTION"]`.
- Add automated test that family actions contain no product, brand, buy, rent, construction, contractor, or professional-install language.
- Add automated test that Gemini-provided action text is ignored or rejected if ever added to model output.
- Add `cannot_determine_items` generated by rule engine regardless of Gemini.

### 5. Confidence / Uncertainty Layer Defense

Current:

- Thresholding exists.
- `needs_human_confirmation` exists.

Recommended:

- UI should show "リスク候補" not "リスク判定".
- Each finding should display one of:
  - "写真で確認できる候補"
  - "写真だけでは要確認"
  - "この写真では判断不可"
- Add a summary section:
  - "写真外の動線"
  - "正確な寸法"
  - "床材の摩擦"
  - "壁下地"
  - "本人の歩行・立ち座り動作"
  - "介護保険・助成制度の適用"
  - "施工可否"

### 6. Human Confirmation Layer Defense

Current:

- Contractor tier includes on-site confirmation disclaimers.
- Care manager tier says制度/necessity must be confirmed.

Recommended:

- Report renderer should show a clear "相談先の目安":
  - 地域包括支援センター: where to ask general older-adult support questions.
  - ケアマネ・福祉用具専門相談員: when welfare equipment or care plan relevance exists.
  - 住宅改修/施工専門職: when wall fixing, floor changes, door replacement, toilet replacement, or on-site measurements are involved.
- Never route directly from AI to purchase or contractor request.

### 7. Demo / Production Mode Defense

Current:

- `REQUIRE_REAL_GEMINI=true` disables backend fallback for missing key/API failure.
- `/status` reports mode-related flags.
- Frontend debug panel shows mode only when `?debug=1`.
- Frontend has local mock fallback when backend is unreachable unless `REQUIRE_REAL_GEMINI=true`.

Required for government demos:

- `MOCK_MODE=false`
- `REQUIRE_REAL_GEMINI=true`
- Valid `GEMINI_API_KEY`
- `/status` checked before demo
- Debug panel enabled or separate operator status visible
- Any mock/sample run labeled "mock sample", not "analysis result"
- Backend or Gemini failure returns error; it must not display local mock as successful analysis

Recommended:

- Add a `GOVERNMENT_DEMO_MODE=true` env flag that forces:
  - frontend `FRONTEND_MOCK=false`
  - frontend fallback disabled
  - debug/status badge visible to operator
  - "リスク候補" wording
  - mode included in generated report footer

### 8. Test And Log Defense

Current tests cover:

- health/status.
- mock analysis schema.
- strict missing-key 503.
- non-home no findings.
- empty findings.
- confidence filtering.
- Gemini JSON parsing and bbox normalization.
- visual renderer and label prioritization.

Recommended tests:

- `test_strict_malformed_json_returns_503`
- `test_frontend_strict_backend_unreachable_returns_503`
- `test_government_demo_mode_disables_local_mock`
- `test_report_contains_cannot_determine_section`
- `test_report_uses_risk_candidate_not_diagnosis`
- `test_family_actions_no_purchase_or_rental_or_construction`
- `test_evidence_source_ids_present_for_known_risks`
- `test_non_home_fixture_matrix`

Log requirements:

- Include `analysis_id`, mode, model, latency, finding count, confidence threshold result, fallback reason.
- Do not log image bytes, API keys, full raw Gemini response, personal names, addresses, or EXIF.
- For government demo, retain only operational logs necessary to prove mode and failures; no image retention.

## 4. Strict No-Mock Rule For Government Use

Rule:

If a real-photo government demo or pilot claims Gemini analysis, then any of these must stop output and show an error:

- Missing Gemini API key.
- Gemini API error.
- Gemini timeout.
- Malformed Gemini JSON.
- Unexpected JSON shape.
- Backend unreachable.
- Frontend fallback attempted.

Allowed mock use:

- Local development.
- Automated tests.
- Clearly labeled sample walkthrough using synthetic or sample images.
- Internal design review, never as evidence of real AI performance.

