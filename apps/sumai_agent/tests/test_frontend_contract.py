from __future__ import annotations

import importlib.util
import re
import subprocess
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
    assert "confirmationNote.hidden = true" in html
    assert "btnShowSuggestions.style.display = 'none'" in html
    assert "resultSummary.style.display = 'flex'" in html
    assert "document.getElementById('screen2-title').textContent = \"安全チェック結果\"" in html


def test_visible_risks_and_confirmation_items_use_separate_payload_contracts() -> None:
    html = _index_html()

    assert '<span class="summary-label">可視リスク</span>' in html
    assert 'id="confirmation-items-note"' in html
    assert 'id="confirmation-items-title"' in html
    assert 'id="confirmation-items-body"' in html
    assert 'id="result-current-image-card"' in html
    assert 'id="result-improvement-image-card"' in html
    assert (
        "const confirmationItems = Array.isArray(payload.confirmation_items) "
        "? payload.confirmation_items : [];"
    ) in html
    assert "const findings = Array.isArray(payload.findings) ? payload.findings : [];" in html
    assert "const count = findings.length;" in html
    assert "const hasVisibleFindings = findings.length > 0;" in html
    assert "confirmationNote.hidden = confirmationItems.length === 0;" in html
    assert "写真だけでは確認できない項目" in html
    assert "中性確認" not in html
    assert "中性の観察" not in html
    assert "improvementCard.hidden = !hasVisibleFindings" in html
    assert "btnShowSuggestions.style.display = hasVisibleFindings ? '' : 'none'" in html


def test_all_markdown_sinks_use_an_inert_strict_allowlist_renderer() -> None:
    html = _index_html()

    assert "function renderSafeMarkdown(element, markdown)" in html
    assert "const template = document.createElement('template');" in html
    assert "template.innerHTML = parsedMarkdown;" in html
    assert "node.removeAttribute(attribute.name);" in html
    assert "element.replaceChildren(template.content.cloneNode(true));" in html
    assert ".innerHTML = marked.parse(" not in html

    allowlist_match = re.search(
        r"const SAFE_MARKDOWN_TAGS = new Set\(\[([^\]]+)\]\);",
        html,
        flags=re.DOTALL,
    )
    assert allowlist_match is not None
    allowlist = set(re.findall(r"'([A-Z0-9]+)'", allowlist_match.group(1)))
    assert allowlist == {
        "H2",
        "H3",
        "P",
        "UL",
        "OL",
        "LI",
        "STRONG",
        "EM",
        "BR",
        "CODE",
    }
    assert allowlist.isdisjoint({"A", "IMG", "SCRIPT", "STYLE", "IFRAME"})

    for element_id, field in (
        ("confirmation-items-body", "confirmation_items_markdown"),
        ("action-family-content", "family_actions_markdown"),
        ("action-care-content", "care_manager_actions_markdown"),
        ("action-contractor-content", "contractor_actions_markdown"),
        ("risk-details-content", "risk_summary_markdown"),
    ):
        assert (
            f"renderSafeMarkdown(document.getElementById('{element_id}'), "
            f"payload.{field});"
        ) in html
    assert "finding.ontology_rule_kind === 'expected_feature'" not in html
    assert "画像上に赤枠や設置候補を表示していません" in html
    assert "位置を特定できる注意箇所はありません" in html


def test_applicable_zero_risk_keeps_current_image_but_hides_improvement_and_navigation() -> None:
    html = _index_html()

    assert "imagesList.style.display = 'flex'" in html
    assert "currentImage.src = 'data:image/png;base64,' + payload.annotated_image_base64" in html
    assert "improvementCard.hidden = !hasVisibleFindings" in html
    assert "btnShowSuggestions.style.display = hasVisibleFindings ? '' : 'none'" in html


def test_waiting_ui_uses_real_stages_without_fake_progress() -> None:
    html = _index_html()

    assert "写真を安全に処理" in html
    assert "見える範囲を解析" in html
    assert "結果を整理" in html
    assert "application/x-ndjson" in html
    assert "response.body.getReader()" in html
    assert "intake_complete" in html
    assert "vision_complete" in html
    assert "step1 = setTimeout" not in html
    assert "step2 = setTimeout" not in html
    assert "}, 1200)" not in html
    assert "}, 2600)" not in html
    assert 'id="analysis-progress-percent"' not in html
    assert 'aria-valuenow="' not in html
    assert "fetch('/analyze/stream'" in html
    assert "fetch('/analyze'" not in html
    assert html.count("fetch('/analyze/stream'") == 1


def test_waiting_tips_are_local_and_motion_is_accessible() -> None:
    html = _index_html()

    assert "床が濡れていたら、早めに拭きましょう。" in html
    assert (
        "通り道に物がないか、無理のない範囲で確認しましょう。"
        in html
    )
    assert (
        "夜間に足元が見える明るさか、家族と確認しましょう。"
        in html
    )
    assert "prefers-reduced-motion: reduce" in html
    assert ".analysis-scan-line," in html
    assert ".analysis-activity::after," in html
    assert "animation: none !important;" in html
    assert "通常より時間がかかっていますが、解析は続いています" in html
    assert 'aria-live="polite"' in html
    assert "}, 5000);" in html
    assert "}, 20000);" in html


