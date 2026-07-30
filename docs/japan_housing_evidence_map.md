# Japan Housing Evidence Map

Review date: 2026-07-13 JST

Purpose: map SumaiGuard risk categories to Japanese official or authoritative housing-safety,介護保険住宅改修,福祉用具, and local-government sources. This file is evidence planning, not legal or administrative advice.

Expected-feature non-detections enter only neutral `confirmation_items`; they never enter `findings`, `RuleEngine`, actions, or overlays. Only localized `visible_hazard` evidence may enter `findings` and `RuleEngine`.

Support-feature non-detection is confirmation-only; it never justifies high-risk classification or professional action.

## 1. Source Registry

| Source ID | URL | Title | Publisher | Supports |
|---|---|---|---|---|
| MHLW_WELFARE_HOUSING | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000212398.html | 福祉用具・住宅改修 | 厚生労働省 | 福祉用具貸与/販売, handrails, slopes, walkers, bath aids, housing modification categories. |
| MHLW_NOTICE_OLD34 | https://www.mhlw.go.jp/web/t_doc?dataId=00ta4381&dataType=1&pageNo=1 | 介護保険の給付対象となる福祉用具及び住宅改修の取扱いについて | 厚生労働省 | Definitions of handrail installation, step elimination, slip-preventive floor/path materials, door replacement, toilet replacement, incidental works. |
| CAA_FALL_PREVENTION | https://www.caa.go.jp/policies/policy/consumer_safety/caution/caution_040 | 高齢者の転倒事故に注意しましょう | 消費者庁 | Home fall prevention points: bath/dressing slip mats, bed/night toilet caution, steps/stairs/entrance handrails/slip prevention, cords out of paths. |
| CAA_HOUSING_SAFETY_SURVEY | https://www.caa.go.jp/policies/future/project/project_012/assets/caa_future_cms201_230331_01.pdf | 住環境における高齢者の安全等に関する調査報告書 | 消費者庁 | Social background and home-environment safety issue framing. |
| KOKUSEN_HOME_ACCIDENTS_2025 | https://www.kokusen.go.jp/pdf/n-20251029_1.pdf | 医療機関ネットワーク事業情報からみた高齢者の家庭内事故 | 国民生活センター | Home accident examples: stairs, bathroom equipment, cords, steps, slippers, carpet edges, injury severity. |
| CAO_AGING_2025 | https://www8.cao.go.jp/kourei/whitepaper/w-2025/html/zenbun/s1_1_1.html | 令和7年版高齢社会白書 高齢化の状況 | 内閣府 | Demographic pressure and long-term need context. |
| FUNABASHI_HOUSING_MOD | https://www.city.funabashi.lg.jp/kenkou/kaigo/004/p056497.html | 住宅改修費の支給制度 | 船橋市 | Local介護保険住宅改修 process, pre-application, support amount, target works. |
| FUNABASHI_ELDERLY_REMODEL | https://www.city.funabashi.lg.jp/kenkou/koureisha/002/p001777.html | 高齢者住宅改造資金の助成 | 船橋市 | Local related制度 and need to confirm requirements with responsible departments. |
| FUNABASHI_BARRIER_FREE | https://www.city.funabashi.lg.jp/machi/juutaku/005/p000000a.html | 住宅バリアフリー・断熱改修支援事業 | 船橋市 | Local related制度 for barrier-free improvement and route to housing policy section. |
| FUNABASHI_REGION_SUPPORT | https://www.city.funabashi.lg.jp/kenkou/koureisha/001/p004493.html | 船橋市地域包括支援センター | 船橋市 | Local comprehensive consultation point for older adults and families. |
| FUNABASHI_CONNECT | https://www.city.funabashi.lg.jp/shisei/keikaku/003/p112446.html | 公民連携窓口 公民CONNECT | 船橋市 | Public-private consultation route and department coordination. |
| FUNABASHI_PRECONSULT | https://www.city.funabashi.lg.jp/shisei/keikaku/003/p112998.html | 民間提案制度における事前相談について | 船橋市 | Pre-consultation route for proposals. |
| TYOJYU_HOME_ACCIDENTS | https://www.tyojyu.or.jp/net/kenkou-tyoju/koureisha-sumai/koreisha-jutakunaijiko.html | 高齢者の住宅内の事故 | 公益財団法人長寿科学振興財団 | Semi-authoritative explanatory support: handrails, lighting, obstacles on paths. |
| TYOJYU_REMODELING_METHODS | https://www.tyojyu.or.jp/net/topics/tokushu/koureisha-sumai/koureisha-seikatsukoui-zyukankyo.html.html | 高齢者の生活行為と住環境 転倒予防に配慮した住宅の改修方法 | 公益財団法人長寿科学振興財団 | Semi-authoritative theory: lighting/shadows, step visibility, photo/field-observation limits. |

