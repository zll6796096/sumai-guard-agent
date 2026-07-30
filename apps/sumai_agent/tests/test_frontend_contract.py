from __future__ import annotations

import importlib.util
import re
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
