# Truthful Analysis Waiting Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved B1 waiting experience: real processing-stage events, an indeterminate activity bar, a calm photo scan animation, and local rotating safety tips without extra Gemini calls or polling.

**Architecture:** Add an NDJSON streaming endpoint to both Agent and Web while preserving the existing synchronous `/analyze` APIs. `AnalysisOrchestrator` emits three truthful stage boundaries through an optional callback; the browser reads the single response stream and runs all animation and tip rotation locally.

**Tech Stack:** Python 3.13, FastAPI `StreamingResponse`, asyncio, httpx streaming, pytest, vanilla JavaScript, CSS media queries.

**Branch:** `codex/sumaiguard-analysis-waiting-experience`

**Dependency:** Create only after `codex/sumaiguard-visible-risk-policy` passes its full gate and independent review. This is a stacked branch and includes all visible-risk commits.

---

## File Responsibility Map

- `apps/sumai_agent/app/services/orchestrator.py`: emit request-local stage callbacks at real boundaries.
- `apps/sumai_agent/app/services/analysis_stream.py`: encode safe NDJSON progress, result, and error events.
- `apps/sumai_agent/app/main.py`: expose Agent `/analyze/stream` while preserving `/analyze`.
- `apps/sumai_web/app.py`: stream proxy plus B1 HTML, CSS, and JavaScript.
- `apps/sumai_agent/tests/test_streaming_analysis.py`: Agent event order, result, cache, and error behavior.
- `apps/sumai_agent/tests/test_web_streaming.py`: Web proxy streaming and safe failure behavior.
- `apps/sumai_agent/tests/test_frontend_contract.py`: no fake timers/percentages; local tips and reduced motion.
- `docs/{architecture,decisions}.md`: stream and resource boundary.

### Task 1: Create the Stacked Branch and Prove Its Base

**Files:**
- No source changes.

- [ ] **Step 1: Verify the visible-risk branch is clean and reviewed**

```bash
git -C /Users/zhanglonglong/Projects/apps/sumai-guard-agent/.worktrees/codex-sumaiguard-visible-risk-policy \
  status --short --branch
git -C /Users/zhanglonglong/Projects/apps/sumai-guard-agent/.worktrees/codex-sumaiguard-visible-risk-policy \
  log -1 --oneline
```

Expected: no working-tree changes and HEAD is the reviewed visible-risk commit.

- [ ] **Step 2: Create the waiting-experience worktree**

```bash
git -C /Users/zhanglonglong/Projects/apps/sumai-guard-agent \
  worktree add \
  /Users/zhanglonglong/Projects/apps/sumai-guard-agent/.worktrees/codex-sumaiguard-analysis-waiting-experience \
  -b codex/sumaiguard-analysis-waiting-experience \
  codex/sumaiguard-visible-risk-policy
```

Expected: the new branch HEAD equals the visible-risk branch HEAD.

- [ ] **Step 3: Run the inherited baseline**

```bash
cd /Users/zhanglonglong/Projects/apps/sumai-guard-agent/.worktrees/codex-sumaiguard-analysis-waiting-experience
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh
```

Expected: all tests PASS, frontend import succeeds, and compose config validates.

### Task 2: Emit Real Request-Local Progress From the Orchestrator

**Files:**
- Create: `apps/sumai_agent/tests/test_streaming_analysis.py`
- Modify: `apps/sumai_agent/app/services/orchestrator.py`

- [ ] **Step 1: Write failing callback tests**

Define the real upload and deterministic provider fixtures at the top of the new test
file:

```python
import io
from collections.abc import Callable

import pytest
from fastapi import UploadFile
from PIL import Image

from app.models import VisionFacts


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class DeterministicVision:
    async def analyze(self, **_: object) -> tuple[VisionFacts, str]:
        return (
            VisionFacts(
                environment="home",
                room_type="toilet",
                visible_regions=["room"],
                entities=[],
                feature_observations=[],
                relationships=[],
            ),
            "gemini",
        )

    async def aclose(self) -> None:
        return None


@pytest.fixture
def upload_factory() -> Callable[[], UploadFile]:
    return lambda: UploadFile(
        filename="toilet.png",
        file=io.BytesIO(_png_bytes()),
    )


@pytest.mark.asyncio
async def test_orchestrator_emits_real_stages_in_order(
    upload_factory,
) -> None:
    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    response = await AnalysisOrchestrator(
        vision=DeterministicVision()
    ).analyze(
        upload=upload_factory(),
        room_hint="toilet",
        mock=False,
        progress=progress,
    )

    assert response.room_type == "toilet"
    assert stages == ["intake_complete", "vision_complete"]
```

Add cache behavior:

```python
@pytest.mark.asyncio
async def test_cache_hit_still_reports_intake_and_semantic_readiness(
    upload_factory,
) -> None:
    orchestrator = AnalysisOrchestrator(vision=DeterministicVision())
    await orchestrator.analyze(
        upload=upload_factory(), room_hint="toilet", progress=None
    )
    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    response = await orchestrator.analyze(
        upload=upload_factory(), room_hint="toilet", progress=progress
    )

    assert response._cache_hit is True
    assert stages == ["intake_complete", "vision_complete"]
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_streaming_analysis.py -q
```

Expected: FAIL because `AnalysisOrchestrator.analyze` has no `progress` parameter.

- [ ] **Step 3: Add the typed callback**

In `orchestrator.py`:

```python
from collections.abc import Awaitable, Callable

ProgressCallback = Callable[[str], Awaitable[None]]


async def _emit_progress(
    callback: ProgressCallback | None,
    stage: str,
) -> None:
    if callback is not None:
        await callback(stage)
```

Change the signature:

```python
async def analyze(
    self,
    upload: UploadFile,
    room_hint: str = "auto",
    mock: bool = False,
    progress: ProgressCallback | None = None,
) -> AnalysisResponse:
```

Emit immediately after sanitized intake:

```python
image, safe_png, pixel_digest = await asyncio.to_thread(
    _prepare_image, raw_bytes
)
await _emit_progress(progress, "intake_complete")
```

Inside the memo factory, emit after `self.vision.analyze` completes:

```python
vision_facts, mode = await self.vision.analyze(...)
await _emit_progress(progress, "vision_complete")
```

After `get_or_compute`, emit `vision_complete` only for cache hits or coalesced
followers where `factory_ran[0]` is false:

```python
if not factory_ran[0]:
    await _emit_progress(progress, "vision_complete")
```

- [ ] **Step 4: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/tests/test_streaming_analysis.py
git commit -m "feat: emit truthful analysis stages"
```

### Task 3: Add the Agent NDJSON Stream

**Files:**
- Modify: `apps/sumai_agent/tests/test_streaming_analysis.py`
- Create: `apps/sumai_agent/app/services/analysis_stream.py`
- Modify: `apps/sumai_agent/app/main.py`

- [ ] **Step 1: Add failing event-order and safe-error tests**

```python
def test_agent_stream_emits_progress_then_result(client) -> None:
    with client.stream(
        "POST",
        "/analyze/stream",
        files={"image": ("toilet.png", _png_bytes(), "image/png")},
        data={"room_hint": "toilet", "mock": "true"},
    ) as response:
        events = [
            json.loads(line)
            for line in response.iter_lines()
            if line.strip()
        ]

    assert response.status_code == 200
    assert [event["type"] for event in events] == [
        "progress", "progress", "result"
    ]
    assert [event.get("stage") for event in events[:2]] == [
        "intake_complete", "vision_complete"
    ]
    AnalysisResponse.model_validate(events[-1]["payload"])
