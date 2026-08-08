from __future__ import annotations

import asyncio
import io
import json
import logging
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import ClientError
from httpx import Request, Response
from PIL import Image

from app.main import app
from app.config import Settings
from app.errors import GeminiUnavailableError, ServiceLimitedError
from app.models import AnalysisResponse, BoundingBox, RiskFinding, RoomType, VisionFacts, VisionResult
from app.services import gemini_vision as gemini_vision_module
from app.services.gemini_vision import GeminiVisionService, parse_vision_json
from app.services.rule_engine import RuleEngine


SENTINEL = "SECRET_PROVIDER_DETAIL_12345"
PROVIDER_TEXT = "RESOURCE_EXHAUSTED"
HUGE_INTEGER = 10**400
SERVICE_LIMITED_RESPONSE = {
    "error": "SERVICE_LIMITED",
    "message": "現在アクセスが集中しています。時間をおいてお試しください。",
}
GEMINI_UNAVAILABLE_RESPONSE = {
    "error": "GEMINI_UNAVAILABLE",
    "message": "現在解析を利用できません。時間をおいてお試しください。",
}


class SyntheticProviderError(RuntimeError):
    def __init__(self, **metadata: object) -> None:
        super().__init__(f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}")
        for name, value in metadata.items():
            setattr(self, name, value)


class HostileEqualityValue:
    def __eq__(self, _other: object) -> bool:
        raise AssertionError(f"hostile equality invoked: {SENTINEL}")

    def __repr__(self) -> str:
        return f"HostileEqualityValue({SENTINEL}, {HUGE_INTEGER})"


class HostileClassValue:
    @property
    def __class__(self) -> type[object]:
        raise RuntimeError(f"hostile class access: {SENTINEL}: {HUGE_INTEGER}")

    def __repr__(self) -> str:
        return f"HostileClassValue({SENTINEL}, {HUGE_INTEGER})"


class RaisingExceptionClassProviderError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}")

    @property
    def __class__(self) -> type[object]:
        raise RuntimeError(f"hostile exception class: {SENTINEL}: {HUGE_INTEGER}")


class SpoofedExceptionClassProviderError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}")

    @property
    def __class__(self) -> type[object]:
        return ServiceLimitedError


class HostileMetadataProviderError(RuntimeError):
    code = HostileEqualityValue()

    def __init__(self) -> None:
        super().__init__(f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}")

    @property
    def status_code(self) -> object:
        raise RuntimeError(f"hostile property invoked: {SENTINEL}: {HUGE_INTEGER}")


class HostileStatusQuotaProviderError(RuntimeError):
    code = " \t429\n"

    def __init__(self) -> None:
        super().__init__(f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}")

    @property
    def status_code(self) -> object:
        raise RuntimeError(f"hostile property invoked: {SENTINEL}: {HUGE_INTEGER}")


MALFORMED_GEMINI_RESPONSES = [
    pytest.param(json.dumps({"provider_detail": SENTINEL}), id="empty-response-shape"),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [{"provider_detail": SENTINEL}],
                "missing_safety_features": [],
            }
        ),
        id="empty-visible-hazard",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "findings": [],
                "missing_safety_features": [{"provider_detail": SENTINEL}],
            }
        ),
        id="mixed-malformed-missing-feature",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 99,
                        "confidence": 0.8,
                        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-severity-out-of-domain",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": SENTINEL,
                "observations": {},
                "visible_hazards": [],
                "missing_safety_features": [],
            }
        ),
        id="canonical-room-out-of-domain",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": False,
                "room_type": "auto",
                "observations": {},
                "visible_hazards": [],
                "missing_safety_features": [],
                "not_applicable_reason_ja": {"provider_detail": SENTINEL},
            }
        ),
        id="canonical-reason-wrong-type",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 3,
                        "confidence": 0.8,
                        "bbox": {"x": 0.9, "y": 0.2, "w": 0.2, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-bbox-exceeds-image",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 3,
                        "confidence": HUGE_INTEGER,
                        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-huge-confidence",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 3,
                        "confidence": 0.8,
                        "bbox": {"x": HUGE_INTEGER, "y": 0.2, "w": 0.3, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-huge-bbox",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {SENTINEL: True},
                "visible_hazards": [],
                "missing_safety_features": [],
            }
        ),
        id="canonical-provider-observation-key",
    ),
]


