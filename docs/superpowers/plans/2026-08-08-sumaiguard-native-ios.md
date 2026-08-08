# SumaiGuard Native iOS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native, Japanese, iPhone-only `実家あんしんチェック` app that obtains per-image consent, sends one sanitized photo with Firebase App Check/App Attest, renders cautious visible-risk results, and creates a text-only advice PDF without retaining user content.

**Architecture:** A single `AppFlowCoordinator` owns the `capture -> consent -> processing -> result -> advice` state machine and all request cancellation. Protocol-backed services isolate image sanitization, App Check, multipart transport, and local PDF generation. Release builds use Firebase App Attest; explicit Debug builds use Firebase's debug provider only. Views remain declarative and never initiate transport directly.

**Tech Stack:** Swift 6, SwiftUI, PhotosUI, AVFoundation, UIKit/CoreGraphics/ImageIO, PDFKit/UIGraphicsPDFRenderer, URLSession, XCTest, XcodeGen 2.45.4, Firebase iOS SDK 12.17.0 through Swift Package Manager, iOS 17+.

---

## Scope and guardrails

- Product name: `実家あんしんチェック`; home-screen name: `実家チェック`.
- Bundle ID: `com.zll.sumaiguard`; iPhone only; portrait; iOS 17.0 minimum.
- Native SwiftUI only; no `WKWebView` product wrapper.
- No account, history, database, analytics, ads, payments, push notifications, or persistent user content.
- No request occurs before fresh per-image consent; every retry returns to consent.
- Both client and server remove metadata and enforce image limits.
- Release uses `AppAttestProvider`; simulator/CI may use `AppCheckDebugProviderFactory` only under `#if DEBUG`.
- No real home photo enters tests, screenshots, fixtures, Git, logs, or release evidence.
- The public API origin is supplied by Release configuration and must be `https`, non-loopback, and host-only.
- Do not read, modify, stage, or delete `docs/preconsultation/`.

## Acceptance evidence

- XcodeGen regenerates a tracked project without semantic diff.
- All simulator tests pass with zero hidden skips.
- Consent cancellation and processing cancellation produce zero/aborted requests and clear content.
- Sanitized output is upright JPEG, at most 1600 px on the long side, at most 10 MiB, and contains no EXIF/GPS metadata.
- Release transport sends App Check only as `X-Firebase-AppCheck`, uses an ephemeral session, and decodes stable errors without leaking provider detail.
- Applicable, no-findings, not-applicable, quota, unavailable, invalid-image, and network states render correctly.
- Generated PDF is Japanese, text-only, contains the approved disclaimer, and contains no image/debug/token data.
- Release archive contains the production App Attest entitlement and contains no debug provider/token marker.
- A physical iPhone obtains a real App Attest-backed token and receives 200 from the exact Cloud Run candidate.

## Task 1: Scaffold the reproducible Xcode project and release configuration

**Files:**

- Create: `ios/project.yml`
- Create: `ios/exportOptions.plist`
- Create: `ios/SumaiGuard/Info.plist`
- Create: `ios/SumaiGuard/SumaiGuard.entitlements`
- Create: `ios/SumaiGuard/Config/Debug.xcconfig`
- Create: `ios/SumaiGuard/Config/Release.xcconfig`
- Create: `ios/SumaiGuard/App/SumaiGuardApp.swift`
- Create: `ios/SumaiGuardTests/ProjectContractTests.swift`
- Generate and track: `ios/SumaiGuard.xcodeproj/**`

- [ ] **Step 1: Write the project contract test first**

Test exact bundle metadata and configuration:

```swift
final class ProjectContractTests: XCTestCase {
    func testPublicIdentityIsStable() {
        let bundle = Bundle.main
        XCTAssertEqual(bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String, "実家チェック")
        XCTAssertEqual(bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String, "1.0")
        XCTAssertEqual(bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String, "1")
    }
}
```

- [ ] **Step 2: Create `project.yml` with pinned dependencies**

Use this target contract:

