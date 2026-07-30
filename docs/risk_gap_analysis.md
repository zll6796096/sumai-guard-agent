# Risk Gap Analysis

Review date: 2026-07-13 JST

Repository-state correction: 2026-07-29 JST (source layer and rule-source facts only).

Scope: government-contact readiness for SumaiGuard Agent / 親の家 安全チェックAI.

## 1. Current Gap Table

| Problem | Severity | Impact | Current evidence | Recommended change | Must before government contact? |
|---|---|---|---|---|---|
| UI wording overstates capability: "危険を...見つけて改善", "リスク判定", "診断結果", "危険提示", "改善案作成". | High | User / Government / Legal | `apps/sumai_web/app.py` contains these phrases. | Change to "リスク候補", "確認結果", "注意箇所", "相談候補整理". | Yes before any demo screenshot or live walkthrough. |
| Demo docs use hackathon framing and "Visual Diagnosis Result". | Medium | Government | `docs/demo_script.md` describes "診断結果" and demo points. | Create government-specific script with cautious terms and mode disclosure. | Yes before sending materials. |
| Privacy, consent, and deletion explanation are insufficient for government-facing use. | High | User / Government / Legal | `image_intake.py` strips EXIF and app does not persist images, but no user consent/deletion page exists. | Add consent/privacy text: no storage, EXIF strip, logs, third-party Gemini processing, pilot data handling, deletion/non-retention. | Yes. |
| Mock/fallback can look like successful analysis outside debug mode. | High | Government / Technical | Backend fallback when `REQUIRE_REAL_GEMINI=false`; frontend local fallback when backend unreachable. | Government demo must set `MOCK_MODE=false` and `REQUIRE_REAL_GEMINI=true`; show `/status` and logs; disable or visibly label frontend local fallback for government mode. | Yes. |
| Strict mode malformed JSON may still become mock output because `parse_vision_json()` falls back to mock on JSON decode/type errors. | High | Technical / Government | `gemini_vision.py` returns `mock_vision_result()` on malformed JSON; strict path calls `_call_gemini()` and receives a valid-looking result. | Add strict parsing path that raises `GeminiUnavailableError` on malformed/invalid Gemini output; add test. | Yes before real demo. |
| Source provenance exists in code but is not yet an externally reviewed government evidence package. | Medium | Government / Technical | `room_checklists.yaml` contains `source_registry` entries with source IDs, publisher, and URL plus `basis_source_map`; `OntologyRepository` validates the mapping and findings carry source IDs. The ordinary report still shows basis label/summary rather than full citations. | Review source coverage with appropriate experts and expose verified publisher/URL citations in government materials. Engineering provenance is not government endorsement. | Yes before serious pilot or official-evidence claims; not a blocker to a carefully framed first consultation. |
| No explicit "写真だけでは判断できない項目" section. | High | User / Government / Legal | Report has `要確認` per finding, but no consolidated photo-limit section. | Report should list dimensions, wall backing, floor friction, resident movement, care level, subsidy eligibility, construction feasibility as not judgeable from one photo. | Yes before demo. |
| Non-home detection is helpful but not robustly validated. | Medium | Technical / Government | Tests include solid-color non-home; prompt lists non-home examples. | Add test fixtures for people-only, outdoor street, public facility, document, product close-up, and furniture showroom. | No for first inquiry, yes before pilot. |
| Low-score/unknown filtering exists but user-facing uncertainty is still limited. | Medium | User / Government | Rule engine treats the uncalibrated model score as a routing signal: `<0.45` is filtered, known `0.45-0.60` requires human confirmation, and unknown requires `>=0.75`. | Keep the explicit uncalibrated label and surface "候補/要確認" in UI summary and report. | Yes before live government demo. |
| Visual boxes may be approximate or mapped to heuristic zones. | Medium | User / Government / Technical | `visual_renderer.py` remaps some risk types to fixed zones and caps to three boxes. | Label boxes as "表示位置は目安"; keep original evidence text; avoid using boxes as measurement or construction position. | Yes before demo. |
| Improvement image may imply final renovation design. | Medium | Legal / Government | UI says "改善イメージ"; watermark says not construction drawing. | Rename to "相談用イメージ" or "改善候補イメージ"; repeat it is not a design, quote, or construction instruction. | Yes before demo. |
| Family no-cost tier mostly works, but some family actions may imply adding items if not already owned. | Medium | User / Commercial / Legal | Some checklist wording references lights/mats/stands; rule engine blocks explicit purchase words only. | Audit family tier so it says "既存の照明を使う", "今ある物を移動する", no purchase. | Yes. |
| Care-manager tier label "購入・レンタル" may feel commercially誘導. | Medium | Government / Commercial | UI accordion badge says "購入・レンタル". | Reword to "相談候補" or "福祉用具相談"; keep purchase/rental only inside cautious explanation. | Yes before government materials. |
| Cloud Run docs and unauthenticated deployment scripts exceed local PoC boundary. | Medium | Government / Privacy | `README.md` and `docs/cloudrun_deployment.md` describe Cloud Run deployment. | For government pre-consultation, state that no public resident upload endpoint will be used without privacy/security review; local/offline demo preferred. | Yes in contact material. |
| No government pilot protocol. | High | Government | No docs for participant criteria, data handling, evaluator workflow, metrics, or incident response. | Add pilot protocol before any "small-scale実証" request. | Yes before asking for a pilot, not necessarily before first事前相談. |
| No formal evaluation metrics. | Medium | Government / Technical | Tests prove behavior, not usefulness. | Define metrics: user comprehension, false reassurance rate, expert review agreement, uncertainty clarity, time to consultation prep. | No for first inquiry; yes before pilot. |
| No report export/government exhibit package. | Low | Government | PDF download is intentionally not implemented. | Keep PDF out of app for now; create static sample screenshots and anonymized sample report outside user data flow. | No. |
| Commercialization path is not isolated in docs. | High | Government / Commercial | Product boundary forbids product/contractor recommendations, but care tier mentions purchase/rental. | Add explicit "公益版 has no product, brand, contractor, affiliate, bidding, group-buying, lead-gen." | Yes. |
| Aggregate municipal insight is only a concept, not governed. | Medium | Government / Legal | No aggregation schema or consent. | Do not mention aggregate analytics unless separately consented/anonymized and approved. | Yes. |
| "AIで安全チェック" may be acceptable for user acquisition but too broad for government trust. | Low / Medium | Government / User | UI button says "AIで安全チェック" in docs and scripts. | For government mode, use "写真で注意箇所を確認". | Recommended before demo. |

