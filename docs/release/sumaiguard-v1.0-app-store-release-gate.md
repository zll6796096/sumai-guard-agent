# SumaiGuard v1.0 App Store Release Gate

## Current-truth snapshot

Cloud Run control-plane and public endpoints were rechecked on 2026-08-11 JST.
Apple distribution state below is the last verified 2026-08-10 state and was
not refreshed during this release-chain remediation. This record separates
local source readiness, Cloud Run release state, Apple distribution, review,
approval, manual release, and Japan storefront visibility. A PASS at one gate
does not imply any later gate has passed.

The release application source was merged by PR #7 and is externally visible
at exact `main` SHA `7bcdbb18321c4c31aa749170f57584024057e924`.
Exact-head GitHub CI run `31396624070` passed both backend and iOS jobs for that
merge commit. The candidate, real-device, promotion, signed IPA, and upload
evidence below are bound to this same release application source.

App Store Connect record `6799968189` now exists with the approved public name
`実家あんしんチェック`, primary language Japanese, bundle ID
`com.zll.sumaiguard`, SKU `SUMAIGUARD-IOS-1`, and unrestricted user access.
Version 1.0 is in `提出準備中`. Screenshots, app information, age rating,
Japan-only free availability, and the privacy-policy URL are saved. Version
metadata still requires an App Review phone number, and the completed privacy
answers remain unpublished pending the operator's legal attestation. Build 1
was uploaded and was last observed in Apple processing; it was not yet attached
to version 1.0. No review submission, review decision, release, or storefront
visibility was verified.

Apple Developer shows App Attest enabled for `com.zll.sumaiguard` and a valid
Apple Distribution identity and App Store provisioning profile were used to
export the validated Build 1 IPA.

## Gate status

| Gate | Status | Current evidence and next acceptance boundary |
|---|---|---|
| Local source and listing assets | PASS | Two focused commits contain the Japanese listing, privacy disclosures, review notes, public privacy/support pages, five validated 1320×2868 screenshots, and a DEBUG-only screenshot harness. |
| Local verification | PASS | Backend: 588 passed. Release/native/script checks: 65 passed. Xcode tests: 168 passed, 0 failed, 1 physical-device-only test skipped in the simulator suite. Debug and Release simulator builds passed; the Release product contains no screenshot-harness marker. The separate physical-device test later passed. |
| App Store Connect record | PASS | App ID `6799968189`, version 1.0 `提出準備中`; record fields match the approved name, language, bundle ID, SKU, and access scope. |
| Apple capability and profile | PASS | App Attest is enabled; the distribution identity and App Store profile produced a validated distribution-signed Build 1 IPA. |
| Source push | PASS | PR #7 merged the release branch to remote `main`; exact release application source is `7bcdbb18321c4c31aa749170f57584024057e924`. |
| Exact-head CI | PASS | GitHub Actions run `31396624070` passed backend and iOS jobs for exact merged `main` SHA `7bcdbb18321c4c31aa749170f57584024057e924`. |
| Cloud Build candidate | PASS | Regional Cloud Build `b6596ba5-d920-461a-8361-14baddddfa5b` succeeded. Agent `sumai-agent-7bcdbb1-b659` and web `sumai-web-7bcdbb1-b659-can` used the dedicated runtime accounts, passed safe probes, and were both at 0% when sanitized evidence was written with `production_traffic_changed: false`. The tracked evidence URI is redacted as `gs://<project-id>-sumai-release-evidence/candidates/7bcdbb18321c4c31aa749170f57584024057e924/b6596ba5-d920-461a-8361-14baddddfa5b.json`. |
| Real-device App Attest | PASS | The paired physical iPhone completed the selected `AppAttestProvider` round trip against `sumai-agent-7bcdbb1-b659`: 1 test, 0 failures, HTTP 200. The sanitized device evidence SHA-256 is `f75037731da65d007687132fef7246bfd6f4245c852c5c2c31d0b083c8c69555`; it contains no token, photo, response body, or device identifier. |
| Production promotion | PASS | The exact candidate/device dry-run passed with `validation=PASS` and `mutation=NONE`; the separately authorized apply produced promotion evidence SHA-256 `05b5de9c01b89cc6b5c645bce693ac62913f5d4340ff79761b0d160365c3899b`. Fresh inspection shows agent `sumai-agent-7bcdbb1-b659` and web `sumai-web-final-7bcdbb1-b659-58e1e1b75e` at 100%, with all required public probes passing. |
| Archive and signing | PASS | The exact-source distribution-signed Build 1 IPA passed release, signing, entitlement, profile, and placeholder checks; its SHA-256 is `c2d191901e57f87611f1cdab1e1e4713b88680287ccc0f1f23b987934901a0f6`. |
| IPA upload and processing | IN PROGRESS | Apple accepted the Build 1 upload and it was last observed processing. Processing completion, build attachment, TestFlight availability, and review readiness were not reverified here. |
| Metadata and privacy answers | IN PROGRESS | Five screenshots, app information, age rating, Japan-only free availability, and privacy-policy URL are saved. Version metadata cannot be saved until an App Review phone number is supplied. Privacy answers are completed but not published because final publication is an operator attestation. |
| App Review submission | AWAITING CHECKPOINT | Submission requires an accepted processed build, completed metadata/privacy/export answers, manual-release selection, and separate explicit confirmation. |
| App Review approval | NOT STARTED | Approval is independent of submission and upload. |
| Manual release | AWAITING CHECKPOINT | Manual release is selected on the unsaved version page; save it after the required review phone is supplied. The final release action still requires explicit authorization after approval. |
| Japan storefront visibility | NOT STARTED | Record the public URL, observed version/build, Japan storefront, and observation time only after visibility is confirmed. |

## Known live-state evidence

- Candidate build evidence proves that production stayed on
  `sumai-agent-5a44215-738e` and `sumai-web-5a44215-738e-fin` while the exact
  `7bcdbb1` candidates were created at 0%.
- The later promotion moved agent production to `sumai-agent-7bcdbb1-b659` and
  web production to `sumai-web-final-7bcdbb1-b659-58e1e1b75e`.
- On 2026-08-11, each service had exactly one 100% revision, the dedicated
  service-account hashes remained distinct, and agent `/health` and `/ready`
  plus web `/`, `/ready`, `/privacy`, and `/support` returned 200.
- The failed GitHub Actions run `31394541871` stopped before checkout or Cloud
  Build because keyless repository configuration was absent. It is not success
  evidence and is separate from the later successful regional Cloud Build.

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

The release application source, exact-head CI, candidate build, real-device App
Attest, production promotion, signed IPA, and upload transport are complete for
exact SHA `7bcdbb18321c4c31aa749170f57584024057e924`. Public release is not yet
complete. Build processing/attachment, metadata and privacy publication, App
Review submission, approval, manual release, propagation, and Japan storefront
visibility remain distinct later gates. Release-chain tooling corrections after
this SHA require their own reviewed CI and candidate orchestration evidence;
they do not retroactively change the Build 1 application source.
