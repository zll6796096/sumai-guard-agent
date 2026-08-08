# SumaiGuard Japan App Store Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Submit `実家あんしんチェック` build 1 to App Review, obtain approval, manually release it in Japan, verify its public storefront, and complete one privacy-safe production smoke without conflating any gate.

**Architecture:** Tracked release documents define the public wording, privacy answers, review path, screenshots, and sanitized evidence schema. A verified signed archive is exported and uploaded only after the exact production backend and public policy pages pass. App Store Connect actions use the intended provider/team and require explicit checkpoints before upload, review submission, and manual release. Evidence tracks Archive, Export, Upload, Processing, TestFlight, Review, Approval, Release, Storefront, and Smoke independently.

**Tech Stack:** Xcode 26.6, App Store Connect, Apple Developer, Transporter/Xcode Organizer, SwiftUI simulator and physical iPhone, Python release validators, Cloud Run public endpoints, Markdown release artifacts.

---

## Scope and fixed listing identity

| Field | Value |
|---|---|
| App Store name | `実家あんしんチェック` |
| Home-screen name | `実家チェック` |
| Subtitle | `写真で見つける住まいの注意点` |
| Bundle ID | `com.zll.sumaiguard` |
| Version / build | `1.0` / `1` |
| Storefront | Japan |
| Language | Japanese |
| Price | Free |
| In-app purchases | None |
| Primary / secondary category | Lifestyle / Utilities |
| Device | iPhone only |
| Release method | Manual |

The public name remains provisional until the exact App Store Connect record accepts it. If Apple rejects or reserves the name, stop and return to product naming; do not silently choose a variant.

## Guardrails

- No upload before the exact source SHA, exact candidate, real-device App Attest, production promotion, and production endpoints are verified.
- No App Review submission before all metadata, privacy answers, screenshots, review notes, support, privacy policy, and build selection are re-read in App Store Connect.
- No manual release before the user confirms the exact approved build and current production evidence.
- Screenshots and smoke tests use fictional/synthetic home content only.
- Tracked files contain no Apple account identifiers, provider IDs, certificates, API keys, tokens, signed URLs, device IDs, reviewer personal data, or real home photos.
- Privacy answers are conservative and reflect implemented providers and observed log retention; do not select `Data Not Collected` by convenience.
- Do not read, modify, stage, or delete `docs/preconsultation/`.

## Acceptance evidence

- Public `/privacy` and `/support` URLs are stable, HTTPS, Japanese, `no-store`, and reachable without login.
- App Store Connect accepts the exact app name and bundle ID in the intended provider.
- A signed archive and App Store Connect export pass validation; entitlements and embedded origin match the release contract.
- The exact build uploads, processes, appears in TestFlight, and passes a physical-device production smoke.
- Japanese metadata, privacy label, screenshots, age rating, export compliance, and review notes are saved and independently rechecked.
- App Review submission and approval are observed separately.
- Manual release is explicitly confirmed and observed.
- The direct Japan storefront URL resolves to the exact app/version and a post-release privacy-safe smoke succeeds.

## Task 1: Resolve owner-controlled public identity and support boundary

**Files:**

- Create: `docs/app-store/privacy-policy.md`
- Create: `docs/app-store/app-description-ja.md`
- Create: `docs/app-store/app-privacy-label-draft.md`
- Create: `docs/app-store/app-review-notes.md`
- Create: `docs/app-store/screenshot-plan.md`
- Modify: `apps/sumai_web/public_pages.py`
- Modify: `apps/sumai_agent/tests/test_documentation_contract.py`
- Modify: `apps/sumai_agent/tests/test_web_ui_contract.py`

- [ ] **Step 1: Confirm the accountable public operator and support channel**

Before editing public policy text, the owner must confirm the legal/operator display name and a monitored support email or support form. Verify control of the selected address by sending and receiving a harmless test message. Record only the public values intended for the storefront; do not expose private addresses or Apple account email.

If no monitored public support channel exists, this task is blocked. Do not invent one or substitute a personal address without explicit owner approval.

- [ ] **Step 2: Write RED content-contract tests**

Require both rendered pages and tracked drafts to contain:

- `実家あんしんチェック`;
- the confirmed operator and support contact;
- one-photo visible-risk purpose;
- SumaiGuard Cloud Run and Google Gemini by Google LLC;
- Firebase App Check and Apple App Attest integrity processing;
- EXIF removal and no SumaiGuard application persistence;
- actual bounded process-local semantic memo behavior;
- observed Cloud Logging retention;
- refusal, withdrawal, support, and deletion-request paths;
- medical, care, insurance, legal-compliance, exact-measurement, and construction boundaries.

