import Combine
import CoreGraphics
import Foundation
import ImageIO

final class SelectedImage: Equatable {
    let id: UUID
    let preview: CGImage

    init(id: UUID = UUID(), preview: CGImage) {
        self.id = id
        self.preview = preview
    }

    static func == (lhs: SelectedImage, rhs: SelectedImage) -> Bool {
        lhs.id == rhs.id
    }
}

struct PreviewLimits: Equatable, Sendable {
    let maxLongSide: Int
    let maxSourcePixels: Int

    static let production = PreviewLimits(
        maxLongSide: 512,
        maxSourcePixels: ImageSanitizer.maxSourcePixels
    )

    init(maxLongSide: Int, maxSourcePixels: Int) {
        precondition(maxLongSide > 0)
        precondition(maxSourcePixels >= 0)
        self.maxLongSide = maxLongSide
        self.maxSourcePixels = maxSourcePixels
    }
}

enum ImagePreviewError: Error, Equatable, Sendable {
    case invalidImage
    case sourceTooLarge
}

protocol PreviewRendering: Sendable {
    func renderPreview(from sourceData: Data) async throws -> CGImage
}

actor ImagePreviewRenderer: PreviewRendering {
    private let limits: PreviewLimits

    init(limits: PreviewLimits = .production) {
        self.limits = limits
    }

    func renderPreview(from sourceData: Data) throws -> CGImage {
        try Task.checkCancellation()
        guard !sourceData.isEmpty else {
            throw ImagePreviewError.invalidImage
        }

        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard
            let source = CGImageSourceCreateWithData(sourceData as CFData, sourceOptions),
            CGImageSourceGetCount(source) > 0,
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, sourceOptions)
                as? [CFString: Any],
            let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
            let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
            width > 0,
            height > 0
        else {
            throw ImagePreviewError.invalidImage
        }

        guard width <= limits.maxSourcePixels / height else {
            throw ImagePreviewError.sourceTooLarge
        }
        try Task.checkCancellation()

        let thumbnailOptions: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: limits.maxLongSide,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(
            source,
            0,
            thumbnailOptions as CFDictionary
        ) else {
            throw ImagePreviewError.invalidImage
        }
        try Task.checkCancellation()

        return try Self.redraw(thumbnail)
    }

    private static func redraw(_ source: CGImage) throws -> CGImage {
        let width = source.width
        let height = source.height
        let bytesPerPixel = 4
        guard
            width > 0,
            height > 0,
            width <= Int.max / bytesPerPixel,
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * bytesPerPixel,
                space: colorSpace,
                bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue
                    | CGImageAlphaInfo.premultipliedLast.rawValue
            )
        else {
            throw ImagePreviewError.invalidImage
        }

        context.interpolationQuality = .high
        context.draw(source, in: CGRect(x: 0, y: 0, width: width, height: height))
        guard let preview = context.makeImage() else {
            throw ImagePreviewError.invalidImage
        }
        return preview
    }
}

enum UserFacingError: Equatable, Sendable {
    case invalidImage
    case imageTooLarge
    case verificationUnavailable
    case serviceBusy
    case serviceUnavailable
    case invalidResponse
    case network
    case unexpected

    var messageJA: String {
        switch self {
        case .invalidImage:
            "この写真を読み取れませんでした。別の写真を選んでください。"
        case .imageTooLarge:
            "写真のサイズが大きすぎます。別の写真を選んでください。"
        case .verificationUnavailable:
            "アプリの確認を完了できませんでした。時間をおいてもう一度お試しください。"
        case .serviceBusy:
            "ただいま利用が集中しています。時間をおいてもう一度お試しください。"
        case .serviceUnavailable:
            "現在、解析サービスを利用できません。時間をおいてもう一度お試しください。"
        case .invalidResponse:
            "解析結果を安全に確認できませんでした。もう一度お試しください。"
        case .network:
            "通信できませんでした。接続を確認してもう一度お試しください。"
        case .unexpected:
            "処理を完了できませんでした。時間をおいてもう一度お試しください。"
        }
    }
}

enum AppScreen: Equatable {
    case capture
    case consent(SelectedImage)
    case processing(SelectedImage)
    case result(AnalysisResponse)
    case advice(AnalysisResponse)
    case noFindings(AnalysisResponse)
    case notApplicable(String)
    case error(UserFacingError)

