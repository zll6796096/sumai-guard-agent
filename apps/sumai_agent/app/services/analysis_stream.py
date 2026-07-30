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
    """Yield truthful progress and one terminal event as safe NDJSON."""
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
            assert isinstance(timings, dict)
            timings["serialize"] = max(
                0,
                int((time.monotonic() - serialize_started) * 1000),
            )
            timings["total"] = sum(
                value
                for key, value in timings.items()
                if key != "total" and isinstance(value, int)
            )
            await queue.put(
                _line(
                    {
                        "type": "result",
                        "payload": payload,
                    }
                )
            )
        except GeminiUnavailableError:
            await queue.put(
                _line(
                    {
                        "type": "error",
                        "error": "gemini_unavailable",
                        "message": "解析サービスは現在利用できません。",
                    }
                )
            )
        except ValueError:
            await queue.put(
                _line(
                    {
                        "type": "error",
                        "error": "invalid_upload",
                        "message": "画像または入力内容を確認してください。",
                    }
                )
            )
        except Exception:
            await queue.put(
                _line(
                    {
                        "type": "error",
                        "error": "analysis_failed",
                        "message": "分析を完了できませんでした。",
                    }
                )
            )
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
        await upload.close()
