from __future__ import annotations

from app.models import (
    ActionItem,
    ActionPlan,
    BoundingBox,
    ConfirmationItem,
    RiskFinding,
)
from app.services.report_renderer import ReportRenderer


def _confirmation() -> ConfirmationItem:
    return ConfirmationItem(
        id="C1",
        feature_key="has_handrail",
        label_ja="手すり",
        description_ja="この写真では手すりを確認できませんでした。",
        confidence=0.82,
        evidence_source_ids=["MHLW_WELFARE_HOUSING"],
        basis_label_ja="写真で確認できる範囲",
        basis_summary_ja="写真だけでは実際の有無を判断できません。",
        needs_human_confirmation=True,
    )


def _visible_finding() -> RiskFinding:
    return RiskFinding(
        id="R1",
        risk_type="hallway_cord",
        label_ja="通路上のコード",
        description_ja="通路上にコードが見え、つまずく可能性があります。",
        severity=3,
        confidence=0.91,
        bbox=BoundingBox(x=0.1, y=0.5, w=0.6, h=0.2),
        evidence_source_ids=["E1"],
        evidence_ja="床の通路を横切るコードが見えます。",
        basis_label_ja="転倒予防",
        basis_summary_ja="通路上の障害物を減らします。",
        needs_human_confirmation=False,
        ontology_key="hallway_cord",
        ontology_rule_kind="visible_hazard",
    )


def _visible_action() -> ActionItem:
    return ActionItem(
        id="A1",
        risk_id="R1",
        tier="FAMILY_NO_COST",
        title_ja="コードを通路の外へ移す",
        description_ja="コードを壁際に寄せて通路を空けます。",
        why_ja="つまずく可能性を減らすためです。",
        cost_level="ZERO",
        requires_professional=False,
        disclaimer_ja="無理に動かさず、安全を確認してください。",
    )


def test_confirmation_only_report_keeps_neutral_observations_out_of_risks_and_actions() -> None:
    reports = ReportRenderer().render(
        room_type="toilet",
        overall_risk_level="low",
        findings=[],
        confirmation_items=[_confirmation()],
        action_plan=ActionPlan(),
    )

    summary = reports["risk_summary_markdown"]
    confirmations = reports["confirmation_items_markdown"]
    assert "現時点で大きな赤枠リスクは検出されませんでした。" in summary
    assert "手すり" not in summary
    assert "## 写真での中性確認" in confirmations
    assert "手すり" in confirmations
    assert "設備が存在しないこと" in confirmations
    assert "増設が必要かどうか" in confirmations
    assert "設置位置" in confirmations

    for key in (
        "family_actions_markdown",
        "care_manager_actions_markdown",
        "contractor_actions_markdown",
    ):
        markdown = reports[key]
        assert "###" not in markdown
        assert "手すり" not in markdown
        assert "現時点で可視リスクに対応する行動候補はありません。" in markdown


def test_mixed_report_routes_only_visible_findings_into_risks_and_actions() -> None:
    reports = ReportRenderer().render(
        room_type="hallway",
        overall_risk_level="medium",
        findings=[_visible_finding()],
        confirmation_items=[_confirmation()],
        action_plan=ActionPlan(family_no_cost=[_visible_action()]),
    )

    summary = reports["risk_summary_markdown"]
    confirmations = reports["confirmation_items_markdown"]
    actions = reports["family_actions_markdown"]
    assert "通路上のコード" in summary
    assert "手すり" not in summary
    assert "手すり" in confirmations
    assert "通路上のコード" not in confirmations
    assert "コードを通路の外へ移す" in actions
    assert "手すり" not in actions


def test_report_shape_always_includes_neutral_confirmation_markdown() -> None:
    reports = ReportRenderer().render(
        room_type="hallway",
        overall_risk_level="low",
        findings=[],
        confirmation_items=[],
        action_plan=ActionPlan(),
    )
    not_applicable = ReportRenderer().render_not_applicable(
        "写真から確認対象の部屋を特定できません。"
    )

    assert set(reports) == set(not_applicable) == {
        "risk_summary_markdown",
        "confirmation_items_markdown",
        "family_actions_markdown",
        "care_manager_actions_markdown",
        "contractor_actions_markdown",
    }
    assert "中性確認項目はありません" in reports["confirmation_items_markdown"]
    assert "表示していません" in not_applicable["confirmation_items_markdown"]
