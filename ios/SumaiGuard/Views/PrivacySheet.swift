import SwiftUI

struct PrivacySheet: View {
    let content: CaptureConsentContent

    @Environment(\.dismiss) private var dismiss

    init(content: CaptureConsentContent = .production) {
        self.content = content
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(content.disclosures) { disclosure in
                        HStack(alignment: .top, spacing: 14) {
                            Image(systemName: disclosure.systemImage)
                                .font(.title3.weight(.semibold))
                                .frame(width: 28, height: 28)
                                .foregroundStyle(Color("BrandForest"))
                                .accessibilityHidden(true)
                            Text(disclosure.text)
                                .font(.body)
                                .foregroundStyle(.primary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle(content.privacyHeading)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(content.privacyCloseLabel) { dismiss() }
                        .frame(minWidth: 44, minHeight: 44)
                        .foregroundStyle(Color("BrandForest"))
                        .accessibilityIdentifier("privacy.close")
                }
            }
        }
        .accessibilityIdentifier("privacy.sheet")
    }
}
