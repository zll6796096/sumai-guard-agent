import CoreGraphics
import Foundation
import ImageIO
@testable import SumaiGuard
import UniformTypeIdentifiers
import XCTest

@MainActor
final class AppFlowCoordinatorTests: XCTestCase {
    func testSelectedImageMovesToConsentWithoutDoingWork() async throws {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)

        await selectImage(on: coordinator)

        guard case let .consent(selection) = coordinator.screen else {
            return XCTFail("A selection must wait at the consent screen")
        }
        XCTAssertFalse(selection.id.uuidString.isEmpty)
        XCTAssertEqual(selection.preview.width, 1)
        XCTAssertEqual(selection.preview.height, 1)
        XCTAssertFalse(Mirror(reflecting: selection).children.contains { $0.value is Data })
        let sanitizerCallCount = await sanitizer.callCount
        let analyzerCallCount = await analyzer.callCount
        XCTAssertEqual(sanitizerCallCount, 0)
        XCTAssertEqual(analyzerCallCount, 0)
        XCTAssertEqual(
            coordinator.sensitiveStateForTesting,
            .init(hasSource: true, hasSanitizedImage: false, hasResponse: false, hasPDF: false, hasActiveTask: false)
        )
    }

    func testCancelConsentClearsSensitiveStateAndSendsZeroRequests() async {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)

        coordinator.cancelConsent()

        XCTAssertEqual(coordinator.screen, .capture)
        let sanitizerCallCount = await sanitizer.callCount
        let analyzerCallCount = await analyzer.callCount
        XCTAssertEqual(sanitizerCallCount, 0)
        XCTAssertEqual(analyzerCallCount, 0)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
    }

    func testInvalidOrAbovePreviewPixelLimitSelectionFailsClosedWithoutWork() async {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ControlledAnalyzerSpy()
        let invalidCoordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)

        await selectImage(on: invalidCoordinator, data: Data("not-an-image".utf8))

        XCTAssertEqual(invalidCoordinator.screen, .error(.invalidImage))
        XCTAssertEqual(invalidCoordinator.sensitiveStateForTesting, .empty)

        let boundedCoordinator = AppFlowCoordinator(
            sanitizer: sanitizer,
            analyzer: analyzer,
            previewRenderer: ImagePreviewRenderer(
                limits: .init(maxLongSide: 512, maxSourcePixels: 0)
            )
        )
        await selectImage(on: boundedCoordinator)

        XCTAssertEqual(boundedCoordinator.screen, .error(.imageTooLarge))
        XCTAssertEqual(boundedCoordinator.sensitiveStateForTesting, .empty)
        let sanitizerCalls = await sanitizer.callCount
        let analyzerCalls = await analyzer.callCount
        XCTAssertEqual(sanitizerCalls, 0)
        XCTAssertEqual(analyzerCalls, 0)
    }

    func testPreviewRenderingIsAsyncAndDoesNotBlockMainActor() async throws {
        let renderer = ControlledPreviewRenderer()
        let coordinator = AppFlowCoordinator(
            sanitizer: ImmediateSanitizerSpy(),
            analyzer: ControlledAnalyzerSpy(),
            previewRenderer: renderer
        )

        coordinator.selectImage(syntheticSourceImage)
        var mainActorSentinelRan = false
        mainActorSentinelRan = true

        XCTAssertTrue(mainActorSentinelRan)
        XCTAssertTrue(coordinator.isPreparingPreview)
        XCTAssertEqual(coordinator.screen, .capture)
        await renderer.waitForCallCount(1)
        await renderer.succeed(call: 0, preview: try decodedSyntheticPreview())
        await waitUntil { coordinator.isPreparingPreview == false }
        guard case .consent = coordinator.screen else {
            return XCTFail("Completed preview rendering must enter consent")
        }
    }

    func testReplacementCancelsOldPreviewAndIgnoresItsLateCompletion() async throws {
        let renderer = ControlledPreviewRenderer()
        let coordinator = AppFlowCoordinator(
            sanitizer: ImmediateSanitizerSpy(),
            analyzer: ControlledAnalyzerSpy(),
            previewRenderer: renderer
        )
        coordinator.selectImage(syntheticSourceImage)
        await renderer.waitForCallCount(1)

        coordinator.selectImage(syntheticSourceImage)

        await renderer.waitForCancellation(call: 0)
        await renderer.waitForCallCount(2)
        await renderer.succeed(call: 0, preview: try decodedSyntheticPreview())
        XCTAssertTrue(coordinator.isPreparingPreview)
        XCTAssertEqual(coordinator.screen, .capture)
        let replacementPreview = try decodedSyntheticPreview()
        await renderer.succeed(call: 1, preview: replacementPreview)
        await waitUntil { coordinator.isPreparingPreview == false }
        guard case let .consent(selection) = coordinator.screen else {
            return XCTFail("Only the replacement preview may enter consent")
        }
        XCTAssertTrue(selection.preview === replacementPreview)
    }

    func testReturnHomeCancelsPreviewAndIgnoresLateCompletion() async throws {
        let renderer = ControlledPreviewRenderer()
        let coordinator = AppFlowCoordinator(
            sanitizer: ImmediateSanitizerSpy(),
            analyzer: ControlledAnalyzerSpy(),
            previewRenderer: renderer
        )
        coordinator.selectImage(syntheticSourceImage)
        await renderer.waitForCallCount(1)

        coordinator.returnHome()

        await renderer.waitForCancellation(call: 0)
        XCTAssertFalse(coordinator.isPreparingPreview)
        XCTAssertEqual(coordinator.screen, .capture)
        await renderer.succeed(call: 0, preview: try decodedSyntheticPreview())
        await renderer.waitUntilNoPendingCompletion(call: 0)
        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
    }

    func testRealPreviewRendererNormalizesOrientationBoundsSizeAndChecksPixelsBeforeDecode() async throws {
        let renderer = ImagePreviewRenderer()
        let oriented = try await renderer.renderPreview(
            from: try syntheticJPEG(width: 80, height: 120, orientation: 6)
        )
        XCTAssertEqual(oriented.width, 120)
        XCTAssertEqual(oriented.height, 80)

        let bounded = try await renderer.renderPreview(
            from: try syntheticJPEG(width: 2_000, height: 1_000)
        )
        XCTAssertEqual(bounded.width, 512)
        XCTAssertEqual(bounded.height, 256)

        let pixelLimitedRenderer = ImagePreviewRenderer(
            limits: .init(maxLongSide: 512, maxSourcePixels: 100)
        )
        do {
            _ = try await pixelLimitedRenderer.renderPreview(
                from: try syntheticJPEG(width: 11, height: 10)
            )
            XCTFail("The header pixel limit must reject before thumbnail decode")
        } catch {
            XCTAssertEqual(error as? ImagePreviewError, .sourceTooLarge)
        }
    }

    func testAgreeSanitizesBeforeOneAutoRequestAndDoubleAgreeDoesNotDuplicateIt() async throws {
        let events = FlowEventRecorder()
        let sanitizer = ImmediateSanitizerSpy(events: events)
        let analyzer = ControlledAnalyzerSpy(events: events)
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)

        coordinator.agreeAndAnalyze()
        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)

        let sanitizerCallCount = await sanitizer.callCount
        let analyzerCallCount = await analyzer.callCount
        let preflightCallCount = await analyzer.preflightCallCount
        let roomHints = await analyzer.roomHints
        let recordedEvents = await events.values
        XCTAssertEqual(sanitizerCallCount, 1)
        XCTAssertEqual(analyzerCallCount, 1)
        XCTAssertEqual(preflightCallCount, 1)
        XCTAssertEqual(roomHints, ["auto"])
        XCTAssertEqual(recordedEvents, [.preflight, .sanitize, .analyze])
        guard case .processing = coordinator.screen else {
            return XCTFail("The coordinator must stay in processing until the response arrives")
        }

        await analyzer.succeed(try fixture("analysis-applicable"))
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }

        guard case .result = coordinator.screen else {
            return XCTFail("An applicable response with findings must show result")
        }
    }

    func testBlockedPreflightStartsNoSanitizationOrUploadAndHomeReleasesFlowState() async throws {
        let sanitizer = ImmediateSanitizerSpy()
        let authorizedUpload = AuthorizedUploadRecorder()
        let analyzer = ControlledPreflightAnalyzer(uploadRecorder: authorizedUpload)
        let sourceDeallocationProbe = DeallocationProbe()
        var coordinator: AppFlowCoordinator? = AppFlowCoordinator(
            sanitizer: sanitizer,
            analyzer: analyzer
        )
        weak var weakCoordinator: AppFlowCoordinator?
        weakCoordinator = coordinator
        await selectImage(
            on: try XCTUnwrap(coordinator),
            data: sourceDeallocationProbe.makeTrackedData(copying: syntheticSourceImage)
        )
        weak var weakSelection: SelectedImage?
        weak var weakPreview: CGImage?
        do {
            guard case let .consent(selection) = coordinator?.screen else {
                return XCTFail("Expected consent before preflight")
            }
            weakSelection = selection
            weakPreview = selection.preview
        }

        coordinator?.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)

        let sanitizerCallsDuringPreflight = await sanitizer.callCount
        let uploadsDuringPreflight = await authorizedUpload.callCount
        XCTAssertEqual(sanitizerCallsDuringPreflight, 0)
        XCTAssertEqual(uploadsDuringPreflight, 0)
        coordinator?.returnHome()
        await analyzer.waitForCancellation()
        await sourceDeallocationProbe.waitForDeallocation()
        XCTAssertNil(weakSelection)
        XCTAssertNil(weakPreview)

        coordinator = nil
        XCTAssertNil(weakCoordinator)

        await analyzer.succeed()
        await authorizedUpload.waitForAuthorizedRelease()
        let sanitizerCallsAfterLateToken = await sanitizer.callCount
        let uploadsAfterLateToken = await authorizedUpload.callCount
        XCTAssertEqual(sanitizerCallsAfterLateToken, 0)
        XCTAssertEqual(uploadsAfterLateToken, 0)
    }

    func testPreflightFailureRetainsSelectionAndRetryPerformsFreshPreflightOnlyAfterConsent() async {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ImmediatePreflightFailingAnalyzer(error: .appCheckInvalid)
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        guard case let .consent(firstSelection) = coordinator.screen else {
            return XCTFail("Expected initial consent")
        }

        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }

        XCTAssertEqual(coordinator.screen, .error(.verificationUnavailable))
        let sanitizerCallsAfterFailure = await sanitizer.callCount
        XCTAssertEqual(sanitizerCallsAfterFailure, 0)
        coordinator.retry()
        guard case let .consent(retrySelection) = coordinator.screen else {
            return XCTFail("Retry must require renewed consent")
        }
        XCTAssertTrue(firstSelection === retrySelection)
        let preflightsBeforeRenewedConsent = await analyzer.callCount
        XCTAssertEqual(preflightsBeforeRenewedConsent, 1)

        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(2)
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }
        let totalPreflights = await analyzer.callCount
        let totalSanitizerCalls = await sanitizer.callCount
        XCTAssertEqual(totalPreflights, 2)
        XCTAssertEqual(totalSanitizerCalls, 0)
    }

    func testCancelProcessingClearsEverythingAndIgnoresLateSuccess() async throws {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)
        XCTAssertFalse(coordinator.sensitiveStateForTesting.hasSanitizedImage)

        coordinator.cancelProcessing()

        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
        await analyzer.succeed(try fixture("analysis-applicable"))
        await analyzer.waitUntilNoPendingCompletion()
        await waitUntil { coordinator.inFlightTaskCountForTesting == 0 }
        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
    }

    func testReturnHomeIgnoresLateErrorAndNeverShowsCancellationAsError() async {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)

        coordinator.returnHome()
        await analyzer.fail(.network)
        await analyzer.waitUntilNoPendingCompletion()
        await waitUntil { coordinator.inFlightTaskCountForTesting == 0 }

        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
    }

    func testSanitizerFailureStartsNoRequestAndRetryRequiresRenewedConsent() async {
        let sanitizer = ImmediateSanitizerSpy(failure: .invalidImage)
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await sanitizer.waitForCallCount(1)
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }

        XCTAssertEqual(coordinator.screen, .error(.invalidImage))
        let requestCountBeforeRetry = await analyzer.callCount
        XCTAssertEqual(requestCountBeforeRetry, 0)
        XCTAssertEqual(
            coordinator.sensitiveStateForTesting,
            .init(hasSource: true, hasSanitizedImage: false, hasResponse: false, hasPDF: false, hasActiveTask: false)
        )

        coordinator.retry()

        guard case .consent = coordinator.screen else {
            return XCTFail("Retry must ask for consent again")
        }
        let sanitizerCallCount = await sanitizer.callCount
        let analyzerCallCount = await analyzer.callCount
        XCTAssertEqual(sanitizerCallCount, 1)
        XCTAssertEqual(analyzerCallCount, 0)
    }

    func testEveryAPIErrorMapsToStableJapaneseCopyWithoutProviderDetails() async {
        let cases: [(APIError, UserFacingError)] = [
            (.invalidImage, .invalidImage),
            (.appCheckInvalid, .verificationUnavailable),
            (.imageTooLarge, .imageTooLarge),
            (.serviceLimited, .serviceBusy),
            (.geminiUnavailable, .serviceUnavailable),
            (.internalError, .invalidResponse),
            (.invalidResponse, .invalidResponse),
            (.network, .network),
        ]

        for (apiError, expected) in cases {
            let sanitizer = ImmediateSanitizerSpy()
            let analyzer = ImmediateFailingAnalyzer(error: apiError)
            let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
            await selectImage(on: coordinator)
            coordinator.agreeAndAnalyze()
            await analyzer.waitForCallCount(1)
            await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }

            XCTAssertEqual(coordinator.screen, .error(expected), "\(apiError)")
            XCTAssertEqual(
                coordinator.sensitiveStateForTesting,
                .init(hasSource: true, hasSanitizedImage: false, hasResponse: false, hasPDF: false, hasActiveTask: false)
            )
            XCTAssertFalse(expected.messageJA.isEmpty)
            XCTAssertFalse(expected.messageJA.contains("SECRET"))
        }

        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ImmediateFailingAnalyzer(error: SecretProviderError())
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }

        XCTAssertEqual(coordinator.screen, .error(.unexpected))
        guard case let .error(error) = coordinator.screen else {
            return XCTFail("Unknown failures must map to a stable error")
        }
        XCTAssertFalse(error.messageJA.contains("SECRET_PROVIDER_TOKEN_DETAIL"))
    }

    func testReplacementSelectionCancelsOldWorkClearsIntermediatesAndIgnoresLateResponse() async throws {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        guard case let .consent(firstSelection) = coordinator.screen else {
            return XCTFail("Expected first consent")
        }
        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)

        await selectImage(on: coordinator)

        guard case let .consent(secondSelection) = coordinator.screen else {
            return XCTFail("A replacement must require new consent")
        }
        XCTAssertNotEqual(firstSelection, secondSelection)
        XCTAssertEqual(
            coordinator.sensitiveStateForTesting,
            .init(hasSource: true, hasSanitizedImage: false, hasResponse: false, hasPDF: false, hasActiveTask: false)
        )
        await analyzer.succeed(try fixture("analysis-applicable"))
        await analyzer.waitUntilNoPendingCompletion()
        await waitUntil { coordinator.inFlightTaskCountForTesting == 0 }
        XCTAssertEqual(coordinator.screen, .consent(secondSelection))
        let analyzerCallCount = await analyzer.callCount
        XCTAssertEqual(analyzerCallCount, 1)
    }

    func testNotApplicableTakesPriorityAndCannotEnterAdvice() async throws {
        let response = try fixture("analysis-not-applicable")
        let coordinator = makeCoordinator(response: response)

        await runAnalysis(coordinator)

        XCTAssertEqual(coordinator.screen, .notApplicable("住まいの室内を確認できる写真ではありません。"))
        coordinator.showAdvice()
        XCTAssertEqual(coordinator.screen, .notApplicable("住まいの室内を確認できる写真ではありません。"))
        XCTAssertFalse(coordinator.sensitiveStateForTesting.hasSource)
        XCTAssertTrue(coordinator.sensitiveStateForTesting.hasResponse)
    }

    func testRetryKeepsTheExactIndependentlyRenderedPreviewWithoutExposingSourceBytes() async {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = ImmediateFailingAnalyzer(error: APIError.network)
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        guard case let .consent(firstSelection) = coordinator.screen else {
            return XCTFail("Expected consent with a renderable preview")
        }
        let firstPreview = firstSelection.preview

        coordinator.agreeAndAnalyze()
        await analyzer.waitForCallCount(1)
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }
        coordinator.retry()

        guard case let .consent(retrySelection) = coordinator.screen else {
            return XCTFail("Retry must restore consent with the selected preview")
        }
        XCTAssertTrue(firstSelection === retrySelection)
        XCTAssertTrue(firstPreview === retrySelection.preview)
        XCTAssertEqual(retrySelection.preview.width, 1)
        XCTAssertEqual(retrySelection.preview.height, 1)
        XCTAssertFalse(Mirror(reflecting: retrySelection).children.contains { $0.value is Data })
    }

    func testCancelHomeAndReplacementReleaseOldPreviewObjects() async {
        let coordinator = AppFlowCoordinator(
            sanitizer: ImmediateSanitizerSpy(),
            analyzer: ControlledAnalyzerSpy()
        )

        weak var cancelledSelection: SelectedImage?
        do {
            await selectImage(on: coordinator)
            guard case let .consent(selection) = coordinator.screen else {
                return XCTFail("Expected consent")
            }
            cancelledSelection = selection
        }
        coordinator.cancelConsent()
        XCTAssertNil(cancelledSelection)

        weak var homeSelection: SelectedImage?
        do {
            await selectImage(on: coordinator)
            guard case let .consent(selection) = coordinator.screen else {
                return XCTFail("Expected consent")
            }
            homeSelection = selection
        }
        coordinator.returnHome()
        XCTAssertNil(homeSelection)

        weak var replacedSelection: SelectedImage?
        do {
            await selectImage(on: coordinator)
            guard case let .consent(selection) = coordinator.screen else {
                return XCTFail("Expected consent")
            }
            replacedSelection = selection
        }
        await selectImage(on: coordinator)
        XCTAssertNil(replacedSelection)
    }

    func testCancelProcessingPropagatesCancellationThroughAnalyzerAndReleasesSanitizedBytes() async {
        let deallocationProbe = DeallocationProbe()
        let sanitizer = ImmediateSanitizerSpy(dataDeallocationProbe: deallocationProbe)
        let analyzer = CancellationAwareAnalyzer()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await analyzer.waitForStart()
        let wasReleasedBeforeCancellation = await deallocationProbe.isDeallocated
        XCTAssertFalse(wasReleasedBeforeCancellation)

        coordinator.cancelProcessing()

        await analyzer.waitForCancellation()
        await analyzer.waitForFinish()
        await deallocationProbe.waitForDeallocation()
        await waitUntil { coordinator.inFlightTaskCountForTesting == 0 }
        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
    }

    func testReturnHomePropagatesCancellationThroughSanitizerAndStartsNoRequest() async {
        let sanitizer = CancellationAwareSanitizer()
        let analyzer = ControlledAnalyzerSpy()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await sanitizer.waitForStart()

        coordinator.returnHome()

        await sanitizer.waitForCancellation()
        await sanitizer.waitForFinish()
        await waitUntil { coordinator.inFlightTaskCountForTesting == 0 }
        let requestCount = await analyzer.callCount
        XCTAssertEqual(requestCount, 0)
        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
    }

    func testReplacementPropagatesCancellationAndKeepsNewConsentAfterOldTaskFinishes() async {
        let sanitizer = ImmediateSanitizerSpy()
        let analyzer = CancellationAwareAnalyzer()
        let coordinator = AppFlowCoordinator(sanitizer: sanitizer, analyzer: analyzer)
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await analyzer.waitForStart()

        await selectImage(on: coordinator)
        guard case let .consent(replacement) = coordinator.screen else {
            return XCTFail("Replacement must require consent")
        }
        await analyzer.waitForCancellation()
        await analyzer.waitForFinish()
        await waitUntil { coordinator.inFlightTaskCountForTesting == 0 }

        XCTAssertEqual(coordinator.screen, .consent(replacement))
        XCTAssertEqual(
            coordinator.sensitiveStateForTesting,
            .init(hasSource: true, hasSanitizedImage: false, hasResponse: false, hasPDF: false, hasActiveTask: false)
        )
    }

    func testCancellationErrorAndStableCancelledErrorBothReturnToCleanCapture() async {
        let errors: [any Error & Sendable] = [CancellationError(), APIError.cancelled]
        for error in errors {
            let analyzer = ImmediateFailingAnalyzer(error: error)
            let coordinator = AppFlowCoordinator(
                sanitizer: ImmediateSanitizerSpy(),
                analyzer: analyzer
            )
            await selectImage(on: coordinator)
            coordinator.agreeAndAnalyze()
            await analyzer.waitForCallCount(1)
            await waitUntil {
                coordinator.sensitiveStateForTesting.hasActiveTask == false
                    && coordinator.inFlightTaskCountForTesting == 0
            }

            XCTAssertEqual(coordinator.screen, .capture)
            XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
        }
    }

    func testNoFindingsUsesDedicatedStateNeverClaimsSafetyAndCannotEnterAdvice() async throws {
        let response = try applicableResponse(findings: false, actions: false)
        let coordinator = makeCoordinator(response: response)

        await runAnalysis(coordinator)

        XCTAssertEqual(coordinator.screen, .noFindings(response))
        XCTAssertFalse(AppScreen.noFindings(response).accessibilitySummaryJA.contains("安全です"))
        coordinator.showAdvice()
        XCTAssertEqual(coordinator.screen, .noFindings(response))
    }

    func testOnlyApplicableResultWithFindingsAndActionsCanShowAdvice() async throws {
        let response = try fixture("analysis-applicable")
        let coordinator = makeCoordinator(response: response)

        await runAnalysis(coordinator)
        XCTAssertEqual(coordinator.screen, .result(response))

        coordinator.showAdvice()

        XCTAssertEqual(coordinator.screen, .advice(response))
    }

    func testFindingsWithoutAnActionPlanFailClosedAndCannotShowAdvice() async throws {
        let response = try applicableResponse(findings: true, actions: false)
        let coordinator = makeCoordinator(response: response)

        await runAnalysis(coordinator)

        XCTAssertEqual(coordinator.screen, .error(.invalidResponse))
        coordinator.showAdvice()
        XCTAssertEqual(coordinator.screen, .error(.invalidResponse))
    }

    func testReturnHomeClearsSourceSanitizedResponsePDFAndTask() async throws {
        let response = try fixture("analysis-applicable")
        let coordinator = makeCoordinator(response: response)
        await runAnalysis(coordinator)
        coordinator.showAdvice()
        coordinator.cachePDF(Data("private-pdf".utf8))
        XCTAssertEqual(
            coordinator.sensitiveStateForTesting,
            .init(hasSource: false, hasSanitizedImage: false, hasResponse: true, hasPDF: true, hasActiveTask: false)
        )

        coordinator.returnHome()

        XCTAssertEqual(coordinator.screen, .capture)
        XCTAssertEqual(coordinator.sensitiveStateForTesting, .empty)
        coordinator.retry()
        XCTAssertEqual(coordinator.screen, .capture)
    }
}