def _captured_log_details(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(repr(record.__dict__) for record in caplog.records)


def _create_mock_image() -> bytes:
    img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _real_client_error(
    code: int,
    *,
    response_status: int | None = None,
) -> ClientError:
    response = (
        Response(
            response_status,
            request=Request("POST", "https://provider.invalid/analyze"),
        )
        if response_status is not None
        else None
    )
    return ClientError(
        code,
        {
            "error": {
                "code": code,
                "message": f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}",
                "status": PROVIDER_TEXT,
            }
        },
        response,
    )


def _non_actionable_targeted_facts() -> VisionFacts:
    return VisionFacts(
        environment="home",
        room_type="toilet",
        visible_regions=["room"],
        entities=[],
        feature_observations=[],
        relationships=[],
        not_applicable_reason_code=None,
    )


def _request_strict_provider_error(provider_error: Exception) -> Response:
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings), \
         patch(
             "app.services.gemini_vision.GeminiVisionService._call_gemini",
             new_callable=AsyncMock,
         ) as mock_call_gemini, \
         patch("app.services.gemini_vision.mock_vision_facts") as mock_fallback:
        mock_call_gemini.side_effect = provider_error
        response = TestClient(app).post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "auto", "mock": "false"},
        )

    mock_call_gemini.assert_awaited_once()
    mock_fallback.assert_not_called()
    return response


def _request_strict_targeted_provider_error(provider_error: Exception) -> Response:
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings), \
         patch(
             "app.services.gemini_vision.GeminiVisionService._call_gemini_once",
             new_callable=AsyncMock,
         ) as mock_call_gemini_once, \
         patch("app.services.gemini_vision.mock_vision_facts") as mock_fallback:
        mock_call_gemini_once.side_effect = [
            _non_actionable_targeted_facts(),
            provider_error,
        ]
        response = TestClient(app).post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "auto", "mock": "false"},
        )

    assert mock_call_gemini_once.await_count == 2
    mock_fallback.assert_not_called()
    return response


def _assert_provider_details_are_private(
    response: Response,
    caplog: pytest.LogCaptureFixture,
    provider_error: Exception,
) -> None:
    response_and_logs = f"{response.text}\n{_captured_log_details(caplog)}"
    assert SENTINEL not in response_and_logs
    assert PROVIDER_TEXT not in response_and_logs
    assert str(HUGE_INTEGER) not in response_and_logs
    assert all(
        value is not provider_error
        for record in caplog.records
        for value in record.__dict__.values()
    )


def test_status_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "mock_mode" in data
    assert "require_real_gemini" in data
    assert "has_gemini_api_key" in data
    assert "gemini_model" in data
    assert "mock_allowed" in data


def test_strict_mode_without_api_key() -> None:
    new_settings = Settings(require_real_gemini=True, gemini_api_key="")
    
    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        
        client = TestClient(app)
        img_bytes = _create_mock_image()
        
        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "auto"}
        )
        assert response.status_code == 503
        data = response.json()
        assert data == {
            "error": "GEMINI_UNAVAILABLE",
            "message": "現在解析を利用できません。時間をおいてお試しください。",
        }


@pytest.mark.parametrize(
    "provider_error",
    [
        pytest.param(SyntheticProviderError(status_code=429), id="status-code-int"),
        pytest.param(
            SyntheticProviderError(status_code=HTTPStatus.TOO_MANY_REQUESTS),
            id="status-code-http-status",
        ),
        pytest.param(SyntheticProviderError(code=429), id="code-int"),
        pytest.param(SyntheticProviderError(code=" \t429\n"), id="code-trimmed-string"),
        pytest.param(
            SyntheticProviderError(response=SimpleNamespace(status_code=429)),
            id="response-status-code-int",
        ),
    ],
)
def test_strict_provider_quota_metadata_returns_safe_429_without_mock_fallback(
    provider_error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 429
    assert response.json() == SERVICE_LIMITED_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)
    assert any(
        getattr(record, "fallback_reason", None) == "service_limited"
        and getattr(record, "safe_error_code", None) == "SERVICE_LIMITED"
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "provider_error",
    [
        pytest.param(_real_client_error(429), id="client-error-code"),
        pytest.param(
            _real_client_error(0, response_status=429),
            id="client-error-httpx-response-status",
        ),
    ],
)
def test_strict_real_client_error_shapes_return_safe_429(
    provider_error: ClientError,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 429
    assert response.json() == SERVICE_LIMITED_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)


