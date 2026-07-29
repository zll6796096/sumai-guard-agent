# Government Pre-Consultation Review

Review date: 2026-07-13 JST

Scope: SumaiGuard Agent / 親の家 安全チェックAI as a preventive elderly home visible-risk PoC before any contact with Funabashi City or similar municipalities.

## 1. First-Principles Framing

### Real Objective

The real objective is not to prove that AI can "diagnose" a home. The real objective is to test whether one ordinary home photo can safely and usefully turn hidden, hard-to-discuss fall/slip/trip risks into a cautious, visible, family-shareable checklist before a family, care manager, welfare-equipment provider, or local support office decides what to do next.

Relevant first-principles rule: risk control first, verifiable value second, persuasion third.

Minimum verifiable deliverable:

- One photo in, visible risk candidates out.
- Red boxes show only visible or explicitly missing visible safety features.
- Japanese report uses cautious language and separates uncertainty.
- Actions are routed into exactly three tiers: family no-cost, care-manager/welfare-equipment consultation, professional construction/on-site confirmation.
- Demo/production mode cannot silently replace real Gemini analysis with mock output.
- The app does not store uploaded images and strips EXIF before analysis.

Explicitly out of scope:

- Medical diagnosis.
- Care-level or care-need certification.
- Insurance or介護保険 eligibility judgment.
- Final住宅改修 administrative judgment.
- Construction drawing, measurement, quote, inspection, or completion acceptance.
- Product recommendation, brand recommendation, contractor matching, group-buying, or bidding.

### Ground Truths

- Falls and home accidents among older adults are a real social issue. The Cabinet Office 2025 white paper reports Japan's 65+ population at 29.3% of total population as of 2024-10-01 and projects continued aging pressure. Source: Cabinet Office, "令和7年版高齢社会白書", https://www8.cao.go.jp/kourei/whitepaper/w-2025/html/zenbun/s1_1_1.html
- Home fall prevention points are not arbitrary. Consumer Affairs Agency guidance explicitly points to bathrooms/dressing rooms, beds/night toilet movement, steps/stairs/entrances, handrails/slip prevention, and power cords. Source: Consumer Affairs Agency, "高齢者の転倒事故に注意しましょう", https://www.caa.go.jp/policies/policy/consumer_safety/caution/caution_040
- Japanese long-term care制度 already has recognized categories for housing modification: handrails, step elimination, slip-preventive floor/path material changes, door replacement, western-style toilet replacement, and related incidental works. Source: MHLW, "福祉用具・住宅改修", https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000212398.html
- The app can only infer from pixels. It cannot know the resident's gait, ADL, care level, pain, cognition, medication, floor coefficient, exact dimensions, wall backing, waterproofing, or制度 eligibility.

## 2. Real Problem And Pain Points

### What Problem Is The App Trying To Solve?

Families often notice parent-home risks only after a fall, near miss, or care crisis. The app tries to lower the first step: make visible risk candidates concrete enough for a family conversation and professional pre-consultation, without collecting sensitive health profile data or pretending to decide the final answer.

### Is The Problem Real?

| Stakeholder | Pain point | Reality judgment | Evidence |
|---|---|---:|---|
| Household/family | Risky places become "normal" because residents see them every day. | Real | Consumer Affairs Agency and National Consumer Affairs Center both describe everyday home triggers such as steps, cords, slippers, bathrooms, stairs. |
| Adult children | They may live away, visit rarely, and struggle to start a non-accusatory safety conversation. | Real | The product's one-photo, visual-report mechanism directly targets this conversation gap; current repo implements photo upload, red boxes, and Japanese report rendering. |
| Older resident | The person may dislike being judged or forced into renovation; risk communication must be cautious and autonomy-preserving. | Real, but only partly addressed | Current disclaimers prevent medical/construction overreach, but UI wording still includes strong phrases such as "危険を...見つけて改善" and "診断結果". |
| Municipality /地域包括支援 | They need earlier, lower-friction signals of housing risk, but cannot accept liability-shifting AI judgments. | Real, partially addressed | Funabashi has local consultation and housing modification制度; the app has no government pilot protocol, consent flow, or privacy notice yet. |
| Care manager /住宅改修 /福祉用具 | They need pre-consultation context, but must still inspect, interview, and judge suitability. | Real, partially addressed | Current action tiers route to care-manager/welfare-equipment and professional confirmation, but the evidence basis is still too generic in YAML labels. |

