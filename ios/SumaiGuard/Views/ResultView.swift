import Foundation
import SwiftUI

struct ResultStateContent: Equatable, Sendable {
    let appTitle: String
    let processingHeading: String
    let processingExplanation: String
    let processingPrivacyNote: String
    let processingCancelLabel: String
    let processingUsesIndeterminateProgress: Bool
    let resultHeading: String
    let limitationsHeading: String
    let showAdviceLabel: String
    let returnHomeLabel: String
    let noFindingsHeading: String
    let noFindingsLimitation: String
    let chooseAnotherPhotoLabel: String
    let notApplicableHeading: String
    let notApplicableFallbackReason: String
    let notApplicableGuidance: String
    let errorHeading: String
    let retryLabel: String

    static let production = ResultStateContent(
        appTitle: "実家あんしんチェック",
        processingHeading: "写真で見える注意候補を確認しています",
        processingExplanation: "写真の中で確認できる転倒・滑り・つまずきの注意候補を確認しています。結果が出るまでそのままお待ちください。",
        processingPrivacyNote: "処理中も、SumaiGuard アプリは写真を保存しません。",
        processingCancelLabel: "確認を中止する",
        processingUsesIndeterminateProgress: true,
        resultHeading: "写真で確認できた注意箇所",
        limitationsHeading: "この結果の限界",
        showAdviceLabel: "安全のためにできること",
        returnHomeLabel: "最初の画面に戻る",
        noFindingsHeading: "写真で見える範囲では、明らかな注意候補を確認できませんでした",
        noFindingsLimitation: "住まい全体の安全を示すものではありません",
        chooseAnotherPhotoLabel: "別の写真を選ぶ",
        notApplicableHeading: "この写真では確認できませんでした",
        notApplicableFallbackReason: "この写真からは、室内の注意候補を確認できませんでした。",
        notApplicableGuidance: "床や通路など、確認したい場所が見える明るい室内写真を1枚選んでください。",
        errorHeading: "処理を完了できませんでした",
        retryLabel: "写真を確認してもう一度試す"
    )

    var processingVisibleText: String {
        [processingHeading, processingExplanation, processingPrivacyNote, processingCancelLabel]
            .joined(separator: "\n")
    }
}

struct ValidatedPresentationResponse: Equatable, Sendable {
    let response: AnalysisResponse

    init?(response: AnalysisResponse) {
        guard PresentationResponseValidator.isValid(response) else {
            return nil
        }
        self.response = response
    }
}

enum PresentationResponseValidator {
    // The backend caps each tier at five; the finding and text caps are an
    // independent client-side defense against malformed or unexpectedly deep payloads.
    static let maxFindings = 50
    static let maxActionsPerTier = 5
    static let maxIdentifierUTF8Bytes = 128
    static let maxDisplayFieldUTF8Bytes = 4 * 1_024
    static let maxTotalDisplayUTF8Bytes = 256 * 1_024

