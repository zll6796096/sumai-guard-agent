import SwiftUI

@MainActor
struct ConsentActions {
    let agree: () -> Void
    let cancel: () -> Void
}

struct ConsentView: View {
    let selection: SelectedImage
    let actions: ConsentActions
    let content: CaptureConsentContent

    @State private var showsPrivacy = false

    init(
        selection: SelectedImage,
        actions: ConsentActions,
        content: CaptureConsentContent = .production
    ) {
        self.selection = selection
        self.actions = actions
        self.content = content
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(content.consentHeading)
                    .font(.title.bold())
                    .foregroundStyle(.primary)
                    .accessibilitySortPriority(10)
                    .accessibilityIdentifier("consent.heading")
                Text(content.consentExplanation)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Image(
                    selection.preview,
                    scale: 1,
                    label: Text(content.previewAccessibilityLabel)
                )
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(Color(uiColor: .separator), lineWidth: 1)
                    }
                    .accessibilitySortPriority(9)
                    .accessibilityIdentifier("consent.preview")

                disclosureSummary

                Button(content.agreeAction.label, action: actions.agree)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.borderedProminent)
                    .tint(Color("BrandForest"))
                    .foregroundStyle(Color("BrandCream"))
                    .accessibilitySortPriority(7)
                    .accessibilityIdentifier(content.agreeAction.identifier)
                    .accessibilityHint(content.agreeAction.hint)

                Button(content.cancelConsentAction.label, action: actions.cancel)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.bordered)
                    .tint(Color("BrandForest"))
                    .accessibilitySortPriority(6)
                    .accessibilityIdentifier(content.cancelConsentAction.identifier)
                    .accessibilityHint(content.cancelConsentAction.hint)

                Button {
                    showsPrivacy = true
                } label: {
                    Label(content.privacyAction.label, systemImage: "hand.raised")
                        .frame(minHeight: 44)
                }
                .foregroundStyle(Color("BrandForest"))
                .accessibilitySortPriority(5)
                .accessibilityIdentifier("consent.privacy")
                .accessibilityHint(content.privacyAction.hint)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showsPrivacy) {
            PrivacySheet(content: content)
        }
    }

    private var disclosureSummary: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(content.disclosures) { disclosure in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: disclosure.systemImage)
                        .frame(width: 22, height: 22)
                        .foregroundStyle(Color("BrandForest"))
                        .accessibilityHidden(true)
                    Text(disclosure.text)
                        .font(.callout)
                        .foregroundStyle(Color("BrandForest"))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(16)
        .background(Color("BrandCream"), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(alignment: .topLeading) {
            Rectangle()
                .fill(Color("BrandGold"))
                .frame(width: 5)
                .clipShape(.rect(topLeadingRadius: 14, bottomLeadingRadius: 14))
                .accessibilityHidden(true)
        }
        .accessibilitySortPriority(8)
        .accessibilityIdentifier("consent.disclosures")
    }
}