private extension AppFlowCoordinatorTests {
    func fixture(_ name: String) throws -> AnalysisResponse {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"))
        return try JSONDecoder.sumai.decode(AnalysisResponse.self, from: Data(contentsOf: url))
    }

    func applicableResponse(findings: Bool, actions: Bool) throws -> AnalysisResponse {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "analysis-applicable", withExtension: "json"))
        let data = try Data(contentsOf: url)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        if !findings {
            object["findings"] = []
        }
        if !actions {
            object["action_plan"] = [
                "family_no_cost": [],
                "care_manager_purchase": [],
                "contractor_construction": [],
            ]
        }
        return try JSONDecoder.sumai.decode(AnalysisResponse.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func makeCoordinator(response: AnalysisResponse) -> AppFlowCoordinator {
        AppFlowCoordinator(
            sanitizer: ImmediateSanitizerSpy(),
            analyzer: ImmediateAnalyzer(response: response)
        )
    }

    func runAnalysis(_ coordinator: AppFlowCoordinator) async {
        await selectImage(on: coordinator)
        coordinator.agreeAndAnalyze()
        await waitUntil { coordinator.sensitiveStateForTesting.hasActiveTask == false }
    }

    func waitUntil(
        iterations: Int = 10_000,
        _ predicate: @MainActor () -> Bool
    ) async {
        for _ in 0..<iterations {
            if predicate() {
                return
            }
            await Task.yield()
        }
        XCTFail("Timed out waiting for deterministic coordinator state")
    }

    func selectImage(
        on coordinator: AppFlowCoordinator,
        data: Data = syntheticSourceImage
    ) async {
        coordinator.selectImage(data)
        await waitUntil { coordinator.isPreparingPreview == false }
    }

    func decodedSyntheticPreview() throws -> CGImage {
        let source = try XCTUnwrap(
            CGImageSourceCreateWithData(syntheticSourceImage as CFData, nil)
        )
        return try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
    }

    func syntheticJPEG(
        width: Int,
        height: Int,
        orientation: UInt32 = 1
    ) throws -> Data {
        let pixels = Data(repeating: 0x80, count: width * height * 4)
        let provider = try XCTUnwrap(CGDataProvider(data: pixels as CFData))
        let image = try XCTUnwrap(
            CGImage(
                width: width,
                height: height,
                bitsPerComponent: 8,
                bitsPerPixel: 32,
                bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGBitmapInfo(
                    rawValue: CGImageAlphaInfo.premultipliedLast.rawValue
                ),
                provider: provider,
                decode: nil,
                shouldInterpolate: false,
                intent: .defaultIntent
            )
        )
        let output = NSMutableData()
        let destination = try XCTUnwrap(
            CGImageDestinationCreateWithData(
                output,
                UTType.jpeg.identifier as CFString,
                1,
                nil
            )
        )
        CGImageDestinationAddImage(
            destination,
            image,
            [
                kCGImagePropertyOrientation: orientation,
                kCGImageDestinationLossyCompressionQuality: 0.8,
            ] as CFDictionary
        )
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return output as Data
    }
}

