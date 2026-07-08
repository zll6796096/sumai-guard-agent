# 3-Minute Demo Script

## Preparation

- Local: `docker compose up --build` or `./scripts/local_demo.sh`
- Cloud Run: Ensure services are deployed (`./scripts/check_cloudrun.sh`)
- Sample images are available in `apps/sumai_web/assets/samples/`

## 1. Open the App / Screen 1 (入力画面)

Open `http://localhost:8081` (local) or the Cloud Run web URL.

Point out that we are on **Screen 1 (Home / Photo Input)**:
- Background is a dark navy gradient, looking like a native mobile app.
- Compact design containing icon, title, subtitle.
- A compact room hint dropdown (defaults to "おまかせ").
- One line of guidance and a tiny POC disclaimer at the bottom.
- No debug badges or Gradio visual clutter.

## 2. Take or Select a Photo

Select an optional room hint and click **ライブラリから選択** or **カメラで撮影**.

Mention:
- Selects the image using native controls.
- The app transitions immediately to the **Analyzing State** displaying a loading preview and step indicators.
- In a few seconds, it transitions to **Screen 2: Visual Diagnosis Result**.

## 3. Screen 2: Show Visual Diagnosis Result

On Screen 2, point out:
- Simple header showing "診断結果" and a Back button (ホーム).
- Compact summary at the top showing Overall Risk and number of findings.
- Images are stacked vertically for mobile viewports:
  - First: 現状写真 (with red boxes and R1/R2/R3 labels).
  - Second: 改善イメージ.
- Click the primary CTA: **次にできることを見る** to navigate to Screen 3.

## 4. Screen 3: Show Action Suggestions

On Screen 3, point out:
- Header title "次にできること".
- The three action cards:
  - **家族で今日できること** (no-cost, green theme).
  - **ケアマネ・福祉用具に相談** (blue theme).
  - **専門施工・現地確認** (red theme).
- Expand the accordion **詳しいリスク根拠を見る** to see why the area is dangerous and photo evidence.
- Small disclaimer at the bottom.
- Click **ホームに戻る** to clear the state and return to Screen 1.

## Key Talking Points

- **Mobile-first App-like UX**: Centered viewport layout, native camera/photo access, and zero scrolling on the home screen.
- **Three distinct screens**: Focused attention on input -> visual comparison -> actionable next steps.
- **No questionnaire**: Starts a conversation using just one photo.
- **Action cards**: Separates what family can do today vs what needs professional advice.
- **Disclaimer**: Clear notifications that this POC does not replace medical or professional construction judgment.
- **Mock fallback**: If backend is down, local PIL-based fallback ensures the demo always works.