def test_strict_targeted_followup_real_quota_returns_safe_429(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider_error = _real_client_error(429)

    response = _request_strict_targeted_provider_error(provider_error)

    assert response.status_code == 429
    assert response.json() == SERVICE_LIMITED_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)


@pytest.mark.parametrize(
    "provider_error",
    [
        pytest.param(SyntheticProviderError(status_code=503), id="status-code-non-429"),
        pytest.param(SyntheticProviderError(code=403), id="code-non-429"),
        pytest.param(SyntheticProviderError(code=True), id="code-bool"),
        pytest.param(SyntheticProviderError(code=HUGE_INTEGER), id="code-huge-integer"),
    ],
)
def test_strict_non_quota_metadata_remains_safe_503(
    provider_error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 503
    assert response.json() == GEMINI_UNAVAILABLE_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)
    assert any(
        getattr(record, "safe_error_code", None) == "GEMINI_UNAVAILABLE"
        for record in caplog.records
    )


def test_strict_preclassified_limit_remains_safe_429(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider_error = ServiceLimitedError(
        f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}"
    )

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 429
    assert response.json() == SERVICE_LIMITED_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)


def test_strict_preclassified_limit_is_rethrown_without_provider_payload() -> None:
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    provider_error = ServiceLimitedError(
        f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}"
    )
    service = GeminiVisionService()

    with patch("app.services.gemini_vision.settings", new_settings), \
         patch.object(
             service,
             "_call_gemini",
             new=AsyncMock(side_effect=provider_error),
         ):
        with pytest.raises(ServiceLimitedError) as raised:
            asyncio.run(
                service._analyze_with_gemini_strict(
                    image_png=_create_mock_image(),
                    room_hint="auto",
                    analysis_id="safe-analysis-id",
                )
            )

    assert raised.value is not provider_error
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert raised.value.__suppress_context__ is False


