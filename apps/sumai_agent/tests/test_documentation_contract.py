import json
import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from apps.sumai_agent.tests.web_module_loader import load_web_module


DOCS = Path(__file__).resolve().parents[3] / "docs"
ROOT = DOCS.parent
APP_STORE_DOCS = DOCS / "app-store"


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
        "The release process must observe the deployed memo values before final privacy publication",
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
    artifacts = artifacts.replace(
        "zll6796096@gmail.com", "[approved-public-support-contact]"
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


def test_candidate_wrappers_and_read_only_inspector_are_described_truthfully() -> None:
    normalized = _normalized(_root_document("README.md"))

    assert (
        "`GOOGLE_CLOUD_PROJECT` | (empty) | Explicit target for the read-only "
        "Cloud Run inspector; never release authorization"
    ) in normalized
    assert (
        "Direct legacy deployment paths are retired"
    ) in normalized
    assert "`scripts/check_cloudrun.sh` is now a strict read-only inspector" in normalized
    for required in (
        "The compatibility wrappers remain operational",
        "delegate to `scripts/deploy_all_cloudrun.sh`",
        "submits one paired candidate-only Cloud Build",
        "clean exact `main`/`origin/main` state",
        "approved WIF or otherwise valid `gcloud` authentication",
        "This is an external candidate deployment",
        "changes no production traffic",
        "prints a bounded runtime shape summary",
        "container count, timeout, and concurrency",
        "traffic and service identity summary",
        "never prints environment values, secret references, tokens, or credential/provider details",
    ):
        assert required in normalized
    for forbidden in (
        "`scripts/deploy_*.sh` fail closed",
        "`scripts/deploy_all_cloudrun.sh` fails closed",
        "compatibility wrappers are retired",
        "cannot deploy, change traffic, inspect logs, print configuration values",
    ):
        assert forbidden not in normalized


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
        "Local mock mode needs no Google or Firebase credentials",
        "bounded process-local",
        "does not persist uploaded images or account history",
        "operational logs",
        "Direct legacy deployment paths are retired",
        "default dry-run behavior",
        "0% production traffic",
    ):
        assert required in normalized


def test_app_store_drafts_publish_the_approved_identity_and_privacy_contract() -> None:
    expected_files = (
        "privacy-policy.md",
        "app-description-ja.md",
        "app-privacy-label-draft.md",
        "app-review-notes.md",
        "screenshot-plan.md",
    )
    for name in expected_files:
        assert (APP_STORE_DOCS / name).is_file(), name

    combined = "\n".join(
        (APP_STORE_DOCS / name).read_text(encoding="utf-8")
        for name in expected_files
    )
    for required in (
        "実家あんしんチェック",
        "zhanglonglong",
        "zll6796096@gmail.com",
        "写真1枚",
        "Google LLC",
        "Gemini",
        "Firebase App Check",
        "Apple App Attest",
        "有料サービス",
        "製品改善",
        "限定期間",
        "EXIF",
        "Cloud Logging",
        "30日",
        "医療",
        "介護",
        "保険",
        "法令適合",
        "正確な寸法",
        "施工",
    ):
        assert required in combined

    description = (APP_STORE_DOCS / "app-description-ja.md").read_text(
        encoding="utf-8"
    )
    assert description.startswith(
        "離れて暮らす親の家で気になる場所を、写真1枚から確認するためのアプリです。\n"
        "写真に写っている範囲の、転倒・つまずき・滑りにつながる可能性がある箇所を赤枠で示し、次にできることを3つの相談先に分けて整理します。"
    )
    for forbidden in (
        "AI診断",
        "予防を保証",
        "安全な家",
        "精度99%",
        "POC版",
    ):
        assert forbidden not in combined

    review_notes = (APP_STORE_DOCS / "app-review-notes.md").read_text(
        encoding="utf-8"
    )
    for exact_button_label in (
        "カメラで撮る",
        "写真を1枚選ぶ",
        "同意して写真を送る",
        "安全のためにできること",
    ):
        assert f"「{exact_button_label}」" in review_notes
    for stale_button_label in (
        "カメラで撮影",
        "写真から選ぶ",
        "同意して解析する",
    ):
        assert f"「{stale_button_label}」" not in review_notes


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


