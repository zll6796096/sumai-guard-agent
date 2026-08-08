from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.formparsers import MultiPartParser

from apps.sumai_agent.tests.web_module_loader import load_web_module as _load_web_module


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"
WEB_DOCKERFILE_PATH = WEB_APP_PATH.parent / "Dockerfile"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _home_html() -> str:
    module = _load_web_module()
    response = TestClient(module.app).get("/")
    assert response.status_code == 200
    return response.text


def _image_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _call_analyze_without_receiving_body(
    app,
    monkeypatch,
    *,
    root_path: str = "",
    path: str = "/analyze",
) -> tuple[list[dict[str, object]], int, int]:
    receive_calls = 0
    multipart_parse_calls = 0
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal receive_calls
        receive_calls += 1
        raise AssertionError("disabled public analysis must not read the ASGI body")

    async def fail_multipart_parse(_parser) -> object:
        nonlocal multipart_parse_calls
        multipart_parse_calls += 1
        raise AssertionError("disabled public analysis must not parse multipart data")

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    monkeypatch.setattr(MultiPartParser, "parse", fail_multipart_parse)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": root_path,
        "headers": [
            (b"host", b"example.invalid"),
            (b"content-type", b"multipart/form-data; boundary=malformed"),
            (b"content-length", b"999999999999"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("example.invalid", 443),
    }
    asyncio.run(app(scope, receive, send))
    return messages, receive_calls, multipart_parse_calls


def test_copy_keeps_the_product_safety_first() -> None:
    html = _home_html()
    assert "写真1枚で、親の家を安全チェック" in html
    assert "安全チェック結果" in html
    assert "安全のための対策を見る" in html
    assert "安全のためにできること" in html
    assert "次にできることを見る" not in html
    assert "診断結果" not in html
    assert "点検・修繕提案" not in html


def test_pdf_download_control_is_accessible_and_text_only() -> None:
    html = _home_html()
    assert 'id="btn-download-pdf"' in html
    assert "この内容をPDFで保存" in html
    assert 'id="pdf-download-error"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert "latestReportPayload" in html
    assert "family_actions_markdown: payload.family_actions_markdown" in html
    assert "care_manager_actions_markdown: payload.care_manager_actions_markdown" in html
    assert "contractor_actions_markdown: payload.contractor_actions_markdown" in html
    assert "risk_summary_markdown: payload.risk_summary_markdown" in html
    assert "annotated_image_base64:" not in html
    assert "improvement_image_base64:" not in html
    assert "fetch('/suggestions.pdf'" in html


def test_viewport_keeps_browser_zoom_available() -> None:
    html = _home_html()
    viewport = re.search(r'<meta name="viewport" content="([^"]+)">', html)
    assert viewport
    assert "maximum-scale" not in viewport.group(1)
    assert "user-scalable=no" not in viewport.group(1)


def test_home_declares_an_inline_favicon_without_an_extra_request() -> None:
    html = _home_html()
    assert '<link rel="icon" href="data:,">' in html


def test_repository_root_frontend_import_gate_runs_without_pythonpath_changes() -> None:
    command = """
import importlib.util
from pathlib import Path

path = Path('apps/sumai_web/app.py')
spec = importlib.util.spec_from_file_location('sumai_web_app', path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
print('frontend import ok')
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "frontend import ok"


def test_accordion_headers_are_native_accessible_buttons() -> None:
    html = _home_html()
    assert html.count('class="accordion-card-header"') == 4
    assert html.count('aria-controls="accordion-') == 4
    assert 'aria-expanded="true"' in html
    assert html.count('aria-expanded="false"') == 3
    assert "header.setAttribute('aria-expanded', String(willOpen))" in html
    assert "content.hidden = !willOpen" in html


def test_ui_preserves_required_safety_content() -> None:
    html = _home_html()
    for text in (
        "家族で今日できること",
        "ケアマネ・福祉用具に相談",
        "専門施工・現地確認",
        "現在の注意箇所",
        "対策イメージ（施工図ではありません）",
        "写真は保存しません",
        "見える範囲のみ確認します",
    ):
        assert text in html


def test_interactive_controls_have_accessible_target_sizes() -> None:
    html = _home_html()
    assert "--control-min-height: 44px;" in html
    assert "min-height: var(--control-min-height);" in html
    assert ":focus-visible" in html


def test_action_cards_hide_redundant_report_scaffolding() -> None:
    html = _home_html()
    assert ".action-report > h2" in html
    assert ".action-report > ul > li:nth-child(-n + 2)" in html


def test_web_readiness_endpoint_avoids_cloud_run_reserved_z_suffix() -> None:
    module = _load_web_module()

    response = TestClient(module.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_pages_are_japanese_semantic_responsive_and_not_cached() -> None:
    module = _load_web_module()
    client = TestClient(module.app)

    for path, title in (("/privacy", "プライバシー"), ("/support", "サポート")):
        response = client.get(path)
        html = response.text
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"].startswith("text/html")
        assert '<html lang="ja">' in html
        assert '<meta name="viewport"' in html
        assert "maximum-scale" not in html
        assert "user-scalable=no" not in html
        assert "<main" in html
        assert "<h1" in html
        assert title in html
        assert 'href="/"' in html
        assert "min-height: 44px" in html
        assert ":focus-visible" in html
        assert "<script" not in html
        assert "https://" not in html
        assert "http://" not in html


def test_privacy_page_states_consent_minimization_and_product_boundary() -> None:
    module = _load_web_module()
    html = TestClient(module.app).get("/privacy").text

    for disclosure in (
        "画像を送信するたびに、送信前に同意を確認します",
        "住まいの内部や私物など、私的・機微な内容",
        "EXIF（撮影日時や位置情報など）を削除",
        "写真とPDFは、SumaiGuardアプリによって永続的に保存されません",
        "構造化された解析結果の意味情報",
        "設定されたTTLの範囲で、プロセス内メモリに短時間保持",
        "画像は含まれません",
        "データベース、アカウント、利用履歴として保存しません",
        "プロセスの再起動やワーカー境界を越えて保持されません",
        "ユーザー向けまたはアカウントに紐づく利用履歴はありません",
        "トラッキング、広告、プロファイリングは行いません",
        "アップロード開始前にキャンセル",
        "拒否または同意の撤回",
        "サポート・削除に関する問い合わせ",
        "医療・介護認定・保険・施工",
    ):
        assert disclosure in html
    assert "写真、解析結果、PDF、利用履歴を保存しません" not in html
    assert "写真・結果・PDFを保存しません" not in html


def test_privacy_page_names_confirmed_processors_and_separates_logging() -> None:
    module = _load_web_module()
    html = TestClient(module.app).get("/privacy").text

    for provider in (
        "Google LLC",
        "Gemini",
        "Firebase App Check",
        "Apple's App Attest",
        "Google Cloud Run",
        "Cloud Logging",
    ):
        assert provider in html
    assert "第三者サービスによる一時的な処理" in html
    assert "運用上のリクエストメタデータ" in html
    assert "ユーザーアカウントに結び付けられません" in html
    assert "写真そのものや構造化された解析結果とは区別" in html
    assert "最終的に観測された保存期間" in html
    assert "Phase 3の公開判定項目" in html
    assert not re.search(r"Cloud Logging.{0,120}\d+\s*(?:日|か月|ヶ月|年)", html)


def test_support_page_has_no_account_upload_and_safe_retry_guidance() -> None:
    module = _load_web_module()
    html = TestClient(module.app).get("/support").text

    for guidance in (
        "アカウントなしで利用できます",
        "JPEGまたはPNG",
        "10 MiB以下",
        "時間をおいて再試行",
        "送信前にキャンセル",
        "医療・介護認定・保険・施工",
    ):
        assert guidance in html
    assert 'href="/privacy"' in html


def test_public_pages_do_not_invent_contact_identity_or_service_promises() -> None:
    module = _load_web_module()
    client = TestClient(module.app)
    combined_html = client.get("/privacy").text + client.get("/support").text

    assert "本Phase 1のソースには、公開済みのサポート用メールアドレス" in combined_html
    assert "確認済みの運営者連絡先が提供されるまで公開できません" in combined_html
    assert "mailto:" not in combined_html
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", combined_html)
    assert "24時間以内" not in combined_html
    assert "必ず返信" not in combined_html


def test_web_container_copies_static_public_page_module() -> None:
    dockerfile = WEB_DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "COPY public_pages.py ./public_pages.py" in dockerfile


def test_home_uses_only_safe_builtin_report_rendering_and_strict_csp() -> None:
    module = _load_web_module()
    response = TestClient(module.app).get("/")
    html = response.text

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    csp = response.headers["content-security-policy"]
    for directive in (
        "default-src 'self'",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "object-src 'none'",
        "base-uri 'none'",
    ):
        assert directive in csp
    assert "https:" not in csp
    assert "cdn.jsdelivr" not in html
    assert "marked" not in html.lower()
    assert ".innerHTML" not in html
    assert "function renderSafeMarkdown(target, markdown)" in html
    assert "document.createElement('h2')" in html
    assert "document.createElement('h3')" in html
    assert "document.createElement('ul')" in html
    assert "document.createElement('li')" in html
    assert "document.createElement('p')" in html
    assert "node.textContent = content" in html
    assert "target.replaceChildren(fragment)" in html
    malicious_reports = (
        '<img src=x onerror="alert(1)">',
        '<script>globalThis.compromised = true</script>',
    )
    assert all("<" in report and ">" in report for report in malicious_reports)
    assert "DOMParser" not in html
    assert "insertAdjacentHTML" not in html


def test_production_disabled_gate_rejects_before_body_or_multipart_read(monkeypatch) -> None:
    module = _load_web_module(
        {
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
        }
    )
    backend_post = AsyncMock()
    module._backend_client = SimpleNamespace(post=backend_post)

    messages, receive_calls, multipart_parse_calls = _call_analyze_without_receiving_body(
        module.app,
        monkeypatch,
    )

    assert module.PUBLIC_WEB_ANALYSIS_ENABLED is False
    assert receive_calls == 0
    assert multipart_parse_calls == 0
    backend_post.assert_not_awaited()
    assert messages[0]["status"] == 503
    headers = dict(messages[0]["headers"])
    assert headers[b"cache-control"] == b"no-store"
    assert messages[1]["body"].decode("utf-8") == (
        '{"error":"NATIVE_APP_REQUIRED","message":'
        '"公開版の写真解析はiPhoneアプリからご利用ください。"}'
    )


@pytest.mark.parametrize(
    ("root_path", "path"),
    (("/prefix", "/prefix/analyze"), ("/prefix", "/analyze")),
)
def test_production_gate_normalizes_root_path_before_any_body_read(
    monkeypatch,
    root_path: str,
    path: str,
) -> None:
    module = _load_web_module(
        {
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
        }
    )
    backend_post = AsyncMock()
    module._backend_client = SimpleNamespace(post=backend_post)

    messages, receive_calls, multipart_parse_calls = _call_analyze_without_receiving_body(
        module.app,
        monkeypatch,
        root_path=root_path,
        path=path,
    )

    assert receive_calls == 0
    assert multipart_parse_calls == 0
    backend_post.assert_not_awaited()
    assert messages[0]["status"] == 503
    assert dict(messages[0]["headers"])[b"cache-control"] == b"no-store"
    assert messages[1]["body"].decode("utf-8") == (
        '{"error":"NATIVE_APP_REQUIRED","message":'
        '"公開版の写真解析はiPhoneアプリからご利用ください。"}'
    )


def test_invalid_explicit_public_analysis_flag_fails_closed(monkeypatch) -> None:
    module = _load_web_module(
        {
            "MOCK_MODE": "true",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "unexpected-value",
        }
    )

    messages, receive_calls, multipart_parse_calls = _call_analyze_without_receiving_body(
        module.app,
        monkeypatch,
    )

    assert module.PUBLIC_WEB_ANALYSIS_ENABLED is False
    assert receive_calls == 0
    assert multipart_parse_calls == 0
    assert messages[0]["status"] == 503


def test_local_mock_defaults_to_enabled_and_proxies_only_to_native_api() -> None:
    module = _load_web_module({"MOCK_MODE": "true"})
    backend_response = SimpleNamespace(status_code=200, json=lambda: {"mode": "local_mock"})
    backend_post = AsyncMock(return_value=backend_response)
    module._backend_client = SimpleNamespace(post=backend_post, aclose=AsyncMock())

    with TestClient(module.app) as client:
        response = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
            data={"room_hint": "hallway"},
        )

    assert module.FRONTEND_MOCK is True
    assert module.FRONTEND_REQUIRE_REAL_GEMINI is False
    assert module.PUBLIC_WEB_ANALYSIS_ENABLED is True
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"mode": "local_mock"}
    backend_post.assert_awaited_once()
    upstream_url, = backend_post.await_args.args
    assert upstream_url == f"{module.SUMAI_AGENT_URL}/api/v1/analyze"
    assert "headers" not in backend_post.await_args.kwargs
    assert "X-Firebase-AppCheck" not in backend_post.await_args.kwargs["data"]


def test_enabled_analyze_adds_no_store_to_upstream_error_and_validation() -> None:
    module = _load_web_module({"MOCK_MODE": "true"})
    backend_response = SimpleNamespace(status_code=409, json=lambda: {})
    module._backend_client = SimpleNamespace(
        post=AsyncMock(return_value=backend_response),
        aclose=AsyncMock(),
    )

    with TestClient(module.app) as client:
        upstream_error = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )
        validation_error = client.post("/analyze", data={"room_hint": "auto"})

    assert upstream_error.status_code == 409
    assert upstream_error.headers["cache-control"] == "no-store"
    assert validation_error.status_code == 422
    assert validation_error.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "failure_source",
    ("multipart", "route", "backend", "response_construction"),
)
def test_enabled_analyze_unexpected_pre_response_failure_is_safe_and_not_cached(
    monkeypatch,
    caplog,
    failure_source: str,
) -> None:
    module = _load_web_module({"MOCK_MODE": "true"})
    sentinel = f"SENTINEL_{failure_source.upper()}_DETAIL"

    if failure_source == "multipart":
        async def fail_multipart(_parser):
            raise RuntimeError(sentinel)

        monkeypatch.setattr(MultiPartParser, "parse", fail_multipart)

        async def multipart_failure(_scope, _receive, _send) -> None:
            await MultiPartParser.parse(object())

        messages: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        middleware = module.PublicWebAnalysisGateMiddleware(
            multipart_failure,
            analysis_enabled=True,
        )
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/analyze",
            "root_path": "",
        }
        caplog.set_level(logging.ERROR, logger="sumai.web")
        asyncio.run(middleware(scope, receive, send))
        start = next(
            message
            for message in messages
            if message["type"] == "http.response.start"
        )
        response_status = start["status"]
        response_headers = dict(start["headers"])
        response_text = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        ).decode("utf-8")
        response_json = json.loads(response_text)
    else:
        if failure_source == "route":
            async def fail_route(**_values):
                raise RuntimeError(sentinel)

            analyze_route = next(
                route
                for route in module.app.routes
                if getattr(route, "path", None) == "/analyze"
            )
            monkeypatch.setattr(analyze_route.dependant, "call", fail_route)
        elif failure_source == "backend":
            module._backend_client = SimpleNamespace(
                post=AsyncMock(side_effect=RuntimeError(sentinel)),
                aclose=AsyncMock(),
            )
        else:
            backend_response = SimpleNamespace(status_code=409, json=lambda: {})
            module._backend_client = SimpleNamespace(
                post=AsyncMock(return_value=backend_response),
                aclose=AsyncMock(),
            )

            def fail_response_construction(_status_code: int):
                raise RuntimeError(sentinel)

            monkeypatch.setattr(
                module,
                "_safe_backend_client_error",
                fail_response_construction,
            )

        caplog.set_level(logging.ERROR, logger="sumai.web")
        with TestClient(module.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/analyze",
                files={"image": ("room.png", _image_bytes(), "image/png")},
            )
        response_status = response.status_code
        response_headers = response.headers
        response_text = response.text
        response_json = response.json()

    assert response_status == 500
    if isinstance(response_headers, dict):
        assert response_headers[b"cache-control"] == b"no-store"
    else:
        assert response_headers["cache-control"] == "no-store"
    assert response_json == {
        "error": "ANALYSIS_FAILED",
        "message": "分析を完了できませんでした。時間をおいて、もう一度お試しください。",
    }
    assert sentinel not in response_text
    assert sentinel not in caplog.text
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "web_analysis_unexpected_failure"
    ]
    assert len(records) == 1
    assert records[0].args == ()
    assert records[0].exc_info is None
    assert records[0].failure_code == "ANALYSIS_FAILED"
    assert records[0].failure_type == "RuntimeError"


def test_enabled_analyze_does_not_send_second_response_after_start() -> None:
    module = _load_web_module({"MOCK_MODE": "true"})
    messages: list[dict[str, object]] = []

    async def started_then_failed(_scope, _receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        raise RuntimeError("SENTINEL_AFTER_RESPONSE_START")

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    middleware = module.PublicWebAnalysisGateMiddleware(
        started_then_failed,
        analysis_enabled=True,
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analyze",
        "root_path": "",
    }

    with pytest.raises(RuntimeError, match="SENTINEL_AFTER_RESPONSE_START"):
        asyncio.run(middleware(scope, receive, send))

    starts = [
        message
        for message in messages
        if message["type"] == "http.response.start"
    ]
    assert len(starts) == 1
    assert dict(starts[0]["headers"])[b"cache-control"] == b"no-store"


def test_each_web_load_has_isolated_environment_and_module_globals() -> None:
    production = _load_web_module(
        {
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "true",
        }
    )
    local = _load_web_module({"MOCK_MODE": "true"})

    assert production.__name__ != local.__name__
    assert production.FRONTEND_MOCK is False
    assert production.FRONTEND_REQUIRE_REAL_GEMINI is True
    assert production.PUBLIC_WEB_ANALYSIS_ENABLED is True
    assert local.FRONTEND_MOCK is True
    assert local.FRONTEND_REQUIRE_REAL_GEMINI is False
    assert local.PUBLIC_WEB_ANALYSIS_ENABLED is True


def test_web_loader_isolates_every_import_environment_and_leaks_no_modules(
    monkeypatch,
) -> None:
    hostile_environment = {
        "MOCK_MODE": "false",
        "REQUIRE_REAL_GEMINI": "true",
        "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
        "SUMAI_AGENT_TIMEOUT_SECONDS": "1",
        "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS": "2",
        "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS": "3",
        "ANALYSIS_TIMEOUT": "4",
        "SUMAI_AGENT_URL": "https://hostile.invalid/api",
        "SUMAI_WEB_PORT": "9999",
        "LOG_LEVEL": "DEBUG",
        "PYTHON_DOTENV_DISABLED": "0",
    }
    for name, value in hostile_environment.items():
        monkeypatch.setenv(name, value)
    sys.modules.pop("public_pages", None)

    module = _load_web_module()

    assert module.FRONTEND_MOCK is True
    assert module.FRONTEND_REQUIRE_REAL_GEMINI is False
    assert module.PUBLIC_WEB_ANALYSIS_ENABLED is True
    assert module.SUMAI_AGENT_TIMEOUT_SECONDS == 150.0
    assert module.SUMAI_AGENT_URL == "http://localhost:8080"
    assert module.SUMAI_WEB_PORT == 8081
    assert {name: os.environ.get(name) for name in hostile_environment} == hostile_environment
    assert module.__name__ not in sys.modules
    assert "public_pages" not in sys.modules
    assert not any(name.startswith("sumai_web_test_") for name in sys.modules)


def test_web_loader_disables_dotenv_during_module_execution(monkeypatch) -> None:
    import dotenv

    observed_values: list[str | None] = []
    real_load_dotenv = dotenv.load_dotenv

    def observe_dotenv_environment(*args, **kwargs):
        observed_values.append(os.environ.get("PYTHON_DOTENV_DISABLED"))
        return real_load_dotenv(*args, **kwargs)

    monkeypatch.setattr(dotenv, "load_dotenv", observe_dotenv_environment)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "0")

    _load_web_module()

    assert observed_values == ["1"]
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "0"
