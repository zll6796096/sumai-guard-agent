import AVFoundation
import CoreGraphics
import Foundation
import SwiftUI
@testable import SumaiGuard
import UIKit
import XCTest

@MainActor
final class CaptureConsentViewTests: XCTestCase {
    func testProductionContentDefinesEveryVisibleActionAndDisclosureInJapanese() {
        let content = CaptureConsentContent.production

        XCTAssertEqual(content.title, "実家あんしんチェック")
        XCTAssertEqual(content.cameraAction.label, "カメラで撮る")
        XCTAssertEqual(content.libraryAction.label, "写真を1枚選ぶ")
        XCTAssertEqual(content.privacyAction.label, "写真の取り扱いを見る")
        XCTAssertEqual(content.agreeAction.label, "同意して写真を送る")
        XCTAssertEqual(content.cancelConsentAction.label, "同意せず戻る")
        XCTAssertEqual(content.cancelPreparationAction.label, "選択を取り消す")
        XCTAssertEqual(content.cancelCameraPermissionAction.label, "カメラの確認を取り消す")
        XCTAssertEqual(
            Set([
                content.cameraAction.identifier,
                content.libraryAction.identifier,
                content.privacyAction.identifier,
                content.agreeAction.identifier,
                content.cancelConsentAction.identifier,
                content.cancelPreparationAction.identifier,
                content.cancelCameraPermissionAction.identifier,
            ]).count,
            7
        )
        XCTAssertTrue(content.allAccessibilityText.allSatisfy { !$0.isEmpty })
        XCTAssertEqual(
            content.disclosures.map(\.text),
            [
                "住まいの写真から、目に見える転倒・滑り・つまずきの注意候補を確認するために使用します。",
                "写真は SumaiGuard Cloud Run と、Google LLC の Google Gemini に送信されます。",
                "住宅の写真には、私的な生活情報が写り込む場合があります。",
                "SumaiGuard アプリは写真を保存しません。",
                "同意しない場合やキャンセルした場合、写真は送信されません。",
                "本結果は、医療、介護認定、保険、法令適合、施工可否の判断に代わるものではありません。",
            ]
        )
        XCTAssertEqual(Set(content.disclosures.map(\.id)).count, 6)
    }

    func testEveryCaptureAndConsentViewUsesTheSameProductionContentModel() throws {
        let acquisition = CaptureAcquisitionModel(
            cameraAccess: CameraAccessStub(isAvailable: false, authorization: .denied),
            onSelectImage: { _ in }
        )
        let selection = SelectedImage(preview: try syntheticPreview())
        let capture = CaptureView(
            acquisition: acquisition,
            isPreparingPreview: false,
            onCancelPreparation: {}
        )
        let consent = ConsentView(
            selection: selection,
            actions: ConsentActions(agree: {}, cancel: {})
        )
        let privacy = PrivacySheet()

        XCTAssertEqual(capture.content, .production)
        XCTAssertEqual(consent.content, .production)
        XCTAssertEqual(privacy.content, .production)
        XCTAssertEqual(consent.selection, selection)
    }

    func testCameraPolicyCoversAvailabilityAndEveryAuthorizationState() {
        XCTAssertEqual(
            CameraAccessPolicy.decision(isAvailable: false, authorization: .authorized),
            .showUnavailable
        )
        XCTAssertEqual(
            CameraAccessPolicy.decision(isAvailable: true, authorization: .authorized),
            .presentCamera
        )
        XCTAssertEqual(
            CameraAccessPolicy.decision(isAvailable: true, authorization: .notDetermined),
            .requestPermission
        )
        XCTAssertEqual(
            CameraAccessPolicy.decision(isAvailable: true, authorization: .denied),
            .showDenied
        )
        XCTAssertEqual(
            CameraAccessPolicy.decision(isAvailable: true, authorization: .restricted),
            .showRestricted
        )
    }