def test_cloudrun_checker_has_a_strict_read_only_command_and_endpoint_allowlist() -> None:
    checker = _root_document("scripts/check_cloudrun.sh")

    for variable in (
        "GOOGLE_CLOUD_PROJECT",
        "SUMAI_REGION",
        "SUMAI_AGENT_SERVICE",
        "SUMAI_WEB_SERVICE",
    ):
        assert variable in checker
        assert f"{variable} is required" in checker

    for forbidden_default in (
        "SUMAI_REGION:-asia-northeast1",
        "SUMAI_AGENT_SERVICE:-sumai-agent",
        "SUMAI_WEB_SERVICE:-sumai-web",
    ):
        assert forbidden_default not in checker

    gcloud_lines = [
        line.strip()
        for line in checker.splitlines()
        if re.search(r"(?:^|\s)gcloud\s", line)
    ]
    assert gcloud_lines
    assert all("gcloud run services describe" in line for line in gcloud_lines)

    for route in ("/health", "/ready", "/privacy", "/support"):
        assert route in checker
    for forbidden in (
        "/status",
        "/healthz",
        "/analyze",
        "run deploy",
        "run services update",
        "update-traffic",
        "run revisions",
        "gcloud logging",
        "gcloud secrets",
        "print-access-token",
        "--request POST",
        "--data",
        "secretKeyRef",
        "GEMINI_API_KEY",
    ):
        assert forbidden not in checker

    assert "--request GET" in checker
    assert "curl \\\n    --disable \\" in checker
    assert "--proto '=https'" in checker
    assert "--max-redirs 0" in checker
    for forbidden_curl_option in (
        "--location",
        "--location-trusted",
        "--user",
        "--oauth2-bearer",
        "--header",
    ):
        assert forbidden_curl_option not in checker
    assert "chmod 700" in checker
    assert "chmod 600" in checker
    assert "service_account_sha256" in checker
    assert "service_accounts_equal" in checker
    assert "env" not in " ".join(
        line.strip().casefold()
        for line in checker.splitlines()
        if line.strip().startswith("printf")
    )