    var accessibilitySummaryJA: String {
        switch self {
        case .capture:
            "住まいの写真を1枚選びます。"
        case .consent:
            "写真を送信する前に内容を確認し、同意を選べます。"
        case .processing:
            "写真で見える注意候補を確認しています。"
        case .result:
            "写真で確認できた注意箇所があります。"
        case .advice:
            "安全のためにできることを相談先別に確認できます。"
        case .noFindings:
            "写真で見える範囲では、明らかな注意候補を確認できませんでした。写真だけで住まい全体の安全は判断できません。"
        case let .notApplicable(reason):
            reason
        case let .error(error):
            error.messageJA
        }
    }
}

protocol ImageSanitizing: Sendable {
    func sanitize(_ sourceData: Data) async throws -> SanitizedImage
}

extension ImageSanitizer: ImageSanitizing {}

struct SensitiveStateSnapshot: Equatable, Sendable {
    let hasSource: Bool
    let hasSanitizedImage: Bool
    let hasResponse: Bool
    let hasPDF: Bool
    let hasActiveTask: Bool

    static let empty = SensitiveStateSnapshot(
        hasSource: false,
        hasSanitizedImage: false,
        hasResponse: false,
        hasPDF: false,
        hasActiveTask: false
    )
}

@MainActor
final class AppFlowCoordinator: ObservableObject {
    @Published private(set) var screen: AppScreen = .capture
    @Published private(set) var isPreparingPreview = false

    private let sanitizer: any ImageSanitizing
    private let analyzer: any Analyzing
    private let previewRenderer: any PreviewRendering

    private var selectedImage: SelectedImage?
    private var sourceData: Data?
    private var response: AnalysisResponse?
    private var pdfData: Data?
    private var activeTask: Task<Void, Never>?
    private var previewTask: Task<Void, Never>?
    private var pendingPreviewSource: PreviewSourceBox?
    private var inFlightTaskCount = 0
    private var operationID = UUID()

    init(
        sanitizer: any ImageSanitizing,
        analyzer: any Analyzing,
        previewRenderer: any PreviewRendering = ImagePreviewRenderer()
    ) {
        self.sanitizer = sanitizer
        self.analyzer = analyzer
        self.previewRenderer = previewRenderer
    }

    func selectImage(_ data: Data) {
        invalidateActiveOperation()
        clearSensitiveState()
        screen = .capture

        let operationID = UUID()
        self.operationID = operationID
        let sourceBox = PreviewSourceBox(data: data)
        pendingPreviewSource = sourceBox
        isPreparingPreview = true
        let previewRenderer = self.previewRenderer
        previewTask = Task { [weak self, previewRenderer, sourceBox] in
            do {
                let preview = try await Self.renderPreview(
                    using: previewRenderer,
                    sourceBox: sourceBox
                )
                try Task.checkCancellation()
                self?.finishPreview(
                    preview,
                    sourceBox: sourceBox,
                    operationID: operationID
                )
            } catch is CancellationError {
                self?.finishPreviewCancellation(operationID: operationID)
            } catch {
                self?.finishPreviewFailure(error, operationID: operationID)
            }
        }
    }

    func agreeAndAnalyze() {
        guard
            activeTask == nil,
            case let .consent(selection) = screen,
            selectedImage == selection,
            sourceData != nil
        else {
            return
        }

        response = nil
        pdfData = nil
        let operationID = UUID()
        self.operationID = operationID
        screen = .processing(selection)

        let sanitizer = self.sanitizer
        let analyzer = self.analyzer
        let selectionID = selection.id
        let coordinatorReference = WeakCoordinatorReference(self)
        inFlightTaskCount += 1
        activeTask = Task { [analyzer, coordinatorReference, operationID, sanitizer, selectionID] in
            let outcome = await Self.runAnalysis(
                analyzer: analyzer,
                sanitizer: sanitizer,
                coordinatorReference: coordinatorReference,
                operationID: operationID,
                selectionID: selectionID
            )
            switch outcome {
            case let .response(response):
                coordinatorReference.finish(
                    response: response,
                    operationID: operationID,
                    selectionID: selectionID
                )
            case let .failure(error):
                coordinatorReference.finish(
                    error: error,
                    operationID: operationID,
                    selectionID: selectionID
                )
            case .cancelled:
                coordinatorReference.finishCancellation(operationID: operationID)
            }
            coordinatorReference.operationFinished()
        }
    }

    func cancelConsent() {
        guard case .consent = screen else {
            return
        }
        resetToCapture()
    }

    func cancelProcessing() {
        guard case .processing = screen else {
            return
        }
        resetToCapture()
    }

