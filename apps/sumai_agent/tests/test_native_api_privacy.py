from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
import threading
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image, JpegImagePlugin, PngImagePlugin

from app import config as config_module
from app import main
from app.config import Settings
from app.errors import (
    AppCheckInvalidError,
    GeminiUnavailableError,
    ImageTooLargeError,
    InvalidImageError,
    ServiceLimitedError,
)
from app.models import ActionPlan, AnalysisResponse
from app.security import app_check
from app.services import gemini_vision as gemini_module
from app.services import image_intake
from app.services import orchestrator as orchestrator_module


def _image_bytes(
    mode: str = "RGB",
    size: tuple[int, int] = (4, 3),
    *,
    image_format: str = "PNG",
) -> bytes:
    image = Image.new(mode, size, 127)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def test_read_upload_bytes_accepts_exact_byte_limit_with_fixed_chunks() -> None:
    async def run() -> bytes:
        upload = UploadFile(filename="room.bin", file=io.BytesIO(b"12345678"))
        return await image_intake.read_upload_bytes(upload, max_bytes=8, chunk_size=4)

    assert asyncio.run(run()) == b"12345678"


def test_read_upload_bytes_stops_on_first_over_limit_chunk() -> None:
    class RecordingUpload:
        def __init__(self) -> None:
            self.file = io.BytesIO(b"123456789")
            self.read_sizes: list[int] = []

        async def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            return self.file.read(size)

    async def run() -> RecordingUpload:
        upload = RecordingUpload()
        with pytest.raises(ImageTooLargeError):
            await image_intake.read_upload_bytes(upload, max_bytes=8, chunk_size=4)
        return upload

    upload = asyncio.run(run())
    assert upload.read_sizes == [4, 4, 1]
    assert upload.file.tell() == 9


def test_read_upload_bytes_rejects_empty_upload() -> None:
    async def run() -> None:
        upload = UploadFile(filename="empty.png", file=io.BytesIO())
        with pytest.raises(InvalidImageError):
            await image_intake.read_upload_bytes(upload, max_bytes=8, chunk_size=4)

    asyncio.run(run())


def test_invalid_image_bytes_raise_fresh_public_error() -> None:
    with pytest.raises(InvalidImageError) as caught:
        image_intake.read_and_sanitize_image(b"not an image")

    assert str(caught.value) == ""
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_source_pixel_limit_is_checked_before_conversion() -> None:
    with pytest.raises(ImageTooLargeError):
        image_intake.read_and_sanitize_image(
            _image_bytes(size=(4, 3)),
            max_source_pixels=11,
        )


def test_emitted_decompression_warning_is_followed_by_explicit_pixel_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image_bytes(size=(4, 4))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 15)

    with pytest.warns(Image.DecompressionBombWarning):
        with pytest.raises(ImageTooLargeError):
            image_intake.read_and_sanitize_image(source, max_source_pixels=15)


def test_decompression_bomb_warning_exception_maps_to_image_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image_bytes(size=(4, 4))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 15)

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with pytest.raises(ImageTooLargeError) as caught:
            image_intake.read_and_sanitize_image(source, max_source_pixels=100)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_pillow_decompression_bomb_error_maps_to_image_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image_bytes(size=(4, 4))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 7)

    with pytest.raises(ImageTooLargeError) as caught:
        image_intake.read_and_sanitize_image(source, max_source_pixels=100)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_concurrent_bomb_and_valid_intake_leave_global_warning_filters_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = _image_bytes(size=(4, 4))
    valid = _image_bytes(size=(2, 2))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 7)
    original_catch_warnings = warnings.catch_warnings
    catch_warnings_calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(2)

    def recording_catch_warnings(*args: object, **kwargs: object) -> object:
        nonlocal catch_warnings_calls
        with calls_lock:
            catch_warnings_calls += 1
        return original_catch_warnings(*args, **kwargs)

    monkeypatch.setattr(warnings, "catch_warnings", recording_catch_warnings)
    filters_before = tuple(warnings.filters)

    def reject_oversized() -> str:
        start.wait()
        with pytest.raises(ImageTooLargeError):
            image_intake.read_and_sanitize_image(oversized, max_source_pixels=100)
        return "rejected"

    def accept_valid() -> str:
        start.wait()
        image, _ = image_intake.read_and_sanitize_image(valid, max_source_pixels=100)
        return image.mode

    with ThreadPoolExecutor(max_workers=2) as executor:
        oversized_future = executor.submit(reject_oversized)
        valid_future = executor.submit(accept_valid)
        results = [oversized_future.result(), valid_future.result()]

    assert results == ["rejected", "RGB"]
    assert catch_warnings_calls == 0
    assert tuple(warnings.filters) == filters_before


