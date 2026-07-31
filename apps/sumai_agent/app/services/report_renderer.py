from __future__ import annotations

import html

from app.models import (
    ActionItem,
    ActionPlan,
    ConfirmationItem,
    RiskFinding,
    RiskLevel,
    RoomType,
)


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


def _markdown_text(value: str) -> str:
    """Keep model-controlled text inline and prevent raw HTML in Markdown."""
    return html.escape(" ".join(value.splitlines()), quote=True)


class ReportRenderer:
    def render_not_applicable(self, reason_ja: str) -> dict[str, str]:
        summary = "\n".join(
            [
                "## リスク概要",
                "- 判定: 対象外または判定不能",
                f"- 理由: {_markdown_text(reason_ja)}",
                "- 写真から安全性を判定できません。",
                "- 安全または低リスクという意味ではないため、写真外の状況を含めて確認が必要です。",
            ]
        )
        undecided = "対象外または判定不能のため、具体的な提案は表示していません。"
        return {
            "risk_summary_markdown": summary,
            "confirmation_items_markdown": (
                "## 写真だけでは確認できない項目\n\n"
                "対象外または判定不能のため、項目は表示していません。"
            ),
            "family_actions_markdown": f"## 家族で今日できること\n\n{undecided}",
            "care_manager_actions_markdown": f"## ケアマネ・福祉用具に相談\n\n{undecided}",
            "contractor_actions_markdown": f"## 専門施工・現地確認\n\n{undecided}",
        }

    def render(
        self,
        room_type: RoomType,
        overall_risk_level: RiskLevel,
        findings: list[RiskFinding],
        confirmation_items: list[ConfirmationItem],
        action_plan: ActionPlan,
    ) -> dict[str, str]:
        return {
            "risk_summary_markdown": self.risk_summary(
                room_type,
                overall_risk_level,
                findings,
                has_confirmation_items=bool(confirmation_items),
            ),
            "confirmation_items_markdown": self.confirmations_markdown(
                confirmation_items
            ),
            "family_actions_markdown": self.actions_markdown(
                "家族で今日できること",
                action_plan.family_no_cost,
            ),
            "care_manager_actions_markdown": self.actions_markdown(
                "ケアマネ・福祉用具に相談",
                action_plan.care_manager_purchase,
            ),
            "contractor_actions_markdown": self.actions_markdown(
                "専門施工・現地確認",
                action_plan.contractor_construction,
            ),
        }

    def risk_summary(
        self,
        room_type: RoomType,
        overall_risk_level: RiskLevel,
        findings: list[RiskFinding],
        *,
        has_confirmation_items: bool = False,
    ) -> str:
        lines = [
            "## リスク概要",
            f"- 部屋: {ROOM_LABELS.get(room_type, room_type)}",
            f"- 写真内の可視リスクレベル: {RISK_LABELS[overall_risk_level]}",
            "- 写真で見える範囲だけを対象にしています。",
            "",
        ]
        if not findings:
            lines.append("現時点で大きな赤枠リスクは検出されませんでした。")
            if has_confirmation_items:
                lines.append(
                    "ただし、写真だけでは判断できず、現地確認が必要な項目があります。"
                )
            lines.append("写真外の状況は判断できません。")
            return "\n".join(lines)

        for finding in findings:
            confidence_percent = round(finding.confidence * 100)
            lines.extend(
                [
                    f"### 注意箇所: {_markdown_text(finding.label_ja)}",
                    f"- 危険な理由: {_markdown_text(finding.description_ja)}",
                    f"- 理由の根拠: {_markdown_text(finding.evidence_ja)}",
                    f"- 参考根拠: {_markdown_text(finding.basis_label_ja)}",
                    f"- 根拠の要約: {_markdown_text(finding.basis_summary_ja)}",
                    f"- モデル検出スコア（未校正）: {confidence_percent}%",
                ]
            )
            if finding.needs_human_confirmation:
                lines.append("- 要確認: 写真だけでは断定せず、人の確認が必要です。")
            lines.append("")
        return "\n".join(lines).strip()

    def confirmations_markdown(
        self,
        confirmation_items: list[ConfirmationItem],
    ) -> str:
        lines = [
            "## 写真だけでは確認できない項目",
            "",
            "ここには、写真の中で確認できなかった項目だけを表示しています。",
            "写真で確認できなかったことは、住宅内に存在しないことを意味しません。",
            "増設が必要かどうかや、設置位置も、この写真だけでは判断できません。",
            "誤解を避けるため、画像上に赤枠や設置候補を表示していません。",
            "",
        ]
        if not confirmation_items:
            lines.append("この写真には、追加で表示する項目はありません。")
            return "\n".join(lines)

        for item in confirmation_items:
            lines.extend(
                [
                    f"### 確認項目: {_markdown_text(item.label_ja)}",
                    f"- 写真での確認: {_markdown_text(item.description_ja)}",
                    "- 人による確認: 必要に応じて、実際の設備と周囲の状況を確認してください。",
                    "",
                ]
            )
        return "\n".join(lines).strip()

    def actions_markdown(
        self,
        title: str,
        actions: list[ActionItem],
    ) -> str:
        lines = [f"## {_markdown_text(title)}", ""]
        if not actions:
            lines.append("現時点で可視リスクに対応する行動候補はありません。")
            return "\n".join(lines)

        for action in actions:
            lines.extend(
                [
                    f"### {_markdown_text(action.title_ja)}",
                    "- 対象: 今回検出された危険箇所",
                    f"- 内容: {_markdown_text(action.description_ja)}",
                    f"- 理由: {_markdown_text(action.why_ja)}",
                    f"- 注意: {_markdown_text(action.disclaimer_ja)}",
                    "",
                ]
            )
        return "\n".join(lines).strip()
