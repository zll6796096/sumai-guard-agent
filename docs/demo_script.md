# 3-Minute Demo Script

## Preparation

- Local: `docker compose up --build` or `./scripts/local_demo.sh`
- Cloud Run: Ensure services are deployed (`./scripts/check_cloudrun.sh`)
- Sample images are available in `apps/sumai_web/assets/samples/`

## 1. Open the App / Screen 1 (入力画面)

Open `http://localhost:8081` (local) or the Cloud Run web URL.

Point out that we are on **Screen 1 (Home / Photo Input)**:
- Background is a dark navy gradient, looking like a native mobile app.
- Compact design containing the app tag and message.
- A six-place guidance grid: 玄関, 廊下, 浴室, トイレ, 寝室, and キッチン.
- One line of shooting guidance, separate **カメラで撮影** and **ライブラリから選択** buttons, and a tiny POC disclaimer at the bottom.
- No debug badges or framework chrome in the normal user view.

## 2. Take or Select a Photo

Click **ライブラリから選択** or **カメラで撮影** and select one photo.

Mention:
- Selects the image using native controls (separate camera capture vs library).
- Photo selection transitions directly to Screen 2 and starts analysis automatically.
- The **Analyzing State** displays the selected photo, `写真確認中`, and progress indicators.
- In a few seconds, it transitions to **Screen 2: Visual Diagnosis Result**.

## 3. Screen 2: Show Visual Diagnosis Result

On Screen 2, point out:
- Simple header showing "診断結果" and a Back button (ホーム).
- Compact summary at the top showing Overall Risk and number of findings.
- Exactly two images are stacked vertically:
  - First: 危険提示 (with red boxes and Japanese risk labels).
  - Second: 改善イメージ (improvement-only image shown below the first image).
- Click the primary CTA: **点検・修繕提案を見る** to navigate to Screen 3.

## 4. Screen 3: Show Action Suggestions

On Screen 3, point out:
- Header title "点検・修繕提案".
- Subtitle: "できることから順に確認してください。"
- The three collapsed action cards:
  - **家族で今日できること** (0円・すぐできる, green theme).
  - **ケアマネ・福祉用具に相談** (購入・レンタル, blue theme).
  - **専門施工・現地確認** (工事・専門確認, red theme).
- Point out that clicking any header toggles the accordion smoothly.
- Each header shows the estimated count dynamically (e.g. `(1件)`).
- Expand the accordion **詳しいリスク根拠を見る** to see why the area is dangerous and photo evidence.
- Small disclaimer at the bottom.
- Click **ホームに戻る** to clear the state and return to Screen 1.

## 5. Developer Debug & Edge Case Scenarios

### Showing the Debug Panel (`?debug=1`)
1. Append `?debug=1` to the URL (e.g., `http://localhost:8081/?debug=1`).
2. Run the analysis as usual.
3. Show the **DEBUG INFO** panel rendered at the bottom of Screen 2 and Screen 3:
   - Point out the `mode` (e.g., `gemini` or `mock`).
   - Show the exact `model` being called (e.g. `gemini-2.5-flash`).
   - Mention the unique `Analysis ID` and `Findings Count`.
   - Point out that this badge is completely hidden for normal users.

### Non-Home Environment Demo
1. Select a non-home image (e.g., food, outdoor, animal, document) or generate a solid blue color; analysis starts automatically.
2. Point out that the AI correctly identifies it as a non-home environment (`is_home_environment: false` in the debug panel).
3. View Screen 2:
   - Notice that the image cards are hidden.
   - A warning box is displayed: `住宅内の安全確認対象ではない可能性があります。`
   - Overall risk level is `low` (低) and finding count is `0件`.
   - The action cards show the fallback warning message.

### Strict Mode / Gemini Unavailable Demo
1. Disable the Gemini API key or set `REQUIRE_REAL_GEMINI=true` without setting the key.
2. Attempt to run safety analysis.
3. Point out the clear error message on Screen 1 notifying the user that real Gemini analysis is required but unavailable (HTTP 503 error), demonstrating that strict production requirements are met and no mock fallbacks are allowed.

## Key Talking Points

- **Mobile-first App-like UX**: Centered viewport layout, native camera/photo access, and zero scrolling on the home screen.
- **Three distinct screens**: Focused attention on input -> visual comparison -> actionable next steps.
- **No questionnaire**: Starts a conversation using just one photo.
- **Action cards**: Separates what family can do today vs what needs professional advice.
- **Disclaimer**: Clear notifications that this POC does not replace medical or professional construction judgment.
- **Strict Production Mode**: Optional strict mode (`REQUIRE_REAL_GEMINI=true`) ensures that only real Gemini output is returned, preventing silent mock fallbacks during important demos.
- **Non-home Validation**: Protects the boundary by recognizing and warning the user if the uploaded photo is not a home environment.
- **Uncalibrated Model-Score Thresholds**: Deterministically filter low-score candidates; this is not a calibrated probability or an accuracy guarantee.
