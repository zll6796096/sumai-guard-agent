# SumaiGuard Backend Privacy And App Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the native-app backend contract so production analysis is attested, bounded, non-persistent, and safe to expose before SwiftUI client work begins.

**Architecture:** Keep the existing FastAPI analysis pipeline and deterministic action-tier engine. Add a small header-only Firebase App Check verifier in front of both analysis routes, bound image intake inside the existing orchestrator, normalize every public error, and attach `Cache-Control: no-store` to every analysis response. Keep `sumai-web` fully usable in local mock mode, while a production flag disables browser analysis and leaves only the product, privacy, support, and readiness pages public.

**Tech Stack:** Python 3.12/3.13, FastAPI, Firebase Admin Python SDK, Pillow, Pydantic 2, httpx, pytest, Docker Compose.

---

## First-Principles Contract

- **Real objective:** create a verifiable privacy and abuse-control boundary for
  the approved native iPhone release, not merely add new routes.
- **Relevant rule:** risk control and evidence come before release speed.
- **Minimal verifiable deliverable:** both analysis routes enforce the same
  optional-by-configuration App Check dependency; production-shaped tests prove
  attestation rejection before orchestration, bounded intake, stable safe errors,
  no-store responses, and disabled public-browser analysis.
- **Out of scope:** SwiftUI/Xcode files, Firebase console registration, App Attest
  device validation, Cloud Run candidate deployment or traffic changes, App Store
  metadata/upload/review/release, replay-token consumption, accounts, persistent
  quota storage, and edits under `docs/preconsultation/`.
- **Guardrails:** defaults preserve credential-free local mock mode; no image,
  token, Firebase identifier, exception string, Gemini payload, pixel hash, report
  text, or action text enters public errors or logs; no deployment command runs.
- **Acceptance:** focused RED/GREEN tests, the complete Python suite, frontend
  import, Compose validation, diff review, and Git status all pass or are reported
  exactly.

## File Map

- Modify `apps/sumai_agent/app/config.py`: production security flags, upload
  ceiling, safe readiness predicate, and version `0.3.0`.
- Modify `apps/sumai_agent/app/errors.py`: typed internal failures that map to the
  approved public status/code pairs.
- Create `apps/sumai_agent/app/security/__init__.py`: security package marker.
- Create `apps/sumai_agent/app/security/app_check.py`: injectable Firebase App
  Check token verification without replay-protection claims.
- Modify `apps/sumai_agent/app/services/image_intake.py`: bounded streaming read,
  decoded-pixel ceiling, EXIF stripping, and normalized image errors.
- Modify `apps/sumai_agent/app/services/orchestrator.py`: use bounded intake and
  keep images outside the process-local semantic memo.
- Modify `apps/sumai_agent/app/services/gemini_vision.py`: distinguish provider
  quota exhaustion from generic strict-provider unavailability without logging
  provider text.
- Modify `apps/sumai_agent/app/main.py`: `/health`, `/ready`, versioned analysis
  route, compatibility route, App Check dependency, safe error mapper, no-store
  middleware, and metadata-only logging.
- Modify `apps/sumai_agent/requirements.txt`: Firebase Admin SDK runtime bound.
- Create `apps/sumai_agent/tests/test_app_check.py`: verifier and configuration
  unit tests.
- Create `apps/sumai_agent/tests/test_native_api_privacy.py`: versioned route,
  order-of-operations, error, intake, response-header, and logging contracts.
- Modify `apps/sumai_agent/tests/test_healthz.py`: safe operational endpoints and
  compatibility alias.
- Modify `apps/sumai_agent/tests/test_strict_production.py`: uppercase stable
  provider errors and quota mapping.
- Create `apps/sumai_web/public_pages.py`: static Japanese privacy and support
  HTML with no runtime user data.
- Modify `apps/sumai_web/Dockerfile`: copy the public-page module into the
  runtime image.
- Modify `apps/sumai_web/app.py`: `/privacy`, `/support`, no-store headers, the
  `PUBLIC_WEB_ANALYSIS_ENABLED` gate, and versioned backend URL.
- Modify `apps/sumai_agent/tests/test_web_ui_contract.py`: public-page and
  production browser-analysis contracts.
- Modify `.env.example`: explicit local-safe security defaults.
- Modify `docker-compose.yml`: pass the new flags while keeping mock defaults.
- Modify `README.md`: document API routes, environment contract, privacy boundary,
  and the fact that Python App Check verification does not consume tokens.
