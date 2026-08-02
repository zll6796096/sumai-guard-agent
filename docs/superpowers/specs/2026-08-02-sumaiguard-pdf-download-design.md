# SumaiGuard Safety Advice PDF Download Design

## Objective

Make the result-to-action transition easier to understand in Japanese and let
families save the displayed safety advice as a real PDF for later review or
sharing. The export must remain a cautious POC output, not a medical, care,
insurance, legal, construction, or quotation document.

## First-Principles Rule

Understanding and verifiable user value come before feature breadth. The new
copy must name the value of the next screen, and the PDF must help a family act
without making the one-photo analysis appear more authoritative than it is.

## Minimal Verifiable Deliverable

- Work on branch `codex/sumaiguard-pdf-download`.
- Rename the result-screen CTA from `次にできることを見る` to
  `安全のための対策を見る`.
- Rename the action-screen title from `次にできること` to
  `安全のためにできること`.
- Add `この内容をPDFで保存` on the action screen.
- Return a downloadable Japanese PDF generated in memory from the current
  result payload.
- Include the safety boundary and uncertainty disclaimer in every PDF.
- Preserve the existing three deterministic action tiers and mock mode.

## User Experience

### Result Screen

The primary action reads `安全のための対策を見る`. This names the purpose of
the destination instead of requiring the user to interpret the abstract word
`次`.

### Action Screen

The screen title reads `安全のためにできること`. The existing three accordion
cards remain unchanged and the family/no-cost tier remains open by default.

A secondary full-width button labeled `この内容をPDFで保存` appears after the
action cards and before `ホームに戻る`. While generating the file, the button is
disabled and reads `PDFを作成中…`. Failure is announced in a Japanese live
region without removing the on-screen advice. A successful response downloads
`sumai-guard-safety-actions-YYYYMMDD.pdf`.

## PDF Content

The PDF contains text only:

1. `親の家 安全チェックAI` and `安全のためにできること`.
2. Generation date in Japan time.
3. Visible finding count and the displayed overall-risk label.
4. The exact current content of the three required action tiers:
   `家族で今日できること`, `ケアマネ・福祉用具に相談`, and
   `専門施工・現地確認`.
5. `詳しいリスク根拠`.
6. A visually distinct disclaimer block.

The PDF does not contain the uploaded photo, annotated image, improvement
image, filename, analysis identifier, provider/model name, debug information,
or other personal metadata.

The disclaimer must communicate all of the following in cautious Japanese:

- The output is based only on what can be seen in one photo and may miss risks.
- It is general safety guidance and a consultation aid.
- It does not replace medical, care-level, insurance, legal-compliance,
  construction-feasibility, estimate, or on-site professional judgment.
- The actual site must be checked and the appropriate professional consulted
  when needed.
- The POC does not store the photo or the generated PDF.

## Architecture And Data Flow

The browser keeps the latest successful analysis payload in memory. Clicking
the PDF button posts only the report fields required above to a new web-service
endpoint. Image fields and debug identifiers are excluded before the request is
created.

The endpoint validates bounded text fields, converts the existing Markdown
subset into safe report paragraphs and lists, and builds the PDF in an
`io.BytesIO` buffer using ReportLab 5.x. Japanese text uses ReportLab's
documented `UnicodeCIDFont('HeiseiKakuGo-W5')` support so generation does not
depend on a user-specific font path. The response uses `application/pdf` and an
attachment `Content-Disposition`. The buffer is discarded after the response;
no file, database row, account history, or server-side report cache is created.

HTML is not accepted or rendered by the PDF endpoint. Markdown markers are
parsed as plain headings/list structure, and user-controlled text is escaped
before it reaches ReportLab paragraph markup.

## Error Handling And Guardrails

- The PDF button is unavailable until a successful applicable analysis exists.
- The request schema rejects missing report sections, invalid risk labels, and
  oversized text with a client-safe `422` response.
- PDF generation failures return a generic Japanese error and do not expose
  report contents, filesystem paths, or exception details.
