from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path


def _index_html() -> str:
    app_path = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"
    module_name = f"sumai_web_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.INDEX_HTML


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
