from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models import ActionItem, ActionPlan, RiskFinding


PROFESSIONAL_CONFIRMATION_RISKS = {
    "bathroom_slip",
    "bathtub_stepover",
    "toilet_transfer",
    "genkan_step",
    "large_step",
    "stairs",
}

FAMILY_FORBIDDEN_WORDS = ("購入", "レンタル", "工事", "施工", "設置を依頼", "専門")

FAMILY_DISCLAIMER = "家族でできる範囲の一般的な予防行動です。無理な作業は避けてください。"
CARE_MANAGER_DISCLAIMER = "購入・レンタル・福祉用具の相談候補です。適用制度や必要性は専門職に確認してください。"
CONTRACTOR_DISCLAIMER = "写真だけでは寸法や施工可否を判断しません。必要に応じて現地確認を行ってください。"


class RuleEngine:
    def __init__(self, rules_path: Path | None = None) -> None:
        self.rules_path = rules_path or Path(__file__).resolve().parents[1] / "knowledge_base" / "demo_rules.yaml"
        self.rules = self._load_rules()

    def apply(self, findings: list[RiskFinding]) -> tuple[list[RiskFinding], ActionPlan]:
        normalized_findings: list[RiskFinding] = []
        family: list[ActionItem] = []
        care: list[ActionItem] = []
        contractor: list[ActionItem] = []
        seen_actions: set[tuple[str, str, str]] = set()

        for index, finding in enumerate(findings, start=1):
            rule = self.rules.get(finding.risk_type, self._fallback_rule(finding))
            normalized = finding.model_copy(
                update={
                    "id": f"R{index}",
                    "basis_label_ja": rule["basis_label_ja"],
                    "basis_summary_ja": rule["basis_summary_ja"],
                    "needs_human_confirmation": finding.needs_human_confirmation or finding.confidence < 0.55,
                }
            )
            normalized_findings.append(normalized)

            before_count = len(family) + len(care) + len(contractor)
            self._append_actions(
                target=family,
                seen=seen_actions,
                finding=normalized,
                tier="FAMILY_NO_COST",
                cost_level="ZERO",
                requires_professional=False,
                raw_actions=rule.get("family_no_cost_actions", []),
                disclaimer=FAMILY_DISCLAIMER,
            )
            self._append_actions(
                target=care,
                seen=seen_actions,
                finding=normalized,
                tier="CARE_MANAGER_PURCHASE",
                cost_level="LOW",
                requires_professional=True,
                raw_actions=rule.get("care_manager_purchase_actions", []),
                disclaimer=CARE_MANAGER_DISCLAIMER,
            )
            self._append_actions(
                target=contractor,
                seen=seen_actions,
                finding=normalized,
                tier="CONTRACTOR_CONSTRUCTION",
                cost_level="HIGH",
                requires_professional=True,
                raw_actions=rule.get("contractor_construction_actions", []),
                disclaimer=CONTRACTOR_DISCLAIMER,
            )

            if normalized.risk_type in PROFESSIONAL_CONFIRMATION_RISKS:
                self._append_actions(
                    target=contractor,
                    seen=seen_actions,
                    finding=normalized,
                    tier="CONTRACTOR_CONSTRUCTION",
                    cost_level="HIGH",
                    requires_professional=True,
                    raw_actions=[
                        {
                            "title_ja": "専門職による現地確認",
                            "description_ja": "写真だけでは寸法・固定位置・下地を判断しないため、必要に応じて現地で確認します。",
                            "why_ja": "段差、水回り、立ち座り動作は転倒時の影響が大きく、写真だけで結論を出さないためです。",
                        }
                    ],
                    disclaimer=CONTRACTOR_DISCLAIMER,
                )

            after_count = len(family) + len(care) + len(contractor)
            if normalized.severity >= 4 and after_count == before_count:
                self._append_actions(
                    target=family,
                    seen=seen_actions,
                    finding=normalized,
                    tier="FAMILY_NO_COST",
                    cost_level="ZERO",
                    requires_professional=False,
                    raw_actions=[
                        {
                            "title_ja": "危険箇所の一時的な見える化",
                            "description_ja": "家族の会話用に、写真の該当箇所を確認し、今日近づく時の注意点を共有します。",
                            "why_ja": "高めのリスク候補は、まず認識をそろえることが予防の出発点になるためです。",
                        }
                    ],
                    disclaimer=FAMILY_DISCLAIMER,
                )

        return normalized_findings, ActionPlan(
            family_no_cost=family[:5],
            care_manager_purchase=care[:5],
            contractor_construction=contractor[:5],
        )

    def _load_rules(self) -> dict[str, dict[str, Any]]:
        with self.rules_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data.get("rules", {})

    def _append_actions(
        self,
        target: list[ActionItem],
        seen: set[tuple[str, str, str]],
        finding: RiskFinding,
        tier: str,
        cost_level: str,
        requires_professional: bool,
        raw_actions: list[dict[str, str]],
        disclaimer: str,
    ) -> None:
        for raw_action in raw_actions:
            title = raw_action.get("title_ja", "").strip()
            description = raw_action.get("description_ja", "").strip()
            why = raw_action.get("why_ja", "").strip()
            if not title or not description or not why:
                continue
            if tier == "FAMILY_NO_COST" and self._is_invalid_family_action(title, description, why):
                continue

            key = (tier, title, description)
            if key in seen:
                continue
            seen.add(key)

            target.append(
                ActionItem(
                    id=f"{finding.id}-{tier.lower()}-{len(target) + 1}",
                    risk_id=finding.id,
                    tier=tier,  # type: ignore[arg-type]
                    title_ja=title,
                    description_ja=description,
                    why_ja=why,
                    cost_level=cost_level,  # type: ignore[arg-type]
                    requires_professional=requires_professional,
                    disclaimer_ja=disclaimer,
                )
            )

    def _is_invalid_family_action(self, *parts: str) -> bool:
        text = " ".join(parts)
        return any(word in text for word in FAMILY_FORBIDDEN_WORDS)

    def _fallback_rule(self, finding: RiskFinding) -> dict[str, Any]:
        return {
            "basis_label_ja": "高齢者住宅安全チェックの一般原則",
            "basis_summary_ja": "写真で見える範囲の一般的な転倒・つまずき予防の観点です。",
            "family_no_cost_actions": [
                {
                    "title_ja": "家族で該当箇所を確認",
                    "description_ja": "写真の赤枠部分を見ながら、今日の移動時に気をつける場所として共有します。",
                    "why_ja": "見えるリスクを家族内でそろえることで、まず無理のない予防行動につなげるためです。",
                }
            ],
            "care_manager_purchase_actions": [],
            "contractor_construction_actions": [],
        }