def test_jpeg_drafts_and_thumbnails_before_detached_rgb_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image_bytes(size=(200, 100), image_format="JPEG")
    events: list[tuple[str, tuple[int, int], bool | None]] = []
    original_draft = JpegImagePlugin.JpegImageFile.draft
    original_transpose = image_intake.ImageOps.exif_transpose
    original_thumbnail = Image.Image.thumbnail
    original_convert = Image.Image.convert
    original_copy = Image.Image.copy

    def recording_draft(
        self: JpegImagePlugin.JpegImageFile,
        mode: str | None,
        size: tuple[int, int] | None,
    ) -> object:
        events.append(("draft", self.size, None))
        return original_draft(self, mode, size)

    def recording_transpose(
        image: Image.Image,
        *,
        in_place: bool = False,
    ) -> Image.Image | None:
        events.append(("transpose", image.size, in_place))
        return original_transpose(image, in_place=in_place)

    def recording_thumbnail(
        self: Image.Image,
        size: tuple[int, int],
        resample: Image.Resampling = Image.Resampling.BICUBIC,
        reducing_gap: float | None = 2.0,
    ) -> None:
        events.append(("thumbnail", self.size, None))
        original_thumbnail(self, size, resample, reducing_gap)

    def recording_convert(
        self: Image.Image,
        mode: str | None = None,
        *args: object,
        **kwargs: object,
    ) -> Image.Image:
        events.append(("convert", self.size, None))
        return original_convert(self, mode, *args, **kwargs)

    def recording_copy(self: Image.Image) -> Image.Image:
        events.append(("copy", self.size, None))
        return original_copy(self)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", recording_draft)
    monkeypatch.setattr(image_intake.ImageOps, "exif_transpose", recording_transpose)
    monkeypatch.setattr(Image.Image, "thumbnail", recording_thumbnail)
    monkeypatch.setattr(Image.Image, "convert", recording_convert)
    monkeypatch.setattr(Image.Image, "copy", recording_copy)

    image, _ = image_intake.read_and_sanitize_image(
        source,
        max_dimension=20,
        max_source_pixels=20_000,
    )

    names = [event[0] for event in events]
    assert names.index("draft") < names.index("transpose") < names.index("thumbnail")
    assert next(event[2] for event in events if event[0] == "transpose") is True
    thumbnail_index = names.index("thumbnail")
    for index, (name, size, _) in enumerate(events):
        if name in {"convert", "copy"}:
            assert index > thumbnail_index
            assert max(size) <= 20
    assert max(image.size) <= 20


def test_non_rgb_image_is_thumbnailed_before_rgb_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image_bytes(mode="RGBA", size=(80, 40))
    events: list[tuple[str, tuple[int, int], str | None]] = []
    original_thumbnail = Image.Image.thumbnail
    original_convert = Image.Image.convert
    original_copy = Image.Image.copy

    def recording_thumbnail(
        self: Image.Image,
        size: tuple[int, int],
        resample: Image.Resampling = Image.Resampling.BICUBIC,
        reducing_gap: float | None = 2.0,
    ) -> None:
        events.append(("thumbnail", self.size, None))
        original_thumbnail(self, size, resample, reducing_gap)

    def recording_convert(
        self: Image.Image,
        mode: str | None = None,
        *args: object,
        **kwargs: object,
    ) -> Image.Image:
        events.append(("convert", self.size, mode))
        return original_convert(self, mode, *args, **kwargs)

    def recording_copy(self: Image.Image) -> Image.Image:
        events.append(("copy", self.size, None))
        return original_copy(self)

    monkeypatch.setattr(Image.Image, "thumbnail", recording_thumbnail)
    monkeypatch.setattr(Image.Image, "convert", recording_convert)
    monkeypatch.setattr(Image.Image, "copy", recording_copy)

    image, _ = image_intake.read_and_sanitize_image(
        source,
        max_dimension=16,
        max_source_pixels=80 * 40,
    )

    thumbnail_index = next(
        index for index, event in enumerate(events) if event[0] == "thumbnail"
    )
    rgb_convert_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "convert" and event[2] == "RGB"
    )
    assert thumbnail_index < rgb_convert_index
    for name, size, target_mode in events:
        if name == "copy" or (name == "convert" and target_mode == "RGB"):
            assert max(size) <= 16
    assert image.mode == "RGB"
    assert max(image.size) <= 16


@pytest.mark.parametrize("mode", ["1", "P", "RGB", "RGBA"])
def test_thin_alternating_lines_retain_gray_evidence_after_resize(mode: str) -> None:
    one_bit = Image.new("1", (64, 16))
    pixels = one_bit.load()
    assert pixels is not None
    for x in range(one_bit.width):
        value = 255 if x % 2 else 0
        for y in range(one_bit.height):
            pixels[x, y] = value
    source_image = one_bit if mode == "1" else one_bit.convert(mode)
    source = io.BytesIO()
    source_image.save(source, format="PNG")

    image, _ = image_intake.read_and_sanitize_image(
        source.getvalue(),
        max_dimension=8,
        max_source_pixels=64 * 16,
    )

    luminance_values = set(image.convert("L").getdata())
    assert image.mode == "RGB"
    assert image.size == (8, 2)
    assert any(0 < value < 255 for value in luminance_values)


