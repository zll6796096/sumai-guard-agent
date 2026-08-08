from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import threading
import warnings

import pytest
from fastapi import UploadFile
from PIL import Image, JpegImagePlugin, PngImagePlugin

from app.errors import ImageTooLargeError, InvalidImageError
from app.services import image_intake


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
