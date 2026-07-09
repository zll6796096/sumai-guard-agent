from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.models import ActionItem, ActionPlan, RiskFinding

logger = logging.getLogger("sumai.rule_engine")

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
    def __init__(self, checklists_path: Path | None = None) -> None:
        if checklists_path is None:
            checklists_path = Path(__file__).resolve().parents[1] / "knowledge_base" / "room_checklists.yaml"
        self.checklists_path = checklists_path
        self.checklists = self._load_checklists()

    def _load_checklists(self) -> dict[str, Any]:
        try:
            with self.checklists_path.open("r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        except Exception as e:
            logger.error(f"Failed to load checklists: {e}")
            return {}

    def _find_checklist_item(self, risk_type: str) -> dict[str, Any] | None:
        for room_name, room_data in self.checklists.items():
            for feat in room_data.get("expected_features", []):
                if feat.get("missing_risk_type") == risk_type:
                    return feat
            for haz in room_data.get("visible_hazards", []):
                if haz.get("risk_type") == risk_type:
                    return haz
        return None

    def apply(self, findings: list[RiskFinding]) -> tuple[list[RiskFinding], ActionPlan]:
        normalized_findings: list[RiskFinding] = []
        family: list[ActionItem] = []
        care: list[ActionItem] = []
        contractor: list[ActionItem] = []
        seen_actions: set[tuple[str, str, str]] = set()

        filtered_findings = []
        for finding in findings:
            if finding.confidence < 0.45:
                continue

            is_known = self._find_checklist_item(finding.risk_type) is not None

            if 0.45 <= finding.confidence < 0.60:
                if not is_known:
                    continue
                finding = finding.model_copy(update={"needs_human_confirmation": True})

            if not is_known:
                if finding.confidence < 0.75:
                    continue

            filtered_findings.append(finding)

        for index, finding in enumerate(filtered_findings, start=1):
            chk_item = self._find_checklist_item(finding.risk_type)
            
            # Populate basis if not already filled by checklist engine
            basis_label = finding.basis_label_ja
            basis_summary = finding.basis_summary_ja
            if chk_item:
                if not basis_label:
                    basis_label = chk_item.get("basis_label_ja", "")
                if not basis_summary:
                    basis_summary = chk_item.get("basis_summary_ja", "")

            if not basis_label:
                basis_label = "高齢者住宅安全チェックの一般原則"
            if not basis_summary:
                basis_summary = "写真で見える範囲の一般的な転倒・つまずき予防の観点です。"

            needs_confirm = finding.needs_human_confirmation or finding.confidence < 0.60
            normalized = finding.model_copy(
                update={
                    "id": f"R{index}",
                    "basis_label_ja": basis_label,
                    "basis_summary_ja": basis_summary,
                    "needs_human_confirmation": needs_confirm,
                }
            )
            normalized_findings.append(normalized)

            # Build action lists from checklist definition
            if chk_item:
                desc_reason = normalized.description_ja.rstrip("。")
                # Family actions
                family_raw = [
                    {"title_ja": act, "description_ja": f"{normalized.label_ja}への対策として、{act}を行います。", "why_ja": f"{desc_reason}を防ぐためです。"}
                    for act in chk_item.get("family_actions", [])
                ]
                # Care Manager actions
                care_raw = [
                    {"title_ja": act, "description_ja": f"専門職と連携し、{act}について相談・検討します。", "why_ja": f"{desc_reason}のリスクを軽減するためです。"}
                    for act in chk_item.get("care_manager_actions", [])
                ]
                # Contractor actions
                contractor_raw = [
                    {"title_ja": act, "description_ja": f"施工会社などの専門業者に依頼し、{act}の可否を確認します。", "why_ja": f"住宅改修により高齢者の自立支援と安全を確保するためです。"}
                    for act in chk_item.get("contractor_actions", [])
                ]
            else:
                # Fallback action
                family_raw = [{
                    "title_ja": "家族で該当箇所を確認",
                    "description_ja": "写真の赤枠部分を見ながら、今日の移動時に気をつける場所として共有します。",
                    "why_ja": "見えるリスクを家族内でそろえることで、まず無理のない予防行動につなげるためです。",
                }]
                care_raw = []
                contractor_raw = []

            self._append_actions(
                target=family,
                seen=seen_actions,
                finding=normalized,
                tier="FAMILY_NO_COST",
                cost_level="ZERO",
                requires_professional=False,
                raw_actions=family_raw,
                disclaimer=FAMILY_DISCLAIMER,
            )
            self._append_actions(
                target=care,
                seen=seen_actions,
                finding=normalized,
                tier="CARE_MANAGER_PURCHASE",
                cost_level="LOW",
                requires_professional=True,
                raw_actions=care_raw,
                disclaimer=CARE_MANAGER_DISCLAIMER,
            )
            self._append_actions(
                target=contractor,
                seen=seen_actions,
                finding=normalized,
                tier="CONTRACTOR_CONSTRUCTION",
                cost_level="HIGH",
                requires_professional=True,
                raw_actions=contractor_raw,
                disclaimer=CONTRACTOR_DISCLAIMER,
            )

            # Professional confirmation override
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

        return normalized_findings, ActionPlan(
            family_no_cost=family[:5],
            care_manager_purchase=care[:5],
            contractor_construction=contractor[:5],
        )

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