- Modify `apps/sumai_agent/tests/test_documentation_contract.py`: source and
  operator-documentation assertions.

## Task 1: Security Configuration And Typed Failure Taxonomy

**Files:**
- Modify: `apps/sumai_agent/app/config.py`
- Modify: `apps/sumai_agent/app/errors.py`
- Modify: `apps/sumai_agent/requirements.txt`
- Create: `apps/sumai_agent/tests/test_app_check.py`

- [ ] **Step 1: Add failing configuration tests**

Create `apps/sumai_agent/tests/test_app_check.py` with these initial tests:

```python
from __future__ import annotations

import pytest

from app.config import Settings


def test_local_defaults_keep_app_check_optional() -> None:
    configured = Settings()
    assert configured.app_check_required is False
    assert configured.max_upload_bytes == 10 * 1024 * 1024
    assert configured.max_source_pixels == 25_000_000


def test_required_app_check_needs_an_expected_firebase_app_id() -> None:
    with pytest.raises(ValueError, match="firebase_app_id"):
        Settings(app_check_required=True, firebase_app_id="")


@pytest.mark.parametrize("field", ["max_upload_bytes", "max_source_pixels"])
def test_image_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        Settings(**{field: 0})
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest apps/sumai_agent/tests/test_app_check.py -v
```

Expected: FAIL because the security and upload-limit fields do not exist.

- [ ] **Step 3: Add exact settings and validate fail-closed production input**

In `apps/sumai_agent/app/config.py`, extend `Settings` with:

```python
app_check_required: bool = _env_bool("APP_CHECK_REQUIRED", False)
firebase_app_id: str = os.getenv("FIREBASE_APP_ID", "").strip()
max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
max_source_pixels: int = int(os.getenv("MAX_SOURCE_PIXELS", "25000000"))
version: str = "0.3.0"
```

Extend `__post_init__()` so required App Check with a blank Firebase app ID and
non-positive image limits raise `ValueError` using only configuration field
names. Do not require Firebase credentials when `APP_CHECK_REQUIRED=false`.

- [ ] **Step 4: Add internal exceptions with no user-derived payload**

Replace the single-class `apps/sumai_agent/app/errors.py` with these typed
internal failures:

```python
class AppCheckInvalidError(Exception):
    """The request lacks a valid token for the configured Firebase app."""


class InvalidImageError(Exception):
    """The upload cannot be accepted as a supported image."""


class ImageTooLargeError(Exception):
    """The upload exceeds the byte or decoded-pixel contract."""


class ServiceLimitedError(Exception):
    """The provider rejected work because a quota or rate bound was reached."""


class GeminiUnavailableError(Exception):
    """Strict real-Gemini analysis is unavailable."""
```

Exception instances must not store image bytes, tokens, provider response text,
or user-visible report content.

- [ ] **Step 5: Add the Firebase Admin dependency**

Append this compatible runtime bound to
`apps/sumai_agent/requirements.txt`:

```text
firebase-admin>=7.1,<8.0
```

Install both requirement sets in the active isolated environment used for this
repository. If no isolated environment is active, create `.venv` and
install there; do not mutate system Python packages:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install \
  -r apps/sumai_agent/requirements.txt \
  -r apps/sumai_web/requirements.txt
```

Expected: exit 0; `firebase-admin` resolves below 8.0.

- [ ] **Step 6: Run the focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest apps/sumai_agent/tests/test_app_check.py -v
```

Expected: PASS.

Commit only the Task 1 paths:

```bash
git add apps/sumai_agent/app/config.py \
  apps/sumai_agent/app/errors.py \
  apps/sumai_agent/requirements.txt \
  apps/sumai_agent/tests/test_app_check.py
git commit -m "feat: define native API security contract"
```

## Task 2: Injectable Firebase App Check Verification

**Files:**
- Create: `apps/sumai_agent/app/security/__init__.py`
- Create: `apps/sumai_agent/app/security/app_check.py`
- Modify: `apps/sumai_agent/tests/test_app_check.py`

- [ ] **Step 1: Add verifier tests for every accepted and rejected state**

Extend `test_app_check.py` with an injectable `token_verifier` and assert:

1. enforcement disabled accepts a missing header and never calls Firebase;
2. enforcement enabled rejects missing and blank headers;
3. Firebase verification exceptions become `AppCheckInvalidError` without
   preserving the provider exception text;
