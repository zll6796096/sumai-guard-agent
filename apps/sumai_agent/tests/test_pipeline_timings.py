from __future__ import annotations

import asyncio
import io
import logging
import re
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models import VisionFacts
from app.services.orchestrator import AnalysisOrchestrator


TIMING_KEYS = {
    "intake",
    "memo_lookup",
    "vision",
    "ontology",
    "render",
    "report",
    "serialize",
    "total",
}


class CountingVision:
    def __init__(self, *, not_applicable: bool = False) -> None:
        self.calls = 0
        self.not_applicable = not_applicable

    async def analyze(self, **_kwargs: object) -> tuple[VisionFacts, str]:
        self.calls += 1
        return (
            VisionFacts(
                environment="non_home" if self.not_applicable else "home",
                room_type="unknown" if self.not_applicable else "genkan",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
            ),
            "mock",
        )


class IncrementingClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.01
        return self.now


def _png_bytes() -> bytes:
    image = Image.new("RGB", (100, 80), (236, 232, 224))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(contents: bytes | None = None) -> UploadFile:
    return UploadFile(filename="room.png", file=io.BytesIO(contents or _png_bytes()))


def _subject(monkeypatch: pytest.MonkeyPatch, vision: CountingVision) -> AnalysisOrchestrator:
    from app.services import orchestrator as orchestrator_module

    monkeypatch.setattr(
        orchestrator_module,
        "settings",
        SimpleNamespace(
            mock_mode=True,
            require_real_gemini=False,
            gemini_api_key="",
            gemini_model="gemini-test",
            result_memo_ttl_seconds=300,
            result_memo_max_items=128,
        ),
    )
    return AnalysisOrchestrator(vision=vision)


