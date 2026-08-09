import SwiftUI
import UIKit

struct CameraPicker: UIViewControllerRepresentable {
    let onImageData: (Data?) -> Void
    let onCancel: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onImageData: onImageData, onCancel: onCancel)
    }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.allowsEditing = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_: UIImagePickerController, context _: Context) {}

    @MainActor
    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        private let onImageData: (Data?) -> Void
        private let onCancel: () -> Void
        private var didComplete = false

        init(onImageData: @escaping (Data?) -> Void, onCancel: @escaping () -> Void) {
            self.onImageData = onImageData
            self.onCancel = onCancel
        }

        func imagePickerController(
            _: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            guard !didComplete else {
                return
            }
            didComplete = true
            let data = (info[.originalImage] as? UIImage)?.jpegData(compressionQuality: 0.95)
            onImageData(data)
        }

        func imagePickerControllerDidCancel(_: UIImagePickerController) {
            guard !didComplete else {
                return
            }
            didComplete = true
            onCancel()
        }
    }
}
