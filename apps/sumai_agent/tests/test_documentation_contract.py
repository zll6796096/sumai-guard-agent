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

    for threshold in ("0.45", "0.60", "0.75"):
        assert threshold in risk_policy
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


def test_pdf_export_policy_is_text_only_disclaimed_and_nonpersistent() -> None:
    root = Path(__file__).resolve().parents[3]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "PDF report download" not in agents
    assert "PDF report download" not in readme
    for phrase in ("text-only PDF", "disclaimer", "must not persist"):
        assert phrase in agents
    for phrase in (
        "Japanese text-only PDF",
        "does not include photos",
        "not stored",
    ):
        assert phrase in readme


def test_ci_installs_both_app_dependencies_before_collecting_all_tests() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    backend_install = workflow.index(
        "pip install -r apps/sumai_agent/requirements.txt"
    )
    frontend_install = workflow.index(
        "pip install -r apps/sumai_web/requirements.txt"
    )
    full_test_suite = workflow.index(
        "python -m pytest apps/sumai_agent/tests -v"
    )

    assert backend_install < full_test_suite
    assert frontend_install < full_test_suite
