# SumaiGuard v1.0 App Store Release Gate

## Current-truth snapshot

Observed on 2026-08-10 JST. This record separates local source readiness,
Cloud Run release state, Apple distribution, review, approval, manual release,
and Japan storefront visibility. A PASS at one gate does not imply any later
gate has passed.

The release source was merged by PR #6 and is externally visible at exact
`main` SHA `a029ee9c60411fde992a5fd01f94a3bd3cdd6ab0`. Exact-head GitHub CI run
`31393786376` passed both backend and iOS jobs for that merge commit. The
candidate and real-device evidence below are bound to this same source SHA.

App Store Connect record `6799968189` now exists with the approved public name
`実家あんしんチェック`, primary language Japanese, bundle ID
`com.zll.sumaiguard`, SKU `SUMAIGUARD-IOS-1`, and unrestricted user access.
Version 1.0 is in `提出準備中`. Screenshots, app information, age rating,
Japan-only free availability, and the privacy-policy URL are saved. Version
metadata still requires an App Review phone number, and the completed privacy
answers remain unpublished pending the operator's legal attestation. No build,
review submission, review decision, release, or storefront visibility exists.

Apple Developer shows App Attest enabled for `com.zll.sumaiguard` and a valid
Apple Distribution identity is installed locally. No SumaiGuard App Store
provisioning profile is currently present in the developer portal, so archive
signing must create or install one before archive acceptance.

## Gate status

| Gate | Status | Current evidence and next acceptance boundary |
|---|---|---|
| Local source and listing assets | PASS | Two focused commits contain the Japanese listing, privacy disclosures, review notes, public privacy/support pages, five validated 1320×2868 screenshots, and a DEBUG-only screenshot harness. |
| Local verification | PASS | Backend: 588 passed. Release/native/script checks: 65 passed. Xcode tests: 168 passed, 0 failed, 1 physical-device-only test skipped in the simulator suite. Debug and Release simulator builds passed; the Release product contains no screenshot-harness marker. The separate physical-device test later passed. |
| App Store Connect record | PASS | App ID `6799968189`, version 1.0 `提出準備中`; record fields match the approved name, language, bundle ID, SKU, and access scope. |
| Apple capability and profile | IN PROGRESS | App Attest is enabled and the Apple Distribution identity exists. SumaiGuard has no App Store provisioning profile yet; create/install it during the archive-signing step. |
| Source push | PASS | PR #6 merged the release branch to remote `main`; exact release SHA is `a029ee9c60411fde992a5fd01f94a3bd3cdd6ab0`. |
| Exact-head CI | PASS | GitHub Actions run `31393786376` passed backend and iOS jobs for exact merged `main` SHA `a029ee9c60411fde992a5fd01f94a3bd3cdd6ab0`. |
| Cloud Build candidate | PASS | Cloud Build `1067d847-0540-48f4-9fac-874e76a2b68c` succeeded. Agent `sumai-agent-a029ee9-1067` and web `sumai-web-a029ee9-1067-can` use the dedicated runtime accounts, passed safe probes, and remain at 0% traffic. Sanitized evidence is stored at `gs://zhang23-23-sumai-release-evidence/candidates/a029ee9c60411fde992a5fd01f94a3bd3cdd6ab0/1067d847-0540-48f4-9fac-874e76a2b68c.json`. |
| Real-device App Attest | PASS | On 2026-08-10 at `13:57:36Z`, the paired physical iPhone completed the selected `AppAttestProvider` round trip against `sumai-agent-a029ee9-1067`: 1 test, 0 failures, HTTP 200. The evidence file SHA-256 is `2549b9e09f40aee2d1607b9b20644ef1175c87c18e90728b8e19ccd2050e58a9`; it contains no token, photo, response body, or device identifier. |
| Production promotion | AWAITING CHECKPOINT | The exact candidate/device dry-run passed with `validation=PASS` and `mutation=NONE`. Current production remains on the predecessor revisions. Apply only after explicit promotion confirmation and a final no-drift check. |
| Archive and signing | NOT STARTED | No accepted release archive exists. Record source SHA, version/build, profile, signing result, and export validation. |
| IPA upload and processing | AWAITING CHECKPOINT | No build has been uploaded for App ID `6799968189`. Upload requires a separate explicit confirmation after archive acceptance. |
| Metadata and privacy answers | IN PROGRESS | Five screenshots, app information, age rating, Japan-only free availability, and privacy-policy URL are saved. Version metadata cannot be saved until an App Review phone number is supplied. Privacy answers are completed but not published because final publication is an operator attestation. |
| App Review submission | AWAITING CHECKPOINT | Submission requires an accepted processed build, completed metadata/privacy/export answers, manual-release selection, and separate explicit confirmation. |
| App Review approval | NOT STARTED | Approval is independent of submission and upload. |
| Manual release | AWAITING CHECKPOINT | Manual release is selected on the unsaved version page; save it after the required review phone is supplied. The final release action still requires explicit authorization after approval. |
| Japan storefront visibility | NOT STARTED | Record the public URL, observed version/build, Japan storefront, and observation time only after visibility is confirmed. |