- The UI restores the button after success or failure and keeps the advice
  visible.
- Only one PDF request is allowed per click; repeated clicks while pending are
  ignored.
- Existing photo non-persistence, EXIF stripping, mock mode, and deterministic
  tier routing remain unchanged.

## Files Likely To Change

- `apps/sumai_web/app.py`: CTA/title copy, PDF button and state handling,
  validated PDF endpoint, and in-memory renderer integration.
- `apps/sumai_web/requirements.txt`: bounded ReportLab 5.x dependency.
- `apps/sumai_agent/tests/test_web_ui_contract.py`: copy, accessibility, and
  client request-contract assertions.
- `apps/sumai_agent/tests/test_pdf_download.py`: endpoint, headers, content,
  input bounds, and disclaimer tests.
- `AGENTS.md`: replace the PDF-wide prohibition with the narrowly approved
  text-only, disclaimer, and non-persistence guardrail.
- `README.md` and `docs/risk_gap_analysis.md`: reflect the implemented,
  constrained export and its limitations.

No other file will be modified unless a verification failure proves it is
required for this scope.

## Explicitly Out Of Scope

- Photos or generated images inside the PDF.
- PDF history, accounts, authentication, cloud storage, email, or sharing
  integrations.
- Medical, care-level, insurance, legal, subsidy, construction, measurement,
  quotation, product, brand, or contractor conclusions.
- Gemini prompts, provider selection, risk extraction, ontology, deterministic
  action-tier mapping, or report-source changes.
- Cloud deployment or production release.
- General frontend refactoring or a framework migration.

## Risks And Mitigations

- **Formal-report misinterpretation:** keep the POC label and full disclaimer
  prominent; exclude photos, branding claims, approval language, signatures,
  and professional-report styling.
- **Privacy leakage:** send and render text-only allowlisted fields; never include
  image data, filenames, IDs, provider metadata, or debug state.
- **Japanese glyph or wrapping failure:** use documented Japanese CID-font
  support and verify both extracted text and rendered pages.
- **Markdown injection or malformed layout:** support only headings, paragraphs,
  and list items; escape all content and enforce length limits.
- **Mobile download failure:** use an actual PDF attachment response and a Blob
  download path, then verify the complete flow at 390 x 844.
- **Regression in the single-file frontend:** add contract tests first and run
  the full repository gate plus browser acceptance.

## Acceptance Criteria

- The result CTA reads `安全のための対策を見る`; the old CTA phrase is absent.
- The action screen is titled `安全のためにできること`.
- `この内容をPDFで保存` is keyboard accessible, has at least a 44 px target,
  and exposes pending/failure state accessibly.
- An applicable completed result can download a filename ending in `.pdf`.
- The response is `application/pdf`, has attachment disposition, and begins
  with a valid PDF signature.
- The PDF opens, renders Japanese without missing glyphs or clipping, and
  contains all three action tiers, risk basis, generation date, and every
  required disclaimer concept.
- The PDF contains no image objects or excluded metadata.
- Invalid or oversized requests fail safely without creating a file.
- Existing health, mock analysis, deterministic policy, visual rendering,
  report rendering, and UI-contract tests remain green.
- The 390 x 844 mock flow has no horizontal overflow or clipped primary action,
  and the PDF download request succeeds from the rendered action screen.
- Git diff contains only the approved scope; unrelated untracked
  `docs/preconsultation/` remains untouched.

## Verification Commands

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest \
  apps/sumai_agent/tests/test_pdf_download.py \
  apps/sumai_agent/tests/test_web_ui_contract.py -v

PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh

docker compose build sumai-web
docker compose config
git diff --check
git diff --stat origin/main...HEAD
git status --short --branch
```

Browser acceptance at 390 x 844 must additionally verify the full mock upload,
result, action, PDF download, error-free console, and lack of horizontal
overflow. The downloaded artifact must be parsed and rendered for inspection;
an HTTP 200 response alone is not PDF acceptance evidence.