4. a decoded token with the wrong or missing `app_id` is rejected;
5. a decoded token with the exact expected `app_id` is accepted;
6. the returned claims object contains only the validated app ID, never the raw
   token or full decoded claims.

Use this test-double shape:

```python
def valid_verify(token: str) -> dict[str, object]:
    assert token == "attested-token"
    return {"app_id": "1:123:ios:abc", "sub": "private-install-claim"}
```

The accepted result must equal `VerifiedAppCheck(app_id="1:123:ios:abc")` and
must not expose `sub`.

- [ ] **Step 2: Run the verifier tests and verify RED**

```bash
.venv/bin/python -m pytest apps/sumai_agent/tests/test_app_check.py -v
```

Expected: FAIL because `app.security.app_check` does not exist.

- [ ] **Step 3: Implement the narrow verifier**

Create `apps/sumai_agent/app/security/app_check.py` with these public types and
signatures:

```python
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hmac

from app.errors import AppCheckInvalidError

DecodedToken = Mapping[str, object]
TokenVerifier = Callable[[str], DecodedToken]


@dataclass(frozen=True)
class VerifiedAppCheck:
    app_id: str


class AppCheckVerifier:
    def __init__(
        self,
        *,
        required: bool,
        expected_app_id: str,
        token_verifier: TokenVerifier | None = None,
    ) -> None:
        self._required = required
        self._expected_app_id = expected_app_id
        self._token_verifier = token_verifier or _verify_with_firebase

    def verify(self, token: str | None) -> VerifiedAppCheck | None:
        if not self._required:
            return None
        candidate = (token or "").strip()
        if not candidate:
            raise AppCheckInvalidError from None
        try:
            decoded = self._token_verifier(candidate)
            app_id = decoded.get("app_id")
        except Exception:
            raise AppCheckInvalidError from None
        if not isinstance(app_id, str) or not hmac.compare_digest(
            app_id, self._expected_app_id
        ):
            raise AppCheckInvalidError from None
        return VerifiedAppCheck(app_id=app_id)
```

The default callable lazily imports
`firebase_admin.app_check.verify_token`. Firebase initialization must use
Application Default Credentials and occur only when verification is required:

```python
def _verify_with_firebase(token: str) -> DecodedToken:
    import firebase_admin
    from firebase_admin import app_check

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app()
    return app_check.verify_token(token)
```

`verify()` must strip the header, call the verifier once, compare the decoded
`app_id` with `expected_app_id` using `hmac.compare_digest`, and raise a fresh
`AppCheckInvalidError` from `None` for every failure. Do not log the token,
claims, Firebase exception, or app ID. Do not pass `consume=True`; Python
baseline verification does not provide token-consumption replay protection.

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/python -m pytest apps/sumai_agent/tests/test_app_check.py -v
git add apps/sumai_agent/app/security/__init__.py \
  apps/sumai_agent/app/security/app_check.py \
  apps/sumai_agent/tests/test_app_check.py
git commit -m "feat: verify Firebase App Check tokens"
```

Expected: tests PASS.

## Task 3: Bounded And Metadata-Free Image Intake

**Files:**
- Modify: `apps/sumai_agent/app/services/image_intake.py`
- Modify: `apps/sumai_agent/app/services/orchestrator.py`
- Create: `apps/sumai_agent/tests/test_native_api_privacy.py`

- [ ] **Step 1: Write failing byte, pixel, and metadata tests**

Create `apps/sumai_agent/tests/test_native_api_privacy.py`. Test
`read_upload_bytes()` directly with Starlette `UploadFile` instances and assert:

- exactly eight bytes succeed;
- nine bytes with `max_bytes=8` raise `ImageTooLargeError`;
- zero bytes raise `InvalidImageError`;
- invalid bytes passed to `read_and_sanitize_image()` raise
  `InvalidImageError` with no Pillow exception text;
- an image whose decoded `width * height` exceeds a supplied
  `max_source_pixels` raises `ImageTooLargeError`;
- a JPEG containing EXIF data returns normalized PNG bytes for which
  `Image.open(io.BytesIO(safe_png)).getexif()` is empty;
- a large but allowed image is resized to at most 1600 pixels on its longest
  side.

Use small test-specific limits for the oversized cases; do not allocate a
10 MiB or 25-megapixel fixture.

- [ ] **Step 2: Run the intake tests and verify RED**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_native_api_privacy.py -v
```

Expected: FAIL because bounded upload reading and typed intake errors do not
exist.