@pytest.mark.parametrize(
    ("provider_error", "expected_error_type"),
    [
        pytest.param(
            _real_client_error(429),
            ServiceLimitedError,
            id="client-error-quota",
        ),
        pytest.param(
            _real_client_error(503),
            GeminiUnavailableError,
            id="client-error-unavailable",
        ),
    ],
)
def test_strict_real_provider_error_is_not_retained_by_public_exception(
    provider_error: ClientError,
    expected_error_type: type[Exception],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    service = GeminiVisionService()

    with patch("app.services.gemini_vision.settings", new_settings), \
         patch.object(
             service,
             "_call_gemini",
             new=AsyncMock(side_effect=provider_error),
         ):
        with pytest.raises(expected_error_type) as raised:
            asyncio.run(
                service._analyze_with_gemini_strict(
                    image_png=_create_mock_image(),
                    room_hint="auto",
                    analysis_id="safe-analysis-id",
                )
            )

    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert raised.value.__suppress_context__ is False
    retained_state = repr(
        (
            raised.value.args,
            raised.value.__dict__,
            raised.value.__cause__,
            raised.value.__context__,
        )
    )
    assert SENTINEL not in retained_state
    assert PROVIDER_TEXT not in retained_state
    assert str(HUGE_INTEGER) not in retained_state
    assert SENTINEL not in _captured_log_details(caplog)


def test_targeted_followup_real_quota_is_rethrown_without_provider_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider_error = _real_client_error(429)
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    service = GeminiVisionService()
    call_gemini_once = AsyncMock(
        side_effect=[_non_actionable_targeted_facts(), provider_error]
    )

    with patch("app.services.gemini_vision.settings", new_settings), \
         patch.object(service, "_call_gemini_once", new=call_gemini_once):
        with pytest.raises(Exception) as raised:
            asyncio.run(service._call_gemini(_create_mock_image(), "auto"))

    assert call_gemini_once.await_count == 2
    assert type(raised.value) is getattr(
        gemini_vision_module,
        "_TargetedFollowupLimitedError",
        None,
    )
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert raised.value.__suppress_context__ is False
    assert SENTINEL not in repr(raised.value.__dict__)
    assert SENTINEL not in _captured_log_details(caplog)


def test_non_strict_direct_service_limit_retains_generic_mock_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider_error = ServiceLimitedError(
        f"{PROVIDER_TEXT}: {SENTINEL}: {HUGE_INTEGER}"
    )
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    service = GeminiVisionService()

    with patch("app.services.gemini_vision.settings", new_settings), \
         patch.object(
             service,
             "_call_gemini",
             new=AsyncMock(side_effect=provider_error),
         ), \
         patch(
             "app.services.gemini_vision.mock_vision_facts",
             wraps=gemini_vision_module.mock_vision_facts,
         ) as mock_fallback:
        _result, mode = asyncio.run(
            service._analyze_with_gemini(
                _create_mock_image(),
                "auto",
                "safe-analysis-id",
            )
        )

    assert mode == "gemini_fallback(provider_error)"
    mock_fallback.assert_called_once_with("auto")
    assert SENTINEL not in _captured_log_details(caplog)


def test_non_strict_targeted_real_quota_retains_neutral_partial_fallback() -> None:
    provider_error = _real_client_error(429)
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    service = GeminiVisionService()
    call_gemini_once = AsyncMock(
        side_effect=[_non_actionable_targeted_facts(), provider_error]
    )

    with patch("app.services.gemini_vision.settings", new_settings), \
         patch.object(service, "_call_gemini_once", new=call_gemini_once), \
         patch("app.services.gemini_vision.mock_vision_facts") as mock_fallback:
        result, mode = asyncio.run(
            service._analyze_with_gemini(
                _create_mock_image(),
                "auto",
                "safe-analysis-id",
            )
        )

    assert call_gemini_once.await_count == 2
    mock_fallback.assert_not_called()
    assert mode == "gemini_partial(followup_provider_error)"
    assert result.environment == "uncertain"
    assert result.room_type == "unknown"
    assert result.not_applicable_reason_code == "targeted_followup_failed"


def test_strict_hostile_metadata_falls_back_to_safe_503_without_equality(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider_error = HostileMetadataProviderError()

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 503
    assert response.json() == GEMINI_UNAVAILABLE_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)


@pytest.mark.parametrize(
    "metadata_path",
    ["status_code", "code", "response.status_code"],
)
def test_strict_hostile_class_metadata_falls_back_to_safe_503(
    metadata_path: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    hostile_value = HostileClassValue()
    provider_error = (
        SyntheticProviderError(response=SimpleNamespace(status_code=hostile_value))
        if metadata_path == "response.status_code"
        else SyntheticProviderError(**{metadata_path: hostile_value})
    )

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 503
    assert response.json() == GEMINI_UNAVAILABLE_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)
    assert all(
        value is not hostile_value
        for record in caplog.records
        for value in record.__dict__.values()
    )


@pytest.mark.parametrize(
    "provider_error",
    [
        pytest.param(RaisingExceptionClassProviderError(), id="raising-class"),
        pytest.param(SpoofedExceptionClassProviderError(), id="spoofed-limit-class"),
    ],
)
def test_strict_provider_exception_class_cannot_crash_or_spoof_quota(
    provider_error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 503
    assert response.json() == GEMINI_UNAVAILABLE_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)


def test_strict_hostile_status_property_still_accepts_trustworthy_quota_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider_error = HostileStatusQuotaProviderError()

    response = _request_strict_provider_error(provider_error)

    assert response.status_code == 429
    assert response.json() == SERVICE_LIMITED_RESPONSE
    assert response.headers["cache-control"] == "no-store"
    _assert_provider_details_are_private(response, caplog, provider_error)


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
@pytest.mark.parametrize("raw_json", MALFORMED_GEMINI_RESPONSES)
def test_strict_mode_parse_failure_returns_503_without_detail_leakage(
    mock_call_gemini: AsyncMock,
    raw_json: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")

    async def parse_provider_response(*_args: object, **_kwargs: object) -> VisionResult:
        return parse_vision_json(raw_json, fallback_room="auto")

    mock_call_gemini.side_effect = parse_provider_response
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "auto", "mock": "false"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": "GEMINI_UNAVAILABLE",
        "message": "現在解析を利用できません。時間をおいてお試しください。",
    }
    assert SENTINEL not in response.text
    assert str(HUGE_INTEGER) not in response.text
    log_details = _captured_log_details(caplog)
    assert SENTINEL not in log_details
    assert str(HUGE_INTEGER) not in log_details
    assert "invalid_response" in log_details


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
@pytest.mark.parametrize("raw_json", MALFORMED_GEMINI_RESPONSES)
def test_non_strict_parse_failure_returns_labeled_deterministic_fallback(
    mock_call_gemini: AsyncMock,
    raw_json: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")

    async def parse_provider_response(*_args: object, **_kwargs: object) -> VisionResult:
        return parse_vision_json(raw_json, fallback_room="auto")

    mock_call_gemini.side_effect = parse_provider_response
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "bathroom", "mock": "false"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "gemini_fallback(invalid_response)"
    assert SENTINEL not in response.text
    assert str(HUGE_INTEGER) not in response.text
    log_details = _captured_log_details(caplog)
    assert SENTINEL not in log_details
    assert str(HUGE_INTEGER) not in log_details
    assert data["room_type"] == "bathroom"
    assert [finding["risk_type"] for finding in data["findings"]] == ["bathroom_slip"]


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_non_strict_provider_error_uses_stable_code_without_detail_leakage(
    mock_call_gemini: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")
    mock_call_gemini.side_effect = RuntimeError(f"Provider failed: {SENTINEL}")
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "gemini_fallback(provider_error)"
    assert SENTINEL not in response.text
    assert SENTINEL not in _captured_log_details(caplog)


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_non_strict_timeout_uses_stable_code_without_detail_leakage(
    mock_call_gemini: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")
    mock_call_gemini.side_effect = TimeoutError(f"Timed out: {SENTINEL}")
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "gemini_fallback(gemini_timeout)"
    assert SENTINEL not in response.text
    assert SENTINEL not in _captured_log_details(caplog)


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_non_home_environment_returns_neutral_not_applicable_response(mock_call_gemini: AsyncMock) -> None:
    mock_call_gemini.return_value = VisionFacts(
        environment="non_home",
        room_type="unknown",
        visible_regions=[],
        entities=[],
        feature_observations=[],
        relationships=[],
        not_applicable_reason_code="non_home",
    )

    new_settings = Settings(require_real_gemini=False, gemini_api_key="dummy_key", mock_mode=False)

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        
        client = TestClient(app)
        img_bytes = _create_mock_image()
        
        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "auto"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_home_environment"] is False
        assert data["is_not_applicable"] is True
        assert AnalysisResponse.model_validate(data).is_not_applicable is True
        assert data["not_applicable_reason_ja"] == "住宅内の安全確認対象ではない可能性があります。"
        assert len(data["findings"]) == 0
        assert data["action_plan"] == {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        }
        assert data["overall_risk_level"] == "low"
        assert data["annotated_image_base64"] == data["improvement_image_base64"]
        visible_output = "\n".join(
            [
                data["risk_summary_markdown"],
                data["family_actions_markdown"],
                data["care_manager_actions_markdown"],
                data["contractor_actions_markdown"],
            ]
        )
        assert "判定できません" in visible_output
        assert "安全または低リスクという意味ではない" in visible_output
        assert "リスクは検出されませんでした" not in visible_output
        assert "総合リスク: 低" not in visible_output


def test_unknown_room_returns_neutral_not_applicable_response() -> None:
    client = TestClient(app)
    img_bytes = _create_mock_image()
    
    with patch("app.services.gemini_vision.GeminiVisionService.analyze") as mock_analyze:
        mock_analyze.return_value = (
            VisionFacts(
                environment="home",
                room_type="unknown",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
                not_applicable_reason_code=None,
            ),
            "mock"
        )
        
        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "auto"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overall_risk_level"] == "low"
        assert data["is_not_applicable"] is True
        assert AnalysisResponse.model_validate(data).is_not_applicable is True
        assert len(data["findings"]) == 0
        assert data["not_applicable_reason_ja"] == "写真から確認対象の部屋を特定できないため、結果を表示していません。"
        assert data["action_plan"] == {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        }
        assert data["annotated_image_base64"] == data["improvement_image_base64"]
        visible_output = "\n".join(
            [
                data["risk_summary_markdown"],
                data["family_actions_markdown"],
                data["care_manager_actions_markdown"],
                data["contractor_actions_markdown"],
            ]
        )
        assert "対象外または判定不能" in visible_output
        assert "リスクは検出されませんでした" not in visible_output
        assert "総合リスク: 低" not in visible_output


def test_not_applicable_reason_code_returns_neutral_response() -> None:
    client = TestClient(app)
    img_bytes = _create_mock_image()

    with patch("app.services.gemini_vision.GeminiVisionService.analyze") as mock_analyze:
        mock_analyze.return_value = (
            VisionFacts(
                environment="home",
                room_type="bathroom",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
                not_applicable_reason_code="insufficient_visibility",
            ),
            "mock",
        )

        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "bathroom", "mock": "true"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["is_not_applicable"] is True
    assert AnalysisResponse.model_validate(data).is_not_applicable is True
    assert data["not_applicable_reason_ja"]
    assert data["findings"] == []
    assert data["action_plan"] == {
        "family_no_cost": [],
        "care_manager_purchase": [],
        "contractor_construction": [],
    }
    assert data["annotated_image_base64"] == data["improvement_image_base64"]
    visible_output = "\n".join(
        [
            data["risk_summary_markdown"],
            data["family_actions_markdown"],
            data["care_manager_actions_markdown"],
            data["contractor_actions_markdown"],
        ]
    )
    assert "対象外または判定不能" in visible_output
    assert "リスクは検出されませんでした" not in visible_output
    assert "総合リスク: 低" not in visible_output


def test_rule_engine_confidence_filtering() -> None:
    engine = RuleEngine()
    
    # Define a helper finding creator
    def _make_finding(risk_type: str, confidence: float) -> RiskFinding:
        return RiskFinding(
            id="test",
            risk_type=risk_type,
            label_ja="Test Risk",
            description_ja="Test Description",
            severity=1,
            confidence=confidence,
            bbox=BoundingBox(x=0.0, y=0.0, w=0.1, h=0.1),
            evidence_ja="evidence",
            basis_label_ja="",
            basis_summary_ja="",
            needs_human_confirmation=False
        )

    # 1. confidence < 0.45: dropped
    findings, _ = engine.apply([
        _make_finding("hallway_cord", 0.44),  # Known but too low confidence
        _make_finding("unknown_risk", 0.44)   # Unknown and too low confidence
    ], "hallway")
    assert len(findings) == 0

    # 2. 0.45 <= confidence < 0.60 with known risk: kept, needs_human_confirmation=True
    findings, _ = engine.apply([
        _make_finding("hallway_cord", 0.50)
    ], "hallway")
    assert len(findings) == 1
    assert findings[0].needs_human_confirmation is True

    # 3. 0.45 <= confidence < 0.60 with unknown risk: dropped
    findings, _ = engine.apply([
        _make_finding("unknown_risk", 0.50)
    ], "hallway")
    assert len(findings) == 0

    # 4. Unknown risk type: kept only if confidence >= 0.75
    findings, _ = engine.apply([
        _make_finding("unknown_risk", 0.74),  # Too low for unknown
        _make_finding("unknown_risk", 0.76)   # High enough
    ], "hallway")
    assert len(findings) == 1
    assert findings[0].risk_type == "unknown_risk"
    assert findings[0].confidence == 0.76
