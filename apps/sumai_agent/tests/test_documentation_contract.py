import json
import os
import re
import subprocess
from pathlib import Path


DOCS = Path(__file__).resolve().parents[3] / "docs"
ROOT = DOCS.parent


def _document(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _root_document(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _normalized(document: str) -> str:
    return " ".join(document.split())


COMPOSE_ENV_NAMES = {
    "ANALYSIS_TIMEOUT",
    "APP_CHECK_REQUIRED",
    "FIREBASE_APP_ID",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GOOGLE_CLOUD_PROJECT",
    "LOG_LEVEL",
    "MAX_SOURCE_PIXELS",
    "MAX_UPLOAD_BYTES",
    "MOCK_MODE",
    "PUBLIC_WEB_ANALYSIS_ENABLED",
    "REQUIRE_REAL_GEMINI",
    "RESULT_MEMO_MAX_ITEMS",
    "RESULT_MEMO_TTL_SECONDS",
    "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS",
    "SUMAI_AGENT_URL",
    "SUMAI_BIND_ADDRESS",
    "SUMAI_WEB_PORT",
}


def _resolved_compose(overrides: dict[str, str] | None = None) -> dict[str, object]:
    environment = os.environ.copy()
    for name in COMPOSE_ENV_NAMES:
        environment.pop(name, None)
    environment.update(overrides or {})
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env.example"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_readme_documents_the_native_api_probe_and_public_error_contract() -> None:
    readme = _root_document("README.md")
    normalized = _normalized(readme)

    for route in (
        "/api/v1/analyze",
        "/health",
        "/ready",
        "/privacy",
        "/support",
    ):
        assert route in readme

    for error_code in (
        "INVALID_IMAGE",
        "APP_CHECK_INVALID",
        "IMAGE_TOO_LARGE",
        "SERVICE_LIMITED",
        "GEMINI_UNAVAILABLE",
        "INTERNAL_ERROR",
    ):
        assert error_code in readme

    assert "10 MiB (10,485,760 bytes)" in normalized
    assert "25,000,000 decoded source pixels" in normalized
    assert "`/analyze` is compatibility-only" in normalized
    assert "`/healthz` is a local compatibility alias" in normalized


def test_resolved_compose_defaults_are_loopback_bound_and_string_typed() -> None:
    services = _resolved_compose()["services"]
    agent = services["sumai-agent"]
    web = services["sumai-web"]

    assert agent["ports"] == [
        {
            "host_ip": "127.0.0.1",
            "mode": "ingress",
            "protocol": "tcp",
            "published": "8080",
            "target": 8080,
        }
    ]
    assert web["ports"] == [
        {
            "host_ip": "127.0.0.1",
            "mode": "ingress",
            "protocol": "tcp",
            "published": "8081",
            "target": 8080,
        }
    ]

    for service in (agent, web):
        assert all(
            isinstance(value, str) for value in service["environment"].values()
        )

    agent_environment = agent["environment"]
    web_environment = web["environment"]
    expected_agent_environment = {
        "APP_CHECK_REQUIRED": "false",
        "FIREBASE_APP_ID": "",
        "MAX_UPLOAD_BYTES": "10485760",
        "MAX_SOURCE_PIXELS": "25000000",
        "RESULT_MEMO_TTL_SECONDS": "300",
        "RESULT_MEMO_MAX_ITEMS": "128",
    }
    for name, value in expected_agent_environment.items():
        assert agent_environment[name] == value
    assert web_environment["PUBLIC_WEB_ANALYSIS_ENABLED"] == "true"
    for agent_only in (
        "APP_CHECK_REQUIRED",
        "FIREBASE_APP_ID",
        "MAX_UPLOAD_BYTES",
        "MAX_SOURCE_PIXELS",
        "RESULT_MEMO_TTL_SECONDS",
        "RESULT_MEMO_MAX_ITEMS",
    ):
        assert agent_only not in web_environment
    assert "PUBLIC_WEB_ANALYSIS_ENABLED" not in agent_environment


def test_resolved_production_shaped_compose_keeps_values_string_typed_and_owned() -> None:
    services = _resolved_compose(
        {
            "APP_CHECK_REQUIRED": "true",
            "FIREBASE_APP_ID": "test-ios-app-id",
            "MOCK_MODE": "false",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "RESULT_MEMO_MAX_ITEMS": "256",
            "RESULT_MEMO_TTL_SECONDS": "600",
            "SUMAI_BIND_ADDRESS": "127.0.0.1",
        }
    )["services"]
    agent_environment = services["sumai-agent"]["environment"]
    web_environment = services["sumai-web"]["environment"]

    assert agent_environment["APP_CHECK_REQUIRED"] == "true"
    assert agent_environment["FIREBASE_APP_ID"] == "test-ios-app-id"
    assert agent_environment["MOCK_MODE"] == "false"
    assert agent_environment["REQUIRE_REAL_GEMINI"] == "true"
    assert agent_environment["RESULT_MEMO_MAX_ITEMS"] == "256"
    assert agent_environment["RESULT_MEMO_TTL_SECONDS"] == "600"
    assert web_environment["PUBLIC_WEB_ANALYSIS_ENABLED"] == "false"
    for service in services.values():
        assert all(
            isinstance(value, str) for value in service["environment"].values()
        )


def test_privacy_guidance_distinguishes_memoized_text_from_binary_artifacts() -> None:
    readme = _root_document("README.md")
    normalized = _normalized(readme)
    lowered = normalized.lower()

    for required in (
        "structured semantic result, including generated report/advice text",
        "may be held and reused briefly in the bounded process-local TTL memo",
        "uploaded image bytes, the sanitized PNG, annotated image bytes, and PDF bytes are not stored in the memo",
        "PDF bytes are generated on demand and are not persisted or cached",
        "no database or account history",
        "cleared when the worker process restarts",
    ):
        assert required in normalized

    for forbidden in (
        "reports/pdfs are generated per request",
        "report text is never retained",
        "reports are never retained",
        "result is never retained",
        "results are never retained",
    ):
        assert forbidden not in lowered


def test_upload_docs_describe_declared_mime_and_enforced_size_boundaries() -> None:
    readme = _root_document("README.md")
    normalized = _normalized(readme)

    for required in (
        "multipart `image` part must declare `image/jpeg` or `image/png`",
        "Pillow decodes the supplied pixels and the intake strips metadata",
        "does not independently magic-sniff and reject every other encoded format when a file is mislabeled",
        "Send a sanitized JPEG or PNG and label it accurately",
        "10 MiB (10,485,760 bytes) is the image file-part byte limit",
        "enforced during orchestrator upload reads after App Check",
        "not a limit on the entire multipart request",
        "25,000,000 decoded source pixels",
    ):
        assert required in normalized

    assert "containing exactly JPEG or PNG" not in normalized
    assert "The request limit is 10 MiB" not in normalized


def test_local_example_is_credential_free_and_has_safe_phase_one_defaults() -> None:
    env_example = _root_document(".env.example")

    for exact_line in (
        "MOCK_MODE=true",
        "REQUIRE_REAL_GEMINI=false",
        "APP_CHECK_REQUIRED=false",
        "FIREBASE_APP_ID=",
        "MAX_UPLOAD_BYTES=10485760",
        "MAX_SOURCE_PIXELS=25000000",
        "PUBLIC_WEB_ANALYSIS_ENABLED=true",
        "RESULT_MEMO_TTL_SECONDS=300",
        "RESULT_MEMO_MAX_ITEMS=128",
        "SUMAI_BIND_ADDRESS=127.0.0.1",
    ):
        assert exact_line in env_example.splitlines()


def test_compose_passes_local_safe_security_limits_to_the_correct_services() -> None:
    compose = _root_document("docker-compose.yml")
    agent, web = compose.split("  sumai-web:", maxsplit=1)

    for exact_setting in (
        "APP_CHECK_REQUIRED: ${APP_CHECK_REQUIRED:-false}",
        "FIREBASE_APP_ID: ${FIREBASE_APP_ID:-}",
        "MAX_UPLOAD_BYTES: ${MAX_UPLOAD_BYTES:-10485760}",
        "MAX_SOURCE_PIXELS: ${MAX_SOURCE_PIXELS:-25000000}",
        "RESULT_MEMO_TTL_SECONDS: ${RESULT_MEMO_TTL_SECONDS:-300}",
        "RESULT_MEMO_MAX_ITEMS: ${RESULT_MEMO_MAX_ITEMS:-128}",
    ):
        assert exact_setting in agent
        assert exact_setting not in web

    assert (
        "PUBLIC_WEB_ANALYSIS_ENABLED: ${PUBLIC_WEB_ANALYSIS_ENABLED:-true}"
        in web
    )
    assert "PUBLIC_WEB_ANALYSIS_ENABLED:" not in agent
    assert "MOCK_MODE: ${MOCK_MODE:-true}" in agent
    assert "MOCK_MODE: ${MOCK_MODE:-true}" in web
    assert '"${SUMAI_BIND_ADDRESS:-127.0.0.1}:8080:8080"' in agent
    assert '"${SUMAI_BIND_ADDRESS:-127.0.0.1}:8081:8080"' in web


def test_readme_documents_loopback_default_and_explicit_unsafe_lan_opt_in() -> None:
    normalized = _normalized(_root_document("README.md"))

    for required in (
        "Docker Compose publishes both services on `127.0.0.1` by default",
        "Setting `SUMAI_BIND_ADDRESS=0.0.0.0` is an explicit LAN opt-in",
        "unsafe while `APP_CHECK_REQUIRED=false` and `PUBLIC_WEB_ANALYSIS_ENABLED=true`",
        "Do not use this LAN opt-in with real Gemini",
    ):
        assert required in normalized


def test_readme_documents_strict_provider_error_routing() -> None:
    normalized = _normalized(_root_document("README.md"))

    assert (
        "A missing Gemini key or a non-quota strict provider failure returns "
        "`503 GEMINI_UNAVAILABLE`"
    ) in normalized
    assert (
        "A recognized provider quota or rate-limit failure returns "
        "`429 SERVICE_LIMITED`"
    ) in normalized


def test_readme_documents_memo_defaults_configurability_and_observation_gate() -> None:
    normalized = _normalized(_root_document("README.md"))

    for required in (
        "`RESULT_MEMO_TTL_SECONDS` | `300`",
        "`RESULT_MEMO_MAX_ITEMS` | `128`",
        "Both memo limits are environment-configurable",
        "structured semantic results and generated report/advice text only",
        "never image or PDF bytes",
        "Phase 3 must observe the deployed memo values before final privacy publication",
    ):
        assert required in normalized


def test_readme_omits_unverified_latency_ranges() -> None:
    readme = _root_document("README.md")

    for unverified_range in (
        "3-15 seconds",
        "3–15 seconds",
        "5-10 seconds",
        "5–10 seconds",
    ):
        assert unverified_range not in readme


def test_task7_artifacts_contain_no_real_credentials_identities_or_service_urls() -> None:
    artifacts = "\n".join(
        _root_document(name)
        for name in (
            ".env.example",
            "docker-compose.yml",
            "README.md",
            "apps/sumai_agent/tests/test_documentation_contract.py",
        )
    )
    forbidden_patterns = {
        "private key block": re.compile(
            "-----BEGIN " + r"[A-Z ]*PRIVATE " + "KEY-----"
        ),
        "credential json": re.compile(
            '"(?:private_' + 'key|client_' + r'email)"\s*:'
        ),
        "Google API key": re.compile("AI" + r"za[0-9A-Za-z_-]{20,}"),
        "GitHub token": re.compile("gh" + r"p_[0-9A-Za-z]{20,}"),
        "OpenAI key": re.compile("sk" + r"-[0-9A-Za-z]{20,}"),
        "email address": re.compile(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            re.IGNORECASE,
        ),
        "Firebase iOS app ID": re.compile(
            r"\b1:\d{6,}:ios:[0-9a-f]{6,}\b",
            re.IGNORECASE,
        ),
        "project number": re.compile(r"(?<![\d_])\d{10,13}(?![\d_])"),
        "Cloud Run service URL": re.compile(
            r"https?://[^\s)>'\"]+\.run\.app\b",
            re.IGNORECASE,
        ),
    }

    for label, pattern in forbidden_patterns.items():
        assert pattern.search(artifacts) is None, label


def test_legacy_cloud_run_entries_are_explicitly_non_release() -> None:
    normalized = _normalized(_root_document("README.md"))

    assert (
        "`GOOGLE_CLOUD_PROJECT` | (empty) | Legacy deploy tooling only; "
        "not for App Store release"
    ) in normalized
    assert (
        "Cloud Run Deployment — legacy/non-release; do not use for App Store release"
    ) in normalized


def test_production_guidance_states_the_app_check_and_gemini_boundaries() -> None:
    readme = _root_document("README.md")
    normalized = _normalized(readme)

    for required in (
        "APP_CHECK_REQUIRED=true",
        "FIREBASE_APP_ID='1:<PROJECT_NUMBER>:ios:<APP_ID_HASH>'",
        "REQUIRE_REAL_GEMINI=true",
        "PUBLIC_WEB_ANALYSIS_ENABLED=false",
        "Application Default Credentials (ADC)",
        "ordinary App Check tokens",
        "does not consume tokens for single-use or replay protection",
        "30 minutes in the Firebase console, not in Python",
        "abuse mitigation, not user authentication",
    ):
        assert required in normalized

    assert not re.search(
        r"FIREBASE_APP_ID=['\"]?1:\d+:ios:[0-9a-f]+",
        readme,
        flags=re.IGNORECASE,
    )


def test_operator_guidance_keeps_observed_facts_and_phase_gates_separate() -> None:
    readme = _root_document("README.md")
    normalized = _normalized(readme)

    for required in (
        "Cloud Logging retention must be observed in the target environment",
        "owner-approved support/operator contact must be confirmed",
        "Phase 1 makes no deployment, traffic, Firebase console, or App Store changes",
        "Phase 3 Cloud Build uses control-plane verification",
        "remove `/status`",
        "Local mock mode needs no Google or Firebase credentials",
        "bounded process-local",
        "does not persist uploaded images or account history",
        "operational logs",
        "legacy and non-release",
        "must not be used for an App Store release",
        "Phase 3 replaces or converges",
    ):
        assert required in normalized


def test_readme_does_not_overclaim_release_or_replay_readiness() -> None:
    readme = _root_document("README.md")
    lowered = readme.lower()

    for forbidden in (
        "app store ready",
        "app-store ready",
        "production ready",
        "production-ready",
        "provides replay protection",
        "prevents token replay",
    ):
        assert forbidden not in lowered


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
