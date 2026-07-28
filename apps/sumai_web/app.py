from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

import requests
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sumai.web")

SUMAI_AGENT_URL = os.getenv("SUMAI_AGENT_URL", "http://localhost:8080").rstrip("/")
SUMAI_WEB_PORT = int(os.getenv("SUMAI_WEB_PORT", "8081"))
FRONTEND_MOCK = os.getenv("MOCK_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title="SumaiGuard Web")

DISCLAIMER = (
    "POC版です。医療・介護・施工判断を代替しません。\n"
    "改善イメージはコミュニケーション用であり施工図ではありません。\n"
    "写真から正確な寸法や適用制度を判断するものではありません。"
)
WATERMARK = "コミュニケーション用イメージ｜施工図ではありません"


# HTML Template with mobile-first CSS and vanilla JS
INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>親の家 安全チェックAI</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
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
            grid-template-columns: 1fr 1fr;
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
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 16px;
        }

        .steps-container-compact {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 6px;
            background-color: var(--surface);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 8px 16px;
            display: inline-flex;
            margin: 0 auto;
        }

        .step-compact {
            font-size: 0.72rem;
            font-weight: 500;
            color: var(--text-muted);
            transition: all 0.3s ease;
        }

        .step-compact.active {
            color: var(--primary-color);
            font-weight: 700;
        }

        .step-compact.completed {
            color: var(--success-color);
            font-weight: 700;
        }

        .step-arrow-compact {
            font-size: 0.7rem;
            color: var(--separator);
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

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                transition-duration: 0.01ms !important;
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
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

        <!-- SCREEN 2: Visual Diagnosis Result / Analyzing -->
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
                <div class="analyzing-status-box" role="status" aria-live="polite">
                    <p class="analyzing-subtitle">AIが写真を確認しています…</p>
                    <div class="steps-container-compact">
                        <div class="step-compact active" id="step-c1">写真確認</div>
                        <div class="step-arrow-compact">→</div>
                        <div class="step-compact" id="step-c2">リスク判定</div>
                        <div class="step-arrow-compact">→</div>
                        <div class="step-compact" id="step-c3">改善案作成</div>
                    </div>
                </div>
            </div>

            <!-- 2. Completed State Container -->
            <div id="result-completed-container" style="display: none;">
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
                    <button id="btn-show-suggestions" class="btn btn-primary">次にできることを見る</button>
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
                <span class="nav-title">次にできること</span>
                <div style="width: 60px;"></div>
            </div>

            <h1 class="section-title" data-screen-title tabindex="-1">次にできること</h1>
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
                        <div id="action-family-content" class="card-body markdown-body"></div>
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
                        <div id="action-care-content" class="card-body markdown-body"></div>
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
                        <div id="action-contractor-content" class="card-body markdown-body"></div>
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
        const btnBackHomes = document.querySelectorAll('.btn-back-home');

        let selectedFile = null;

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

            // Start step animations
            startStepAnimation();

            // Run analysis immediately
            uploadAndAnalyze(selectedFile);
        }

        // Clear preview / reset to home
        function clearPreview() {
            selectedFile = null;
            cameraInput.value = '';
            libraryInput.value = '';
            document.getElementById('result-large-preview').src = '';
            errorDiv.style.display = 'none';
        }

        // Simulated Step animations
        let step1, step2;
        function startStepAnimation() {
            const steps = [
                document.getElementById('step-c1'),
                document.getElementById('step-c2'),
                document.getElementById('step-c3')
            ];
            steps.forEach((step, idx) => {
                step.className = 'step-compact';
                if (idx === 0) step.classList.add('active');
            });

            clearStepAnimation();

            step1 = setTimeout(() => {
                steps[0].classList.add('completed');
                steps[0].classList.remove('active');
                steps[1].classList.add('active');
            }, 1200);

            step2 = setTimeout(() => {
                steps[1].classList.add('completed');
                steps[1].classList.remove('active');
                steps[2].classList.add('active');
            }, 2600);
        }

        function clearStepAnimation() {
            clearTimeout(step1);
            clearTimeout(step2);
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
                renderResults(data);

            } catch (err) {
                console.error(err);
                clearStepAnimation();
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

        function renderResults(payload) {
            // Set risk badge
            const riskBadge = document.getElementById('risk-badge');
            const overallRisk = payload.overall_risk_level || 'medium';
            riskBadge.textContent = getRiskLabel(overallRisk);
            riskBadge.className = 'badge badge-' + overallRisk;

            // Set findings count
            const count = payload.findings ? payload.findings.length : 0;
            document.getElementById('risk-count').textContent = count + '件';

            // Check if home environment
            const notAppContainer = document.getElementById('not-applicable-container');
            const notAppMsg = document.getElementById('not-applicable-message');
            const imagesList = document.querySelector('.result-images-list');

            if (payload.is_home_environment === false) {
                notAppMsg.textContent = payload.not_applicable_reason_ja || "住宅内の安全確認対象ではない可能性があります。";
                notAppContainer.style.display = 'block';
                imagesList.style.display = 'none';
            } else {
                notAppContainer.style.display = 'none';
                imagesList.style.display = 'flex';
                
                // Set Images
                document.getElementById('result-annotated-img').src = 'data:image/png;base64,' + payload.annotated_image_base64;
                document.getElementById('result-improvement-img').src = 'data:image/png;base64,' + payload.improvement_image_base64;
            }

            // Render Markdown using marked.js
            document.getElementById('action-family-content').innerHTML = marked.parse(payload.family_actions_markdown || '');
            document.getElementById('action-care-content').innerHTML = marked.parse(payload.care_manager_actions_markdown || '');
            document.getElementById('action-contractor-content').innerHTML = marked.parse(payload.contractor_actions_markdown || '');
            document.getElementById('risk-details-content').innerHTML = marked.parse(payload.risk_summary_markdown || '');

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

            clearStepAnimation();
            
            // Switch title and transition to completed layout inside Screen 2
            document.getElementById('screen2-title').textContent = "安全チェック結果";
            document.getElementById('result-analyzing-container').style.display = 'none';
            document.getElementById('result-completed-container').style.display = 'block';
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

        // Reset flow
        function resetApp() {
            clearPreview();
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


@app.get("/", response_class=HTMLResponse)
def get_home():
    return HTMLResponse(content=INDEX_HTML)


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
        response = requests.post(f"{SUMAI_AGENT_URL}/analyze", data=data, files=files, timeout=60)

        if response.status_code == 200:
            return JSONResponse(content=response.json())

        # Strict mode: never fallback on error
        if FRONTEND_REQUIRE_REAL_GEMINI or response.status_code == 503:
            try:
                err_data = response.json()
            except Exception:
                err_data = {"error": "gemini_unavailable", "message": f"Backend returned status {response.status_code}"}
            return JSONResponse(status_code=503, content=err_data)

        logger.warning(f"Backend returned non-200: {response.status_code}, using fallback mock.")
        payload = _build_local_mock(image_bytes, room_hint, f"Backend HTTP {response.status_code}")
        return JSONResponse(content=payload)

    except Exception as exc:
        if FRONTEND_REQUIRE_REAL_GEMINI:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "gemini_unavailable",
                    "message": f"Real Gemini analysis is required but backend is unreachable: {exc}"
                }
            )
        logger.warning(f"Backend call failed: {exc}, using fallback mock.")
        payload = _build_local_mock(image_bytes, room_hint, str(exc))
        return JSONResponse(content=payload)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _build_local_mock(image_bytes: bytes, room_hint: str, reason: str) -> dict[str, Any]:
    """Generates the local mock payload internally using PIL if the backend is unreachable."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        # Generate raw placeholder if corrupt
        image = Image.new("RGB", (800, 600), (15, 16, 32))

    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    width, height = annotated.size
    box = (int(width * 0.16), int(height * 0.55), int(width * 0.72), int(height * 0.82))
    draw.rectangle(box, outline=(220, 38, 38), width=max(5, width // 120))
    draw.rectangle((box[0], max(0, box[1] - 34), box[0] + 58, box[1]), fill=(220, 38, 38))
    draw.text((box[0] + 8, max(0, box[1] - 28)), "注意", fill=(255, 255, 255), font=_font(24))

    improvement = _local_improvement_image(image, annotated)
    room_label = ROOM_LABELS.get(room_hint, "おまかせ")
    return {
        "analysis_id": "local_fallback",
        "room_type": room_hint,
        "overall_risk_level": "medium",
        "mode": "local_mock",
        "findings": [{"id": "注意"}],
        "annotated_image_base64": _to_base64_png(annotated),
        "improvement_image_base64": _to_base64_png(improvement),
        "risk_summary_markdown": (
            "## リスク概要\n"
            f"- 部屋: {room_label}\n"
            "- 総合リスク: 中\n\n"
            "### 注意箇所: 動線上の注意箇所\n"
            "- 危険な理由: 写真上の床・通路まわりに、つまずきや滑りにつながる可能性があります。\n"
            "- 参考根拠: 高齢者住宅安全チェックの一般原則\n"
            "- 信頼度: ローカルフォールバック\n"
            f"- 備考: バックエンド未接続のためローカルフォールバック表示しています。`{reason[:120]}`"
        ),
        "family_actions_markdown": (
            "## 家族で今日できること\n\n"
            "### 通る場所だけ先に空ける\n"
            "- 内容: 床・段差・通路にある物を移動し、足を置く場所を広くします。\n"
            "- 理由: 追加費用なしで、つまずきや回避動作を減らすためです。"
        ),
        "care_manager_actions_markdown": (
            "## ケアマネ・福祉用具に相談\n\n"
            "### 福祉用具の候補を相談\n"
            "- 内容: 滑り止め、置き型手すり、補助用品などが必要か相談します。\n"
            "- 理由: 写真だけでは本人の動作や寸法に合うか判断できないためです。"
        ),
        "contractor_actions_markdown": (
            "## 専門施工・現地確認\n\n"
            "### 現地確認の要否を判断\n"
            "- 内容: 固定手すりや床材変更が必要そうな場合だけ、専門職が現地で確認します。\n"
            "- 理由: 施工可否、下地、寸法は写真だけでは判断しないためです。"
        ),
        "disclaimer_ja": DISCLAIMER,
    }


def _local_improvement_image(image: Image.Image, annotated: Image.Image) -> Image.Image:
    canvas = image.convert("RGB").copy()
    width, height = canvas.size
    footer_h = max(36, height // 16)
    output = Image.new("RGB", (width, height + footer_h), (248, 250, 252))
    output.paste(canvas, (0, 0))

    draw = ImageDraw.Draw(output, "RGBA")
    label_font = _font(max(16, width // 42))
    small_font = _font(max(12, width // 54))

    safe_zone = (int(width * 0.16), int(height * 0.58), int(width * 0.72), int(height * 0.82))
    draw.rounded_rectangle(safe_zone, radius=10, fill=(22, 163, 74, 48), outline=(22, 163, 74, 230), width=4)
    draw.rounded_rectangle((36, 36, 206, 82), radius=8, fill=(255, 255, 255, 235))
    draw.text((50, 48), "動線確保", fill=(17, 24, 39), font=label_font)

    footer_y = height
    draw.rectangle((0, footer_y, width, footer_y + footer_h), fill=(255, 255, 255, 235))
    draw.text((16, footer_y + 8), WATERMARK, fill=(71, 85, 105), font=small_font)
    return output


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _to_base64_png(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


ROOM_LABELS = {
    "auto": "おまかせ",
    "genkan": "玄関",
    "hallway": "廊下",
    "bathroom": "浴室",
    "toilet": "トイレ",
    "bedroom": "寝室",
    "kitchen": "キッチン",
}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=SUMAI_WEB_PORT, reload=True)
