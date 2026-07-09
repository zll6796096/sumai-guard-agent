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
            padding: 20px;
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
            margin-top: 20px;
            margin-bottom: 12px;
        }

        .app-tag {
            display: inline-block;
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--primary-color);
            background-color: rgba(108, 92, 231, 0.12);
            padding: 4px 10px;
            border-radius: 6px;
            margin-bottom: 12px;
            letter-spacing: 0.5px;
        }

        .home-intro {
            font-size: 1.05rem;
            line-height: 1.6;
            color: var(--text-color);
            text-align: left;
            margin-bottom: 16px;
        }

        /* 3-Step Instruction Flow */
        .home-steps {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 10px;
            padding: 10px 14px;
            margin: 16px 0;
        }

        .home-step-item {
            font-size: 0.72rem;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .home-step-num {
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background-color: var(--primary-color);
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            font-size: 0.65rem;
            font-weight: 700;
        }

        .home-step-arrow {
            color: rgba(255, 255, 255, 0.2);
            font-size: 0.8rem;
        }

        .home-controls {
            margin: 8px 0;
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
            background-color: #14172A;
            color: var(--text-color);
            direction: ltr;
        }

        .guidance-text {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.4;
            background-color: rgba(255,255,255,0.02);
            border-radius: 8px;
            padding: 8px;
            border: 1px dashed rgba(255,255,255,0.05);
        }

        .error-message {
            background-color: rgba(239, 68, 68, 0.12);
            border: 1px solid var(--danger-color);
            color: #FFA4A4;
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 0.75rem;
            text-align: center;
            margin-top: 10px;
            font-weight: bold;
        }

        .home-footer {
            margin-bottom: 16px;
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
            height: 48px;
            border-radius: 12px;
            font-size: 0.95rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
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
            box-shadow: 0 4px 12px rgba(108, 92, 231, 0.25);
        }

        .btn-primary:active {
            background-color: #5b4bc4;
        }

        .btn-secondary {
            background-color: var(--secondary-color);
            color: white;
            box-shadow: 0 4px 12px rgba(76, 125, 255, 0.2);
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
            width: 18px;
            height: 18px;
            margin-right: 8px;
        }

        .disclaimer-text {
            font-size: 0.7rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.3;
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
            font-size: 1.4rem;
            font-weight: 900;
            color: var(--primary-color);
            margin-bottom: 6px;
        }

        .analyzing-subtitle {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 20px;
        }

        .preview-container {
            width: 160px;
            height: 120px;
            border-radius: 10px;
            overflow: hidden;
            margin: 0 auto 24px auto;
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
            margin: 20px auto 0 auto;
            position: relative;
            max-width: 280px;
            padding: 0 8px;
        }

        .steps-container::before {
            content: '';
            position: absolute;
            top: 7px;
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
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background-color: #14172A;
            border: 2px solid var(--border-color);
            margin-bottom: 6px;
            transition: all 0.3s ease;
        }

        .step-item.active .step-dot {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
            box-shadow: 0 0 8px var(--primary-color);
        }

        .step-item.completed .step-dot {
            background-color: var(--success-color);
            border-color: var(--success-color);
        }

        .step-label {
            font-size: 0.7rem;
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
            margin-bottom: 16px;
            flex-shrink: 0;
        }

        .nav-back {
            background: transparent;
            border: none;
            color: var(--secondary-color);
            font-size: 0.9rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            cursor: pointer;
            outline: none;
        }

        .nav-back svg {
            width: 18px;
            height: 18px;
            margin-right: 4px;
        }

        .nav-title {
            font-size: 1rem;
            font-weight: 900;
        }

        .result-summary {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px;
            display: flex;
            justify-content: space-around;
            margin-bottom: 16px;
            flex-shrink: 0;
        }

        .summary-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .summary-label {
            font-size: 0.7rem;
            color: var(--text-muted);
            margin-bottom: 4px;
        }

        .summary-value {
            font-size: 1.05rem;
            font-weight: 900;
        }

        .badge {
            padding: 2px 10px;
            border-radius: 10px;
            font-weight: 900;
            font-size: 0.8rem;
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
            border-radius: 14px;
            overflow: hidden;
            padding: 12px;
        }

        .image-card-title {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-muted);
            margin-bottom: 8px;
            display: block;
        }

        .image-wrapper {
            width: 100%;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.05);
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
            padding-top: 12px;
            flex-shrink: 0;
        }

        /* Screen 3: Action Suggestions */
        .section-title {
            font-size: 1.2rem;
            font-weight: 900;
            margin-bottom: 4px;
        }

        .section-subtitle {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 16px;
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
            border-radius: 12px;
            overflow: hidden;
            transition: all 0.3s ease;
        }

        .accordion-card-header {
            padding: 12px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
        }

        .accordion-card-title-group {
            display: flex;
            flex-direction: column;
        }

        .accordion-card-title {
            font-size: 0.9rem;
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
            font-size: 0.65rem;
            font-weight: 700;
            padding: 1px 6px;
            border-radius: 4px;
        }

        .accordion-card-count {
            font-size: 0.7rem;
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
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.25s ease-out;
            padding: 0 16px;
        }

        .accordion-card.open .accordion-card-content {
            max-height: 1200px;
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
            font-size: 0.85rem;
            line-height: 1.5;
            color: var(--text-color);
        }

        /* Markdown styles */
        .markdown-body h2, .markdown-body h3 {
            font-size: 0.85rem;
            margin-top: 10px;
            margin-bottom: 4px;
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
            margin-bottom: 3px;
        }
    </style>
