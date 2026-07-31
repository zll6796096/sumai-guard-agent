# UI-only Waiting Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a truthful, local-only waiting experience to the restored SumaiGuard UI without changing any backend runtime code or analysis contract.

**Architecture:** Keep the existing single `POST /analyze` flow. Add one self-contained waiting panel and three browser-only lifecycle functions inside `INDEX_HTML`; CSS handles the indeterminate motion, while JavaScript timers rotate neutral status copy and safety tips and are always cleared before result/error rendering.

**Tech Stack:** FastAPI-served HTML, CSS, vanilla JavaScript, pytest frontend contract tests, Docker Compose, Google Cloud Build/Cloud Run.

---

### Task 1: Lock the frontend-only contract

**Files:**
- Modify: `apps/sumai_agent/tests/test_frontend_contract.py`
- Test: `apps/sumai_agent/tests/test_frontend_contract.py`

- [ ] **Step 1: Write the failing contract tests**

Add tests that require `waiting-progress-track`, `waiting-status-text`,
`waiting-tip-text`, `waiting-long-note`, `startWaitingExperience`,
`stopWaitingExperience`, and `window.matchMedia('(prefers-reduced-motion: reduce)')`.
Also assert that `fetch('/analyze'` occurs exactly once and that `EventSource`,
`WebSocket`, `/analyze/stream`, and displayed percent copy are absent.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
/Users/zhanglonglong/Projects/apps/sumai-guard-agent/.venv/bin/python -m pytest -q apps/sumai_agent/tests/test_frontend_contract.py
```

Expected: the new waiting-experience tests fail because the required DOM and
lifecycle functions are absent; existing tests remain passing.

- [ ] **Step 3: Commit the RED test contract with the later implementation**

Stage this test explicitly together with `apps/sumai_web/app.py` after GREEN so
the repository never publishes a test-only broken commit.

### Task 2: Implement the minimal local waiting experience

**Files:**
- Modify: `apps/sumai_web/app.py`
- Test: `apps/sumai_agent/tests/test_frontend_contract.py`

- [ ] **Step 1: Add the waiting panel markup and styles**

Add an indeterminate progress track with no numeric value, a polite status text,
a static tip heading and rotating tip body, plus a hidden long-wait note. Extend
the existing reduced-motion media query to disable the indicator animation and
tip transitions.

- [ ] **Step 2: Add lifecycle functions**

Implement `startWaitingExperience()`, `renderWaitingPhase()`, and
`stopWaitingExperience()`. Store timer handles, update neutral elapsed-time copy,
rotate four fixed safety tips every six seconds, reveal the long-wait note after
24 seconds, and clear every handle in `stopWaitingExperience()`.

- [ ] **Step 3: Integrate with the existing request lifecycle**

Replace the old `startStepAnimation()` call with `startWaitingExperience()`.
Call `stopWaitingExperience()` before success rendering, inside the request
error handler, and when returning home. Leave the existing `fetch('/analyze',
{method: 'POST', body: formData})` and `renderResults(data)` contract unchanged.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the focused pytest command from Task 1. Expected: all frontend-contract
tests pass.

- [ ] **Step 5: Review the runtime diff**

Run:

```bash
git diff -- apps/sumai_web/app.py apps/sumai_agent/tests/test_frontend_contract.py
git diff --name-only
```

Expected: runtime changes are limited to `apps/sumai_web/app.py`; no path under
`apps/sumai_agent/app/` appears.

### Task 3: Verify the complete restored product contract

**Files:**
- Verify only: all repository files

- [ ] **Step 1: Run the full backend suite**

```bash
/Users/zhanglonglong/Projects/apps/sumai-guard-agent/.venv/bin/python -m pytest -q apps/sumai_agent/tests
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Verify frontend import and Compose configuration**

```bash
/Users/zhanglonglong/Projects/apps/sumai-guard-agent/.venv/bin/python -c 'import sys; sys.path.insert(0,"apps/sumai_web"); import app; print("frontend import ok")'
docker compose config >/dev/null
```

Expected: `frontend import ok` and exit status zero.

- [ ] **Step 3: Commit and push the isolated branch**

Stage only the two documentation files, the frontend contract test, and
`apps/sumai_web/app.py`. Commit with `feat: add local-only analysis waiting UI`
and push `codex/sumaiguard-ui-only-fixed`.

### Task 4: Release and fix the accepted baseline

**Files:**
- No additional source changes

- [ ] **Step 1: Merge the verified branch into `main` and push**

Use a non-fast-forward merge, confirm `docs/preconsultation/` remains untracked
and untouched, then push `main` to trigger Cloud Build.

- [ ] **Step 2: Verify Cloud Build and Cloud Run**

Require Cloud Build `SUCCESS`, matching commit-tagged Agent/Web images, ready
revisions, and 100 percent traffic for both services.

- [ ] **Step 3: Run real-photo production acceptance**

Use a real residential photo through the deployed page or production Web
endpoint. Require HTTP 200, non-empty findings, distinct annotated and
improvement images, non-empty action tiers, and no extra analysis request.

- [ ] **Step 4: Create and push the fixed tag**

Create annotated tag `sumai-ui-fixed-2026-07-31` at the verified merge commit
with message `Fixed UI-only SumaiGuard production baseline`, then push that
single tag.

- [ ] **Step 5: Report evidence and remaining risks**

Report tests, SHAs, build ID, revisions, traffic, real-photo outcome, clean path
audit, preserved untracked files, and the fact that this release deliberately
retains the restored backend's legacy risk-location behavior.
