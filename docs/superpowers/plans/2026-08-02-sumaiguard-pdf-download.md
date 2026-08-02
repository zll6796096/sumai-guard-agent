# SumaiGuard Safety Advice PDF Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ambiguous next-step copy and add a privacy-bounded, disclaimer-complete Japanese PDF download for the current safety advice.

**Architecture:** Keep the existing embedded FastAPI HTML/CSS/vanilla-JavaScript frontend and add one validated `POST /suggestions.pdf` endpoint in `apps/sumai_web/app.py`. The browser sends only allowlisted text report fields; ReportLab generates a text-only PDF in `io.BytesIO`, and the response is downloaded as a Blob without persisting the photo or PDF.

**Tech Stack:** Python 3.12/3.13, FastAPI, Pydantic 2, ReportLab 5, pypdf 6, embedded HTML/CSS, vanilla JavaScript, pytest, Docker Compose.

---

## File Map

- Modify `apps/sumai_web/app.py`: request model, Markdown-to-PDF renderer,
  endpoint, clearer Japanese copy, PDF button, and download state handling.
- Modify `apps/sumai_web/requirements.txt`: explicit Pydantic, ReportLab, and
  pypdf bounds used by runtime validation/generation and PDF acceptance tests.
- Create `apps/sumai_agent/tests/test_pdf_download.py`: endpoint, Japanese text,
  disclaimer, privacy, schema-bound, and failure-contract coverage.
- Modify `apps/sumai_agent/tests/test_web_ui_contract.py`: copy, control,
  accessibility, and allowlisted-payload contracts.
- Modify `AGENTS.md`: replace the PDF-wide prohibition with the specifically
  approved constrained-export guardrail.
- Modify `README.md`: document the available text-only PDF and its limits.
- Modify `docs/risk_gap_analysis.md`: replace the obsolete “not implemented”
  finding with the remaining interpretation/privacy limit.

## Task 1: PDF Endpoint Contract And Renderer

**Files:**
- Create: `apps/sumai_agent/tests/test_pdf_download.py`
- Modify: `apps/sumai_web/app.py`
- Modify: `apps/sumai_web/requirements.txt`

- [ ] **Step 1: Add the PDF dependencies**

Append these explicit compatible ranges to
`apps/sumai_web/requirements.txt`:

```text
pydantic>=2.7,<3.0
reportlab>=5.0,<6.0
pypdf>=6.14,<7.0
```

Install both application requirement sets into the Python 3.13 environment:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pip install \
  -r apps/sumai_agent/requirements.txt \
  -r apps/sumai_web/requirements.txt
```

Expected: exit 0 with ReportLab 5.x and pypdf 6.x installed.

- [ ] **Step 2: Write the failing endpoint and content tests**

Create `apps/sumai_agent/tests/test_pdf_download.py` with a local app loader,
an allowlisted sample request, and these behaviors:

```python
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"


def _load_web_module():
    spec = importlib.util.spec_from_file_location("sumai_web_pdf_contract", WEB_APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, object]:
    return {
        "finding_count": 2,
        "overall_risk_level": "medium",
        "family_actions_markdown": "## 家族で今日できること\n- 通路の物を移動する",
        "care_manager_actions_markdown": "## ケアマネ・福祉用具に相談\n- 手すりを相談する",
        "contractor_actions_markdown": "## 専門施工・現地確認\n- 現地確認を依頼する",
        "risk_summary_markdown": "## 詳しいリスク根拠\n床の物につまずく可能性があります。",
    }


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_download_returns_a_text_only_japanese_attachment() -> None:
    module = _load_web_module()
    response = TestClient(module.app).post("/suggestions.pdf", json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert "sumai-guard-safety-actions-" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(response.content))
    text = _pdf_text(response.content)
    for expected in (
        "安全のためにできること",
        "家族で今日できること",
        "ケアマネ・福祉用具に相談",
        "専門施工・現地確認",
        "詳しいリスク根拠",
        "写真1枚に写っている範囲",
        "医療・介護認定・保険・法令適合・施工可否・見積もり",
        "写真やPDFは保存しません",
    ):
        assert expected in text

    for page in reader.pages:
        xobjects = page.get("/Resources", {}).get("/XObject", {})
        assert all(obj.get_object().get("/Subtype") != "/Image" for obj in xobjects.values())