```yaml
name: SumaiGuard
options:
  minimumXcodeGenVersion: 2.45.4
settings:
  base:
    SWIFT_VERSION: 6.0
    IPHONEOS_DEPLOYMENT_TARGET: 17.0
    TARGETED_DEVICE_FAMILY: 1
    PRODUCT_BUNDLE_IDENTIFIER: com.zll.sumaiguard
    MARKETING_VERSION: 1.0
    CURRENT_PROJECT_VERSION: 1
packages:
  Firebase:
    url: https://github.com/firebase/firebase-ios-sdk.git
    exactVersion: 12.17.0
targets:
  SumaiGuard:
    type: application
    platform: iOS
    sources: [SumaiGuard]
    dependencies:
      - package: Firebase
        product: FirebaseAppCheck
      - package: Firebase
        product: FirebaseCore
  SumaiGuardTests:
    type: bundle.unit-test
    platform: iOS
    sources: [SumaiGuardTests]
    dependencies:
      - target: SumaiGuard
```

Add per-configuration xcconfig files, Info.plist, entitlements, test host, portrait orientation, camera usage text, and no photo-library usage key because `PhotosPicker` does not require full-library access.

- [ ] **Step 3: Define safe API origin injection**

`Release.xcconfig` contains only a non-secret build setting:

```text
SUMAI_API_ORIGIN = https:/$()/invalid.invalid
```

The committed invalid origin makes accidental release fail closed. The archive command must override `SUMAI_API_ORIGIN` with the verified production host. `Info.plist` maps it to `SUMAI_API_ORIGIN`; no API key or token is stored in plist or xcconfig.

- [ ] **Step 4: Configure production App Attest entitlement**

`SumaiGuard.entitlements` contains:

```xml
<key>com.apple.developer.devicecheck.appattest-environment</key>
<string>production</string>
```

The app has no keychain-sharing, push, associated-domain, iCloud, health, location, contact, or background-mode entitlement.

- [ ] **Step 5: Generate and run the first build**

Run:

```bash
cd ios
xcodegen generate
xcodebuild -project SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```

Expected: build succeeds after the minimal app entry exists.

- [ ] **Step 6: Verify deterministic generation and commit**

Run:

```bash
cd ios
xcodegen generate
git diff --exit-code -- SumaiGuard.xcodeproj
cd ..
git add ios/project.yml ios/exportOptions.plist ios/SumaiGuard ios/SumaiGuardTests/ProjectContractTests.swift ios/SumaiGuard.xcodeproj
git commit -m "build: scaffold native SumaiGuard iOS app"
```

## Task 2: Implement exact Codable response and stable client errors

**Files:**

- Create: `ios/SumaiGuard/Models/AnalysisResponse.swift`
- Create: `ios/SumaiGuard/Models/APIError.swift`
- Create: `ios/SumaiGuardTests/AnalysisResponseTests.swift`
- Create: `ios/SumaiGuardTests/Fixtures/analysis-applicable.json`
- Create: `ios/SumaiGuardTests/Fixtures/analysis-not-applicable.json`
- Create: `ios/SumaiGuardTests/Fixtures/error-app-check.json`

- [ ] **Step 1: Add fictional JSON fixtures from the Python contract**

The applicable fixture must include every public field from `AnalysisResponse`, normalized bounding boxes, all three action arrays, both base64 image strings using a synthetic 1x1 image, report strings, versions, and `stage_timings_ms`. The not-applicable fixture must use `room_type: auto`, low risk, empty findings/actions, and a cautious Japanese reason.

- [ ] **Step 2: Write RED decoding tests**

```swift
func testDecodesApplicableResponseExactly() throws {
    let response = try JSONDecoder.sumai.decode(
        AnalysisResponse.self,
        from: fixture("analysis-applicable")
    )
    XCTAssertEqual(response.actionPlan.familyNoCost.first?.tier, .familyNoCost)
    XCTAssertEqual(response.stageTimingsMS["total"], 120)
    XCTAssertFalse(response.isNotApplicable)
}

func testRejectsUnknownActionTier() {
    XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: malformedTierFixture))
}
```

- [ ] **Step 3: Implement exact typed models**

Use `Decodable`, explicit `CodingKeys`, `Sendable`, and enums for `roomType`, `overallRiskLevel`, `tier`, and `costLevel`. Preserve every field documented in `apps/sumai_agent/app/models.py`; do not use `[String: Any]`.

