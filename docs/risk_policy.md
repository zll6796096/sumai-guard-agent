# Risk Policy

This local POC presents cautious, photo-scoped safety candidates. It does not make medical, care-level, insurance, legal, subsidy, or construction judgments, and it does not collect a resident profile.

## Evidence gate before policy

Only `RelationshipEngine` may turn typed visual facts into candidate findings. A visible hazard needs a clear entity and a configured full relationship triple (subject, predicate, target). A missing expected feature needs `absent_with_full_coverage` plus an evidence bbox; `cannot_determine`, partial coverage, a non-home image, or an unknown room produces no finding.

Only `is_not_applicable=true` is a neutral not-applicable result. It is reserved for non-home, unknown-room, or explicit insufficient-evidence facts, and requires empty findings/actions plus a non-empty neutral reason. The web UI then hides its compatibility low-risk summary, images, and suggestion button.

A known home room with `is_not_applicable=false` and ordinary empty findings is different: it means no obvious candidate was detected in the visible, validated scope. It keeps the ordinary `overall_risk_level=low` compatibility semantics and must not be reclassified as neutral not-applicable. It is also not proof that the home is safe or risk-free beyond the photo.

## Confidence and known-rule gate

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