def test_jpeg_exif_is_removed_and_orientation_is_normalized() -> None:
    source_image = Image.new("RGB", (4, 2), (180, 90, 30))
    exif = source_image.getexif()
    exif[274] = 6
    exif[315] = "SENTINEL_ARTIST"
    exif[270] = "SENTINEL_DESCRIPTION"
    source = io.BytesIO()
    source_image.save(
        source,
        format="JPEG",
        exif=exif,
        icc_profile=b"SENTINEL_ICC",
    )

    image, safe_png = image_intake.read_and_sanitize_image(source.getvalue())

    with Image.open(io.BytesIO(safe_png)) as reopened:
        reopened.load()
        assert reopened.format == "PNG"
        assert reopened.size == (2, 4)
        assert reopened.mode == "RGB"
        assert len(reopened.getexif()) == 0
        assert reopened.info == {}
    assert image.size == (2, 4)
    assert len(image.getexif()) == 0
    assert image.info == {}
    assert b"SENTINEL" not in safe_png


def test_png_text_and_icc_metadata_are_removed() -> None:
    source_image = Image.new("RGB", (3, 2), (20, 40, 60))
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("Comment", "SENTINEL_TEXT")
    source = io.BytesIO()
    source_image.save(
        source,
        format="PNG",
        pnginfo=png_info,
        icc_profile=b"SENTINEL_ICC",
    )

    image, safe_png = image_intake.read_and_sanitize_image(source.getvalue())

    assert image.info == {}
    assert len(image.getexif()) == 0
    assert b"SENTINEL" not in safe_png
    with Image.open(io.BytesIO(safe_png)) as reopened:
        reopened.load()
        assert reopened.info == {}
        assert len(reopened.getexif()) == 0


def test_large_allowed_image_is_resized_to_default_longest_side() -> None:
    image, safe_png = image_intake.read_and_sanitize_image(
        _image_bytes(size=(1601, 4)),
        max_source_pixels=1601 * 4,
    )

    assert max(image.size) <= 1600
    with Image.open(io.BytesIO(safe_png)) as reopened:
        assert max(reopened.size) <= 1600


ANALYSIS_PATHS = ("/api/v1/analyze", "/analyze")
APP_CHECK_ERROR = {
    "error": "APP_CHECK_INVALID",
    "message": "アプリの確認に失敗しました。もう一度お試しください。",
}
PUBLIC_ERRORS = {
    "INVALID_IMAGE": (
        400,
        "画像を確認できませんでした。JPEGまたはPNGを選んでください。",
    ),
    "IMAGE_TOO_LARGE": (
        413,
        "画像が大きすぎます。別の写真を選んでください。",
    ),
    "SERVICE_LIMITED": (
        429,
        "現在アクセスが集中しています。時間をおいてお試しください。",
    ),
    "GEMINI_UNAVAILABLE": (
        503,
        "現在解析を利用できません。時間をおいてお試しください。",
    ),
    "INTERNAL_ERROR": (
        500,
        "解析を完了できませんでした。時間をおいてお試しください。",
    ),
}
PROVIDER_SENTINEL = "SECRET_PROVIDER_FIREBASE_DETAIL_98765"
TOKEN_SENTINEL = "SECRET_ATTESTATION_TOKEN_98765"
EXPECTED_APP_ID = "1:123:ios:abc"


def _explicit_settings(
    *,
    app_check_required: bool = False,
    firebase_app_id: str = "",
    max_upload_bytes: int = 10 * 1024 * 1024,
    max_source_pixels: int = 25_000_000,
) -> Settings:
    return Settings(
        mock_mode=True,
        gemini_api_key="",
        gemini_model="gemini-test-model",
        log_level="INFO",
        analysis_timeout=120,
        version="0.3.0",
        require_real_gemini=False,
        app_check_required=app_check_required,
        firebase_app_id=firebase_app_id,
        max_upload_bytes=max_upload_bytes,
        max_source_pixels=max_source_pixels,
        result_memo_ttl_seconds=300,
        result_memo_max_items=128,
    )


@pytest.fixture(autouse=True)
def _hermetic_native_api_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncMock:
    explicit = _explicit_settings()
    provider_call = AsyncMock(
        side_effect=AssertionError("security tests must not call a real provider")
    )
    monkeypatch.setattr(main, "settings", explicit)
    monkeypatch.setattr(config_module, "settings", explicit)
    monkeypatch.setattr(orchestrator_module, "settings", explicit)
    monkeypatch.setattr(gemini_module, "settings", explicit)
    monkeypatch.setattr(gemini_module.GeminiVisionService, "_call_gemini", provider_call)
    return provider_call