Map stable server errors only:

```swift
enum APIError: Error, Equatable, Sendable {
    case invalidImage
    case appCheckInvalid
    case imageTooLarge
    case serviceLimited
    case geminiUnavailable
    case internalError
    case invalidResponse
    case network
    case cancelled
}
```

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:SumaiGuardTests/AnalysisResponseTests test
```

Then:

```bash
git add ios/SumaiGuard/Models ios/SumaiGuardTests/AnalysisResponseTests.swift ios/SumaiGuardTests/Fixtures
git commit -m "feat: model the native analysis contract"
```

## Task 3: Sanitize image pixels before consented upload

**Files:**

- Create: `ios/SumaiGuard/Services/ImageSanitizer.swift`
- Create: `ios/SumaiGuardTests/ImageSanitizerTests.swift`
- Create: `ios/SumaiGuardTests/Fixtures/synthetic-orientation-gps.jpg`

- [ ] **Step 1: Generate a synthetic metadata fixture**

Create the fixture from colored geometric shapes only. It may contain fake GPS metadata (`0,0`) and an orientation tag solely to test removal; it must contain no real photo or personal content.

- [ ] **Step 2: Write RED tests**

Test:

```swift
func testNormalizesOrientationAndLimitsLongestSideTo1600() async throws
func testOutputIsJPEGAndContainsNoEXIFOrGPS() async throws
func testRejectsUndecodableBytes() async
func testRejectsOutputOverTenMiB() async
func testCancellationDoesNotReturnBytes() async
```

Inspect output properties with `CGImageSourceCopyPropertiesAtIndex`; assert GPS and EXIF dictionaries are absent.

- [ ] **Step 3: Implement an actor-based sanitizer**

```swift
actor ImageSanitizer {
    static let maxLongSide = 1_600
    static let maxBytes = 10 * 1_024 * 1_024

    func sanitize(_ source: Data) throws -> SanitizedImage {
        try Task.checkCancellation()
        // Decode pixels, apply source orientation, scale once, render into a new
        // RGB context, and encode JPEG from the new pixels with no metadata.
    }
}
```

Use `CGImageSourceCreateWithData`, apply orientation into a fresh context, and write with `CGImageDestinationCreateWithData` using only lossy quality and pixel dimensions. Never pass source property dictionaries to the destination.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:SumaiGuardTests/ImageSanitizerTests test
```

Then stage only the named service, test, and synthetic fixture and commit:

```bash
git commit -m "feat: sanitize native image uploads"
```

## Task 4: Bootstrap Firebase App Check and implement ephemeral transport

**Files:**

- Create: `ios/SumaiGuard/Services/AppCheckBootstrap.swift`
- Create: `ios/SumaiGuard/Services/APIClient.swift`
- Create: `ios/SumaiGuardTests/AppCheckBootstrapTests.swift`
- Create: `ios/SumaiGuardTests/APIClientTests.swift`

- [ ] **Step 1: Write RED provider-selection and request tests**

Cover:

```swift
func testReleaseBuildSelectsAppAttestProvider()
func testDebugBuildSelectsDebugProvider()
func testInvalidOrLoopbackReleaseOriginIsRejected()
func testRequestUsesEphemeralSessionAndNoCache()
func testAppCheckTokenAppearsOnlyInHeader()
func testMultipartContainsOneJPEGAndAutoRoomHint()
func testServerErrorMapsFromStableCodeOnly()
func testCancellationCancelsURLTask()
```

Inject `AppCheckTokenProviding` and `URLProtocol` doubles. Assert the token is absent from URL, query, body, logs, and returned errors.

- [ ] **Step 2: Initialize the provider before Firebase**

```swift
enum AppCheckBootstrap {
    static func configure() {
#if DEBUG
        AppCheck.setAppCheckProviderFactory(AppCheckDebugProviderFactory())
#else
        AppCheck.setAppCheckProviderFactory(SumaiAppCheckProviderFactory())
#endif
        FirebaseApp.configure()
    }
}

final class SumaiAppCheckProviderFactory: NSObject, AppCheckProviderFactory {
    func createProvider(with app: FirebaseApp) -> AppCheckProvider? {
        AppAttestProvider(app: app)
    }
}
```

