from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

import gradio as gr
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sumai.web")

SUMAI_AGENT_URL = os.getenv("SUMAI_AGENT_URL", "http://localhost:8080").rstrip("/")
SUMAI_WEB_PORT = int(os.getenv("SUMAI_WEB_PORT", "8081"))
FRONTEND_MOCK = os.getenv("MOCK_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}

ROOM_OPTIONS = [
    ("おまかせ", "auto"),
    ("玄関", "genkan"),
    ("廊下", "hallway"),
    ("浴室", "bathroom"),
    ("トイレ", "toilet"),
    ("寝室", "bedroom"),
    ("キッチン", "kitchen"),
]

ROOM_LABELS = dict((value, label) for label, value in ROOM_OPTIONS)

GUIDANCE = {
    "genkan": "玄関: 床、上がり框、靴の置き場、手すりの有無が入るように撮影してください。",
    "hallway": "廊下: 床面、壁沿い、コード、敷物、段差が見えるように撮影してください。",
    "bathroom": "浴室: 入口、床、浴槽のまたぎ部分、手すりの有無が入るように撮影してください。",
    "toilet": "トイレ: 便器の周辺、立ち座りスペース、手すりの有無が分かるように撮影してください。",
    "bedroom": "寝室: ベッド横、床、夜間トイレまでの動線が見えるように撮影してください。",
    "kitchen": "キッチン: 床、マット、よく歩く動線、コンロ周辺が見えるように撮影してください。",
    "auto": "おまかせ: 床・段差・手すり・通路が見えるように撮影してください。",
}

DISCLAIMER = (
    "POC版です。医療・介護・施工判断を代替しません。\n"
    "改善イメージはコミュニケーション用であり施工図ではありません。\n"
    "写真から正確な寸法や適用制度を判断するものではありません。"
)


def _check_backend_health() -> dict[str, Any] | None:
    """Non-blocking backend health check."""
    try:
        response = requests.get(f"{SUMAI_AGENT_URL}/healthz", timeout=5)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Backend connected: {data}")
            return data
    except Exception as exc:
        logger.warning(f"Backend health check failed: {exc}")
    return None


# Check backend on startup
_backend_health = _check_backend_health()


def _get_mode_badge_html() -> str:
    """Return HTML for the mode badge with styling."""
    if _backend_health:
        is_mock = _backend_health.get("mock_mode", True)
        if is_mock:
            return '<span class="badge badge-mock">🟢 MOCK MODE</span>'
        else:
            return '<span class="badge badge-gemini">🔴 GEMINI MODE</span>'
    if FRONTEND_MOCK:
        return '<span class="badge badge-mock">🟢 MOCK MODE</span>'
    return '<span class="badge badge-unknown">🟡 BACKEND UNKNOWN</span>'


def shooting_guidance(room_hint: str) -> str:
    return GUIDANCE.get(room_hint, GUIDANCE["auto"])


def _call_backend(image: Image.Image, room_hint: str) -> dict[str, Any]:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    files = {"image": ("sumai-photo.png", buffer.getvalue(), "image/png")}
    data = {"room_hint": room_hint, "mock": "true" if FRONTEND_MOCK else "false"}
    response = requests.post(f"{SUMAI_AGENT_URL}/analyze", data=data, files=files, timeout=60)
    response.raise_for_status()
    payload = response.json()
    required = [
        "annotated_image_base64",
        "improvement_image_base64",
        "risk_summary_markdown",
        "family_actions_markdown",
        "care_manager_actions_markdown",
        "contractor_actions_markdown",
        "disclaimer_ja",
    ]
    if not all(key in payload for key in required):
        raise ValueError("backend response missing required fields")
    return payload


def _overall_markdown(payload: dict[str, Any]) -> str:
    risk_map = {"low": "低", "medium": "中", "high": "高"}
    room = ROOM_LABELS.get(str(payload.get("room_type", "auto")), "おまかせ")
    risk = risk_map.get(str(payload.get("overall_risk_level", "medium")), "中")
    count = len(payload.get("findings") or [])
    mode = payload.get("mode", "mock")
    mode_label = "MOCK" if mode == "mock" else "GEMINI"
    return f"## 総合リスク: {risk}\n- 部屋: {room}\n- 赤枠リスク: {count}件\n- 分析ID: `{payload.get('analysis_id', 'local_mock')}`\n- 分析モード: {mode_label}"


def _image_from_base64(encoded: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def _local_mock_payload(image: Image.Image, room_hint: str, reason: str) -> dict[str, Any]:
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
        "analysis_id": "local_mock",
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
            "- 信頼度: ローカルモック\n"
            f"- 備考: バックエンド未接続のためローカルモックで表示しています。`{reason[:120]}`"
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


def check_image(image: Image.Image | None) -> tuple[Any, ...]:
    """Validate image exists and transition to analyzing state."""
    if image is None:
        return (
            gr.update(visible=True),  # input_screen visible
            gr.update(visible=False), # analyzing_screen hidden
            gr.update(value="### ⚠️ 写真を追加してください。", visible=True),
            None,
            None
        )
    return (
        gr.update(visible=False), # input_screen hidden
        gr.update(visible=True),  # analyzing_screen visible
        gr.update(value="", visible=False),
        image,
        image
    )


def run_analysis_and_transition(image: Image.Image | None, room_hint: str) -> tuple[Any, ...]:
    """Perform backend call and transition to result screen."""
    if image is None:
        return (
            gr.update(visible=False), # analyzing_screen hidden
            gr.update(visible=True),  # input_screen visible
            gr.update(visible=False), # result_screen hidden
            "## 総合リスク\n画像を追加してください。",
            None,
            None,
            "",
            "",
            "",
            "",
            DISCLAIMER,
            "input",
            None
        )

    image_rgb = image.convert("RGB")
    fallback_warning = ""
    try:
        payload = _call_backend(image=image_rgb, room_hint=room_hint)
        mode = payload.get("mode", "mock")
        logger.info(f"Analysis complete: mode={mode}, findings={len(payload.get('findings', []))}")
    except requests.RequestException as exc:
        fallback_warning = "⚠️ バックエンドに接続できなかったため、ローカルデモ結果を表示しています。"
        logger.warning(f"Backend request failed, using local mock: {exc}")
        payload = _local_mock_payload(image=image_rgb, room_hint=room_hint, reason=str(exc))
    except ValueError as exc:
        fallback_warning = "⚠️ バックエンドに接続できなかったため、ローカルデモ結果を表示しています。"
        logger.warning(f"Backend response invalid, using local mock: {exc}")
        payload = _local_mock_payload(image=image_rgb, room_hint=room_hint, reason=str(exc))

    annotated = _image_from_base64(payload["annotated_image_base64"])
    improvement = _image_from_base64(payload["improvement_image_base64"])

    overall_md = _overall_markdown(payload)
    if fallback_warning:
        overall_md = f"{fallback_warning}\n\n{overall_md}"

    return (
        gr.update(visible=False), # analyzing_screen hidden
        gr.update(visible=False), # input_screen hidden
        gr.update(visible=True),  # result_screen visible
        overall_md,
        annotated,
        improvement,
        payload["risk_summary_markdown"],
        payload["family_actions_markdown"],
        payload["care_manager_actions_markdown"],
        payload["contractor_actions_markdown"],
        payload["disclaimer_ja"],
        "result",
        payload
    )


def reset_to_input() -> tuple[Any, ...]:
    """Reset the app state and inputs back to Screen 1."""
    return (
        None,                      # photo_input cleared
        "auto",                    # room_hint reset
        gr.update(value="", visible=False),  # error_output hidden/cleared
        gr.update(visible=True),   # input_screen visible=True
        gr.update(visible=False),  # analyzing_screen visible=False
        gr.update(visible=False),  # result_screen visible=False
        None,                      # annotated_output cleared
        None,                      # improvement_output cleared
        "",                        # risk_markdown cleared
        "",                        # family_markdown cleared
        "",                        # care_markdown cleared
        "",                        # contractor_markdown cleared
        "input"                    # current_screen_state
    )


# Gradio Block layout
with gr.Blocks(
    title="親の家 安全チェックAI",
    theme=gr.themes.Soft(primary_hue="red", neutral_hue="slate"),
    css="""
    #container { max-width: 1100px; margin: 0 auto; padding: 20px; }
    .header-container { border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; margin-bottom: 24px; }
    .header-main { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
    .app-title { font-size: 2.1rem; font-weight: 800; color: #0f172a; margin: 0; }
    .app-subtitle { font-size: 1.05rem; color: #475569; margin: 6px 0 0 0; }
    .badge { padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 0.9rem; display: inline-block; }
    .badge-mock { background-color: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; }
    .badge-gemini { background-color: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
    .badge-unknown { background-color: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
    .sumai-card { background: #ffffff; padding: 24px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); margin-bottom: 20px; }
    .hero-card { background: linear-gradient(135deg, #fef2f2 0%, #fff 100%); border-left: 6px solid #ef4444; }
    .disclaimer-box { color: #64748b; font-size: 0.85rem; line-height: 1.5; padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #f1f5f9; margin-top: 16px; }
    .error-box { color: #dc2626; background: #fee2e2; border: 1px solid #fecaca; padding: 12px; border-radius: 8px; margin: 12px 0; font-weight: bold; }
    .guidance-box { background: #f8fafc; border-left: 4px solid #64748b; padding: 12px 16px; border-radius: 0 8px 8px 0; font-size: 0.95rem; margin-top: 12px; }
    .action-card { background: #ffffff; padding: 20px; border-radius: 10px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); margin-bottom: 12px; }
    .family-card { border-top: 5px solid #10b981; background-color: #f0fdf4; }
    .care-card { border-top: 5px solid #3b82f6; background-color: #eff6ff; }
    .contractor-card { border-top: 5px solid #ef4444; background-color: #fef2f2; }
    .result-hero-box { background: #f8fafc; padding: 16px; border-radius: 10px; border: 1px solid #e2e8f0; margin-bottom: 20px; }
    .section-title { font-size: 1.5rem; font-weight: bold; margin: 24px 0 12px 0; color: #0f172a; }
    .details-accordion { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; margin-top: 20px; }
    #analyze-btn { background-color: #ef4444; color: white; font-size: 1.2rem; font-weight: bold; height: 50px; border-radius: 8px; }
    """
) as demo:
    # State management
    current_screen_state = gr.State("input")
    last_image_state = gr.State(None)
    last_payload_state = gr.State(None)

    with gr.Column(elem_id="container"):
        # Global Header
        gr.HTML(
            f"""
            <div class="header-container">
                <div class="header-main">
                    <h1 class="app-title">親の家 安全チェックAI</h1>
                    {_get_mode_badge_html()}
                </div>
                <p class="app-subtitle">写真1枚で、転倒・つまずき・滑りやすさを見える化。</p>
            </div>
            """
        )

        # ==========================================
        # Screen 1: Input Screen
        # ==========================================
        with gr.Column(visible=True) as input_screen:
            gr.HTML(
                """
                <div class="sumai-card hero-card">
                    <h2 style="margin-top:0; color:#ef4444; font-size: 1.3rem;">親の家、危ない場所をAIで見える化</h2>
                    <p style="margin: 0; color:#475569;">まずは写真を1枚撮影またはアップロードしてください。</p>
                </div>
                """
            )

            photo_input = gr.Image(
                label="写真を撮る / アップロード",
                type="pil",
                sources=["upload", "webcam"],
                height=430,
            )

            error_output = gr.Markdown("", visible=False, elem_classes=["error-box"])

            room_hint = gr.Radio(
                label="部屋のヒント",
                choices=ROOM_OPTIONS,
                value="auto",
            )

            guidance = gr.Markdown(shooting_guidance("auto"), elem_classes=["guidance-box"])

            analyze_button = gr.Button("AIで安全チェック", variant="primary", size="lg", elem_id="analyze-btn")

            gr.Markdown(DISCLAIMER, elem_classes=["disclaimer-box"])

        # ==========================================
        # Transient Screen: Analyzing State
        # ==========================================
        with gr.Column(visible=False) as analyzing_screen:
            gr.HTML(
                """
                <div style="text-align: center; margin-bottom: 20px;">
                    <h2 style="color: #ef4444; font-size: 1.6rem;">AI分析中...</h2>
                    <p style="color: #475569; font-size: 1.1rem; margin-top: 8px;">
                        AIが写真の中の転倒・つまずき・滑りやすさを確認しています。
                    </p>
                </div>
                """
            )

            analyzing_image_preview = gr.Image(label="アップロードされた写真", type="pil", height=300, interactive=False)

            gr.HTML(
                """
                <div class="sumai-card" style="margin-top: 20px; text-align: center;">
                    <div style="display: inline-block; text-align: left; font-size: 1.15rem; line-height: 2.2;">
                        <div>🔄 <strong>1. 写真を確認</strong></div>
                        <div>🔄 <strong>2. リスクを抽出</strong></div>
                        <div>🔄 <strong>3. 行動を分類</strong></div>
                        <div>🔄 <strong>4. 結果を作成</strong></div>
                    </div>
                </div>
                """
            )

        # ==========================================
        # Screen 2: Result Screen
        # ==========================================
        with gr.Column(visible=False) as result_screen:
            overall_output = gr.Markdown("## 総合リスク", elem_classes=["result-hero-box"])

            # Visual Display Section (Side-by-side or stacked on mobile)
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 現状写真：赤枠リスク表示")
                    annotated_output = gr.Image(label="赤枠リスク表示", type="pil", height=420, show_label=False, interactive=False)
                with gr.Column(scale=1):
                    gr.Markdown("### 現状 vs 改善イメージ")
                    improvement_output = gr.Image(label="現状 vs 改善イメージ", type="pil", height=420, show_label=False, interactive=False)

            gr.Markdown("<p style='text-align: center; color: #475569; font-size: 0.9rem; margin-top: 8px;'>※コミュニケーション用イメージ｜施工図ではありません</p>")

            # Action Cards Section
            gr.Markdown("## 次にできること", elem_classes=["section-title"])

            with gr.Row():
                with gr.Column(elem_classes=["action-card", "family-card"]):
                    family_markdown = gr.Markdown()
                with gr.Column(elem_classes=["action-card", "care-card"]):
                    care_markdown = gr.Markdown()
                with gr.Column(elem_classes=["action-card", "contractor-card"]):
                    contractor_markdown = gr.Markdown()

            # Risk Details Accordion
            with gr.Accordion("詳しいリスク根拠を見る", open=False, elem_classes=["details-accordion"]):
                risk_markdown = gr.Markdown()

            disclaimer_output = gr.Markdown(DISCLAIMER, elem_classes=["disclaimer-box"])

            # Navigation buttons
            with gr.Row():
                retry_button = gr.Button("対策後の写真でもう一度チェック", variant="secondary", size="lg")
                another_photo_button = gr.Button("別の写真をチェック", variant="secondary", size="lg")

        # ==========================================
        # Event Handlers
        # ==========================================
        room_hint.change(fn=shooting_guidance, inputs=room_hint, outputs=guidance)

        # Sequence:
        # 1. Validate image presence, if valid hide input and show loading screen
        # 2. Run API analysis and update results screen, transition views
        analyze_button.click(
            fn=check_image,
            inputs=[photo_input],
            outputs=[input_screen, analyzing_screen, error_output, analyzing_image_preview, last_image_state]
        ).then(
            fn=run_analysis_and_transition,
            inputs=[photo_input, room_hint],
            outputs=[
                analyzing_screen,
                input_screen,
                result_screen,
                overall_output,
                annotated_output,
                improvement_output,
                risk_markdown,
                family_markdown,
                care_markdown,
                contractor_markdown,
                disclaimer_output,
                current_screen_state,
                last_payload_state,
            ]
        )

        retry_button.click(
            fn=reset_to_input,
            outputs=[
                photo_input,
                room_hint,
                error_output,
                input_screen,
                analyzing_screen,
                result_screen,
                annotated_output,
                improvement_output,
                risk_markdown,
                family_markdown,
                care_markdown,
                contractor_markdown,
                current_screen_state
            ]
        )

        another_photo_button.click(
            fn=reset_to_input,
            outputs=[
                photo_input,
                room_hint,
                error_output,
                input_screen,
                analyzing_screen,
                result_screen,
                annotated_output,
                improvement_output,
                risk_markdown,
                family_markdown,
                care_markdown,
                contractor_markdown,
                current_screen_state
            ]
        )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=SUMAI_WEB_PORT)