```

```python
def test_agent_stream_sanitizes_provider_failure(
    client, monkeypatch
) -> None:
    from app import main as main_module
    from app.errors import GeminiUnavailableError

    async def fail_analysis(**_: object):
        raise GeminiUnavailableError("provider-secret-body")

    monkeypatch.setattr(
        main_module.orchestrator,
        "analyze",
        fail_analysis,
    )
    with client.stream(
        "POST",
        "/analyze/stream",
        files={
            "image": (
                "toilet.png",
                _png_bytes(),
                "image/png",
            )
        },
        data={"room_hint": "toilet", "mock": "false"},
    ) as response:
        events = [
            json.loads(line)
            for line in response.iter_lines()
            if line.strip()
        ]

    assert events == [{
        "type": "error",
        "error": "gemini_unavailable",
        "message": "解析サービスは現在利用できません。",
    }]
    assert "api" not in json.dumps(events).lower()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_streaming_analysis.py -q
```

Expected: FAIL with HTTP 404 for `/analyze/stream`.

- [ ] **Step 3: Implement the NDJSON event generator**

Create `analysis_stream.py`:

```python
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import UploadFile

from app.errors import GeminiUnavailableError
from app.services.orchestrator import AnalysisOrchestrator

_END = object()


def _line(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


async def stream_analysis(
    orchestrator: AnalysisOrchestrator,
    upload: UploadFile,
    room_hint: str,
    mock: bool,
) -> AsyncIterator[bytes]:
    queue: asyncio.Queue[bytes | object] = asyncio.Queue()

    async def progress(stage: str) -> None:
        await queue.put(_line({"type": "progress", "stage": stage}))

    async def run() -> None:
        try:
            response = await orchestrator.analyze(
                upload=upload,
                room_hint=room_hint,
                mock=mock,
                progress=progress,
            )
            serialize_started = time.monotonic()
            payload = response.model_dump(mode="json")
            timings = payload["stage_timings_ms"]
            timings["serialize"] = max(
                0,
                int((time.monotonic() - serialize_started) * 1000),
            )
            timings["total"] = sum(
                value
                for key, value in timings.items()
                if key != "total"
            )
            await queue.put(_line({
                "type": "result",
                "payload": payload,
            }))
        except GeminiUnavailableError:
            await queue.put(_line({
                "type": "error",
                "error": "gemini_unavailable",
                "message": "解析サービスは現在利用できません。",
            }))
        except ValueError:
            await queue.put(_line({
                "type": "error",
                "error": "invalid_upload",
                "message": "画像または入力内容を確認してください。",
            }))
        except Exception:
            await queue.put(_line({
                "type": "error",
                "error": "analysis_failed",
                "message": "分析を完了できませんでした。",
            }))
        finally:
            await queue.put(_END)

    task = asyncio.create_task(run())
    try:
        while True:
            item = await queue.get()
            if item is _END:
                break
            assert isinstance(item, bytes)
            yield item
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
```

- [ ] **Step 4: Expose `/analyze/stream`**

In `main.py` import `StreamingResponse` and add:

```python
@app.post("/analyze/stream")
async def analyze_stream(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
    mock: bool = Form(False),
) -> StreamingResponse:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルを指定してください。")
    return StreamingResponse(
        stream_analysis(orchestrator, image, room_hint, mock),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
```

- [ ] **Step 5: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_agent/app/main.py \
  apps/sumai_agent/app/services/analysis_stream.py \
  apps/sumai_agent/tests/test_streaming_analysis.py
git commit -m "feat: stream analysis progress and result"
```

### Task 4: Stream Through the Web Proxy Without Polling

**Files:**
- Create: `apps/sumai_agent/tests/test_web_streaming.py`
- Modify: `apps/sumai_web/app.py`

- [ ] **Step 1: Write failing Web proxy tests**

Use actual ASGI and httpx transports so the test proves one upstream request without a
handwritten client:

```python
import io
import json

import pytest
from PIL import Image


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _load_web_module():
    import importlib.util
    import sys
    import uuid
    from pathlib import Path

    app_path = (
        Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"
    )
    module_name = f"sumai_web_stream_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_web_stream_forwards_ndjson_chunks_without_rewriting(
    monkeypatch,
) -> None:
    import httpx

    web_module = _load_web_module()

    stream_lines = [
        b'{"type":"progress","stage":"intake_complete"}\n',
        b'{"type":"progress","stage":"vision_complete"}\n',
        b'{"type":"result","payload":{"analysis_id":"sumai_test"}}\n',
    ]
    requests: list[httpx.Request] = []

    async def backend_handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=b"".join(stream_lines),
        )

    backend = httpx.AsyncClient(
        transport=httpx.MockTransport(backend_handler)
    )
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as web_client:
        async with web_client.stream(
            "POST",
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        ) as response:
            body = await response.aread()
    await backend.aclose()

    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert body == b"".join(stream_lines)
    assert len(requests) == 1
```

Add strict 503 sanitization:

```python
@pytest.mark.asyncio
async def test_web_stream_sanitizes_strict_503(monkeypatch) -> None:
    import httpx

    web_module = _load_web_module()
    monkeypatch.setattr(web_module, "FRONTEND_REQUIRE_REAL_GEMINI", True)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            content=b'{"secret":"provider-secret-body"}',
        )

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    events = [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]
    assert events == [{
        "type": "error",
        "error": "gemini_unavailable",
        "message": "解析サービスは現在利用できません。",
    }]
    assert "provider-secret-body" not in response.text
```

Add non-strict neutral abstention:

```python
@pytest.mark.asyncio
async def test_web_stream_uses_neutral_result_for_non_strict_500(
    monkeypatch,
) -> None:
    import httpx

    web_module = _load_web_module()
    monkeypatch.setattr(web_module, "FRONTEND_REQUIRE_REAL_GEMINI", False)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"untrusted-upstream")

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    event = json.loads(response.text)
    assert event["type"] == "result"
    assert event["payload"]["is_not_applicable"] is True
    assert event["payload"]["findings"] == []
    assert "untrusted-upstream" not in response.text
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_web_streaming.py -q
```

Expected: FAIL because the Web app has no stream proxy.

- [ ] **Step 3: Implement the one-request stream proxy**

Add:

```python
async def _proxy_analysis_stream(
    image_bytes: bytes,
    filename: str,
    content_type: str,
    room_hint: str,
):
    files = {"image": (filename, image_bytes, content_type)}
    data = {
        "room_hint": room_hint,
        "mock": "true" if FRONTEND_MOCK else "false",
    }
    try:
        async with backend_client().stream(
            "POST",
            f"{SUMAI_AGENT_URL}/analyze/stream",
            data=data,
            files=files,
        ) as response:
            if response.status_code == 200:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
                return
            if FRONTEND_REQUIRE_REAL_GEMINI or response.status_code == 503:
                yield _ndjson_error(
                    "gemini_unavailable",
                    "解析サービスは現在利用できません。",
                )
                return
            yield _ndjson_result(
                _build_local_mock(
                    image_bytes, room_hint, "backend_http_error"
                )
            )
    except httpx.RequestError:
        if FRONTEND_REQUIRE_REAL_GEMINI:
            yield _ndjson_error(
                "gemini_unavailable",
                "解析サービスは現在利用できません。",
            )
        else:
            yield _ndjson_result(
                _build_local_mock(
                    image_bytes, room_hint, "backend_unreachable"
                )
            )
```

Expose:

```python
@app.post("/analyze/stream")
async def analyze_stream(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
):
    image_bytes = await image.read()
    return StreamingResponse(
        _proxy_analysis_stream(
            image_bytes,
            image.filename or "photo.png",
            image.content_type or "image/png",
            room_hint,
        ),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )
```

- [ ] **Step 4: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_web/app.py \
  apps/sumai_agent/tests/test_web_streaming.py
git commit -m "feat: proxy analysis progress stream"
```

### Task 5: Implement the Approved B1 Browser Experience

**Files:**
- Modify: `apps/sumai_agent/tests/test_frontend_contract.py`
- Modify: `apps/sumai_web/app.py`

- [ ] **Step 1: Write failing frontend contract tests**

```python
def test_waiting_ui_uses_real_stages_without_fake_progress() -> None:
    html = _index_html()
    assert "写真を安全に処理" in html
    assert "見える範囲を解析" in html
    assert "結果を整理" in html
    assert "application/x-ndjson" in html
    assert "response.body.getReader()" in html
    assert "intake_complete" in html
    assert "vision_complete" in html
    assert "step1 = setTimeout" not in html
    assert "step2 = setTimeout" not in html
    assert "}, 1200)" not in html
    assert "}, 2600)" not in html
    assert 'id="analysis-progress-percent"' not in html
    assert 'aria-valuenow="' not in html
```

```python
def test_waiting_tips_are_local_and_motion_is_accessible() -> None:
    html = _index_html()
    assert "床が濡れていたら、早めに拭きましょう" in html
    assert "通り道に物がないか" in html
    assert "夜間に足元が見える明るさか" in html
    assert "prefers-reduced-motion: reduce" in html
    assert "通常より時間がかかっていますが、解析は続いています" in html
    assert "aria-live=\"polite\"" in html
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_frontend_contract.py -q
```

Expected: FAIL because the current UI uses 1.2s/2.6s timer-driven stages.

- [ ] **Step 3: Replace waiting markup and CSS**

Add a scan overlay inside the selected-photo wrapper, an indeterminate activity track,
three stage rows, and one tip card. Use:

```css
.analysis-activity::after {
    content: "";
    position: absolute;
    width: 34%;
    height: 100%;
    border-radius: inherit;
    background: var(--primary-color);
    animation: analysis-activity 1.55s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
    .analysis-scan-line,
    .analysis-activity::after,
    .analysis-stage.active::before {
        animation: none;
        transform: none;
    }
}
```

Use fixed Japanese labels and no numeric progress.

- [ ] **Step 4: Replace fake timers with stream events**

Use a static local array:

```javascript
const analysisTips = [
    '床が濡れていたら、早めに拭きましょう。',
    '通り道に物がないか、無理のない範囲で確認しましょう。',
    '夜間に足元が見える明るさか、家族と確認しましょう。'
];
```

Implement lifecycle helpers:

```javascript
let analysisTipTimer = null;
let longWaitTimer = null;
let activeAnalysisController = null;

function startWaitingExperience() {
    stopWaitingExperience();
    setAnalysisStage('intake');
    let tipIndex = 0;
    renderAnalysisTip(analysisTips[tipIndex]);
    analysisTipTimer = window.setInterval(() => {
        tipIndex = (tipIndex + 1) % analysisTips.length;
        renderAnalysisTip(analysisTips[tipIndex]);
    }, 5000);
    longWaitTimer = window.setTimeout(() => {
        document.getElementById('analysis-long-wait').hidden = false;
    }, 20000);
}

function stopWaitingExperience() {
    window.clearInterval(analysisTipTimer);
    window.clearTimeout(longWaitTimer);
    analysisTipTimer = null;
    longWaitTimer = null;
    document.getElementById('analysis-long-wait').hidden = true;
}
```

Read NDJSON incrementally:

```javascript
const response = await fetch('/analyze/stream', {
    method: 'POST',
    body: formData,
    signal: activeAnalysisController.signal
});
const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';
while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
        if (line.trim()) handleAnalysisEvent(JSON.parse(line));
    }
    if (done) break;
}
```

`handleAnalysisEvent` completes intake only on `intake_complete`, completes vision only
on `vision_complete`, calls `renderResults` only for `result`, and throws a safe
Japanese error for `error`. Stop timers on result, error, returning home, and page
hidden; abort the active fetch only when the user explicitly leaves the analysis.

- [ ] **Step 5: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_web/app.py \
  apps/sumai_agent/tests/test_frontend_contract.py
git commit -m "feat: add truthful local waiting experience"
```

