"""Static public privacy and support pages for the SumaiGuard web service.

The pages contain no runtime user data and load no third-party resources.
"""

from __future__ import annotations


_PAGE_STYLES = """
        :root {
            color-scheme: light;
            --page: #f4f7f4;
            --surface: #ffffff;
            --text: #1f2a24;
            --muted: #526158;
            --accent: #286443;
            --accent-soft: #e5f0e9;
            --border: #cad8cf;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            background: var(--page);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans",
                "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
            font-size: 16px;
            line-height: 1.75;
        }
        header, main, footer {
            width: min(100% - 32px, 760px);
            margin-inline: auto;
        }
        header { padding: 28px 0 12px; }
        nav {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        a {
            display: inline-flex;
            min-height: 44px;
            align-items: center;
            padding: 8px 12px;
            border-radius: 10px;
            color: var(--accent);
            font-weight: 650;
            text-underline-offset: 0.2em;
        }
        a:hover { background: var(--accent-soft); }
        a:focus-visible {
            outline: 3px solid var(--accent);
            outline-offset: 3px;
        }
        main { padding: 8px 0 32px; }
        h1 {
            margin: 16px 0 8px;
            font-size: clamp(1.75rem, 6vw, 2.35rem);
            line-height: 1.3;
            letter-spacing: -0.02em;
        }
        h2 {
            margin: 0 0 8px;
            font-size: 1.2rem;
            line-height: 1.45;
        }
        p { margin: 0 0 12px; }
        ul, ol { margin: 0; padding-left: 1.4rem; }
        li + li { margin-top: 8px; }
        .lead { color: var(--muted); }
        section {
            margin-top: 16px;
            padding: 20px;
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
        }
        .release-boundary {
            border-left: 5px solid var(--accent);
            background: var(--accent-soft);
        }
        footer {
            padding: 0 0 32px;
            color: var(--muted);
            font-size: 0.9rem;
        }
        @media (max-width: 520px) {
            header, main, footer { width: min(100% - 24px, 760px); }
            header { padding-top: 18px; }
            section { padding: 16px; }
        }
"""