Call this once from a UIKit app delegate before any Firebase service use, then attach that delegate to SwiftUI:

```swift
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        AppCheckBootstrap.configure()
        return true
    }
}

@main
struct SumaiGuardApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    var body: some Scene { WindowGroup { RootView() } }
}
```

Set `FirebaseAppDelegateProxyEnabled` to `NO` in `Info.plist`. Do not print debug tokens in app code; the developer obtains simulator registration material only from the Xcode debug console during controlled setup.

- [ ] **Step 3: Validate the production origin**

`APIOrigin` must reject invalid syntax, non-HTTPS Release origins, credentials in URLs, query/fragment, loopback, raw IPs, and path prefixes. The accepted origin has scheme and host only; `APIClient` appends `/api/v1/analyze`.

- [ ] **Step 4: Implement token and multipart transport**

```swift
protocol AppCheckTokenProviding: Sendable {
    func token() async throws -> String
}

protocol Analyzing: Sendable {
    func analyze(image: SanitizedImage, roomHint: String) async throws -> AnalysisResponse
}
```

Use `URLSessionConfiguration.ephemeral`, `urlCache = nil`, `requestCachePolicy = .reloadIgnoringLocalCacheData`, `timeoutIntervalForRequest = 120`, `Cache-Control: no-store`, and `X-Firebase-AppCheck`. Build multipart data in memory, set the token header immediately before sending, and clear local references after completion.

- [ ] **Step 5: Run GREEN and commit**

Run:

```bash
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:SumaiGuardTests/AppCheckBootstrapTests -only-testing:SumaiGuardTests/APIClientTests test
```

Then commit:

```bash
git add ios/SumaiGuard/Services/AppCheckBootstrap.swift ios/SumaiGuard/Services/APIClient.swift ios/SumaiGuardTests/AppCheckBootstrapTests.swift ios/SumaiGuardTests/APIClientTests.swift
git commit -m "feat: add App Check protected native transport"
```

## Task 5: Implement the consent-owned flow coordinator

**Files:**

- Create: `ios/SumaiGuard/ViewModels/AppFlowCoordinator.swift`
- Create: `ios/SumaiGuardTests/AppFlowCoordinatorTests.swift`

- [ ] **Step 1: Write the complete RED state table**

```swift
@MainActor
final class AppFlowCoordinatorTests: XCTestCase {
    func testSelectedImageMovesToConsentWithoutRequest() async
    func testCancelConsentClearsImageAndSendsZeroRequests() async
    func testAgreeSanitizesThenSendsExactlyOneRequest() async
    func testCancelProcessingCancelsRequestAndClearsState() async
    func testRetryReturnsToConsentBeforeAnotherRequest() async
    func testNotApplicableNeverShowsAdvice() async
    func testNoFindingsNeverClaimsSafe() async
    func testReturnHomeClearsImageResponsePDFAndTask() async
}
```

- [ ] **Step 2: Implement explicit states and events**

```swift
enum AppScreen: Equatable {
    case capture
    case consent(SelectedImage)
    case processing(SelectedImage)
    case result(AnalysisResponse)
    case advice(AnalysisResponse)
    case noFindings(AnalysisResponse)
    case notApplicable(String)
    case error(UserFacingError)
}
```

Keep selected source data, sanitized data, response, PDF, and active `Task` private to the coordinator. `cancelConsent`, `cancelProcessing`, and `returnHome` overwrite those references with `nil`.

- [ ] **Step 3: Enforce renewed consent on retry**

