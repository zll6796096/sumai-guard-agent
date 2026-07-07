# Risk Policy

This POC is a preventive safety checker. It does not make medical, care-level, insurance, legal, or construction judgments.

## Three Action Tiers

### 1. 家族で今日できること

No-cost actions only.

Allowed:

- Move objects out of walkways.
- Remove or flatten loose mats when possible.
- Use existing lights.
- Share caution points with family.

Not allowed:

- Product purchase.
- Rental.
- Construction.
- Professional installation claims.

### 2. ケアマネ・福祉用具に相談

Purchase, rental, and welfare-equipment consultation only.

Allowed:

- Discuss non-construction welfare equipment.
- Consider anti-slip goods, step aids, bath aids, night lights, or portable handrails.

Not allowed:

- Construction instructions.
- Claims that a product is appropriate without professional review.

### 3. 専門施工・現地確認

Professional construction or on-site confirmation only.

Allowed:

- Fixed handrail feasibility checks.
- Bathroom floor, threshold, or lighting on-site confirmation.
- Wall backing, dimensions, and installation-position confirmation.

Not allowed:

- Final drawings from a single photo.
- Exact measurements from a single photo.
- Legal or insurance applicability decisions.

## Deterministic Policies

- If confidence is below `0.55`, set `needs_human_confirmation=true`.
- If severity is `4` or higher, ensure at least one action exists.
- For `bathroom_slip`, `bathtub_stepover`, `toilet_transfer`, `genkan_step`, `large_step`, and `stairs`, add a professional confirmation note.
- Family actions must remain no-cost and cannot include purchase, rental, construction, or professional-installation wording.
- Care-manager actions must stay purchase, rental, or welfare-equipment oriented and must not include construction.
- Contractor actions are reserved for construction or on-site confirmation.
- Duplicate actions are merged.
- Each tier is limited to five actions for UI clarity.
- Gemini may identify visible risks, but it cannot override deterministic tier policy.