private enum FlowEvent: Equatable, Sendable {
    case preflight
    case sanitize
    case analyze
}

private actor FlowEventRecorder {
    private(set) var values: [FlowEvent] = []

    func append(_ event: FlowEvent) {
        values.append(event)
    }
}

private actor ControlledPreviewRenderer: PreviewRendering {
    private var nextCall = 0
    private var continuations: [Int: CheckedContinuation<CGImage, any Error>] = [:]
    private var cancelledCalls: Set<Int> = []
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []
    private var cancellationWaiters: [(Int, CheckedContinuation<Void, Never>)] = []
    private var completionWaiters: [(Int, CheckedContinuation<Void, Never>)] = []

    func renderPreview(from sourceData: Data) async throws -> CGImage {
        let call = nextCall
        nextCall += 1
        resumeCallWaiters()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                continuations[call] = continuation
            }
        } onCancel: {
            Task { await self.observeCancellation(call: call) }
        }
    }

    func succeed(call: Int, preview: CGImage) {
        let continuation = continuations.removeValue(forKey: call)
        continuation?.resume(returning: preview)
        let ready = completionWaiters.filter { $0.0 == call }
        completionWaiters.removeAll { $0.0 == call }
        ready.forEach { $0.1.resume() }
    }

    func waitForCallCount(_ count: Int) async {
        guard nextCall < count else { return }
        await withCheckedContinuation { continuation in
            callWaiters.append((count, continuation))
        }
    }

    func waitForCancellation(call: Int) async {
        guard !cancelledCalls.contains(call) else { return }
        await withCheckedContinuation { continuation in
            cancellationWaiters.append((call, continuation))
        }
    }

    func waitUntilNoPendingCompletion(call: Int) async {
        guard continuations[call] != nil else { return }
        await withCheckedContinuation { continuation in
            completionWaiters.append((call, continuation))
        }
    }

    private func observeCancellation(call: Int) {
        cancelledCalls.insert(call)
        let ready = cancellationWaiters.filter { $0.0 == call }
        cancellationWaiters.removeAll { $0.0 == call }
        ready.forEach { $0.1.resume() }
    }

    private func resumeCallWaiters() {
        let ready = callWaiters.filter { nextCall >= $0.0 }
        callWaiters.removeAll { nextCall >= $0.0 }
        ready.forEach { $0.1.resume() }
    }
}

