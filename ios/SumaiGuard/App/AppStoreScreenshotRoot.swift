#if DEBUG
import SwiftUI
import UIKit

enum AppStoreScreenshotScene: String {
    case capture
    case visibleRisks
    case actionTiers
    case consent
    case sharePDF

    static var current: AppStoreScreenshotScene? {
        guard let rawValue = ProcessInfo.processInfo.environment["SUMAI_SCREENSHOT_SCENE"] else {
            return nil
        }
        return AppStoreScreenshotScene(rawValue: rawValue)
    }
}

@MainActor
struct AppStoreScreenshotRoot: View {
    let scene: AppStoreScreenshotScene

    var body: some View {
        NavigationStack {
            switch scene {
            case .capture:
                ScreenshotCaptureView()
            case .visibleRisks:
                ResultView(
                    response: AppStoreScreenshotFixture.response,
                    actions: ResultActions(showAdvice: {}, returnHome: {})
                )
            case .actionTiers:
                AdviceView(
                    response: AppStoreScreenshotFixture.response,
                    actions: AdviceActions(returnHome: {}, shareAdvice: {})
                )
            case .consent:
                ConsentView(
                    selection: AppStoreScreenshotFixture.selection,
                    actions: ConsentActions(agree: {}, cancel: {})
                )
            case .sharePDF:
                ScreenshotPDFShareView()
            }
        }
        .environment(\.locale, Locale(identifier: "ja_JP"))
        .preferredColorScheme(.light)
    }
}

@MainActor
private struct ScreenshotCaptureView: View {
    @StateObject private var acquisition: CaptureAcquisitionModel

    init() {
        _acquisition = StateObject(
            wrappedValue: CaptureAcquisitionModel(
                cameraAccess: ScreenshotCameraAccess(),
                onSelectImage: { _ in }
            )
        )
    }

    var body: some View {
        CaptureView(
            acquisition: acquisition,
            isPreparingPreview: false,
            onCancelPreparation: {}
        )
    }
}

@MainActor
private final class ScreenshotCameraAccess: CameraAccessProviding {
    func isCameraAvailable() -> Bool { false }
    func authorizationStatus() -> CameraAuthorizationState { .denied }
    func requestAccess() async -> Bool { false }
}

@MainActor
private struct ScreenshotPDFShareView: View {
    @State private var presentsShareSheet = false

    private let payload = PDFSharePayload(
        itemSource: PDFActivityItemSource(
            data: Data("%PDF-1.4\n% 架空の相談用テキストPDF\n%%EOF".utf8)
        )
    )

    var body: some View {
        AdviceView(
            response: AppStoreScreenshotFixture.response,
            actions: AdviceActions(returnHome: {}, shareAdvice: {})
        )
        .sheet(isPresented: $presentsShareSheet) {
            ShareSheet(payload: payload, onComplete: {})
        }
        .task {
            try? await Task.sleep(for: .milliseconds(450))
            presentsShareSheet = true
        }
    }
}

@MainActor
private enum AppStoreScreenshotFixture {
    static let selection = SelectedImage(preview: sourceImage.cgImage!)

