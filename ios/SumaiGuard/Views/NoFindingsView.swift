import SwiftUI

struct NoFindingsPresentation: Equatable, Sendable {
    let heading: String
    let limitation: String
    let guidance: String
    let chooseAnotherPhotoLabel: String

    init(content: ResultStateContent = .production) {
        heading = content.noFindingsHeading
        limitation = content.noFindingsLimitation
        guidance = "見えにくい場所や写真の外側は確認できません。気になる場所があれば、別の角度の写真も確認してください。"
        chooseAnotherPhotoLabel = content.chooseAnotherPhotoLabel
    }

    var visibleText: String {
        [heading, limitation, guidance, chooseAnotherPhotoLabel].joined(separator: "\n")
    }
}

@MainActor
struct NoFindingsActions {
    let returnHome: () -> Void
}

struct NoFindingsView: View {
    let actions: NoFindingsActions
    let content: ResultStateContent

    init(
        actions: NoFindingsActions,
        content: ResultStateContent = .production
    ) {
        self.actions = actions
        self.content = content
    }

    var body: some View {
        let presentation = NoFindingsPresentation(content: content)
        ScrollView {
            VStack(spacing: 20) {
                Image(systemName: "photo.badge.checkmark")
                    .font(.system(size: 52))
                    .foregroundStyle(Color("BrandForest"))
                    .accessibilityHidden(true)
                Text(presentation.heading)
                    .font(.title.bold())
                    .multilineTextAlignment(.center)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("noFindings.heading")
                Text(presentation.limitation)
                    .font(.headline)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color("BrandForest"))
                    .fixedSize(horizontal: false, vertical: true)
                Text(presentation.guidance)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                Button(presentation.chooseAnotherPhotoLabel, action: actions.returnHome)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.borderedProminent)
                    .tint(Color("BrandForest"))
                    .foregroundStyle(Color("BrandCream"))
                    .accessibilityIdentifier("noFindings.returnHome")
            }
            .frame(maxWidth: .infinity)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.appTitle)
        .navigationBarTitleDisplayMode(.inline)
    }
}