</head>
<body>
    <div id="app-container">
        <!-- Separate Hidden Inputs for Camera and Library -->
        <input type="file" id="camera-input" accept="image/*" capture="environment" style="display: none;">
        <input type="file" id="library-input" accept="image/*" style="display: none;">

        <!-- SCREEN 1: Home / Photo Input -->
        <div id="screen-home" class="screen active">
            <div class="home-header">
                <div class="app-tag">親の家 安全チェックAI</div>
                <p class="home-intro">
                    このツールは、あなたやご両親の住まいに潜む安全リスク（めくれたマット、浴室の滑りやすさ、コードの散乱など）を事前に見つけ、低コストで実践しやすい高齢者向けの改善案を提案します。
                </p>
            </div>

            <div class="home-controls">
                <p id="guidance-text" class="guidance-text" style="font-size: 0.85rem; text-align: left; background-color: rgba(255,255,255,0.02); border-radius: 10px; padding: 12px; border: 1px dashed rgba(255,255,255,0.06); line-height: 1.6; margin-bottom: 16px;">
                    まずは次のいずれかを1か所撮影してください。<br>
                    <strong>玄関・廊下・浴室・トイレ・寝室・キッチン</strong><br><br>
                    床、段差、手すり、通路が入るように撮影してください。
                </p>
                <div id="error-message" class="error-message" style="display: none;"></div>
            </div>

            <div class="home-footer">
                <!-- Select buttons state -->
                <div id="selection-buttons-container">
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
                </div>

                <!-- Selected preview and AI CTA state -->
                <div id="preview-cta-container" style="display: none;">
                    <div class="compact-preview-wrapper">
                        <img id="home-image-preview" src="" alt="Selected Preview">
                        <button id="btn-clear-preview" class="btn-clear-x">×</button>
                    </div>
                    <button id="btn-run-analysis" class="btn btn-primary">AIで安全チェック</button>
                    <button id="btn-change-photo" class="btn btn-outline" style="height: 40px; font-size: 0.85rem;">他の写真を選ぶ</button>
                </div>

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

            <!-- Not Applicable Warning Box -->
            <div id="not-applicable-container" style="display: none; background-color: rgba(245, 158, 11, 0.1); border: 1px solid var(--warning-color); border-radius: 12px; padding: 16px; margin-bottom: 20px; text-align: center;">
                <p id="not-applicable-message" style="color: #FFD580; font-weight: bold; font-size: 0.95rem;"></p>
            </div>

            <!-- Stacked Images: Annotated first, Improvement second -->
            <div class="result-images-list">
                <div class="result-image-card">
                    <span class="image-card-title">危険提示</span>
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

            <!-- Hidden Debug Panel -->
            <div class="debug-panel" style="display: none; background-color: rgba(255,255,255,0.05); border: 1px dashed rgba(255,255,255,0.15); border-radius: 8px; padding: 12px; font-size: 0.75rem; font-family: monospace; margin-top: 16px; text-align: left;">
                <div style="font-weight: bold; margin-bottom: 4px; color: var(--warning-color);">[DEBUG INFO]</div>
                <div>Mode: <span class="debug-mode">--</span></div>
                <div>Analysis ID: <span class="debug-analysis-id">--</span></div>
                <div>Model: <span class="debug-model">--</span></div>
                <div>Findings Count: <span class="debug-finding-count">--</span></div>
                <div>Is Home Environment: <span class="debug-is-home">--</span></div>
            </div>

            <div class="result-actions">
                <button id="btn-show-suggestions" class="btn btn-primary">点検・修繕提案を見る</button>
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
                <span class="nav-title">点検・修繕提案</span>
                <div style="width: 60px;"></div>
            </div>

            <h2 class="section-title">点検・修繕提案</h2>
            <p class="section-subtitle">できることから順に確認してください。</p>

            <!-- Collapsed Accordion Cards -->
            <div class="action-cards-container">
                <!-- Family Card -->
                <div class="accordion-card family-card">
                    <div class="accordion-card-header">
                        <div class="accordion-card-title-group">
                            <span class="accordion-card-title">家族で今日できること</span>
                            <div class="accordion-card-sub">
                                <span class="accordion-card-label">0円・すぐできる</span>
                                <span id="family-count" class="accordion-card-count"></span>
                            </div>
                        </div>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </div>
                    <div class="accordion-card-content">
                        <div id="action-family-content" class="card-body markdown-body"></div>
                    </div>
                </div>

                <!-- Care Manager Card -->
                <div class="accordion-card care-card">
                    <div class="accordion-card-header">
                        <div class="accordion-card-title-group">
                            <span class="accordion-card-title">ケアマネ・福祉用具に相談</span>
                            <div class="accordion-card-sub">
                                <span class="accordion-card-label">購入・レンタル</span>
                                <span id="care-count" class="accordion-card-count"></span>
                            </div>
                        </div>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </div>
                    <div class="accordion-card-content">
                        <div id="action-care-content" class="card-body markdown-body"></div>
                    </div>
                </div>

                <!-- Contractor Card -->
                <div class="accordion-card contractor-card">
                    <div class="accordion-card-header">
                        <div class="accordion-card-title-group">
                            <span class="accordion-card-title">専門施工・現地確認</span>
                            <div class="accordion-card-sub">
                                <span class="accordion-card-label">工事・専門確認</span>
                                <span id="contractor-count" class="accordion-card-count"></span>
                            </div>
                        </div>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </div>
                    <div class="accordion-card-content">
                        <div id="action-contractor-content" class="card-body markdown-body"></div>
                    </div>
                </div>

                <!-- Risk Basis Card -->
                <div class="accordion-card basis-card">
                    <div class="accordion-card-header">
                        <div class="accordion-card-title-group">
                            <span class="accordion-card-title">詳しいリスク根拠を見る</span>
                        </div>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </div>
                    <div class="accordion-card-content">
                        <div id="risk-details-content" class="markdown-body"></div>
                    </div>
                </div>
            </div>

            <p class="disclaimer-text" style="color: var(--text-muted); text-align: left; margin: 16px 0;">
                ※POC版です。医療・介護・施工判断を代替しません。<br>
                ※改善イメージはコミュニケーション用であり施工図ではありません。
            </p>

            <!-- Hidden Debug Panel -->
            <div class="debug-panel" style="display: none; background-color: rgba(255,255,255,0.05); border: 1px dashed rgba(255,255,255,0.15); border-radius: 8px; padding: 12px; font-size: 0.75rem; font-family: monospace; margin-top: 16px; text-align: left; margin-bottom: 16px;">
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
        const guidanceText = document.getElementById('guidance-text');
        const errorDiv = document.getElementById('error-message');
        
        const selectionContainer = document.getElementById('selection-buttons-container');
        const previewContainer = document.getElementById('preview-cta-container');
        const homePreviewImg = document.getElementById('home-image-preview');
        const btnRunAnalysis = document.getElementById('btn-run-analysis');
        const btnClearPreview = document.getElementById('btn-clear-preview');
        const btnChangePhoto = document.getElementById('btn-change-photo');
        
        const btnShowSuggestions = document.getElementById('btn-show-suggestions');
        const btnBackToResult = document.getElementById('btn-back-to-result');
        const btnBackHomes = document.querySelectorAll('.btn-back-home');

        let selectedFile = null;

        // Nav functions
        function showScreen(screenId) {
            const screens = document.querySelectorAll('.screen');
            screens.forEach(screen => {
                screen.classList.remove('active');
            });
            document.getElementById(screenId).classList.add('active');
        }

        // Bind camera/library triggers
        let selectedFile = null;
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

            // Show preview image in Screen 1
            const reader = new FileReader();
            reader.onload = function(e) {
                homePreviewImg.src = e.target.result;
                document.getElementById('analyzing-preview').src = e.target.result;
            };
            reader.readAsDataURL(file);

            // Hide select buttons, show preview with CTA
            selectionContainer.style.display = 'none';
            previewContainer.style.display = 'block';
        }

        // Clear preview
        function clearPreview() {
            selectedFile = null;
            cameraInput.value = '';
            libraryInput.value = '';
            homePreviewImg.src = '';
            previewContainer.style.display = 'none';
            selectionContainer.style.display = 'block';
            errorDiv.style.display = 'none';
        }

        btnClearPreview.addEventListener('click', clearPreview);
        btnChangePhoto.addEventListener('click', () => {
            clearPreview();
            libraryInput.click();
        });

        // Trigger AI analysis
        btnRunAnalysis.addEventListener('click', () => {
            if (!selectedFile) {
                errorDiv.textContent = "写真を選択してください。";
                errorDiv.style.display = "block";
                return;
            }
            showScreen('screen-analyzing');
            startStepAnimation();
            uploadAndAnalyze(selectedFile);
        });

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

            // Collapse all accordion cards by default
            document.querySelectorAll('.accordion-card').forEach(card => {
                card.classList.remove('open');
            });

            // Update Debug Panel
            updateDebugPanel(payload);

            clearStepAnimation();
            showScreen('screen-result');
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
                const card = header.parentElement;
                card.classList.toggle('open');
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
