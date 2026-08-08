from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Literal

import anyio
from fastapi import FastAPI, File, Form, Request, UploadFile, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette._utils import get_route_path
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.errors import (
    AppCheckInvalidError,
    GeminiUnavailableError,
    ImageTooLargeError,
    InvalidImageError,
    ServiceLimitedError,
)
from app.models import AnalysisResponse
from app.security.app_check import AppCheckVerifier
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
                        "finding_count", "entity_count", "feature_count",
                        "reason", "raw_length", "index", "type",
                        "stage_timings_ms", "cache_hit", "failure_type",
                        "failure_stage", "safe_error_code"):
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

orchestrator = AnalysisOrchestrator()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        try:
            await orchestrator.aclose()
        except Exception:
            logger.error("orchestrator_close_failed")


app = FastAPI(title="SumaiGuard Agent", version=settings.version, lifespan=lifespan)

logger.info(
    "server_startup",
    extra={
        "mock_mode": settings.mock_mode,
        "model": settings.gemini_model,
        "version": settings.version,
        "analysis_timeout": settings.analysis_timeout,
    },
)


ANALYSIS_PATHS = frozenset({"/api/v1/analyze", "/analyze"})


def _is_analysis_route(scope: Scope) -> bool:
    return get_route_path(scope) in ANALYSIS_PATHS


PublicErrorCode = Literal[
    "INVALID_IMAGE",
    "APP_CHECK_INVALID",
    "IMAGE_TOO_LARGE",
    "SERVICE_LIMITED",
    "GEMINI_UNAVAILABLE",
    "INTERNAL_ERROR",
]
PUBLIC_ERRORS: dict[PublicErrorCode, tuple[int, str]] = {
    "INVALID_IMAGE": (
        status.HTTP_400_BAD_REQUEST,
        "画像を確認できませんでした。JPEGまたはPNGを選んでください。",
    ),
    "APP_CHECK_INVALID": (
        status.HTTP_401_UNAUTHORIZED,
        "アプリの確認に失敗しました。もう一度お試しください。",
    ),
    "IMAGE_TOO_LARGE": (
        413,
        "画像が大きすぎます。別の写真を選んでください。",
    ),
    "SERVICE_LIMITED": (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "現在アクセスが集中しています。時間をおいてお試しください。",
    ),
    "GEMINI_UNAVAILABLE": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "現在解析を利用できません。時間をおいてお試しください。",
    ),
    "INTERNAL_ERROR": (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "解析を完了できませんでした。時間をおいてお試しください。",
    ),
}


class PublicErrorResponse(BaseModel):
    error: PublicErrorCode
    message: str


ANALYSIS_ERROR_RESPONSES = {
    status_code: {
        "model": PublicErrorResponse,
        "description": error_code,
    }
    for error_code, (status_code, _message) in PUBLIC_ERRORS.items()
}


def public_error(code: PublicErrorCode) -> JSONResponse:
    status_code, message = PUBLIC_ERRORS[code]
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "message": message},
        headers={"Cache-Control": "no-store"},
    )


def _scope_header(scope: Scope, name: bytes) -> str | None:
    for key, value in reversed(scope.get("headers", [])):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class AnalysisSecurityMiddleware:
    """Authenticate and protect native analysis responses before body intake."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or not _is_analysis_route(scope):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def no_store_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
                await send(message)
                response_started = True
                return
            await send(message)

        failure_stage = "app_check"
        try:
            if settings.app_check_required:
                token = _scope_header(scope, b"x-firebase-appcheck")

                def verify() -> None:
                    AppCheckVerifier(
                        required=True,
                        expected_app_id=settings.firebase_app_id,
                    ).verify(token)

                await anyio.to_thread.run_sync(verify)

            failure_stage = "inner_app"
            await self.app(scope, receive, no_store_send)
        except AppCheckInvalidError:
            if response_started:
                raise
            await public_error("APP_CHECK_INVALID")(scope, receive, no_store_send)
        except Exception as exc:
            logger.error(
                "analysis_request_failed",
                extra={
                    "failure_stage": failure_stage,
                    "failure_type": type(exc).__name__,
                    "safe_error_code": "INTERNAL_ERROR",
                },
            )
            if response_started:
                raise
            await public_error("INTERNAL_ERROR")(scope, receive, no_store_send)


app.add_middleware(AnalysisSecurityMiddleware)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    if _is_analysis_route(request.scope):
        return public_error("INVALID_IMAGE")
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(StarletteHTTPException)
async def http_exception_safety_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if (
        _is_analysis_route(request.scope)
        and exc.status_code == status.HTTP_400_BAD_REQUEST
    ):
        return public_error("INVALID_IMAGE")
    return await http_exception_handler(request, exc)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "version": settings.version}


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "version": settings.version}


@app.get("/ready")
def ready() -> dict[str, object]:
    return {"status": "ready", "version": settings.version}


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


@app.post(
    "/api/v1/analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    responses=ANALYSIS_ERROR_RESPONSES,
)
@app.post(
    "/analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def analyze(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
    mock: bool = Form(False),
) -> Any:
    try:
        if image.content_type not in {"image/jpeg", "image/png"}:
            raise InvalidImageError
        response = await orchestrator.analyze(upload=image, room_hint=room_hint, mock=mock)
        serialize_started = time.monotonic()
        content = response.model_dump(mode="json")
        stage_timings_ms = content["stage_timings_ms"]
        stage_timings_ms["serialize"] = max(
            0, int((time.monotonic() - serialize_started) * 1000)
        )
        # This is an instrumented application-stage sum, not HTTP end-to-end latency:
        # Starlette JSON encoding, socket, and network time are intentionally excluded.
        stage_timings_ms["total"] = sum(
            value for key, value in stage_timings_ms.items() if key != "total"
        )
        logger.info(
            "analysis_complete",
            extra={
                "analysis_id": response.analysis_id,
                "mode": response.mode,
                "model": response.model,
                "number_of_findings": len(response.findings),
                "stage_timings_ms": stage_timings_ms,
                "cache_hit": response._cache_hit,
            },
        )
        return JSONResponse(content=content)
    except InvalidImageError:
        return public_error("INVALID_IMAGE")
    except ImageTooLargeError:
        return public_error("IMAGE_TOO_LARGE")
    except ServiceLimitedError:
        return public_error("SERVICE_LIMITED")
    except GeminiUnavailableError:
        return public_error("GEMINI_UNAVAILABLE")
    except ValueError as exc:
        logger.error(
            "analysis_failed",
            extra={
                "failure_type": type(exc).__name__,
                "safe_error_code": "INTERNAL_ERROR",
            },
        )
        return public_error("INTERNAL_ERROR")
    except Exception as exc:
        logger.error(
            "analysis_failed",
            extra={
                "failure_type": type(exc).__name__,
                "safe_error_code": "INTERNAL_ERROR",
            },
        )
        return public_error("INTERNAL_ERROR")


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    operation = schema["paths"]["/api/v1/analyze"]["post"]
    operation["responses"].pop("422", None)
    parameters = operation.setdefault("parameters", [])
    parameters.append(
        {
            "name": "X-Firebase-AppCheck",
            "in": "header",
            "required": True,
            "description": (
                "Production requests require Firebase App Check attestation; "
                "local development may disable enforcement explicitly."
            ),
            "schema": {"type": "string"},
        }
    )
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