- [ ] **Step 3: Implement bounded streaming intake**

In `apps/sumai_agent/app/services/image_intake.py`, add:

```python
UPLOAD_CHUNK_SIZE = 1024 * 1024


async def read_upload_bytes(
    upload: UploadFile,
    *,
    max_bytes: int,
    chunk_size: int = UPLOAD_CHUNK_SIZE,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(chunk_size):
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError
        chunks.append(chunk)
    if total == 0:
        raise InvalidImageError
    return b"".join(chunks)
```

Update `read_and_sanitize_image()` to accept
`max_source_pixels: int = 25_000_000`. Open the image inside a context manager,
read dimensions before conversion, reject excessive `width * height`, apply
`ImageOps.exif_transpose`, convert to RGB, thumbnail to 1600, and encode a new
PNG. Map Pillow decode failures to `InvalidImageError` from `None`; map Pillow
decompression-bomb failures to `ImageTooLargeError` from `None`.

- [ ] **Step 4: Wire bounded intake into the existing orchestrator**

In `AnalysisOrchestrator.analyze()`, replace `await upload.read()` with:

```python
raw_bytes = await read_upload_bytes(
    upload,
    max_bytes=settings.max_upload_bytes,
)
image, safe_png, pixel_digest = await asyncio.to_thread(
    _prepare_image,
    raw_bytes,
    settings.max_source_pixels,
)
```

Change `_prepare_image` to accept `max_source_pixels` and pass it to
`read_and_sanitize_image`. Do not put `raw_bytes`, `safe_png`, the upload, or
`pixel_digest` into `ComputedAnalysis` or `AsyncResultMemo`.

- [ ] **Step 5: Run focused and existing pipeline tests**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_native_api_privacy.py \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_pipeline_timings.py \
  apps/sumai_agent/tests/test_idempotency.py -v
```

Expected: PASS. Existing timing helpers forward `max_source_pixels` where
needed.

- [ ] **Step 6: Commit the bounded-intake slice**

```bash
git add apps/sumai_agent/app/services/image_intake.py \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/tests/test_native_api_privacy.py
git commit -m "feat: bound and sanitize native image intake"
```

## Task 4: Versioned API, Attestation Order, Safe Errors, And No-Store

**Files:**
- Modify: `apps/sumai_agent/app/main.py`
- Modify: `apps/sumai_agent/tests/test_healthz.py`
- Modify: `apps/sumai_agent/tests/test_native_api_privacy.py`
- Modify: `apps/sumai_agent/tests/test_strict_production.py`

- [ ] **Step 1: Add failing safe operational-endpoint tests**

Replace the current `/healthz` assertions with:

```python
def test_health_and_compatibility_alias_are_safe() -> None:
    client = TestClient(app)
    expected = {"status": "ok", "version": "0.3.0"}
    assert client.get("/health").json() == expected
    assert client.get("/healthz").json() == expected


def test_ready_does_not_disclose_runtime_secrets_or_provider_state() -> None:
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "version": "0.3.0"}
    for forbidden in ("key", "secret", "credential", "firebase", "model"):
        assert forbidden not in response.text.lower()
```

Keep `/status` unchanged in this phase because the current Cloud Build promotion
script consumes it. Phase 3 must replace that probe with control-plane evidence
before removing `/status`; do not expand the endpoint or use it in iOS code.

- [ ] **Step 2: Add failing API security and privacy tests**

Extend `test_native_api_privacy.py` with a fake orchestrator whose `analyze()`
increments a call counter, and cover both `/api/v1/analyze` and `/analyze`:

- missing App Check token with enforcement enabled returns exactly
  `401 {"error":"APP_CHECK_INVALID","message":"アプリの確認に失敗しました。もう一度お試しください。"}`;
- invalid and wrong-app tokens return the same body;
- rejected requests leave the fake orchestrator call count at zero;
- a valid token reaches the fake orchestrator exactly once;
- local `APP_CHECK_REQUIRED=false` accepts no token and preserves mock analysis;
- MIME types other than exactly `image/jpeg` or `image/png` return
  `400 INVALID_IMAGE`;
- invalid pixels return `400 INVALID_IMAGE`;
- excessive bytes or decoded pixels return `413 IMAGE_TOO_LARGE`;
- request-schema errors on either analysis path return `400 INVALID_IMAGE`, not
  FastAPI's raw 422 detail;
- strict Gemini unavailability returns `503 GEMINI_UNAVAILABLE`;
- `ServiceLimitedError` returns `429 SERVICE_LIMITED`;
- unexpected exceptions return `500 INTERNAL_ERROR` and neither response nor
  captured logs contain a sentinel exception string;
- every success and error response from either analysis path includes
  `Cache-Control: no-store`.

Patch `app.main.settings` with a concrete `Settings` instance and patch
`app.main.AppCheckVerifier` to inject the deterministic verifier. Never place a
real token or Firebase credential in a test.

- [ ] **Step 3: Run the API tests and verify RED**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_healthz.py \
  apps/sumai_agent/tests/test_native_api_privacy.py -v
```

