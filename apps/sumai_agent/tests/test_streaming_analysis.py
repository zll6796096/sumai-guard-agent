from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Callable

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models import AnalysisResponse, VisionFacts
from app.services.analysis_stream import stream_analysis
from app.services.orchestrator import AnalysisOrchestrator


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class DeterministicVision:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, **_: object) -> tuple[VisionFacts, str]:
        self.calls += 1
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


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.asyncio
async def test_orchestrator_emits_real_stages_in_order(
    upload_factory: Callable[[], UploadFile],
) -> None:
    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    response = await AnalysisOrchestrator(
        vision=DeterministicVision()  # type: ignore[arg-type]
    ).analyze(
        upload=upload_factory(),
        room_hint="toilet",
        mock=False,
        progress=progress,
    )

    assert response.room_type == "toilet"
    assert stages == ["intake_complete", "vision_complete"]


@pytest.mark.asyncio
async def test_cache_hit_still_reports_intake_and_semantic_readiness(
    upload_factory: Callable[[], UploadFile],
) -> None:
    vision = DeterministicVision()
    orchestrator = AnalysisOrchestrator(vision=vision)  # type: ignore[arg-type]
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
    assert vision.calls == 1
    assert stages == ["intake_complete", "vision_complete"]


@pytest.mark.asyncio
async def test_coalesced_requests_receive_request_local_stage_events(
    upload_factory: Callable[[], UploadFile],
) -> None:
    class BlockingVision(DeterministicVision):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(self, **kwargs: object) -> tuple[VisionFacts, str]:
            self.started.set()
            await self.release.wait()
            return await super().analyze(**kwargs)

    vision = BlockingVision()
    orchestrator = AnalysisOrchestrator(vision=vision)  # type: ignore[arg-type]
    owner_stages: list[str] = []
    follower_stages: list[str] = []

    async def owner_progress(stage: str) -> None:
        owner_stages.append(stage)

    async def follower_progress(stage: str) -> None:
        follower_stages.append(stage)

    owner = asyncio.create_task(
        orchestrator.analyze(
            upload=upload_factory(),
            room_hint="toilet",
            progress=owner_progress,
        )
    )
    await vision.started.wait()
    follower = asyncio.create_task(
        orchestrator.analyze(
            upload=upload_factory(),
            room_hint="toilet",
            progress=follower_progress,
        )
    )
    await asyncio.sleep(0)
    vision.release.set()
    await asyncio.gather(owner, follower)

    assert vision.calls == 1
    assert owner_stages == ["intake_complete", "vision_complete"]
    assert follower_stages == ["intake_complete", "vision_complete"]


@pytest.mark.asyncio
async def test_stream_closes_its_request_local_upload(
    upload_factory: Callable[[], UploadFile],
) -> None:
    upload = upload_factory()
    events = [
        json.loads(line)
        async for line in stream_analysis(
            AnalysisOrchestrator(
                vision=DeterministicVision()  # type: ignore[arg-type]
            ),
            upload,
            "toilet",
            False,
        )
    ]

    assert events[-1]["type"] == "result"
    assert upload.file.closed is True


