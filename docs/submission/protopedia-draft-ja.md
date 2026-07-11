# ProtoPedia 投稿草稿 — 親の家 安全チェックAI

この文書は ProtoPedia 入力用の確認済み草稿です。外部公開前に YouTube URL を差し替え、各 URL の到達性を再確認してください。

## 基本情報

- **作品タイトル**: 親の家 安全チェックAI：1枚の写真から転倒リスクと次の行動を整理
- **ステータス**: 開発中（動作する POC / Cloud Run 公開デモ）
- **ひとこと概要**: 写真1枚から見える転倒リスクを赤枠で可視化し、家族・福祉用具・専門施工の3段階へ整理するAIエージェント。
- **カテゴリ候補**: アプリケーション / データサイエンス・AI・BOT
- **関連イベント**: DevOps × AI Agent Hackathon 最新ツールでAIエージェント開発を体験しよう（2026）
- **公開範囲**: 一般公開
- **ライセンス**: 要確認（公開画面でユーザーが選択）

## タグ

`findy_hackathon` `AI` `生成AI` `AIエージェント` `Gemini` `GoogleCloud` `CloudRun` `FastAPI` `HTML` `JavaScript` `Python` `高齢者住宅` `転倒予防`

必須タグ `findy_hackathon` は表記を変えずに登録します。

## 開発素材

- Google Cloud Run
- Gemini 2.5 Flash（Gemini API）
- Python
- FastAPI
- HTML / CSS / Vanilla JavaScript
- Pydantic
- Pillow
- Docker / Docker Compose
- GitHub Actions

## 作品概要

離れて暮らす親の家では、床の物、滑りやすそうな場所、段差などの危険が、転倒やヒヤリハットの後まで家族に共有されないことがあります。

「親の家 安全チェックAI」は、質問票や個人プロフィールを入力せず、室内写真を1枚送るだけで安全対話のきっかけをつくる POC です。Gemini 2.5 Flash が写真で確認できる転倒・滑り・つまずき候補を構造化して抽出し、アプリ側の決定論ルールが次の行動を3段階に分類します。結果は、赤枠付き画像、慎重な根拠説明、改善イメージ、行動別レポートとして日本語で返します。

## ストーリー

### 背景と課題

離れて暮らす家族は、親の家に潜む危険を日常的に確認できません。一方、住まい全体の詳しい質問票や専門知識を最初から求めると、点検を始める負担が大きくなります。

そこで本 POC は、「事故を予測すること」ではなく、「写真で見える範囲の危険を家族が同じ画面で確認し、次に誰へ相談するかを整理すること」に目的を限定しました。1枚の写真を、安全について話し始めるための最小入力にしています。

### 想定ユーザー

- 離れて暮らす親の住まいを気にかける子世代
- 親子で住まいの安全を話し合いたい家族
- ケアマネジャーや福祉用具専門職へ相談する前に、写真で論点を整理したい人

### プロダクトの特徴

1. **写真1枚から開始**
   高齢者本人の年齢、病歴、介護度、転倒歴などを尋ねず、室内写真1枚だけで点検を始めます。

2. **見える根拠を可視化**
   写真で確認できる危険候補を赤枠と日本語ラベルで示し、根拠を慎重な日本語で説明します。写真が住宅内部でない場合や、明確な危険を確認できない場合も扱います。

3. **AI抽出と行動判断を分離**
   Gemini は写真から見える候補の抽出を担当します。返却 JSON は Pydantic スキーマで検証し、その後の行動区分は決定論ルールが担当します。Gemini が「家族でできること」「福祉用具の相談」「専門施工」の境界を上書きしない設計です。

4. **次の行動を3段階に整理**
   - 家族で今日できること：費用のかからない行動のみ
   - ケアマネ・福祉用具に相談：購入、レンタル、福祉用具の相談
   - 専門施工・現地確認：施工会社などによる確認が必要な候補

5. **安全境界を明示**
   アップロード画像はアプリ内に永続保存せず、Gemini へ送る前に EXIF 情報を除去します。写真1枚から正確な寸法、制度適用、施工可否を断定しません。

## AIエージェントと技術構成

ブラウザから Cloud Run 上の `sumai-web`（FastAPI が配信する HTML / CSS / Vanilla JavaScript UI）へ写真を送り、`sumai-agent`（FastAPI）が次の処理を順に実行します。

1. 画像をメモリ上で読み込み、EXIF 除去、向き補正、RGB 化、最大 1600 px への縮小を実施
2. Gemini 2.5 Flash が住宅内部かを確認し、写真で見える危険候補と正規化座標を構造化 JSON で抽出
3. Pydantic が部屋種別、信頼度、重要度、バウンディングボックスなどの応答スキーマを検証
4. 決定論ルールが信頼度しきい値と既知ルールを適用し、3段階の行動へ分類
5. 赤枠付き画像、改善イメージ、日本語レポートを生成して Web UI に返却

公開デモのバックエンドは `MOCK_MODE=false`、`REQUIRE_REAL_GEMINI=true` の strict mode で動作し、Gemini が利用できない場合にモック結果を実結果として返さない構成です。2026-07-12 JST の確認時点で、住宅画像と非住宅画像のオンラインスモークテスト、およびバックエンド 160 テストが通過しています。外部サービス状態は確認後に変化する可能性があるため、再現用の時点証拠をリポジトリ内の evidence JSON に残しています。

## Google Cloud / ハッカソン要件との対応