private actor ImmediateSanitizerSpy: ImageSanitizing {
    private(set) var callCount = 0
    private let failure: ImageSanitizerError?
    private let events: FlowEventRecorder?
    private let dataDeallocationProbe: DeallocationProbe?
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []

    init(
        failure: ImageSanitizerError? = nil,
        events: FlowEventRecorder? = nil,
        dataDeallocationProbe: DeallocationProbe? = nil
    ) {
        self.failure = failure
        self.events = events
        self.dataDeallocationProbe = dataDeallocationProbe
    }

    func sanitize(_ sourceData: Data) async throws -> SanitizedImage {
        callCount += 1
        resumeSatisfiedWaiters()
        await events?.append(.sanitize)
        if let failure {
            throw failure
        }
        return SanitizedImage(
            data: dataDeallocationProbe?.makeTrackedData()
                ?? Data([0xFF, 0xD8, 0xFF, 0xD9]),
            pixelWidth: 1,
            pixelHeight: 1,
            mimeType: "image/jpeg",
            filename: "sumaiguard-upload.jpg"
        )
    }

    func waitForCallCount(_ expected: Int) async {
        guard callCount < expected else { return }
        await withCheckedContinuation { continuation in
            callWaiters.append((expected, continuation))
        }
    }

    private func resumeSatisfiedWaiters() {
        let ready = callWaiters.filter { callCount >= $0.0 }
        callWaiters.removeAll { callCount >= $0.0 }
        ready.forEach { $0.1.resume() }
    }
}

