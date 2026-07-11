from __future__ import annotations

import pytest

from scripts import smoke_real_gemini


EXPECTED_MODEL = "gemini-2.5-flash"


def _valid_status() -> dict[str, object]:
    return {
        "mock_mode": False,
        "require_real_gemini": True,
        "mock_allowed": False,
        "has_gemini_api_key": True,
        "gemini_model": EXPECTED_MODEL,
    }


def _valid_payload(
    *,
    analysis_id: str = "sumai_abc123",
    is_home: bool = True,
) -> dict[str, object]:
    return {
        "mode": "gemini",
        "model": EXPECTED_MODEL,
        "analysis_id": analysis_id,
        "is_home_environment": is_home,
        "findings": [{"risk_type": "hallway_cord"}] if is_home else [],
        "overall_risk_level": "medium" if is_home else "low",
    }


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("mock_mode", True),
        ("require_real_gemini", False),
        ("mock_allowed", True),
        ("has_gemini_api_key", False),
        ("gemini_model", "wrong-model"),
    ],
)
def test_validate_status_rejects_each_invalid_provenance_gate(
    field: str,
    invalid_value: object,
) -> None:
    status = _valid_status()
    status[field] = invalid_value

    with pytest.raises(AssertionError, match=field):
        smoke_real_gemini.validate_status(status, EXPECTED_MODEL)


def test_validate_status_accepts_exact_real_gemini_configuration() -> None:
    smoke_real_gemini.validate_status(_valid_status(), EXPECTED_MODEL)


@pytest.mark.parametrize("invalid_mode", ["mock", "gemini_fallback(gemini_timeout)"])
def test_validate_analysis_payload_rejects_mock_or_fallback_mode(invalid_mode: str) -> None:
    payload = _valid_payload()
    payload["mode"] = invalid_mode

    with pytest.raises(AssertionError, match="mode"):
        smoke_real_gemini.validate_analysis_payload(
            payload,
            EXPECTED_MODEL,
            expected_home=True,
        )


def test_validate_analysis_payload_rejects_wrong_model() -> None:
    payload = _valid_payload()
    payload["model"] = "wrong-model"

    with pytest.raises(AssertionError, match="model"):
        smoke_real_gemini.validate_analysis_payload(
            payload,
            EXPECTED_MODEL,
            expected_home=True,
        )


@pytest.mark.parametrize("invalid_analysis_id", [None, "", "   "])
def test_validate_analysis_payload_rejects_missing_or_empty_analysis_id(
    invalid_analysis_id: object,
) -> None:
    payload = _valid_payload()
    if invalid_analysis_id is None:
        payload.pop("analysis_id")
    else:
        payload["analysis_id"] = invalid_analysis_id

    with pytest.raises(AssertionError, match="analysis_id"):
        smoke_real_gemini.validate_analysis_payload(
            payload,
            EXPECTED_MODEL,
            expected_home=True,
        )


def test_validate_analysis_payload_rejects_duplicate_analysis_id() -> None:
    payload = _valid_payload(analysis_id="sumai_duplicate")

    with pytest.raises(AssertionError, match="distinct"):
        smoke_real_gemini.validate_analysis_payload(
            payload,
            EXPECTED_MODEL,
            expected_home=False,
            previous_analysis_id="sumai_duplicate",
        )


def test_validate_analysis_payload_accepts_home_payload() -> None:
    analysis_id = smoke_real_gemini.validate_analysis_payload(
        _valid_payload(analysis_id="sumai_home", is_home=True),
        EXPECTED_MODEL,
        expected_home=True,
    )

    assert analysis_id == "sumai_home"


def test_validate_analysis_payload_accepts_non_home_payload_with_distinct_id() -> None:
    analysis_id = smoke_real_gemini.validate_analysis_payload(
        _valid_payload(analysis_id="sumai_nonhome", is_home=False),
        EXPECTED_MODEL,
        expected_home=False,
        previous_analysis_id="sumai_home",
    )

    assert analysis_id == "sumai_nonhome"
