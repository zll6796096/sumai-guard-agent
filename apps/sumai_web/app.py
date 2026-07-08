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


def _check_backend_health() -> dict[str, Any] | None:
    """Non-blocking backend health check."""
    try:
        response = requests.get(f"{SUMAI_AGENT_URL}/healthz", timeout=3)
        if response.status_code == 200:
            return response.json()
    except Exception as exc:
        logger.warning(f"Backend health check failed: {exc}")
    return None


_backend_health = _check_backend_health()


# HTML Template with mobile-first CSS and vanilla JS
INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>親の家 安全チェックAI</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-gradient: linear-gradient(180deg, #0F1020 0%, #14172A 100%);
            --card-bg: #1B2033;
            --text-color: #F7F8FA;
            --text-muted: #A8AFBF;
            --primary-color: #6C5CE7;
            --secondary-color: #4C7DFF;
            --border-color: rgba(255,255,255,0.12);
            --danger-color: #EF4444;
            --success-color: #10B981;
            --warning-color: #F59E0B;
            --accent-green: #10B981;
            --accent-blue: #3B82F6;
            --accent-red: #EF4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background-color: #0F1020;
            font-family: 'Noto Sans JP', sans-serif;
            color: var(--text-color);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        #app-container {
            width: 100%;
            max-width: 480px;
            height: 100vh;
            max-height: 844px;
            background: var(--bg-gradient);
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            position: relative;
            overflow: hidden;
            border-radius: 0;
        }

        @media (min-width: 481px) {
            #app-container {
                border-radius: 20px;
                border: 1px solid var(--border-color);
            }
        }

        .screen {
            width: 100%;
            height: 100%;
            display: none;
            flex-direction: column;
            padding: 24px;
            position: absolute;
            top: 0;
            left: 0;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
        }

        .screen.active {
            display: flex;
        }

        /* Screen 1: Home */
        #screen-home {
            overflow-y: hidden;
            justify-content: space-between;
        }

        .home-header {
            text-align: center;
            margin-top: 40px;
        }

        .home-icon {
            width: 64px;
            height: 64px;
            background-color: rgba(108, 92, 231, 0.15);
            color: var(--primary-color);
            border-radius: 18px;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0 auto 16px auto;
            border: 1px solid rgba(108, 92, 231, 0.3);
        }

        .home-icon svg {
            width: 32px;
            height: 32px;
        }

        .home-title {
            font-size: 1.8rem;
            font-weight: 900;
            letter-spacing: -0.5px;
            margin-bottom: 8px;
        }

        .home-subtitle {
            font-size: 0.95rem;
            color: var(--text-muted);
        }

        .home-controls {
            margin: 24px 0;
        }

        .control-group {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .control-label {
            font-size: 0.9rem;
            font-weight: 700;
            color: var(--text-muted);
        }

        .room-dropdown {
            background: transparent;
            border: none;
            color: var(--text-color);
            font-size: 0.95rem;
            font-weight: 700;
            outline: none;
            text-align: right;
            cursor: pointer;
            width: 150px;
            direction: rtl;
        }

        .room-dropdown option {
            background-color: #14172A;
            color: var(--text-color);
            direction: ltr;
        }

        .guidance-text {
            font-size: 0.85rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.5;
            background-color: rgba(255,255,255,0.03);
            border-radius: 8px;
            padding: 10px;
            border: 1px dashed rgba(255,255,255,0.06);
        }

        .error-message {
            background-color: rgba(239, 68, 68, 0.15);
            border: 1px solid var(--danger-color);
            color: #FFA4A4;
            border-radius: 8px;
            padding: 10px;
            font-size: 0.85rem;
            text-align: center;
            margin-top: 12px;
            font-weight: bold;
        }

        .home-footer {
            margin-bottom: 24px;
        }

        .btn {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 54px;
            border-radius: 14px;
            font-size: 1.05rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            box-sizing: border-box;
            margin-bottom: 12px;
            text-decoration: none;
        }

        .btn:active {
            transform: scale(0.98);
        }

        .btn-primary {
            background-color: var(--primary-color);
            color: white;
            box-shadow: 0 4px 12px rgba(108, 92, 231, 0.3);
        }

        .btn-primary:active {
            background-color: #5b4bc4;
        }

        .btn-secondary {
            background-color: var(--secondary-color);
            color: white;
            box-shadow: 0 4px 12px rgba(76, 125, 255, 0.25);
        }

        .btn-secondary:active {
            background-color: #3b6adc;
        }

        .btn-outline {
            background-color: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-color);
        }

        .btn-outline:active {
            background-color: rgba(255, 255, 255, 0.05);
        }

        .btn-icon {
            width: 20px;
            height: 20px;
            margin-right: 8px;
        }

        .disclaimer-text {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.4;
        }

        /* Screen: Analyzing */
        #screen-analyzing {
            justify-content: center;
            align-items: center;
            background: var(--bg-gradient);
        }

        .analyzing-content {
            text-align: center;
            width: 100%;
        }

        .analyzing-title {
            font-size: 1.5rem;
            font-weight: 900;
            color: var(--primary-color);
            margin-bottom: 8px;
        }

        .analyzing-subtitle {
            font-size: 0.95rem;
            color: var(--text-muted);
            margin-bottom: 24px;
        }

        .preview-container {
            width: 200px;
            height: 150px;
            border-radius: 12px;
            overflow: hidden;
            margin: 0 auto 32px auto;
            border: 1px solid var(--border-color);
            background-color: var(--card-bg);
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .preview-container img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }

        .steps-container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 24px auto 0 auto;
            position: relative;
            max-width: 320px;
            padding: 0 10px;
        }

        .steps-container::before {
            content: '';
            position: absolute;
            top: 8px;
            left: 20px;
            right: 20px;
            height: 2px;
            background-color: var(--border-color);
            z-index: 1;
        }

        .step-item {
            position: relative;
            z-index: 2;
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
        }

        .step-dot {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background-color: #14172A;
            border: 2px solid var(--border-color);
            margin-bottom: 8px;
            transition: all 0.3s ease;
        }

        .step-item.active .step-dot {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
            box-shadow: 0 0 10px var(--primary-color);
        }

        .step-item.completed .step-dot {
            background-color: var(--success-color);
            border-color: var(--success-color);
        }

        .step-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-weight: 500;
        }

        .step-item.active .step-label {
            color: var(--text-color);
            font-weight: 700;
        }

        /* Screen: Result & Suggestions */
        .screen-nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-shrink: 0;
        }

        .nav-back {
            background: transparent;
            border: none;
            color: var(--secondary-color);
            font-size: 0.95rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            cursor: pointer;
            outline: none;
        }

        .nav-back svg {
            width: 20px;
            height: 20px;
            margin-right: 4px;
        }

        .nav-title {
            font-size: 1.1rem;
            font-weight: 900;
        }

        .result-summary {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 16px;
            display: flex;
            justify-content: space-around;
            margin-bottom: 20px;
            flex-shrink: 0;
        }

        .summary-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .summary-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .summary-value {
            font-size: 1.15rem;
            font-weight: 900;
        }

        .badge {
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: 900;
            font-size: 0.85rem;
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
            gap: 20px;
            margin-bottom: 24px;
        }

        .result-image-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            padding: 16px;
        }

        .image-card-title {
            font-size: 0.9rem;
            font-weight: 700;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: block;
        }

        .image-wrapper {
            width: 100%;
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.06);
            background-color: #0F1020;
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
            padding-top: 16px;
            flex-shrink: 0;
        }

        /* Screen 3: Action Suggestions */
        .section-title {
            font-size: 1.3rem;
            font-weight: 900;
            margin-bottom: 16px;
        }

        .action-cards-container {
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-bottom: 20px;
        }

        .action-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .family-card {
            border-left: 5px solid var(--accent-green);
        }

        .care-card {
            border-left: 5px solid var(--accent-blue);
        }

        .contractor-card {
            border-left: 5px solid var(--accent-red);
        }

        .card-header {
            display: flex;
            align-items: center;
            margin-bottom: 12px;
        }

        .card-badge {
            font-size: 0.7rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 6px;
            margin-right: 8px;
        }

        .family-card .card-badge {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
        }

        .care-card .card-badge {
            background-color: rgba(59, 130, 246, 0.15);
            color: var(--accent-blue);
        }

        .contractor-card .card-badge {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--accent-red);
        }

        .card-title {
            font-size: 1.05rem;
            font-weight: 900;
        }

        .card-body {
            font-size: 0.9rem;
            line-height: 1.6;
            color: var(--text-color);
        }

        /* Markdown rendering styles */
        .markdown-body h2, .markdown-body h3 {
            font-size: 0.95rem;
            margin-top: 12px;
            margin-bottom: 6px;
            font-weight: bold;
            color: var(--text-color);
        }
        
        .markdown-body p {
            margin-bottom: 8px;
        }

        .markdown-body ul, .markdown-body ol {
            padding-left: 18px;
            margin-bottom: 10px;
        }

        .markdown-body li {
            margin-bottom: 4px;
        }

        /* Accordion Details */
        .details-accordion {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            overflow: hidden;
            margin-bottom: 20px;
        }

        .accordion-header {
            padding: 16px;
            font-size: 0.95rem;
            font-weight: 700;
            cursor: pointer;
            outline: none;
            user-select: none;
            color: var(--secondary-color);
        }

        .accordion-content {
            padding: 16px;
            border-top: 1px solid var(--border-color);
            font-size: 0.85rem;
            line-height: 1.6;
            color: var(--text-muted);
            background-color: rgba(0, 0, 0, 0.15);
        }
    </style>
