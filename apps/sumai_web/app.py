from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import logging
import math
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from starlette._utils import get_route_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _load_static_public_pages() -> tuple[str, str]:
    public_pages_path = Path(__file__).with_name("public_pages.py")
    spec = importlib.util.spec_from_file_location(
        "_sumai_web_static_public_pages",
        public_pages_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("public pages module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PRIVACY_HTML, module.SUPPORT_HTML


PRIVACY_HTML, SUPPORT_HTML = _load_static_public_pages()


load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sumai.web")

SUMAI_AGENT_URL = os.getenv("SUMAI_AGENT_URL", "http://localhost:8080").rstrip("/")
SUMAI_WEB_PORT = int(os.getenv("SUMAI_WEB_PORT", "8081"))
FRONTEND_MOCK = os.getenv("MOCK_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


def _public_web_analysis_enabled(frontend_mock: bool) -> bool:
    raw_value = os.getenv("PUBLIC_WEB_ANALYSIS_ENABLED")
    if raw_value is None:
        return frontend_mock
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return False


PUBLIC_WEB_ANALYSIS_ENABLED = _public_web_analysis_enabled(FRONTEND_MOCK)

_backend_client: httpx.AsyncClient | None = None

DISCLAIMER = (
    "POC版です。医療・介護・施工判断を代替しません。\n"
    "改善イメージはコミュニケーション用であり施工図ではありません。\n"
    "写真から正確な寸法や適用制度を判断するものではありません。"
)

HOME_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

PDF_FONT_NAME = "HeiseiKakuGo-W5"
PDF_DISCLAIMER = (
    "このPDFは、写真1枚に写っている範囲だけをもとにした一般的な安全上の注意と相談の目安です。"
    "写真に写っていない危険や、AIが見落とした危険がある可能性があります。\n"
    "医療・介護認定・保険・法令適合・施工可否・見積もり、その他の専門判断を行うものではありません。"
    "実際の状況を現地で確認し、必要に応じてケアマネジャー、福祉用具専門相談員、施工の専門家へ相談してください。\n"
    "このPOCは、アップロードした写真や生成したPDFを保存しません。"
)


class SuggestionPdfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_count: int = Field(ge=0, le=100)
    overall_risk_level: Literal["low", "medium", "high"]
    family_actions_markdown: str = Field(min_length=1, max_length=20_000)
    care_manager_actions_markdown: str = Field(min_length=1, max_length=20_000)
    contractor_actions_markdown: str = Field(min_length=1, max_length=20_000)
    risk_summary_markdown: str = Field(min_length=1, max_length=20_000)


pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_NAME))


def _pdf_styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "SumaiTitle",
            fontName=PDF_FONT_NAME,
            fontSize=19,
            leading=26,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1D1D1F"),
            spaceAfter=5 * mm,
            wordWrap="CJK",
        ),
        "meta": ParagraphStyle(
            "SumaiMeta",
            fontName=PDF_FONT_NAME,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#6E6E73"),
            spaceAfter=2 * mm,
            wordWrap="CJK",
        ),
        "heading": ParagraphStyle(
            "SumaiHeading",
            fontName=PDF_FONT_NAME,
            fontSize=13,
            leading=19,
            textColor=colors.HexColor("#1D1D1F"),
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            wordWrap="CJK",
        ),
        "subheading": ParagraphStyle(
            "SumaiSubheading",
            fontName=PDF_FONT_NAME,
            fontSize=11,
            leading=17,
            textColor=colors.HexColor("#1D1D1F"),
            spaceBefore=2 * mm,
            spaceAfter=1 * mm,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "SumaiBody",
            fontName=PDF_FONT_NAME,
            fontSize=10,
            leading=16,
            textColor=colors.HexColor("#1D1D1F"),
            spaceAfter=1.5 * mm,
            wordWrap="CJK",
        ),
        "disclaimer": ParagraphStyle(
            "SumaiDisclaimer",
            fontName=PDF_FONT_NAME,
            fontSize=8.5,
            leading=14,
            textColor=colors.HexColor("#3A3A3C"),
            wordWrap="CJK",
        ),
    }


def _markdown_flowables(
    markdown: str,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    flowables: list[Flowable] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flowables.append(Spacer(1, 1.5 * mm))
        elif line.startswith("### "):
            flowables.append(Paragraph(escape(line[4:]), styles["subheading"]))
        elif line.startswith("## "):
            flowables.append(Paragraph(escape(line[3:]), styles["heading"]))
        elif re.match(r"^[-*]\s+", line):
            content = re.sub(r"^[-*]\s+", "", line)
            flowables.append(Paragraph("・" + escape(content), styles["body"]))
        else:
            flowables.append(Paragraph(escape(line), styles["body"]))
    return flowables


def _draw_pdf_page_furniture(
    canvas: Any,
    document: Any,
    *,
    continuation: bool,
) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#6E6E73"))
    canvas.setFont(PDF_FONT_NAME, 8)
    if continuation:
        canvas.drawString(
            document.leftMargin,
            A4[1] - 11 * mm,
            "安全のためにできること",
        )
    canvas.drawString(document.leftMargin, 9 * mm, "親の家 安全チェックAI")
    canvas.drawRightString(
        A4[0] - document.rightMargin,
        9 * mm,
        f"ページ {document.page}",
    )
    canvas.restoreState()


def _draw_pdf_first_page(canvas: Any, document: Any) -> None:
    _draw_pdf_page_furniture(canvas, document, continuation=False)


def _draw_pdf_later_page(canvas: Any, document: Any) -> None:
    _draw_pdf_page_furniture(canvas, document, continuation=True)


def build_safety_advice_pdf(report: SuggestionPdfRequest) -> bytes:
    buffer = io.BytesIO()
    styles = _pdf_styles()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="親の家 安全チェックAI - 安全のためにできること",
        author="SumaiGuard Agent POC",
    )
    risk_labels = {"low": "低", "medium": "中", "high": "高"}
    generated_at = datetime.now(ZoneInfo("Asia/Tokyo"))

    story: list[Flowable] = [
        Paragraph("親の家 安全チェックAI", styles["meta"]),
        Paragraph("安全のためにできること", styles["title"]),
        Paragraph(
            f"作成日：{generated_at:%Y年%m月%d日}（日本時間）",
            styles["meta"],
        ),
        Paragraph(
            "写真で確認した注意箇所："
            f"{report.finding_count}件　総合リスク：{risk_labels[report.overall_risk_level]}",
            styles["meta"],
        ),
    ]
    for markdown in (
        report.family_actions_markdown,
        report.care_manager_actions_markdown,
        report.contractor_actions_markdown,
        report.risk_summary_markdown,
    ):
        story.extend(_markdown_flowables(markdown, styles))

    story.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph("ご利用前に必ずご確認ください", styles["heading"]),
            Table(
                [
                    [
                        Paragraph(
                            escape(PDF_DISCLAIMER).replace("\n", "<br/>"),
                            styles["disclaimer"],
                        )
                    ]
                ],
                colWidths=[A4[0] - 36 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F7")),
                        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C7C7CC")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                    ]
                ),
            ),
        ]
    )
    document.build(
        story,
        onFirstPage=_draw_pdf_first_page,
        onLaterPages=_draw_pdf_later_page,
    )
    return buffer.getvalue()


