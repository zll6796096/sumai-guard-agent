# 3-Minute Demo Script

## Preparation

- Local: `docker compose up --build` or `./scripts/local_demo.sh`
- Cloud Run: Ensure services are deployed (`./scripts/check_cloudrun.sh`)
- Sample images are available in `apps/sumai_web/assets/samples/`

## 1. Open the App

Open `http://localhost:8081` (local) or the Cloud Run web URL.

Point out the mode badge:
- 🟢 **MOCK MODE** = Deterministic demo results
- 🔴 **GEMINI MODE** = Real Gemini AI analysis

Explain that the app asks for no elderly questionnaire because the POC works from one photo only.

## 2. Upload a Photo

Upload a 玄関 or 浴室 photo and select the matching room hint.

Mention:
- Room hint is optional (おまかせ = auto-detect).
- Shooting guidance appears below the room hint.
- The app strips EXIF metadata for privacy.

## 3. Show Red Boxes

Click `AIで安全チェック`.

Show the annotated photo with red boxes and R1/R2/R3 labels. Explain that the red boxes are visible-risk communication markers, not measurement or construction output.

## 4. Show Current vs Improvement

Scroll to the side-by-side image:
- Left: Current photo with red risk boxes.
- Right: Improvement illustration with green safe zones and labels.

Point out the watermark: **コミュニケーション用イメージ｜施工図ではありません**

This is a communication tool, not a construction plan.

## 5. Show Basis

Open the リスク詳細 section.

Point out:

- Why the area may be dangerous.
- The photo-based evidence.
- The cautious demo basis label.
- Confidence percentage and human-confirmation flags.

## 6. Show Three Action Cards

Review:

- **家族で今日できること**: no-cost actions only. No products, no construction.
- **ケアマネ・福祉用具に相談**: purchase/rental/welfare-equipment consultation.
- **専門施工・現地確認**: professional construction or on-site confirmation.

Explain that deterministic policy routes actions after the AI vision result. Gemini identifies risks but cannot override the action tier policy.

## 7. Show Re-Check Loop

Click `対策後の写真でもう一度チェック`.

Explain the intended loop: take a photo, act on safe next steps, take another photo, and compare whether visible risks were reduced.

## 8. Show Mode Difference (if time permits)

- Demo mock mode first (instant, deterministic).
- Switch to Gemini mode (real analysis, 3-15 seconds).
- Compare findings — Gemini results are photo-specific.

## Key Talking Points

- **No questionnaire**: One photo starts the conversation.
- **Three tiers**: Separates what family can do today vs. what needs professionals.
- **POC disclaimer**: Does not replace medical, care, or construction judgment.
- **Privacy**: EXIF stripped, no image persistence.
- **Fallback safety**: If Gemini fails, mock mode ensures demo always works.
