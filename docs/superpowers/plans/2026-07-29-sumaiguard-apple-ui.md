# SumaiGuard Apple-Inspired UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the existing Japanese SumaiGuard web flow with a calm Apple-inspired visual system, clearer safety-first copy, and accessible interactions without changing backend analysis or action-tier policy.

**Architecture:** Keep the existing FastAPI web application and its embedded `INDEX_HTML`. Add behavior-focused tests that request the real `/` route, then update only the HTML, CSS, and browser-side interaction code inside `apps/sumai_web/app.py`. Validate with the existing mock backend and the in-app browser at 390 x 844.

**Tech Stack:** Python 3.13, FastAPI, vanilla HTML/CSS/JavaScript, pytest, Pillow, in-app browser.

---

### Task 1: Add UI Contract Tests

**Files:**
- Create: `apps/sumai_agent/tests/test_web_ui_contract.py`
- Test: `apps/sumai_agent/tests/test_web_ui_contract.py`

- [ ] **Step 1: Write the failing tests**

Create a test helper that imports `apps/sumai_web/app.py`, serves `/` through
`TestClient`, and checks:

```python
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from fastapi.testclient import TestClient


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"


def _home_html() -> str:
    spec = importlib.util.spec_from_file_location("sumai_web_ui_contract", WEB_APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = TestClient(module.app).get("/")
    assert response.status_code == 200
    return response.text


def test_copy_keeps_the_product_safety_first() -> None:
    html = _home_html()
    assert "写真1枚で、親の家を安全チェック" in html
    assert "安全チェック結果" in html
    assert "次にできること" in html
    assert "診断結果" not in html
    assert "点検・修繕提案" not in html


def test_viewport_keeps_browser_zoom_available() -> None:
    html = _home_html()
    viewport = re.search(r'<meta name="viewport" content="([^"]+)">', html)
    assert viewport
    assert "maximum-scale" not in viewport.group(1)
    assert "user-scalable=no" not in viewport.group(1)


def test_accordion_headers_are_native_accessible_buttons() -> None:
    html = _home_html()
    assert html.count('class="accordion-card-header"') == 4
    assert html.count('aria-controls="accordion-') == 4
    assert 'aria-expanded="true"' in html
    assert html.count('aria-expanded="false"') == 3
    assert "header.setAttribute('aria-expanded', String(willOpen))" in html
    assert "content.hidden = !willOpen" in html


def test_ui_preserves_required_safety_content() -> None:
    html = _home_html()
    for text in (
        "家族で今日できること",
        "ケアマネ・福祉用具に相談",
        "専門施工・現地確認",
        "現在の注意箇所",
        "対策イメージ（施工図ではありません）",
        "写真は保存しません",
        "見える範囲のみ確認します",
    ):
        assert text in html


def test_interactive_controls_have_accessible_target_sizes() -> None:
    html = _home_html()
    assert "--control-min-height: 44px;" in html
    assert "min-height: var(--control-min-height);" in html
    assert ":focus-visible" in html
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest apps/sumai_agent/tests/test_web_ui_contract.py -v
```

Expected: all five tests fail because the approved copy, zoom contract, native
accordion buttons, trust copy, and shared control-size token do not yet exist.

- [ ] **Step 3: Commit the RED tests**

```bash
git add apps/sumai_agent/tests/test_web_ui_contract.py
git commit -m "test: define SumaiGuard UI refresh contract"
```

### Task 2: Implement The Apple-Inspired Visual System And Copy

**Files:**
- Modify: `apps/sumai_web/app.py`
- Test: `apps/sumai_agent/tests/test_web_ui_contract.py`

- [ ] **Step 1: Replace the visual tokens**

Update the embedded stylesheet to use this system:

```css
:root {
    --system-bg: #F5F5F7;
    --surface: #FFFFFF;
    --surface-muted: #F2F2F7;
    --text-primary: #1D1D1F;
    --text-secondary: #6E6E73;
    --separator: rgba(60, 60, 67, 0.16);
    --system-blue: #007AFF;
    --system-blue-pressed: #0062CC;
    --system-green: #248A3D;
    --system-orange: #C93400;
    --system-red: #D70015;
    --control-min-height: 44px;
    --card-radius: 20px;
    --control-radius: 14px;
    --page-shadow: 0 24px 64px rgba(0, 0, 0, 0.12);
}
```