`retry()` transitions from error to consent using the still-selected preview only if the user has not returned home. It must not call analyze. `agreeAndAnalyze()` is the sole entry point that may sanitize and request.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:SumaiGuardTests/AppFlowCoordinatorTests test
```

Then commit the two named files with `feat: add consent-owned native flow`.

## Task 6: Build capture and consent screens

**Files:**

- Create: `ios/SumaiGuard/Views/CaptureView.swift`
- Create: `ios/SumaiGuard/Views/CameraPicker.swift`
- Create: `ios/SumaiGuard/Views/ConsentView.swift`
- Create: `ios/SumaiGuard/Views/PrivacySheet.swift`
- Create: `ios/SumaiGuard/Views/RootView.swift`
- Create: `ios/SumaiGuardTests/CaptureConsentViewTests.swift`

- [ ] **Step 1: Write RED view-model accessibility contracts**

Assert the rendered accessibility tree/model exposes Japanese labels for camera, `PhotosPicker`, privacy, consent, cancellation, and these disclosures:

- visible-risk extraction purpose;
- SumaiGuard Cloud Run and Google Gemini by Google LLC;
- private context may appear in a home photo;
- SumaiGuard application does not save the photo;
- refusal/cancel sends no request;
- medical, care, insurance, and construction non-judgment boundary.

- [ ] **Step 2: Implement native acquisition**

Use `PhotosPicker(selection:matching: .images)` and `UIImagePickerController` with `.camera`. Check camera availability and authorization at action time. Do not request full-library permission and do not write captured images to the photo library.

- [ ] **Step 3: Implement the selected brand**

Use semantic colors backed by asset variants: forest green `#173D32`, cream `#F6F0E2`, warm gold `#C6923E`, system background, and accessible high-contrast text. Avoid gradients, scanning rings, AI sparkle imagery, medical symbols, and fear copy.

- [ ] **Step 4: Verify and commit**

Run focused tests and a simulator build, then commit the named views/tests with `feat: add native capture and consent`.

## Task 7: Build processing, result, advice, and terminal states

**Files:**

- Create: `ios/SumaiGuard/Views/ProcessingView.swift`
- Create: `ios/SumaiGuard/Views/ResultView.swift`
- Create: `ios/SumaiGuard/Views/AdviceView.swift`
- Create: `ios/SumaiGuard/Views/NoFindingsView.swift`
- Create: `ios/SumaiGuard/Views/NotApplicableView.swift`
- Create: `ios/SumaiGuard/Views/ErrorView.swift`
- Create: `ios/SumaiGuard/Views/RemoteResultImage.swift`
- Create: `ios/SumaiGuardTests/ResultStateTests.swift`

- [ ] **Step 1: Write RED content and state tests**

Assert:

- processing has indeterminate progress and cancel, never a fabricated percentage;
- result heading is `写真で確認できた注意箇所`;
- evidence and improvement images are vertically stacked;
- confidence is labeled as an uncalibrated model score, not probability of harm;
- limitations are consolidated;
- no-findings says visible obvious candidates were not confirmed and never says `安全です`;
- not-applicable hides findings/actions and asks for another suitable photo;
- error states map from `APIError` to cautious Japanese text with no raw body.

- [ ] **Step 2: Render base64 images without persistence**

Decode into memory, validate image bytes, render SwiftUI `Image`, and release decoded data when the view/coordinator resets. Never write result images to caches, files, photo library, or `UserDefaults`.

- [ ] **Step 3: Render exactly three action tiers**

Use the fixed headings:

```text
家族で今日できること
ケアマネ・福祉用具に相談
専門施工・現地確認
```

Do not reorder action items across tiers or infer new purchase/construction advice client-side.

- [ ] **Step 4: Verify and commit**

Run `ResultStateTests`, a full simulator test, and commit with `feat: render native safety results`.

## Task 8: Generate and share a text-only advice PDF on device

**Files:**

- Create: `ios/SumaiGuard/Services/SafetyPDFRenderer.swift`
- Create: `ios/SumaiGuard/Views/ShareSheet.swift`
- Create: `ios/SumaiGuardTests/SafetyPDFRendererTests.swift`

- [ ] **Step 1: Write RED PDF inspection tests**

Generate a PDF from fictional Japanese actions, inspect with PDFKit, and assert:

```swift
XCTAssertTrue(text.contains("家族で今日できること"))
XCTAssertTrue(text.contains("医療・介護認定・保険・法令適合・施工可否・見積もり"))
XCTAssertFalse(text.contains("analysis_id"))
XCTAssertEqual(pdfImageObjectCount(data), 0)
```

Also assert the PDF contains no base64 prefix, model name, token marker, timing key, request ID, or response image.

- [ ] **Step 2: Implement local rendering**

