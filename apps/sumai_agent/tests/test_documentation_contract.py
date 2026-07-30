from pathlib import Path


DOCS = Path(__file__).resolve().parents[3] / "docs"


def _document(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_architecture_documents_the_current_typed_pipeline_and_identity_boundary() -> None:
    architecture = _document("architecture.md")

    for required in (
        "room_checklists.yaml",
        "RelationshipEngine",
        "result_key",
        "semantic_hash",
        "absent_with_full_coverage",
        "is_not_applicable",
        "analysis-mode-banner",
        "not HTTP end-to-end",
        "synthetic",
        "not recognition evidence",
        "scored_applicable_response_coverage",
        "results are abstentions",
        "rule identity",
        "evidence bbox",
        "IoU",
        "schema_version",
        "local_mock",
    ):
        assert required in architecture


def test_gemini_document_describes_the_facts_contract_and_retires_legacy_claims() -> None:
    gemini = _document("gemini_integration.md")

    for required in (
        "GEMINI_FACTS_JSON_SCHEMA",
        "absent_with_full_coverage",
        "RelationshipEngine",
        "google-genai>=2.10.0,<3.0",
    ):
        assert required in gemini
    assert "demo_rules.yaml" not in gemini
    assert "VisionResult schema" not in gemini
    assert "0–1000" not in gemini
    assert "Invalid individual findings are skipped" not in gemini


def test_risk_and_stability_documents_state_the_live_safety_thresholds() -> None:
    risk_policy = _document("risk_policy.md")
    stability = _document("llm_stability_plan.md")

    for threshold in ("0.45", "0.60"):
        assert threshold in risk_policy
    assert "Unknown risks are not accepted at any confidence." in risk_policy
    assert "absent_with_full_coverage" in stability
    assert "is_not_applicable" in stability
    assert "analysis-mode-banner" in stability
    assert "Only `is_not_applicable=true`" in risk_policy
    assert "known home room" in risk_policy
    assert "synthetic" in stability
    assert "not recognition evidence" in stability
    assert "scored_applicable_response_coverage" in stability
    assert "strict malformed JSON behavior" not in stability


def test_decisions_retires_rag_lite_demo_rules_language() -> None:
    decisions = _document("decisions.md")

    assert "room_checklists.yaml" in decisions
    assert "OntologyRepository" in decisions
    assert "is_not_applicable" in decisions
    assert "analysis-mode-banner" in decisions
    assert "scored_applicable_response_coverage" in decisions
    assert "demo_rules.yaml" not in decisions


def test_documents_distinguish_localized_hazards_from_absence_coverage() -> None:
    architecture = _document("architecture.md")
    gemini = _document("gemini_integration.md")
    risk_policy = _document("risk_policy.md")
    decisions = _document("decisions.md")

    for document in (architecture, gemini, risk_policy, decisions):
        assert "coverage region" in document
        assert "installation position" in document
    assert "only `visible_hazard` findings receive image overlays" in architecture
    assert "room-template" in architecture


def test_government_review_docs_reflect_source_layer_without_overclaiming() -> None:
    risk_gaps = _document("risk_gap_analysis.md")
    pre_review = _document("pre_government_review.md")

    for document in (risk_gaps, pre_review):
        assert "room_checklists.yaml" in document
        assert "OntologyRepository" in document
        assert "source_registry" in document
        assert "basis_source_map" in document
        assert "demo_rules.yaml" not in document
        assert "government endorsement" in document

    assert "No government pilot protocol" in risk_gaps
    assert "No formal evaluation metrics" in risk_gaps
    assert "Not suitable now" in pre_review


def test_documents_define_visible_findings_and_neutral_confirmations_as_separate_channels() -> None:
    architecture = _document("architecture.md")
    risk_policy = _document("risk_policy.md")
    decisions = _document("decisions.md")

    assert "`findings` and `confirmation_items` are separate output channels" in architecture
    assert "schema `2.1.0`" in architecture
    assert "ontology `1.0.1`" in architecture
    assert "inference config `1.0.6`" in architecture
    assert "`semantic_hash` includes `confirmation_items`" in architecture
    assert "Actual-photo browser verification remains required" in architecture
    assert "`findings` contains only `visible_hazard`" in risk_policy
    assert "`confirmation_items` never affects overall risk" in risk_policy
    assert "has no bbox, severity, risk level, or action" in risk_policy
    assert "No visible hazard means `overall_risk_level=low`" in risk_policy
    assert "A photo-scoped non-detection does not create an action" in decisions
    assert "ignores legacy `observations` and `missing_safety_features`" in decisions


def test_government_review_limits_red_boxes_to_localized_visible_hazards() -> None:
    pre_review = _document("pre_government_review.md")

    assert "Red boxes show only localized `visible_hazard` findings." in pre_review
    assert (
        "Red boxes show only visible or explicitly missing visible safety features."
        not in pre_review
    )
    assert "missing handrails in visible areas" not in pre_review
    assert "maps observations and missing visible features to risk findings" not in pre_review


def test_current_state_docs_never_promote_expected_non_detections_to_risks() -> None:
    stability = _document("llm_stability_plan.md")
    gemini = _document("gemini_integration.md")
    evidence_map = _document("japan_housing_evidence_map.md")

    for document in (stability, gemini, evidence_map):
        assert (
            "Expected-feature non-detections enter only neutral "
            "`confirmation_items`; they never enter `findings`, `RuleEngine`, "
            "actions, or overlays."
        ) in document
        assert (
            "Only localized `visible_hazard` evidence may enter `findings` "
            "and `RuleEngine`."
        ) in document

    for retired_claim in (
        "required for a missing-feature finding",
        "coordinate-backed missing feature or visible hazard",
        "preserves exact `(room, ontology_key, rule_kind)` identity into `RuleEngine`",
    ):
        assert retired_claim not in stability

    assert "it creates no missing-feature finding" not in gemini
    assert "carries that identity on the finding. `RuleEngine`" not in gemini

    for retired_route in (
        "`bathroom_missing_non_slip`",
        "`toilet_missing_handrail`",
        "`toilet_transfer_support`",
        "`toilet_slip`",
        "`kitchen_slip`",
        "`kitchen_unreachable_storage`",
        "Must be in report renderer and rule engine as a first-class section.",
    ):
        assert retired_route not in evidence_map

    assert (
        "Support-feature non-detection is confirmation-only; it never justifies "
        "high-risk classification or professional action."
    ) in evidence_map
    for retired_semantic_claim in (
        "absence of visible handrail",
        "no visible support",
    ):
        assert retired_semantic_claim not in evidence_map


def test_docs_define_truthful_streamed_waiting_and_resource_boundary() -> None:
    architecture = _document("architecture.md")
    decisions = _document("decisions.md")

    assert "single NDJSON response" in architecture
    assert "`POST /analyze/stream`" in architecture
    assert "`intake_complete`" in architecture
    assert "`vision_complete`" in architecture
    assert "cache hits and coalesced followers" in architecture
    assert "static browser data" in architecture
    assert "synchronous `/analyze`" in architecture

    assert "no polling and no additional Gemini request" in decisions
    assert "indeterminate activity bar" in decisions
    assert "five seconds" in decisions
    assert "20 seconds" in decisions
    assert "`prefers-reduced-motion`" in decisions
    assert "no percentage or ETA" in decisions