## 2. Must Fix Before Contacting Government

Minimum before emailing or calling for事前相談:

- Prepare a one-page conservative summary: problem, PoC boundary, no diagnosis/no certification/no construction judgment, desired feedback.
- Do not attach hackathon demo script as-is.
- Add or attach privacy/non-retention statement.
- State whether any demo is mock or real Gemini; do not blur the two.
- Include this evidence map and source list rather than saying "AI standard".
- Avoid commercial terms such as product recommendation, contractor referral, group buying, bidding, or marketplace.

Minimum before live demo or small pilot request:

- UI text downgrade.
- Strict mode malformed JSON fix.
- Government-demo config proof: `MOCK_MODE=false`, `REQUIRE_REAL_GEMINI=true`, `/status` screenshot/log, fallback blocked.
- Consent/privacy/deletion flow.
- "写真だけでは判断できない項目" section.
- Pilot protocol and evaluation metrics.

## 3. Can Iterate After First Contact

These can follow after receiving municipal feedback:

- More room/risk test fixtures.
- Expert review workflow for care managers or福祉住環境コーディネーター.
- Expose reviewed `source_registry` publisher/URL citations in the report or government exhibit; API source-ID mapping already exists through `basis_source_map`.
- Anonymized sample report package.
- Accessibility improvements for elderly users and caregivers.
- Evaluation dashboard for pilot results, only with approved anonymization.

## 4. Commercialization Deferred

Do not add now:

- Product recommendation.
- Brand recommendation.
- Contractor recommendation.
- Lead generation.
- Group-buying.
- Auction/bidding.
- Affiliate links.
- Paid prioritization.

Why: in an older-adult safety context, commercial conversion can look like fear-based誘導, conflict of interest, or public-service capture. If ever considered, it must be separated from the公益版 by governance, disclosure, opt-in, and independent expert review. For government contact, the product should be framed as公益 PoC only.