def test_pdf_download_forbids_image_and_debug_fields() -> None:
    module = _load_web_module()
    payload = _payload() | {"annotated_image_base64": "secret", "analysis_id": "private"}
    response = TestClient(module.app).post("/suggestions.pdf", json=payload)
    assert response.status_code == 422


def test_pdf_download_rejects_oversized_report_text() -> None:
    module = _load_web_module()
    payload = _payload() | {"risk_summary_markdown": "危険" * 10_001}
    response = TestClient(module.app).post("/suggestions.pdf", json=payload)
    assert response.status_code == 422


def test_pdf_generation_failure_is_generic_and_does_not_echo_content(monkeypatch) -> None:
    module = _load_web_module()
    monkeypatch.setattr(module, "build_safety_advice_pdf", lambda _report: (_ for _ in ()).throw(RuntimeError("secret path")))
    response = TestClient(module.app).post("/suggestions.pdf", json=_payload())
    assert response.status_code == 500
    assert response.json() == {
        "error": "pdf_generation_failed",
        "message": "PDFを作成できませんでした。時間をおいて、もう一度お試しください。",
    }
    assert "secret path" not in response.text
```

- [ ] **Step 3: Run the focused test and verify the RED state**

Run:

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest apps/sumai_agent/tests/test_pdf_download.py -v
```

Expected: FAIL because `POST /suggestions.pdf` returns `404 Not Found`.

- [ ] **Step 4: Add the validated request model and Japanese renderer**

In `apps/sumai_web/app.py`, add imports for `re`, `datetime`, `html.escape`,
`zoneinfo.ZoneInfo`, Pydantic, FastAPI `Response`, and ReportLab. Define:

```python
PDF_DISCLAIMER = (
    "このPDFは、写真1枚に写っている範囲だけをもとにした一般的な安全上の注意と相談の目安です。"
    "写真に写っていない危険や、AIが見落とした危険がある可能性があります。\n"
    "医療・介護認定・保険・法令適合・施工可否・見積もり、その他の専門判断を行うものではありません。"
    "実際の状況を現地で確認し、必要に応じてケアマネジャー、福祉用具専門相談員、施工の専門家へ相談してください。\n"
    "このPOCは、アップロードした写真や生成したPDFを保存しません。"
)


class SuggestionPdfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_count: int = Field(ge=0, le=100)
    overall_risk_level: Literal["low", "medium", "high"]
    family_actions_markdown: str = Field(min_length=1, max_length=20_000)
    care_manager_actions_markdown: str = Field(min_length=1, max_length=20_000)
    contractor_actions_markdown: str = Field(min_length=1, max_length=20_000)
    risk_summary_markdown: str = Field(min_length=1, max_length=20_000)
```

Register `UnicodeCIDFont("HeiseiKakuGo-W5")`. Implement
`build_safety_advice_pdf(report: SuggestionPdfRequest) -> bytes` with
`SimpleDocTemplate`, `Paragraph`, and `Spacer`. Convert only Markdown headings,
plain paragraphs, and `-`/`*` list items; escape every string with
`html.escape()` before passing it to `Paragraph`. Use `A4`, 18 mm margins,
Japan-time generation date, the risk labels `低・中・高`, and a pale bordered
disclaimer table. Build into `io.BytesIO` and return `buffer.getvalue()`.

The Markdown conversion must follow this concrete shape:

```python
def _markdown_flowables(markdown: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    flowables: list[Flowable] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flowables.append(Spacer(1, 4))
        elif line.startswith("### "):
            flowables.append(Paragraph(escape(line[4:]), styles["subheading"]))
        elif line.startswith("## "):
            flowables.append(Paragraph(escape(line[3:]), styles["heading"]))
        elif re.match(r"^[-*]\s+", line):
            flowables.append(Paragraph("・" + escape(re.sub(r"^[-*]\s+", "", line)), styles["body"]))
        else:
            flowables.append(Paragraph(escape(line), styles["body"]))
    return flowables
```

- [ ] **Step 5: Add the in-memory attachment endpoint**

Add this behavior beside the existing readiness and analysis endpoints:

```python
@app.post("/suggestions.pdf")
def download_suggestions_pdf(report: SuggestionPdfRequest):
    try:
        content = build_safety_advice_pdf(report)
    except Exception as exc:
        logger.error("pdf_generation_failed", extra={"failure_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={
                "error": "pdf_generation_failed",
                "message": "PDFを作成できませんでした。時間をおいて、もう一度お試しください。",
            },
        )

    generated = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="sumai-guard-safety-actions-{generated}.pdf"',
            "Cache-Control": "no-store",
        },
    )
```

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run the same focused pytest command from Step 3.

Expected: all tests in `test_pdf_download.py` PASS; Japanese text extraction
works and no page contains an image XObject.

- [ ] **Step 7: Commit the endpoint slice**

```bash
git add -- \
  apps/sumai_web/app.py \
  apps/sumai_web/requirements.txt \
  apps/sumai_agent/tests/test_pdf_download.py
git diff --cached --check
git commit -m "feat: add bounded safety advice PDF endpoint"
```

## Task 2: Clearer Copy And Accessible Download Interaction

**Files:**
- Modify: `apps/sumai_agent/tests/test_web_ui_contract.py`
- Modify: `apps/sumai_web/app.py`

- [ ] **Step 1: Write failing UI contract tests**

Extend `test_copy_keeps_the_product_safety_first` and add a dedicated test:

```python
def test_copy_keeps_the_product_safety_first() -> None:
    html = _home_html()
    assert "写真1枚で、親の家を安全チェック" in html
    assert "安全チェック結果" in html
    assert "安全のための対策を見る" in html
    assert "安全のためにできること" in html
    assert "次にできることを見る" not in html
    assert "診断結果" not in html
    assert "点検・修繕提案" not in html


def test_pdf_download_control_is_accessible_and_text_only() -> None:
    html = _home_html()
    assert 'id="btn-download-pdf"' in html
    assert "この内容をPDFで保存" in html
    assert 'id="pdf-download-error"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert "latestReportPayload" in html
    assert "family_actions_markdown" in html
    assert "care_manager_actions_markdown" in html
    assert "contractor_actions_markdown" in html
    assert "risk_summary_markdown" in html
    assert "annotated_image_base64:" not in html
    assert "improvement_image_base64:" not in html
    assert "fetch('/suggestions.pdf'" in html
```

- [ ] **Step 2: Run the UI contract tests and verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest apps/sumai_agent/tests/test_web_ui_contract.py -v
```

Expected: FAIL on missing `安全のための対策を見る` and missing
`btn-download-pdf`.

- [ ] **Step 3: Implement the copy, control, and live region**

In the result screen, change only the primary CTA text to
`安全のための対策を見る`. In the action screen, change both the navigation title
and `h1` to `安全のためにできること`.

Insert before the home button:

```html
<button id="btn-download-pdf" class="btn btn-secondary" type="button" disabled>
    この内容をPDFで保存