    static let response = AnalysisResponse(
        analysisID: "fictional-analysis",
        roomType: .genkan,
        overallRiskLevel: .high,
        findings: [
            RiskFinding(
                id: "fictional-rug",
                riskType: "loose_mat",
                labelJA: "架空のマットのめくれ",
                descriptionJA: "合成画像では、マットの端が浮いて見えます。",
                severity: 4,
                confidence: 0.82,
                bbox: BoundingBox(x: 0.10, y: 0.55, w: 0.32, h: 0.20),
                displayBBox: BoundingBox(x: 0.08, y: 0.53, w: 0.36, h: 0.24),
                evidenceSourceIDs: ["fictional-mat"],
                evidenceJA: "架空の玄関床にあるマット端を根拠にしています。",
                basisLabelJA: "見える段差候補",
                basisSummaryJA: "写真で確認できる範囲に小さな段差候補があります。",
                needsHumanConfirmation: true,
                ontologyKey: "floor.loose_mat",
                ontologyRuleKind: .visibleHazard
            ),
            RiskFinding(
                id: "fictional-wall",
                riskType: "expected_handrail",
                labelJA: "手すりの現地確認候補",
                descriptionJA: "写真だけでは設置の必要性や可否を判断できません。",
                severity: 2,
                confidence: 0.61,
                bbox: BoundingBox(x: 0.70, y: 0.15, w: 0.15, h: 0.50),
                displayBBox: nil,
                evidenceSourceIDs: ["fictional-wall"],
                evidenceJA: "架空の壁面範囲を根拠にしています。",
                basisLabelJA: "設備の確認候補",
                basisSummaryJA: "必要性や設置可否は写真だけでは判断できません。",
                needsHumanConfirmation: true,
                ontologyKey: "entrance.handrail",
                ontologyRuleKind: .expectedFeature
            ),
        ],
        actionPlan: ActionPlan(
            familyNoCost: [
                ActionItem(
                    id: "fictional-family",
                    riskID: "fictional-rug",
                    tier: .familyNoCost,
                    titleJA: "マットを一時的に外す",
                    descriptionJA: "安全に動かせる場合だけ、家族で通路から外します。",
                    whyJA: "見えている段差候補を減らすためです。",
                    costLevel: .zero,
                    requiresProfessional: false,
                    disclaimerJA: "無理に動かさず、現地の状態を確認してください。"
                )
            ],
            careManagerPurchase: [
                ActionItem(
                    id: "fictional-care",
                    riskID: "fictional-rug",
                    tier: .careManagerPurchase,
                    titleJA: "滑り止め用品を相談する",
                    descriptionJA: "購入や福祉用具の適否を専門職に相談します。",
                    whyJA: "環境に合う用品か写真だけでは判断できないためです。",
                    costLevel: .low,
                    requiresProfessional: true,
                    disclaimerJA: "製品の適合性は専門職に確認してください。"
                )
            ],
            contractorConstruction: [
                ActionItem(
                    id: "fictional-contractor",
                    riskID: "fictional-wall",
                    tier: .contractorConstruction,
                    titleJA: "手すり設置の現地確認",
                    descriptionJA: "壁の下地や動線を専門施工者に確認してもらいます。",
                    whyJA: "施工可否と位置は写真だけでは判断できないためです。",
                    costLevel: .high,
                    requiresProfessional: true,
                    disclaimerJA: "施工判断や見積もりは専門事業者に依頼してください。"
                )
            ]
        ),
        annotatedImageBase64: pngBase64(annotatedImage),
        improvementImageBase64: pngBase64(improvementImage),
        riskSummaryMarkdown: "架空の注意候補です。",
        familyActionsMarkdown: "家族で安全に確認します。",
        careManagerActionsMarkdown: "福祉用具の適否を相談します。",
        contractorActionsMarkdown: "施工可否を現地確認します。",
        disclaimerJA: "医療・介護認定・保険・法令適合・施工可否の判断に代わるものではありません。",
        mode: "fictional",
        isHomeEnvironment: true,
        isNotApplicable: false,
        notApplicableReasonJA: nil,
        model: "fictional",
        resultKey: "fictional",
        semanticHash: "fictional",
        schemaVersion: "2.0.0",
        ontologyVersion: "1.0.0",
        preprocessVersion: "1.0.0",
        inferenceConfigVersion: "1.0.0",
        stageTimingsMS: [:]
    )

    private static let sourceImage = makeRoomImage(showRiskBoxes: false, showHandrail: false)
    private static let annotatedImage = makeRoomImage(showRiskBoxes: true, showHandrail: false)
    private static let improvementImage = makeRoomImage(showRiskBoxes: false, showHandrail: true)

    private static func pngBase64(_ image: UIImage) -> String {
        image.pngData()!.base64EncodedString()
    }

    private static func makeRoomImage(showRiskBoxes: Bool, showHandrail: Bool) -> UIImage {
        let size = CGSize(width: 1_000, height: 720)
        return UIGraphicsImageRenderer(size: size).image { context in
            UIColor(red: 0.91, green: 0.88, blue: 0.78, alpha: 1).setFill()
            context.fill(CGRect(origin: .zero, size: size))

            UIColor(red: 0.84, green: 0.78, blue: 0.64, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 420, width: 1_000, height: 300))

            UIColor(red: 0.28, green: 0.36, blue: 0.31, alpha: 1).setFill()
            context.fill(CGRect(x: 650, y: 95, width: 220, height: 325))

            UIColor(red: 0.48, green: 0.31, blue: 0.18, alpha: 1).setFill()
            context.fill(CGRect(x: 110, y: 455, width: 330, height: 145))
            UIColor(red: 0.70, green: 0.52, blue: 0.30, alpha: 1).setFill()
            context.fill(CGRect(x: 122, y: 468, width: 306, height: 118))

            UIColor(red: 0.25, green: 0.22, blue: 0.18, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 410, width: 1_000, height: 18))

            if showHandrail {
                let path = UIBezierPath()
                path.move(to: CGPoint(x: 695, y: 255))
                path.addLine(to: CGPoint(x: 830, y: 255))
                path.lineWidth = 22
                UIColor(red: 0.18, green: 0.34, blue: 0.25, alpha: 1).setStroke()
                path.stroke()
            }

            if showRiskBoxes {
                let path = UIBezierPath(rect: CGRect(x: 88, y: 438, width: 372, height: 178))
                path.lineWidth = 14
                UIColor(red: 0.82, green: 0.12, blue: 0.12, alpha: 1).setStroke()
                path.stroke()
            }
        }
    }
}
#endif