private actor ControlledAnalyzerSpy: Analyzing, AuthorizedAnalyzing {
    private(set) var preflightCallCount = 0
    private(set) var callCount = 0
    private(set) var roomHints: [String] = []
    private let events: FlowEventRecorder?
    private var completion: CheckedContinuation<Result<AnalysisResponse, APIError>, Never>?
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []
    private var completionWaiters: [CheckedContinuation<Void, Never>] = []

    init(events: FlowEventRecorder? = nil) {
        self.events = events
    }

    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        preflightCallCount += 1
        await events?.append(.preflight)
        return self
    }

    func analyze(image _: SanitizedImage, roomHint: String) async throws -> AnalysisResponse {
        callCount += 1
        roomHints.append(roomHint)
        resumeSatisfiedCallWaiters()
        await events?.append(.analyze)
        let result = await withCheckedContinuation { continuation in
            completion = continuation
        }
        completion = nil
        completionWaiters.forEach { $0.resume() }
        completionWaiters.removeAll()
        return try result.get()
    }

    func succeed(_ response: AnalysisResponse) {
        completion?.resume(returning: .success(response))
    }

    func fail(_ error: APIError) {
        completion?.resume(returning: .failure(error))
    }

    func waitForCallCount(_ expected: Int) async {
        guard callCount < expected else { return }
        await withCheckedContinuation { continuation in
            callWaiters.append((expected, continuation))
        }
    }

    func waitUntilNoPendingCompletion() async {
        guard completion != nil else { return }
        await withCheckedContinuation { continuation in
            completionWaiters.append(continuation)
        }
    }

    private func resumeSatisfiedCallWaiters() {
        let ready = callWaiters.filter { callCount >= $0.0 }
        callWaiters.removeAll { callCount >= $0.0 }
        ready.forEach { $0.1.resume() }
    }
}

