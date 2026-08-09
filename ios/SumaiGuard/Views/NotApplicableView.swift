import Foundation
import SwiftUI

struct NotApplicablePresentation: Equatable, Sendable {
    let heading: String
    let reason: String
    let guidance: String
    let chooseAnotherPhotoLabel: String

    init(
        reason: String,
        content: ResultStateContent = .production
    ) {
        heading = content.notApplicableHeading
        self.reason = Self.safeReason(reason, fallback: content.notApplicableFallbackReason)
        guidance = content.notApplicableGuidance
        chooseAnotherPhotoLabel = content.chooseAnotherPhotoLabel
    }

    var visibleText: String {
        [heading, reason, guidance, chooseAnotherPhotoLabel].joined(separator: "\n")
    }

    private static func safeReason(_ rawValue: String, fallback: String) -> String {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            PresentationResponseValidator.isSafeDisplayText(trimmed)
        else {
            return fallback
        }
        return trimmed
    }
}

@MainActor
struct NotApplicableActions {
    let returnHome: () -> Void
}

struct NotApplicableView: View {
    let reason: String
    let actions: NotApplicableActions
    let content: ResultStateContent

    init(
        reason: String,
        actions: NotApplicableActions,
        content: ResultStateContent = .production
    ) {
        self.reason = reason
        self.actions = actions
        self.content = content
    }

    var body: some View {
        let presentation = NotApplicablePresentation(reason: reason, content: content)
        ScrollView {
            VStack(spacing: 20) {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 52))
                    .foregroundStyle(Color("BrandForest"))
                    .accessibilityHidden(true)
                Text(presentation.heading)
                    .font(.title.bold())
                    .multilineTextAlignment(.center)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("notApplicable.heading")
                Text(presentation.reason)
                    .font(.body)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("notApplicable.reason")
                Text(presentation.guidance)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(16)
                    .frame(maxWidth: .infinity)
                    .background(Color("BrandCream"), in: RoundedRectangle(cornerRadius: 14))
                Button(presentation.chooseAnotherPhotoLabel, action: actions.returnHome)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.borderedProminent)
                    .tint(Color("BrandForest"))
                    .foregroundStyle(Color("BrandCream"))
                    .accessibilityIdentifier("notApplicable.returnHome")
            }
            .frame(maxWidth: .infinity)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.appTitle)
        .navigationBarTitleDisplayMode(.inline)
    }
}
