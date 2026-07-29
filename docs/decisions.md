# Product Decisions

## One-photo, privacy-bounded POC

The product accepts one home photo and returns cautious visible-risk candidates with three action tiers. It does not ask age, walking state, fall history, care level, disease, medication, or insurance questions. Uploaded images are sanitized in memory, EXIF is stripped, and neither images nor results are persisted.

Reason: validate whether a low-friction visual safety conversation is useful without collecting sensitive personal data or asserting a broader judgment.

## No RAG or vector database

The POC uses the versioned `room_checklists.yaml` through a typed `OntologyRepository`, not retrieval augmentation. The repository validates rooms, expected features, visible hazards, relationships and targets, source registry, source mappings, schema/version metadata, and action policy.

Reason: the immediate value is reproducible, room-scoped deterministic policy. A vector database would add storage, retrieval uncertainty, and operations without helping this bounded visual-evidence flow.

## Gemini supplies facts; Python supplies policy

The provider output is `GEMINI_FACTS_JSON_SCHEMA`: visual environment/room/regions/entities/features/relationships only. `RelationshipEngine` requires a valid subject/predicate/target triple; absence requires `absent_with_full_coverage` and evidence bbox. `RuleEngine` deterministically assigns known-rule severity, Japanese wording, source IDs, confidence treatment, and the three action tiers.

Reason: a model must not decide medical/care/insurance/construction meaning, action text, or final risk policy. Unknown/insufficient/non-home inputs render neutral not-applicable output, rather than a low-risk conclusion.

## Three action tiers are required

- `家族で今日できること`: no-cost actions only.
- `ケアマネ・福祉用具に相談`: purchase, rental, or welfare-equipment consultation only.
- `専門施工・現地確認`: construction or on-site confirmation only.

Reason: a safety candidate is useful only if the next step remains within its authority. One photo cannot support a final design, exact measurement, construction instruction, legal claim, insurance conclusion, or benefit decision.

## Mock mode and strict real mode

Mock mode is required for local development, tests, and credential-free demonstrations. In strict real mode (`REQUIRE_REAL_GEMINI=true`), missing key, timeout, provider error, malformed facts, or parser rejection fails safely with HTTP 503. Non-strict fallback is explicitly labelled `gemini_fallback(reason)` and is uncached; it cannot be presented as a real analysis.

Reason: availability must not turn a provider failure into a false claim of Gemini recognition.

## Identity, rendering, and memoization

Every request has a random `analysis_id`. `result_key` hashes sanitized-pixel digest, hint, versions, model, and execution policy to identify reusable computation. `semantic_hash` covers stable reader-facing semantic output but excludes images, timing, mode, and presentation-only display bbox. The memo is bounded TTL/LRU, process-local, stores no image, and is not persistent or cross-process; rendering/report delivery remains per request.

Reason: distinguish correlation, safe computation reuse, and semantic equality without retaining user images or treating cache behavior as durable state.

## Benchmarks and logs

Synthetic benchmark repetitions are capped at 50. Mock P/R/F1 = 1 means the deterministic pipeline matched the synthetic fixture; it is not recognition accuracy. Real-mode accuracy requires strict status plus reviewed real-photo labels.

Structured completion logs contain final stage timings and private cache metadata. The published `total` is an instrumented application-stage sum, not HTTP end-to-end latency; it excludes Starlette JSON encoding, socket, and network time.

Reason: a reproducible diagnostic must not become an unsupported performance or recognition claim.

## Local POC versus historical Cloud configuration

Existing Cloud Run scripts/configuration are historical repository material. This Task9 documentation change does not deploy, change, or verify Cloud Run. Any existing 120-second deployment request limit and the local 150-second web proxy budget remain a scope-separated compatibility risk.

Reason: a local POC acceptance result is not production readiness, and deployment behavior must be verified independently before it is claimed.