## Known live-state evidence before mutation

- Production agent traffic was 100% on `sumai-agent-5a44215-738e`.
- Production web traffic was 100% on `sumai-web-5a44215-738e-fin`.
- Earlier 0%-traffic candidates were `sumai-agent-a95c4ac-774c` and
  `sumai-web-a95c4ac-774c-can`; they predate the two App Store commits and are
  not candidates for the exact release SHA.
- The earlier production agent returned 404 for `/health` and `/ready`; the
  earlier production web returned 404 for `/privacy` and `/support`.
- The earlier candidates returned 200 for `/health`, `/ready`, `/privacy`, and
  `/support` as applicable. These observations do not authorize promotion.
- Exact-SHA candidates `sumai-agent-a029ee9-1067` and
  `sumai-web-a029ee9-1067-can` now exist at 0% traffic. `/health`, `/ready`,
  `/`, `/privacy`, and `/support` returned 200 as applicable.
- After candidate creation, production remained 100% on
  `sumai-agent-5a44215-738e` and `sumai-web-5a44215-738e-fin`; candidate
  evidence records `production_traffic_changed: false`.

## Acceptance rules

- **Source** requires a reviewed, focused diff, clean working tree, exact pushed
  SHA, and successful exact-head CI.
- **Candidate** requires immutable digests, 0%-traffic revisions, unchanged
  predecessors, strict Gemini, App Check, web analysis disabled, safe probes,
  and sanitized evidence.
- **Device** requires current real-device `AppAttestProvider` evidence bound to
  the exact candidate agent revision. Simulator, browser, curl, historic phone
  testing, or skipped evidence does not pass.
- **Promotion** requires a passing dry-run followed by explicit authorization,
  ownership-preserving `resourceVersion` compare-and-swap, stable probes, and
  rollback readiness.
- **Archive/upload** requires a distribution-signed archive from the exact
  source, valid profile/export checks, separate upload authorization, and
  successful App Store Connect processing.
- **Review** requires complete metadata, privacy and export declarations,
  screenshots, review contact/notes, accepted build, manual-release selection,
  and separate submission authorization.
- **Public release** requires Apple approval followed by explicit manual-release
  authorization. Storefront visibility is verified separately after propagation.

## Current decision

The source, exact-head CI, 0%-traffic candidates, safe endpoint probes, and
real-device App Attest gate are complete. Public release is not yet complete.
The next operator inputs are an App Review phone number, confirmation to publish
the App Store privacy answers, and a separate explicit production-promotion
confirmation. Archive/signing, IPA upload, App Review submission, approval,
manual release, propagation, and Japan storefront visibility remain distinct
later gates.
