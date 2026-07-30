from __future__ import annotations

import logging
from pathlib import Path

from app.models import ActionItem, ActionPlan, RiskFinding
from app.ontology import OntologyRepository, OntologyRiskRule

logger = logging.getLogger("sumai.rule_engine")

PROFESSIONAL_CONFIRMATION_RISKS = {
    "bathroom_slip",
    "bathtub_stepover",
    "toilet_transfer",
    "genkan_step",
    "large_step",
    "stairs",
}

class RuleEngine:
    def __init__(
        self,
        checklists_path: Path | None = None,
        ontology: OntologyRepository | None = None,
    ) -> None:
        if checklists_path is not None and ontology is not None:
            raise ValueError("Pass either checklists_path or ontology, not both")
        self.checklists_path = checklists_path
        self.ontology = (
            ontology
            if ontology is not None
            else OntologyRepository.load(checklists_path)
            if checklists_path is not None
            else OntologyRepository.load_default()
        )

    def _find_checklist_item(
        self, room_type: str, finding: RiskFinding | str
    ) -> OntologyRiskRule | None:
        try:
            if isinstance(finding, str):
                return self.ontology.risk_rule(room_type, finding)
            if finding.ontology_key and finding.ontology_rule_kind:
                return self.ontology.rule(
                    room_type, finding.ontology_key, finding.ontology_rule_kind
                )
            return self.ontology.risk_rule(room_type, finding.risk_type)
        except KeyError:
            return None

    def _find_unambiguous_legacy_visible_rule(
        self, room_type: str, risk_type: str
    ) -> tuple[OntologyRiskRule | None, bool]:
        """Return a visible-only legacy rule and whether the risk is in ontology."""
        room_data = self.ontology.room(room_type)
        if room_data is None:
            return None, False

        visible_matches = [
            item
            for item in room_data["visible_hazards"]
            if item["risk_type"] == risk_type
        ]
        expected_matches = [
            item
            for item in room_data["expected_features"]
            if item["missing_risk_type"] == risk_type
        ]
        has_ontology_mapping = bool(visible_matches or expected_matches)
        if len(visible_matches) != 1 or expected_matches:
            return None, has_ontology_mapping

        try:
            return (
                self.ontology.rule(
                    room_type,
                    visible_matches[0]["key"],
                    "visible_hazard",
                ),
                True,
            )
        except KeyError:
            return None, True

    def apply(
        self, findings: list[RiskFinding], room_type: str
    ) -> tuple[list[RiskFinding], ActionPlan]:
        normalized_findings: list[RiskFinding] = []
        family: list[ActionItem] = []
        care: list[ActionItem] = []
        contractor: list[ActionItem] = []
        seen_actions: set[tuple[str, str, str]] = set()

        filtered_findings: list[tuple[RiskFinding, OntologyRiskRule | None]] = []
        for finding in findings:
            has_ontology_key = bool(finding.ontology_key)
            has_rule_kind = finding.ontology_rule_kind is not None
            if has_ontology_key != has_rule_kind:
                continue

            if has_ontology_key:
                if finding.ontology_rule_kind != "visible_hazard":
                    continue
                chk_item = self._find_checklist_item(room_type, finding)
                if chk_item is None or chk_item.rule_kind != "visible_hazard":
                    continue
            else:
                chk_item, has_ontology_mapping = (
                    self._find_unambiguous_legacy_visible_rule(
                        room_type, finding.risk_type
                    )
                )
                if has_ontology_mapping and chk_item is None:
                    continue

            if finding.confidence < 0.45:
                continue

            is_known = chk_item is not None

            if 0.45 <= finding.confidence < 0.60:
                if not is_known:
                    continue
                finding = finding.model_copy(update={"needs_human_confirmation": True})

            if not is_known:
                continue

            filtered_findings.append((finding, chk_item))

        for index, (finding, chk_item) in enumerate(filtered_findings, start=1):
            basis_label = finding.basis_label_ja
            basis_summary = finding.basis_summary_ja
            if chk_item:
                basis_label = chk_item.basis_label_ja
                basis_summary = chk_item.basis_summary_ja

            if not basis_label:
                basis_label = "高齢者住宅安全チェックの一般原則"
            if not basis_summary:
                basis_summary = "写真で見える範囲の一般的な転倒・つまずき予防の観点です。"

            needs_confirm = (
                finding.needs_human_confirmation
                or finding.confidence < 0.60
            )
            normalized = finding.model_copy(
                update={
                    "id": f"R{index}",
                    "basis_label_ja": basis_label,
                    "basis_summary_ja": basis_summary,
                    "needs_human_confirmation": needs_confirm,
                    **(
                        {
                            # Preserve legacy risk_type-only callers while
                            # restoring the semantic kind required downstream.
                            "ontology_key": chk_item.key,
                            "ontology_rule_kind": chk_item.rule_kind,
                        }
                        if chk_item
                        else {}
                    ),
                    **(
                        {
                            "risk_type": chk_item.risk_type,
                            "label_ja": chk_item.label_ja,
                            "severity": chk_item.severity,
                            "evidence_source_ids": list(
                                chk_item.evidence_source_ids
                            ),
                        }
                        if chk_item
                        else {}
                    ),
                }
            )
            normalized_findings.append(normalized)

            # Build action lists from checklist definition
            if chk_item:
                desc_reason = normalized.description_ja.rstrip("。")
                family_raw = [
                    {
                        "title_ja": act,
                        "description_ja": (
                            f"{normalized.label_ja}への対策として、{act}を行います。"
                        ),
                        "why_ja": f"{desc_reason}を防ぐためです。",
                    }
                    for act in chk_item.family_actions
                ]
                care_raw = [
                    {
                        "title_ja": act,
                        "description_ja": (
                            f"専門職と連携し、{act}について相談・検討します。"
                        ),
                        "why_ja": f"{desc_reason}のリスクを軽減するためです。",
                    }
                    for act in chk_item.care_manager_actions
                ]
                contractor_raw = [
                    {
                        "title_ja": act,
                        "description_ja": (
                            f"施工会社などの専門業者に依頼し、{act}の可否を確認します。"
                        ),
                        "why_ja": (
                            "住宅改修により高齢者の自立支援と安全を確保するためです。"
                        ),
                    }
                    for act in chk_item.contractor_actions
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
                disclaimer=self._disclaimer("family"),
            )
            self._append_actions(
                target=care,
                seen=seen_actions,
                finding=normalized,
                tier="CARE_MANAGER_PURCHASE",
                cost_level="LOW",
                requires_professional=True,
                raw_actions=care_raw,
                disclaimer=self._disclaimer("care_manager"),
            )
            self._append_actions(
                target=contractor,
                seen=seen_actions,
                finding=normalized,
                tier="CONTRACTOR_CONSTRUCTION",
                cost_level="HIGH",
                requires_professional=True,
                raw_actions=contractor_raw,
                disclaimer=self._disclaimer("contractor"),
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
                    disclaimer=self._disclaimer("contractor"),
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
        policy = self.ontology.action_policy.get("family", {})
        forbidden_words = policy.get("forbidden_words", [])
        return any(word in text for word in forbidden_words)

    def _disclaimer(self, tier: str) -> str:
        policy = self.ontology.action_policy.get(tier, {})
        return str(policy.get("disclaimer_ja", ""))
