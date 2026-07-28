# SumaiGuard Apple-Inspired UI Design

## Objective

Refresh the existing mobile-first SumaiGuard POC so it feels calm, trustworthy,
and familiar on Apple devices while keeping the product focused on preventive
elderly-home safety. The UI must help an adult child move from one photo to
visible risks and then to the three deterministic action tiers without implying
medical diagnosis, renovation design, or construction approval.

## First-Principles Rule

Safety and comprehension come before visual novelty. Apple-inspired styling is
useful only when it makes the next action clearer, improves readability, and
raises trust without weakening SumaiGuard's product boundaries.

## Minimal Verifiable Deliverable

- A dedicated `codex/sumaiguard-apple-ui` branch based on `origin/main`.
- A refreshed Japanese home, result, and action flow in the existing FastAPI
  web frontend.
- Automated UI-contract tests for product wording, zoom support, touch target
  sizing, and accessible accordions.
- Browser evidence for the complete mock flow at a 390 x 844 viewport.

## Experience Design

### Home

- Use a light system-style background, white elevated cards, one Apple-blue
  primary action, and a neutral secondary action.
- Lead with `写真1枚で、親の家を安全チェック` and explain that only visible
  fall, slip, and trip risks are checked.
- Keep the six supported photo locations as guidance, not selectable profile
  data.
- Make `カメラで撮る` the primary action and `ライブラリから選ぶ` secondary.
- Show readable trust facts: photos are not stored, only visible areas are
  checked, and the POC does not replace professional judgment.

### Result

- Use `安全チェック結果`, never `診断結果`.
- Lead with the concrete finding count and keep overall risk as supporting
  information.
- Rename the image sections to `現在の注意箇所` and
  `対策イメージ（施工図ではありません）`.
- Keep the required current-risk and improvement images stacked vertically.
- Keep the next-step button within a safe, easy-to-reach bottom action area.

### Actions

- Use `次にできること`, never `点検・修繕提案`.
- Keep the exact three policy tiers:
  `家族で今日できること`, `ケアマネ・福祉用具に相談`,
  and `専門施工・現地確認`.
- Expand the family tier by default so the safest immediate actions are visible.
- Keep the other tiers collapsed and clearly label empty tiers as having no
  applicable suggestion.
- Implement accordion headers as real buttons with keyboard focus,
  `aria-expanded`, and `aria-controls`.

## Visual System

- Font stack:
  `-apple-system`, `BlinkMacSystemFont`, `"Hiragino Sans"`,
  `"Noto Sans JP"`, sans-serif.
- Base background: `#F5F5F7`.
- Primary surface: `#FFFFFF`.
- Primary text: `#1D1D1F`.
- Secondary text: `#6E6E73`.
- Primary action: `#007AFF`.
- Safety state colors remain semantic and are not used as decoration.
- Use 16-20 px card radii, restrained shadows, 16-17 px body text, and
  44 px minimum interactive target height.
- Use a translucent top navigation treatment only where it supports hierarchy;
  avoid decorative glass effects behind dense safety content.

## Accessibility And Interaction

- Remove `maximum-scale` and `user-scalable=no` so browser zoom remains
  available.
- Provide an `h1` on the home screen and a logical heading structure afterward.
- Use at least 44 px hit areas for navigation and action controls.
- Add visible `:focus-visible` states.
- Announce analysis and error state changes with live regions.
- Keep collapsed accordion content hidden from both layout and assistive
  technology.
- Preserve Japanese alternative text for both result images.

## Files

- Modify: `apps/sumai_web/app.py`
- Create: `apps/sumai_agent/tests/test_web_ui_contract.py`
- Modify only if needed for test execution:
  `scripts/test_all.sh`

## Out Of Scope

- Gemini prompts, parsing, model selection, or credentials.
- Deterministic rule mapping and action-tier policy.
- Authentication, user profiles, persistence, uploaded-image storage, RAG,
  PDF reports, or cloud deployment.
- Medical, care-level, insurance, legal, or construction decisions.
- Final renovation design or exact measurements from one photo.
- Broad frontend framework migration or unrelated refactoring.

## Risks And Guardrails

- The frontend is one embedded HTML/CSS/JavaScript string, so markup edits can
  silently break event wiring. Contract tests and a full browser flow are
  mandatory.
- Apple-like polish can reduce contrast if translucency is overused. Dense
  safety content remains on opaque surfaces.
- Copy changes can accidentally widen the product boundary. The UI continues
  to say that it checks visible risks only and does not replace professional
  judgment.
- Existing mock mode, image non-persistence, EXIF stripping, and deterministic
  action tiers must remain unchanged.

## Acceptance Criteria

- `写真1枚で、親の家を安全チェック`, `安全チェック結果`, and
  `次にできること` are visible in the intended screens.
- `診断結果` and `点検・修繕提案` are absent from user-facing HTML.
- Page zoom is not disabled.
- All navigation buttons, calls to action, and accordion headers have at least
  a 44 px hit area.
- Every accordion header is a native button with working keyboard behavior and
  synchronized `aria-expanded` state.
- The family tier is open by default; the other tiers remain collapsed.
- All three policy tiers and both result images remain present.
- The mock flow succeeds at 390 x 844 without horizontal scrolling or clipped
  primary actions.
- Existing backend tests, frontend import, and Compose validation pass.

## Verification

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  python3 -m pytest apps/sumai_agent/tests/test_web_ui_contract.py -v

PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh

git diff --check
git status --short --branch
```
