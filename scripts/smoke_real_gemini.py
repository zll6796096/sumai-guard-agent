#!/usr/bin/env python3
import io
import os
from typing import cast

import requests
from PIL import Image


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_status(status_data: dict[str, object], expected_model: str) -> None:
    required_values: dict[str, object] = {
        "mock_mode": False,
        "require_real_gemini": True,
        "mock_allowed": False,
        "has_gemini_api_key": True,
        "gemini_model": expected_model,
    }
    for field, expected in required_values.items():
        actual = status_data.get(field)
        _require(
            actual == expected and type(actual) is type(expected),
            f"status.{field} must be {expected!r} for real Gemini smoke; got {actual!r}",
        )


def validate_analysis_payload(
    payload: dict[str, object],
    expected_model: str,
    expected_home: bool,
    previous_analysis_id: str | None = None,
) -> str:
    mode = payload.get("mode")
    _require(mode == "gemini", f"payload.mode must be 'gemini'; got {mode!r}")

    model = payload.get("model")
    _require(
        model == expected_model,
        f"payload.model must be {expected_model!r}; got {model!r}",
    )

    analysis_id = payload.get("analysis_id")
    _require(
        isinstance(analysis_id, str) and bool(analysis_id.strip()),
        f"payload.analysis_id must be a nonempty string; got {analysis_id!r}",
    )
    analysis_id = cast(str, analysis_id).strip()
    if previous_analysis_id is not None:
        _require(
            analysis_id != previous_analysis_id,
            "analysis IDs must be distinct across smoke requests; "
            f"both were {analysis_id!r}",
        )

    is_home = payload.get("is_home_environment")
    _require(
        is_home is expected_home,
        f"payload.is_home_environment must be {expected_home!r}; got {is_home!r}",
    )

    if not expected_home:
        findings = payload.get("findings")
        _require(
            isinstance(findings, list),
            f"payload.findings must be a list; got {type(findings).__name__}",
        )
        findings = cast(list[object], findings)
        _require(
            len(findings) == 0,
            f"payload.findings must be empty for non-home image; got {len(findings)}",
        )
        risk_level = payload.get("overall_risk_level")
        _require(
            risk_level == "low",
            "payload.overall_risk_level must be 'low' for non-home image; "
            f"got {risk_level!r}",
        )

    return analysis_id


def main() -> int:
    base_url = os.getenv("SUMAI_AGENT_URL", "http://localhost:8000").rstrip("/")
    expected_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    print(f"Running smoke test against agent backend at: {base_url}")

    try:
        status_res = requests.get(f"{base_url}/status", timeout=5)
        status_res.raise_for_status()
        status_data = status_res.json()
        validate_status(status_data, expected_model)
        print(f"✅ Status provenance passed: model={expected_model}")

        home_img_path = "apps/sumai_web/assets/samples/hallway_sample.png"
        if not os.path.exists(home_img_path):
            home_img_path = "../apps/sumai_web/assets/samples/hallway_sample.png"

        if not os.path.exists(home_img_path):
            raise FileNotFoundError("Could not find hallway_sample.png")

        print(f"Sending home interior image: {home_img_path}...")
        with open(home_img_path, "rb") as home_file:
            files = {"image": ("hallway.png", home_file.read(), "image/png")}
            data = {"room_hint": "hallway", "mock": "false"}
            res = requests.post(f"{base_url}/analyze", files=files, data=data, timeout=60)
            if res.status_code != 200:
                raise AssertionError(
                    f"Home analysis failed with code {res.status_code}: {res.text}"
                )

        home_payload = res.json()
        home_analysis_id = validate_analysis_payload(
            home_payload,
            expected_model,
            expected_home=True,
        )
        print("✅ Home analysis response received successfully!")
        print(
            f"   mode={home_payload['mode']} model={home_payload['model']} "
            f"analysis_id={home_analysis_id}"
        )
        print(f"   is_home_environment: {home_payload.get('is_home_environment')}")
        print(f"   findings count: {len(home_payload.get('findings', []))}")
        print(f"   overall_risk_level: {home_payload.get('overall_risk_level')}")

        print("Generating solid color non-home image...")
        non_home_img = Image.new("RGB", (300, 300), color="blue")
        buf = io.BytesIO()
        non_home_img.save(buf, format="PNG")
        non_home_bytes = buf.getvalue()

        print("Sending non-home image...")
        files = {"image": ("non_home.png", non_home_bytes, "image/png")}
        data = {"room_hint": "auto", "mock": "false"}
        res = requests.post(f"{base_url}/analyze", files=files, data=data, timeout=60)
        if res.status_code != 200:
            raise AssertionError(
                f"Non-home analysis failed with code {res.status_code}: {res.text}"
            )

        non_home_payload = res.json()
        non_home_analysis_id = validate_analysis_payload(
            non_home_payload,
            expected_model,
            expected_home=False,
            previous_analysis_id=home_analysis_id,
        )
        print("✅ Non-home analysis response received successfully!")
        print(
            f"   mode={non_home_payload['mode']} model={non_home_payload['model']} "
            f"analysis_id={non_home_analysis_id}"
        )
        print(f"   is_home_environment: {non_home_payload.get('is_home_environment')}")
        print(f"   not_applicable_reason_ja: {non_home_payload.get('not_applicable_reason_ja')}")
        print(f"   findings count: {len(non_home_payload.get('findings', []))}")
        print(f"   overall_risk_level: {non_home_payload.get('overall_risk_level')}")
    except Exception as exc:
        print(f"❌ REAL GEMINI SMOKE FAILED: {exc}")
        return 1

    print("\n🎉 ALL REAL GEMINI PROVENANCE SMOKE TESTS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
