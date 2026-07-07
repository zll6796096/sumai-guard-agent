from __future__ import annotations

import base64
import io
import os
from typing import Any

import gradio as gr
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


load_dotenv()

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


def shooting_guidance(room_hint: str) -> str:
    return GUIDANCE.get(room_hint, GUIDANCE["auto"])


def analyze_photo(image: Image.Image | None, room_hint: str) -> tuple[Any, ...]:
    if image is None:
        return (
            "## 総合リスク\n画像を追加してください。",
            None,
            None,
            "",
            "",
            "",
            "",
            DISCLAIMER,
        )

    image = image.convert("RGB")
    try:
        payload = _call_backend(image=image, room_hint=room_hint)
    except requests.RequestException as exc:
        payload = _local_mock_payload(image=image, room_hint=room_hint, reason=str(exc))
    except ValueError as exc:
        payload = _local_mock_payload(image=image, room_hint=room_hint, reason=str(exc))

    annotated = _image_from_base64(payload["annotated_image_base64"])
    improvement = _image_from_base64(payload["improvement_image_base64"])
    return (
        _overall_markdown(payload),
        annotated,
        improvement,
        payload["risk_summary_markdown"],
        payload["family_actions_markdown"],
        payload["care_manager_actions_markdown"],
        payload["contractor_actions_markdown"],
        payload["disclaimer_ja"],
    )


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
    return f"## 総合リスク: {risk}\n- 部屋: {room}\n- 赤枠リスク: {count}件\n- 分析ID: `{payload.get('analysis_id', 'local_mock')}`"


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


def reset_results() -> tuple[Any, ...]:
    return (None, "## 総合リスク", None, None, "", "", "", "", DISCLAIMER)


with gr.Blocks(
    title="親の家 安全チェックAI",
    theme=gr.themes.Soft(primary_hue="red", neutral_hue="slate"),
    css="""
    .sumai-title h1 { font-size: 2.1rem; line-height: 1.2; }
    .sumai-subtitle { color: #475569; font-size: 1.05rem; }
    .disclaimer-box { color: #475569; font-size: 0.92rem; }
    """,
) as demo:
    gr.Markdown(
        """
        # 親の家 安全チェックAI
        <div class="sumai-subtitle">写真1枚で、転倒・つまずき・滑りやすさを見える化。<br>
        家族でできること、相談すべきことをAIが分けて提案します。</div>
        """,
        elem_classes=["sumai-title"],
    )

    with gr.Row():
        with gr.Column(scale=1):
            photo_input = gr.Image(
                label="写真をアップロード / 撮影",
                type="pil",
                sources=["upload", "webcam"],
                height=360,
            )
            room_hint = gr.Radio(
                label="部屋のヒント",
                choices=ROOM_OPTIONS,
                value="auto",
            )
            guidance = gr.Markdown(shooting_guidance("auto"))
            analyze_button = gr.Button("AIで安全チェック", variant="primary", size="lg")
        with gr.Column(scale=1):
            overall_output = gr.Markdown("## 総合リスク")
            disclaimer_output = gr.Markdown(DISCLAIMER, elem_classes=["disclaimer-box"])

    room_hint.change(fn=shooting_guidance, inputs=room_hint, outputs=guidance)

    gr.Markdown("## 現状写真：赤枠リスク表示")
    annotated_output = gr.Image(label="赤枠リスク表示", type="pil", height=420)

    gr.Markdown("## 現状 vs 改善イメージ")
    improvement_output = gr.Image(label="現状 vs 改善イメージ", type="pil", height=420)

    with gr.Row():
        with gr.Column():
            risk_markdown = gr.Markdown(label="リスク詳細")
        with gr.Column():
            gr.Markdown("## 次にできること")
            family_markdown = gr.Markdown()
            care_markdown = gr.Markdown()
            contractor_markdown = gr.Markdown()

    retry_button = gr.Button("対策後の写真でもう一度チェック")

    analyze_button.click(
        fn=analyze_photo,
        inputs=[photo_input, room_hint],
        outputs=[
            overall_output,
            annotated_output,
            improvement_output,
            risk_markdown,
            family_markdown,
            care_markdown,
            contractor_markdown,
            disclaimer_output,
        ],
    )
    retry_button.click(
        fn=reset_results,
        outputs=[
            photo_input,
            overall_output,
            annotated_output,
            improvement_output,
            risk_markdown,
            family_markdown,
            care_markdown,
            contractor_markdown,
            disclaimer_output,
        ],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=SUMAI_WEB_PORT)