# HTML Template with mobile-first CSS and vanilla JS
INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <link rel="icon" href="data:,">
    <title>親の家 安全チェックAI</title>
    <style>
        :root {
            color-scheme: light;
            --system-bg: #F5F5F7;
            --surface: #FFFFFF;
            --surface-muted: #F2F2F7;
            --text-primary: #1D1D1F;
            --text-secondary: #6E6E73;
            --separator: rgba(60, 60, 67, 0.16);
            --system-blue: #007AFF;
            --system-blue-pressed: #0062CC;
            --system-green: #248A3D;
            --system-orange: #C93400;
            --system-red: #D70015;
            --control-min-height: 44px;
            --card-radius: 20px;
            --control-radius: 14px;
            --page-shadow: 0 24px 64px rgba(0, 0, 0, 0.12);
            --bg-gradient: linear-gradient(180deg, #FFFFFF 0%, #F5F5F7 100%);
            --card-bg: var(--surface);
            --text-color: var(--text-primary);
            --text-muted: var(--text-secondary);
            --primary-color: var(--system-blue);
            --secondary-color: var(--system-blue);
            --border-color: var(--separator);
            --danger-color: var(--system-red);
            --success-color: var(--system-green);
            --warning-color: var(--system-orange);
            --accent-green: var(--system-green);
            --accent-blue: var(--system-blue);
            --accent-red: var(--system-red);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background:
                radial-gradient(circle at 50% 0%, rgba(0, 122, 255, 0.10), transparent 34rem),
                var(--system-bg);
            font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans",
                "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif;
            color: var(--text-color);
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            justify-content: center;
            align-items: center;
            -webkit-font-smoothing: antialiased;
            text-rendering: optimizeLegibility;
        }

        #app-container {
            width: 100%;
            max-width: 480px;
            height: 100vh;
            height: 100dvh;
            background: var(--bg-gradient);
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
            border-radius: 0;
        }

        @media (min-width: 481px) {
            #app-container {
                height: min(900px, calc(100dvh - 40px));
                border-radius: 30px;
                border: 1px solid var(--border-color);
                box-shadow: var(--page-shadow);
            }
        }

        .screen {
            width: 100%;
            height: 100%;
            display: none;
            flex-direction: column;
            padding: max(20px, env(safe-area-inset-top)) 20px
                max(20px, env(safe-area-inset-bottom));
            position: absolute;
            top: 0;
            left: 0;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
        }

        .screen.active {
            display: flex;
        }

        [hidden] {
            display: none !important;
        }

        :focus-visible {
            outline: 3px solid rgba(0, 122, 255, 0.45);
            outline-offset: 3px;
        }

        [data-screen-title]:focus {
            outline: none;
        }

        /* Screen 1: Home */
        #screen-home {
            overflow-y: auto;
            justify-content: flex-start;
        }

        .home-header {
            text-align: left;
            margin-top: 4px;
            margin-bottom: 20px;
        }

        .app-tag {
            display: inline-block;
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--primary-color);
            background-color: rgba(0, 122, 255, 0.10);
            padding: 5px 10px;
            border-radius: 999px;
            margin-bottom: 12px;
            letter-spacing: 0.02em;
        }

        .home-title {
            font-size: clamp(1.75rem, 8vw, 2.15rem);
            font-weight: 750;
            letter-spacing: -0.035em;
            line-height: 1.2;
            color: var(--text-color);
            margin-bottom: 10px;
        }

        .home-lead {
            max-width: 24rem;
            font-size: 0.98rem;
            line-height: 1.65;
            color: var(--text-muted);
        }

        /* Place Grid */
        .place-section-title {
            font-size: 0.82rem;
            font-weight: 700;
            color: var(--text-muted);
            margin-bottom: 10px;
            text-align: left;
        }

        .place-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }

        .place-block {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background-color: var(--surface);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            min-height: 76px;
            padding: 10px 4px;
            gap: 6px;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
        }

        .place-block svg {
            width: 24px;
            height: 24px;
            color: var(--secondary-color);
        }

        .place-block span {
            font-size: 0.76rem;
            font-weight: 600;
            color: var(--text-color);
        }

        .shooting-hint {
            font-size: 0.82rem;
            line-height: 1.5;
            color: var(--text-muted);
            text-align: left;
            margin-bottom: 14px;
        }

        .home-controls {
            margin: 0;
        }

        .control-group {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 10px 16px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .control-label {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-muted);
        }

        .room-dropdown {
            background: transparent;
            border: none;
            color: var(--text-color);
            font-size: 0.9rem;
            font-weight: 700;
            outline: none;
            text-align: right;
            cursor: pointer;
            width: 120px;
            direction: rtl;
        }

        .room-dropdown option {
            background-color: var(--surface);
            color: var(--text-color);
            direction: ltr;
        }

        .guidance-text {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.4;
            background-color: var(--surface-muted);
            border-radius: 8px;
            padding: 8px;
            border: 1px dashed var(--border-color);
        }

        .error-message {
            background-color: rgba(239, 68, 68, 0.12);
            border: 1px solid var(--danger-color);
            color: var(--danger-color);
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 0.75rem;
            text-align: center;
            margin-top: 10px;
            font-weight: bold;
        }

        .home-footer {
            margin-top: auto;
            padding-top: 4px;
            margin-bottom: 4px;
        }

        .trust-card {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 16px;
            padding: 14px;
            background: var(--surface);
            border: 1px solid var(--border-color);
            border-radius: 16px;
        }

        .trust-item {
            min-width: 0;
        }

        .trust-label {
            display: block;
            margin-bottom: 3px;
            color: var(--text-muted);
            font-size: 0.72rem;
            font-weight: 600;
        }

        .trust-value {
            display: block;
            color: var(--text-color);
            font-size: 0.82rem;
            font-weight: 700;
            line-height: 1.35;
        }

        .trust-note {
            grid-column: 1 / -1;
            padding-top: 10px;
            border-top: 1px solid var(--border-color);
            color: var(--text-muted);
            font-size: 0.76rem;
            line-height: 1.5;
        }

        /* Enlarge Image Preview State */
        .compact-preview-wrapper {
            position: relative;
            width: 80%;
            height: 260px;
            margin: 0 auto 16px auto;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            background-color: var(--card-bg);
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .compact-preview-wrapper img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }

        .btn-clear-x {
            position: absolute;
            top: 4px;
            right: 4px;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background-color: rgba(0,0,0,0.6);
            color: white;
            border: none;
            font-size: 14px;
            line-height: 20px;
            text-align: center;
            cursor: pointer;
            font-weight: bold;
        }

        .btn {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: var(--control-min-height);
            height: 52px;
            border-radius: var(--control-radius);
            font-size: 1rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: transform 0.16s ease, background-color 0.16s ease,
                box-shadow 0.16s ease;
            box-sizing: border-box;
            margin-bottom: 10px;
            text-decoration: none;
        }

        .btn:active {
            transform: scale(0.98);
        }

        .btn:disabled {
            cursor: not-allowed;
            opacity: 0.55;
            transform: none;
        }

        .btn-primary {
            background-color: var(--primary-color);
            color: white;
            box-shadow: 0 8px 20px rgba(0, 122, 255, 0.22);
        }

        .btn-primary:active {
            background-color: var(--system-blue-pressed);
        }

        .btn-secondary {
            background-color: var(--surface);
            color: var(--primary-color);
            border: 1px solid var(--border-color);
            box-shadow: none;
        }

        .btn-secondary:active {
            background-color: var(--surface-muted);
        }

        .btn-outline {
            background-color: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-color);
        }

        .btn-outline:active {
            background-color: var(--surface-muted);
        }

        .btn-icon {
            width: 18px;
            height: 18px;
            margin-right: 8px;
        }

        .disclaimer-text {
            font-size: 0.78rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.5;
        }

        /* Screen: Result & Analyzing */
        .large-preview-wrapper {
            width: 100%;
            max-height: 52svh;
            border-radius: var(--card-radius);
            overflow: hidden;
            border: 1px solid var(--border-color);
            background-color: var(--card-bg);
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 16px;
        }

        .large-preview-wrapper img {
            width: 100%;
            height: auto;
            max-height: 52svh;
            object-fit: contain;
            display: block;
            border-radius: 12px;
        }

        .analyzing-status-box {
            text-align: center;
            margin-top: 12px;
        }

        .analyzing-subtitle {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 12px;
            line-height: 1.5;
        }

        .waiting-progress-track {
            position: relative;
            width: min(100%, 360px);
            height: 8px;
            margin: 0 auto 18px;
            overflow: hidden;
            border-radius: 999px;
            background-color: var(--separator);
        }

        .waiting-progress-indicator {
            display: block;
            width: 42%;
            height: 100%;
            border-radius: inherit;
            background-color: var(--secondary-color);
            box-shadow: 0 0 10px rgba(0, 122, 255, 0.25);
            animation: waiting-progress-sweep 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        }

        @keyframes waiting-progress-sweep {
            from { transform: translateX(-20%); }
            to { transform: translateX(138%); }
        }

        .waiting-tip-card {
            width: min(100%, 420px);
            margin: 0 auto;
            padding: 14px 16px;
            border: 1px solid var(--border-color);
            border-radius: 16px;
            background-color: var(--surface);
            text-align: left;
        }

        .waiting-tip-label {
            display: block;
            margin-bottom: 5px;
            color: var(--secondary-color);
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.02em;
        }

        .waiting-tip-text {
            min-height: 3em;
            margin: 0;
            color: var(--text-color);
            font-size: 0.9rem;
            font-weight: 600;
            line-height: 1.5;
            transition: opacity 0.18s ease;
        }

        .waiting-long-note {
            margin: 12px auto 0;
            color: var(--text-muted);
            font-size: 0.78rem;
            line-height: 1.5;
        }

        .waiting-long-note[hidden] {
            display: none;
        }

        /* Screen: Result & Suggestions */
        .screen-nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            min-height: var(--control-min-height);
            margin-bottom: 18px;
            flex-shrink: 0;
            position: sticky;
            top: 0;
            z-index: 5;
            background: rgba(245, 245, 247, 0.90);
            -webkit-backdrop-filter: blur(18px) saturate(160%);
            backdrop-filter: blur(18px) saturate(160%);
        }

        .nav-back {
            background: transparent;
            border: none;
            color: var(--secondary-color);
            min-width: 64px;
            min-height: var(--control-min-height);
            padding: 8px 0;
            font-size: 0.96rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            cursor: pointer;
            border-radius: 10px;
        }

        .nav-back svg {
            width: 18px;
            height: 18px;
            margin-right: 4px;
        }

        .nav-title {
            font-size: 1.02rem;
            font-weight: 700;
            letter-spacing: -0.015em;
        }

        .result-summary {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            padding: 16px;
            display: flex;
            justify-content: space-around;
            margin-bottom: 16px;
            flex-shrink: 0;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.05);
        }

        .analysis-mode-banner {
            border-radius: 10px;
            margin-bottom: 12px;
            padding: 10px 12px;
            font-size: 0.85rem;
            font-weight: 700;
            text-align: center;
        }

        .analysis-mode-banner.mode-gemini {
            background-color: rgba(16, 185, 129, 0.12);
            border: 1px solid var(--success-color);
            color: var(--success-color);
        }

        .analysis-mode-banner.mode-mock,
        .analysis-mode-banner.mode-warning {
            background-color: rgba(245, 158, 11, 0.1);
            border: 1px solid var(--warning-color);
            color: var(--warning-color);
        }

        .summary-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .summary-label {
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-bottom: 4px;
        }

        .summary-value {
            font-size: 1.45rem;
            font-weight: 750;
            letter-spacing: -0.03em;
        }

        .badge {
            padding: 4px 11px;
            border-radius: 999px;
            font-weight: 750;
            font-size: 0.9rem;
        }

        .badge-low {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--success-color);
            border: 1px solid var(--success-color);
        }

        .badge-medium {
            background-color: rgba(245, 158, 11, 0.15);
            color: var(--warning-color);
            border: 1px solid var(--warning-color);
        }

        .badge-high {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--danger-color);
            border: 1px solid var(--danger-color);
        }

        .result-images-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-bottom: 20px;
        }

        .result-image-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            overflow: hidden;
            padding: 14px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.04);
        }

        .image-card-title {
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 10px;
            display: block;
        }

        .image-wrapper {
            width: 100%;
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            background-color: var(--surface-muted);
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .image-wrapper img {
            width: 100%;
            height: auto;
            display: block;
            object-fit: contain;
        }

        .result-actions, .suggestions-actions {
            margin-top: auto;
            padding: 14px 0 max(2px, env(safe-area-inset-bottom));
            flex-shrink: 0;
        }

        .result-actions {
            position: sticky;
            bottom: -20px;
            z-index: 4;
            background: linear-gradient(
                to bottom,
                rgba(245, 245, 247, 0),
                rgba(245, 245, 247, 0.98) 24px
            );
            padding-top: 28px;
        }

        .download-error {
            margin: 0 0 10px;
            color: var(--danger-color);
            font-size: 0.9rem;
            font-weight: 600;
            line-height: 1.5;
            text-align: left;
        }

        /* Screen 3: Action Suggestions */
        .section-title {
            font-size: 1.75rem;
            line-height: 1.25;
            font-weight: 750;
            letter-spacing: -0.035em;
            margin-bottom: 8px;
        }

        .section-subtitle {
            font-size: 0.92rem;
            line-height: 1.55;
            color: var(--text-muted);
            margin-bottom: 20px;
        }

        .action-cards-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 16px;
        }

        /* Custom Accordion Cards */
        .accordion-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            overflow: hidden;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.035);
        }

        .accordion-card-header {
            width: 100%;
            min-height: var(--control-min-height);
            padding: 14px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
            border: 0;
            background: transparent;
            color: inherit;
            font: inherit;
            text-align: left;
        }

        .accordion-card-title-group {
            display: flex;
            flex-direction: column;
        }

        .accordion-card-title {
            font-size: 0.96rem;
            font-weight: 700;
            color: var(--text-color);
        }

        .accordion-card-sub {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-top: 4px;
        }

        .accordion-card-label {
            font-size: 0.72rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 999px;
        }

        .accordion-card-count {
            font-size: 0.78rem;
            color: var(--text-muted);
            font-weight: 500;
        }

        .accordion-card-icon {
            width: 18px;
            height: 18px;
            color: var(--text-muted);
            transition: transform 0.25s ease;
        }

        .accordion-card.open .accordion-card-icon {
            transform: rotate(180deg);
        }

        .accordion-card-content {
            padding: 0 16px;
        }

        .accordion-card.open .accordion-card-content {
            padding: 12px 16px 16px 16px;
            border-top: 1px solid var(--border-color);
        }

        /* Color variations for left borders and badges */
        .family-card {
            border-left: 4px solid var(--accent-green);
        }
        .family-card .accordion-card-label {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
        }

        .care-card {
            border-left: 4px solid var(--accent-blue);
        }
        .care-card .accordion-card-label {
            background-color: rgba(59, 130, 246, 0.15);
            color: var(--accent-blue);
        }

        .contractor-card {
            border-left: 4px solid var(--accent-red);
        }
        .contractor-card .accordion-card-label {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--accent-red);
        }

        .card-body {
            font-size: 0.94rem;
            line-height: 1.65;
            color: var(--text-color);
        }

        /* Markdown styles */
        .markdown-body h2, .markdown-body h3 {
            font-size: 0.96rem;
            margin-top: 12px;
            margin-bottom: 6px;
            font-weight: bold;
            color: var(--text-color);
        }
        
        .markdown-body p {
            margin-bottom: 6px;
        }

        .markdown-body ul, .markdown-body ol {
            padding-left: 16px;
            margin-bottom: 8px;
        }

        .markdown-body li {
            margin-bottom: 5px;
        }

        .action-report > h2,
        .action-report > ul > li:nth-child(-n + 2) {
            display: none;
        }

        .action-report > h3 {
            margin-top: 14px;
            font-size: 1rem;
            letter-spacing: -0.01em;
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                transition-duration: 0.01ms !important;
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
            }

            .waiting-progress-indicator {
                width: 68%;
                transform: none;
            }
        }
    </style>