Key external evidence:

- National Consumer Affairs Center, "医療機関ネットワーク事業情報からみた高齢者の家庭内事故", https://www.kokusen.go.jp/pdf/n-20251029_1.pdf
- Consumer Affairs Agency, "住環境における高齢者の安全等に関する調査報告書", https://www.caa.go.jp/policies/future/project/project_012/assets/caa_future_cms201_230331_01.pdf
- Funabashi City, "住宅改修費の支給制度", https://www.city.funabashi.lg.jp/kenkou/kaigo/004/p056497.html
- Funabashi City, "船橋市地域包括支援センター", https://www.city.funabashi.lg.jp/kenkou/koureisha/001/p004493.html

## 3. What The App Is Not Solving

This app must not be described as solving:

- Medical diagnosis, fall-risk diagnosis, disease inference, care planning, or rehabilitation assessment.
- Care level certification,介護認定, benefits eligibility, or insurance approval.
- Official住宅改修可否判断, pre-application approval, subsidy amount, or administrative decision.
- Construction drawing, exact measurement, wall backing verification, waterproofing feasibility, legal compliance, or contractor inspection.
- Product selection, brand ranking, price comparison, group-buying, contractor matching, or bid generation.
- Proof that a home is safe after improvement.

Preferred government-facing wording:

- "写真で見える範囲のリスク候補を整理する"
- "家族・専門職との相談前に情報を可視化する"
- "小規模実証で有用性と限界を確認したい"

Avoid:

- "診断する"
- "判定する"
- "安全を保証する"
- "住宅改修の必要性を決める"
- "最適な商品・施工先を提案する"

## 4. Underlying Mechanism

The app's actual value mechanism is:

1. Visible environmental risk discovery: steps, cords, clutter, wet/slippery areas, missing handrails in visible areas, lighting problems, toilet/bathroom transfer points.
2. Hidden-to-visible conversion: red boxes make ambiguous family concern discussable.
3. Standardized risk language: risk type, severity, uncalibrated model score, evidence, basis summary.
4. Deterministic action-tier routing: Gemini can identify candidates, but rules decide action categories.
5. Professional pre-consultation preparation: family can take one report to a care manager,福祉用具専門相談員,地域包括支援センター, or construction professional.
6. Potential aggregated public-health insight: only if consented and anonymized, local governments could learn which visible housing risks appear often in volunteer pilot photos. This is not implemented today.

## 5. Does It Solve The Pain?

| Pain | Current judgment | Repo evidence | Why |
|---|---:|---|---|
| "I do not know where to start checking my parent's home." | Solved for a narrow PoC | `apps/sumai_web/app.py`, `README.md` | The app accepts one photo and guides the user to major rooms. |
| "I need visible, shareable risk candidates." | Partially solved | `visual_renderer.py`, `report_renderer.py` | Red boxes and reports exist, but visual boxes are approximate and can be inaccurate. |
| "I need advice separated by what family can do, what needs care-manager/welfare-equipment, and what needs construction/on-site confirmation." | Mostly solved | `rule_engine.py`, `docs/risk_policy.md`, `room_checklists.yaml` | Deterministic routing exists and family tier forbids purchase/construction wording, but some UI labels still say "購入・レンタル" too prominently. |
| "I need score context and uncertainty." | Partially solved | `rule_engine.py`, `ReportRenderer.risk_summary` | Low uncalibrated model scores are filtered or marked `needs_human_confirmation`, but the UI does not expose a strong "写真だけでは判断できない項目" section. |
| "I need Japan-specific institutional grounding." | Partially solved | `room_checklists.yaml`, `demo_rules.yaml` | Basis labels exist, but sources are generic and lack URL/publisher/action mappings. |
| "I need privacy confidence." | Not yet solved for government use | `image_intake.py`, `README.md` | EXIF stripping/no persistence are implemented, but consent, deletion, and pilot data handling docs are missing. |
| "I need government-grade evidence for a pilot." | Not yet solved | Existing docs are mostly hackathon/local POC docs | Need pilot protocol, evaluation metrics, consent flow, mode proof, and responsibility boundaries. |