</button>
<p id="pdf-download-error" class="download-error" role="alert" aria-live="assertive" hidden></p>
```

Add `.download-error` styling using the existing danger color, 0.9rem minimum
font size, left alignment, and an 8 px top margin. Existing `.btn` rules already
provide the 44 px minimum target.

- [ ] **Step 4: Implement the allowlisted Blob download flow**

Add `let latestReportPayload = null;`. In `renderResults`, set it to `null` for
not-applicable results. For applicable results, assign exactly:

```javascript
latestReportPayload = {
    finding_count: count,
    overall_risk_level: overallRisk,
    family_actions_markdown: payload.family_actions_markdown || '',
    care_manager_actions_markdown: payload.care_manager_actions_markdown || '',
    contractor_actions_markdown: payload.contractor_actions_markdown || '',
    risk_summary_markdown: payload.risk_summary_markdown || ''
};
pdfDownloadButton.disabled = false;
```

Implement the click handler with one pending request, a generic Japanese error,
and guaranteed restoration:

```javascript
async function downloadSuggestionsPdf() {
    if (!latestReportPayload || pdfDownloadButton.disabled) return;
    const originalLabel = pdfDownloadButton.textContent;
    pdfDownloadButton.disabled = true;
    pdfDownloadButton.textContent = 'PDFを作成中…';
    pdfDownloadError.hidden = true;
    pdfDownloadError.textContent = '';

    try {
        const response = await fetch('/suggestions.pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(latestReportPayload)
        });
        if (!response.ok) throw new Error('pdf_download_failed');
        const blob = await response.blob();
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="([A-Za-z0-9._-]+)"/);
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = match ? match[1] : 'sumai-guard-safety-actions.pdf';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (_error) {
        pdfDownloadError.textContent = 'PDFを保存できませんでした。時間をおいて、もう一度お試しください。';
        pdfDownloadError.hidden = false;
    } finally {
        pdfDownloadButton.textContent = originalLabel;
        pdfDownloadButton.disabled = latestReportPayload === null;
    }
}
```

Reset `latestReportPayload`, disable the button, and clear the error in
`resetApp`. Register one `click` listener on `pdfDownloadButton`.

- [ ] **Step 5: Run UI and PDF tests and verify GREEN**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest \
  apps/sumai_agent/tests/test_web_ui_contract.py \
  apps/sumai_agent/tests/test_pdf_download.py -v
```

Expected: all focused UI and PDF tests PASS.

- [ ] **Step 6: Commit the browser interaction slice**

```bash
git add -- apps/sumai_web/app.py apps/sumai_agent/tests/test_web_ui_contract.py
git diff --cached --check
git commit -m "feat: add safety advice PDF download control"
```

## Task 3: Policy And User Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/risk_gap_analysis.md`
- Test: `apps/sumai_agent/tests/test_documentation_contract.py`

- [ ] **Step 1: Write the failing documentation contract**

Add this test to `apps/sumai_agent/tests/test_documentation_contract.py`:

```python
def test_pdf_export_policy_is_text_only_disclaimed_and_nonpersistent() -> None:
    root = Path(__file__).resolve().parents[3]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "PDF report download" not in agents
    assert "PDF report download" not in readme
    for phrase in ("text-only PDF", "disclaimer", "must not persist"):
        assert phrase in agents
    for phrase in ("Japanese text-only PDF", "does not include photos", "not stored"):
        assert phrase in readme
```

- [ ] **Step 2: Run the documentation test and verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest \
  apps/sumai_agent/tests/test_documentation_contract.py::test_pdf_export_policy_is_text_only_disclaimed_and_nonpersistent -v
```

Expected: FAIL because the existing documents still say PDF download is
forbidden or not implemented.

- [ ] **Step 3: Update the policy and public documentation**

In `AGENTS.md`, remove only `- PDF report download.` from forbidden scope creep
and add under Engineering Rules:

```text
- PDF export is limited to a text-only copy of the current action advice and risk basis.
- Every PDF must include the approved POC/professional-judgment disclaimer, must not include photos or debug metadata, and must not persist the PDF.
```

In `README.md`, add the feature bullet `Japanese text-only PDF export of the
current safety advice` and state under limitations that the PDF `does not
include photos, is not stored, and is not a professional inspection,
medical/care, insurance, legal, construction, or quotation document.` Remove
the two obsolete `No PDF report download` bullets.

In `docs/risk_gap_analysis.md`, replace the obsolete row with a low-severity row
that states the text-only PDF is now available but may still be mistaken for a
formal report; list the disclaimer, no-photo, and no-persistence controls and
retain expert/on-site confirmation as the mitigation.

- [ ] **Step 4: Run the documentation and focused feature tests**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest \
  apps/sumai_agent/tests/test_documentation_contract.py \
  apps/sumai_agent/tests/test_web_ui_contract.py \
  apps/sumai_agent/tests/test_pdf_download.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the policy slice**

```bash
git add -- \
  AGENTS.md \
  README.md \
  docs/risk_gap_analysis.md \
  apps/sumai_agent/tests/test_documentation_contract.py