def _fixed_analysis_response() -> AnalysisResponse:
    return AnalysisResponse(
        analysis_id="sumai_test_fixed",
        room_type="genkan",
        overall_risk_level="low",
        findings=[],
        action_plan=ActionPlan(),
        annotated_image_base64="fixed-annotated",
        improvement_image_base64="fixed-improvement",
        risk_summary_markdown="固定された安全なテスト結果",
        family_actions_markdown="",
        care_manager_actions_markdown="",
        contractor_actions_markdown="",
        disclaimer_ja="POC版です。医療・介護・施工判断を代替しません。",
        mode="mock",
        model="N/A",
        result_key="fixed-result-key",
        semantic_hash="fixed-semantic-hash",
        stage_timings_ms={
            "intake": 0,
            "memo_lookup": 0,
            "vision": 0,
            "ontology": 0,
            "render": 0,
            "report": 0,
            "serialize": 0,
            "total": 0,
        },
    )


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, bool]] = []

    async def analyze(
        self,
        upload: object,
        room_hint: str = "auto",
        mock: bool = False,
    ) -> AnalysisResponse:
        self.calls.append((upload, room_hint, mock))
        return _fixed_analysis_response()


def _asgi_scope(
    path: str,
    *,
    token: str | None = None,
    root_path: str = "",
) -> dict[str, object]:
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"multipart/form-data; boundary=malformed"),
        (b"content-length", b"999999999999"),
    ]
    if token is not None:
        headers.append((b"x-firebase-appcheck", token.encode("latin-1")))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": root_path,
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


