# 実家あんしんチェック App Review Notes

## Review access

- Account：不要です。ログイン、会員登録、課金、App内課金はありません。
- Operator：zhanglonglong
- Review contact：zll6796096@gmail.com
- Language：日本語

## Suggested review flow

1. 「カメラで撮る」または「写真を1枚選ぶ」で、架空・合成の室内写真を1枚選びます。
2. 送信前の同意画面で、Google Cloud RunとGoogle LLCのGeminiへの送信、住まいの写真に私的内容が含まれ得ること、非永続保存の説明を確認します。
3. 「同意して写真を送る」を選びます。キャンセルした場合はネットワーク要求が行われず、写真がクリアされます。
4. 写真に見える注意箇所、根拠、写真だけでは判断できない事項を確認します。
5. 「安全のためにできること」から3つの相談先別アドバイスを確認します。
6. 写真を含まない日本語のPDFを端末上で生成し、共有シートを開きます。

## Security and processing

リリース版はFirebase App CheckとApple App Attestを使用します。正規のApp Checkトークンがない解析要求は、画像本文を読み取る前に拒否されます。画像は送信前とサーバー受付時に再エンコードされ、EXIFが除去されます。

写真、結果画像、PDF、利用履歴はSumaiGuardのデータベースや利用者アカウントへ永続保存されません。構造化された解析結果は、現在の公開候補設定では最大128件、5分間のプロセス内メモリに一時保持される場合があります。通常のCloud Logging運用ログは30日間保持されますが、写真、解析結果、PDFの内容は記録しません。

Gemini APIはCloud Billingが有効な有料サービスとして利用します。Googleの追加規約では、写真と応答を製品改善には使用しませんが、不正利用の検出・防止や必要な法令対応のため限定期間記録されます。Googleが固定の保持日数を示していないため、SumaiGuard側の非永続化およびCloud Loggingの30日保持とは分けて開示します。

## Product boundary

本アプリは、写真1枚に見える範囲の一般的な注意を示します。住まいの安全を保証せず、医療、介護認定、保険、法令適合、正確な寸法、見積もり、施工の判断を代替しません。必要に応じて専門家へ相談するよう案内します。

## Review environment

公開前に本番のGoogle Cloud Runエンドポイント、Firebase App Check、Apple App Attest、プライバシーURL、サポートURLを再確認します。審査用の実在する住宅写真や個人情報は提供しません。