Use the system Japanese font stack, opaque content surfaces, 16-17 px body
copy, 44 px controls, visible focus rings, and light/dark color-scheme
adaptation. Keep the two result images stacked.

- [ ] **Step 2: Update the three screen structures**

Apply the approved user-facing copy:

```html
<h1 class="home-title">写真1枚で、<br>親の家を安全チェック</h1>
<p class="home-lead">写真に写っている転倒・すべり・つまずきの注意箇所を確認します。</p>
<button id="btn-camera" class="btn btn-primary">カメラで撮る</button>
<button id="btn-library" class="btn btn-secondary">ライブラリから選ぶ</button>
```

Add an opaque trust card containing `写真は保存しません`,
`見える範囲のみ確認します`, and the existing professional-judgment
disclaimer. Rename result and action headings to `安全チェック結果` and
`次にできること`, and rename the image cards to `現在の注意箇所` and
`対策イメージ（施工図ではありません）`.

- [ ] **Step 3: Run the contract tests**

Run:

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest apps/sumai_agent/tests/test_web_ui_contract.py -v
```

Expected: copy, viewport, safety-content, and target-size tests pass; accordion
tests remain failing until Task 3.

### Task 3: Make The Action Tiers Accessible

**Files:**
- Modify: `apps/sumai_web/app.py`
- Test: `apps/sumai_agent/tests/test_web_ui_contract.py`

- [ ] **Step 1: Replace accordion headers with buttons**

Use the following structure for each tier:

```html
<button
    type="button"
    class="accordion-card-header"
    aria-expanded="true"
    aria-controls="accordion-family"
>
    <span class="accordion-card-title">家族で今日できること</span>
</button>
<div id="accordion-family" class="accordion-card-content">
    <div id="action-family-content" class="card-body markdown-body"></div>
</div>
```

The family card starts with `open` and `aria-expanded="true"`. The care,
contractor, and evidence cards start with `aria-expanded="false"` and their
content containers use the `hidden` attribute.

- [ ] **Step 2: Synchronize state in JavaScript**

Replace the click-only class toggle with:

```javascript
document.querySelectorAll('.accordion-card-header').forEach(header => {
    header.addEventListener('click', () => {
        const card = header.closest('.accordion-card');
        const contentId = header.getAttribute('aria-controls');
        const content = document.getElementById(contentId);
        const willOpen = header.getAttribute('aria-expanded') !== 'true';
        card.classList.toggle('open', willOpen);
        header.setAttribute('aria-expanded', String(willOpen));
        content.hidden = !willOpen;
    });
});
```

- [ ] **Step 3: Verify GREEN**

Run:

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest apps/sumai_agent/tests/test_web_ui_contract.py -v
```

Expected: five tests pass.

- [ ] **Step 4: Commit the implementation**

```bash
git add apps/sumai_web/app.py apps/sumai_agent/tests/test_web_ui_contract.py
git commit -m "feat: refresh SumaiGuard safety flow UI"
```

### Task 4: Regression And Browser Acceptance

**Files:**
- Verify: `apps/sumai_web/app.py`
- Verify: `apps/sumai_agent/tests/test_web_ui_contract.py`

- [ ] **Step 1: Run the full local suite**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh
```

Expected: 171 pytest tests pass, frontend import passes, and Compose config is
valid.

- [ ] **Step 2: Run the mock services**

```bash
MOCK_MODE=true /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8080

SUMAI_AGENT_URL=http://127.0.0.1:8080 MOCK_MODE=true SUMAI_WEB_PORT=8081 \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 app.py
```

- [ ] **Step 3: Verify the 390 x 844 flow**

Capture and inspect:

1. Home with readable trust card and one dominant blue action.
2. Result with `安全チェック結果`, both images, and an unclipped next action.
3. Actions with the family tier open by default.
4. Collapsed and expanded tier keyboard/focus behavior.

Confirm no horizontal scrolling, no disabled zoom, and no console errors.

- [ ] **Step 4: Review repository evidence**

```bash
git diff --check
git status --short --branch
git log --oneline --decorate -5
```

Expected: only the approved design, plan, UI implementation, and UI contract
test are present on `codex/sumaiguard-apple-ui`.