Expected: FAIL because `/health`, `/ready`, `/api/v1/analyze`, attestation, safe
errors, and no-store handling are absent.

- [ ] **Step 4: Add one shared public-error response helper**

In `apps/sumai_agent/app/main.py`, define centralized public copy:

```python
PUBLIC_ERRORS = {
    "INVALID_IMAGE": (400, "画像を確認できませんでした。JPEGまたはPNGを選んでください。"),
    "APP_CHECK_INVALID": (401, "アプリの確認に失敗しました。もう一度お試しください。"),
    "IMAGE_TOO_LARGE": (413, "画像が大きすぎます。別の写真を選んでください。"),
    "SERVICE_LIMITED": (429, "現在アクセスが集中しています。時間をおいてお試しください。"),
    "GEMINI_UNAVAILABLE": (503, "現在解析を利用できません。時間をおいてお試しください。"),
    "INTERNAL_ERROR": (500, "解析を完了できませんでした。時間をおいてお試しください。"),
}
```

`public_error(code)` returns the matching flat JSON body with
`Cache-Control: no-store`. It must never receive `str(exc)`, `repr(exc)`,
`HTTPException.detail`, or a provider payload.

- [ ] **Step 5: Add the App Check dependency before multipart intake**

Define:

```python
def require_app_check(
    x_firebase_appcheck: Annotated[str | None, Header()] = None,
) -> None:
    AppCheckVerifier(
        required=settings.app_check_required,
        expected_app_id=settings.firebase_app_id,
    ).verify(x_firebase_appcheck)
```

Register an `AppCheckInvalidError` exception handler returning
`public_error("APP_CHECK_INVALID")`. Put
`dependencies=[Depends(require_app_check)]` on both analysis route decorators so
dependency resolution completes before the endpoint calls the orchestrator.

- [ ] **Step 6: Share one handler across versioned and compatibility routes**

Use two decorators on the existing function:

```python
@app.post(
    "/api/v1/analyze",
    response_model=AnalysisResponse,
    dependencies=[Depends(require_app_check)],
)
@app.post(
    "/analyze",
    response_model=AnalysisResponse,
    dependencies=[Depends(require_app_check)],
    include_in_schema=False,
)
```

Apply these decorators to the existing `analyze` function without changing its
`image`, `room_hint`, `mock`, or return annotations. Replace its exception
mapping as specified below; the shared existing pipeline must execute through
both routes.

Accept only exact JPEG/PNG MIME types. Map typed failures to the six approved
public codes. Convert image decode failures through `InvalidImageError`, not by
inspecting exception text. Residual `ValueError` and all unexpected failures map
to `INTERNAL_ERROR`.

Remove `error` and `original` from the JSON formatter allowlist. For unexpected
failures, log only `failure_type=type(exc).__name__`, `safe_error_code`, and
generated request metadata. Never use `logger.exception` on the analysis path.

- [ ] **Step 7: Normalize validation and response caching**

Register a `RequestValidationError` handler that returns `INVALID_IMAGE` only
for the two analysis paths and delegates to FastAPI's default handler elsewhere.
Add middleware that sets `Cache-Control: no-store` on every response whose path
is `/api/v1/analyze` or `/analyze`, including dependency and validation errors.
Successful responses use `model_dump(mode="json")` and do not serialize
`_cache_hit`.

- [ ] **Step 8: Add safe operational endpoints**

Return only:

```python
{"status": "ok", "version": settings.version}
{"status": "ready", "version": settings.version}
```

from `/health`/`/healthz` and `/ready`, respectively. Production configuration
identity is verified later through the Cloud Run control plane.

- [ ] **Step 9: Update strict assertions and run focused tests**

