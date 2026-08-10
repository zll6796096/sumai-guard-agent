# 実家あんしんチェック App Privacy 回答案

この文書はApp Store Connect入力用の保守的な草稿です。対象バイナリと実運用設定を再確認してから保存します。

運営者：zhanglonglong
連絡先：zll6796096@gmail.com

## トラッキング

- Tracking：No
- 広告、第三者広告、利用者追跡、広告プロファイリング：なし

## Photos or Videos

- Collected：Yes
- Purpose：App Functionality
- Linked to the User：Yes（住まいの写真が人物・世帯を識別し得るため保守的に回答）
- Used for Tracking：No

写真1枚はGoogle Cloud Run上のSumaiGuardバックエンドとGoogle LLCのGeminiへ送信されます。送信前にEXIFを削除し、写真をSumaiGuardのデータベース、アカウント、利用履歴へ永続保存しません。

Gemini APIは有料サービスとして利用します。Googleの追加規約では写真と応答を製品改善には使用しませんが、不正利用の検出・防止や必要な法令対応のため限定期間記録されます。Googleが固定の保持日数を示していないため、SumaiGuard側の非永続化とは分けて回答します。

## Diagnostics / Other Diagnostic Data

- Collected：Yes
- Purpose：App Functionality
- Linked to the User：No
- Used for Tracking：No

Cloud Loggingへ処理時刻、応答状態、処理時間、画像のMIMEタイプとバイト数、検出件数などの運用メタデータが記録される場合があります。通常の運用ログは30日間保持されます。写真、解析結果、PDFの内容、トークン、認証情報は記録しません。

## App integrity / Fraud Prevention

Firebase App CheckとApple App Attestを、正規アプリからの要求確認および不正利用対策に利用します。広告やプロファイリングには利用しません。

## Data Not Collected

選択しません。写真と運用メタデータの処理を上記のとおり申告します。

## 公開ポリシーに含める境界

写真1枚に見える転倒・つまずき・滑りの可能性のみを扱います。医療、介護認定、保険、法令適合、正確な寸法、見積もり、施工の判断を行いません。