private actor ControlledPreflightAnalyzer: Analyzing {
    private let uploadRecorder: AuthorizedUploadRecorder
    private(set) var callCount = 0
    private var continuation: CheckedContinuation<any AuthorizedAnalyzing, any Error>?
    private var cancelled = false
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []
    private var cancellationWaiters: [CheckedContinuation<Void, Never>] = []

    init(uploadRecorder: AuthorizedUploadRecorder) {
        self.uploadRecorder = uploadRecorder
    }

    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        callCount += 1
        let ready = callWaiters.filter { callCount >= $0.0 }
        callWaiters.removeAll { callCount >= $0.0 }
        ready.forEach { $0.1.resume() }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
            }
        } onCancel: {
            Task { await self.observeCancellation() }
        }
    }

    func succeed() {
        let pending = continuation
        continuation = nil
        pending?.resume(returning: TrackedAuthorizedUpload(recorder: uploadRecorder))
    }

    func waitForCallCount(_ expected: Int) async {
        guard callCount < expected else { return }
        await withCheckedContinuation { continuation in
            callWaiters.append((expected, continuation))
        }
    }

    func waitForCancellation() async {
        guard !cancelled else { return }
        await withCheckedContinuation { continuation in
            cancellationWaiters.append(continuation)
        }
    }

    private func observeCancellation() {
        cancelled = true
        cancellationWaiters.forEach { $0.resume() }
        cancellationWaiters.removeAll()
    }

}