def test_waiting_lifecycle_cleans_local_timers_and_active_request() -> None:
    html = _index_html()

    assert "let analysisTipTimer = null;" in html
    assert "let longWaitTimer = null;" in html
    assert "let activeAnalysisSession = null;" in html
    assert "window.clearInterval(analysisTipTimer);" in html
    assert "window.clearTimeout(longWaitTimer);" in html
    assert "session.controller.signal" in html
    assert "event.type === 'result'" in html
    assert "event.type === 'error'" in html
    assert "stopWaitingExperience();" in html
    assert "cancelActiveAnalysis();" in html
    assert "window.addEventListener('pagehide', cancelActiveAnalysis);" in html
    assert "document.addEventListener('visibilitychange'" in html
    assert "if (document.hidden)" in html
    assert "if (activeAnalysisSession !== session) return;" in html
    assert "function resetApp()" in html


def test_waiting_stream_contract_is_indeterminate_local_and_safe() -> None:
    html = _index_html()

    assert 'class="analysis-activity"' in html
    assert 'role="progressbar"' in html
    assert "setInterval" in html
    assert "setInterval(fetch" not in html
    assert "setTimeout(fetch" not in html
    assert "analysisErrorMessage(accepted.error)" in html
    assert "event.message" not in html
    assert "new AnalysisRequestSession(new AbortController())" in html
    assert "let reader = null;" in html
    assert "reader = response.body.getReader();" in html
    assert "new TextDecoder()" in html
    assert "class AnalysisUiError extends Error" in html
    assert "err instanceof AnalysisUiError" in html
    assert "err && err.message" not in html


def test_analysis_request_and_event_state_machines_execute_in_node() -> None:
    html = _index_html()
    block = re.search(
        r"/\* ANALYSIS_STATE_MACHINES_START \*/"
        r"(?P<body>.*?)"
        r"/\* ANALYSIS_STATE_MACHINES_END \*/",
        html,
        flags=re.DOTALL,
    )
    assert block is not None
    test_script = r"""
const assert = require('node:assert/strict');

(async () => {
    const state = new AnalysisEventStateMachine();
    assert.deepEqual(
        state.accept({type: 'progress', stage: 'intake_complete'}),
        {type: 'progress', stage: 'intake_complete'}
    );
    assert.throws(
        () => state.accept({type: 'progress', stage: 'intake_complete'}),
        AnalysisUiError
    );
    assert.deepEqual(
        state.accept({type: 'progress', stage: 'vision_complete'}),
        {type: 'progress', stage: 'vision_complete'}
    );
    assert.deepEqual(
        state.accept({type: 'result', payload: {ok: true}}),
        {type: 'result', payload: {ok: true}}
    );
    assert.throws(
        () => state.accept({type: 'error', error: 'analysis_failed'}),
        AnalysisUiError
    );

    const earlyResult = new AnalysisEventStateMachine();
    assert.throws(
        () => earlyResult.accept({type: 'result', payload: {ok: true}}),
        AnalysisUiError
    );

    let aborts = 0;
    let cancels = 0;
    const controller = {
        signal: {aborted: false},
        abort() {
            aborts += 1;
            this.signal.aborted = true;
        }
    };
    const reader = {
        cancel() {
            cancels += 1;
            return Promise.resolve();
        }
    };
    const request = new AnalysisRequestSession(controller);
    request.attachReader(reader);
    await request.cancel();
    await request.cancel();
    assert.equal(aborts, 1);
    assert.equal(cancels, 1);
    assert.equal(request.succeeded, false);

    let successAborts = 0;
    let successCancels = 0;
    const successController = {
        signal: {aborted: false},
        abort() {
            successAborts += 1;
            this.signal.aborted = true;
        }
    };
    const successRequest = new AnalysisRequestSession(successController);
    successRequest.attachReader({
        cancel() {
            successCancels += 1;
            return Promise.resolve();
        }
    });
    await successRequest.finishSuccess();
    await successRequest.cancel();
    assert.equal(successRequest.succeeded, true);
    assert.equal(successAborts, 0);
    assert.equal(successCancels, 1);

    let lateCancels = 0;
    const lateController = {
        signal: {aborted: false},
        abort() {
            this.signal.aborted = true;
        }
    };
    const lateRequest = new AnalysisRequestSession(lateController);
    await lateRequest.cancel();
    lateRequest.attachReader({
        cancel() {
            lateCancels += 1;
            return Promise.resolve();
        }
    });
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(lateCancels, 1);

    const throwingRequest = new AnalysisRequestSession({
        signal: {aborted: false},
        abort() {
            this.signal.aborted = true;
        }
    });
    throwingRequest.attachReader({
        cancel() {
            throw new Error('reader-secret');
        }
    });
    await assert.doesNotReject(() => throwingRequest.cancel());
})().catch(error => {
    console.error(error);
    process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", block.group("body") + test_script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
