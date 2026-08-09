import Foundation
import SwiftUI

enum RootRoute: Equatable {
    case capture
    case consent(SelectedImage)
    case processing(SelectedImage)
    case result(AnalysisResponse)
    case advice(AnalysisResponse)
    case noFindings(AnalysisResponse)
    case notApplicable(String)
    case error(UserFacingError)
}

enum RootRouting {
    static func route(for screen: AppScreen) -> RootRoute {
        switch screen {
        case .capture:
            .capture
        case let .consent(selection):
            .consent(selection)
        case let .processing(selection):
            .processing(selection)
        case let .result(response):
            .result(response)
        case let .advice(response):
            .advice(response)
        case let .noFindings(response):
            .noFindings(response)
        case let .notApplicable(reason):
            .notApplicable(reason)
        case let .error(error):
            .error(error)
        }
    }
}

enum RootPDFRouting {
    static func document(for screen: AppScreen) -> SafetyPDFDocument? {
        guard
            case let .advice(response) = screen,
            let validated = ValidatedPresentationResponse(response: response)
        else {
            return nil
        }
        return try? SafetyPDFDocument(validatedResponse: validated)
    }
}

@MainActor
enum ProductionComposition {
    static func makeCoordinator(bundle: Bundle = .main) -> AppFlowCoordinator {
        let rawValue = bundle.object(forInfoDictionaryKey: "SUMAI_API_ORIGIN") as? String ?? ""
        return makeCoordinator(apiOriginRawValue: rawValue)
    }

    static func makeCoordinator(
        apiOriginRawValue: String,
        protocolClasses: [AnyClass]? = nil
    ) -> AppFlowCoordinator {
        let analyzer: any Analyzing
        if let origin = try? APIOrigin(apiOriginRawValue) {
            analyzer = APIClient(
                origin: origin,
                tokenProvider: FirebaseAppCheckTokenProvider(),
                protocolClasses: protocolClasses
            )
        } else {
            analyzer = FailClosedAnalyzer()
        }
        return AppFlowCoordinator(
            sanitizer: ImageSanitizer(),
            analyzer: analyzer
        )
    }
}

private struct FailClosedAnalyzer: Analyzing {
    func prepareAnalysis() async throws -> any AuthorizedAnalyzing {
        throw APIError.appCheckInvalid
    }
}

struct RootView: View {
    @StateObject private var coordinator: AppFlowCoordinator
    @StateObject private var acquisition: CaptureAcquisitionModel
    @StateObject private var pdfShareController: PDFShareController

    init() {
        let coordinator = ProductionComposition.makeCoordinator()
        _coordinator = StateObject(wrappedValue: coordinator)
        _pdfShareController = StateObject(
            wrappedValue: PDFShareController(
                renderer: SafetyPDFRenderer(),
                cachePDF: coordinator.cachePDF,
                clearCachedPDF: coordinator.clearCachedPDF
            )
        )
        _acquisition = StateObject(
            wrappedValue: CaptureAcquisitionModel { [weak coordinator] data in
                coordinator?.selectImage(data)
            }
        )
    }

    init(
        coordinator: AppFlowCoordinator,
        cameraAccess: any CameraAccessProviding = SystemCameraAccess(),
        pdfRenderer: any SafetyPDFRendering = SafetyPDFRenderer()
    ) {
        _coordinator = StateObject(wrappedValue: coordinator)
        _pdfShareController = StateObject(
            wrappedValue: PDFShareController(
                renderer: pdfRenderer,
                cachePDF: coordinator.cachePDF,
                clearCachedPDF: coordinator.clearCachedPDF
            )
        )
        _acquisition = StateObject(
            wrappedValue: CaptureAcquisitionModel(
                cameraAccess: cameraAccess,
                onSelectImage: { [weak coordinator] data in
                    coordinator?.selectImage(data)
                }
            )
        )
    }

    var body: some View {
        NavigationStack {
            routedContent
        }
        .onChange(of: coordinator.screen) { _, newScreen in
            if RootPDFRouting.document(for: newScreen) == nil {
                pdfShareController.clear()
            }
        }
        .sheet(
            isPresented: Binding(
                get: { pdfShareController.payload != nil },
                set: { isPresented in
                    if !isPresented {
                        pdfShareController.shareSheetDidDismiss()
                    }
                }
            ),
            onDismiss: pdfShareController.shareSheetDidDismiss
        ) {
            if let payload = pdfShareController.payload {
                ShareSheet(
                    payload: payload,
                    onComplete: pdfShareController.activityDidComplete
                )
            }
        }
    }

    @ViewBuilder
    private var routedContent: some View {
        switch RootRouting.route(for: coordinator.screen) {
        case .capture:
            CaptureView(
                acquisition: acquisition,
                isPreparingPreview: coordinator.isPreparingPreview,
                onCancelPreparation: coordinator.returnHome
            )
        case let .consent(selection):
            ConsentView(
                selection: selection,
                actions: ConsentActions(
                    agree: coordinator.agreeAndAnalyze,
                    cancel: coordinator.cancelConsent
                )
            )
        case let .processing(selection):
            ProcessingView(
                selection: selection,
                actions: ProcessingActions(
                    cancelProcessing: coordinator.cancelProcessing
                )
            )
        case let .result(response):
            ResultView(
                response: response,
                actions: ResultActions(
                    showAdvice: coordinator.showAdvice,
                    returnHome: coordinator.returnHome
                )
            )
        case let .advice(response):
            let document = RootPDFRouting.document(for: .advice(response))
            AdviceView(
                response: response,
                actions: AdviceActions(
                    returnHome: {
                        pdfShareController.returnHome()
                        coordinator.returnHome()
                    },
                    shareAdvice: document.map { document in
                        { pdfShareController.generate(document) }
                    },
                    cancelPDF: pdfShareController.cancelGeneration
                ),
                pdfState: pdfShareController.viewState
            )
        case .noFindings:
            NoFindingsView(
                actions: NoFindingsActions(returnHome: coordinator.returnHome)
            )
        case let .notApplicable(reason):
            NotApplicableView(
                reason: reason,
                actions: NotApplicableActions(returnHome: coordinator.returnHome)
            )
        case let .error(error):
            ErrorView(
                error: error,
                actions: ErrorActions(
                    retry: coordinator.retry,
                    returnHome: coordinator.returnHome
                )
            )
        }
    }
}