private actor AuthorizedUploadRecorder {
    private(set) var callCount = 0
    private var authorizedReleased = false
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func recordUpload() {
        callCount += 1
    }

    func recordAuthorizedRelease() {
        authorizedReleased = true
        releaseWaiters.forEach { $0.resume() }
        releaseWaiters.removeAll()
    }

    func waitForAuthorizedRelease() async {
        guard !authorizedReleased else { return }
        await withCheckedContinuation { continuation in
            releaseWaiters.append(continuation)
        }
    }
}

private final class TrackedAuthorizedUpload: AuthorizedAnalyzing, @unchecked Sendable {
    private let recorder: AuthorizedUploadRecorder

    init(recorder: AuthorizedUploadRecorder) {
        self.recorder = recorder
    }

    deinit {
        let recorder = recorder
        Task { await recorder.recordAuthorizedRelease() }
    }

    func analyze(image _: SanitizedImage, roomHint _: String) async throws -> AnalysisResponse {
        await recorder.recordUpload()
        throw APIError.invalidResponse
    }
}

private actor ImmediatePreflightFailingAnalyzer: Analyzing {
    private let error: APIError
    private(set) var callCount = 0
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []

    init(error: APIError) {
        self.error = error
    }

    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        callCount += 1
        let ready = callWaiters.filter { callCount >= $0.0 }
        callWaiters.removeAll { callCount >= $0.0 }
        ready.forEach { $0.1.resume() }
        throw error
    }

    func waitForCallCount(_ expected: Int) async {
        guard callCount < expected else { return }
        await withCheckedContinuation { continuation in
            callWaiters.append((expected, continuation))
        }
    }
}

private actor ImmediateAnalyzer: Analyzing, AuthorizedAnalyzing {
    private let response: AnalysisResponse

    init(response: AnalysisResponse) {
        self.response = response
    }

    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        self
    }

    func analyze(image _: SanitizedImage, roomHint _: String) async throws -> AnalysisResponse {
        response
    }
}

private actor ImmediateFailingAnalyzer: Analyzing, AuthorizedAnalyzing {
    private let error: any Error & Sendable
    private(set) var callCount = 0
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []

    init(error: any Error & Sendable) {
        self.error = error
    }

    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        self
    }

    func analyze(image _: SanitizedImage, roomHint _: String) async throws -> AnalysisResponse {
        callCount += 1
        let ready = callWaiters.filter { callCount >= $0.0 }
        callWaiters.removeAll { callCount >= $0.0 }
        ready.forEach { $0.1.resume() }
        throw error
    }

    func waitForCallCount(_ expected: Int) async {
        guard callCount < expected else { return }
        await withCheckedContinuation { continuation in
            callWaiters.append((expected, continuation))
        }
    }
}

