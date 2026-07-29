# Gemini Integration

## Boundary

Gemini is a minimal visual-evidence extractor for one possible home photo. It may return environment, room, visible regions, entities, expected-feature observations, and relationships. It must not decide risk severity, labels, action tiers, recommendations, report text, medical/care/insurance meaning, legal compliance, or construction feasibility. Python owns all of those downstream decisions.

The POC remains usable in clearly labelled mock mode. It never persists uploaded images; intake strips EXIF by re-encoding sanitized pixels, and logs exclude image bytes, raw provider payloads, and API keys.

## SDK and lifecycle

- Dependency: `google-genai>=2.10.0,<3.0`.
- The service creates `genai.Client(api_key=...)` lazily and reuses it while the process is alive.
- Provider calls are asynchronous: `await client.aio.models.generate_content(...)`.
- FastAPI lifespan calls `aclose()` on shutdown, which closes `client.aio` when present.
- The web proxy has its own reusable async `httpx.AsyncClient`; it is not the Gemini client.

No API key example belongs in this document or in logs.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `GEMINI_API_KEY` | empty | Enables a real provider request when mock mode is off. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Provider model identifier included in computation identity. |
| `MOCK_MODE` | `true` | Uses deterministic local facts instead of Gemini. |
| `REQUIRE_REAL_GEMINI` | `false` | Strict mode: real Gemini is required and fallback is disabled. |
| `ANALYSIS_TIMEOUT` | `120` | Agent-side provider budget in seconds. |

The web proxy budget is separate: it defaults to the 120-second agent budget plus a 30-second margin (150 seconds). See `docs/architecture.md` for its scope and timing definition.

## Facts contract

The current provider contract is `GEMINI_FACTS_JSON_SCHEMA`, passed as the JSON response schema with `response_mime_type="application/json"`. It is ontology-derived and closed: room names, entity keys, expected feature keys, relationship predicates, and visible regions come from `room_checklists.yaml`.

`VisionFacts` contains only these typed facts:

- `environment`: `home`, `non_home`, or `uncertain`;
- `room_type`, including `unknown` when the photo does not establish a room;
- declared `visible_regions`;
- entities with a unique `ref`, ontology key, visibility, score, and evidence bbox;
- expected-feature observations with `present`, `absent_with_full_coverage`, or `cannot_determine`; and
- full relationship triples: `subject`, `predicate`, `object`.

The prompt requires direct, minimal visual evidence. A feature may be `absent_with_full_coverage` only when the relevant area is fully visible. Cropped, obscured, or ambiguous evidence must be `cannot_determine`; it creates no missing-feature finding. Negative observation of a bathroom chair uses the expected key `has_shower_chair`, not a negated ontology key.

Evidence bboxes are normalized floating-point values in the inclusive 0..1 image coordinate domain, with positive width/height and `x + w` / `y + h` in bounds. Evidence bboxes are analysis facts; a presentation-only `display_bbox` is derived later and is not provider evidence. The legacy parser has compatibility tests, but it is not the current provider contract and does not justify a provider-path default box or coordinate clamping.

## Strict parsing and deterministic ownership

The parser rejects malformed JSON, non-object responses, missing required fields, unknown vocabulary, unknown region, unknown predicate, duplicate entity refs, duplicate feature observations, dangling relationships, non-boolean/non-numeric strict values, and invalid or out-of-bounds bboxes. It logs only a safe failure reason and raw length, never raw provider content. It does not silently skip invalid facts.

After parsing, `RelationshipEngine` verifies room-scoped ontology membership and the configured subject/predicate/target triple. `RuleEngine` then assigns severity, Japanese wording, source IDs, confidence treatment, and actions from `room_checklists.yaml`. Gemini cannot override the deterministic policy or its three action tiers.

Non-home, uncertain, unknown-room, or explicitly not-applicable facts yield neutral not-applicable output rather than a low-risk/no-risk conclusion.

## Failure and fallback behavior

With `REQUIRE_REAL_GEMINI=true`, missing key, timeout, provider error, malformed response, or parser rejection returns safe HTTP 503 (`gemini_unavailable`). No mock result is presented as real Gemini analysis.

With strict mode off, a real-call timeout, provider error, or parser rejection returns deterministic mock facts with mode `gemini_fallback(reason)`. Such fallback work is explicitly labelled and is not memoized. If no key is configured, the service enters direct `mock` mode; it does not claim a Gemini call occurred. Forced mock and configured mock are likewise explicit modes.

The public response exposes `is_not_applicable` as a strict boolean. Only a true value is neutral not-applicable: it requires empty findings/actions and a non-empty neutral reason, so the web result screen hides its compatibility `overall_risk_level=low`, risk summary, images, and action navigation. A known home room with false plus ordinary empty findings remains the normal low-compatible “no obvious candidate detected” result, not neutral output. Its non-debug `analysis-mode-banner` always displays whether the result was Gemini, mock, local mock, or fallback; mock/fallback are never labelled as Gemini analysis.

## Testing and safe operation

Run the backend suite with the project Python environment:

```bash
python3 -m pytest apps/sumai_agent/tests -v
```

Tests cover strict 503 behavior, facts parsing, relationship targets, full-coverage absence, deterministic policy, mock analysis, lifecycle closure, and the distinction between evidence and presentation rendering. A real smoke test requires an intentionally supplied environment key and must be treated as a connectivity/status check, not an accuracy evaluation.
