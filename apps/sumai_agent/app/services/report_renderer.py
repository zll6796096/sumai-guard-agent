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
        return {
            "risk_summary_markdown": self.risk_summary(room_type, overall_risk_level, findings),
            "family_actions_markdown": self.actions_markdown("家族で今日できること", action_plan.family_no_cost),
            "care_manager_actions_markdown": self.actions_markdown("ケアマネ・福祉用具に相談", action_plan.care_manager_purchase),
            "contractor_actions_markdown": self.actions_markdown("専門施工・現地確認", action_plan.contractor_construction),
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
            lines.extend(
                [
                    f"### {finding.id}: {finding.label_ja}",
                    f"- 危険な理由: {finding.description_ja}",
                    f"- 写真上の根拠: {finding.evidence_ja}",
                    f"- 参考根拠: {finding.basis_label_ja}",
                    f"- 根拠の要約: {finding.basis_summary_ja}",
                    f"- 信頼度: {confidence_percent}%",
                ]
            )
            if finding.needs_human_confirmation:
                lines.append("- 要確認: 写真だけでは断定せず、人の確認が必要です。")
            lines.append("")
        return "\n".join(lines).strip()

    def actions_markdown(self, title: str, actions: list[ActionItem]) -> str:
        lines = [f"## {title}", ""]
        if not actions:
            lines.append("この写真からは、この区分の具体的な提案はありません。")
            return "\n".join(lines)

        for action in actions:
            lines.extend(
                [
                    f"### {action.title_ja}",
                    f"- 対象リスク: {action.risk_id}",
                    f"- 内容: {action.description_ja}",
                    f"- 理由: {action.why_ja}",
                    f"- 注意: {action.disclaimer_ja}",
                    "",
                ]
            )
        return "\n".join(lines).strip()