## 2. Risk Category Mapping

| Risk category | Visible cues | Cannot judge from photo alone | Family no-cost advice | Care manager / welfare-equipment consultation | Professional construction / on-site confirmation | Recommended source types | Fit for app report/rule engine |
|---|---|---|---|---|---|---|---|
| 段差 / 門檻 / 玄関高低差 | Visible threshold,上がり框, floor height change, shoe-changing area, step edge. | Exact height, resident leg strength, whether step is acceptable, subsidy eligibility, best solution. | Clear shoes/bags around step; slow down; share where to hold; improve visibility using existing lighting. | Step aid, portable ramp, welfare equipment相談 if needed. | Fixed handrail, threshold modification, slope, floor raising only after site inspection. | MHLW_WELFARE_HOUSING, MHLW_NOTICE_OLD34, CAA_FALL_PREVENTION, FUNABASHI_HOUSING_MOD. | A localized visible step may use `genkan_step`; construction always requires professional confirmation. |
| 水分・液体汚れ / 浴室 | Clearly visible local water, soap, or other liquid contamination on the floor; visibly lifted mat edge is a separate trip cue. | Actual friction coefficient, cleaning condition, resident footwear, whether material change is appropriate. | Wipe visible water/oil/soap; remove loose obstacles; keep an existing towel or mat from bunching if safe. | Bath aids or a non-slip mat may be discussed, without a brand recommendation. | Floor material change, waterproofing, drainage, and fixed work require site inspection. | MHLW_NOTICE_OLD34, CAA_FALL_PREVENTION, KOKUSEN_HOME_ACCIDENTS_2025. | A localized bathroom `wet_floor` may map to `bathroom_slip`; glossy material or a kitchen room alone never proves a slip finding. |
| 手すり・立ち座りの確認 | Relevant toilet, bath, bed, or entrance area is sufficiently covered for a photo-scoped non-detection. | Whether support is needed, exact position/height, wall backing, and resident movement pattern. | Discuss the uncertain point without treating absence as established. | Portable supports or aids remain consultation topics only. | Fixed installation and wall backing require on-site confirmation. | MHLW_WELFARE_HOUSING, MHLW_NOTICE_OLD34, FUNABASHI_HOUSING_MOD, FUNABASHI_REGION_SUPPORT. | Neutral confirmation channel only; non-detection never becomes a risk or action. |
| 夜間動線 / 照明不足 | A directly visible, localized dark region affecting the photographed path. | Actual night brightness, switch usability, vision condition, nighttime behavior, exact lux. | Use existing lights; keep path clear; keep doorways unobstructed; avoid rushing at night. | Sensor light or footlight相談 only as consultation, not product recommendation. | Electrical work, switch relocation, added lighting only after site confirmation. | CAA_FALL_PREVENTION, TYOJYU_HOME_ACCIDENTS, TYOJYU_REMODELING_METHODS. | Daytime or ambiguous lighting does not create a finding; `cannot_determine` produces no output item. |
| 通路障害物 / 電線 / 家具配置 | Cords crossing walking route, floor clutter, shoes, bags, trash bins, narrow path. | Whether resident uses walker/cane, actual daily route, visibility at night, object weight/necessity. | Move cords along wall; clear only main path first; define storage location. | Storage aids or cord cover相談 only if no-cost rearrangement fails. | Usually no construction; site confirmation if structural narrowing or door replacement is considered. | CAA_FALL_PREVENTION, KOKUSEN_HOME_ACCIDENTS_2025, TYOJYU_HOME_ACCIDENTS. | Yes. Strong fit for family no-cost tier. |
| 階段 / 廊下 / 玄関 | Localized stair edge, cord, clutter, or landing obstacle. | Step dimensions, handrail presence/continuity, lighting at night, gait, and whether stairs can be used safely. | Remove visible objects; use existing lighting; avoid carrying large items on stairs if possible. | Cane/walker route remains a consultation topic only. | Modification questions require on-site confirmation, but a support non-detection does not create that action. | MHLW_NOTICE_OLD34, CAA_FALL_PREVENTION, KOKUSEN_HOME_ACCIDENTS_2025. | Only the localized step or obstacle may become a visible finding; support non-detection remains neutral confirmation only. |
| トイレ移動・便座まわり | Explicit localized floor clutter or a visibly lifted mat edge in the walking path. | Standing/sitting ability, grab direction, actual clearance, toilet height, care level, and whether a replacement is needed. | Clear visible floor obstacles; confirm emergency communication method; avoid unstable supports. | Portable handrail, raised toilet seat, and welfare equipment remain consultation topics. | Fixed handrail, door replacement, toilet replacement, and floor material change require on-site confirmation. | MHLW_WELFARE_HOUSING, MHLW_NOTICE_OLD34, FUNABASHI_HOUSING_MOD. | Only explicit localized obstacle or mat evidence may create a visible finding; narrow-looking space, material appearance, and support non-detection do not. |
| 浴槽出入り | Localized visible tub edge, explicit wet stepping area, or obstacle at the transfer zone. | Support presence outside the frame, actual tub height, user balance, bathing method, water depth, wall fixing, and whether an aid fits. | Clear visible bottles/items and do not rush; do not infer support needs from the photo. | Bath aids remain consultation topics independent of photo non-detection. | A localized tub-edge finding may route a modification question to site inspection; support non-detection alone never does. | MHLW_NOTICE_OLD34, MHLW_WELFARE_HOUSING, CAA_FALL_PREVENTION, KOKUSEN_HOME_ACCIDENTS_2025. | Explicit tub-edge or wet-floor evidence may be high impact; support non-detection remains confirmation-only and adds no action. |
| 家具転倒・物の落下 | Tall shelf, stacked items, unstable visible furniture, objects above head height. | Fixing status, wall type, earthquake risk, item weight, resident height, and reach behavior. | Do not infer ordinary storage reach from one photo; remove unstable stacks only if safe. | Storage/reach support may be discussed outside the visible-risk channel. | Furniture anchoring and wall fixing require site confirmation. | KOKUSEN_HOME_ACCIDENTS_2025 for home injury severity; TYOJYU_HOME_ACCIDENTS for high-place task caution. | Not a current visible rule; storage height alone cannot create a finding or action. |
| 写真だけでは判断不能 | Blurry/dark/out-of-frame photo, no floor, no path, close-up, non-home, showroom, people-only image. | Everything outside visible frame; exact dimensions; resident movement; legal/insurance/construction judgment. | Retake from another angle; include floor, path, step, handrail area; discuss with family. | Ask regional support or a care manager if concern remains. | Site confirmation is required where construction, wall fixing, floor material, or subsidy is involved. | All sources; especially MHLW_NOTICE_OLD34 and FUNABASHI_HOUSING_MOD for administrative/technical limits. | Route to neutral confirmation or not-applicable output; never fabricate a risk, action, or overlay. |