## 6. Current PoC Boundary

The PoC is valid only under these conditions:

- User uploads one residential interior photo.
- Output is limited to visible fall/slip/trip/transfer-route risk candidates.
- No health profile is collected.
- No image persistence is performed.
- EXIF is stripped during intake.
- Gemini is used only for visible-risk extraction.
- Deterministic rule engine controls action tier routing.
- All outputs remain cautious and state that medical, care, insurance, and construction judgment are not replaced.
- Mock mode is clearly marked as mock and is never used as real-government-demo evidence.

Current repo support:

- `AGENTS.md`: product boundary and forbidden scope creep.
- `README.md`: PoC boundary, strict production mode, mock vs Gemini mode.
- `apps/sumai_agent/app/services/image_intake.py`: EXIF orientation normalization and PNG re-encoding.
- `apps/sumai_agent/app/services/gemini_vision.py`: structured JSON prompt, home/non-home guard, Gemini/mock/fallback modes.
- `apps/sumai_agent/app/services/checklist_engine.py`: maps observations and missing visible features to risk findings.
- `apps/sumai_agent/app/services/rule_engine.py`: uncalibrated model-score filtering and deterministic action tiers.
- `apps/sumai_agent/app/services/report_renderer.py`: Japanese markdown reports with an explicitly uncalibrated score label and basis fields.
- `apps/sumai_agent/tests/`: tests for health, mock analysis, strict production, Gemini parsing, rules, visual rendering.

## 7. Minimum Conditions For A Government-Ready PoC

Before presenting this as anything beyond "事前相談":

1. Replace strong UI/demo wording: "診断結果", "リスク判定", "危険を見つけて改善", "改善案作成" should become "確認結果", "リスク候補整理", "写真で見える注意箇所を確認", "相談候補整理".
2. Add a visible "写真だけでは判断できない項目" report section.
3. Add consent/privacy/deletion page or modal: no storage, EXIF stripping, no use for medical/care/construction judgment, how logs are handled, what happens in pilot.
4. Require `REQUIRE_REAL_GEMINI=true` and `MOCK_MODE=false` for any real-photo government demo; if Gemini fails, return 503.
5. Fix strict malformed-JSON behavior so invalid Gemini output cannot become mock output under strict mode.
6. Add source IDs or URLs to risk basis mapping, not only generic labels.
7. Prepare a one-page pilot protocol: target users, image handling, consent, exclusion criteria, evaluation metrics, incident handling, and what the city is not being asked to approve.
8. Show tests and logs proving mode, model, latency, fallback reason, and no image persistence.

## 8. Government Contact Feasibility

Conservative judgment:

- Suitable now: limited事前相談 through Funabashi City's public-private consultation route, only as a problem/PoC discussion and only if the message is framed as "risk visualization for family/professional conversation".
- Not suitable now: formal proposal, procurement discussion, live municipal service, public resident pilot, or any claim that the AI determines safety,改修 necessity,制度 eligibility, or construction suitability.

Funabashi contact route evidence:

- Funabashi City says公民CONNECT receives pre-consultations for proposals. Source: "民間提案制度における事前相談について", https://www.city.funabashi.lg.jp/shisei/keikaku/003/p112998.html
- Funabashi describes公民CONNECT as receiving民間提案, organizing necessity/effectiveness, and connecting to relevant departments. Source: "公民連携窓口 公民CONNECT", https://www.city.funabashi.lg.jp/shisei/keikaku/003/p112446.html

Recommended first-contact ask:

"高齢者住環境の見える範囲のリスク候補を、家族・地域包括・ケアマネとの相談前に整理する小規模PoCについて、自治体側の関心、懸念、相談先部署、実証条件を確認したい。医療・介護認定・住宅改修可否判断・施工判断は行わない。"

Do not promise:

- Accuracy guarantees.
- Fall prevention outcomes.
- Resident safety certification.
- Administrative approval support.
- Subsidy eligibility prediction.
- Product/contractor matching.
- Image storage or aggregate analytics unless a separate consent and governance plan is approved.
