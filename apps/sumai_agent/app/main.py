from __future__ import annotations

import json
import logging
import sys
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.models import AnalysisResponse
from app.services.orchestrator import AnalysisOrchestrator


def _setup_logging() -> None:
    """Configure structured JSON logging."""

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            log_entry: dict[str, object] = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            # Add extra fields (analysis_id, mode, latency_ms, etc.)
            for key in ("analysis_id", "mode", "model", "room_hint", "mock_or_gemini",
                        "number_of_findings", "latency_ms", "fallback_reason",
                        "finding_count", "reason", "raw_length", "index", "error",
                        "original", "type"):
                value = getattr(record, key, None)
                if value is not None:
                    log_entry[key] = value
            return json.dumps(log_entry, ensure_ascii=False)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(settings.log_level.upper())


_setup_logging()
logger = logging.getLogger("sumai.main")

app = FastAPI(title="SumaiGuard Agent", version=settings.version)
orchestrator = AnalysisOrchestrator()

logger.info(
    "server_startup",
    extra={
        "mock_mode": settings.mock_mode,
        "model": settings.gemini_model,
        "version": settings.version,
        "analysis_timeout": settings.analysis_timeout,
    },
)


from app.errors import GeminiUnavailableError


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "gemini_model": settings.gemini_model,
        "version": settings.version,
    }


@app.get("/status")
def status_endpoint() -> dict[str, object]:
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "require_real_gemini": settings.require_real_gemini,
        "has_gemini_api_key": bool(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "mock_allowed": not settings.require_real_gemini,
    }


@app.post("/analyze", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
    mock: bool = Form(False),
) -> Any:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルを指定してください。")

    try:
        return await orchestrator.analyze(upload=image, room_hint=room_hint, mock=mock)
    except GeminiUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": "gemini_unavailable",
                "message": "Real Gemini analysis is required but unavailable."
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("analyze_error", extra={"error": str(exc)[:500]})
        raise HTTPException(status_code=500, detail=f"分析中にエラーが発生しました: {exc}") from exc