    func retry() {
        guard
            case .error = screen,
            activeTask == nil,
            let selectedImage,
            sourceData != nil
        else {
            return
        }

        response = nil
        pdfData = nil
        operationID = UUID()
        screen = .consent(selectedImage)
    }

    func showAdvice() {
        guard
            case let .result(result) = screen,
            !result.isNotApplicable,
            !result.findings.isEmpty,
            !result.actionPlan.isEmpty,
            response == result
        else {
            return
        }
        screen = .advice(result)
    }

    func returnHome() {
        resetToCapture()
    }

    func cachePDF(_ data: Data) {
        guard case .advice = screen else {
            return
        }
        pdfData = data
    }

    var sensitiveStateForTesting: SensitiveStateSnapshot {
        SensitiveStateSnapshot(
            hasSource: sourceData != nil,
            hasSanitizedImage: false,
            hasResponse: response != nil,
            hasPDF: pdfData != nil,
            hasActiveTask: activeTask != nil || previewTask != nil
        )
    }

    var inFlightTaskCountForTesting: Int {
        inFlightTaskCount
    }

    private final class WeakCoordinatorReference: @unchecked Sendable {
        weak var coordinator: AppFlowCoordinator?

        init(_ coordinator: AppFlowCoordinator) {
            self.coordinator = coordinator
        }

        @MainActor
        func sourceData(operationID: UUID, selectionID: UUID) -> Data? {
            guard
                let coordinator,
                coordinator.isCurrent(operationID, selectionID: selectionID)
            else {
                return nil
            }
            return coordinator.sourceData
        }

        @MainActor
        func finish(
            response: AnalysisResponse,
            operationID: UUID,
            selectionID: UUID
        ) {
            guard coordinator?.isCurrent(operationID, selectionID: selectionID) == true else {
                return
            }
            coordinator?.finish(response, operationID: operationID)
        }

        @MainActor
        func finish(
            error: UserFacingError,
            operationID: UUID,
            selectionID: UUID
        ) {
            guard coordinator?.isCurrent(operationID, selectionID: selectionID) == true else {
                return
            }
            coordinator?.finishFailure(error, operationID: operationID)
        }

        @MainActor
        func finishCancellation(operationID: UUID) {
            coordinator?.finishCancellation(operationID: operationID)
        }

        @MainActor
        func operationFinished() {
            guard let coordinator, coordinator.inFlightTaskCount > 0 else {
                return
            }
            coordinator.inFlightTaskCount -= 1
        }
    }
}

private final class PreviewSourceBox: @unchecked Sendable {
    private let lock = NSLock()
    private var data: Data?

    init(data: Data) {
        self.data = data
    }

    func snapshot() throws -> Data {
        try lock.withLock {
            guard let data else {
                throw CancellationError()
            }
            return data
        }
    }

    func take() -> Data? {
        lock.withLock {
            defer { data = nil }
            return data
        }
    }

    func clear() {
        lock.withLock {
            data = nil
        }
    }
}

private enum AnalysisTaskOutcome: Sendable {
    case response(AnalysisResponse)
    case failure(UserFacingError)
    case cancelled
}

private extension AppFlowCoordinator {
    nonisolated static func renderPreview(
        using renderer: any PreviewRendering,
        sourceBox: PreviewSourceBox
    ) async throws -> CGImage {
        let sourceData = try sourceBox.snapshot()
        return try await renderer.renderPreview(from: sourceData)
    }

    func finishPreview(
        _ preview: CGImage,
        sourceBox: PreviewSourceBox,
        operationID: UUID
    ) {
        guard
            self.operationID == operationID,
            previewTask != nil,
            pendingPreviewSource === sourceBox,
            let sourceData = sourceBox.take()
        else {
            return
        }

        previewTask = nil
        pendingPreviewSource = nil
        isPreparingPreview = false
        let selection = SelectedImage(preview: preview)
        selectedImage = selection
        self.sourceData = sourceData
        screen = .consent(selection)
    }

    func finishPreviewFailure(_ error: any Error, operationID: UUID) {
        guard self.operationID == operationID, previewTask != nil else {
            return
        }
        pendingPreviewSource?.clear()
        pendingPreviewSource = nil
        previewTask = nil
        isPreparingPreview = false
        if error as? ImagePreviewError == .sourceTooLarge {
            screen = .error(.imageTooLarge)
        } else {
            screen = .error(.invalidImage)
        }
    }

    func finishPreviewCancellation(operationID: UUID) {
        guard self.operationID == operationID else {
            return
        }
        resetToCapture()
    }