## 3. How To Wire Evidence Into The App

Recommended YAML additions:

```yaml
source_registry:
  MHLW_NOTICE_OLD34:
    title_ja: 介護保険の給付対象となる福祉用具及び住宅改修の取扱いについて
    publisher_ja: 厚生労働省
    url: https://www.mhlw.go.jp/web/t_doc?dataId=00ta4381&dataType=1&pageNo=1
    supports:
      - handrail_installation
      - step_elimination
      - slip_preventive_floor_material
      - door_replacement
      - western_toilet_replacement
```

Per risk rule:

```yaml
risk_type: bathroom_slip
evidence_source_ids:
  - CAA_FALL_PREVENTION
  - MHLW_NOTICE_OLD34
report_basis_ja: 写真で見える範囲では浴室床の滑り候補です。床材変更や施工可否は現地確認が必要です。
cannot_determine_ja:
  - 床材の摩擦係数
  - 防水・排水状態
  - 施工可否
  - 介護保険住宅改修の適用可否
```

Report renderer should show:

- "参考根拠": title, publisher, URL.
- "この写真だけでは判断できないこと": fixed list plus risk-specific items.
- "相談先の目安": family / care-manager-welfare-equipment / professional-on-site.

Rule engine should use evidence IDs only for explanatory mapping. Evidence IDs must not become legal or administrative decisions.

## 4. Conclusions That Must Not Be Hardcoded

Never hardcode:

- "この住宅改修は介護保険対象です。"
- "この工事が必要です。"
- "この手すり位置が正しいです。"
- "この床材なら安全です。"
- "この家は安全です。"
- "この人にはこの福祉用具が合います。"
- "この自治体制度を利用できます。"

Use instead:

- "写真で見える範囲では、相談候補です。"
- "制度の適用や施工可否は、市・専門職・現地確認が必要です。"
- "本人の動作や寸法は写真だけでは判断できません。"
