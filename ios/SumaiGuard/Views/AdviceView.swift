import Foundation
import SwiftUI

struct AdviceItemPresentation: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let description: String
    let why: String
    let disclaimer: String
    let costLabel: String

    init(_ item: ActionItem) {
        id = item.id
        title = item.titleJA
        description = item.descriptionJA
        why = item.whyJA
        disclaimer = item.disclaimerJA
        costLabel = switch item.costLevel {
        case .zero: "費用の目安：費用なし"
        case .low: "費用の目安：低め"
        case .medium: "費用の目安：中程度"
        case .high: "費用の目安：高め"
        }
    }

    var visibleText: String {
        [title, description, why, disclaimer, costLabel].joined(separator: "\n")
    }
}

struct AdviceSectionPresentation: Identifiable, Equatable, Sendable {
    let id: ActionTier
    let heading: String
    let items: [AdviceItemPresentation]
    let emptyMessage: String

    var visibleText: String {
        ([heading] + (items.isEmpty ? [emptyMessage] : items.map(\.visibleText)))
            .joined(separator: "\n")
    }
}

struct AdvicePresentation: Equatable, Sendable {
    let heading: String
    let explanation: String
    let sections: [AdviceSectionPresentation]
    let failureMessage: String?
    let overallDisclaimer: String
    let returnHomeLabel: String

    init(
        response: AnalysisResponse,
        content: ResultStateContent = .production
    ) {
        heading = "次にできること"
        explanation = "写真で確認できた注意候補について、相談先ごとに確認してください。無理に作業せず、現地の状態を確かめてください。"
        let emptyMessage = "該当する提案はありません"
        let validated = ValidatedPresentationResponse(response: response)
        let canDisplayActions = validated != nil
            && !response.isNotApplicable
            && !response.findings.isEmpty
            && !response.actionPlan.isEmpty
        failureMessage = canDisplayActions ? nil : "提案を安全に表示できません"
        let displayedResponse = canDisplayActions ? validated?.response : nil
        sections = [
            AdviceSectionPresentation(
                id: .familyNoCost,
                heading: "家族で今日できること",
                items: displayedResponse?.actionPlan.familyNoCost.map(AdviceItemPresentation.init) ?? [],
                emptyMessage: emptyMessage
            ),
            AdviceSectionPresentation(
                id: .careManagerPurchase,
                heading: "ケアマネ・福祉用具に相談",
                items: displayedResponse?.actionPlan.careManagerPurchase.map(AdviceItemPresentation.init) ?? [],
                emptyMessage: emptyMessage
            ),
            AdviceSectionPresentation(
                id: .contractorConstruction,
                heading: "専門施工・現地確認",
                items: displayedResponse?.actionPlan.contractorConstruction.map(AdviceItemPresentation.init) ?? [],
                emptyMessage: emptyMessage
            ),
        ]
        overallDisclaimer = "医療・介護認定・保険・法令適合・施工可否・見積もりの判断に代わるものではありません。"
        returnHomeLabel = content.returnHomeLabel
    }

    var visibleText: String {
        if let failureMessage {
            return [heading, failureMessage, returnHomeLabel].joined(separator: "\n")
        }
        return ([heading, explanation]
                + sections.map(\.visibleText)
                + [overallDisclaimer, returnHomeLabel])
                .joined(separator: "\n")
    }
}

@MainActor
struct AdviceActions {
    let returnHome: () -> Void
    let shareAdvice: (() -> Void)?

    init(
        returnHome: @escaping () -> Void,
        shareAdvice: (() -> Void)? = nil
    ) {
        self.returnHome = returnHome
        self.shareAdvice = shareAdvice
    }
}

struct AdviceView: View {
    let response: AnalysisResponse
    let actions: AdviceActions
    let content: ResultStateContent

    init(
        response: AnalysisResponse,
        actions: AdviceActions,
        content: ResultStateContent = .production
    ) {
        self.response = response
        self.actions = actions
        self.content = content
    }

    var body: some View {
        let presentation = AdvicePresentation(response: response, content: content)
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 24) {
                Text(presentation.heading)
                    .font(.largeTitle.bold())
                    .foregroundStyle(Color("BrandForest"))
                    .accessibilityAddTraits(.isHeader)
                    .accessibilitySortPriority(10)
                    .accessibilityIdentifier("advice.heading")
                if presentation.failureMessage == nil {
                    Text(presentation.explanation)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let failureMessage = presentation.failureMessage {
                    Label(failureMessage, systemImage: "exclamationmark.circle")
                        .font(.headline)
                        .foregroundStyle(Color("BrandForest"))
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color("BrandCream"), in: RoundedRectangle(cornerRadius: 14))
                        .accessibilityIdentifier("advice.failClosed")
                } else {
                    ForEach(Array(presentation.sections.enumerated()), id: \.element.id) { sectionIndex, section in
                        LazyVStack(alignment: .leading, spacing: 14) {
                            Text(section.heading)
                                .font(.title2.bold())
                                .foregroundStyle(Color("BrandForest"))
                                .accessibilityAddTraits(.isHeader)
                            if section.items.isEmpty {
                                Text(section.emptyMessage)
                                    .font(.body)
                                    .foregroundStyle(.secondary)
                            } else {
                                ForEach(section.items) { item in
                                    adviceCard(item)
                                }
                            }
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilitySortPriority(Double(8 - sectionIndex))
                        .accessibilityIdentifier("advice.section.\(sectionIndex)")
                    }
                }

                if presentation.failureMessage == nil {
                    Label(presentation.overallDisclaimer, systemImage: "info.circle")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color("BrandCream"), in: RoundedRectangle(cornerRadius: 14))
                        .accessibilityIdentifier("advice.disclaimer")
                }

                if presentation.failureMessage == nil, let shareAdvice = actions.shareAdvice {
                    Button("テキストPDFを共有", action: shareAdvice)
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .buttonStyle(.borderedProminent)
                        .tint(Color("BrandForest"))
                        .foregroundStyle(Color("BrandCream"))
                        .accessibilityIdentifier("advice.sharePDF")
                }
                Button(presentation.returnHomeLabel, action: actions.returnHome)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.bordered)
                    .tint(Color("BrandForest"))
                    .accessibilityIdentifier("advice.returnHome")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.appTitle)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func adviceCard(_ item: AdviceItemPresentation) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(item.title)
                .font(.headline)
            Text(item.description)
                .fixedSize(horizontal: false, vertical: true)
            detail(label: "理由", text: item.why)
            Text(item.costLabel)
                .font(.caption.bold())
                .foregroundStyle(Color("BrandForest"))
            Text(item.disclaimer)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("advice.item.\(item.id)")
    }

    private func detail(label: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.callout.bold())
            Text(text)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