    nonisolated private static func runAnalysis(
        analyzer: any Analyzing,
        sanitizer: any ImageSanitizing,
        coordinatorReference: WeakCoordinatorReference,
        operationID: UUID,
        selectionID: UUID
    ) async -> AnalysisTaskOutcome {
        do {
            let authorizedAnalyzer = try await analyzer.prepareAnalysis()
            try Task.checkCancellation()
            let sanitizedImage = try await sanitizeCurrentSource(
                using: sanitizer,
                coordinatorReference: coordinatorReference,
                operationID: operationID,
                selectionID: selectionID
            )
            try Task.checkCancellation()
            let response = try await authorizedAnalyzer.analyze(
                image: sanitizedImage,
                roomHint: "auto"
            )
            try Task.checkCancellation()
            return .response(response)
        } catch is CancellationError {
            return .cancelled
        } catch let error as APIError where error == .cancelled {
            return .cancelled
        } catch {
            return .failure(userFacingError(for: error))
        }
    }

    nonisolated private static func sanitizeCurrentSource(
        using sanitizer: any ImageSanitizing,
        coordinatorReference: WeakCoordinatorReference,
        operationID: UUID,
        selectionID: UUID
    ) async throws -> SanitizedImage {
        guard let sourceData = await coordinatorReference.sourceData(
            operationID: operationID,
            selectionID: selectionID
        ) else {
            throw CancellationError()
        }
        return try await sanitizer.sanitize(sourceData)
    }

    func isCurrent(_ operationID: UUID, selectionID: UUID) -> Bool {
        self.operationID == operationID
            && selectedImage?.id == selectionID
            && activeTask != nil
            && {
                guard case let .processing(selection) = screen else {
                    return false
                }
                return selection.id == selectionID
            }()
    }

    func finish(_ newResponse: AnalysisResponse, operationID: UUID) {
        guard self.operationID == operationID else {
            return
        }

        if !newResponse.isNotApplicable {
            let hasFindings = !newResponse.findings.isEmpty
            let hasActions = !newResponse.actionPlan.isEmpty
            guard hasFindings == hasActions else {
                finishFailure(.invalidResponse, operationID: operationID)
                return
            }
        }

        activeTask = nil
        sourceData = nil
        selectedImage = nil
        pdfData = nil
        response = newResponse

        if newResponse.isNotApplicable {
            let reason = newResponse.notApplicableReasonJA?.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let reason, !reason.isEmpty else {
                response = nil
                screen = .error(.invalidResponse)
                return
            }
            screen = .notApplicable(reason)
        } else if newResponse.findings.isEmpty {
            screen = .noFindings(newResponse)
        } else {
            screen = .result(newResponse)
        }
    }

    func finishFailure(_ error: UserFacingError, operationID: UUID) {
        guard self.operationID == operationID, activeTask != nil else {
            return
        }
        activeTask = nil
        response = nil
        pdfData = nil
        screen = .error(error)
    }

    func finishCancellation(operationID: UUID) {
        guard self.operationID == operationID else {
            return
        }
        resetToCapture()
    }

    func resetToCapture() {
        invalidateActiveOperation()
        clearSensitiveState()
        screen = .capture
    }

    func invalidateActiveOperation() {
        operationID = UUID()
        activeTask?.cancel()
        activeTask = nil
        previewTask?.cancel()
        previewTask = nil
        pendingPreviewSource?.clear()
        pendingPreviewSource = nil
        isPreparingPreview = false
    }

    func clearSensitiveState() {
        selectedImage = nil
        sourceData = nil
        response = nil
        pdfData = nil
    }

    nonisolated static func userFacingError(for error: any Error) -> UserFacingError {
        if let sanitizerError = error as? ImageSanitizerError {
            switch sanitizerError {
            case .invalidImage, .encodingFailed:
                return .invalidImage
            case .sourceTooLarge, .outputTooLarge:
                return .imageTooLarge
            }
        }

        guard let apiError = error as? APIError else {
            return .unexpected
        }
        switch apiError {
        case .invalidImage:
            return .invalidImage
        case .appCheckInvalid:
            return .verificationUnavailable
        case .imageTooLarge:
            return .imageTooLarge
        case .serviceLimited:
            return .serviceBusy
        case .geminiUnavailable:
            return .serviceUnavailable
        case .internalError, .invalidResponse:
            return .invalidResponse
        case .network:
            return .network
        case .cancelled:
            return .unexpected
        }
    }
}