</head>
<body>
    <div id="app-container">
        <!-- Hidden Inputs for Files -->
        <input type="file" id="camera-input" accept="image/*" capture="environment" style="display: none;">
        <input type="file" id="library-input" accept="image/*" style="display: none;">

        <!-- SCREEN 1: Home / Photo Input -->
        <div id="screen-home" class="screen active">
            <div class="home-header">
                <div class="home-icon">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M19 13.586V20a1 1 0 0 1-1 1h-4v-6h-4v6H6a1 1 0 0 1-1-1v-6.414l7-7 7 7zM12 2.69l-9 9V13h2v7a2 2 0 0 0 2 2h6v-6h2v6h6a2 2 0 0 0 2-2v-7h2v-1.31l-9-9z"/>
                    </svg>
                </div>
                <h1 class="home-title">親の家 安全チェックAI</h1>
                <p class="home-subtitle">写真1枚で、転倒リスクを見える化</p>
            </div>

            <div class="home-controls">
                <div class="control-group">
                    <span class="control-label">診断する部屋</span>
                    <select id="room-select" class="room-dropdown">
                        <option value="auto" selected>おまかせ</option>
                        <option value="genkan">玄関</option>
                        <option value="hallway">廊下</option>
                        <option value="bathroom">浴室</option>
                        <option value="toilet">トイレ</option>
                        <option value="bedroom">寝室</option>
                        <option value="kitchen">キッチン</option>
                    </select>
                </div>
                <p id="guidance-text" class="guidance-text">床・段差・手すり・通路が見えるように撮影してください。</p>
                <div id="error-message" class="error-message" style="display: none;"></div>
            </div>

            <div class="home-footer">
                <button id="btn-camera" class="btn btn-primary">
                    <svg class="btn-icon" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M4 4h3l2-2h6l2 2h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm8 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/>
                    </svg>
                    カメラで撮影
                </button>
                <button id="btn-library" class="btn btn-secondary">
                    <svg class="btn-icon" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-9 14l-4-4 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                    </svg>
                    ライブラリから選択
                </button>
                <p class="disclaimer-text">POC版です。専門判断を代替しません。</p>
            </div>
        </div>

        <!-- SCREEN 1.5: Analyzing -->
        <div id="screen-analyzing" class="screen">
            <div class="analyzing-content">
                <h2 class="analyzing-title">AI分析中...</h2>
                <p class="analyzing-subtitle">AIが写真を確認しています</p>
                
                <div class="preview-container">
                    <img id="analyzing-preview" src="" alt="Preview">
                </div>
                
                <div class="steps-container">
                    <div class="step-item active">
                        <span class="step-dot"></span>
                        <span class="step-label">写真を確認</span>
                    </div>
                    <div class="step-item">
                        <span class="step-dot"></span>
                        <span class="step-label">リスク抽出</span>
                    </div>
                    <div class="step-item">
                        <span class="step-dot"></span>
                        <span class="step-label">結果作成</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- SCREEN 2: Visual Diagnosis Result -->
        <div id="screen-result" class="screen">
            <div class="screen-nav">
                <button class="nav-back btn-back-home">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.828 12l4.95 4.95-1.414 1.414-6.364-6.364 6.364-6.364 1.414 1.414z"/>
                    </svg>
                    ホーム
                </button>
                <span class="nav-title">診断結果</span>
                <div style="width: 60px;"></div>
            </div>

            <div class="result-summary">
                <div class="summary-item">
                    <span class="summary-label">総合リスク</span>
                    <span id="risk-badge" class="badge">--</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">赤枠リスク</span>
                    <span id="risk-count" class="summary-value">--件</span>
                </div>
            </div>

            <div class="result-images-list">
                <div class="result-image-card">
                    <span class="image-card-title">現状写真（赤枠）</span>
                    <div class="image-wrapper">
                        <img id="result-annotated-img" src="" alt="現状写真">
                    </div>
                </div>
                <div class="result-image-card">
                    <span class="image-card-title">改善イメージ</span>
                    <div class="image-wrapper">
                        <img id="result-improvement-img" src="" alt="改善イメージ">
                    </div>
                </div>
            </div>

            <div class="result-actions">
                <button id="btn-show-suggestions" class="btn btn-primary">次にできることを見る</button>
                <button class="btn btn-outline btn-back-home">ホームに戻る</button>
            </div>
        </div>

        <!-- SCREEN 3: Action Suggestions -->
        <div id="screen-suggestions" class="screen">
            <div class="screen-nav">
                <button id="btn-back-to-result" class="nav-back">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.828 12l4.95 4.95-1.414 1.414-6.364-6.364 6.364-6.364 1.414 1.414z"/>
                    </svg>
                    戻る
                </button>
                <span class="nav-title">対策の提案</span>
                <div style="width: 60px;"></div>
            </div>

            <h2 class="section-title">次にできること</h2>

            <div class="action-cards-container">
                <div class="action-card family-card">
                    <div class="card-header">
                        <span class="card-badge">今日できる</span>
                        <h3 class="card-title">家族で今日できること</h3>
                    </div>
                    <div id="action-family-content" class="card-body markdown-body"></div>
                </div>

                <div class="action-card care-card">
                    <div class="card-header">
                        <span class="card-badge">相談・レンタル</span>
                        <h3 class="card-title">ケアマネ・福祉用具に相談</h3>
                    </div>
                    <div id="action-care-content" class="card-body markdown-body"></div>
                </div>

                <div class="action-card contractor-card">
                    <div class="card-header">
                        <span class="card-badge">専門工事</span>
                        <h3 class="card-title">専門施工・現地確認</h3>
                    </div>
                    <div id="action-contractor-content" class="card-body markdown-body"></div>
                </div>
            </div>

            <details class="details-accordion">
                <summary class="accordion-header">詳しいリスク根拠を見る</summary>
                <div id="risk-details-content" class="accordion-content markdown-body"></div>
            </details>

            <p class="disclaimer-text" style="color: var(--text-muted); text-align: left; margin: 24px 0 16px 0;">
                ※POC版です。医療・介護・施工判断を代替しません。<br>
                ※改善イメージはコミュニケーション用であり施工図ではありません。
            </p>

            <div class="suggestions-actions">
                <button class="btn btn-outline btn-back-home">ホームに戻る</button>
            </div>
        </div>
    </div>

    <script>
        const GUIDANCE = {
            genkan: "玄関: 床、上がり框、靴の置き場、手すりの有無が入るように撮影してください。",
            hallway: "廊下: 床面、壁沿い、コード、敷物、段差が見えるように撮影してください。",
            bathroom: "浴室: 入口、床、浴槽のまたぎ部分、手すりの有無が入るように撮影してください。",
            toilet: "トイレ: 便器の周辺、立ち座りスペース、手すりの有無が分かるように撮影してください。",
            bedroom: "寝室: ベッド横、床、夜間トイレまでの動線が見えるように撮影してください。",
            kitchen: "キッチン: 床、マット、よく歩く動線、コンロ周辺が見えるように撮影してください。",
            auto: "床・段差・手すり・通路が見えるように撮影してください。"
        };

        const cameraInput = document.getElementById('camera-input');
        const libraryInput = document.getElementById('library-input');
        const btnCamera = document.getElementById('btn-camera');
        const btnLibrary = document.getElementById('btn-library');
        const roomSelect = document.getElementById('room-select');
        const guidanceText = document.getElementById('guidance-text');
        const errorDiv = document.getElementById('error-message');
        const btnShowSuggestions = document.getElementById('btn-show-suggestions');
        const btnBackToResult = document.getElementById('btn-back-to-result');
        const btnBackHomes = document.querySelectorAll('.btn-back-home');

        // Nav functions
        function showScreen(screenId) {
            const screens = document.querySelectorAll('.screen');
            screens.forEach(screen => {
                screen.classList.remove('active');
            });
            document.getElementById(screenId).classList.add('active');
        }

        // Room Select guidance changer
        function updateGuidance() {
            const val = roomSelect.value;
            guidanceText.textContent = GUIDANCE[val] || GUIDANCE.auto;
        }

        roomSelect.addEventListener('change', updateGuidance);

        // Bind camera/library triggers
        btnCamera.addEventListener('click', () => {
            errorDiv.style.display = 'none';
            cameraInput.click();
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

            errorDiv.style.display = 'none';

            // Show preview image instantly
            const reader = new FileReader();
            reader.onload = function(e) {
                document.getElementById('analyzing-preview').src = e.target.result;
            };
            reader.readAsDataURL(file);

            // Go to Screen 1.5 (Analyzing state)
            showScreen('screen-analyzing');
            startStepAnimation();

            // Run backend fetch
            uploadAndAnalyze(file);
        }

        // Simulated Step animations
        let step1, step2;
        function startStepAnimation() {
            const steps = document.querySelectorAll('.step-item');
            steps.forEach((step, idx) => {
                step.className = 'step-item';
                if (idx === 0) step.classList.add('active');
            });

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
            formData.append('room_hint', roomSelect.value);

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

        function renderResults(payload) {
            // Set risk badge
            const riskBadge = document.getElementById('risk-badge');
            const overallRisk = payload.overall_risk_level || 'medium';
            riskBadge.textContent = getRiskLabel(overallRisk);
            riskBadge.className = 'badge badge-' + overallRisk;

            // Set findings count
            const count = payload.findings ? payload.findings.length : 0;
            document.getElementById('risk-count').textContent = count + '件';

            // Set Images
            document.getElementById('result-annotated-img').src = 'data:image/png;base64,' + payload.annotated_image_base64;
            document.getElementById('result-improvement-img').src = 'data:image/png;base64,' + payload.improvement_image_base64;

            // Render Markdown using marked.js
            document.getElementById('action-family-content').innerHTML = marked.parse(payload.family_actions_markdown || '');
            document.getElementById('action-care-content').innerHTML = marked.parse(payload.care_manager_actions_markdown || '');
            document.getElementById('action-contractor-content').innerHTML = marked.parse(payload.contractor_actions_markdown || '');
            document.getElementById('risk-details-content').innerHTML = marked.parse(payload.risk_summary_markdown || '');

            clearStepAnimation();
            showScreen('screen-result');
        }

        function getRiskLabel(risk) {
            if (risk === 'low') return '低';
            if (risk === 'medium') return '中';
            if (risk === 'high') return '高';
            return '中';
        }

        // Navigate between result and action cards
        btnShowSuggestions.addEventListener('click', () => {
            showScreen('screen-suggestions');
        });

        btnBackToResult.addEventListener('click', () => {
            showScreen('screen-result');
        });

        // Reset flow
        function resetApp() {
            cameraInput.value = '';
            libraryInput.value = '';
            roomSelect.value = 'auto';
            updateGuidance();
            errorDiv.style.display = 'none';
            showScreen('screen-home');
        }

        btnBackHomes.forEach(btn => {
            btn.addEventListener('click', resetApp);
        });
    </script>
</body>
</html>
"""


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

        logger.warning(f"Backend returned non-200: {response.status_code}, using fallback mock.")
        payload = _build_local_mock(image_bytes, room_hint, f"Backend HTTP {response.status_code}")
        return JSONResponse(content=payload)

    except Exception as exc:
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
    draw.text((box[0] + 8, max(0, box[1] - 28)), "R1", fill=(255, 255, 255), font=_font(24))

    improvement = _local_improvement_image(image, annotated)
    room_label = ROOM_LABELS.get(room_hint, "おまかせ")
    return {
        "analysis_id": "local_fallback",
        "room_type": room_hint,
        "overall_risk_level": "medium",
        "mode": "local_mock",
        "findings": [{"id": "R1"}],
        "annotated_image_base64": _to_base64_png(annotated),
        "improvement_image_base64": _to_base64_png(improvement),
        "risk_summary_markdown": (
            "## リスク概要\n"
            f"- 部屋: {room_label}\n"
            "- 総合リスク: 中\n\n"
            "### R1: 動線上の注意箇所\n"
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
    width, height = image.size
    header_h = max(56, height // 10)
    footer_h = max(42, height // 14)
    output = Image.new("RGB", (width * 2, height + header_h + footer_h), (248, 250, 252))
    output.paste(annotated, (0, header_h))
    output.paste(image, (width, header_h))
    draw = ImageDraw.Draw(output, "RGBA")
    title_font = _font(max(22, width // 30))
    draw.rectangle((0, 0, width * 2, header_h), fill=(255, 255, 255, 255))
    draw.text((24, 16), "現状", fill=(17, 24, 39), font=title_font)
    draw.text((width + 24, 16), "改善イメージ", fill=(17, 24, 39), font=title_font)
    safe_zone = (width + int(width * 0.14), header_h + int(height * 0.58), width + int(width * 0.82), header_h + int(height * 0.82))
    draw.rounded_rectangle(safe_zone, radius=10, fill=(22, 163, 74, 48), outline=(22, 163, 74, 230), width=4)
    draw.rounded_rectangle((width + 36, header_h + 36, width + 206, header_h + 82), radius=8, fill=(255, 255, 255, 235))
    draw.text((width + 50, header_h + 48), "動線確保", fill=(17, 24, 39), font=_font(max(17, width // 42)))
    footer_y = header_h + height
    draw.rectangle((0, footer_y, width * 2, footer_y + footer_h), fill=(255, 255, 255, 235))
    draw.text((24, footer_y + 10), "コミュニケーション用イメージ｜施工図ではありません", fill=(71, 85, 105), font=_font(max(14, width // 54)))
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
