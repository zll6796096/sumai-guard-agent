import Foundation
import SwiftUI
import UniformTypeIdentifiers
import UIKit

final class PDFActivityItemSource: NSObject, UIActivityItemSource, @unchecked Sendable {
    private let data: Data

    init(data: Data) {
        self.data = data
        super.init()
    }

    var dataForTesting: Data {
        data
    }

    func activityViewControllerPlaceholderItem(_ activityViewController: UIActivityViewController) -> Any {
        Data()
    }

    func activityViewController(
        _ activityViewController: UIActivityViewController,
        itemForActivityType activityType: UIActivity.ActivityType?
    ) -> Any? {
        data
    }

    func activityViewController(
        _ activityViewController: UIActivityViewController,
        dataTypeIdentifierForActivityType activityType: UIActivity.ActivityType?
    ) -> String {
        UTType.pdf.identifier
    }

    func activityViewController(
        _ activityViewController: UIActivityViewController,
        subjectForActivityType activityType: UIActivity.ActivityType?
    ) -> String {
        "実家あんしんチェック 安全のためにできること"
    }
}

@MainActor
final class ShareCompletionGate {
    private var itemSource: PDFActivityItemSource?
    private var completion: (() -> Void)?

    init(itemSource: PDFActivityItemSource, completion: @escaping () -> Void) {
        self.itemSource = itemSource
        self.completion = completion
    }

    func finish() {
        guard let completion else {
            return
        }
        self.completion = nil
        itemSource = nil
        completion()
    }
}

@MainActor
struct PDFSharePayload: Identifiable {
    let id = UUID()
    let itemSource: PDFActivityItemSource
}

enum PDFShareViewState: Equatable, Sendable {
    case idle
    case generating
    case failed(String)

    var isShareButtonDisabled: Bool {
        self == .generating
    }

    var visibleText: String {
        switch self {
        case .idle:
            ""
        case .generating:
            "テキストPDFを作成しています"
        case let .failed(message):
            message
        }
    }
}

@MainActor
final class PDFShareController: ObservableObject {
    static let safeErrorMessage = "PDFを作成できませんでした。時間をおいてもう一度お試しください。"

    @Published private(set) var viewState: PDFShareViewState = .idle
    @Published private(set) var payload: PDFSharePayload?

    private let renderer: any SafetyPDFRendering
    private let cachePDF: (Data) -> Void
    private let clearCachedPDF: () -> Void
    private var renderTask: Task<Void, Never>?
    private var generationID = UUID()

    init(
        renderer: any SafetyPDFRendering,
        cachePDF: @escaping (Data) -> Void,
        clearCachedPDF: @escaping () -> Void
    ) {
        self.renderer = renderer
        self.cachePDF = cachePDF
        self.clearCachedPDF = clearCachedPDF
    }

    var isGenerating: Bool {
        viewState == .generating
    }

    var isShareButtonDisabled: Bool {
        viewState.isShareButtonDisabled
    }

    var errorMessage: String? {
        guard case let .failed(message) = viewState else {
            return nil
        }
        return message
    }

    func generate(_ document: SafetyPDFDocument) {
        invalidateGeneration()
        let generationID = UUID()
        self.generationID = generationID
        viewState = .generating
        let renderer = self.renderer
        renderTask = Task { [weak self, document, generationID, renderer] in
            do {
                let data = try await renderer.render(document)
                try Task.checkCancellation()
                self?.finish(data: data, generationID: generationID)
            } catch is CancellationError {
                self?.finishCancellation(generationID: generationID)
            } catch {
                self?.finishFailure(generationID: generationID)
            }
        }
    }

    func cancelGeneration() {
        invalidateGeneration()
    }

    func activityDidComplete() {
        invalidateGeneration()
    }

    func shareSheetDidDismiss() {
        invalidateGeneration()
    }

    func returnHome() {
        invalidateGeneration()
    }

    func clear() {
        invalidateGeneration()
    }

    private func finish(data: Data, generationID: UUID) {
        guard self.generationID == generationID, renderTask != nil else {
            return
        }
        renderTask = nil
        guard data.starts(with: Data("%PDF".utf8)) else {
            finishFailure(generationID: generationID, requireActiveTask: false)
            return
        }
        cachePDF(data)
        payload = PDFSharePayload(itemSource: PDFActivityItemSource(data: data))
        viewState = .idle
    }

    private func finishCancellation(generationID: UUID) {
        guard self.generationID == generationID else {
            return
        }
        renderTask = nil
        clearPayloadAndCache()
        viewState = .idle
    }

    private func finishFailure(generationID: UUID, requireActiveTask: Bool = true) {
        guard
            self.generationID == generationID,
            !requireActiveTask || renderTask != nil
        else {
            return
        }
        renderTask = nil
        clearPayloadAndCache()
        viewState = .failed(Self.safeErrorMessage)
    }

    private func invalidateGeneration() {
        generationID = UUID()
        renderTask?.cancel()
        renderTask = nil
        clearPayloadAndCache()
        viewState = .idle
    }

    private func clearPayloadAndCache() {
        payload = nil
        clearCachedPDF()
    }
}

struct ShareSheet: UIViewControllerRepresentable {
    let payload: PDFSharePayload
    let onComplete: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(itemSource: payload.itemSource, onComplete: onComplete)
    }

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(
            activityItems: [payload.itemSource],
            applicationActivities: nil
        )
        controller.completionWithItemsHandler = { _, _, _, _ in
            Task { @MainActor in
                context.coordinator.finish()
            }
        }
        controller.presentationController?.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, UIAdaptivePresentationControllerDelegate {
        private let gate: ShareCompletionGate

        init(itemSource: PDFActivityItemSource, onComplete: @escaping () -> Void) {
            gate = ShareCompletionGate(itemSource: itemSource, completion: onComplete)
        }

        func finish() {
            gate.finish()
        }

        func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
            finish()
        }
    }
}