### Task 6: Full Validation, Independent Review, Push, and Cloud Run Deployment

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/decisions.md`
- Modify: `apps/sumai_agent/tests/test_documentation_contract.py`

- [ ] **Step 1: Document and test the resource boundary**

Add assertions:

```python
assert "single NDJSON response" in architecture
assert "no polling and no additional Gemini request" in decisions
assert "indeterminate activity bar" in decisions
```

Update docs with the actual endpoint, events, reduced-motion behavior, and the fact
that tips are static browser data.

- [ ] **Step 2: Run focused and full gates**

```bash
git diff --check
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_streaming_analysis.py \
  apps/sumai_agent/tests/test_web_streaming.py \
  apps/sumai_agent/tests/test_frontend_contract.py \
  apps/sumai_agent/tests/test_documentation_contract.py -q
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh
```

Expected: all pytest tests PASS, frontend import succeeds, and compose config validates.

- [ ] **Step 3: Commit docs and request independent review**

```bash
git add \
  docs/architecture.md \
  docs/decisions.md \
  apps/sumai_agent/tests/test_documentation_contract.py
git commit -m "docs: define truthful streamed progress"
```

Review request:

```text
Review the stacked visible-risk plus B1 waiting implementation. Verify progress
events reflect real boundaries, stream errors do not leak provider details, no
polling/duplicate Gemini calls exist, timers are cleaned up, reduced motion works,
and the visible-risk contract still excludes confirmations from risk/actions.
Report P0-P3 findings with file and line evidence.
```

Fix all P0-P2 issues with RED/GREEN tests and rerun the full gate.

- [ ] **Step 4: Browser-verify locally at 390×844**

Start the reviewed worktree locally using the repository's compose configuration.
Verify:

```text
1. Scan line and indeterminate activity bar animate.
2. A real stage does not complete before its NDJSON event.
3. Tips rotate every five seconds without network requests.
4. At 20 seconds the honest long-wait message appears.
5. Reduced-motion disables movement.
6. No horizontal overflow or console errors.
7. Confirmation-only toilet result shows 0 visible risks and no action button.
```

Capture a screenshot and console/network evidence. Do not treat health endpoints alone
as UI acceptance.

- [ ] **Step 5: Push both branches**

```bash
git push -u origin codex/sumaiguard-visible-risk-policy
git push -u origin codex/sumaiguard-analysis-waiting-experience
```

Expected: both remote branch tips match their local reviewed commits.

- [ ] **Step 6: Integrate into `main` without touching unrelated files**

In the main worktree, verify only user-owned `docs/preconsultation/` remains untracked.
Then merge in order:

```bash
git merge --no-ff codex/sumaiguard-visible-risk-policy \
  -m "merge: enforce visible-risk policy"
