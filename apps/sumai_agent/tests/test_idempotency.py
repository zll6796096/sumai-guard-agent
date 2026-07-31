from __future__ import annotations

import asyncio
import io
from dataclasses import fields
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from PIL import Image

from app.config import Settings
from app.models import ActionPlan, VisionFacts
from app.services.orchestrator import AnalysisOrchestrator, ComputedAnalysis
from app.services.result_memo import AsyncResultMemo


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_result_memo_caches_deep_copies_until_ttl_expires() -> None:
    async def run() -> None:
        clock = FakeClock()
        memo: AsyncResultMemo[dict[str, list[int]]] = AsyncResultMemo(
            max_items=2, ttl_seconds=5, clock=clock
        )
        calls = 0

        async def factory() -> tuple[dict[str, list[int]], bool]:
            nonlocal calls
            calls += 1
            return {"items": [calls]}, True

        first, first_hit = await memo.get_or_compute("same", factory)
        first["items"].append(99)
        second, second_hit = await memo.get_or_compute("same", factory)
        clock.now = 5
        third, third_hit = await memo.get_or_compute("same", factory)

        assert first_hit is False
        assert second_hit is True
        assert third_hit is False
        assert second == {"items": [1]}
        assert third == {"items": [2]}
        assert calls == 2

    asyncio.run(run())


def test_result_memo_coalesces_concurrent_requests_and_isolates_callers() -> None:
    async def run() -> None:
        memo: AsyncResultMemo[dict[str, list[int]]] = AsyncResultMemo(max_items=2, ttl_seconds=5)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def factory() -> tuple[dict[str, list[int]], bool]:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"items": [1]}, True

        tasks = [asyncio.create_task(memo.get_or_compute("same", factory)) for _ in range(5)]
        await started.wait()
        release.set()
        results = await asyncio.gather(*tasks)
        for value, hit in results:
            assert hit is False
            value["items"].append(2)

        cached, cached_hit = await memo.get_or_compute("same", factory)
        assert calls == 1
        assert cached_hit is True
        assert cached == {"items": [1]}

    asyncio.run(run())


def test_result_memo_lru_refreshes_on_read_and_evicts_oldest() -> None:
    async def run() -> None:
        memo: AsyncResultMemo[str] = AsyncResultMemo(max_items=2, ttl_seconds=5)
        calls: dict[str, int] = {}

        def factory_for(key: str):
            async def factory() -> tuple[str, bool]:
                calls[key] = calls.get(key, 0) + 1
                return f"{key}:{calls[key]}", True

            return factory

        await memo.get_or_compute("a", factory_for("a"))
        await memo.get_or_compute("b", factory_for("b"))
        assert (await memo.get_or_compute("a", factory_for("a")))[1] is True
        await memo.get_or_compute("c", factory_for("c"))
        assert (await memo.get_or_compute("a", factory_for("a")))[1] is True
        value_b, hit_b = await memo.get_or_compute("b", factory_for("b"))

        assert hit_b is False
        assert value_b == "b:2"

    asyncio.run(run())


def test_result_memo_does_not_persist_non_cacheable_values() -> None:
    async def run() -> None:
        memo: AsyncResultMemo[int] = AsyncResultMemo(max_items=2, ttl_seconds=5)
        calls = 0

        async def factory() -> tuple[int, bool]:
            nonlocal calls
            calls += 1
            return calls, False

        assert await memo.get_or_compute("same", factory) == (1, False)
        assert await memo.get_or_compute("same", factory) == (2, False)

    asyncio.run(run())


def test_result_memo_cleans_failed_and_cancelled_in_flight_work_without_cancelling_waiters() -> None:
    async def run() -> None:
        memo: AsyncResultMemo[str] = AsyncResultMemo(max_items=2, ttl_seconds=5)
        calls = 0

        async def failing_factory() -> tuple[str, bool]:
            nonlocal calls
            calls += 1
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await memo.get_or_compute("failure", failing_factory)

        async def retry_factory() -> tuple[str, bool]:
            nonlocal calls
            calls += 1
            return "recovered", True

        assert await memo.get_or_compute("failure", retry_factory) == ("recovered", False)

        async def cancelled_factory() -> tuple[str, bool]:
            nonlocal calls
            calls += 1
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await memo.get_or_compute("factory-cancelled", cancelled_factory)
        assert await memo.get_or_compute("factory-cancelled", retry_factory) == ("recovered", False)

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_factory() -> tuple[str, bool]:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "shared", True

        cancelled_waiter = asyncio.create_task(memo.get_or_compute("cancel", slow_factory))
        survivor = asyncio.create_task(memo.get_or_compute("cancel", slow_factory))
        await started.wait()
        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_waiter
        release.set()
        assert await survivor == ("shared", False)
        assert calls == 5

    asyncio.run(run())


def test_result_memo_observes_failure_after_its_only_waiter_cancels() -> None:
    async def run() -> None:
        memo: AsyncResultMemo[str] = AsyncResultMemo(max_items=2, ttl_seconds=5)
        started = asyncio.Event()
        release = asyncio.Event()
        unhandled: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        def capture_unhandled(
            _loop: asyncio.AbstractEventLoop, context: dict[str, object]
        ) -> None:
            unhandled.append(context)

        async def detached_failure() -> tuple[str, bool]:
            started.set()
            await release.wait()
            raise RuntimeError("detached failure")

        async def retry() -> tuple[str, bool]:
            return "recovered", True

        loop.set_exception_handler(capture_unhandled)
        try:
            waiter = asyncio.create_task(memo.get_or_compute("same", detached_failure))
            await started.wait()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            release.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

            assert unhandled == []
            assert await memo.get_or_compute("same", retry) == ("recovered", False)
        finally:
            loop.set_exception_handler(previous_handler)

    asyncio.run(run())