Change strict tests from lower-case `gemini_unavailable` and raw English
messages to the exact uppercase safe contract. Run:

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_healthz.py \
  apps/sumai_agent/tests/test_native_api_privacy.py \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_strict_production.py \
  apps/sumai_agent/tests/test_async_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit the public API slice**

```bash
git add apps/sumai_agent/app/main.py \
  apps/sumai_agent/tests/test_healthz.py \
  apps/sumai_agent/tests/test_native_api_privacy.py \
  apps/sumai_agent/tests/test_strict_production.py
git commit -m "feat: expose attested native analysis API"
```

## Task 5: Stable Quota Semantics Without Provider Leakage

**Files:**
- Modify: `apps/sumai_agent/app/services/gemini_vision.py`
- Modify: `apps/sumai_agent/tests/test_strict_production.py`

- [ ] **Step 1: Write the failing strict quota test**

Add a synthetic exception with `status_code = 429` whose string contains a
sentinel provider payload. Patch `_call_gemini` to raise it in strict mode and
assert:

- the response is `429 SERVICE_LIMITED`;
- neither response text nor `caplog` contains the sentinel;
- mock fallback is not invoked.

Add a second exception with `code = 429` to cover the alternate SDK shape. Keep
existing timeout/provider-failure tests expecting `503 GEMINI_UNAVAILABLE`.

- [ ] **Step 2: Run the strict quota tests and verify RED**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_strict_production.py -k 'quota or limited' -v
```

Expected: FAIL because every strict provider exception currently becomes
`GeminiUnavailableError`.

- [ ] **Step 3: Add a metadata-only quota classifier**

In `gemini_vision.py`, add:

```python
def _is_provider_limited(exc: Exception) -> bool:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if value == 429 or value == "429":
            return True
    return False
```

In strict analysis, log only safe classification/timing and raise
`ServiceLimitedError` from `None` when true. Otherwise retain
`GeminiUnavailableError`. Do not parse or log the exception string.

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_strict_production.py \
  apps/sumai_agent/tests/test_native_api_privacy.py -v
git add apps/sumai_agent/app/services/gemini_vision.py \
  apps/sumai_agent/tests/test_strict_production.py
git commit -m "feat: map provider limits to safe API errors"
```

Expected: tests PASS and the commit contains no provider sentinel.

## Task 6: Public Privacy And Support Pages, Production Web Gate

**Files:**
- Create: `apps/sumai_web/public_pages.py`
- Modify: `apps/sumai_web/Dockerfile`
- Modify: `apps/sumai_web/app.py`
- Modify: `apps/sumai_agent/tests/test_web_ui_contract.py`

- [ ] **Step 1: Add a reusable web-module loader with explicit environment**

Refactor the test-only module loader in `test_web_ui_contract.py` to accept
environment overrides and a unique module name. Before executing the module,
set or clear `MOCK_MODE`, `REQUIRE_REAL_GEMINI`, and
`PUBLIC_WEB_ANALYSIS_ENABLED` with `monkeypatch`, so one test cannot inherit
another test's module globals.

- [ ] **Step 2: Write failing public-page tests**

Add tests asserting:

- `GET /privacy` and `GET /support` return 200 Japanese HTML;
- both include `Cache-Control: no-store` and a link back to `/`;
- privacy names `Google LLC`, Gemini, Firebase App Check, Apple's App Attest,
  Google Cloud Run, and Cloud Logging;
- privacy states per-image consent, possible private home context, EXIF removal,
  no SumaiGuard application persistence, no tracking/advertising, withdrawal by
  canceling before upload, and a support/deletion-request path;
- privacy does not invent a Cloud Logging retention duration;
- support contains no-account steps, the JPEG/PNG/10 MiB contract, retry
  guidance, and the medical/care/insurance/construction disclaimer;
- neither page contains an unconfirmed email address, organization name, or
  retention number.

- [ ] **Step 3: Write failing production browser-gate tests**

Load the web app with:

```text
MOCK_MODE=false
REQUIRE_REAL_GEMINI=true
PUBLIC_WEB_ANALYSIS_ENABLED=false
```

Post a small PNG to `/analyze` and assert HTTP 503, no-store, and exactly:

```json
{
  "error": "NATIVE_APP_REQUIRED",
  "message": "公開版の写真解析はiPhoneアプリからご利用ください。"
}
```

Patch `backend_client` with a double that fails if called, proving no image is
forwarded. Then load with `MOCK_MODE=true` and the production flag unset; assert
the existing local mock analysis and PDF tests still pass without credentials.