Use `UIGraphicsPDFRenderer`; render title, visible-risk basis, the three action sections, and the approved disclaimer. Accept only the text fields required for the PDF, not the complete `AnalysisResponse`.

- [ ] **Step 3: Share and delete temporary output**

Prefer an in-memory `Data` item provider. If the share sheet requires a temporary file, create it under a per-share temporary directory, remove it when the activity controller completes, and clear it on `returnHome`.

- [ ] **Step 4: Verify and commit**

Run PDF tests and commit with `feat: add private native advice PDF`.

## Task 9: Finish assets, accessibility, and icon validation

**Files:**

- Create: `ios/SumaiGuard/Resources/Assets.xcassets/AppIcon.appiconset/**`
- Create: `ios/SumaiGuard/Resources/Assets.xcassets/BrandForest.colorset/Contents.json`
- Create: `ios/SumaiGuard/Resources/Assets.xcassets/BrandCream.colorset/Contents.json`
- Create: `ios/SumaiGuard/Resources/Assets.xcassets/BrandGold.colorset/Contents.json`
- Create: `ios/SumaiGuardTests/AccessibilityContractTests.swift`
- Create: `scripts/validate_ios_release.py`
- Create: `scripts/test_validate_ios_release.py`

- [ ] **Step 1: Write RED release-validator tests**

The Python validator must fail on:

- absent/transparent/incorrect-size 1024x1024 icon;
- alpha channel in App Store icon;
- missing production App Attest entitlement;
- `AppCheckDebugProviderFactory`, `FIRAppCheckDebugToken`, loopback, `.invalid`, or cleartext HTTP in Release sources/settings;
- bundle/name/version/build mismatch between `project.yml`, plist, and generated project;
- iPad target or deployment target below 17.0;
- unpinned Firebase dependency.

- [ ] **Step 2: Produce the selected icon**

Create an opaque 1024x1024 PNG: dark forest-green field, cream home/check symbol, small warm-gold doorway accent. It must have no text, medical cross, person silhouette, robot, or sparkle. Render and inspect 1024, 180, 120, 60, and 40 px previews before acceptance.

- [ ] **Step 3: Add accessibility acceptance**

Verify Dynamic Type through accessibility sizes, VoiceOver labels/order, Reduce Motion behavior, light/dark variants, color contrast, and minimum 44x44 point controls. Snapshot or UI tests must use synthetic fixtures and Japanese locale.

- [ ] **Step 4: Run validator and full simulator gate**

Run:

```bash
python -m pytest scripts/test_validate_ios_release.py -v
python scripts/validate_ios_release.py
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

Expected: zero failures and zero skipped release tests.

- [ ] **Step 5: Commit assets and validation**

Stage only `ios/**` and the two validator files; verify the protected docs remain unstaged; commit with `feat: finish SumaiGuard release presentation`.

## Task 10: Wire CI and validate the Release archive locally

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] **Step 1: Add an iOS CI job**

Use a macOS runner, Xcode project, exact iPhone simulator destination, and these gates:

```yaml
- run: brew install xcodegen
- run: cd ios && xcodegen generate && git diff --exit-code -- SumaiGuard.xcodeproj
- run: python scripts/validate_ios_release.py --allow-invalid-api-origin-for-ci
- run: xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

CI does not possess distribution signing material and does not upload an app.

- [ ] **Step 2: Create a temporary signed archive with verified origin**

After the production origin is known:

```bash
archive_dir="$(mktemp -d /tmp/sumaiguard-archive.XXXXXX)"
xcodebuild \
  -project ios/SumaiGuard.xcodeproj \
  -scheme SumaiGuard \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$archive_dir/SumaiGuard.xcarchive" \
  DEVELOPMENT_TEAM="$SUMAI_DEVELOPMENT_TEAM" \
  SUMAI_API_ORIGIN="$SUMAI_PRODUCTION_API_ORIGIN" \
  archive
```

Do not delete the archive until entitlements and metadata have been inspected and the user authorizes cleanup.

- [ ] **Step 3: Inspect the archive**

Run:

```bash
codesign -d --entitlements :- "$archive_dir/SumaiGuard.xcarchive/Products/Applications/SumaiGuard.app"
plutil -p "$archive_dir/SumaiGuard.xcarchive/Info.plist"
strings "$archive_dir/SumaiGuard.xcarchive/Products/Applications/SumaiGuard.app/SumaiGuard" | rg 'AppCheckDebug|FIRAppCheckDebugToken|localhost|example.invalid' && exit 1 || true
```

Expected: production App Attest entitlement, correct application properties, and no debug/invalid origin marker.

- [ ] **Step 4: Run complete local gates, commit, push, and require exact-SHA CI**

Run:

```bash
PATH="/Users/zhanglonglong/Projects/apps/.venv/bin:$PATH" ./scripts/test_all.sh
python scripts/validate_ios_release.py
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
git diff --check
git status --short --branch
```

Commit CI/docs with `ci: verify native iOS release`, push the exact SHA, and require both backend and iOS jobs green.

## Task 11: Configure Firebase/Apple and prove real-device App Attest on the candidate

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Verify external identifiers before mutation**

In Apple Developer and Firebase Console, confirm the intended team, App ID `com.zll.sumaiguard`, Firebase iOS app, Google service plist, and App Check registration. Stop if an existing record conflicts with another app or organization.

- [ ] **Step 2: Enable App Attest and configure TTL**

Enable App Attest for the exact App ID. Register the exact Firebase iOS app for App Check using App Attest and set token TTL to 30 minutes. Do not enable enforcement until a debug/simulator path and a physical-device path have both been validated.

- [ ] **Step 3: Install Firebase configuration securely**

Place `ios/SumaiGuard/Resources/GoogleService-Info.plist` in the Xcode target only after confirming it belongs to `com.zll.sumaiguard` and the same Google Cloud project as the candidate backend. Firebase documents this downloaded file as non-secret client configuration; review every identifier and track it so CI and release builds are reproducible. Extend `validate_ios_release.py` to assert the bundle ID and Firebase app ID while never printing the client API key. Never include a server key, service-account JSON, App Check debug token, or access token.

- [ ] **Step 4: Register the simulator debug provider without weakening Release**

Run Debug on the simulator, copy the generated debug token directly into Firebase Console, and confirm a debug request succeeds. Never put the token in Git, tracked docs, CI logs, screenshots, or chat. Re-run `validate_ios_release.py` to prove Release has no debug provider path.

- [ ] **Step 5: Run a physical-device candidate test**

Install a Release-signed build on a physical iPhone. Use a synthetic room image containing only geometric furniture-like shapes. Confirm:

- camera and `PhotosPicker` work;
- cancel at consent sends no request;
- agree sends one request to the exact candidate URL;
- candidate returns HTTP 200 with a valid typed response;
- Firebase metrics identify App Attest, not Debug;
- server logs contain metadata only;
- app reset clears all result content.

- [ ] **Step 6: Record sanitized device evidence and ask for promotion confirmation**

Create device evidence JSON outside the repository with source SHA, candidate revision/URL, `app_attest_provider: AppAttestProvider`, status 200, observation timestamp, device OS major/minor, app version/build, and the SHA-256 of the synthetic input. Exclude the token, device identifier, response body, result images, reports, names, Apple account, and serial number.

Update the tracked release gate with only a hash/reference to that evidence. Stop and request explicit confirmation before invoking `SUMAI_PROMOTE_APPLY=true` in Plan 1.

- [ ] **Step 7: Commit and push the verified Firebase configuration**

Run the full validator and simulator test again, stage only `ios/SumaiGuard/Resources/GoogleService-Info.plist`, the exact `project.yml`/generated-project resource references, validator changes, and sanitized release-gate change, then commit with `build: bind the native app to Firebase App Check`. Push the exact SHA and require the iOS CI job to pass before production promotion.

## Final verification and handoff

Run:

```bash
python scripts/validate_ios_release.py
xcodebuild -project ios/SumaiGuard.xcodeproj -scheme SumaiGuard -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
git diff --check
git status --short --branch
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Report simulator, archive, signing, Release entitlement, Firebase configuration, debug-provider isolation, physical-device App Attest, candidate response, CI, Git, and all skipped external states separately. Do not call the app ready for App Review until Plan 3 is complete.
