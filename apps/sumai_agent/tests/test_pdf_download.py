from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient
from pypdf import PdfReader


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"


def _load_web_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sumai_web_pdf_contract", WEB_APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, object]:
    return {
        "finding_count": 2,
        "overall_risk_level": "medium",
        "family_actions_markdown": "## 家族で今日できること\n- 通路の物を移動する",
        "care_manager_actions_markdown": "## ケアマネ・福祉用具に相談\n- 手すりを相談する",
        "contractor_actions_markdown": "## 専門施工・現地確認\n- 現地確認を依頼する",
        "risk_summary_markdown": "## 詳しいリスク根拠\n床の物につまずく可能性があります。",
    }


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_download_returns_a_text_only_japanese_attachment() -> None:
    module = _load_web_module()
    response = TestClient(module.app).post("/suggestions.pdf", json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert "sumai-guard-safety-actions-" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(response.content))
    text = _pdf_text(response.content)
    for expected in (
        "安全のためにできること",
        "家族で今日できること",
        "ケアマネ・福祉用具に相談",
        "専門施工・現地確認",
        "詳しいリスク根拠",
        "写真1枚に写っている範囲",
        "医療・介護認定・保険・法令適合・施工可否・見積もり",
        "写真や生成したPDFを保存しません",
    ):
        assert expected in text

    for page in reader.pages:
        resources = page.get("/Resources", {})
        xobjects = resources.get("/XObject", {})
        assert all(
            obj.get_object().get("/Subtype") != "/Image"
            for obj in xobjects.values()
        )


def test_multi_page_pdf_repeats_context_and_numbers_every_page() -> None:
    module = _load_web_module()
    payload = _payload() | {
        "family_actions_markdown": (
            "## 家族で今日できること\n"
            + "\n".join(
                f"- 対策{i}：通路に置かれた物を安全な場所へ移動します。"
                for i in range(1, 36)
            )
        )
    }

    response = TestClient(module.app).post("/suggestions.pdf", json=payload)

    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) >= 2
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        assert "安全のためにできること" in text
        assert f"ページ {page_number}" in text


def test_pdf_download_forbids_image_and_debug_fields() -> None:
    module = _load_web_module()
    payload = _payload() | {
        "annotated_image_base64": "secret",
        "analysis_id": "private",
    }

    response = TestClient(module.app).post("/suggestions.pdf", json=payload)

    assert response.status_code == 422
    assert "secret" not in response.text
    assert "private" not in response.text


def test_pdf_download_rejects_oversized_report_text() -> None:
    module = _load_web_module()
    payload = _payload() | {"risk_summary_markdown": "危険" * 10_001}

    response = TestClient(module.app).post("/suggestions.pdf", json=payload)

    assert response.status_code == 422


def test_pdf_generation_failure_is_generic_and_does_not_echo_content(
    monkeypatch,
) -> None:
    module = _load_web_module()

    def fail_generation(_report) -> bytes:
        raise RuntimeError("secret path")

    monkeypatch.setattr(module, "build_safety_advice_pdf", fail_generation)

    response = TestClient(module.app).post("/suggestions.pdf", json=_payload())

    assert response.status_code == 500
    assert response.json() == {
        "error": "pdf_generation_failed",
        "message": "PDFを作成できませんでした。時間をおいて、もう一度お試しください。",
    }
    assert "secret path" not in response.text
