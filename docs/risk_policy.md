# Risk Policy

This local POC presents cautious, photo-scoped safety candidates. It does not make medical, care-level, insurance, legal, subsidy, or construction judgments, and it does not collect a resident profile.

## Evidence gate before policy

Only `RelationshipEngine` may turn typed visual facts into output candidates. A visible hazard needs a clear entity and a configured full relationship triple (subject, predicate, target). The public `findings` contains only `visible_hazard` entries with localized evidence. A photo-scoped expected-feature non-detection needs `absent_with_full_coverage` plus an input coverage bbox, but it enters the separate neutral `confirmation_items` channel rather than `findings`. `cannot_determine` or partial coverage produces neither channel; a non-home image or unknown room produces the distinct not-applicable state.

The provider-side bbox for an expected-feature non-detection is a coverage region: it records which relevant wall, floor, fixture, or transfer area was visible enough to check. It is not the location of a missing object and must never be presented as a danger location or installation position. A public confirmation item has no bbox, severity, risk level, or action. Only exact `visible_hazard` findings may receive red or improvement overlays, and those overlays stay on the provider evidence rather than a room-template position.

`confirmation_items` never affects overall risk, finding count, risk level, overlays, action tiers, the improvement image, or suggestion navigation. It is cautious text for a human to confirm outside the photo pipeline, not evidence that a safety feature is absent.

Only `is_not_applicable=true` is a neutral not-applicable result. It is reserved for non-home, unknown-room, or explicit insufficient-evidence facts, and requires empty findings/actions plus a non-empty neutral reason. The web UI then hides its compatibility low-risk summary, images, and suggestion button.

A known home room with `is_not_applicable=false` and ordinary empty findings is different: it means no obvious candidate was detected in the visible, validated scope. It keeps the ordinary `overall_risk_level=low` compatibility semantics and must not be reclassified as neutral not-applicable. It is also not proof that the home is safe or risk-free beyond the photo.

No visible hazard means `overall_risk_level=low`, zero findings, empty action tiers, no improvement image, and no suggestions in the applicable UI. The sanitized clean photo remains as context. This describes only the validated visible scope and does not prove that the residence is safe.

## Confidence and known-rule gate

The public field remains named `confidence` for API compatibility, but it carries an uncalibrated model detection score rather than a calibrated probability that a finding is correct. The thresholds below are deterministic routing rules only, and the ordinary report labels the value `モデル検出スコア（未校正）`.

`RuleEngine` applies the following exact order:

- Confidence `< 0.45`: drop the candidate.
- Known ontology rule and `0.45 <= confidence < 0.60`: keep it and set `needs_human_confirmation=true`.
- Known ontology rule and `confidence >= 0.60`: keep it (while preserving any existing confirmation flag).
- Unknown rule with `confidence < 0.75`: drop it.
- Unknown rule with `confidence >= 0.75`: use the conservative fallback policy only if it somehow reaches the rule engine. The facts/ontology pipeline should prevent this route for ordinary provider output.

No provider score bypasses relationship validation, ontology scope, or tier policy. Gemini supplies facts only; it cannot set final severity, copy, or action routing.

## Three required action tiers

The versioned `room_checklists.yaml` ontology supplies known-rule wording, source mapping, and action policy.

### 家族で今日できること

No-cost actions only: for example, remove visible obstacles, share a caution point, or use existing lighting. The family policy rejects purchase, rental, construction, installation-request, and professional wording. It must not turn into a product recommendation.

### ケアマネ・福祉用具に相談

Purchase, rental, or welfare-equipment consultation only. It can identify a topic to discuss but cannot decide that a particular product, benefit, or service is appropriate. It must not instruct construction.

### 専門施工・現地確認

Professional construction or on-site confirmation only. It can route questions about fixed handrails, floor/threshold changes, wall backing, dimensions, or installation position, but it never supplies a final drawing, measurement, eligibility decision, or construction conclusion from one photo.

## Sources and uncertainty

Known ontology rules carry `evidence_source_ids` from the source registry. An empty list is valid only when the corresponding basis label is explicitly mapped to no source in the ontology; the system must not fabricate source IDs or citations.

For higher-impact configured risks, the policy can add a professional on-site confirmation note. That is an uncertainty safeguard, not a diagnosis or instruction to buy, renovate, claim insurance, or apply for a benefit.
