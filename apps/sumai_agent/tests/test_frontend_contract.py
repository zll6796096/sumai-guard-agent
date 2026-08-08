from __future__ import annotations

import os

from apps.sumai_agent.tests.web_module_loader import load_web_module as _load_web_module


def _index_html() -> str:
    return _load_web_module().INDEX_HTML


def test_frontend_loader_ignores_hostile_outer_environment_and_restores_it(
    monkeypatch,
) -> None:
    hostile_environment = {
        "MOCK_MODE": "false",
        "REQUIRE_REAL_GEMINI": "true",
        "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
    }
    for name, value in hostile_environment.items():
        monkeypatch.setenv(name, value)

    module = _load_web_module()

    assert module.FRONTEND_MOCK is True
    assert module.FRONTEND_REQUIRE_REAL_GEMINI is False
    assert module.PUBLIC_WEB_ANALYSIS_ENABLED is True
    assert {name: os.environ.get(name) for name in hostile_environment} == hostile_environment


def test_completed_result_exposes_mode_provenance_without_debug_mode() -> None:
    html = _index_html()

    assert 'id="analysis-mode-banner"' in html
    assert "Gemini解析結果" in html
    assert "モック結果（AI実解析ではありません）" in html
    assert "ローカルモック結果（AI実解析ではありません）" in html
    assert "フォールバック結果（Gemini解析として扱わないでください）" in html
    assert "部分解析（補完に失敗したため安全判定として扱わないでください）" in html
    assert "実行モードを確認できません" in html
    assert "mode.startsWith('gemini_fallback(')" in html
    assert "mode.startsWith('gemini_partial(')" in html


def test_not_applicable_result_hides_risk_summary_images_and_suggestions() -> None:
    html = _index_html()

    assert "payload.is_not_applicable === true || payload.is_home_environment === false" in html
    assert "resultSummary.style.display = 'none'" in html
    assert "imagesList.style.display = 'none'" in html
    assert "btnShowSuggestions.style.display = 'none'" in html
    assert "resultSummary.style.display = 'flex'" in html
    assert "btnShowSuggestions.style.display = ''" in html
    assert "document.getElementById('screen2-title').textContent = \"安全チェック結果\"" in html


def test_waiting_experience_is_local_indeterminate_and_accessible() -> None:
    html = _index_html()

    assert 'id="waiting-progress-track"' in html
    assert 'class="waiting-progress-indicator"' in html
    assert 'role="progressbar"' in html
    assert 'aria-label="写真確認の進行状況"' in html
    assert "aria-valuenow" not in html
    assert "from { transform: translateX(-20%); }" in html
    assert "to { transform: translateX(138%); }" in html
    assert 'id="waiting-status-text"' in html
    assert 'id="waiting-tip-text"' in html
    assert 'id="waiting-long-note"' in html
    assert "startWaitingExperience" in html
    assert "renderWaitingPhase" in html
    assert "stopWaitingExperience" in html
    assert "window.matchMedia('(prefers-reduced-motion: reduce)')" in html

    assert html.count("fetch('/analyze'") == 1
    assert "EventSource" not in html
    assert "WebSocket" not in html
    assert "/analyze/stream" not in html


def test_waiting_experience_stops_on_success_failure_and_home_reset() -> None:
    html = _index_html()

    assert "clearTimeout(waitingPhaseTimer)" in html
    assert "clearInterval(waitingTipTimer)" in html
    assert "clearTimeout(waitingLongNoteTimer)" in html
    assert "stopWaitingExperience();\n                renderResults(data);" in html
    assert "catch (err) {\n                stopWaitingExperience();" in html
    assert "function clearPreview() {\n            stopWaitingExperience();" in html