</head>
<body>
    <div id="app-container">
        <!-- Separate Hidden Inputs for Camera and Library -->
        <input type="file" id="camera-input" accept="image/*" capture="environment" style="display: none;">
        <input type="file" id="library-input" accept="image/*" style="display: none;">

        <!-- SCREEN 1: Home / Photo Input -->
        <div id="screen-home" class="screen active" aria-hidden="false">
            <div class="home-header">
                <div class="app-tag">親の家 安全チェック</div>
                <h1
                    class="home-title"
                    data-screen-title
                    tabindex="-1"
                    aria-label="写真1枚で、親の家を安全チェック"
                >
                    写真1枚で、<br>親の家を安全チェック
                </h1>
                <p class="home-lead">
                    写真に写っている転倒・すべり・つまずきの注意箇所を確認します。
                </p>
            </div>

            <p class="place-section-title">撮影する場所の例</p>
            <div class="place-grid">
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4"/></svg>
                    <span>玄関</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18"/></svg>
                    <span>廊下</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 21h10M12 3v4M5 7h14a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2V9a2 2 0 012-2z"/></svg>
                    <span>浴室</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="2"/><line x1="12" y1="18" x2="12" y2="18.01"/></svg>
                    <span>トイレ</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V7"/><path d="M21 7H3l2-4h14l2 4z"/></svg>
                    <span>寝室</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3v4a1 1 0 001 1h4"/><path d="M4 14h6v7H4z"/><circle cx="17" cy="17" r="3"/></svg>
                    <span>キッチン</span>
                </div>
            </div>
            <p class="shooting-hint">
                床・段差・手すり・通路が一緒に写るように、まずは1か所を撮影してください。
            </p>

            <div class="home-controls">
                <div
                    id="error-message"
                    class="error-message"
                    role="alert"
                    aria-live="assertive"
                    style="display: none;"
                ></div>
            </div>

            <div class="home-footer">
                <div class="trust-card" aria-label="このチェックについて">
                    <div class="trust-item">
                        <span class="trust-label">写真の取り扱い</span>
                        <strong class="trust-value">写真は保存しません</strong>
                    </div>
                    <div class="trust-item">
                        <span class="trust-label">確認できること</span>
                        <strong class="trust-value">見える範囲のみ確認します</strong>
                    </div>
                    <p class="trust-note">
                        POC版です。医療・介護・保険・施工の専門判断を代替しません。
                    </p>
                </div>

                <!-- Select buttons state -->
                <div id="selection-buttons-container">
                    <button id="btn-camera" class="btn btn-primary">
                        <svg class="btn-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M4 4h3l2-2h6l2 2h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm8 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/>
                        </svg>
                        カメラで撮る
                    </button>
                    <button id="btn-library" class="btn btn-secondary">
                        <svg class="btn-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-9 14l-4-4 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                        </svg>
                        ライブラリから選ぶ
                    </button>
                </div>
            </div>
        </div>

        <!-- SCREEN 2: Safety Check Result / Analyzing -->
        <div id="screen-result" class="screen" aria-hidden="true">
            <div class="screen-nav">
                <button class="nav-back btn-back-home">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.828 12l4.95 4.95-1.414 1.414-6.364-6.364 6.364-6.364 1.414 1.414z"/>
                    </svg>
                    ホーム
                </button>
                <span class="nav-title" id="screen2-title" data-screen-title tabindex="-1">
                    写真確認中
                </span>
                <div style="width: 60px;"></div>
            </div>

            <!-- 1. Analyzing State Container -->
            <div id="result-analyzing-container">
                <div class="large-preview-wrapper">
                    <img id="result-large-preview" src="" alt="Selected Photo">
                </div>
                <div class="analyzing-status-box">
                    <p id="waiting-status-text" class="analyzing-subtitle" role="status" aria-live="polite">
                        写真を安全に準備しています…
                    </p>
                    <div
                        id="waiting-progress-track"
                        class="waiting-progress-track"
                        role="progressbar"
                        aria-label="写真確認の進行状況"
                    >
                        <span class="waiting-progress-indicator" aria-hidden="true"></span>
                    </div>
                    <div class="waiting-tip-card">
                        <span class="waiting-tip-label">待ち時間にできる安全確認</span>
                        <p id="waiting-tip-text" class="waiting-tip-text">
                            夜間に通る場所は、足元まで明るく見えるか確認してみましょう。
                        </p>
                    </div>
                    <p id="waiting-long-note" class="waiting-long-note" hidden>
                        写真によっては確認に少し時間がかかります。このまま画面を開いてお待ちください。
                    </p>
                </div>
            </div>

            <!-- 2. Completed State Container -->
            <div id="result-completed-container" style="display: none;">
                <div id="analysis-mode-banner" class="analysis-mode-banner mode-warning" role="status"></div>
                <div class="result-summary">
                    <div class="summary-item">
                        <span class="summary-label">注意が必要な箇所</span>
                        <span id="risk-count" class="summary-value">--件</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">総合リスク</span>
                        <span id="risk-badge" class="badge">--</span>
                    </div>
                </div>

                <!-- Not Applicable Warning Box -->
                <div id="not-applicable-container" style="display: none; background-color: rgba(201, 52, 0, 0.08); border: 1px solid var(--warning-color); border-radius: 16px; padding: 16px; margin-bottom: 20px; text-align: center;">
                    <p id="not-applicable-message" style="color: var(--warning-color); font-weight: bold; font-size: 0.95rem;"></p>
                </div>

                <!-- Stacked Images: Annotated first, Improvement second -->
                <div class="result-images-list">
                    <div class="result-image-card">
                        <span class="image-card-title">現在の注意箇所</span>
                        <div class="image-wrapper">
                            <img id="result-annotated-img" src="" alt="赤枠で注意箇所を示した現在の写真">
                        </div>
                    </div>
                    <div class="result-image-card">
                        <span class="image-card-title">対策イメージ（施工図ではありません）</span>
                        <div class="image-wrapper">
                            <img id="result-improvement-img" src="" alt="注意箇所への一般的な対策イメージ">
                        </div>
                    </div>
                </div>

                <!-- Hidden Debug Panel -->
                <div class="debug-panel" style="display: none; background-color: var(--surface); border: 1px dashed var(--border-color); border-radius: 12px; padding: 12px; font-size: 0.75rem; font-family: monospace; margin-top: 16px; text-align: left;">
                    <div style="font-weight: bold; margin-bottom: 4px; color: var(--warning-color);">[DEBUG INFO]</div>
                    <div>Mode: <span class="debug-mode">--</span></div>
                    <div>Analysis ID: <span class="debug-analysis-id">--</span></div>
                    <div>Model: <span class="debug-model">--</span></div>
                    <div>Findings Count: <span class="debug-finding-count">--</span></div>
                    <div>Is Home Environment: <span class="debug-is-home">--</span></div>
                </div>

                <div class="result-actions">
                    <button id="btn-show-suggestions" class="btn btn-primary">安全のための対策を見る</button>
                    <button class="btn btn-outline btn-back-home">ホームに戻る</button>
                </div>
            </div>
        </div>

        <!-- SCREEN 3: Action Suggestions -->
        <div id="screen-suggestions" class="screen" aria-hidden="true">
            <div class="screen-nav">
                <button id="btn-back-to-result" class="nav-back">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.828 12l4.95 4.95-1.414 1.414-6.364-6.364 6.364-6.364 1.414 1.414z"/>
                    </svg>
                    戻る
                </button>
                <span class="nav-title">安全のためにできること</span>
                <div style="width: 60px;"></div>
            </div>

            <h1 class="section-title" data-screen-title tabindex="-1">安全のためにできること</h1>
            <p class="section-subtitle">
                安全のため、家族で今日できることから順に確認してください。
            </p>

            <!-- Collapsed Accordion Cards -->
            <div class="action-cards-container">
                <!-- Family Card -->
                <div class="accordion-card family-card open">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="true"
                        aria-controls="accordion-family"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">家族で今日できること</span>
                            <span class="accordion-card-sub">
                                <span class="accordion-card-label">今日・費用なし</span>
                                <span id="family-count" class="accordion-card-count"></span>
                            </span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-family" class="accordion-card-content">
                        <div id="action-family-content" class="card-body markdown-body action-report"></div>
                    </div>
                </div>

                <!-- Care Manager Card -->
                <div class="accordion-card care-card">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="false"
                        aria-controls="accordion-care"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">ケアマネ・福祉用具に相談</span>
                            <span class="accordion-card-sub">
                                <span class="accordion-card-label">購入・レンタルの相談</span>
                                <span id="care-count" class="accordion-card-count"></span>
                            </span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-care" class="accordion-card-content" hidden>
                        <div id="action-care-content" class="card-body markdown-body action-report"></div>
                    </div>
                </div>

                <!-- Contractor Card -->
                <div class="accordion-card contractor-card">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="false"
                        aria-controls="accordion-contractor"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">専門施工・現地確認</span>
                            <span class="accordion-card-sub">
                                <span class="accordion-card-label">工事・現地確認</span>
                                <span id="contractor-count" class="accordion-card-count"></span>
                            </span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-contractor" class="accordion-card-content" hidden>
                        <div id="action-contractor-content" class="card-body markdown-body action-report"></div>
                    </div>
                </div>

                <!-- Risk Basis Card -->
                <div class="accordion-card basis-card">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="false"
                        aria-controls="accordion-basis"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">詳しいリスク根拠を見る</span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-basis" class="accordion-card-content" hidden>
                        <div id="risk-details-content" class="markdown-body"></div>
                    </div>
                </div>
            </div>

            <p class="disclaimer-text" style="color: var(--text-muted); text-align: left; margin: 16px 0;">
                ※POC版です。医療・介護・施工判断を代替しません。<br>
                ※対策イメージはコミュニケーション用であり施工図ではありません。
            </p>

            <!-- Hidden Debug Panel -->
            <div class="debug-panel" style="display: none; background-color: var(--surface); border: 1px dashed var(--border-color); border-radius: 12px; padding: 12px; font-size: 0.75rem; font-family: monospace; margin-top: 16px; text-align: left; margin-bottom: 16px;">
                <div style="font-weight: bold; margin-bottom: 4px; color: var(--warning-color);">[DEBUG INFO]</div>
                <div>Mode: <span class="debug-mode">--</span></div>
                <div>Analysis ID: <span class="debug-analysis-id">--</span></div>
                <div>Model: <span class="debug-model">--</span></div>
                <div>Findings Count: <span class="debug-finding-count">--</span></div>
                <div>Is Home Environment: <span class="debug-is-home">--</span></div>
            </div>

            <div class="suggestions-actions">
                <button id="btn-download-pdf" class="btn btn-secondary" type="button" disabled>
                    この内容をPDFで保存
                </button>
                <p
                    id="pdf-download-error"
                    class="download-error"
                    role="alert"
                    aria-live="assertive"
                    hidden
                ></p>
                <button class="btn btn-outline btn-back-home">ホームに戻る</button>
            </div>
        </div>
    </div>

    <script>
        const cameraInput = document.getElementById('camera-input');
        const libraryInput = document.getElementById('library-input');
        const btnCamera = document.getElementById('btn-camera');
        const btnLibrary = document.getElementById('btn-library');
        const errorDiv = document.getElementById('error-message');

        const btnShowSuggestions = document.getElementById('btn-show-suggestions');
        const btnBackToResult = document.getElementById('btn-back-to-result');
        const pdfDownloadButton = document.getElementById('btn-download-pdf');
        const pdfDownloadError = document.getElementById('pdf-download-error');
        const btnBackHomes = document.querySelectorAll('.btn-back-home');

        let selectedFile = null;
        let latestReportPayload = null;

        function resetPdfDownloadState() {
            latestReportPayload = null;
            pdfDownloadButton.disabled = true;
            pdfDownloadButton.textContent = 'この内容をPDFで保存';
            pdfDownloadError.textContent = '';
            pdfDownloadError.hidden = true;
        }

        // Nav functions
        function showScreen(screenId) {
            const screens = document.querySelectorAll('.screen');
            screens.forEach(screen => {
                screen.classList.remove('active');
                screen.setAttribute('aria-hidden', 'true');
            });
            const nextScreen = document.getElementById(screenId);
            nextScreen.classList.add('active');
            nextScreen.setAttribute('aria-hidden', 'false');
            nextScreen.scrollTop = 0;

            requestAnimationFrame(() => {
                const screenTitle = nextScreen.querySelector('[data-screen-title]');
                if (screenTitle) {
                    screenTitle.focus({ preventScroll: true });
                }
            });
        }

        btnCamera.addEventListener('click', () => {
            errorDiv.style.display = 'none';
            cameraInput.click();
            if (!/Mobi|Android|iPhone/i.test(navigator.userAgent)) {
                errorDiv.textContent = "このブラウザではカメラ起動が制限される場合があります。ライブラリから選択してください。";
                errorDiv.style.display = "block";
            }
        });

        btnLibrary.addEventListener('click', () => {
            errorDiv.style.display = 'none';
            libraryInput.click();
        });

        cameraInput.addEventListener('change', handleFileSelect);
        libraryInput.addEventListener('change', handleFileSelect);

        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;

            resetPdfDownloadState();
            selectedFile = file;
            errorDiv.style.display = 'none';

            // Show selected photo in Screen 2 immediately
            const reader = new FileReader();
            reader.onload = function(e) {
                document.getElementById('result-large-preview').src = e.target.result;
            };
            reader.readAsDataURL(file);

            // Move directly to Screen 2
            showScreen('screen-result');

            // Reset Screen 2 state to "Analyzing"
            document.getElementById('screen2-title').textContent = "写真確認中";
            document.getElementById('result-analyzing-container').style.display = 'block';
            document.getElementById('result-completed-container').style.display = 'none';

            // Start browser-only waiting guidance. This does not add requests.
            startWaitingExperience();

            // Run analysis immediately
            uploadAndAnalyze(selectedFile);
        }

        // Clear preview / reset to home
        function clearPreview() {
            stopWaitingExperience();
            selectedFile = null;
            cameraInput.value = '';
            libraryInput.value = '';
            document.getElementById('result-large-preview').src = '';
            errorDiv.style.display = 'none';
        }

        const waitingTips = [
            '夜間に通る場所は、足元まで明るく見えるか確認してみましょう。',
            '廊下や出入口に、つまずきやすい物が置かれていないか見直しましょう。',
            '浴室や洗面所の床は、濡れたままにしないことが大切です。',
            'よく使う物は、無理に背伸びをしない高さに置くと安心です。'
        ];
        const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
        let waitingPhaseTimer = null;
        let waitingTipTimer = null;
        let waitingLongNoteTimer = null;
        let waitingTipIndex = 0;

        function renderWaitingPhase(elapsedMs) {
            const status = document.getElementById('waiting-status-text');
            if (elapsedMs < 8000) {
                status.textContent = '写真を安全に準備しています…';
            } else if (elapsedMs < 20000) {
                status.textContent = '写真に写っている注意点を確認しています…';
            } else {
                status.textContent = '確認結果をまとめています…';
            }
        }

        function startWaitingExperience() {
            stopWaitingExperience();
            waitingTipIndex = 0;

            const tip = document.getElementById('waiting-tip-text');
            const longNote = document.getElementById('waiting-long-note');
            const track = document.getElementById('waiting-progress-track');
            tip.textContent = waitingTips[waitingTipIndex];
            longNote.hidden = true;
            track.dataset.reducedMotion = String(reducedMotionQuery.matches);
            renderWaitingPhase(0);

            waitingPhaseTimer = setTimeout(() => {
                renderWaitingPhase(8000);
                waitingPhaseTimer = setTimeout(() => {
                    renderWaitingPhase(20000);
                    waitingPhaseTimer = null;
                }, 12000);
            }, 8000);

            waitingTipTimer = setInterval(() => {
                waitingTipIndex = (waitingTipIndex + 1) % waitingTips.length;
                tip.textContent = waitingTips[waitingTipIndex];
            }, 6000);

            waitingLongNoteTimer = setTimeout(() => {
                longNote.hidden = false;
                waitingLongNoteTimer = null;
            }, 24000);
        }

        function stopWaitingExperience() {
            clearTimeout(waitingPhaseTimer);
            clearInterval(waitingTipTimer);
            clearTimeout(waitingLongNoteTimer);
            waitingPhaseTimer = null;
            waitingTipTimer = null;
            waitingLongNoteTimer = null;
            document.getElementById('waiting-long-note').hidden = true;
        }

        async function uploadAndAnalyze(file) {
            const formData = new FormData();
            formData.append('image', file);
            formData.append('room_hint', 'auto');

            try {
                const response = await fetch('/analyze', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    throw new Error('分析サービスとの通信に失敗しました。');
                }

                const data = await response.json();
                stopWaitingExperience();
                renderResults(data);

            } catch (err) {
                stopWaitingExperience();
                console.error(err);
                showScreen('screen-home');
                errorDiv.textContent = err.message || '分析エラーが発生しました。';
                errorDiv.style.display = 'block';
            }
        }

        function countItems(markdown) {
            if (!markdown) return 0;
            const matches = markdown.match(/###/g);
            return matches ? matches.length : 0;
        }

        function renderSafeMarkdown(target, markdown) {
            const fragment = document.createDocumentFragment();
            let currentList = null;

            String(markdown || '').split(/\r?\n/).forEach(rawLine => {
                const line = rawLine.trim();
                if (!line) {
                    currentList = null;
                    return;
                }

                let node;
                let content;
                if (line.startsWith('### ')) {
                    node = document.createElement('h3');
                    content = line.slice(4);
                    currentList = null;
                } else if (line.startsWith('## ')) {
                    node = document.createElement('h2');
                    content = line.slice(3);
                    currentList = null;
                } else if (line.startsWith('- ') || line.startsWith('* ')) {
                    if (!currentList) {
                        currentList = document.createElement('ul');
                        fragment.appendChild(currentList);
                    }
                    node = document.createElement('li');
                    content = line.slice(2);
                    node.textContent = content;
                    currentList.appendChild(node);
                    return;
                } else {
                    node = document.createElement('p');
                    content = line;
                    currentList = null;
                }

                node.textContent = content;
                fragment.appendChild(node);
            });

            target.replaceChildren(fragment);
        }

        function renderResults(payload) {
            const isNotApplicable = payload.is_not_applicable === true || payload.is_home_environment === false;
            const resultSummary = document.querySelector('.result-summary');
            const notAppContainer = document.getElementById('not-applicable-container');
            const notAppMsg = document.getElementById('not-applicable-message');
            const imagesList = document.querySelector('.result-images-list');

            resetPdfDownloadState();
            renderAnalysisModeBanner(payload);

            // Set risk badge
            const riskBadge = document.getElementById('risk-badge');
            const overallRisk = payload.overall_risk_level || 'medium';
            riskBadge.textContent = getRiskLabel(overallRisk);
            riskBadge.className = 'badge badge-' + overallRisk;

            // Set findings count
            const count = payload.findings ? payload.findings.length : 0;
            document.getElementById('risk-count').textContent = count + '件';

            if (isNotApplicable) {
                notAppMsg.textContent = payload.not_applicable_reason_ja || "この写真では確認結果を表示できません。";
                notAppContainer.style.display = 'block';
                resultSummary.style.display = 'none';
                imagesList.style.display = 'none';
                btnShowSuggestions.style.display = 'none';
            } else {
                notAppContainer.style.display = 'none';
                resultSummary.style.display = 'flex';
                imagesList.style.display = 'flex';
                btnShowSuggestions.style.display = '';
                
                // Set Images
                document.getElementById('result-annotated-img').src = 'data:image/png;base64,' + payload.annotated_image_base64;
                document.getElementById('result-improvement-img').src = 'data:image/png;base64,' + payload.improvement_image_base64;

                latestReportPayload = {
                    finding_count: count,
                    overall_risk_level: overallRisk,
                    family_actions_markdown: payload.family_actions_markdown || '',
                    care_manager_actions_markdown: payload.care_manager_actions_markdown || '',
                    contractor_actions_markdown: payload.contractor_actions_markdown || '',
                    risk_summary_markdown: payload.risk_summary_markdown || ''
                };
                pdfDownloadButton.disabled = false;
            }

            renderSafeMarkdown(
                document.getElementById('action-family-content'),
                payload.family_actions_markdown
            );
            renderSafeMarkdown(
                document.getElementById('action-care-content'),
                payload.care_manager_actions_markdown
            );
            renderSafeMarkdown(
                document.getElementById('action-contractor-content'),
                payload.contractor_actions_markdown
            );
            renderSafeMarkdown(
                document.getElementById('risk-details-content'),
                payload.risk_summary_markdown
            );

            // Set dynamic counts in headers
            const famCount = countItems(payload.family_actions_markdown);
            document.getElementById('family-count').textContent = famCount ? `(${famCount}件)` : '';

            const cCount = countItems(payload.care_manager_actions_markdown);
            document.getElementById('care-count').textContent = cCount ? `(${cCount}件)` : '';

            const conCount = countItems(payload.contractor_actions_markdown);
            document.getElementById('contractor-count').textContent = conCount ? `(${conCount}件)` : '';

            // Keep the safest immediate actions open and the other tiers collapsed.
            document.querySelectorAll('.accordion-card').forEach(card => {
                const header = card.querySelector('.accordion-card-header');
                const content = document.getElementById(header.getAttribute('aria-controls'));
                const shouldOpen = card.classList.contains('family-card');
                card.classList.toggle('open', shouldOpen);
                header.setAttribute('aria-expanded', String(shouldOpen));
                content.hidden = !shouldOpen;
            });

            // Update Debug Panel
            updateDebugPanel(payload);

            stopWaitingExperience();
            
            // Switch title and transition to completed layout inside Screen 2
            document.getElementById('screen2-title').textContent = "安全チェック結果";
            document.getElementById('result-analyzing-container').style.display = 'none';
            document.getElementById('result-completed-container').style.display = 'block';
        }

        function renderAnalysisModeBanner(payload) {
            const banner = document.getElementById('analysis-mode-banner');
            const mode = typeof payload.mode === 'string' ? payload.mode : '';
            let text = '実行モードを確認できません';
            let style = 'mode-warning';

            if (mode === 'gemini') {
                text = 'Gemini解析結果';
                style = 'mode-gemini';
            } else if (mode === 'mock') {
                text = 'モック結果（AI実解析ではありません）';
                style = 'mode-mock';
            } else if (mode === 'local_mock') {
                text = 'ローカルモック結果（AI実解析ではありません）';
                style = 'mode-mock';
            } else if (mode.startsWith('gemini_fallback(')) {
                text = 'フォールバック結果（Gemini解析として扱わないでください）';
                style = 'mode-warning';
            } else if (mode.startsWith('gemini_partial(')) {
                text = '部分解析（補完に失敗したため安全判定として扱わないでください）';
                style = 'mode-warning';
            }

            banner.textContent = text;
            banner.className = 'analysis-mode-banner ' + style;
        }

        function updateDebugPanel(payload) {
            const urlParams = new URLSearchParams(window.location.search);
            const isDebug = urlParams.get('debug') === '1';
            
            const panels = document.querySelectorAll('.debug-panel');
            panels.forEach(panel => {
                panel.style.display = isDebug ? 'block' : 'none';
            });
            
            if (isDebug && payload) {
                const mode = payload.mode || 'N/A';
                const analysisId = payload.analysis_id || 'N/A';
                const model = payload.model || 'N/A';
                const count = payload.findings ? payload.findings.length : 0;
                const isHome = payload.is_home_environment !== false;
                
                document.querySelectorAll('.debug-mode').forEach(el => el.textContent = mode);
                document.querySelectorAll('.debug-analysis-id').forEach(el => el.textContent = analysisId);
                document.querySelectorAll('.debug-model').forEach(el => el.textContent = model);
                document.querySelectorAll('.debug-finding-count').forEach(el => el.textContent = count);
                document.querySelectorAll('.debug-is-home').forEach(el => el.textContent = isHome ? 'True' : 'False');
            }
        }

        function getRiskLabel(risk) {
            if (risk === 'low') return '低';
            if (risk === 'medium') return '中';
            if (risk === 'high') return '高';
            return '中';
        }

        async function downloadSuggestionsPdf() {
            if (!latestReportPayload || pdfDownloadButton.disabled) return;

            pdfDownloadButton.disabled = true;
            pdfDownloadButton.textContent = 'PDFを作成中…';
            pdfDownloadError.textContent = '';
            pdfDownloadError.hidden = true;

            try {
                const response = await fetch('/suggestions.pdf', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(latestReportPayload)
                });
                if (!response.ok) throw new Error('pdf_download_failed');

                const blob = await response.blob();
                const disposition = response.headers.get('Content-Disposition') || '';
                const match = disposition.match(/filename="([A-Za-z0-9._-]+)"/);
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = match ? match[1] : 'sumai-guard-safety-actions.pdf';
                document.body.appendChild(link);
                link.click();
                link.remove();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (_error) {
                pdfDownloadError.textContent = 'PDFを保存できませんでした。時間をおいて、もう一度お試しください。';
                pdfDownloadError.hidden = false;
            } finally {
                pdfDownloadButton.textContent = 'この内容をPDFで保存';
                pdfDownloadButton.disabled = latestReportPayload === null;
            }
        }

        // Accordion Card Toggle Handler
        document.querySelectorAll('.accordion-card-header').forEach(header => {
            header.addEventListener('click', () => {
                const card = header.closest('.accordion-card');
                const contentId = header.getAttribute('aria-controls');
                const content = document.getElementById(contentId);
                const willOpen = header.getAttribute('aria-expanded') !== 'true';
                card.classList.toggle('open', willOpen);
                header.setAttribute('aria-expanded', String(willOpen));
                content.hidden = !willOpen;
            });
        });

        // Navigate between result and action cards
        btnShowSuggestions.addEventListener('click', () => {
            showScreen('screen-suggestions');
        });

        btnBackToResult.addEventListener('click', () => {
            showScreen('screen-result');
        });

        pdfDownloadButton.addEventListener('click', downloadSuggestionsPdf);

        // Reset flow
        function resetApp() {
            clearPreview();
            resetPdfDownloadState();
            updateDebugPanel(null);
            showScreen('screen-home');
        }

        btnBackHomes.forEach(btn => {
            btn.addEventListener('click', resetApp);
        });
    </script>
</body>
</html>
"""


FRONTEND_REQUIRE_REAL_GEMINI = os.getenv("REQUIRE_REAL_GEMINI", "false").strip().lower() in {"1", "true", "yes", "on"}


def _positive_timeout_env(name: str, default: float | str) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


_analysis_timeout_fallback = _positive_timeout_env("ANALYSIS_TIMEOUT", 120.0)
SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS = _positive_timeout_env(
    "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS", _analysis_timeout_fallback
)
SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS = _positive_timeout_env(
    "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS", 30.0
)
_proxy_timeout_override = os.getenv("SUMAI_AGENT_TIMEOUT_SECONDS", "").strip()
SUMAI_AGENT_TIMEOUT_SECONDS = (
    _positive_timeout_env("SUMAI_AGENT_TIMEOUT_SECONDS", 0.0)
    if _proxy_timeout_override
    else SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS + SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS
)
_required_proxy_timeout = (
    SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS + SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS
)
if SUMAI_AGENT_TIMEOUT_SECONDS < _required_proxy_timeout:
    raise ValueError(
        "SUMAI_AGENT_TIMEOUT_SECONDS must be at least "
        "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS plus "
        "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS"
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await close_backend_client()


class PublicWebAnalysisGateMiddleware:
    """Reject public photo uploads from ASGI scope data before body parsing."""

    def __init__(self, app: ASGIApp, *, analysis_enabled: bool) -> None:
        self.app = app
        self.analysis_enabled = analysis_enabled

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or get_route_path(scope) != "/analyze":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_without_storage(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        if not self.analysis_enabled:
            response = JSONResponse(
                status_code=503,
                content={
                    "error": "NATIVE_APP_REQUIRED",
                    "message": "公開版の写真解析はiPhoneアプリからご利用ください。",
                },
            )
            await response(scope, receive, send_without_storage)
            return

        try:
            await self.app(scope, receive, send_without_storage)
        except Exception as exc:
            if response_started:
                raise
            logger.error(
                "web_analysis_unexpected_failure",
                extra={
                    "failure_code": "ANALYSIS_FAILED",
                    "failure_type": type(exc).__name__,
                },
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": "ANALYSIS_FAILED",
                    "message": (
                        "分析を完了できませんでした。"
                        "時間をおいて、もう一度お試しください。"
                    ),
                },
            )
            await response(scope, receive, send_without_storage)


app = FastAPI(title="SumaiGuard Web", lifespan=lifespan)
app.add_middleware(
    PublicWebAnalysisGateMiddleware,
    analysis_enabled=PUBLIC_WEB_ANALYSIS_ENABLED,
)


@app.exception_handler(RequestValidationError)
async def safe_request_validation_error(
    request: Request,
    exc: RequestValidationError,
):
    if request.url.path == "/suggestions.pdf":
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_pdf_request",
                "message": "PDFの内容が無効です。画面を再読み込みして、もう一度お試しください。",
            },
        )
    return await request_validation_exception_handler(request, exc)


def backend_client() -> httpx.AsyncClient:
    global _backend_client
    if _backend_client is None:
        _backend_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                SUMAI_AGENT_TIMEOUT_SECONDS,
                connect=min(10.0, SUMAI_AGENT_TIMEOUT_SECONDS / 2),
            )
        )
    return _backend_client


async def close_backend_client() -> None:
    """Close the reusable backend client before its event loop is discarded."""
    global _backend_client
    client = _backend_client
    _backend_client = None
    if client is None:
        return
    try:
        await client.aclose()
    except Exception as exc:
        logger.warning("backend_client_close_failed", extra={"failure_type": type(exc).__name__})


def _safe_backend_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "gemini_unavailable",
            "message": "Real Gemini analysis is required but unavailable.",
        },
    )


def _safe_backend_client_error(status_code: int) -> JSONResponse:
    if status_code in {400, 422}:
        content = {
            "error": "invalid_upload",
            "message": "画像または入力内容が無効です。内容を確認して、もう一度お試しください。",
        }
    else:
        content = {
            "error": "backend_request_rejected",
            "message": "分析リクエストを処理できませんでした。入力内容を確認してください。",
        }
    return JSONResponse(status_code=status_code, content=content)


@app.get("/", response_class=HTMLResponse)
def get_home():
    return HTMLResponse(
        content=INDEX_HTML,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": HOME_CONTENT_SECURITY_POLICY,
        },
    )


@app.get("/privacy", response_class=HTMLResponse)
def get_privacy():
    return HTMLResponse(
        content=PRIVACY_HTML,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/support", response_class=HTMLResponse)
def get_support():
    return HTMLResponse(
        content=SUPPORT_HTML,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/suggestions.pdf")
def download_suggestions_pdf(report: SuggestionPdfRequest):
    try:
        content = build_safety_advice_pdf(report)
    except Exception as exc:
        logger.error(
            "pdf_generation_failed",
            extra={"failure_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "pdf_generation_failed",
                "message": "PDFを作成できませんでした。時間をおいて、もう一度お試しください。",
            },
        )

    generated_at = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                'attachment; filename="sumai-guard-safety-actions-'
                f'{generated_at}.pdf"'
            ),
            "Cache-Control": "no-store",
        },
    )


@app.post("/analyze")
async def analyze(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
):
    """Proxy requests to sumai-agent backend with a local mock fallback if unreachable."""
    image_bytes = await image.read()

    # Call sumai-agent backend
    try:
        files = {"image": (image.filename or "photo.png", image_bytes, image.content_type or "image/png")}
        data = {"room_hint": room_hint, "mock": "true" if FRONTEND_MOCK else "false"}
        response = await backend_client().post(
            f"{SUMAI_AGENT_URL}/api/v1/analyze", data=data, files=files
        )

        if response.status_code == 200:
            try:
                return JSONResponse(content=response.json())
            except Exception as exc:
                if FRONTEND_REQUIRE_REAL_GEMINI:
                    return _safe_backend_unavailable()
                logger.warning(
                    "backend_invalid_json", extra={"failure_type": type(exc).__name__}
                )
                payload = _build_local_mock(image_bytes, room_hint, "backend_invalid_response")
                return JSONResponse(content=payload)

        # Client errors describe this request, not backend availability. Preserve
        # their status without trusting or forwarding the upstream body.
        if 400 <= response.status_code < 500:
            logger.warning(
                "backend_request_rejected",
                extra={"status_code": response.status_code},
            )
            return _safe_backend_client_error(response.status_code)

        # A backend 503 always indicates that the strict provider path failed.
        # Its response body is not trusted because it may contain provider details.
        if FRONTEND_REQUIRE_REAL_GEMINI or response.status_code == 503:
            return _safe_backend_unavailable()

        if 500 <= response.status_code < 600:
            logger.warning(
                "backend_non_200", extra={"status_code": response.status_code}
            )
            payload = _build_local_mock(image_bytes, room_hint, "backend_http_error")
            return JSONResponse(content=payload)

        logger.warning(
            "backend_invalid_status", extra={"status_code": response.status_code}
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "backend_invalid_response",
                "message": "分析サービスから有効な応答を受け取れませんでした。",
            },
        )

    except httpx.RequestError as exc:
        if FRONTEND_REQUIRE_REAL_GEMINI:
            return _safe_backend_unavailable()
        logger.warning("backend_call_failed", extra={"failure_type": type(exc).__name__})
        payload = _build_local_mock(image_bytes, room_hint, "backend_unreachable")
        return JSONResponse(content=payload)


@app.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ok"}


def _build_local_mock(image_bytes: bytes, room_hint: str, reason: str) -> dict[str, Any]:
    """Return a neutral abstention when the analysis backend is unreachable."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        image = Image.new("RGB", (800, 600), (15, 16, 32))

    image_base64 = _to_base64_png(image)
    pixel_payload = (
        image.mode.encode("ascii")
        + image.width.to_bytes(4, "big")
        + image.height.to_bytes(4, "big")
        + image.tobytes()
    )
    pixel_digest = hashlib.sha256(pixel_payload).hexdigest()
    result_identity = {
        "execution_mode": "local_mock_abstention",
        "inference_config_version": "1.0.0",
        "model": "N/A",
        "ontology_version": "1.0.0",
        "pixel_digest": pixel_digest,
        "preprocess_version": "1.0.0",
        "room_hint": room_hint,
        "schema_version": "2.0.0",
    }
    result_key = hashlib.sha256(
        json.dumps(
            result_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    not_applicable_reason = (
        "解析バックエンドに接続できないため、安全上の判定を保留しました。"
        f"再接続後に解析してください（{reason[:120]}）。"
    )
    semantic_hash = hashlib.sha256(
        json.dumps(
            {
                "action_plan": {
                    "care_manager_purchase": [],
                    "contractor_construction": [],
                    "family_no_cost": [],
                },
                "findings": [],
                "is_home_environment": True,
                "not_applicable_reason_ja": not_applicable_reason,
                "room_type": "auto",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    neutral_report = (
        "## 判定保留\n\n"
        f"{not_applicable_reason}\n\n"
        "この表示は写真の安全性を評価した結果ではありません。"
    )
    empty_actions = "## 表示なし\n\n判定保留中のため、行動候補を表示していません。"
    return {
        "analysis_id": f"local_{uuid.uuid4().hex}",
        "room_type": "auto",
        "overall_risk_level": "low",
        "mode": "local_mock",
        "is_home_environment": True,
        "is_not_applicable": True,
        "not_applicable_reason_ja": not_applicable_reason,
        "findings": [],
        "action_plan": {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        },
        "annotated_image_base64": image_base64,
        "improvement_image_base64": image_base64,
        "risk_summary_markdown": neutral_report,
        "family_actions_markdown": empty_actions,
        "care_manager_actions_markdown": empty_actions,
        "contractor_actions_markdown": empty_actions,
        "disclaimer_ja": DISCLAIMER,
        "model": "N/A",
        "result_key": result_key,
        "semantic_hash": semantic_hash,
        "schema_version": "2.0.0",
        "ontology_version": "1.0.0",
        "preprocess_version": "1.0.0",
        "inference_config_version": "1.0.0",
        "stage_timings_ms": {
            "intake": 0,
            "memo_lookup": 0,
            "vision": 0,
            "ontology": 0,
            "render": 0,
            "report": 0,
            "serialize": 0,
            "total": 0,
        },
    }


def _to_base64_png(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=SUMAI_WEB_PORT, reload=True)