git diff --cached --check
git commit -m "docs: define bounded safety PDF policy"
```

## Task 4: Rendered PDF, Browser, And Full Regression Acceptance

**Files:**
- Inspect: generated PDF artifact in a temporary directory
- Inspect: rendered PDF pages in a temporary directory
- Inspect: mobile browser at 390 x 844
- Review: all branch changes relative to `origin/main`

- [ ] **Step 1: Read the PDF skill and load workspace PDF dependencies**

Read the complete PDF skill before generating or inspecting an artifact, then
load the bundled workspace dependency paths. Use its prescribed parser and
renderer rather than treating HTTP success as document acceptance.

- [ ] **Step 2: Run the full repository gate**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh
```

Expected: all pytest tests PASS, frontend import reports `frontend import ok`,
and Docker Compose reports `docker compose config ok`.

- [ ] **Step 3: Build the web container**

```bash
docker compose build sumai-web
docker compose config > /dev/null
```

Expected: the image builds with ReportLab 5.x and exits 0; Compose remains
valid.

- [ ] **Step 4: Generate, parse, and render a representative PDF**

Create a task-specific temporary directory with `mktemp -d`. Use FastAPI's
`TestClient` and the same allowlisted sample request from Task 1 to save one PDF
there. Assert the response headers, parse all page text with pypdf, and render
every page to PNG using the PDF skill's renderer. Inspect every PNG for Japanese
glyphs, clipping, empty pages, overlapping text, and disclaimer visibility.

Expected: valid non-empty PDF, all required text present, zero image XObjects,
and every page visually readable.

- [ ] **Step 5: Run the complete mobile mock flow in a real browser**

Start the local backend and frontend in mock mode on verified unused ports.
At 390 x 844, upload a repository sample image, wait for `安全チェック結果`,
select `安全のための対策を見る`, verify `安全のためにできること`, click
`この内容をPDFで保存`, and confirm the request returns a PDF attachment.
Verify:

- `document.documentElement.scrollWidth === 390`.
- The PDF button is at least 44 px high and is not clipped.
- Pending label and disabled state appear while the request is active.
- Accordion accessibility state still matches `hidden` content.
- Browser console contains no error or warning.

- [ ] **Step 6: Review branch scope and workspace state**

```bash
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- \
  AGENTS.md README.md docs/risk_gap_analysis.md \
  apps/sumai_web/app.py apps/sumai_web/requirements.txt \
  apps/sumai_agent/tests/test_pdf_download.py \
  apps/sumai_agent/tests/test_web_ui_contract.py \
  apps/sumai_agent/tests/test_documentation_contract.py \
  docs/superpowers/specs/2026-08-02-sumaiguard-pdf-download-design.md \
  docs/superpowers/plans/2026-08-02-sumaiguard-pdf-download.md
git status --short --branch
```

Expected: only approved files differ; `docs/preconsultation/` remains untracked
and untouched; no staged files remain.

- [ ] **Step 7: Commit any acceptance-only correction with explicit paths**

If browser or rendered-PDF acceptance required a scoped correction, stage only
the named modified implementation/test files, run the focused tests again, and
commit:

```bash
git commit -m "fix: complete safety PDF acceptance"
```

If no correction was required, do not create an empty commit.
