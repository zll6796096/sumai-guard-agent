# 3-Minute Demo Script

## Preparation

- Local: `docker compose up --build` or `./scripts/local_demo.sh`
- Cloud Run: Ensure services are deployed (`./scripts/check_cloudrun.sh`)
- Sample images are available in `apps/sumai_web/assets/samples/`

## 1. Open the App / Screen 1 (入力画面)

Open `http://localhost:8081` (local) or the Cloud Run web URL.

Point out that we are on **Screen 1 (入力画面 / photo capture screen)**:
- Hero card: "親の家、危ない場所をAIで見える化"
- Large photo capture area.
- Mode badge: 🟢 **MOCK MODE** (deterministic demo results) or 🔴 **GEMINI MODE** (real Gemini AI analysis).

Explain that the app asks for no elderly questionnaire because the POC works from one photo only.

## 2. Upload a Photo

Upload a 玄関 or 浴室 photo and select the matching room hint.

Mention:
- Room hint is optional (おまかせ = auto-detect).
- Shooting guidance appears dynamically.
- The app strips EXIF metadata for privacy.

## 3. Transient State (診断中)

Click `AIで安全チェック`.

Explain that:
- Screen 1 disappears.
- The **Transient Screen (診断中 / analyzing state)** appears, showing the image preview and step-by-step indicators.
- In 3-15 seconds, it transitions to **Screen 2 (診断結果画面 / analysis result screen)**.

## 4. Screen 2: Show Red Boxes and Visual Comparison

On Screen 2, point out the strongest visual section at the top:
- Left: Current photo with red risk boxes (赤枠リスク表示).
- Right: Improvement illustration with green safe zones (現状 vs 改善イメージ).
- Watermark: **コミュニケーション用イメージ｜施工図ではありません** (communication tool, not a construction plan).

## 5. Show Three Action Cards

Review:
- **家族で今日できること**: no-cost actions only (calm green theme).
- **ケアマネ・福祉用具に相談**: purchase/rental/welfare-equipment consultation.
- **専門施工・現地確認**: professional construction or on-site confirmation.

Explain that deterministic policy routes actions after the AI vision result. Gemini identifies risks but cannot override the action tier policy.

## 6. Show Basis

Open the accordion: **詳しいリスク根拠を見る** (risk details).

Point out:
- Why the area may be dangerous.
- The photo-based evidence.
- The cautious demo basis label.
- Confidence percentage and human-confirmation flags.

## 7. Show Re-Check Loop

Click `対策後の写真でもう一度チェック` or `別の写真をチェック`.

Point out that:
- The result screen is cleared.
- We return to Screen 1 with a clean state.
- Explain the intended loop: take a photo, act on safe next steps, take another photo, and compare whether visible risks were reduced.

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