Require absence of `POC版` in public release pages while retaining a clear professional-judgment disclaimer.

- [ ] **Step 3: Run RED**

Run:

```bash
python -m pytest apps/sumai_agent/tests/test_documentation_contract.py apps/sumai_agent/tests/test_web_ui_contract.py -v
```

Expected: failure until the public release copy is added.

- [ ] **Step 4: Write source-faithful Japanese listing copy**

The description leads with family value and uses this fixed opening:

```text
離れて暮らす親の家で気になる場所を、写真1枚から確認するためのアプリです。
写真に写っている範囲の、転倒・つまずき・滑りにつながる可能性がある箇所を赤枠で示し、次にできることを3つの相談先に分けて整理します。
```

It must state that the app does not determine safety, does not replace experts, may miss risks, and does not infer dimensions or eligibility. Do not market `AI diagnosis`, `prevention guarantee`, `safe home`, or accuracy percentages.

- [ ] **Step 5: Publish privacy/support through the existing web service**

Update static page sources only; retain no-store and security headers. The production web home may describe the native app but keeps `PUBLIC_WEB_ANALYSIS_ENABLED=false` and does not add public browser upload.

- [ ] **Step 6: Run GREEN and commit**

Run:

```bash
python -m pytest apps/sumai_agent/tests/test_documentation_contract.py apps/sumai_agent/tests/test_web_ui_contract.py -v
```

Stage only the named docs, page source, and tests; commit with `docs: prepare SumaiGuard App Store listing`.

## Task 2: Create and validate the App Store screenshot set

**Files:**

- Create: `docs/app-store/screenshots/ja-JP/6.9-inch/01-capture.png`
- Create: `docs/app-store/screenshots/ja-JP/6.9-inch/02-visible-risks.png`
- Create: `docs/app-store/screenshots/ja-JP/6.9-inch/03-action-tiers.png`
- Create: `docs/app-store/screenshots/ja-JP/6.9-inch/04-consent.png`
- Create: `docs/app-store/screenshots/ja-JP/6.9-inch/05-share-pdf.png`
- Create: `scripts/validate_app_store_assets.py`
- Create: `scripts/test_validate_app_store_assets.py`

- [ ] **Step 1: Write RED asset validation tests**

The validator must enforce Apple-accepted 6.9-inch screenshot pixel dimensions used by the current App Store Connect uploader, RGB/RGBA PNG, five unique hashes, no alpha-only blank frame, Japanese copy presence in the source manifest, and filename order. It also scans OCR output and metadata for email addresses, GPS, names, street addresses, debug banners, localhost, tokens, and real device identifiers.