@pytest.mark.asyncio
async def test_last_stream_disconnect_cancels_shared_vision_worker(
    upload_factory: Callable[[], UploadFile],
) -> None:
    class CancellableVision(DeterministicVision):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def analyze(self, **_: object) -> tuple[VisionFacts, str]:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    vision = CancellableVision()
    stream = stream_analysis(
        AnalysisOrchestrator(vision=vision),  # type: ignore[arg-type]
        upload_factory(),
        "toilet",
        False,
    )

    intake = json.loads(await anext(stream))
    assert intake == {"type": "progress", "stage": "intake_complete"}
    await vision.started.wait()
    await stream.aclose()

    await asyncio.wait_for(vision.cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_owner_stream_disconnect_keeps_worker_for_follower(
    upload_factory: Callable[[], UploadFile],
) -> None:
    class SharedVision(DeterministicVision):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def analyze(self, **kwargs: object) -> tuple[VisionFacts, str]:
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            return await super().analyze(**kwargs)

    vision = SharedVision()
    orchestrator = AnalysisOrchestrator(vision=vision)  # type: ignore[arg-type]
    owner = stream_analysis(
        orchestrator, upload_factory(), "toilet", False
    )
    follower = stream_analysis(
        orchestrator, upload_factory(), "toilet", False
    )

    assert json.loads(await anext(owner))["stage"] == "intake_complete"
    await vision.started.wait()
    assert json.loads(await anext(follower))["stage"] == "intake_complete"
    await asyncio.sleep(0)
    await owner.aclose()
    assert vision.cancelled.is_set() is False

    vision.release.set()
    follower_events = [json.loads(line) async for line in follower]
    assert follower_events[-1]["type"] == "result"
    assert vision.cancelled.is_set() is False
    assert vision.calls == 1


@pytest.mark.asyncio
async def test_stream_success_restores_safe_structured_completion_log(
    upload_factory: Callable[[], UploadFile],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.analysis_stream")
    events = [
        json.loads(line)
        async for line in stream_analysis(
            AnalysisOrchestrator(
                vision=DeterministicVision()  # type: ignore[arg-type]
            ),
            upload_factory(),
            "toilet",
            False,
        )
    ]

    result = events[-1]["payload"]
    records = [
        record
        for record in caplog.records
        if record.name == "sumai.analysis_stream"
        and record.message == "analysis_complete"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.analysis_id == result["analysis_id"]
    assert record.mode == result["mode"]
    assert record.model == result["model"]
    assert record.number_of_findings == len(result["findings"])
    assert record.stage_timings_ms == result["stage_timings_ms"]
    assert isinstance(record.cache_hit, bool)


def test_agent_stream_emits_progress_then_result(client: TestClient) -> None:
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
    assert response.headers["content-type"].startswith(
        "application/x-ndjson"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert [event["type"] for event in events] == [
        "progress",
        "progress",
        "result",
    ]
    assert [event.get("stage") for event in events[:2]] == [
        "intake_complete",
        "vision_complete",
    ]
    AnalysisResponse.model_validate(events[-1]["payload"])


def test_agent_stream_sanitizes_provider_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module
    from app.errors import GeminiUnavailableError

    async def fail_analysis(**_: object) -> None:
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

    assert response.status_code == 200
    assert events == [
        {
            "type": "error",
            "error": "gemini_unavailable",
            "message": "解析サービスは現在利用できません。",
        }
    ]
    serialized = json.dumps(events, ensure_ascii=False).lower()
    assert "provider-secret-body" not in serialized
    assert "api" not in serialized


def test_agent_stream_sanitizes_unexpected_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    async def fail_analysis(**_: object) -> None:
        raise RuntimeError("private-upstream-detail")

    monkeypatch.setattr(
        main_module.orchestrator,
        "analyze",
        fail_analysis,
    )
    response = client.post(
        "/analyze/stream",
        files={"image": ("toilet.png", _png_bytes(), "image/png")},
        data={"room_hint": "toilet", "mock": "false"},
    )

    assert response.status_code == 200
    assert json.loads(response.text) == {
        "type": "error",
        "error": "analysis_failed",
        "message": "分析を完了できませんでした。",
    }
    assert "private-upstream-detail" not in response.text


def test_existing_synchronous_analyze_endpoint_remains_available(
    client: TestClient,
) -> None:
    response = client.post(
        "/analyze",
        files={"image": ("toilet.png", _png_bytes(), "image/png")},
        data={"room_hint": "toilet", "mock": "true"},
    )

    assert response.status_code == 200
    AnalysisResponse.model_validate(response.json())


@pytest.mark.parametrize(
    ("failure", "status_code", "expected"),
    [
        (
            ValueError("private-invalid-upload-detail"),
            400,
            {
                "error": "invalid_upload",
                "message": "画像または入力内容を確認してください。",
            },
        ),
        (
            RuntimeError("private-provider-detail"),
            500,
            {
                "error": "analysis_failed",
                "message": "分析を完了できませんでした。",
            },
        ),
    ],
)
def test_existing_synchronous_analyze_sanitizes_failures_and_logs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
    status_code: int,
    expected: dict[str, str],
) -> None:
    from app import main as main_module

    async def fail_analysis(**_: object) -> None:
        raise failure

    monkeypatch.setattr(main_module.orchestrator, "analyze", fail_analysis)
    caplog.set_level(logging.WARNING, logger="sumai.main")

    response = client.post(
        "/analyze",
        files={"image": ("toilet.png", _png_bytes(), "image/png")},
        data={"room_hint": "toilet", "mock": "false"},
    )

    assert response.status_code == status_code
    assert response.json() == expected
    captured = "\n".join(repr(record.__dict__) for record in caplog.records)
    assert str(failure) not in response.text
    assert str(failure) not in captured
    assert type(failure).__name__ in captured
    records = [
        record
        for record in caplog.records
        if record.name == "sumai.main"
    ]
    assert len(records) == 1
    assert records[0].failure_type == type(failure).__name__
    assert records[0].error_code == expected["error"]