def _static_page(*, title: str, description: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <link rel="icon" href="data:,">
    <title>{title} | 親の家 安全チェックAI</title>
    <style>{_PAGE_STYLES}</style>
</head>
<body>
    <header>
        <nav aria-label="公開情報">
            <a href="/">ホームへ戻る</a>
            <a href="/privacy">プライバシー</a>
            <a href="/support">サポート</a>
        </nav>
        <h1>{title}</h1>
        <p class="lead">{description}</p>
    </header>
    <main>{body}</main>
    <footer>親の家 安全チェックAI / SumaiGuard Agent</footer>
</body>
</html>
"""


PRIVACY_HTML = _static_page(
    title="プライバシーについて",
    description="写真を送る前に、処理先・保存範囲・公開上の制約をご確認ください。",
    body="""
        <section aria-labelledby="consent-heading">
            <h2 id="consent-heading">画像送信と同意</h2>
            <p>画像を送信するたびに、送信前に同意を確認します。写真には、住まいの内部や私物など、私的・機微な内容が写る可能性があります。不要な情報が写っていないか、送信前に確認してください。</p>
            <p>同意しない場合は、アップロード開始前にキャンセルしてください。これは送信の拒否または同意の撤回として扱われます。</p>
        </section>
        <section aria-labelledby="handling-heading">
            <h2 id="handling-heading">写真の処理とアプリ内の保存</h2>
            <ul>
                <li>画像受付時にEXIF（撮影日時や位置情報など）を削除します。</li>
                <li>写真は安全チェックのために一時的に処理されます。</li>
                <li>写真とPDFは、SumaiGuardアプリによって永続的に保存されません。</li>
                <li>構造化された解析結果の意味情報（検出項目、行動区分、説明文など）は、同一内容の重複処理を避けるため、設定されたTTLの範囲で、プロセス内メモリに短時間保持される場合があります。この一時メモには上限件数があり、画像は含まれません。</li>
                <li>一時メモはデータベース、アカウント、利用履歴として保存しません。プロセスの再起動やワーカー境界を越えて保持されません。</li>
                <li>ユーザー向けまたはアカウントに紐づく利用履歴はありません。</li>
                <li>トラッキング、広告、プロファイリングは行いません。</li>
            </ul>
        </section>
        <section aria-labelledby="processor-heading">
            <h2 id="processor-heading">第三者サービスでの処理</h2>
            <p>第三者サービスによる一時的な処理と、SumaiGuardアプリでの写真・PDFの非永続化および構造化された意味情報の短時間保持は、別の事項です。確認済みの処理基盤は次のとおりです。</p>
            <ul>
                <li>Google LLC の Gemini：写真に見える転倒・すべり・つまずきの注意箇所の抽出</li>
                <li>Firebase App Check と Apple's App Attest：正規アプリからの要求であることの検証</li>
                <li>Google Cloud Run：要求の受付と安全チェック処理の実行</li>
                <li>Cloud Logging：サービス運用に必要なログの取り扱い</li>
            </ul>
        </section>
        <section aria-labelledby="logging-heading">
            <h2 id="logging-heading">運用ログ</h2>
            <p>障害調査や不正利用対策のため、処理時刻、応答状態、処理時間などの運用上のリクエストメタデータがCloud Loggingに記録される場合があります。本サービスにはアカウントがないため、これらはユーザーアカウントに結び付けられません。これは写真そのものや構造化された解析結果とは区別されます。</p>
            <p>最終的に観測された保存期間はPhase 3の公開判定項目であり、実環境で確認できるまで公開できません。ここでは、未確認の保存期間を記載しません。</p>
        </section>
        <section aria-labelledby="inquiry-heading">
            <h2 id="inquiry-heading">サポート・削除に関する問い合わせ</h2>
            <p>本サービスはアカウントを作らず、写真とPDFを永続的に保存しません。構造化された意味情報は上限件数とTTLのあるプロセス内メモリに限られ、アカウント単位の利用履歴や削除機能はありません。運用上のリクエストメタデータは別に扱われます。サポート・削除に関する問い合わせの現在の案内は、<a href="/support">サポートページ</a>をご覧ください。</p>
        </section>
        <section aria-labelledby="boundary-heading">
            <h2 id="boundary-heading">専門判断との境界</h2>
            <p>本サービスは、写真1枚に見える範囲の一般的な安全上の注意を示すPOCです。医療・介護認定・保険・施工の判断、法令適合、正確な寸法、見積もりを代替しません。</p>
        </section>
        <section class="release-boundary" aria-labelledby="release-heading">
            <h2 id="release-heading">公開前に必要な連絡先</h2>
            <p>本Phase 1のソースには、公開済みのサポート用メールアドレスおよび連絡先となる運営者情報はありません。Phase 3では、確認済みの運営者連絡先が提供されるまで公開できません。</p>
        </section>
    """,
)


SUPPORT_HTML = _static_page(
    title="サポート",
    description="利用方法、うまく送信できない場合の確認事項、現在の問い合わせ境界をご案内します。",
    body="""
        <section aria-labelledby="start-heading">
            <h2 id="start-heading">利用する前に</h2>
            <p>アカウントなしで利用できます。公開版の写真解析はiPhoneアプリから利用し、画像を送るたびに内容を確認して同意してください。</p>
            <ol>
                <li><a href="/privacy">プライバシーについて</a>を確認します。</li>
                <li>JPEGまたはPNGの画像を用意します。ファイルは10 MiB以下にしてください。</li>
                <li>私物、書類、人物など不要な情報が写っていないことを確認してから送信します。</li>
            </ol>
        </section>
        <section aria-labelledby="trouble-heading">
            <h2 id="trouble-heading">送信・解析が完了しない場合</h2>
            <ul>
                <li>通信状態を確認し、アプリを開き直してから時間をおいて再試行してください。</li>
                <li>画像形式と10 MiB以下のファイルサイズをもう一度確認してください。</li>
                <li>送りたくない内容に気づいた場合は、送信前にキャンセルしてください。アップロード開始前であれば送信されません。</li>
                <li>繰り返し失敗する場合は、写真を連続送信せず、公開済みの連絡先が確認されるまで送信を中止してください。</li>
            </ul>
        </section>
        <section aria-labelledby="judgment-heading">
            <h2 id="judgment-heading">安全上の注意</h2>
            <p>写真に写っていない危険や、AIが見落とした危険がある可能性があります。本サービスは医療・介護認定・保険・施工の専門判断、法令適合、見積もりを代替しません。必要に応じて、ケアマネジャー、福祉用具専門相談員、施工の専門家へ相談してください。</p>
        </section>
        <section class="release-boundary" aria-labelledby="contact-heading">
            <h2 id="contact-heading">問い合わせ先に関する公開境界</h2>
            <p>本Phase 1のソースには、公開済みのサポート用メールアドレスおよび連絡先となる運営者情報はありません。サポートや削除に関する個別問い合わせを受け付けると約束できる連絡先も、現時点では掲載しません。</p>
            <p>Phase 3では、確認済みの運営者連絡先が提供されるまで公開できません。確認前にメールアドレス、運営者名、プロジェクトID、サービスURL、返信期限を推測して掲載することはありません。</p>
        </section>
    """,
)


__all__ = ["PRIVACY_HTML", "SUPPORT_HTML"]