def _asgi_response(messages: list[dict[str, object]]) -> tuple[int, dict[str, str], dict[str, str]]:
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }
    return int(start["status"]), headers, json.loads(body)


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize(
    ("token", "hostile_body"),
    [
        pytest.param(None, b"malformed multipart", id="missing-malformed"),
        pytest.param(TOKEN_SENTINEL, b"x" * 1024 * 1024, id="invalid-oversized-looking"),
    ],
)
def test_pure_asgi_app_check_rejects_before_body_read_or_multipart_parse(
    path: str,
    token: str | None,
    hostile_body: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    sent: list[dict[str, object]] = []

    class RejectingVerifier:
        def __init__(self, *, required: bool, expected_app_id: str) -> None:
            assert required is True
            assert expected_app_id == EXPECTED_APP_ID

        def verify(self, received_token: str | None) -> None:
            events.append("app_check_attempted")
            assert received_token == token
            raise AppCheckInvalidError(PROVIDER_SENTINEL)

    async def receive() -> dict[str, object]:
        events.append("receive")
        return {"type": "http.request", "body": hostile_body, "more_body": False}

    async def inner_app(
        _scope: object,
        inner_receive: object,
        _send: object,
    ) -> None:
        events.append("multipart_parse")
        await inner_receive()

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    monkeypatch.setattr(
        main,
        "settings",
        _explicit_settings(
            app_check_required=True,
            firebase_app_id=EXPECTED_APP_ID,
        ),
    )
    monkeypatch.setattr(main, "AppCheckVerifier", RejectingVerifier)

    middleware = main.AnalysisSecurityMiddleware(inner_app)
    asyncio.run(middleware(_asgi_scope(path, token=token), receive, send))

    assert events == ["app_check_attempted"]
    status_code, headers, body = _asgi_response(sent)
    assert status_code == 401
    assert headers["cache-control"] == "no-store"
    assert body == APP_CHECK_ERROR


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_pure_asgi_root_path_missing_app_check_rejects_before_body_read(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receive_calls = 0
    sent: list[dict[str, object]] = []

    class RejectingVerifier:
        def __init__(self, *, required: bool, expected_app_id: str) -> None:
            assert required is True
            assert expected_app_id == EXPECTED_APP_ID

        def verify(self, received_token: str | None) -> None:
            assert received_token is None
            raise AppCheckInvalidError(PROVIDER_SENTINEL)

    async def receive() -> dict[str, object]:
        nonlocal receive_calls
        receive_calls += 1
        return {"type": "http.request", "body": b"private body", "more_body": False}

    async def inner_app(
        _scope: object,
        inner_receive: object,
        inner_send: object,
    ) -> None:
        await inner_receive()
        await inner_send({"type": "http.response.start", "status": 200, "headers": []})
        await inner_send({"type": "http.response.body", "body": b"{}"})

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    monkeypatch.setattr(
        main,
        "settings",
        _explicit_settings(
            app_check_required=True,
            firebase_app_id=EXPECTED_APP_ID,
        ),
    )
    monkeypatch.setattr(main, "AppCheckVerifier", RejectingVerifier)

    asyncio.run(
        main.AnalysisSecurityMiddleware(inner_app)(
            _asgi_scope(f"/prefix{path}", root_path="/prefix"),
            receive,
            send,
        )
    )

    assert receive_calls == 0
    status_code, headers, body = _asgi_response(sent)
    assert status_code == 401
    assert headers["cache-control"] == "no-store"
    assert body == APP_CHECK_ERROR


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_pure_asgi_valid_token_is_verified_off_loop_before_receive_and_parsing(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    sent: list[dict[str, object]] = []
    loop_thread = threading.get_ident()

    class AcceptingVerifier:
        def __init__(self, *, required: bool, expected_app_id: str) -> None:
            assert required is True
            assert expected_app_id == EXPECTED_APP_ID

        def verify(self, received_token: str | None) -> None:
            assert received_token == TOKEN_SENTINEL
            events.append("app_check_verified")
            assert threading.get_ident() != loop_thread
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()

    async def receive() -> dict[str, object]:
        events.append("receive")
        return {"type": "http.request", "body": b"valid body", "more_body": False}

    async def inner_app(
        _scope: object,
        inner_receive: object,
        inner_send: object,
    ) -> None:
        events.append("multipart_parse")
        await inner_receive()
        await inner_send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public")],
            }
        )
        await inner_send({"type": "http.response.body", "body": b"{}"})

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    monkeypatch.setattr(
        main,
        "settings",
        _explicit_settings(
            app_check_required=True,
            firebase_app_id=EXPECTED_APP_ID,
        ),
    )
    monkeypatch.setattr(main, "AppCheckVerifier", AcceptingVerifier)

    middleware = main.AnalysisSecurityMiddleware(inner_app)
    asyncio.run(
        middleware(
            _asgi_scope(path, token=TOKEN_SENTINEL),
            receive,
            send,
        )
    )

    assert events == ["app_check_verified", "multipart_parse", "receive"]
    status_code, headers, body = _asgi_response(sent)
    assert status_code == 200
    assert headers["cache-control"] == "no-store"
    assert body == {}


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_pure_asgi_disabled_mode_skips_verifier_and_proceeds(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    sent: list[dict[str, object]] = []

    class ForbiddenVerifier:
        def __init__(self, **_kwargs: object) -> None:
            raise AssertionError("disabled mode must not construct verifier")

    async def receive() -> dict[str, object]:
        events.append("receive")
        return {"type": "http.request", "body": b"local mock", "more_body": False}

    async def inner_app(
        _scope: object,
        inner_receive: object,
        inner_send: object,
    ) -> None:
        await inner_receive()
        await inner_send({"type": "http.response.start", "status": 204, "headers": []})
        await inner_send({"type": "http.response.body", "body": b""})

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    monkeypatch.setattr(main, "settings", _explicit_settings())
    monkeypatch.setattr(main, "AppCheckVerifier", ForbiddenVerifier)

    asyncio.run(
        main.AnalysisSecurityMiddleware(inner_app)(
            _asgi_scope(path),
            receive,
            send,
        )
    )

    assert events == ["receive"]
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 204
    assert dict(start["headers"])[b"cache-control"] == b"no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize("failure_stage", ["constructor", "verify"])
def test_pure_asgi_verifier_failures_are_safe_before_body_read(
    path: str,
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent: list[dict[str, object]] = []
    receive_calls = 0

    class FailingVerifier:
        def __init__(self, **_kwargs: object) -> None:
            if failure_stage == "constructor":
                raise RuntimeError(PROVIDER_SENTINEL)

        def verify(self, _token: str | None) -> None:
            raise RuntimeError(PROVIDER_SENTINEL)

    async def receive() -> dict[str, object]:
        nonlocal receive_calls
        receive_calls += 1
        return {"type": "http.request", "body": b"secret body", "more_body": False}

    async def inner_app(*_args: object) -> None:
        raise AssertionError("inner app must not run")

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    caplog.set_level(logging.INFO, logger="sumai.main")
    monkeypatch.setattr(
        main,
        "settings",
        _explicit_settings(
            app_check_required=True,
            firebase_app_id=EXPECTED_APP_ID,
        ),
    )
    monkeypatch.setattr(main, "AppCheckVerifier", FailingVerifier)

    asyncio.run(
        main.AnalysisSecurityMiddleware(inner_app)(
            _asgi_scope(path, token=TOKEN_SENTINEL),
            receive,
            send,
        )
    )

    assert receive_calls == 0
    status_code, headers, body = _asgi_response(sent)
    assert status_code == 500
    assert headers["cache-control"] == "no-store"
    assert body == {
        "error": "INTERNAL_ERROR",
        "message": PUBLIC_ERRORS["INTERNAL_ERROR"][1],
    }
    assert PROVIDER_SENTINEL not in _log_details(caplog)


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_pure_asgi_inner_response_construction_failure_is_safe_and_no_store(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent: list[dict[str, object]] = []

    def build_inner_response() -> None:
        raise RuntimeError(PROVIDER_SENTINEL)

    async def inner_app(*_args: object) -> None:
        build_inner_response()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    caplog.set_level(logging.INFO, logger="sumai.main")
    monkeypatch.setattr(main, "settings", _explicit_settings())

    asyncio.run(
        main.AnalysisSecurityMiddleware(inner_app)(
            _asgi_scope(path),
            receive,
            send,
        )
    )

    status_code, headers, body = _asgi_response(sent)
    assert status_code == 500
    assert headers["cache-control"] == "no-store"
    assert body == {
        "error": "INTERNAL_ERROR",
        "message": PUBLIC_ERRORS["INTERNAL_ERROR"][1],
    }
    assert PROVIDER_SENTINEL not in _log_details(caplog)


def test_pure_asgi_does_not_send_second_response_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []

    async def inner_app(
        _scope: object,
        _receive: object,
        inner_send: object,
    ) -> None:
        await inner_send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError(PROVIDER_SENTINEL)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message.copy())

    monkeypatch.setattr(main, "settings", _explicit_settings())

    with pytest.raises(RuntimeError, match=PROVIDER_SENTINEL):
        asyncio.run(
            main.AnalysisSecurityMiddleware(inner_app)(
                _asgi_scope("/api/v1/analyze"),
                receive,
                send,
            )
        )

    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert dict(starts[0]["headers"])[b"cache-control"] == b"no-store"


def _request(
    path: str,
    *,
    image_bytes: bytes | None = None,
    content_type: str | None = "image/png",
    token: str | None = None,
    data: dict[str, str] | None = None,
) -> object:
    headers = {"X-Firebase-AppCheck": token} if token is not None else {}
    file_tuple: tuple[object, ...]
    if content_type is None:
        file_tuple = (
            "room.bin",
            image_bytes if image_bytes is not None else _image_bytes(),
            None,
        )
    else:
        file_tuple = (
            "room.bin",
            image_bytes if image_bytes is not None else _image_bytes(),
            content_type,
        )
    return TestClient(main.app, raise_server_exceptions=False).post(
        path,
        headers=headers,
        files={"image": file_tuple},
        data=data or {"room_hint": "auto", "mock": "true"},
    )


def _log_details(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(repr(record.__dict__) for record in caplog.records)


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize(
    ("token", "verified_result"),
    [
        pytest.param(None, {"app_id": EXPECTED_APP_ID}, id="missing"),
        pytest.param("", {"app_id": EXPECTED_APP_ID}, id="blank"),
        pytest.param(TOKEN_SENTINEL, ValueError(PROVIDER_SENTINEL), id="invalid"),
        pytest.param(TOKEN_SENTINEL, {"claims": PROVIDER_SENTINEL}, id="malformed"),
        pytest.param(TOKEN_SENTINEL, RuntimeError(PROVIDER_SENTINEL), id="expired"),
        pytest.param(
            TOKEN_SENTINEL,
            {"app_id": f"wrong:{PROVIDER_SENTINEL}"},
            id="wrong-app",
        ),
    ],
)
def test_app_check_rejections_are_safe_and_precede_analysis_and_intake(
    path: str,
    token: str | None,
    verified_result: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    protected_settings = _explicit_settings(
        app_check_required=True,
        firebase_app_id=EXPECTED_APP_ID,
    )
    fake_orchestrator = RecordingOrchestrator()
    intake = AsyncMock(side_effect=AssertionError("intake must not run"))

    def verify_token(_token: str) -> object:
        if isinstance(verified_result, BaseException):
            raise verified_result
        return verified_result

    monkeypatch.setattr(main, "settings", protected_settings)
    monkeypatch.setattr(main, "orchestrator", fake_orchestrator)
    monkeypatch.setattr(orchestrator_module, "read_upload_bytes", intake)
    monkeypatch.setattr(app_check, "_verify_with_firebase", verify_token)

    response = _request(path, token=token)

    assert response.status_code == 401
    assert response.json() == APP_CHECK_ERROR
    assert response.headers["cache-control"] == "no-store"
    assert fake_orchestrator.calls == []
    intake.assert_not_awaited()
    visible = response.text + _log_details(caplog)
    for forbidden in (
        TOKEN_SENTINEL,
        EXPECTED_APP_ID,
        PROVIDER_SENTINEL,
        "claims",
        "ValueError",
        "RuntimeError",
    ):
        assert forbidden not in visible


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_valid_app_check_token_reaches_orchestrator_once_and_response_is_private(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected_settings = _explicit_settings(
        app_check_required=True,
        firebase_app_id=EXPECTED_APP_ID,
    )
    fake_orchestrator = RecordingOrchestrator()
    monkeypatch.setattr(main, "settings", protected_settings)
    monkeypatch.setattr(main, "orchestrator", fake_orchestrator)
    monkeypatch.setattr(
        app_check,
        "_verify_with_firebase",
        lambda _token: {"app_id": EXPECTED_APP_ID},
    )

    response = _request(path, token=TOKEN_SENTINEL)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "_cache_hit" not in response.json()
    assert len(fake_orchestrator.calls) == 1


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_disabled_app_check_accepts_no_token_without_verifier(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
    _hermetic_native_api_environment: AsyncMock,
) -> None:
    explicit = _explicit_settings(app_check_required=False, firebase_app_id="")
    fake_orchestrator = RecordingOrchestrator()
    monkeypatch.setattr(main, "settings", explicit)
    monkeypatch.setattr(config_module, "settings", explicit)
    monkeypatch.setattr(orchestrator_module, "settings", explicit)
    monkeypatch.setattr(gemini_module, "settings", explicit)
    monkeypatch.setattr(main, "orchestrator", fake_orchestrator)

    response = _request(path)

    assert response.status_code == 200
    assert response.json()["mode"] == "mock"
    assert response.headers["cache-control"] == "no-store"
    assert len(fake_orchestrator.calls) == 1
    _hermetic_native_api_environment.assert_not_awaited()


def test_disabled_app_check_preserves_one_actual_local_mock_compatibility_path(
    monkeypatch: pytest.MonkeyPatch,
    _hermetic_native_api_environment: AsyncMock,
) -> None:
    explicit = _explicit_settings(app_check_required=False, firebase_app_id="")
    monkeypatch.setattr(main, "settings", explicit)
    monkeypatch.setattr(config_module, "settings", explicit)
    monkeypatch.setattr(orchestrator_module, "settings", explicit)
    monkeypatch.setattr(gemini_module, "settings", explicit)

    response = _request("/analyze")

    assert response.status_code == 200
    assert response.json()["mode"] == "mock"
    assert response.headers["cache-control"] == "no-store"
    _hermetic_native_api_environment.assert_not_awaited()


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_app_check_verification_runs_off_the_event_loop(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected_settings = _explicit_settings(
        app_check_required=True,
        firebase_app_id=EXPECTED_APP_ID,
    )
    events: dict[str, object] = {}

    class RecordingVerifier:
        def __init__(self, *, required: bool, expected_app_id: str) -> None:
            assert required is True
            assert expected_app_id == EXPECTED_APP_ID

        def verify(self, _token: str | None) -> None:
            events["verify_thread"] = threading.get_ident()
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                events["verify_has_loop"] = False
            else:
                events["verify_has_loop"] = True

    fake_orchestrator = RecordingOrchestrator()

    async def analyze(*args: object, **kwargs: object) -> object:
        events["route_thread"] = threading.get_ident()
        events["route_has_loop"] = asyncio.get_running_loop().is_running()
        return await fake_orchestrator.analyze(*args, **kwargs)

    monkeypatch.setattr(main, "settings", protected_settings)
    monkeypatch.setattr(main, "AppCheckVerifier", RecordingVerifier)
    monkeypatch.setattr(main, "orchestrator", SimpleNamespace(analyze=analyze))

    response = _request(path, token=TOKEN_SENTINEL)

    assert response.status_code == 200
    assert events["verify_has_loop"] is False
    assert events["route_has_loop"] is True
    assert events["verify_thread"] != events["route_thread"]


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize("content_type", [None, "application/octet-stream", "image/gif"])
def test_analysis_rejects_non_allowlisted_mime_as_invalid_image(
    path: str,
    content_type: str | None,
) -> None:
    response = _request(path, content_type=content_type)

    expected_status, expected_message = PUBLIC_ERRORS["INVALID_IMAGE"]
    assert response.status_code == expected_status
    assert response.json() == {
        "error": "INVALID_IMAGE",
        "message": expected_message,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_invalid_pixels_are_public_invalid_image(path: str) -> None:
    response = _request(path, image_bytes=b"not pixels")

    expected_status, expected_message = PUBLIC_ERRORS["INVALID_IMAGE"]
    assert response.status_code == expected_status
    assert response.json() == {
        "error": "INVALID_IMAGE",
        "message": expected_message,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize("limit_kind", ["bytes", "pixels"])
def test_image_limits_are_public_payload_too_large(
    path: str,
    limit_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited_settings = _explicit_settings(
        max_upload_bytes=1 if limit_kind == "bytes" else 1024 * 1024,
        max_source_pixels=1 if limit_kind == "pixels" else 25_000_000,
    )
    monkeypatch.setattr(orchestrator_module, "settings", limited_settings)

    response = _request(path)

    expected_status, expected_message = PUBLIC_ERRORS["IMAGE_TOO_LARGE"]
    assert response.status_code == expected_status
    assert response.json() == {
        "error": "IMAGE_TOO_LARGE",
        "message": expected_message,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize(
    "request_kwargs",
    [
        pytest.param({"files": {}}, id="missing-image"),
        pytest.param(
            {
                "files": {"image": ("room.png", _image_bytes(), "image/png")},
                "data": {"mock": "not-a-boolean"},
            },
            id="invalid-form-field",
        ),
    ],
)
def test_analysis_request_validation_is_flat_invalid_image(
    path: str,
    request_kwargs: dict[str, object],
) -> None:
    response = TestClient(main.app, raise_server_exceptions=False).post(
        path,
        **request_kwargs,
    )

    expected_status, expected_message = PUBLIC_ERRORS["INVALID_IMAGE"]
    assert response.status_code == expected_status
    assert response.json() == {
        "error": "INVALID_IMAGE",
        "message": expected_message,
    }
    assert "detail" not in response.json()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_malformed_multipart_is_flat_invalid_image(path: str) -> None:
    response = TestClient(main.app, raise_server_exceptions=False).post(
        path,
        content=b"malformed multipart",
        headers={"content-type": "multipart/form-data; boundary=missing"},
    )

    expected_status, expected_message = PUBLIC_ERRORS["INVALID_IMAGE"]
    assert response.status_code == expected_status
    assert response.json() == {
        "error": "INVALID_IMAGE",
        "message": expected_message,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize("failure_kind", ["request-validation", "http-400"])
def test_analysis_error_handlers_normalize_nonempty_root_path(
    path: str,
    failure_kind: str,
) -> None:
    client = TestClient(
        main.app,
        raise_server_exceptions=False,
        root_path="/prefix",
    )
    if failure_kind == "request-validation":
        response = client.post(f"/prefix{path}", files={})
    else:
        response = client.post(
            f"/prefix{path}",
            content=b"malformed multipart",
            headers={"content-type": "multipart/form-data; boundary=missing"},
        )

    expected_status, expected_message = PUBLIC_ERRORS["INVALID_IMAGE"]
    assert response.status_code == expected_status
    assert response.json() == {
        "error": "INVALID_IMAGE",
        "message": expected_message,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize(
    ("raised", "error_code"),
    [
        pytest.param(InvalidImageError(), "INVALID_IMAGE", id="invalid-image"),
        pytest.param(ImageTooLargeError(), "IMAGE_TOO_LARGE", id="image-too-large"),
        pytest.param(ServiceLimitedError(PROVIDER_SENTINEL), "SERVICE_LIMITED", id="limited"),
        pytest.param(
            GeminiUnavailableError(PROVIDER_SENTINEL),
            "GEMINI_UNAVAILABLE",
            id="gemini-unavailable",
        ),
        pytest.param(ValueError(PROVIDER_SENTINEL), "INTERNAL_ERROR", id="value-error"),
        pytest.param(RuntimeError(PROVIDER_SENTINEL), "INTERNAL_ERROR", id="unexpected"),
    ],
)
def test_analysis_exception_mapping_is_exact_private_and_no_store(
    path: str,
    raised: Exception,
    error_code: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.main")
    analyze = AsyncMock(side_effect=raised)
    monkeypatch.setattr(main, "orchestrator", SimpleNamespace(analyze=analyze))

    response = _request(path)

    expected_status, expected_message = PUBLIC_ERRORS[error_code]
    assert response.status_code == expected_status
    assert response.json() == {"error": error_code, "message": expected_message}
    assert response.headers["cache-control"] == "no-store"
    assert PROVIDER_SENTINEL not in response.text
    assert PROVIDER_SENTINEL not in _log_details(caplog)
    analyze.assert_awaited_once()


def test_openapi_documents_runtime_header_and_complete_public_responses() -> None:
    document = TestClient(main.app).get("/openapi.json").json()
    paths = document["paths"]

    assert "/api/v1/analyze" in paths
    assert "/analyze" not in paths
    operation = paths["/api/v1/analyze"]["post"]
    headers = [
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
        and parameter["name"].lower() == "x-firebase-appcheck"
    ]
    assert len(headers) == 1
    assert headers[0]["required"] is True
    assert headers[0]["schema"] == {"type": "string"}
    assert "production" in headers[0]["description"].lower()
    assert "app check" in headers[0]["description"].lower()

    responses = operation["responses"]
    assert set(responses) == {"200", "400", "401", "413", "429", "500", "503"}
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalysisResponse"
    }
    for status_code in ("400", "401", "413", "429", "500", "503"):
        assert responses[status_code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/PublicErrorResponse"
        }
    assert "422" not in responses
    public_error_schema = document["components"]["schemas"]["PublicErrorResponse"]
    assert set(public_error_schema["required"]) == {"error", "message"}
    assert public_error_schema["properties"]["error"]["type"] == "string"
    assert set(public_error_schema["properties"]["error"]["enum"]) == {
        "INVALID_IMAGE",
        "APP_CHECK_INVALID",
        "IMAGE_TOO_LARGE",
        "SERVICE_LIMITED",
        "GEMINI_UNAVAILABLE",
        "INTERNAL_ERROR",
    }
    assert public_error_schema["properties"]["message"]["type"] == "string"


def test_public_image_too_large_status_remains_numeric_413() -> None:
    assert main.PUBLIC_ERRORS["IMAGE_TOO_LARGE"][0] == 413


def test_sanitized_output_is_rgb_png() -> None:
    image, safe_png = image_intake.read_and_sanitize_image(
        _image_bytes(mode="RGBA", size=(3, 2))
    )

    assert image.mode == "RGB"
    assert safe_png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(safe_png)) as reopened:
        reopened.load()
        assert reopened.format == "PNG"
        assert reopened.mode == "RGB"