def test_post_mock_image_returns_complete_non_negative_stage_timings() -> None:
    response = TestClient(app).post(
        "/analyze",
        data={"room_hint": "genkan", "mock": "true"},
        files={"image": ("room.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    timings = response.json()["stage_timings_ms"]
    assert set(timings) == TIMING_KEYS
    assert "cache_hit" not in response.json()
    assert all(isinstance(value, int) and value >= 0 for value in timings.values())
    assert timings["total"] == sum(value for key, value in timings.items() if key != "total")


def test_memo_hit_zeroes_shared_stages_renders_again_and_logs_cache_hit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def run() -> None:
        vision = CountingVision()
        subject = _subject(monkeypatch, vision)
        renders = 0
        original_render = subject.visual_renderer.render

        def counted_render(*args: object, **kwargs: object) -> tuple[str, str]:
            nonlocal renders
            renders += 1
            return original_render(*args, **kwargs)

        monkeypatch.setattr(subject.visual_renderer, "render", counted_render)
        with caplog.at_level(logging.INFO, logger="sumai.orchestrator"):
            first = await subject.analyze(_upload(), room_hint="genkan", mock=True)
            second = await subject.analyze(_upload(), room_hint="genkan", mock=True)

        assert vision.calls == 1
        assert renders == 2
        assert first.stage_timings_ms["vision"] >= 0
        assert second.stage_timings_ms["vision"] == 0
        assert second.stage_timings_ms["ontology"] == 0
        assert second.stage_timings_ms["report"] == 0
        assert second.stage_timings_ms["render"] >= 0
        complete = [record for record in caplog.records if record.message == "analysis_complete"]
        assert getattr(complete[-1], "cache_hit") is True

    asyncio.run(run())


def test_coalesced_follower_attributes_wait_to_memo_lookup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class BlockingVision(CountingVision):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(self, **kwargs: object) -> tuple[VisionFacts, str]:
            self.started.set()
            await self.release.wait()
            return await super().analyze(**kwargs)

    async def run() -> None:
        vision = BlockingVision()
        subject = _subject(monkeypatch, vision)
        original_get_or_compute = subject.result_memo.get_or_compute
        memo_entries = 0
        follower_entered_memo = asyncio.Event()

        async def track_memo_entry(*args: object, **kwargs: object) -> object:
            nonlocal memo_entries
            memo_entries += 1
            if memo_entries == 2:
                follower_entered_memo.set()
            return await original_get_or_compute(*args, **kwargs)

        monkeypatch.setattr(subject.result_memo, "get_or_compute", track_memo_entry)
        with caplog.at_level(logging.INFO, logger="sumai.orchestrator"):
            owner = asyncio.create_task(subject.analyze(_upload(), room_hint="genkan", mock=True))
            await vision.started.wait()
            follower = asyncio.create_task(subject.analyze(_upload(), room_hint="genkan", mock=True))
            await follower_entered_memo.wait()
            vision.release.set()
            first, second = await asyncio.gather(owner, follower)

        assert vision.calls == 1
        follower_response = next(
            response for response in (first, second) if response.stage_timings_ms["vision"] == 0
        )
        assert follower_response.stage_timings_ms["ontology"] == 0
        assert follower_response.stage_timings_ms["report"] == 0
        assert follower_response.stage_timings_ms["memo_lookup"] >= 0
        complete = [record for record in caplog.records if record.message == "analysis_complete"]
        assert all(getattr(record, "cache_hit") is False for record in complete)

    asyncio.run(run())


def test_factory_stages_are_measured_around_real_factory_work(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import orchestrator as orchestrator_module

        subject = _subject(monkeypatch, CountingVision())
        monkeypatch.setattr(orchestrator_module.time, "monotonic", IncrementingClock())
        response = await subject.analyze(_upload(), room_hint="genkan", mock=True)

        assert response.stage_timings_ms["vision"] > 0
        assert response.stage_timings_ms["ontology"] > 0
        assert response.stage_timings_ms["report"] > 0

    asyncio.run(run())


def test_intake_and_visual_rendering_use_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import orchestrator as orchestrator_module

        subject = _subject(monkeypatch, CountingVision())
        threaded_calls: list[str] = []
        intake_calls = 0
        original_to_thread = asyncio.to_thread
        original_intake = orchestrator_module.read_and_sanitize_image

        def counted_intake(raw_bytes: bytes) -> tuple[Image.Image, bytes]:
            nonlocal intake_calls
            intake_calls += 1
            return original_intake(raw_bytes)

        async def recording_to_thread(func: object, /, *args: object, **kwargs: object) -> object:
            threaded_calls.append(getattr(func, "__name__", ""))
            return await original_to_thread(func, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(orchestrator_module, "read_and_sanitize_image", counted_intake)
        monkeypatch.setattr(orchestrator_module.asyncio, "to_thread", recording_to_thread)
        await subject.analyze(_upload(), room_hint="genkan", mock=True)

        assert intake_calls == 1
        assert "_prepare_image" in threaded_calls
        assert "render" in threaded_calls

    asyncio.run(run())


def test_not_applicable_visual_rendering_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import orchestrator as orchestrator_module

        subject = _subject(monkeypatch, CountingVision(not_applicable=True))
        threaded_calls: list[str] = []
        original_to_thread = asyncio.to_thread

        async def recording_to_thread(func: object, /, *args: object, **kwargs: object) -> object:
            threaded_calls.append(getattr(func, "__name__", ""))
            return await original_to_thread(func, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(orchestrator_module.asyncio, "to_thread", recording_to_thread)
        await subject.analyze(_upload(), room_hint="genkan", mock=True)

        assert "render_not_applicable" in threaded_calls

    asyncio.run(run())


def test_analysis_complete_logs_allowlisted_timings_without_sensitive_identity_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def run() -> None:
        subject = _subject(monkeypatch, CountingVision())
        with caplog.at_level(logging.INFO, logger="sumai.orchestrator"):
            response = await subject.analyze(_upload(), room_hint="genkan", mock=True)

        complete = next(record for record in caplog.records if record.message == "analysis_complete")
        assert getattr(complete, "stage_timings_ms") == response.stage_timings_ms
        rendered = "\n".join(repr(record.__dict__) for record in caplog.records)
        assert "result_key" not in rendered
        assert "semantic_hash" not in rendered
        assert "pixel_digest" not in rendered
        assert response.annotated_image_base64 not in rendered
        assert re.search(r"\b[0-9a-f]{64}\b", rendered) is None

    asyncio.run(run())
