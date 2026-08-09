import CoreGraphics
import SwiftUI

struct ProcessingPresentation {
    let preview: CGImage
    let previewAccessibilityLabel: String

    init(selection: SelectedImage) {
        preview = selection.preview
        previewAccessibilityLabel = "確認中の住まいの写真"
    }
}

@MainActor
struct ProcessingActions {
    let cancelProcessing: () -> Void
}

struct ProcessingView: View {
    let selection: SelectedImage
    let actions: ProcessingActions
    let content: ResultStateContent

    init(
        selection: SelectedImage,
        actions: ProcessingActions,
        content: ResultStateContent = .production
    ) {
        self.selection = selection
        self.actions = actions
        self.content = content
    }

    var body: some View {
        let presentation = ProcessingPresentation(selection: selection)
        ScrollView {
            VStack(spacing: 22) {
                ProgressView()
                    .controlSize(.large)
                    .tint(Color("BrandForest"))
                    .accessibilityLabel("確認処理中")
                    .accessibilityIdentifier("processing.progress.indeterminate")
                Text(content.processingHeading)
                    .font(.title2.bold())
                    .multilineTextAlignment(.center)
                    .accessibilitySortPriority(3)
                Text(content.processingExplanation)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                Image(
                    presentation.preview,
                    scale: 1,
                    label: Text(presentation.previewAccessibilityLabel)
                )
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: 280)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(Color(uiColor: .separator), lineWidth: 1)
                    }
                    .accessibilityIdentifier("processing.preview")
                Text(content.processingPrivacyNote)
                    .font(.callout)
                    .foregroundStyle(Color("BrandForest"))
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(16)
                    .frame(maxWidth: .infinity)
                    .background(Color("BrandCream"), in: RoundedRectangle(cornerRadius: 14))
                Button(content.processingCancelLabel, action: actions.cancelProcessing)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .buttonStyle(.bordered)
                    .tint(Color("BrandForest"))
                    .accessibilityIdentifier("processing.cancel")
            }
            .frame(maxWidth: .infinity)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle("確認中")
        .navigationBarTitleDisplayMode(.inline)
    }
}