private struct SecretProviderError: Error, Sendable, CustomStringConvertible {
    var description: String { "SECRET_PROVIDER_TOKEN_DETAIL" }
}

private let syntheticSourceImage = Data(
    base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMQtzUCAAD1AIeGlNxsAAAAAElFTkSuQmCC"
)!

private actor DeallocationProbe {
    private(set) var isDeallocated = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    nonisolated func makeTrackedData() -> Data {
        makeTrackedData(copying: Data(repeating: 0xA5, count: 1_024))
    }

    nonisolated func makeTrackedData(copying source: Data) -> Data {
        precondition(!source.isEmpty)
        let count = source.count
        let bytes = UnsafeMutableRawPointer.allocate(
            byteCount: count,
            alignment: MemoryLayout<UInt8>.alignment
        )
        source.copyBytes(
            to: bytes.assumingMemoryBound(to: UInt8.self),
            count: count
        )
        return Data(bytesNoCopy: bytes, count: count, deallocator: .custom { pointer, _ in
            pointer.deallocate()
            Task { await self.markDeallocated() }
        })
    }

    func waitForDeallocation() async {
        guard !isDeallocated else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    private func markDeallocated() {
        isDeallocated = true
        waiters.forEach { $0.resume() }
        waiters.removeAll()
    }
}

private final class CooperativeCancellationGate<Value: Sendable>: @unchecked Sendable {
    private typealias OperationContinuation = CheckedContinuation<Value, any Error>

    private let lock = NSLock()
    private var operationContinuation: OperationContinuation?
    private var started = false
    private var cancellationObserved = false
    private var finished = false
    private var startWaiters: [CheckedContinuation<Void, Never>] = []
    private var cancellationWaiters: [CheckedContinuation<Void, Never>] = []
    private var finishWaiters: [CheckedContinuation<Void, Never>] = []

    func suspendUntilCancelled() async throws -> Value {
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                var resumeAsCancelled = false
                let waiters: [CheckedContinuation<Void, Never>]
                lock.lock()
                started = true
                waiters = startWaiters
                startWaiters.removeAll()
                if cancellationObserved {
                    resumeAsCancelled = true
                } else {
                    operationContinuation = continuation
                }
                lock.unlock()
                waiters.forEach { $0.resume() }
                if resumeAsCancelled {
                    continuation.resume(throwing: CancellationError())
                }
            }
        } onCancel: {
            self.observeCancellation()
        }
    }

    func markFinished() {
        let waiters: [CheckedContinuation<Void, Never>]
        lock.lock()
        finished = true
        waiters = finishWaiters
        finishWaiters.removeAll()
        lock.unlock()
        waiters.forEach { $0.resume() }
    }

    func waitForStart() async {
        await wait(for: .started)
    }

    func waitForCancellation() async {
        await wait(for: .cancelled)
    }

    func waitForFinish() async {
        await wait(for: .finished)
    }

    private enum Milestone {
        case started
        case cancelled
        case finished
    }

    private func observeCancellation() {
        let continuation: OperationContinuation?
        let waiters: [CheckedContinuation<Void, Never>]
        lock.lock()
        cancellationObserved = true
        continuation = operationContinuation
        operationContinuation = nil
        waiters = cancellationWaiters
        cancellationWaiters.removeAll()
        lock.unlock()
        waiters.forEach { $0.resume() }
        continuation?.resume(throwing: CancellationError())
    }

    private func wait(for milestone: Milestone) async {
        await withCheckedContinuation { continuation in
            var resumeImmediately = false
            lock.lock()
            switch milestone {
            case .started where started:
                resumeImmediately = true
            case .cancelled where cancellationObserved:
                resumeImmediately = true
            case .finished where finished:
                resumeImmediately = true
            case .started:
                startWaiters.append(continuation)
            case .cancelled:
                cancellationWaiters.append(continuation)
            case .finished:
                finishWaiters.append(continuation)
            }
            lock.unlock()
            if resumeImmediately {
                continuation.resume()
            }
        }
    }
}

private final class CancellationAwareSanitizer: ImageSanitizing, @unchecked Sendable {
    private let gate = CooperativeCancellationGate<SanitizedImage>()

    func sanitize(_ sourceData: Data) async throws -> SanitizedImage {
        do {
            let result = try await gate.suspendUntilCancelled()
            gate.markFinished()
            return result
        } catch {
            gate.markFinished()
            throw error
        }
    }

    func waitForStart() async {
        await gate.waitForStart()
    }

    func waitForCancellation() async {
        await gate.waitForCancellation()
    }

    func waitForFinish() async {
        await gate.waitForFinish()
    }
}

private final class CancellationAwareAnalyzer: Analyzing, AuthorizedAnalyzing, @unchecked Sendable {
    private let gate = CooperativeCancellationGate<AnalysisResponse>()

    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        self
    }

    func analyze(image: SanitizedImage, roomHint: String) async throws -> AnalysisResponse {
        do {
            let result = try await gate.suspendUntilCancelled()
            gate.markFinished()
            return result
        } catch {
            gate.markFinished()
            throw error
        }
    }

    func waitForStart() async {
        await gate.waitForStart()
    }

    func waitForCancellation() async {
        await gate.waitForCancellation()
    }

    func waitForFinish() async {
        await gate.waitForFinish()
    }
}