    func testAuthorizedCameraPresentsWithoutRequestingPermission() async {
        let access = CameraAccessStub(isAvailable: true, authorization: .authorized)
        let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })

        await model.requestCamera()

        XCTAssertTrue(model.isCameraPresented)
        XCTAssertNil(model.cameraMessage)
        XCTAssertEqual(access.requestCount, 0)
    }

    func testNotDeterminedCameraRequestsOnceAndPresentsOnlyWhenGranted() async {
        let granted = CameraAccessStub(
            isAvailable: true,
            authorization: .notDetermined,
            requestResult: true
        )
        let grantedModel = CaptureAcquisitionModel(cameraAccess: granted, onSelectImage: { _ in })
        await grantedModel.requestCamera()
        XCTAssertEqual(granted.requestCount, 1)
        XCTAssertTrue(grantedModel.isCameraPresented)

        let refused = CameraAccessStub(
            isAvailable: true,
            authorization: .notDetermined,
            requestResult: false
        )
        let refusedModel = CaptureAcquisitionModel(cameraAccess: refused, onSelectImage: { _ in })
        await refusedModel.requestCamera()
        XCTAssertEqual(refused.requestCount, 1)
        XCTAssertFalse(refusedModel.isCameraPresented)
        XCTAssertEqual(refusedModel.cameraMessage, .denied)
    }

    func testDeniedRestrictedAndUnavailableCameraNeverRequestOrPresentPicker() async {
        let cases: [(CameraAccessStub, CameraAccessMessage)] = [
            (CameraAccessStub(isAvailable: true, authorization: .denied), .denied),
            (CameraAccessStub(isAvailable: true, authorization: .restricted), .restricted),
            (CameraAccessStub(isAvailable: false, authorization: .authorized), .unavailable),
        ]

        for (access, expectedMessage) in cases {
            let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })
            await model.requestCamera()
            XCTAssertEqual(access.requestCount, 0)
            XCTAssertFalse(model.isCameraPresented)
            XCTAssertEqual(model.cameraMessage, expectedMessage)
        }
    }

    func testConcurrentCameraActionsShareOneSuspendedPermissionRequest() async throws {
        let access = SuspendedCameraAccess()
        let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })

        let first = Task { await model.requestCamera() }
        try await waitUntil("the first camera permission request to start") {
            access.requestCount == 1
        }
        XCTAssertTrue(model.isRequestingCameraPermission)

        let second = Task { await model.requestCamera() }
        await second.value
        XCTAssertEqual(access.requestCount, 1)

        access.completeRequest(at: 0, result: true, authorization: .authorized)
        await first.value

        XCTAssertFalse(model.isRequestingCameraPermission)
        XCTAssertTrue(model.isCameraPresented)
        XCTAssertNil(model.cameraMessage)
    }

    func testCancelCameraInvalidatesSuspendedPermissionCompletion() async throws {
        let access = SuspendedCameraAccess()
        let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })
        let request = Task { await model.requestCamera() }
        try await waitUntil("the cancellable camera permission request to start") {
            access.requestCount == 1
        }

        model.cancelCamera()
        XCTAssertFalse(model.isRequestingCameraPermission)
        XCTAssertFalse(model.isCameraPresented)

        access.completeRequest(at: 0, result: true, authorization: .authorized)
        await request.value

        XCTAssertFalse(model.isRequestingCameraPermission)
        XCTAssertFalse(model.isCameraPresented)
        XCTAssertNil(model.cameraMessage)
    }

    func testNewCameraActionCannotBeOverwrittenByOldLatePermissionCallback() async throws {
        let access = SuspendedCameraAccess()
        let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })
        let oldRequest = Task { await model.requestCamera() }
        try await waitUntil("the old camera permission request to start") {
            access.requestCount == 1
        }
        model.invalidate()

        let replacementRequest = Task { await model.requestCamera() }
        try await waitUntil("the replacement camera permission request to start") {
            access.requestCount == 2
        }
        access.completeRequest(at: 1, result: true, authorization: .authorized)
        await replacementRequest.value
        XCTAssertTrue(model.isCameraPresented)
        XCTAssertNil(model.cameraMessage)

        access.completeRequest(at: 0, result: false, authorization: .denied)
        await oldRequest.value

        XCTAssertTrue(model.isCameraPresented)
        XCTAssertNil(model.cameraMessage)
        XCTAssertFalse(model.isRequestingCameraPermission)
    }

    func testPermissionCompletionRechecksFreshStatusAndAvailability() async throws {
        let deniedAccess = SuspendedCameraAccess()
        let deniedModel = CaptureAcquisitionModel(cameraAccess: deniedAccess, onSelectImage: { _ in })
        let deniedRequest = Task { await deniedModel.requestCamera() }
        try await waitUntil("the denied permission request to start") {
            deniedAccess.requestCount == 1
        }
        deniedAccess.completeRequest(at: 0, result: true, authorization: .denied)
        await deniedRequest.value
        XCTAssertFalse(deniedModel.isCameraPresented)
        XCTAssertEqual(deniedModel.cameraMessage, .denied)

        let restrictedAccess = SuspendedCameraAccess()
        let restrictedModel = CaptureAcquisitionModel(cameraAccess: restrictedAccess, onSelectImage: { _ in })
        let restrictedRequest = Task { await restrictedModel.requestCamera() }
        try await waitUntil("the restricted permission request to start") {
            restrictedAccess.requestCount == 1
        }
        restrictedAccess.completeRequest(at: 0, result: true, authorization: .restricted)
        await restrictedRequest.value
        XCTAssertFalse(restrictedModel.isCameraPresented)
        XCTAssertEqual(restrictedModel.cameraMessage, .restricted)

        let unavailableAccess = SuspendedCameraAccess()
        let unavailableModel = CaptureAcquisitionModel(cameraAccess: unavailableAccess, onSelectImage: { _ in })
        let unavailableRequest = Task { await unavailableModel.requestCamera() }
        try await waitUntil("the unavailable permission request to start") {
            unavailableAccess.requestCount == 1
        }
        unavailableAccess.completeRequest(
            at: 0,
            result: true,
            authorization: .authorized,
            isAvailable: false
        )
        await unavailableRequest.value
        XCTAssertFalse(unavailableModel.isCameraPresented)
        XCTAssertEqual(unavailableModel.cameraMessage, .unavailable)
    }

    func testPendingCameraPermissionProgressRendersAndCanBeCancelled() async throws {
        let access = SuspendedCameraAccess()
        let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })
        let request = Task { await model.requestCamera() }
        try await waitUntil("camera permission progress to become visible") {
            model.isRequestingCameraPermission
        }

        let view = CaptureView(
            acquisition: model,
            isPreparingPreview: false,
            onCancelPreparation: {}
        )
        let renderer = ImageRenderer(content: view.frame(width: 390, height: 844))
        XCTAssertNotNil(renderer.uiImage)

        model.cancelCamera()
        access.completeRequest(at: 0, result: true, authorization: .authorized)
        await request.value
        XCTAssertFalse(model.isCameraPresented)
    }

    func testPhotoReplacementIgnoresOldLoadAndSelectsOnlyNewestData() async throws {
        let access = CameraAccessStub(isAvailable: false, authorization: .denied)
        var selections: [Data] = []
        let model = CaptureAcquisitionModel(cameraAccess: access) { selections.append($0) }
        let old = ControlledPhotoLoader()
        let replacement = ControlledPhotoLoader()

        model.loadPhoto(using: old)
        try await waitUntil("the old photo load to start") { await old.hasStarted }
        model.loadPhoto(using: replacement)
        try await waitUntil("the replacement photo load to start") { await replacement.hasStarted }

        await old.succeed(Data([0x01]))
        await replacement.succeed(Data([0x02]))
        try await waitUntil("the replacement photo load to finish") { !model.isLoadingPhoto }

        XCTAssertEqual(selections, [Data([0x02])])
        XCTAssertNil(model.photoMessage)
        XCTAssertFalse(model.isLoadingPhoto)
    }

    func testPhotoAndCameraCancellationSelectNothing() async throws {
        let access = CameraAccessStub(isAvailable: true, authorization: .authorized)
        var selections: [Data] = []
        let model = CaptureAcquisitionModel(cameraAccess: access) { selections.append($0) }
        let loader = ControlledPhotoLoader()

        model.loadPhoto(using: loader)
        try await waitUntil("the cancellable photo load to start") { await loader.hasStarted }
        model.cancelPhotoLoad()
        await loader.succeed(Data([0x01]))
        try await waitUntil("the cancelled photo load to become idle") { !model.isLoadingPhoto }
        model.cancelCamera()

        XCTAssertTrue(selections.isEmpty)
        XCTAssertFalse(model.isCameraPresented)
        XCTAssertFalse(model.isLoadingPhoto)
    }

    func testCameraEncodingFailureShowsCautiousErrorAndAlertCanBeDismissed() async {
        let access = CameraAccessStub(isAvailable: true, authorization: .denied)
        let model = CaptureAcquisitionModel(cameraAccess: access, onSelectImage: { _ in })

        model.receiveCapturedImage(nil)
        XCTAssertEqual(model.photoMessage, .unreadable)

        await model.requestCamera()
        XCTAssertEqual(model.cameraMessage, .denied)
        model.dismissCameraMessage()
        XCTAssertNil(model.cameraMessage)
    }

    func testCameraImageAndConsentActionsInvokeTheirOwnedCoordinatorActionsExactlyOnce() {
        let access = CameraAccessStub(isAvailable: true, authorization: .authorized)
        var selected: [Data] = []
        let model = CaptureAcquisitionModel(cameraAccess: access) { selected.append($0) }
        model.receiveCapturedImage(Data([0x03]))
        model.receiveCapturedImage(nil)

        var agreeCount = 0
        var cancelCount = 0
        let actions = ConsentActions(
            agree: { agreeCount += 1 },
            cancel: { cancelCount += 1 }
        )
        actions.agree()
        actions.cancel()

        XCTAssertEqual(selected, [Data([0x03])])
        XCTAssertEqual(agreeCount, 1)
        XCTAssertEqual(cancelCount, 1)
    }

    func testRootRoutingUsesCaptureAndConsentWithoutInventingAResult() throws {
        let selection = SelectedImage(preview: try syntheticPreview())

        XCTAssertEqual(RootRouting.route(for: .capture), .capture)
        XCTAssertEqual(RootRouting.route(for: .consent(selection)), .consent(selection))
        XCTAssertEqual(RootRouting.route(for: .processing(selection)), .processing(selection))
        XCTAssertEqual(RootRouting.route(for: .error(.network)), .error(.network))
    }

    func testInvalidAndFailClosedProductionOriginsConstructWithoutNetworkOrCrash() async {
        CountingURLProtocol.reset()

        let malformed = ProductionComposition.makeCoordinator(
            apiOriginRawValue: "not a URL",
            protocolClasses: [CountingURLProtocol.self]
        )
        let failClosed = ProductionComposition.makeCoordinator(
            apiOriginRawValue: "https://invalid.invalid",
            protocolClasses: [CountingURLProtocol.self]
        )
        await Task.yield()

        XCTAssertEqual(malformed.screen, .capture)
        XCTAssertEqual(failClosed.screen, .capture)
        XCTAssertEqual(malformed.sensitiveStateForTesting, .empty)
        XCTAssertEqual(failClosed.sensitiveStateForTesting, .empty)
        XCTAssertEqual(CountingURLProtocol.requestCount, 0)
    }

    func testBrandAssetsContainSemanticVariantsAndResolveFromAppBundle() throws {
        let assetRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "SumaiGuard/Resources/Assets.xcassets")

        for name in ["BrandForest", "BrandCream", "BrandGold"] {
            let data = try Data(contentsOf: assetRoot.appending(path: "\(name).colorset/Contents.json"))
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            let colors = try XCTUnwrap(object["colors"] as? [[String: Any]])
            XCTAssertGreaterThanOrEqual(colors.count, 4)
            XCTAssertTrue(colors.contains { $0["appearances"] == nil })
            XCTAssertTrue(colors.contains { entry in
                guard let appearances = entry["appearances"] as? [[String: String]] else { return false }
                return appearances.contains { $0["appearance"] == "luminosity" && $0["value"] == "dark" }
            })
            XCTAssertTrue(colors.contains { entry in
                guard let appearances = entry["appearances"] as? [[String: String]] else { return false }
                return appearances.contains { $0["appearance"] == "contrast" && $0["value"] == "high" }
            })
            XCTAssertNotNil(UIColor(named: name, in: .main, compatibleWith: nil))
        }
    }

    func testCaptureConsentAndPrivacyViewsRenderFromSyntheticPixels() throws {
        let acquisition = CaptureAcquisitionModel(
            cameraAccess: CameraAccessStub(isAvailable: false, authorization: .denied),
            onSelectImage: { _ in }
        )
        let selection = SelectedImage(preview: try syntheticPreview())
        let views: [AnyView] = [
            AnyView(CaptureView(
                acquisition: acquisition,
                isPreparingPreview: false,
                onCancelPreparation: {}
            )),
            AnyView(ConsentView(
                selection: selection,
                actions: ConsentActions(agree: {}, cancel: {})
            )),
            AnyView(PrivacySheet()),
        ]

        for view in views {
            let renderer = ImageRenderer(content: view.frame(width: 390, height: 844))
            renderer.scale = 1
            XCTAssertNotNil(renderer.uiImage)
        }
    }

    private func syntheticPreview() throws -> CGImage {
        guard
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: 2,
                height: 2,
                bitsPerComponent: 8,
                bytesPerRow: 8,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ),
            let image = context.makeImage()
        else {
            throw SyntheticPreviewError.creationFailed
        }
        return image
    }

    private func waitUntil(
        _ description: String,
        timeout: Duration = .seconds(2),
        _ condition: @MainActor () async -> Bool
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !(await condition()) {
            guard clock.now < deadline else {
                throw TestWaitError.timedOut(description)
            }
            await Task.yield()
        }
    }
}