- [ ] **Step 4: Run web tests and verify RED**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_web_ui_contract.py \
  apps/sumai_agent/tests/test_frontend_contract.py \
  apps/sumai_agent/tests/test_pdf_download.py -v
```

Expected: FAIL because public pages and the production gate are absent.

- [ ] **Step 5: Implement static Japanese public pages**

Create `apps/sumai_web/public_pages.py` with `PRIVACY_HTML` and `SUPPORT_HTML`.
Use semantic headings, a responsive layout, 44-pixel links, visible focus styles,
and the existing calm green palette. Privacy copy must distinguish:

- transient application processing from Cloud Logging operational metadata;
- SumaiGuard non-persistence from third-party processing;
- deletion/support requests from a claim that transient data can always be
  recovered or deleted after processing;
- safety support from medical, care-level, insurance, legal, measurement, or
  construction judgment.

State that operational-log retention will be published only after the production
Cloud Logging configuration is observed. This is a Phase 3 release blocker, not
a fabricated number. Return both pages from `app.py` with `HTMLResponse` and
`Cache-Control: no-store`.

Add `COPY public_pages.py ./public_pages.py` to `apps/sumai_web/Dockerfile` next
to the existing `COPY app.py ./app.py`. In the spec-based test loader, prepend
`apps/sumai_web` to `sys.path` with `monkeypatch.syspath_prepend()` before
executing `app.py`, matching the container's `/app` import layout.

- [ ] **Step 6: Gate browser analysis before reading the image**

Define:

```python
PUBLIC_WEB_ANALYSIS_ENABLED = os.getenv(
    "PUBLIC_WEB_ANALYSIS_ENABLED",
    "true" if FRONTEND_MOCK else "false",
).strip().lower() in {"1", "true", "yes", "on"}
```

At the first line of web `/analyze`, return `NATIVE_APP_REQUIRED` when false.
Only then call `await image.read()`. When enabled, proxy to
`${SUMAI_AGENT_URL}/api/v1/analyze`; this mode is local mock only and must not
synthesize or forward an App Check header.

- [ ] **Step 7: Run tests and commit**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_web_ui_contract.py \
  apps/sumai_agent/tests/test_frontend_contract.py \
  apps/sumai_agent/tests/test_pdf_download.py -v
git add apps/sumai_web/public_pages.py \
  apps/sumai_web/Dockerfile \
  apps/sumai_web/app.py \
  apps/sumai_agent/tests/test_web_ui_contract.py
git commit -m "feat: publish privacy pages and gate web analysis"
```

Expected: PASS; local mock web behavior remains available.

## Task 7: Local Configuration And Operator Documentation

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `apps/sumai_agent/tests/test_documentation_contract.py`

- [ ] **Step 1: Add failing documentation assertions**

Extend `test_documentation_contract.py` to assert:

- `/api/v1/analyze`, `/health`, `/ready`, `/privacy`, and `/support`;
- `APP_CHECK_REQUIRED=false` and blank `FIREBASE_APP_ID` in `.env.example`;
- `MAX_UPLOAD_BYTES=10485760`, `MAX_SOURCE_PIXELS=25000000`, and local-only
  `PUBLIC_WEB_ANALYSIS_ENABLED=true`;
- production guidance contains `APP_CHECK_REQUIRED=true` and
  `PUBLIC_WEB_ANALYSIS_ENABLED=false`;
- Python verifies ordinary App Check tokens but does not consume them for
  single-use replay protection;
- Firebase App Check TTL is set to 30 minutes in Firebase console, not Python;
- Cloud Logging retention must be observed before publication;
- no deployment or traffic change belongs to Phase 1.

