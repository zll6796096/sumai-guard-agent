# YouTube upload draft

## Upload artifact

- File: `/Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4`
- Required SHA-256: `d55207a29593cac08d85411fd8a0222f9bd673a382e3bb32545f87ed338b6207`
- Duration: about 76 seconds

## Title

親の家 安全チェックAI｜1枚の写真から転倒リスクと次の行動を整理

## Description

親や家族の住まいを1枚撮影すると、見えている転倒・滑り・つまずきのリスクを整理し、赤枠付き画像と「次に取る行動」を提示する予防型AIエージェントのデモです。

Gemini 2.5 Flashは写真から見える危険候補を抽出します。その後、決定論的なルールエンジンが、提案を次の3段階に振り分けます。

- 家族で今日できること（費用・購入・工事を伴わない対応）
- ケアマネ・福祉用具に相談（購入・レンタル・福祉用具の相談）
- 専門施工・現地確認（専門家による施工・現地確認）

Google Cloud Run上でフロントエンドとAIエージェントを運用し、実デモではモックへの暗黙フォールバックを禁止するstrict modeを使用しています。

公開デモ: https://sumai-web-sxielk4wua-an.a.run.app
GitHub: https://github.com/zll6796096/sumai-guard-agent
ProtoPedia: {{PROTOPEDIA_URL}}

画像はアプリ内に永続保存せず、Geminiへ送信する前にEXIF情報を除去します。本POCは、医療・介護・保険・施工の専門判断に代わるものではありません。1枚の写真から見える範囲の安全対話を始めるための補助ツールです。

DevOps × AI Agent Hackathon 2026 応募作品

#findy_hackathon #Gemini #GoogleCloud #CloudRun #AIエージェント

## Settings

- Visibility: Unlisted
- Audience: No, it is not made for kids
- Category: Science & Technology
- Language: Japanese
- License: Standard YouTube License
- Paid promotion: No
- Altered or synthetic content: No realistic person/event/place is altered; the narration itself is synthesized
- Comments: On
- Recording date: 2026-07-11