@MainActor
private final class CameraAccessStub: CameraAccessProviding {
    let isAvailable: Bool
    private(set) var authorization: CameraAuthorizationState
    let requestResult: Bool
    private(set) var requestCount = 0

    init(
        isAvailable: Bool,
        authorization: CameraAuthorizationState,
        requestResult: Bool = false
    ) {
        self.isAvailable = isAvailable
        self.authorization = authorization
        self.requestResult = requestResult
    }

    func isCameraAvailable() -> Bool { isAvailable }
    func authorizationStatus() -> CameraAuthorizationState { authorization }

    func requestAccess() async -> Bool {
        requestCount += 1
        authorization = requestResult ? .authorized : .denied
        return requestResult
    }
}

@MainActor
private final class SuspendedCameraAccess: CameraAccessProviding {
    private(set) var requestCount = 0
    private var available = true
    private var authorization: CameraAuthorizationState = .notDetermined
    private var continuations: [CheckedContinuation<Bool, Never>?] = []

    func isCameraAvailable() -> Bool { available }
    func authorizationStatus() -> CameraAuthorizationState { authorization }

    func requestAccess() async -> Bool {
        requestCount += 1
        continuations.append(nil)
        let index = continuations.count - 1
        return await withCheckedContinuation { continuation in
            continuations[index] = continuation
        }
    }

