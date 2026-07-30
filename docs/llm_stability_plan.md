# LLM Stability Plan

Review date: 2026-07-29 JST

Scope: current defenses for the local SumaiGuard POC and the remaining evidence gaps. This is not a government, clinical, construction, or production-readiness approval.

## Current defenses

| Layer | Implemented defense | Consequence |
|---|---|---|
| Input/privacy | Decode in memory, strip EXIF by PNG re-encoding, do not persist image/result, do not log image bytes or raw provider output. | Limits retained sensitive material. |
| Provider output | `GEMINI_FACTS_JSON_SCHEMA` is ontology-derived, closed, and limited to minimal visual facts. | Gemini has no severity/action/report authority. |
| Parser | Strict Pydantic parsing rejects malformed shape, unknown vocabulary/regions/predicates, duplicate refs/features, dangling relationships, string numeric values, and invalid bboxes. | Invalid provider output cannot become a partial finding. |
| Ontology document | Each room requires unique keys within `visible_hazards` and within `expected_features`; safe validation failures do not echo document contents. Cross-kind overlap remains valid because identity includes `rule_kind`. | Ambiguous same-kind lookup fails at startup without disclosing ontology text. |
| Absence | `absent_with_full_coverage` plus a local coverage bbox may support a neutral confirmation; `cannot_determine` yields no output item. | Out-of-frame or ambiguous features are not treated as absent, risky, or actionable. |
| Relationship | `RelationshipEngine` requires a configured full subject/predicate/target triple and clear, localized entity visibility before creating a visible finding. | Object names alone cannot trigger a risk, and duplicate `risk_type` values cannot select another rule's copy or actions. |
| Policy | Room-scoped ontology plus Python `RuleEngine` sets severity, Japanese copy, source IDs, thresholds, and three action tiers. | The model cannot override deterministic safety policy. |
| Score semantics | The API keeps `confidence` for compatibility and thresholds, while reports display `モデル検出スコア（未校正）`. | A model score is not presented as a calibrated probability of correctness. |
| Non-applicability | Only non-home, uncertain/unknown-room, or explicit insufficient-evidence facts set public `is_not_applicable=true`, with empty findings/actions and a non-empty reason. | The UI hides its compatibility low summary/images/actions only for that true state; a known-home false empty result remains ordinary low-compatible “no obvious candidate detected,” not neutral output. |
| Identity | Canonical findings, `result_key`, and `semantic_hash` separate calculation inputs from reader-facing semantics. `result_key` includes `schema_version`; IoU dedup uses exact ontology identity and only falls back to `risk_type` when both findings lack identity. | A schema change changes computation identity; duplicates of one rule do not duplicate actions, while distinct rules sharing a risk type are retained. |
| Rendering | Positive in-frame evidence bbox coordinates drive danger selection, overlap suppression, and annotated red boxes. Canonicalization clears `display_bbox`; presentation mapping is improvement-image-only. | Display values cannot select retained evidence or change semantic identity. |
| Legacy evidence | Boolean observations and missing-feature inputs are ignored; only localized visible-hazard input may reach the shared rule gate. | Checklist compatibility cannot fabricate a whole-image bbox or actionable absence. |
| Memo | Bounded process-local TTL/LRU cache stores semantic output only; fallback is uncached and each request renders again. | No images in memo and no fallback masquerading as stable analysis. |
| Web proxy | Safe 400/422 and other 4xx responses preserve upstream status but not detail. Neutral local fallback is limited to transport failure, invalid 200 JSON, and explicit non-strict 5xx handling. | Invalid input is not misreported as backend unavailability or a successful analysis. |
| Async/time | Pillow work uses `to_thread`; reusable Gemini and web `httpx` clients close on lifespan shutdown; agent default is 120s and local proxy budget is 150s. | Avoids blocking the event loop and sets a local failure budget. |
| Timing/logs | Final structured logs carry stage timings and private cache-hit metadata; instrumented total is not HTTP end-to-end. | Diagnostic timing is not misrepresented as browser latency. |
| Benchmark | Synthetic fixtures have repeat bounded to 50. Schema-valid `is_not_applicable=true` results are abstentions, excluded from risk P/R/F1; `scored_applicable_response_count` and `scored_applicable_response_coverage` (denominator: repeated `request_count`) report the scoring coverage. | Synthetic metrics are **not recognition evidence**; no applicable scored response leaves metrics unavailable rather than assigning empty-set accuracy. |

The completed result includes an always-visible `analysis-mode-banner`; it does not depend on `?debug=1`. It labels Gemini, mock, local mock, `gemini_fallback(...)`, and `gemini_partial(...)` separately, so fallback, partial, and mock output cannot look like a complete Gemini analysis in the ordinary UI.

Expected-feature non-detections enter only neutral `confirmation_items`; they never enter `findings`, `RuleEngine`, actions, or overlays. Only localized `visible_hazard` evidence may enter `findings` and `RuleEngine`.

When the browser cannot reach the backend in non-strict local mode, or the explicit invalid-200/5xx fallback policy applies, `local_mock` returns a neutral not-applicable abstention with empty findings/actions and identical unannotated images. Its `analysis_id` is request-local while stable inputs retain stable result and semantic hashes. It does not fabricate a medium-risk box or recommendations. Client-input 4xx responses never enter this path. This is separate from the agent's intentional deterministic mock mode used by tests and credential-free POC runs.

## Strict and demo status gate

For a real-Gemini demonstration, set `MOCK_MODE=false`, `REQUIRE_REAL_GEMINI=true`, and provide a valid key by the runtime environment. Missing key, timeout, provider error, malformed facts, or parser rejection returns safe 503. The UI/operator must treat that as a failed analysis, not substitute sample output.

For non-strict local work, a first-call failure may return `gemini_fallback(reason)` using deterministic mock facts. A failed optional room-scoped follow-up returns a neutral not-applicable result as `gemini_partial(followup_reason)` rather than replacing the first real room classification with unrelated mock risk evidence. Both are visibly mode-labelled, uncached, and unsuitable as evidence that Gemini completed the photo analysis. Missing key enters direct mock mode rather than claiming a provider attempt.

## What is intentionally not inferred

The system does not infer resident gait, health, care need, medication effect, floor friction, exact dimensions, wall backing, benefit eligibility, or construction feasibility. The action output is constrained to no-cost family actions, consultation topics, or professional/on-site confirmation according to ontology policy.

## Remaining gaps and next evidence needed

- No reviewed real-photo gold set is committed, so there is no verified real recognition accuracy or error-rate claim.
- The semantic memo is not cross-process or persistent; TTL expiry, restart, or another worker can produce a new Gemini response.
- Real Gemini output remains nondeterministic after memo TTL expiry or restart, even with strict parsing.
- Synthetic benchmark metrics are pipeline checks, not recognition evidence.
- Image-quality coverage (dark, blurred, too-close, obstructed, and incomplete-path photos) still needs reviewed real-photo cases and acceptance labels.
- Cloud deployment is outside this local POC change. Existing deployment-request timeout behavior may not align with the 150-second local proxy budget and is an unresolved scope risk.

Before any external pilot claim, add reviewed labels and acceptance criteria, run strict real-mode status checks, document the test population and failure cases, and keep results separate from mock/synthetic runs.