def test_result_memo_settings_reject_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="result_memo_ttl_seconds"):
        Settings(result_memo_ttl_seconds=0)
    with pytest.raises(ValueError, match="result_memo_max_items"):
        Settings(result_memo_max_items=0)


class CountingVision:
    def __init__(self, mode: str = "mock") -> None:
        self.calls = 0
        self.mode = mode

    async def analyze(self, **_kwargs: object) -> tuple[VisionFacts, str]:
        self.calls += 1
        return (
            VisionFacts(
                environment="home",
                room_type="genkan",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
            ),
            self.mode,
        )


def _png_bytes(*, compress_level: int = 6) -> bytes:
    image = Image.new("RGB", (100, 80), (236, 232, 224))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=compress_level)
    return buffer.getvalue()


def _upload(contents: bytes) -> UploadFile:
    return UploadFile(filename="room.png", file=io.BytesIO(contents))


def _fresh_orchestrator(monkeypatch: pytest.MonkeyPatch, vision: CountingVision) -> AnalysisOrchestrator:
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


def test_orchestrator_reuses_semantics_but_renders_each_request(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        vision = CountingVision()
        subject = _fresh_orchestrator(monkeypatch, vision)
        renders = 0
        original_render = subject.visual_renderer.render

        def counted_render(*args: object, **kwargs: object) -> tuple[str, str]:
            nonlocal renders
            renders += 1
            return original_render(*args, **kwargs)

        monkeypatch.setattr(subject.visual_renderer, "render", counted_render)
        first = await subject.analyze(_upload(_png_bytes(compress_level=1)), room_hint="genkan", mock=True)
        second = await subject.analyze(_upload(_png_bytes(compress_level=9)), room_hint="genkan", mock=True)

        assert vision.calls == 1
        assert renders == 2
        assert first.analysis_id != second.analysis_id
        assert first.result_key == second.result_key
        assert first.semantic_hash == second.semantic_hash
        assert first.findings == second.findings
        assert first.action_plan == second.action_plan
        assert first.annotated_image_base64 and second.annotated_image_base64

    asyncio.run(run())


def test_orchestrator_coalesces_concurrent_same_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class BlockingVision(CountingVision):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(self, **kwargs: object) -> tuple[VisionFacts, str]:
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return (
                VisionFacts(
                    environment="home",
                    room_type="genkan",
                    visible_regions=[],
                    entities=[],
                    feature_observations=[],
                    relationships=[],
                ),
                "mock",
            )

    async def run() -> None:
        vision = BlockingVision()
        subject = _fresh_orchestrator(monkeypatch, vision)
        first_task = asyncio.create_task(
            subject.analyze(_upload(_png_bytes()), room_hint="genkan", mock=True)
        )
        await vision.started.wait()
        second_task = asyncio.create_task(
            subject.analyze(_upload(_png_bytes()), room_hint="genkan", mock=True)
        )
        await asyncio.sleep(0)
        vision.release.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert vision.calls == 1
        assert first.analysis_id != second.analysis_id
        assert first.result_key == second.result_key
        assert first.semantic_hash == second.semantic_hash

    asyncio.run(run())


def test_orchestrator_separates_room_and_execution_policy_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        vision = CountingVision()
        subject = _fresh_orchestrator(monkeypatch, vision)
        image = _png_bytes()
        forced = await subject.analyze(_upload(image), room_hint="genkan", mock=True)
        room_changed = await subject.analyze(_upload(image), room_hint="bathroom", mock=True)
        configured = await subject.analyze(_upload(image), room_hint="genkan", mock=False)

        assert len({forced.result_key, room_changed.result_key, configured.result_key}) == 3
        assert vision.calls == 3

    asyncio.run(run())


def test_fallback_is_not_cached_and_strict_failure_does_not_poison_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        fallback = CountingVision(mode="gemini_fallback(provider_error)")
        subject = _fresh_orchestrator(monkeypatch, fallback)
        image = _png_bytes()
        await subject.analyze(_upload(image), room_hint="genkan", mock=True)
        await subject.analyze(_upload(image), room_hint="genkan", mock=True)
        assert fallback.calls == 2

        strict = CountingVision()
        strict_subject = _fresh_orchestrator(monkeypatch, strict)
        attempts = 0

        async def fail_once(**_kwargs: object) -> tuple[VisionFacts, str]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("strict provider unavailable")
            return await CountingVision().analyze()

        strict.analyze = fail_once  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="strict provider unavailable"):
            await strict_subject.analyze(_upload(image), room_hint="genkan", mock=True)
        await strict_subject.analyze(_upload(image), room_hint="genkan", mock=True)
        assert attempts == 2

    asyncio.run(run())


def test_computed_analysis_contains_only_structured_semantic_values() -> None:
    forbidden_fragments = ("image", "base64", "pixel", "digest", "result_key", "analysis_id")
    assert all(
        fragment not in field.name.lower()
        for field in fields(ComputedAnalysis)
        for fragment in forbidden_fragments
    )

    computed = ComputedAnalysis(
        response_room="genkan",
        overall_risk="low",
        findings=[],
        action_plan=ActionPlan(),
        reports={"risk_summary_markdown": "結果"},
        mode="mock",
        model_name="N/A",
        semantic_hash="semantic",
        is_home_environment=True,
        not_applicable_reason_ja=None,
        is_not_applicable=False,
    )

    def contains_bytes(value: object) -> bool:
        if isinstance(value, bytes):
            return True
        if isinstance(value, dict):
            return any(contains_bytes(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(contains_bytes(item) for item in value)
        return False

    assert contains_bytes(computed.__dict__) is False