git merge --no-ff codex/sumaiguard-analysis-waiting-experience \
  -m "merge: add truthful analysis waiting experience"
```

Because Branch B is stacked on A, the second merge should add only B-specific commits.
Run `./scripts/test_all.sh` again and inspect `git diff origin/main...main`.

- [ ] **Step 7: Push `main` and deploy through the gated Cloud Build**

```bash
git push origin main
SUMAI_PROJECT_ID="$(gcloud config get-value project)"
test -n "$SUMAI_PROJECT_ID"
gcloud builds submit \
  --project="$SUMAI_PROJECT_ID" \
  --config=cloudbuild.yaml \
  .
```

Expected: Cloud Build tests, builds both images, probes no-traffic candidates, promotes
only after gates pass, and leaves Agent and Web at 100% on revisions labeled with the
new source commit.

- [ ] **Step 8: Verify production and the user's Chrome**

Read-only deployment evidence:

```bash
gcloud run services describe sumai-agent \
  --project="$SUMAI_PROJECT_ID" \
  --region=asia-northeast1 \
  --format='value(status.latestReadyRevisionName,status.url)'
gcloud run services describe sumai-web \
  --project="$SUMAI_PROJECT_ID" \
  --region=asia-northeast1 \
  --format='value(status.latestReadyRevisionName,status.url)'
```

Use the actual toilet photo and verify the production Web URL:

```text
- waiting page matches B1 and receives real stage changes;
- no fake percentage or extra analysis request appears in Network;
- confirmation-only output remains 0 visible risks / low / no actions;
- neutral confirmation wording does not claim absence, purchase, or construction;
- improvement card and suggestion button are hidden without visible findings;
- mobile layout and console are clean.
```

Finally report the two branch HEADs, merge commits, Cloud Build ID, production revisions,
traffic percentages, test counts, actual-photo result, Git status, and remaining
provider non-determinism.