    static func isValid(_ response: AnalysisResponse) -> Bool {
        if response.isNotApplicable {
            guard
                response.findings.isEmpty,
                response.actionPlan.isEmpty,
                let reason = response.notApplicableReasonJA,
                isSafeDisplayText(reason)
            else {
                return false
            }
            return true
        }

        guard response.findings.count <= maxFindings else {
            return false
        }

        var remainingDisplayBytes = maxTotalDisplayUTF8Bytes
        var findingIDs = Set<String>()
        for finding in response.findings {
            guard
                isSafeIdentifier(finding.id),
                findingIDs.insert(finding.id).inserted,
                consumeDisplayText(finding.labelJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(finding.descriptionJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(finding.evidenceJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(finding.basisLabelJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(finding.basisSummaryJA, remaining: &remainingDisplayBytes)
            else {
                return false
            }
        }

        var actionIDs = Set<String>()
        guard
            validateActions(
                response.actionPlan.familyNoCost,
                expectedTier: .familyNoCost,
                expectedCost: .zero,
                expectedProfessional: false,
                findingIDs: findingIDs,
                actionIDs: &actionIDs,
                remainingDisplayBytes: &remainingDisplayBytes
            ),
            validateActions(
                response.actionPlan.careManagerPurchase,
                expectedTier: .careManagerPurchase,
                expectedCost: .low,
                expectedProfessional: true,
                findingIDs: findingIDs,
                actionIDs: &actionIDs,
                remainingDisplayBytes: &remainingDisplayBytes
            ),
            validateActions(
                response.actionPlan.contractorConstruction,
                expectedTier: .contractorConstruction,
                expectedCost: .high,
                expectedProfessional: true,
                findingIDs: findingIDs,
                actionIDs: &actionIDs,
                remainingDisplayBytes: &remainingDisplayBytes
            )
        else {
            return false
        }
        return true
    }

    static func isSafeDisplayText(_ text: String) -> Bool {
        let byteCount = text.utf8.count
        guard
            byteCount > 0,
            byteCount <= maxDisplayFieldUTF8Bytes,
            !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            return false
        }
        return text.unicodeScalars.allSatisfy(isSafeTextScalar)
    }

    private static func validateActions(
        _ actions: [ActionItem],
        expectedTier: ActionTier,
        expectedCost: CostLevel,
        expectedProfessional: Bool,
        findingIDs: Set<String>,
        actionIDs: inout Set<String>,
        remainingDisplayBytes: inout Int
    ) -> Bool {
        guard actions.count <= maxActionsPerTier else {
            return false
        }
        for action in actions {
            guard
                action.tier == expectedTier,
                action.costLevel == expectedCost,
                action.requiresProfessional == expectedProfessional,
                isSafeIdentifier(action.id),
                actionIDs.insert(action.id).inserted,
                isSafeIdentifier(action.riskID),
                findingIDs.contains(action.riskID),
                consumeDisplayText(action.titleJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(action.descriptionJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(action.whyJA, remaining: &remainingDisplayBytes),
                consumeDisplayText(action.disclaimerJA, remaining: &remainingDisplayBytes)
            else {
                return false
            }
        }
        return true
    }

    private static func consumeDisplayText(
        _ text: String,
        remaining: inout Int
    ) -> Bool {
        guard isSafeDisplayText(text) else {
            return false
        }
        let byteCount = text.utf8.count
        guard byteCount <= remaining else {
            return false
        }
        remaining -= byteCount
        return true
    }

    private static func isSafeIdentifier(_ identifier: String) -> Bool {
        let byteCount = identifier.utf8.count
        return byteCount > 0
            && byteCount <= maxIdentifierUTF8Bytes
            && !identifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && identifier.unicodeScalars.allSatisfy(isSafeTextScalar)
    }

    private static func isSafeTextScalar(_ scalar: Unicode.Scalar) -> Bool {
        let value = scalar.value
        if value < 0x20 {
            return value == 0x09 || value == 0x0A
        }
        if (0x7F...0x9F).contains(value) {
            return false
        }
        if value == 0x061C || (0x200E...0x200F).contains(value) {
            return false
        }
        if (0x202A...0x202E).contains(value) || (0x2066...0x2069).contains(value) {
            return false
        }
        return true
    }
}

enum ResultImageRole: Int, Equatable, Hashable, Sendable {
    case evidence
    case improvement
}

struct ResultImagePresentation: Identifiable, Equatable, Sendable {
    let role: ResultImageRole
    let heading: String
    let accessibilityLabel: String
    let base64: String

    var id: ResultImageRole { role }
}

struct FindingPresentation: Identifiable, Equatable, Sendable {
    let id: String
    let label: String
    let description: String
    let severityLabel: String
    let confidenceLabel: String
    let confidenceExplanation: String
    let evidence: String
    let basisLabel: String
    let basisSummary: String
    let needsHumanConfirmation: Bool

    init(_ finding: RiskFinding) {
        id = finding.id
        label = finding.labelJA
        description = finding.descriptionJA
        severityLabel = "注意度 \(finding.severity)/5"
        confidenceLabel = "未校正のモデル参考スコア \(Int((finding.confidence * 100).rounded()))/100"
        confidenceExplanation = "危害発生確率ではありません"
        evidence = finding.evidenceJA
        basisLabel = finding.basisLabelJA
        basisSummary = finding.basisSummaryJA
        needsHumanConfirmation = finding.needsHumanConfirmation
    }

    var visibleText: String {
        [
            label,
            description,
            severityLabel,
            confidenceLabel,
            confidenceExplanation,
            evidence,
            basisLabel,
            basisSummary,
            needsHumanConfirmation ? "人や専門職による確認が必要です" : "",
        ].joined(separator: "\n")
    }
}

struct ResultPresentation: Equatable, Sendable {
    let heading: String
    let images: [ResultImagePresentation]
    let findings: [FindingPresentation]
    let limitationsHeading: String
    let limitations: [String]
    let limitationsRegionCount: Int
    let showAdviceLabel: String
    let returnHomeLabel: String

    init?(
        response: AnalysisResponse,
        content: ResultStateContent = .production
    ) {
        guard
            let validated = ValidatedPresentationResponse(response: response),
            !validated.response.isNotApplicable,
            !validated.response.findings.isEmpty,
            !validated.response.actionPlan.isEmpty
        else {
            return nil
        }
        let response = validated.response

        heading = content.resultHeading
        images = [
            ResultImagePresentation(
                role: .evidence,
                heading: "確認できた箇所",
                accessibilityLabel: "赤枠で示した注意候補の画像",
                base64: response.annotatedImageBase64
            ),
            ResultImagePresentation(
                role: .improvement,
                heading: "改善イメージ",
                accessibilityLabel: "注意候補に対応した改善イメージ",
                base64: response.improvementImageBase64
            ),
        ]
        findings = response.findings.map(FindingPresentation.init)
        limitationsHeading = content.limitationsHeading
        limitations = [
            "写真で見える範囲に限った結果です。",
            "見落としや誤検出があり得ます。",
            "人や専門職による現地確認が必要です。",
            "医療・介護認定・保険・法令適合・施工可否・見積もりの判断に代わるものではありません。",
        ]
        limitationsRegionCount = 1
        showAdviceLabel = content.showAdviceLabel
        returnHomeLabel = content.returnHomeLabel
    }

    var visibleText: String {
        ([heading]
            + images.flatMap { [$0.heading, $0.accessibilityLabel] }
            + findings.map(\.visibleText)
            + [limitationsHeading]
            + limitations
            + [showAdviceLabel, returnHomeLabel])
            .joined(separator: "\n")
    }
}

@MainActor
struct ResultActions {
    let showAdvice: () -> Void
    let returnHome: () -> Void
}

struct ResultView: View {
    let response: AnalysisResponse
    let actions: ResultActions
    let content: ResultStateContent

    init(
        response: AnalysisResponse,
        actions: ResultActions,
        content: ResultStateContent = .production
    ) {
        self.response = response
        self.actions = actions
        self.content = content
    }

    var body: some View {
        ScrollView {
            if let presentation = ResultPresentation(response: response, content: content) {
                LazyVStack(alignment: .leading, spacing: 24) {
                    Text(presentation.heading)
                        .font(.largeTitle.bold())
                        .foregroundStyle(Color("BrandForest"))
                        .accessibilityAddTraits(.isHeader)
                        .accessibilitySortPriority(10)
                        .accessibilityIdentifier("result.heading")

                    ForEach(Array(presentation.images.enumerated()), id: \.element.id) { index, image in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(image.heading)
                                .font(.title2.bold())
                                .accessibilityAddTraits(.isHeader)
                            RemoteResultImage(
                                base64: image.base64,
                                accessibilityLabel: image.accessibilityLabel,
                                identifier: "result.image.\(index)"
                            )
                        }
                        .accessibilitySortPriority(Double(8 - index))
                    }

                    LazyVStack(alignment: .leading, spacing: 16) {
                        ForEach(Array(presentation.findings.enumerated()), id: \.element.id) { index, finding in
                            findingCard(finding, number: index + 1)
                        }
                    }
                    .accessibilitySortPriority(6)
                    .accessibilityIdentifier("result.findings")

                    VStack(alignment: .leading, spacing: 10) {
                        Text(presentation.limitationsHeading)
                            .font(.headline)
                            .accessibilityAddTraits(.isHeader)
                        ForEach(presentation.limitations, id: \.self) { limitation in
                            Label(limitation, systemImage: "info.circle")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(16)
                    .background(Color("BrandCream"), in: RoundedRectangle(cornerRadius: 14))
                    .accessibilityElement(children: .contain)
                    .accessibilitySortPriority(5)
                    .accessibilityIdentifier("result.limitations")

                    Button(presentation.showAdviceLabel, action: actions.showAdvice)
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .buttonStyle(.borderedProminent)
                        .tint(Color("BrandForest"))
                        .foregroundStyle(Color("BrandCream"))
                        .accessibilitySortPriority(4)
                        .accessibilityIdentifier("result.showAdvice")
                    Button(presentation.returnHomeLabel, action: actions.returnHome)
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .buttonStyle(.bordered)
                        .tint(Color("BrandForest"))
                        .accessibilitySortPriority(3)
                        .accessibilityIdentifier("result.returnHome")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
            } else {
                failClosedContent
                    .padding(24)
            }
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.appTitle)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func findingCard(_ finding: FindingPresentation, number: Int) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("注意候補 \(number)：\(finding.label)")
                .font(.title3.bold())
                .foregroundStyle(Color("BrandForest"))
                .accessibilityAddTraits(.isHeader)
            Text(finding.description)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Text(finding.severityLabel)
                Text(finding.confidenceLabel)
            }
            .font(.caption.bold())
            .fixedSize(horizontal: false, vertical: true)
            Text(finding.confidenceExplanation)
                .font(.caption)
                .foregroundStyle(.secondary)
            detailRow(label: "写真上の根拠", value: finding.evidence)
            detailRow(label: finding.basisLabel, value: finding.basisSummary)
            if finding.needsHumanConfirmation {
                Label("人や専門職による確認が必要です", systemImage: "person.crop.circle.badge.questionmark")
                    .font(.callout.bold())
                    .foregroundStyle(Color("BrandForest"))
            }
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("result.finding.\(finding.id)")
    }

    private func detailRow(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.callout.bold())
            Text(value)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var failClosedContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.circle")
                .font(.largeTitle)
                .foregroundStyle(Color("BrandForest"))
                .accessibilityHidden(true)
            Text("結果を安全に表示できませんでした")
                .font(.title2.bold())
                .multilineTextAlignment(.center)
            Text("最初の画面に戻り、別の写真でお試しください。")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button(content.returnHomeLabel, action: actions.returnHome)
                .frame(maxWidth: .infinity, minHeight: 52)
                .buttonStyle(.borderedProminent)
                .tint(Color("BrandForest"))
                .foregroundStyle(Color("BrandCream"))
                .accessibilityIdentifier("result.failClosed.returnHome")
        }
        .frame(maxWidth: .infinity)
    }
}
