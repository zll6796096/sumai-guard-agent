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

    init() {
        let coordinator = ProductionComposition.makeCoordinator()
        _coordinator = StateObject(wrappedValue: coordinator)
        _acquisition = StateObject(
            wrappedValue: CaptureAcquisitionModel { [weak coordinator] data in
                coordinator?.selectImage(data)
            }
        )
    }

    init(
        coordinator: AppFlowCoordinator,
        cameraAccess: any CameraAccessProviding = SystemCameraAccess()
    ) {
        _coordinator = StateObject(wrappedValue: coordinator)
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
        case .processing:
            InterimProcessingView(onCancel: coordinator.cancelProcessing)
        case .result:
            InterimTerminalView(
                heading: "確認結果を受け取りました",
                explanation: "結果の詳しい表示を準備しています。ここでは住まいの安全を判断できません。",
                onReturnHome: coordinator.returnHome
            )
        case .advice:
            InterimTerminalView(
                heading: "次にできること",
                explanation: "相談先ごとの表示を準備しています。専門家の判断に代わるものではありません。",
                onReturnHome: coordinator.returnHome
            )
        case .noFindings:
            InterimTerminalView(
                heading: "明らかな注意候補は確認できませんでした",
                explanation: "写真で見える範囲だけの結果です。住まい全体の安全を示すものではありません。",
                onReturnHome: coordinator.returnHome
            )
        case let .notApplicable(reason):
            InterimTerminalView(
                heading: "この写真では確認できませんでした",
                explanation: reason,
                onReturnHome: coordinator.returnHome
            )
        case let .error(error):
            InterimErrorView(
                message: error.messageJA,
                onRetry: coordinator.retry,
                onReturnHome: coordinator.returnHome
            )
        }
    }
}

private struct InterimProcessingView: View {
    let onCancel: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            ProgressView()
                .controlSize(.large)
            Text("写真で見える注意候補を確認しています")
                .font(.headline)
                .multilineTextAlignment(.center)
            Text("処理中は写真を保存しません。")
                .font(.body)
                .foregroundStyle(.secondary)
            Button("確認を中止する", action: onCancel)
                .frame(minHeight: 44)
                .accessibilityIdentifier("processing.cancel")
        }
        .padding(24)
        .navigationTitle("確認中")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct InterimTerminalView: View {
    let heading: String
    let explanation: String
    let onReturnHome: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label(heading, systemImage: "house")
        } description: {
            Text(explanation)
        } actions: {
            Button("最初の画面に戻る", action: onReturnHome)
                .frame(minHeight: 44)
                .accessibilityIdentifier("terminal.returnHome")
        }
        .navigationTitle("実家あんしんチェック")
    }
}

private struct InterimErrorView: View {
    let message: String
    let onRetry: () -> Void
    let onReturnHome: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label("処理を完了できませんでした", systemImage: "exclamationmark.circle")
        } description: {
            Text(message)
        } actions: {
            VStack(spacing: 12) {
                Button("写真を確認してもう一度試す", action: onRetry)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("error.retry")
                Button("最初の画面に戻る", action: onReturnHome)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("error.returnHome")
            }
        }
        .navigationTitle("実家あんしんチェック")
    }
}
