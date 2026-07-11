# SumaiGuard Hackathon Submission Video Design

## 1. Real objective

Produce a short Japanese demo video that helps the DevOps × AI Agent Hackathon judges understand, within roughly 76 seconds, why SumaiGuard Agent exists, why an AI agent is central, how the product works, and what implementation and safety evidence supports it.

The video is a submission asset, not a product feature. No application behavior or product scope will change.

## 2. First-principles rule

- Goal before options: optimize for the five official judging criteria, not visual novelty.
- Value before effort: reuse the verified real screen recording and add only the evidence the current recording lacks.
- Risk before excitement: do not imply medical, care-level, insurance, or construction authority.
- Evidence before optimism: show only currently verified Gemini, Cloud Run, test, and repository claims.

## 3. Minimum verifiable deliverable

A YouTube-ready MP4 with these properties:

- Duration target: 70–80 seconds; design target: approximately 76 seconds.
- Canvas: 1920×1080, 16:9.
- Video: H.264, `yuv420p`, web-compatible MP4.
- Audio: Japanese synthesized narration plus matching Japanese captions.
- Source: the user's real 56.676-second iPhone screen recording.
- Layout: portrait phone capture on the left and a large explanatory panel on the right.
- Stable local output path outside Git: `/Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4`.

## 4. Narrative structure

| Time | Purpose | Visual | Source span | Japanese narration |
|---|---|---|---|---|
| 0–7s | Define the problem | Dark title card | — | 離れて暮らす親の家。転倒につながる危険は、事故が起きるまで見過ごされがちです。 |
| 7–15s | Explain agent necessity | `visible risk extraction → deterministic policy → three action tiers` diagram | — | このAIエージェントは、一枚の写真から見える危険を確認し、次の行動まで整理します。 |
| 15–24s | Show minimal input | Real home screen and photo selection | 0.0–3.0s | 質問票は不要です。部屋を選び、写真を一枚撮影、または選択します。 |
| 24–30s | Prove real AI participation | Compressed analysis state with `Cloud Run` and `Gemini 2.5 Flash` labels | 6.0–28.0s | Cloud Run上で、Gemini 2.5 Flashが、転倒・滑り・つまずきの候補を抽出します。 |
| 30–44s | Show visible evidence | Real red-box diagnosis screen | 28.0–38.0s | 危険箇所を赤い枠で可視化。写真で確認できる根拠だけを、慎重に提示します。 |
| 44–61s | Show autonomous task output | Real three-tier recommendations | 38.0–55.0s | その後、決定論ルールで、家族が今日できること、福祉用具の相談、専門施工の三段階に分けます。 |
| 61–69s | State risk boundaries | `アプリ内に永続保存しない` / `送信前にEXIF除去` / `専門家へ相談` | — | 画像はアプリ内に永続保存せず、Geminiへ送る前にEXIF情報を除去。医療・介護・保険・施工判断の代わりにはなりません。 |
| 69–76s | Close with evidence | GitHub, Cloud Run, strict Gemini, and test badges | — | 公開コードと動作デモはこちら。事故の前に、家族の安全対話を始めます。 |

Source 3.3–6.0s is intentionally excluded because the photo picker exposes unrelated library content in that interval.

## 5. Visual and audio treatment

- Preserve the existing navy product palette; use white text with blue and violet accents.
- Keep the real portrait recording uncropped inside a phone-like frame.
- Use one short explanatory statement at a time on the right; do not reproduce unreadable UI text.
- Compress the long analysis wait to approximately six seconds. Do not fabricate instant analysis.
- Use burn-in Japanese captions so the video remains understandable when muted.
- Keep narration calm and factual. Avoid dramatic claims, fear-based language, or guaranteed safety outcomes.
- Do not use unrelated stock imagery or synthetic depictions of elderly people.
- Do not display API keys, email addresses, private console data, or precise location data.

## 6. Evidence claims allowed in the video

The following claims were verified on 2026-07-11 JST and may be shown:

- The public repository is `https://github.com/zll6796096/sumai-guard-agent`.
- The deployed frontend is `https://sumai-web-sxielk4wua-an.a.run.app`.
- The backend runs on Cloud Run with `MOCK_MODE=false`, `REQUIRE_REAL_GEMINI=true`, and model `gemini-2.5-flash`.
- A real online smoke test passed for both a home image and a non-home image.
- The local project verification passed 73 backend tests, the frontend import check, and Docker Compose validation.

These claims must be rechecked immediately before upload. If any claim changes, the video copy must be updated or removed.

## 7. Explicit out of scope

- Product code, application UX, backend behavior, or deployment changes.
- New authentication, storage, RAG, PDF, profile questionnaire, or cloud features.
- Medical, care-level, insurance, legal compliance, or final construction judgment.
- Exact measurement claims from one photo.
- A fictional product walkthrough or mock-only recording presented as real Gemini analysis.

## 8. Risks and guardrails

- The source video currently lives in a temporary Photos provider path. Copy it to a stable staging path before editing.
- The source audio is effectively silent; replace it instead of amplifying noise.
- Exclude source 3.3–6.0s from every demo segment because it contains unrelated photo-picker library content.
- Preserve visual evidence that analysis takes time; accelerate the wait visibly rather than deleting all processing state.
- Keep the Gemini/Cloud Run claim conditional on a fresh pre-upload smoke test.
- Keep all generated media outside Git to avoid committing large binaries.
- Use YouTube unlisted visibility initially so the ProtoPedia embed is accessible without exposing the video through channel search. Public visibility can be chosen later if explicitly desired.

## 9. Acceptance criteria

- Final duration is between 70 and 80 seconds.
- Resolution is 1920×1080 and the MP4 decodes as H.264 with AAC audio.
- Narration is audible and Japanese captions match the spoken lines.
- The complete real flow appears: input, analysis, visual risk result, and three action tiers.
- The video clearly explains Gemini extraction and deterministic action routing as separate responsibilities.
- The video states the privacy and professional-judgment boundaries.
- No secret, personal email, or sensitive console content is visible.
- A fresh Cloud Run/Gemini smoke test passes before upload.
- The rendered video receives a dense 1fps + scene-change + targeted transition visual/OCR review, with OCR limitations documented, and an audio loudness check.
- Git status remains clean apart from the approved design/plan commits.

## 10. Verification commands

```bash
ffprobe -v error \
  -show_entries format=duration:stream=codec_name,codec_type,width,height \
  -of json \
  /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4

SUMAI_AGENT_URL=https://sumai-agent-sxielk4wua-an.a.run.app \
  python3 scripts/smoke_real_gemini.py

./scripts/test_all.sh

git diff --check
git status --short
```

## 11. Completion evidence

Completion requires the stable MP4 path, `ffprobe` evidence, contact-sheet review, audio loudness evidence, fresh Gemini smoke-test output, local test output, and a clean Git status report. YouTube upload and external publication are separate representational actions and require action-time confirmation immediately before they occur.