    func completeRequest(
        at index: Int,
        result: Bool,
        authorization: CameraAuthorizationState,
        isAvailable: Bool = true
    ) {
        self.authorization = authorization
        available = isAvailable
        guard continuations.indices.contains(index), let continuation = continuations[index] else {
            return
        }
        continuations[index] = nil
        continuation.resume(returning: result)
    }
}

private actor ControlledPhotoLoader: PhotoDataLoading {
    private var started = false
    private var continuation: CheckedContinuation<Data?, any Error>?

    func loadImageData() async throws -> Data? {
        started = true
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    var hasStarted: Bool { started }

    func succeed(_ data: Data?) {
        continuation?.resume(returning: data)
        continuation = nil
    }
}

private final class CountingURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var count = 0

    static var requestCount: Int { lock.withLock { count } }
    static func reset() { lock.withLock { count = 0 } }

    override class func canInit(with request: URLRequest) -> Bool {
        lock.withLock { count += 1 }
        return false
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {}
    override func stopLoading() {}
}

private enum SyntheticPreviewError: Error {
    case creationFailed
}

private enum TestWaitError: Error, CustomStringConvertible {
    case timedOut(String)

    var description: String {
        switch self {
        case let .timedOut(description):
            "Timed out after 2 seconds waiting for \(description)."
        }
    }
}
