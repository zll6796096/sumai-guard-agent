from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from fastapi.testclient import TestClient


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"


def _home_html() -> str:
    spec = importlib.util.spec_from_file_location("sumai_web_ui_contract", WEB_APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = TestClient(module.app).get("/")
    assert response.status_code == 200
    return response.text


def test_copy_keeps_the_product_safety_first() -> None:
    html = _home_html()
    assert "写真1枚で、親の家を安全チェック" in html
    assert "安全チェック結果" in html
    assert "次にできること" in html
    assert "診断結果" not in html
    assert "点検・修繕提案" not in html


def test_viewport_keeps_browser_zoom_available() -> None:
    html = _home_html()
    viewport = re.search(r'<meta name="viewport" content="([^"]+)">', html)
    assert viewport
    assert "maximum-scale" not in viewport.group(1)
    assert "user-scalable=no" not in viewport.group(1)


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
    spec = importlib.util.spec_from_file_location("sumai_web_readiness_contract", WEB_APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    response = TestClient(module.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