- **Google Cloud 上のアプリケーション実行環境**: `sumai-web` と `sumai-agent` を Cloud Run に配置
- **Google Cloud AI**: Gemini 2.5 Flash を写真の見える危険候補の抽出に使用
- **AIエージェントの中心性**: 画像理解、構造化候補抽出、検証、決定論ポリシー、可視化・レポート生成を一つの点検フローとして実行
- **実装と運用の確認**: 公開コード、Cloud Run の動作デモ、strict Gemini スモークテスト、ローカル自動テストの時点証拠を保存

## URL

- **公開 GitHub**: https://github.com/zll6796096/sumai-guard-agent
- **Cloud Run デモ**: https://sumai-web-sxielk4wua-an.a.run.app
- **YouTube デモ動画**: `PLACEHOLDER_YOUTUBE_URL`
- **技術・検証エビデンス**: https://github.com/zll6796096/sumai-guard-agent/blob/main/docs/submission/sumai-guard-hackathon-evidence.json

## 動画

- **登録 URL**: `PLACEHOLDER_YOUTUBE_URL`
- **動画タイトル案**: 親の家 安全チェックAI｜1枚の写真から転倒リスクと次の行動を整理
- **成片 SHA-256**: `d55207a29593cac08d85411fd8a0222f9bd673a382e3bb32545f87ed338b6207`
- **長さ / 形式**: 76.049 秒 / 1920×1080 / H.264 + AAC

## システム構成画像

- **ファイル**: `docs/submission/assets/sumai-guard-architecture.png`
- **編集可能な原本**: `docs/submission/assets/sumai-guard-architecture.svg`
- **サイズ**: 1920×1080
- **説明文**: Browser → Cloud Run（FastAPI + HTML / JavaScript の sumai-web、FastAPI の sumai-agent）→ EXIF除去・リサイズ → Gemini 2.5 Flash → Pydantic スキーマ検証 → 決定論ルール → 赤枠画像・レポート、という責務分離を示しています。

## 掲載画像候補

| 順序 | ファイル | 内容 | 成片時刻 |
|---|---|---|---:|
| 1 | `docs/submission/assets/01-photo-input.png` | 質問票なし、写真1枚から始める入力画面 | 17.5 秒 |
| 2 | `docs/submission/assets/02-real-gemini-analysis.png` | Cloud Run × Gemini 2.5 Flash の分析状態 | 27.2 秒 |
| 3 | `docs/submission/assets/03-visible-risk-result.png` | 赤枠と根拠説明による可視化 | 31.5 秒 |
| 4 | `docs/submission/assets/04-action-tiers.png` | 決定論ルールによる3段階の次の行動 | 51.5 秒 |

4枚はいずれも、SHA-256 が `d55207a2…6207` の最終成片から 1920×1080 のまま抽出しています。

## 素材の再生成

システム構成 PNG は、編集可能な SVG 原本を macOS 標準の `sips` で描画し、Pillow で変換時のメタデータを除去して再生成できます。

```bash
TMP_PNG=/tmp/sumai-guard-architecture-render.png
rm -f "$TMP_PNG"
sips -s format png docs/submission/assets/sumai-guard-architecture.svg --out "$TMP_PNG"

python - "$TMP_PNG" docs/submission/assets/sumai-guard-architecture.png <<'PY'
import sys
from PIL import Image

with Image.open(sys.argv[1]) as image:
    image.convert("RGBA").save(sys.argv[2], format="PNG", optimize=True)
PY
```

掲載画像は、SHA-256 が `d55207a29593cac08d85411fd8a0222f9bd673a382e3bb32545f87ed338b6207` の成片を 30 fps でデコードし、次のフレーム番号から抽出しています。

```bash
VIDEO="$HOME/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4"

ffmpeg -i "$VIDEO" -vf "select='eq(n,525)'"  -vsync 0 -frames:v 1 docs/submission/assets/01-photo-input.png
ffmpeg -i "$VIDEO" -vf "select='eq(n,816)'"  -vsync 0 -frames:v 1 docs/submission/assets/02-real-gemini-analysis.png
ffmpeg -i "$VIDEO" -vf "select='eq(n,945)'"  -vsync 0 -frames:v 1 docs/submission/assets/03-visible-risk-result.png
ffmpeg -i "$VIDEO" -vf "select='eq(n,1545)'" -vsync 0 -frames:v 1 docs/submission/assets/04-action-tiers.png
```

## 免責・制約

この POC は、写真で見える範囲の一般的な転倒・滑り・つまずき予防を支援するものです。医療、介護度、保険適用、法令適合、施工可否を判断・保証するものではなく、専門家の判断を代替しません。改善イメージは家族や専門職とのコミュニケーション用であり、施工図ではありません。写真1枚から正確な寸法や見えない危険を判断することはできません。

## 公開直前チェック

- [ ] `PLACEHOLDER_YOUTUBE_URL` を実際の YouTube URL に置換
- [ ] GitHub リポジトリが一般公開され、evidence JSON と掲載画像へ到達できる
- [ ] Cloud Run デモが外部から表示・分析できる
- [ ] ProtoPedia の公開範囲を「一般公開」に設定
- [ ] 必須タグ `findy_hackathon` を登録
- [ ] 関連イベントを DevOps × AI Agent Hackathon 2026 に設定
- [ ] タイトル、概要、画像、動画、システム構成、ストーリー、関連リンクをプレビュー確認
- [ ] 公開操作の直前にユーザー確認を取得