The implementation must refresh the accepted dimensions from the current App Store Connect upload UI or Apple screenshot specifications on execution day and encode the observed allowed dimensions as a test fixture. This is an external rule check, not a guessed constant.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest scripts/test_validate_app_store_assets.py -v
```

Expected: failure because screenshots and validator do not exist.

- [ ] **Step 3: Capture clean app screens with fictional content**

Boot the selected 6.9-inch iPhone simulator in Japanese, set a deterministic status bar, and exercise the app with a geometric fictional room fixture. Capture raw screens:

```bash
xcrun simctl status_bar booted override --time 9:41 --batteryState charged --batteryLevel 100 --wifiBars 3 --cellularBars 4
xcrun simctl io booted screenshot /tmp/sumaiguard-capture.png
```

Never use a real home image, family photo, name, address, or device screenshot containing notifications.

- [ ] **Step 4: Compose the value-first five-screen story**

The first three headlines are fixed:

```text
親の家、気になったら 写真を1枚
見える注意点だけ 赤枠で確認
次にできることを 3つの相談先へ
```

Screens 4 and 5 explain per-image consent/privacy and text-only PDF sharing. Use the forest-green/cream/gold brand, large Japanese type, truthful app UI, and no phone-frame or feature that the binary does not provide.

- [ ] **Step 5: Run asset validation and visual inspection**

Run:

```bash
python scripts/validate_app_store_assets.py
shasum -a 256 docs/app-store/screenshots/ja-JP/6.9-inch/*.png
```

Open every final-size image and inspect legibility, cropping, safe areas, color contrast, fictional content, and consistency with build 1.

- [ ] **Step 6: Commit assets and manifest**

Stage only the five approved images, screenshot plan, validator, and tests; commit with `assets: add Japanese App Store screenshots`.

## Task 3: Create the App Store Connect record without submitting a build

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Verify provider/team and agreements**

In App Store Connect, verify the intended provider name, Paid Apps agreement state, tax/banking requirements appropriate for a free no-IAP app, and the role performing the action. Do not proceed in an unknown or personal provider.

- [ ] **Step 2: Verify the Bundle ID and capability**

In Certificates, Identifiers & Profiles, verify `com.zll.sumaiguard`, App Attest capability, iPhone distribution profile, and the team embedded in the local Release archive. Stop on mismatch.

- [ ] **Step 3: Create the app record**

Use:

- Platform: iOS
- Name: `実家あんしんチェック`
- Primary language: Japanese
- Bundle ID: `com.zll.sumaiguard`
- SKU: `SUMAIGUARD-IOS-1`
- User access: Full Access unless owner policy requires a narrower role

This action reserves the name but does not upload, submit, approve, or publish anything.

- [ ] **Step 4: Confirm name acceptance**

Record only the App Store Connect numeric app ID and accepted localized name in sanitized release evidence. If the exact name cannot be saved, stop and ask the user to choose a new name; do not mutate app/bundle names independently.

## Task 4: Promote the verified backend candidate and verify production

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Re-run dry-run promotion validation**

Run:

```bash
GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
SUMAI_CANDIDATE_EVIDENCE="$SUMAI_CANDIDATE_EVIDENCE" \
SUMAI_DEVICE_EVIDENCE="$SUMAI_DEVICE_EVIDENCE" \
./scripts/promote-verified-candidate.sh
```

Expected: it reports a valid, exact candidate and proposed prior/new revisions without mutation.

- [ ] **Step 2: Ask for explicit production-promotion confirmation**

Present exact SHA, candidate revisions, current production revisions, test evidence, rollback target, and expected 100% traffic change. Stop until the user confirms this production mutation.

- [ ] **Step 3: Promote the exact verified candidate**

After confirmation:

```bash
SUMAI_PROMOTE_APPLY=true \
SUMAI_PROMOTE_CONFIRM=PROMOTE_VERIFIED_SUMAI_CANDIDATE \
GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
SUMAI_CANDIDATE_EVIDENCE="$SUMAI_CANDIDATE_EVIDENCE" \
SUMAI_DEVICE_EVIDENCE="$SUMAI_DEVICE_EVIDENCE" \
./scripts/promote-verified-candidate.sh
```

- [ ] **Step 4: Verify production independently**

Check exact 100% agent/web revisions, service accounts, immutable images, App Check settings, strict Gemini, Secret Manager reference, public web analysis disabled, `/health`, `/ready`, `/privacy`, `/support`, unauthenticated 401 before body intake, and a physical-device attested synthetic analysis.

- [ ] **Step 5: Record promotion and rollback evidence**

Store sanitized revisions, digests, timestamps, smoke status, and rollback predecessor names. Production PASS does not imply archive or upload PASS.

## Task 5: Create and inspect the distribution archive and export

**Files:**

- Verify: `ios/exportOptions.plist`
- Verify: `ios/SumaiGuard.xcodeproj/**`
- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Re-run all exact-SHA gates**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git ls-remote origin refs/heads/main
gh run list --workflow CI --commit "$(git rev-parse HEAD)" --limit 1 --json status,conclusion,url,headSha
PATH="/Users/zhanglonglong/Projects/apps/.venv/bin:$PATH" ./scripts/test_all.sh
python scripts/validate_ios_release.py
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

Expected: clean tracked state, local SHA equals remote main, exact-SHA CI success, all tests pass.

- [ ] **Step 2: Verify signing identities without exposing certificates**

Run:

```bash
security find-identity -v -p codesigning
```

Expected: a valid Apple Distribution identity for the intended team. Report only count, team identity match, and expiry suitability; do not paste certificate hashes into tracked docs.

- [ ] **Step 3: Archive in a protected temporary directory**

```bash
release_tmp="$(mktemp -d /tmp/sumaiguard-release.XXXXXX)"
chmod 700 "$release_tmp"
xcodebuild \
  -project ios/SumaiGuard.xcodeproj \
  -scheme SumaiGuard \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$release_tmp/SumaiGuard.xcarchive" \
  DEVELOPMENT_TEAM="$SUMAI_DEVELOPMENT_TEAM" \
  SUMAI_API_ORIGIN="$SUMAI_PRODUCTION_API_ORIGIN" \
  archive | tee "$release_tmp/archive.log"
```

- [ ] **Step 4: Inspect before export**

Verify bundle ID, version/build, display name, team, provisioning profile, production App Attest entitlement, minimum OS, iPhone-only family, icon, privacy manifest presence if required by dependencies, and embedded production origin. Scan for debug provider/token, loopback, `.invalid`, and development App Attest values.

- [ ] **Step 5: Export for App Store Connect**

`ios/exportOptions.plist` uses `method=app-store-connect`, `destination=export`, automatic signing, and the intended team. Run:

```bash
xcodebuild \
  -exportArchive \
  -archivePath "$release_tmp/SumaiGuard.xcarchive" \
  -exportPath "$release_tmp/export" \
  -exportOptionsPlist ios/exportOptions.plist | tee "$release_tmp/export.log"
```

Expected: export succeeds and produces one IPA plus Apple distribution logs. Archive PASS and Export PASS are recorded separately.

- [ ] **Step 6: Validate exported IPA**

Copy the IPA to another protected temporary directory, unzip read-only, repeat plist/entitlement/binary-string validation, and compute SHA-256. Record only build number, IPA hash, source SHA, archive timestamp, and validation PASS in the tracked gate.

## Task 6: Upload build 1 and verify processing/TestFlight

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Ask for explicit upload confirmation**

Present app record, provider, app name, version/build, source SHA, IPA hash, backend revisions, privacy/support URLs, archive/export results, and unresolved risks. Stop until the user authorizes upload of this exact IPA.

- [ ] **Step 2: Upload through Xcode Organizer or Transporter**

Use the authenticated Apple UI for the intended provider. Select the exact validated archive/IPA and keep symbols included. Do not enable automatic App Review submission or automatic release.

If using Xcode Organizer, choose `Distribute App -> App Store Connect -> Upload`, inspect every summary field, then upload. Store the local upload log in the protected temporary directory, not Git.

- [ ] **Step 3: Verify upload independently**

In App Store Connect, observe build `1` under version `1.0` and record upload time and processing state. Upload success means only transport acceptance.

- [ ] **Step 4: Wait for processing and resolve issues**

Observe `Processing` until the build becomes selectable or Apple shows a concrete error. Do not mark Processing PASS from an email alone. Fix warnings/errors by returning to the relevant implementation task and increment the build number if another binary is required; never replace evidence for build 1 with build 2 silently.

- [ ] **Step 5: Verify TestFlight on a physical iPhone**

Install the processed build through TestFlight. Confirm name/icon, launch, camera, `PhotosPicker`, consent cancellation, real App Attest production analysis with a synthetic image, result states, PDF share, privacy link, support link, accessibility basics, and content clearing. Record TestFlight PASS independently.

## Task 7: Complete metadata, privacy, review notes, and compliance answers

**Files:**

- Verify/update: `docs/app-store/app-description-ja.md`
- Verify/update: `docs/app-store/app-privacy-label-draft.md`
- Verify/update: `docs/app-store/app-review-notes.md`
- Verify: `docs/app-store/screenshots/ja-JP/6.9-inch/*.png`

- [ ] **Step 1: Enter version metadata**

Enter exact name, subtitle, description, keywords derived from the actual feature set, Lifestyle/Utilities categories, support URL, privacy URL, copyright owner, free price, Japan availability, and manual release.

- [ ] **Step 2: Upload and inspect screenshots**

Upload the five validated 6.9-inch Japanese screenshots in manifest order. Inspect App Store Connect previews for scaling, crop, text, sequence, and absence of private content.

- [ ] **Step 3: Complete conservative App Privacy answers**

Use the implemented/provider-observed contract:

- Tracking: No.
- Photos or Videos: collected for App Functionality; conservatively linked because a home photo can identify a household; not used for tracking.
- Diagnostics: operational metadata for App Functionality; unlinked; not used for tracking.
- App integrity/fraud prevention: Firebase App Check and Apple App Attest; no advertising/profile use.
- Privacy policy URL: exact public HTTPS page.
- `Data Not Collected`: not selected.

If App Store Connect taxonomy differs on submission day, map the same factual processing conservatively and record the exact selected labels in the draft before saving.

- [ ] **Step 4: Complete age rating and export compliance honestly**

Answer based on the binary: no violence, gambling, sexual content, user-generated content, medical treatment, unrestricted web access, or custom cryptography. For export compliance, answer from Apple's current encryption questions and standard HTTPS/Firebase use; do not guess an exemption code.

- [ ] **Step 5: Enter reviewer instructions**

Review notes state no account is needed, the flow is capture/picker -> consent -> analysis -> visible results -> three-tier advice -> text PDF, and a synthetic test photo may be used. They disclose App Check/App Attest, production endpoint availability, no persistence, visible-scope limitation, and professional-judgment disclaimer. Provide a monitored review contact without exposing it in Git if it is not the public support address.

- [ ] **Step 6: Select the exact processed build**

Attach version 1.0 build 1 and recheck its icon, version, privacy manifest notices, export compliance state, and TestFlight result. Saving metadata is not submission.

## Task 8: Submit to App Review with an explicit checkpoint

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Produce a pre-submission evidence table**

Show exact source SHA, CI URL, production revisions/digests, public URL results, App Attest physical-device result, archive/export/upload/processing/TestFlight states, selected build, metadata completeness, screenshot validation, privacy answers, age rating, export compliance, reviewer contact readiness, and known residual risks.

- [ ] **Step 2: Ask for explicit App Review submission confirmation**

Submission is an external action affecting Apple reviewers. Stop until the user confirms submission of version 1.0 build 1.

- [ ] **Step 3: Submit and capture the exact state**

Click `Add for Review`, recheck the submission summary, then `Submit for Review`. Record the exact App Store Connect state and UTC/JST observation time. Do not translate `Waiting for Review`, `In Review`, or `Pending Developer Release` into approval.

- [ ] **Step 4: Monitor and handle review truthfully**

For any rejection or metadata request, capture the exact guideline/reference, distinguish metadata-only from binary-required fixes, and propose the minimal correction. Do not change privacy wording, product scope, backend traffic, or binary behavior solely to get approval without re-running affected gates.

## Task 9: Verify approval, manually release, and confirm Japan storefront

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Observe approval separately**

Verify App Store Connect shows the exact approved version/build and a manual-release state such as `Pending Developer Release`. Check production health, support/privacy URLs, rollback evidence, App Attest, and TestFlight again. Approval does not authorize release by itself.

- [ ] **Step 2: Ask for explicit manual-release confirmation**

Present the exact approved build, current production revisions, live endpoint results, rollback readiness, Japan availability, and any unresolved risk. Stop until the user confirms the public release.

- [ ] **Step 3: Perform manual release**

Use App Store Connect's manual release action for version 1.0. Record the exact new state and time. Do not claim visibility while Apple propagation is incomplete.

- [ ] **Step 4: Verify the direct Japan storefront URL**

Open `https://apps.apple.com/jp/app/id${APP_STORE_ID}` in a signed-out/private browser and confirm name, icon, subtitle, screenshots, description, privacy link, compatibility, version 1.0, and download availability. Search ranking is not required; the direct page is.

- [ ] **Step 5: Run post-release privacy-safe production smoke**

Install from the Japan storefront or update from TestFlight to the public build. Use a synthetic image and verify App Attest-backed 200 response, cautious results, PDF share, no persisted content after reset/relaunch, and metadata-only logs. Do not use a real customer's home.

- [ ] **Step 6: Finalize evidence and rollback posture**

Record Storefront PASS and Production Smoke PASS separately, exact public URL, version/build, observation timestamps, production revisions, and rollback targets. Keep the prior revisions until the owner accepts the observation period; cleanup requires a separate reversible-operation review.

## Final verification and completion report

Run:

```bash
git diff --check
git status --short --branch
git rev-parse HEAD
git ls-remote origin refs/heads/main
gh run list --workflow CI --commit "$(git rev-parse HEAD)" --limit 1 --json status,conclusion,url,headSha
curl -fsS "$SUMAI_PRODUCTION_API_ORIGIN/health"
curl -fsS "$SUMAI_PRODUCTION_API_ORIGIN/ready"
curl -fsSI "$SUMAI_PUBLIC_WEB_ORIGIN/privacy"
curl -fsSI "$SUMAI_PUBLIC_WEB_ORIGIN/support"
```

The final report must list these states independently:

```text
Source / CI
Candidate deployment
Real-device App Attest
Production promotion
Archive
Export
Upload
Processing
TestFlight
Metadata and privacy
Submitted for Review
Approved
Manual release
Japan storefront
Post-release production smoke
```

For every unobserved state, write `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, or `SKIPPED` with the exact reason. Never convert a preceding PASS into a later gate's PASS.