- [ ] **Step 2: Run documentation tests and verify RED**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_documentation_contract.py -v
```

Expected: FAIL because routes and variables are undocumented.

- [ ] **Step 3: Add local-safe values**

Append to `.env.example`:

```dotenv
APP_CHECK_REQUIRED=false
FIREBASE_APP_ID=
MAX_UPLOAD_BYTES=10485760
MAX_SOURCE_PIXELS=25000000
PUBLIC_WEB_ANALYSIS_ENABLED=true
```

Pass the same defaults through `docker-compose.yml`. Compose must still start
both services in mock mode without Google or Firebase credentials.

- [ ] **Step 4: Replace obsolete README contracts**

Document:

- native clients use `/api/v1/analyze`; `/analyze` is compatibility-only;
- release probes use `/health` and `/ready`; `/healthz` is an alias;
- exact public error codes and 10 MiB upload limit;
- production requires ADC-capable Firebase verification,
  `APP_CHECK_REQUIRED=true`, the exact iOS `FIREBASE_APP_ID`, strict Gemini, and
  `PUBLIC_WEB_ANALYSIS_ENABLED=false`;
- local mock defaults remain credential-free;
- App Check is abuse mitigation, not authentication, a user account, or
  documented replay protection in the Python SDK;
- the retention value and support identity cannot be finalized until observed;
- `/status` is removed in Phase 3 after Cloud Build switches to control-plane
  verification.

Do not include real project numbers, Firebase IDs, credentials, support email
addresses, or Cloud Run URLs.

- [ ] **Step 5: Run checks and commit**

```bash
.venv/bin/python -m pytest \
  apps/sumai_agent/tests/test_documentation_contract.py -v
docker compose --env-file .env.example config >/tmp/sumaiguard-compose-phase1.txt
test -s /tmp/sumaiguard-compose-phase1.txt
docker compose --env-file .env.example build sumai-agent sumai-web
git add .env.example docker-compose.yml README.md \
  apps/sumai_agent/tests/test_documentation_contract.py
git commit -m "docs: define backend privacy operations"
```

Expected: tests and Compose validation PASS. `/tmp` output is not staged.

## Task 8: Full Phase 1 Verification And Handoff

**Files:**
- Review only: all Phase 1 paths
- Do not modify: `docs/preconsultation/`

- [ ] **Step 1: Run the full local gate**

```bash
.venv/bin/python -m pytest apps/sumai_agent/tests -v
.venv/bin/python -c "import importlib.util; from pathlib import Path; p=Path('apps/sumai_web/app.py'); s=importlib.util.spec_from_file_location('sumai_web_release_check', p); assert s and s.loader; m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('frontend import ok')"
docker compose --env-file .env.example config >/tmp/sumaiguard-compose-phase1.txt
test -s /tmp/sumaiguard-compose-phase1.txt
docker compose --env-file .env.example build sumai-agent sumai-web
```

Expected: all tests pass with zero failures and zero hidden skips; frontend
import prints `frontend import ok`; Compose exits 0.

- [ ] **Step 2: Run privacy-focused scans**

```bash
rg -n "str\(exc\)|repr\(exc\)|logger\.exception|X-Firebase-AppCheck|firebase_app_id" \
  apps/sumai_agent/app apps/sumai_web
rg -n "image_base64|safe_png|raw_bytes|pixel_digest|report_text|action_text" \
  apps/sumai_agent/app/main.py apps/sumai_agent/app/security
```

Expected:

- no exception string reaches an analysis response or analysis error log;
- App Check header is read only by the verifier dependency;
- raw token and decoded claims are never logged or returned;
- image/base64/report/action fields are absent from API logging;
- any remaining `str(exc)` outside the analysis/privacy path is explicitly
  reviewed.

- [ ] **Step 3: Review scope and diff**

```bash
git diff --check origin/main..HEAD
git diff --stat origin/main..HEAD
git diff --name-only origin/main..HEAD
git status --short --branch
```

Expected:

- no whitespace errors;
- only Phase 1 files plus the approved design and this plan are changed;
- `docs/preconsultation/` remains unmodified and unstaged;
- no iOS, Cloud Build, deployment workflow, service traffic, Firebase console,
  or App Store state changed.

- [ ] **Step 4: Record the handoff boundary**

Report these gates separately:

```text
Phase 1 source contract: PASS or exact failure
Full Python tests: PASS or exact failure
Frontend import: PASS or exact failure
Compose validation: PASS or exact failure
Firebase console/App Attest configuration: NOT STARTED
Cloud Run candidate deployment: NOT STARTED
Real-device attested analysis: NOT STARTED
Production traffic: UNCHANGED
App Store upload/review/release/storefront: NOT STARTED
```

Do not claim production readiness until Phase 3 configures Firebase, observes
Cloud Logging retention, deploys a zero-traffic candidate, and a real device
completes an attested analysis against that exact candidate.

## Phase Boundary

After this plan passes, write and approve Phase 2 for the native SwiftUI app
against the stable `/api/v1/analyze` contract. Phase 3 then owns Firebase
console/App Attest registration, candidate-only Cloud Build conversion,
real-device candidate evidence, exact-identity promotion, privacy-policy
finalization, and all App Store Connect gates.
