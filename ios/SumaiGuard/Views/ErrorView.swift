import SwiftUI

struct ErrorPresentation: Equatable, Sendable {
    let heading: String
    let message: String
    let retryLabel: String
    let returnHomeLabel: String

    init(
        error: UserFacingError,
        content: ResultStateContent = .production
    ) {
        heading = content.errorHeading
        message = error.messageJA
        retryLabel = content.retryLabel
        returnHomeLabel = content.returnHomeLabel
    }

    var visibleText: String {
        [heading, message, retryLabel, returnHomeLabel].joined(separator: "\n")
    }
}

@MainActor
struct ErrorActions {
    let retry: () -> Void
    let returnHome: () -> Void
}

struct ErrorView: View {
    let error: UserFacingError
    let actions: ErrorActions
    let content: ResultStateContent

    init(
        error: UserFacingError,
        actions: ErrorActions,
        content: ResultStateContent = .production
    ) {
        self.error = error
        self.actions = actions
        self.content = content
    }

    var body: some View {
        let presentation = ErrorPresentation(error: error, content: content)
        ScrollView {
            VStack(spacing: 20) {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: 52))
                    .foregroundStyle(Color("BrandForest"))
                    .accessibilityHidden(true)
                Text(presentation.heading)
                    .font(.title.bold())
                    .multilineTextAlignment(.center)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilitySortPriority(10)
                    .accessibilityIdentifier("error.heading")
                Text(presentation.message)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("error.message")
                Button(presentation.retryLabel, action: actions.retry)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.borderedProminent)
                    .tint(Color("BrandForest"))
                    .foregroundStyle(Color("BrandCream"))
                    .accessibilitySortPriority(4)
                    .accessibilityIdentifier("error.retry")
                Button(presentation.returnHomeLabel, action: actions.returnHome)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.bordered)
                    .tint(Color("BrandForest"))
                    .accessibilitySortPriority(3)
                    .accessibilityIdentifier("error.returnHome")
            }
            .frame(maxWidth: .infinity)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.appTitle)
        .navigationBarTitleDisplayMode(.inline)
    }
}