def _write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_cloudrun_commands(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    call_log = tmp_path / "calls.jsonl"
    call_log.touch()

    _write_executable(
        bin_dir / "gcloud",
        r'''
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from pathlib import Path

        args = sys.argv[1:]
        with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool": "gcloud", "args": args}) + "\n")
        if len(args) < 5 or args[:3] != ["run", "services", "describe"]:
            print("forbidden gcloud command", file=sys.stderr)
            raise SystemExit(90)
        service = args[3]
        if service not in {"sumai-agent", "sumai-web"}:
            print("unexpected service", file=sys.stderr)
            raise SystemExit(91)
        if os.environ.get("FAKE_GCLOUD_FAIL_SERVICE") == service:
            print("private control plane detail", file=sys.stderr)
            raise SystemExit(1)
        component = "agent" if service == "sumai-agent" else "web"
        account = f"{component}-runtime" + chr(64) + "example-project.iam.gserviceaccount.com"
        payload = {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": service,
                "resourceVersion": "12345",
                "labels": {"source-commit": "f" * 40},
            },
            "spec": {
                "template": {
                    "spec": {
                        "serviceAccountName": account,
                        "timeoutSeconds": 120,
                        "containerConcurrency": 80,
                        "containers": [{
                            "image": "registry.invalid/private@sha256:" + "a" * 64,
                            "env": [{
                                "name": "GEMINI_API_KEY",
                                "valueFrom": {"secretKeyRef": {"name": "do-not-print", "key": "9"}},
                            }],
                        }],
                    }
                },
                "traffic": [
                    {"revisionName": f"{service}-r1", "percent": 100},
                    {"revisionName": f"{service}-candidate", "tag": "candidate-safe", "percent": 0},
                ],
            },
            "status": {
                "url": "https:" + f"//{service}-safe-hash-an.a" + ".run" + ".app",
                "latestCreatedRevisionName": f"{service}-candidate",
                "latestReadyRevisionName": f"{service}-candidate",
                "traffic": [
                    {"revisionName": f"{service}-r1", "percent": 100},
                    {
                        "revisionName": f"{service}-candidate",
                        "tag": "candidate-safe",
                        "percent": 0,
                        "url": "https:" + f"//candidate-safe---{service}-safe-hash-an.a" + ".run" + ".app",
                    },
                ],
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }
        print(json.dumps(payload))
        ''',
    )
    _write_executable(
        bin_dir / "curl",
        r'''
        #!/usr/bin/env python3
        import json
        import os
        import stat
        import sys
        from pathlib import Path
        from urllib.parse import urlsplit

        args = sys.argv[1:]
        curl_home = Path(os.environ.get("CURL_HOME", ""))
        if args[:1] != ["--disable"] and (curl_home / ".curlrc").is_file():
            print("malicious curl configuration was applied", file=sys.stderr)
            raise SystemExit(93)
        def option(name):
            index = args.index(name)
            return args[index + 1]

        output_path = Path(option("--output"))
        header_path = Path(option("--dump-header"))
        url = args[-1]
        parsed = urlsplit(url)
        path = parsed.path or "/"
        hostname = parsed.hostname or ""
        record = {
            "tool": "curl",
            "args": args,
            "url": url,
            "output_mode": oct(stat.S_IMODE(output_path.stat().st_mode)),
            "header_mode": oct(stat.S_IMODE(header_path.stat().st_mode)),
            "directory_mode": oct(stat.S_IMODE(output_path.parent.stat().st_mode)),
        }
        with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        if os.environ.get("FAKE_CURL_FAIL_PATH") == path:
            output_path.write_text("private service response", encoding="utf-8")
            print("private network detail", file=sys.stderr)
            raise SystemExit(22)
        if path == "/health":
            body = '{"status":"ok","version":"test"}'
            content_type = "application/json"
        elif path == "/ready" and hostname.startswith("sumai-agent-"):
            body = '{"status":"ready","version":"test"}'
            content_type = "application/json"
        elif path == "/ready" and hostname.startswith("sumai-web-"):
            body = '{"status":"ok","version":"test"}'
            content_type = "application/json"
        elif path in {"/", "/privacy", "/support"}:
            body = "<html lang=ja>safe</html>"
            content_type = "text/html; charset=utf-8"
        else:
            print("forbidden endpoint", file=sys.stderr)
            raise SystemExit(92)
        cache = "Cache-Control: no-store\r\n" if path in {"/privacy", "/support"} else ""
        output_path.write_text(body, encoding="utf-8")
        header_path.write_text(
            "HTTP/1.1 200 OK\r\n" + f"Content-Type: {content_type}\r\n" + cache + "\r\n",
            encoding="iso-8859-1",
        )
        print("200", end="")
        ''',
    )
    return bin_dir, call_log


def _run_cloudrun_checker(
    tmp_path: Path,
    overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    bin_dir, call_log = _fake_cloudrun_commands(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "FAKE_CALL_LOG": str(call_log),
            "GOOGLE_CLOUD_PROJECT": "safe-project-123",
            "SUMAI_REGION": "asia-northeast1",
            "SUMAI_AGENT_SERVICE": "sumai-agent",
            "SUMAI_WEB_SERVICE": "sumai-web",
        }
    )
    environment.update(overrides or {})
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/check_cloudrun.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    return result, calls


def test_cloudrun_checker_runtime_reports_only_sanitized_read_only_evidence(
    tmp_path: Path,
) -> None:
    result, calls = _run_cloudrun_checker(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "inspection_result=PASS" in result.stdout
    assert "service_accounts_equal=false" in result.stdout
    assert result.stdout.count("service_account_sha256=") == 2
    assert "traffic=sumai-agent-r1:100,candidate-safe@sumai-agent-candidate:0" in result.stdout
    assert "traffic=sumai-web-r1:100,candidate-safe@sumai-web-candidate:0" in result.stdout
    assert "config_summary=containers:1,timeout_seconds:120,container_concurrency:80" in result.stdout
    for forbidden in (
        "@example-project.iam.gserviceaccount.com",
        "do-not-print",
        "GEMINI_API_KEY",
        "secretKeyRef",
        "private@sha256",
    ):
        assert forbidden not in result.stdout + result.stderr

    gcloud_calls = [call for call in calls if call["tool"] == "gcloud"]
    curl_calls = [call for call in calls if call["tool"] == "curl"]
    assert len(gcloud_calls) == 2
    assert all(call["args"][:3] == ["run", "services", "describe"] for call in gcloud_calls)
    assert {call["url"].rsplit(".run.app", 1)[1] for call in curl_calls} == {
        "/health",
        "/ready",
        "/",
        "/privacy",
        "/support",
    }
    assert all("--request" in call["args"] for call in curl_calls)
    assert all(call["args"][call["args"].index("--request") + 1] == "GET" for call in curl_calls)
    assert all(call["args"][0] == "--disable" for call in curl_calls)
    assert all(call["args"][call["args"].index("--proto") + 1] == "=https" for call in curl_calls)
    assert all(call["args"][call["args"].index("--max-redirs") + 1] == "0" for call in curl_calls)
    assert all("--location" not in call["args"] for call in curl_calls)
    assert all("--location-trusted" not in call["args"] for call in curl_calls)
    assert all("--header" not in call["args"] for call in curl_calls)
    assert all(call["directory_mode"] == "0o700" for call in curl_calls)
    assert all(call["output_mode"] == "0o600" for call in curl_calls)
    assert all(call["header_mode"] == "0o600" for call in curl_calls)


def test_cloudrun_checker_fails_closed_without_leaking_private_probe_details(
    tmp_path: Path,
) -> None:
    result, calls = _run_cloudrun_checker(
        tmp_path,
        {"FAKE_CURL_FAIL_PATH": "/health"},
    )

    assert result.returncode != 0
    assert "inspection_result=FAILED_SAFE" in result.stderr
    assert "service=sumai-agent endpoint=/health reason=UNREACHABLE_OR_NON_200" in result.stderr
    assert "private network detail" not in result.stderr
    assert "private service response" not in result.stdout + result.stderr
    assert all(call["tool"] in {"gcloud", "curl"} for call in calls)


def test_cloudrun_checker_ignores_a_malicious_curlrc_before_safe_fake_probes(
    tmp_path: Path,
) -> None:
    curl_home = tmp_path / "malicious-curl-home"
    curl_home.mkdir()
    (curl_home / ".curlrc").write_text(
        'request = "POST"\nlocation\nheader = "X-Unsafe: from-curlrc"\n',
        encoding="utf-8",
    )

    result, calls = _run_cloudrun_checker(
        tmp_path / "run",
        {"CURL_HOME": str(curl_home), "HOME": str(curl_home)},
    )

    assert result.returncode == 0, result.stderr
    curl_calls = [call for call in calls if call["tool"] == "curl"]
    assert curl_calls
    assert all(call["args"][0] == "--disable" for call in curl_calls)


def test_cloudrun_checker_uses_the_real_web_readiness_contract() -> None:
    module = load_web_module()
    response = TestClient(module.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    checker = _root_document("scripts/check_cloudrun.sh")
    assert 'probe_endpoint "${agent_service}" "${agent_url}" /ready json ready false' in checker
    assert 'probe_endpoint "${web_service}" "${web_url}" /ready json ok false' in checker


def test_cloudrun_checker_rejects_each_missing_target_before_commands(
    tmp_path: Path,
) -> None:
    for variable in (
        "GOOGLE_CLOUD_PROJECT",
        "SUMAI_REGION",
        "SUMAI_AGENT_SERVICE",
        "SUMAI_WEB_SERVICE",
    ):
        missing, missing_calls = _run_cloudrun_checker(
            tmp_path / f"missing-{variable.casefold()}",
            {variable: ""},
        )
        assert missing.returncode != 0, variable
        assert f"{variable} is required" in missing.stderr
        assert missing_calls == [], variable


def test_cloudrun_checker_rejects_each_unsafe_target_before_commands(
    tmp_path: Path,
) -> None:
    unsafe_targets = {
        "GOOGLE_CLOUD_PROJECT": "UPPER_project",
        "SUMAI_REGION": "asia-northeast1;update",
        "SUMAI_AGENT_SERVICE": "sumai-agent;update",
        "SUMAI_WEB_SERVICE": "sumai/web",
    }
    for variable, value in unsafe_targets.items():
        invalid, invalid_calls = _run_cloudrun_checker(
            tmp_path / f"invalid-{variable.casefold()}",
            {variable: value},
        )
        assert invalid.returncode != 0, variable
        assert "cloud_run_target=INVALID" in invalid.stderr
        assert invalid_calls == [], variable


def test_release_docs_define_candidate_only_and_independent_promotion_gates() -> None:
    readme = _root_document("README.md")
    architecture = _document("architecture.md")
    deployment = _document("cloudrun_deployment.md")
    combined = _normalized("\n".join((readme, architecture, deployment)))
    combined_lowered = combined.casefold()

    for required in (
        "candidate-only",
        "immutable digest",
        "0% production traffic",
        "App Check before reading the multipart body",
        "REQUIRE_REAL_GEMINI=true",
        "PUBLIC_WEB_ANALYSIS_ENABLED=false",
        "local mock mode remains available",
        "separate promotion checkpoint",
        "default dry-run",
        "real-device App Attest evidence",
        "dual confirmation",
        "Cloud Run Admin API",
        "resourceVersion",
        "ownership-aware rollback",
        "direct legacy deployment paths are retired",
    ):
        assert required.casefold() in combined_lowered

    for gate in (
        "source",
        "CI",
        "candidate",
        "device",
        "promotion",
        "archive",
        "review",
        "release",
        "storefront",
    ):
        assert gate in combined
    for forbidden_claim in (
        "candidate is deployed",
        "production is verified",
        "app store release is complete",
    ):
        assert forbidden_claim not in combined_lowered


def test_cloudrun_inspector_usage_requires_all_explicit_targets_and_wrappers_stay_operational() -> None:
    deployment = _normalized(_document("cloudrun_deployment.md"))

    assert (
        "GOOGLE_CLOUD_PROJECT=owner-approved-project "
        "SUMAI_REGION=owner-approved-region "
        "SUMAI_AGENT_SERVICE=owner-approved-agent-service "
        "SUMAI_WEB_SERVICE=owner-approved-web-service "
        "./scripts/check_cloudrun.sh"
    ) in deployment
    for required in (
        "All four inspection targets are mandatory",
        "compatibility wrappers remain operational",
        "delegate to `scripts/deploy_all_cloudrun.sh`",
        "paired candidate-only Cloud Build",
        "clean exact `main` and `origin/main`",
        "approved WIF or otherwise valid `gcloud` authentication",
        "external candidate deployment",
        "does not change production traffic",
    ):
        assert required in deployment
    for forbidden in (
        "`scripts/deploy_sumai_agent.sh`, `scripts/deploy_sumai_web.sh`, and `scripts/deploy_all_cloudrun.sh` fail closed",
        "must not be revived",
    ):
        assert forbidden not in deployment


def test_architecture_and_readme_describe_the_actual_memoized_report_boundary() -> None:
    combined = _normalized(
        _root_document("README.md") + "\n" + _document("architecture.md")
    )
    lowered = combined.casefold()

    for required in (
        "generated report/advice text is cached and reused on a memo hit",
        "annotated and improvement images are rendered for every request",
        "PDF bytes are generated on demand and are not persisted or cached",
        "TTL",
        "maximum item count",
        "process-local",
        "not persistent",
        "not shared across worker processes",
    ):
        assert required.casefold() in lowered
    for forbidden in (
        "per-request render and report",
        "report text is generated for every request",
        "reports are generated per request",
    ):
        assert forbidden not in lowered


def test_release_gate_records_current_app_store_truth_and_future_boundaries() -> None:
    release_gate = _document("release/sumaiguard-v1.0-app-store-release-gate.md")
    normalized = _normalized(release_gate)

    expected_rows = {
        "Local source and listing assets": "PASS",
        "Local verification": "PASS",
        "App Store Connect record": "PASS",
        "Apple capability and profile": "IN PROGRESS",
        "Source push": "NOT STARTED",
        "Exact-head CI": "NOT STARTED",
        "Cloud Build candidate": "NOT STARTED",
        "Real-device App Attest": "NOT STARTED",
        "Production promotion": "AWAITING CHECKPOINT",
        "Archive and signing": "NOT STARTED",
        "IPA upload and processing": "AWAITING CHECKPOINT",
        "Metadata and privacy answers": "IN PROGRESS",
        "App Review submission": "AWAITING CHECKPOINT",
        "App Review approval": "NOT STARTED",
        "Manual release": "AWAITING CHECKPOINT",
        "Japan storefront visibility": "NOT STARTED",
    }
    for gate, status_value in expected_rows.items():
        assert re.search(
            rf"\|\s*{re.escape(gate)}\s*\|\s*{re.escape(status_value)}\s*\|",
            release_gate,
        )

    for required in (
        "2026-08-10 JST",
        "codex/sumaiguard-app-store-release",
        "de37d0b821ea4be0d8df497b575bf9309b15d997",
        "実家あんしんチェック",
        "com.zll.sumaiguard",
        "SUMAIGUARD-IOS-1",
        "version 1.0 is in `提出準備中`",
        "App Attest enabled",
        "No SumaiGuard App Store provisioning profile",
        "current production remains on the predecessor revisions",
        "defaults to automatic release",
        "change it to manual before submission",
        "separate explicit confirmation",
        "Storefront visibility is verified separately",
    ):
        assert required.casefold() in normalized.casefold()

    for forbidden in (
        "final implementation commit has not yet been created",
        "No final Task 6 SHA exists at snapshot time",
        "next action is to create and review the exact Task 6 commit",
    ):
        assert forbidden not in release_gate

    assert "TBD" not in release_gate.upper()
    assert "TODO" not in release_gate.upper()
    assert not re.search(r"https?://", release_gate)
    assert not re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", release_gate, re.I)
    allowed_statuses = {
        "NOT STARTED",
        "IN PROGRESS",
        "AWAITING CHECKPOINT",
        "BLOCKED",
        "SKIPPED",
        "PASS",
    }
    statuses = re.findall(r"^\|\s*[^|]+\|\s*([^|]+?)\s*\|", release_gate, re.M)
    statuses = [
        status_value.strip()
        for status_value in statuses
        if status_value.strip() != "Status"
        and set(status_value.strip()) != {"-"}
    ]
    assert statuses
    assert set(statuses).issubset(allowed_statuses)
