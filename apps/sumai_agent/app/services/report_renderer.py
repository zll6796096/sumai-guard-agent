from __future__ import annotations

from app.models import ActionItem, ActionPlan, RiskFinding, RiskLevel, RoomType


ROOM_LABELS = {
    "auto": "おまかせ",
    "genkan": "玄関",
    "hallway": "廊下",
    "bathroom": "浴室",
    "toilet": "トイレ",
    "bedroom": "寝室",
    "kitchen": "キッチン",
}

RISK_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}


class ReportRenderer:
    def render_not_applicable(self, reason_ja: str) -> dict[str, str]:
        summary = "\n".join(
            [
                "## リスク概要",
                "- 判定: 対象外または判定不能",
                f"- 理由: {reason_ja}",
                "- 写真から安全性を判定できません。",
                "- 安全または低リスクという意味ではないため、写真外の状況を含めて確認が必要です。",
            ]
        )
        undecided = "対象外または判定不能のため、具体的な提案は表示していません。"
        return {
            "risk_summary_markdown": summary,
            "family_actions_markdown": f"## 家族で今日できること\n\n{undecided}",
            "care_manager_actions_markdown": f"## ケアマネ・福祉用具に相談\n\n{undecided}",
            "contractor_actions_markdown": f"## 専門施工・現地確認\n\n{undecided}",
        }

    def render(
        self,
        room_type: RoomType,
        overall_risk_level: RiskLevel,
        findings: list[RiskFinding],
        action_plan: ActionPlan,
    ) -> dict[str, str]:
        if not findings:
            msg = "写真内に明確な転倒リスクは検出されませんでした。必要に応じて別角度で撮影してください。"
            return {
                "risk_summary_markdown": self.risk_summary(room_type, overall_risk_level, findings),
                "family_actions_markdown": msg,
                "care_manager_actions_markdown": msg,
                "contractor_actions_markdown": msg,
            }
        finding_kinds = {
            finding.id: finding.ontology_rule_kind for finding in findings
        }
        return {
            "risk_summary_markdown": self.risk_summary(room_type, overall_risk_level, findings),
            "family_actions_markdown": self.actions_markdown(
                "家族で今日できること",
                action_plan.family_no_cost,
                finding_kinds,
            ),
            "care_manager_actions_markdown": self.actions_markdown(
                "ケアマネ・福祉用具に相談",
                action_plan.care_manager_purchase,
                finding_kinds,
            ),
            "contractor_actions_markdown": self.actions_markdown(
                "専門施工・現地確認",
                action_plan.contractor_construction,
                finding_kinds,
            ),
        }

    def risk_summary(
        self,
        room_type: RoomType,
        overall_risk_level: RiskLevel,
        findings: list[RiskFinding],
    ) -> str:
        lines = [
            "## リスク概要",
            f"- 部屋: {ROOM_LABELS.get(room_type, room_type)}",
            f"- 総合リスク: {RISK_LABELS[overall_risk_level]}",
            "- 写真で見える範囲だけを対象にしています。",
            "",
        ]
        if not findings:
            lines.extend(["現時点で大きな赤枠リスクは検出されませんでした。", "ただし、写真外の状況は判断できません。"])
            return "\n".join(lines)

        for finding in findings:
            confidence_percent = round(finding.confidence * 100)
            if finding.ontology_rule_kind == "expected_feature":
                lines.extend(
                    [
                        f"### 写真内で確認できなかった設備: {finding.label_ja}",
                        f"- 確認結果: {finding.description_ja}",
                        f"- 確認した範囲: {finding.evidence_ja}",
                        "- 画像上の位置表示: なし"
                        "（不存在や設置位置を示すものではありません）",
                        f"- 参考根拠: {finding.basis_label_ja}",
                        f"- 根拠の要約: {finding.basis_summary_ja}",
                        f"- モデル検出スコア（未校正）: {confidence_percent}%",
                        "- 人による確認: 写真だけで不存在や必要性を断定せず、"
                        "実際の設備と状況を確認してください。",
                        "",
                    ]
                )
                continue
            lines.extend(
                [
                    f"### 注意箇所: {finding.label_ja}",
                    f"- 危険な理由: {finding.description_ja}",
                    f"- 理由の根拠: {finding.evidence_ja}",
                    f"- 参考根拠: {finding.basis_label_ja}",
                    f"- 根拠の要約: {finding.basis_summary_ja}",
                    f"- モデル検出スコア（未校正）: {confidence_percent}%",
                ]
            )
            if finding.needs_human_confirmation:
                lines.append("- 要確認: 写真だけでは断定せず、人の確認が必要です。")
            lines.append("")
        return "\n".join(lines).strip()

    def actions_markdown(
        self,
        title: str,
        actions: list[ActionItem],
        finding_kinds: dict[str, str | None] | None = None,
    ) -> str:
        lines = [f"## {title}", ""]
        if not actions:
            lines.append("この写真からは、この区分の具体的な提案はありません。")
            return "\n".join(lines)

        for action in actions:
            is_expected_feature = (
                finding_kinds is not None
                and finding_kinds.get(action.risk_id) == "expected_feature"
            )
            target = (
                "写真内で確認できなかった設備（画像上の位置表示なし）"
                if is_expected_feature
                else "今回検出された危険箇所"
            )
            lines.extend(
                [
                    f"### {action.title_ja}",
                    f"- 対象: {target}",
                    f"- 内容: {action.description_ja}",
                    f"- 理由: {action.why_ja}",
                    f"- 注意: {action.disclaimer_ja}",
                    "",
                ]
            )
        return "\n".join(lines).strip()
