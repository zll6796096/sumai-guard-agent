# Product Decisions

## One-photo, privacy-bounded POC

The product accepts one home photo and returns cautious visible-risk candidates with three action tiers. It does not ask age, walking state, fall history, care level, disease, medication, or insurance questions. Uploaded images are sanitized in memory, EXIF is stripped, and neither images nor results are persisted.

Reason: validate whether a low-friction visual safety conversation is useful without collecting sensitive personal data or asserting a broader judgment.

## No RAG or vector database

The POC uses the versioned `room_checklists.yaml` through a typed `OntologyRepository`, not retrieval augmentation. The repository validates rooms, expected features, visible hazards, relationships and targets, source registry, source mappings, schema/version metadata, and action policy. Within each room, keys must be unique inside each rule kind; the same key across visible and expected rules remains valid because `rule_kind` is part of identity.

Reason: the immediate value is reproducible, room-scoped deterministic policy. A vector database would add storage, retrieval uncertainty, and operations without helping this bounded visual-evidence flow.

## Gemini supplies facts; Python supplies policy

The provider output is `GEMINI_FACTS_JSON_SCHEMA`: visual environment/room/regions/entities/features/relationships only. `RelationshipEngine` requires a valid subject/predicate/target triple for a visible finding; absence requires `absent_with_full_coverage` and an input coverage bbox before it can become a neutral confirmation item. `RuleEngine` deterministically assigns known visible-rule severity, Japanese wording, source IDs, model-score threshold treatment, and the three action tiers. The compatible `confidence` API field is not a calibrated correctness probability, so the user report calls it `モデル検出スコア（未校正）`.

An expected-feature bbox is a provider-side coverage region, not the location of a missing object or an installation position. It can support a neutral confirmation item saying that a feature was not confirmed in the visible scope, but that public item has no bbox, severity, risk level, or action. A photo-scoped non-detection does not create an action. Image overlays are limited to exact `visible_hazard` findings and stay on their evidence bbox.

Reason: a model must not decide medical/care/insurance/construction meaning, action text, final risk policy, or installation position. Unknown/insufficient/non-home inputs render neutral not-applicable output, rather than a low-risk conclusion.

## Three action tiers are required

- `家族で今日できること`: no-cost actions only.
- `ケアマネ・福祉用具に相談`: purchase, rental, or welfare-equipment consultation only.
- `専門施工・現地確認`: construction or on-site confirmation only.

Reason: a safety candidate is useful only if the next step remains within its authority. One photo cannot support a final design, exact measurement, construction instruction, legal claim, insurance conclusion, or benefit decision.

## Mock mode and strict real mode

Mock mode is required for local development, tests, and credential-free demonstrations. In strict real mode (`REQUIRE_REAL_GEMINI=true`), missing key, timeout, provider error, malformed facts, parser rejection, or an invalid room-scoped follow-up fails safely with HTTP 503. Non-strict first-call fallback is explicitly labelled `gemini_fallback(reason)`. A failed optional room-scoped follow-up returns a neutral abstention labelled `gemini_partial(followup_reason)` instead of inventing a mock finding. Both are uncached and cannot be presented as a complete real analysis. The ordinary completed screen has an always-visible `analysis-mode-banner` that separately labels Gemini, mock, local mock, fallback, and partial analysis rather than relying on the optional debug panel.

Reason: availability must not turn a provider failure into a false claim of Gemini recognition.

## Public applicability state

`is_not_applicable` is an additive, strict boolean in every analysis response. Only true denotes neutral non-home, unknown-room, or explicit insufficient-evidence output; it requires empty findings/actions and a non-empty reason. The older `overall_risk_level` enum remains `low` for that wire-compatible state, but the UI hides that summary, annotations, and suggestion navigation when `is_not_applicable=true`, showing the neutral reason instead. A known home room with false and ordinary empty findings remains normal low-compatible “no obvious candidate detected” output, not neutral not-applicable. It retains the clean context photo while hiding the improvement image and suggestions; this is not proof that the home is safe.

Reason: a schema-compatible empty response must not visually imply that the photo establishes a low-risk home.

## Exact rule identity, rendering, and memoization

The relationship path resolves rules by `(room, ontology_key, rule_kind)` and carries exact visible-hazard identity on each finding. Risk-type-only lookup exists only for unambiguous legacy visible callers. `ChecklistEngine` has no neutral confirmation return channel, so it ignores legacy `observations` and `missing_safety_features` and applies the shared `RuleEngine` visible-only gate to `visible_hazards`. This prevents duplicate risk types or expected-feature inputs from selecting another rule's labels, basis, or actions.

Every request, including a web-local abstention, has a random request-local `analysis_id`. `result_key` hashes sanitized-pixel digest, hint, schema/ontology/preprocess/inference versions, model, and execution policy to identify reusable computation. Current schema `2.1.0` and inference config `1.0.5` therefore participate in the key, so a version change changes `result_key`. `semantic_hash` covers stable reader-facing findings, confirmation items, actions, room/applicability semantics, and excludes images, timing, mode, and presentation-only display bbox.

Canonicalization clears `display_bbox`, and overlap deduplication uses exact ontology rule identity before falling back to `risk_type` only for two identity-free legacy findings. Thus presentation values cannot choose the retained evidence, while distinct rules sharing a risk type keep separate actions. The memo is bounded TTL/LRU, process-local, stores no image, and is not persistent or cross-process; rendering/report delivery remains per request.

Annotated danger boxes always use positive, in-frame evidence coordinates from exact `visible_hazard` findings. Boolean-only legacy observations and confirmation items create no image overlay, risk, action, improvement, or suggestion. Red and improvement overlays use the same visible evidence location; visual-zone, anchor, and room-template placement are forbidden. When only confirmation items remain, the renderer returns the unannotated sanitized image and the web UI explains that no image location or installation position can be claimed. The web proxy preserves safe 400/422 and other 4xx statuses instead of converting input rejection into availability fallback, and never forwards the upstream detail. Non-strict `local_mock` is limited to transport failure, invalid JSON on a 200 response, or explicit 5xx fallback; it remains an empty neutral abstention with unannotated images, not fabricated medium-risk findings or actions.

Reason: distinguish correlation, safe computation reuse, and semantic equality without retaining user images or treating cache behavior as durable state.

## Benchmarks and logs

Synthetic benchmark repetitions are capped at 50. Mock P/R/F1 = 1 means the deterministic pipeline matched the synthetic fixture; it is not recognition accuracy. Schema-valid `is_not_applicable=true` output is an abstention, not a risk prediction: it is excluded from P/R/F1 even with an empty gold set. `scored_applicable_response_count` and `scored_applicable_response_coverage` use repeated `request_count` as the coverage denominator, while valid abstentions are reported separately. If no applicable response is scored, risk metrics are unavailable rather than an empty-set accuracy. Real-mode accuracy requires strict status plus reviewed real-photo labels.

Structured completion logs contain final stage timings and private cache metadata. The published `total` is an instrumented application-stage sum, not HTTP end-to-end latency; it excludes Starlette JSON encoding, socket, and network time.

Reason: a reproducible diagnostic must not become an unsupported performance or recognition claim.

## Local POC versus historical Cloud configuration

Existing Cloud Run scripts/configuration are historical repository material. This Task9 documentation change does not deploy, change, or verify Cloud Run. Any existing 120-second deployment request limit and the local 150-second web proxy budget remain a scope-separated compatibility risk.

Reason: a local POC acceptance result is not production readiness, and deployment behavior must be verified independently before it is claimed.
