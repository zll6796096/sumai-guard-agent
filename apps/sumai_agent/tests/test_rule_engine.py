from __future__ import annotations

from app.models import BoundingBox, RiskFinding
from app.services.rule_engine import RuleEngine


def _finding(
    risk_type: str = "hallway_cord",
    confidence: float = 0.8,
    severity: int = 3,
) -> RiskFinding:
    return RiskFinding(
        id="R1",
        risk_type=risk_type,
        label_ja="廊下の電源コード",
        description_ja="動線上に電源コードが見えます。",
        severity=severity,
        confidence=confidence,
        bbox=BoundingBox(x=0.1, y=0.2, w=0.4, h=0.2),
        evidence_ja="床の通路部分にコードが横切っています。",
        basis_label_ja="",
        basis_summary_ja="",
        needs_human_confirmation=False,
    )


def test_rule_engine_keeps_family_actions_no_cost_only() -> None:
    engine = RuleEngine()

    findings, plan = engine.apply([_finding("loose_mat")], "hallway")

    assert findings[0].basis_label_ja
    assert plan.family_no_cost
    for action in plan.family_no_cost:
        text = f"{action.title_ja} {action.description_ja}"
        assert action.cost_level == "ZERO"
        assert not action.requires_professional
        assert "購入" not in text
        assert "レンタル" not in text
        assert "工事" not in text
        assert "施工" not in text


def test_rule_engine_marks_low_confidence_for_human_confirmation() -> None:
    engine = RuleEngine()

    findings, _ = engine.apply([_finding(confidence=0.52)], "hallway")

    assert len(findings) == 1
    assert findings[0].needs_human_confirmation is True
