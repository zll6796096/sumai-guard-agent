# AGENTS.md - SumaiGuard Agent Operating Rules

## Product Boundary

SumaiGuard Agent / 親の家 安全チェックAI is a preventive elderly home safety checker.
It is not an interior design app, not a final renovation design app, and not a medical,
care-level, insurance, or construction judgment system.

Keep the product boundary narrow:

- One photo in, visible safety risks out.
- Red boxes identify visible fall, slip, and trip risks.
- Japanese explanations must stay cautious and evidence-based.
- Next actions must be routed into the three required action tiers.

## Forbidden Scope Creep

Do not add:

- Elderly profile questionnaires.
- Age, walking-state, fall-history, care-level, disease, medication, or insurance questions.
- Full RAG, vector databases, or persistent knowledge stores.
- PDF report download.
- Authentication, user accounts, or persistent storage.
- Cloud deployment work in the local POC.
- Final renovation design, construction drawings, legal compliance claims, or exact measurements from one photo.

## Engineering Rules

- Keep the UI in Japanese.
- Keep code typed and testable.
- Always preserve mock mode.
- Never hardcode secrets or API keys.
- Do not persist uploaded images.
- Strip EXIF during image intake.
- Use Gemini only for visible-risk extraction; deterministic rule mapping runs after Gemini output.
- Gemini must not override the deterministic action-tier policy.

## Action Tier Policy

- `家族で今日できること`: no-cost actions only. No purchased products. No construction.
- `ケアマネ・福祉用具に相談`: purchase, rental, or welfare-equipment consultation only. No construction.
- `専門施工・現地確認`: professional construction or on-site confirmation only.

## Completion Standard

Every change must preserve:

- Local FastAPI backend runnable in mock mode.
- Local Gradio frontend runnable without credentials.
- Tests for health, mock analysis, deterministic policy, visual rendering, and report rendering.
- Clear disclaimers that the POC does not replace medical, care, insurance, or construction judgment.
