import AVFoundation
import PhotosUI
import SwiftUI
import UIKit

struct AccessibilityActionDescriptor: Equatable, Sendable {
    let label: String
    let hint: String
    let identifier: String
}

struct PrivacyDisclosure: Identifiable, Equatable, Sendable {
    enum ID: String, Hashable, Sendable {
        case purpose
        case recipients
        case privateContext
        case noStorage
        case noConsentNoSend
        case professionalBoundary
    }

    let id: ID
    let text: String
    let systemImage: String
}

struct CaptureConsentContent: Equatable, Sendable {
    let title: String
    let captureHeading: String
    let captureExplanation: String
    let cameraAction: AccessibilityActionDescriptor
    let libraryAction: AccessibilityActionDescriptor
    let privacyAction: AccessibilityActionDescriptor
    let agreeAction: AccessibilityActionDescriptor
    let cancelConsentAction: AccessibilityActionDescriptor
    let cancelPreparationAction: AccessibilityActionDescriptor
    let cancelCameraPermissionAction: AccessibilityActionDescriptor
    let consentHeading: String
    let consentExplanation: String
    let previewAccessibilityLabel: String
    let privacyHeading: String
    let privacyCloseLabel: String
    let disclosures: [PrivacyDisclosure]

    var allAccessibilityText: [String] {
        [
            cameraAction.label,
            cameraAction.hint,
            libraryAction.label,
            libraryAction.hint,
            privacyAction.label,
            privacyAction.hint,
            agreeAction.label,
            agreeAction.hint,
            cancelConsentAction.label,
            cancelConsentAction.hint,
            cancelPreparationAction.label,
            cancelPreparationAction.hint,
            cancelCameraPermissionAction.label,
            cancelCameraPermissionAction.hint,
            previewAccessibilityLabel,
            privacyCloseLabel,
        ]
    }

    static let production = CaptureConsentContent(
        title: "実家あんしんチェック",
        captureHeading: "住まいの写真を1枚",
        captureExplanation: "転倒・滑り・つまずきにつながる、写真で見える注意候補を確認します。",
        cameraAction: .init(
            label: "カメラで撮る",
            hint: "カメラを開いて住まいの写真を1枚撮影します。",
            identifier: "capture.camera"
        ),
        libraryAction: .init(
            label: "写真を1枚選ぶ",
            hint: "写真選択画面を開きます。写真ライブラリ全体への許可は求めません。",
            identifier: "capture.library"
        ),
        privacyAction: .init(
            label: "写真の取り扱いを見る",
            hint: "送信先、保存の有無、結果の限界を確認します。",
            identifier: "capture.privacy"
        ),
        agreeAction: .init(
            label: "同意して写真を送る",
            hint: "表示中の写真1枚を送信し、注意候補の確認を始めます。",
            identifier: "consent.agree"
        ),
        cancelConsentAction: .init(
            label: "同意せず戻る",
            hint: "写真を送信せず、最初の画面に戻ります。",
            identifier: "consent.cancel"
        ),
        cancelPreparationAction: .init(
            label: "選択を取り消す",
            hint: "写真を送信せず、読み込みを中止します。",
            identifier: "capture.cancelPreparation"
        ),
        cancelCameraPermissionAction: .init(
            label: "カメラの確認を取り消す",
            hint: "カメラを開かず、使用許可の確認結果をこの画面に反映しません。",
            identifier: "capture.cancelCameraPermission"
        ),
        consentHeading: "送信する写真を確認",
        consentExplanation: "内容と取り扱いを確認し、この写真を送る場合だけ同意してください。",
        previewAccessibilityLabel: "送信前に確認する住まいの写真",
        privacyHeading: "写真の取り扱い",
        privacyCloseLabel: "閉じる",
        disclosures: [
            .init(
                id: .purpose,
                text: "住まいの写真から、目に見える転倒・滑り・つまずきの注意候補を確認するために使用します。",
                systemImage: "eye"
            ),
            .init(
                id: .recipients,
                text: "写真は SumaiGuard Cloud Run と、Google LLC の Google Gemini に送信されます。",
                systemImage: "arrow.up.forward"
            ),
            .init(
                id: .privateContext,
                text: "住宅の写真には、私的な生活情報が写り込む場合があります。",
                systemImage: "house"
            ),
            .init(
                id: .noStorage,
                text: "SumaiGuard アプリは写真を保存しません。",
                systemImage: "externaldrive.badge.xmark"
            ),
            .init(
                id: .noConsentNoSend,
                text: "同意しない場合やキャンセルした場合、写真は送信されません。",
                systemImage: "hand.raised"
            ),
            .init(
                id: .professionalBoundary,
                text: "本結果は、医療、介護認定、保険、法令適合、施工可否の判断に代わるものではありません。",
                systemImage: "info.circle"
            ),
        ]
    )
}

enum CameraAuthorizationState: Equatable, Sendable {
    case authorized
    case notDetermined
    case denied
    case restricted
}

enum CameraAccessDecision: Equatable, Sendable {
    case presentCamera
    case requestPermission
    case showDenied
    case showRestricted
    case showUnavailable
}

enum CameraAccessPolicy {
    static func decision(
        isAvailable: Bool,
        authorization: CameraAuthorizationState
    ) -> CameraAccessDecision {
        guard isAvailable else {
            return .showUnavailable
        }
        switch authorization {
        case .authorized:
            return .presentCamera
        case .notDetermined:
            return .requestPermission
        case .denied:
            return .showDenied
        case .restricted:
            return .showRestricted
        }
    }
}

enum CameraAccessMessage: String, Identifiable, Equatable, Sendable {
    case denied
    case restricted
    case unavailable

    var id: String { rawValue }

    var title: String {
        switch self {
        case .denied:
            "カメラを使用できません"
        case .restricted:
            "カメラの使用が制限されています"
        case .unavailable:
            "カメラを利用できません"
        }
    }

    var explanation: String {
        switch self {
        case .denied:
            "設定でカメラを許可するか、写真を1枚選んでください。"
        case .restricted:
            "この端末の制限を確認するか、写真を1枚選んでください。"
        case .unavailable:
            "この端末ではカメラを開けません。写真を1枚選んでください。"
        }
    }
}

enum PhotoSelectionMessage: String, Identifiable, Equatable, Sendable {
    case unreadable

    var id: String { rawValue }
    var explanation: String {
        "この写真を読み込めませんでした。別の写真を選んでください。"
    }
}

@MainActor
protocol CameraAccessProviding: AnyObject {
    func isCameraAvailable() -> Bool
    func authorizationStatus() -> CameraAuthorizationState
    func requestAccess() async -> Bool
}

@MainActor
final class SystemCameraAccess: CameraAccessProviding {
    func isCameraAvailable() -> Bool {
        UIImagePickerController.isSourceTypeAvailable(.camera)
    }

    func authorizationStatus() -> CameraAuthorizationState {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            .authorized
        case .notDetermined:
            .notDetermined
        case .denied:
            .denied
        case .restricted:
            .restricted
        @unknown default:
            .restricted
        }
    }

    func requestAccess() async -> Bool {
        await AVCaptureDevice.requestAccess(for: .video)
    }
}

protocol PhotoDataLoading: Sendable {
    func loadImageData() async throws -> Data?
}

struct PhotosPickerDataLoader: PhotoDataLoading {
    let item: PhotosPickerItem

    func loadImageData() async throws -> Data? {
        try await item.loadTransferable(type: Data.self)
    }
}

@MainActor
final class CaptureAcquisitionModel: ObservableObject {
    @Published private(set) var isCameraPresented = false
    @Published private(set) var isRequestingCameraPermission = false
    @Published private(set) var cameraMessage: CameraAccessMessage?
    @Published private(set) var isLoadingPhoto = false
    @Published private(set) var photoMessage: PhotoSelectionMessage?

    private let cameraAccess: any CameraAccessProviding
    private let onSelectImage: (Data) -> Void
    private var photoLoadTask: Task<Void, Never>?
    private var photoOperationID = UUID()
    private var cameraPermissionOperationID = UUID()

    init(
        cameraAccess: any CameraAccessProviding = SystemCameraAccess(),
        onSelectImage: @escaping (Data) -> Void
    ) {
        self.cameraAccess = cameraAccess
        self.onSelectImage = onSelectImage
    }

    func requestCamera() async {
        guard !isRequestingCameraPermission else {
            return
        }
        cameraMessage = nil
        let decision = CameraAccessPolicy.decision(
            isAvailable: cameraAccess.isCameraAvailable(),
            authorization: cameraAccess.authorizationStatus()
        )
        switch decision {
        case .presentCamera:
            isCameraPresented = true
        case .requestPermission:
            let operationID = UUID()
            cameraPermissionOperationID = operationID
            isRequestingCameraPermission = true
            _ = await cameraAccess.requestAccess()
            guard cameraPermissionOperationID == operationID else {
                return
            }
            isRequestingCameraPermission = false
            applyCurrentCameraAccessState()
        case .showDenied:
            isCameraPresented = false
            cameraMessage = .denied
        case .showRestricted:
            isCameraPresented = false
            cameraMessage = .restricted
        case .showUnavailable:
            isCameraPresented = false
            cameraMessage = .unavailable
        }
    }

    func cancelCamera() {
        invalidateCameraPermissionOperation()
    }

    func receiveCapturedImage(_ data: Data?) {
        invalidateCameraPermissionOperation()
        guard let data, !data.isEmpty else {
            photoMessage = .unreadable
            return
        }
        photoMessage = nil
        onSelectImage(data)
    }

    func dismissCameraMessage() {
        cameraMessage = nil
    }

    func invalidate() {
        invalidateCameraPermissionOperation()
        cancelPhotoLoad()
        cameraMessage = nil
        photoMessage = nil
    }

    func loadPhoto(using loader: any PhotoDataLoading) {
        cancelPhotoLoad()
        photoMessage = nil
        isLoadingPhoto = true
        let operationID = UUID()
        photoOperationID = operationID
        photoLoadTask = Task { [weak self, loader] in
            do {
                let data = try await loader.loadImageData()
                try Task.checkCancellation()
                self?.finishPhotoLoad(data, operationID: operationID)
            } catch is CancellationError {
                self?.finishPhotoCancellation(operationID: operationID)
            } catch {
                self?.finishPhotoFailure(operationID: operationID)
            }
        }
    }

    func cancelPhotoLoad() {
        photoOperationID = UUID()
        photoLoadTask?.cancel()
        photoLoadTask = nil
        isLoadingPhoto = false
    }

    private func finishPhotoLoad(_ data: Data?, operationID: UUID) {
        guard photoOperationID == operationID else {
            return
        }
        photoLoadTask = nil
        isLoadingPhoto = false
        guard let data, !data.isEmpty else {
            photoMessage = .unreadable
            return
        }
        onSelectImage(data)
    }

    private func finishPhotoCancellation(operationID: UUID) {
        guard photoOperationID == operationID else {
            return
        }
        photoLoadTask = nil
        isLoadingPhoto = false
    }

    private func finishPhotoFailure(operationID: UUID) {
        guard photoOperationID == operationID else {
            return
        }
        photoLoadTask = nil
        isLoadingPhoto = false
        photoMessage = .unreadable
    }

    private func invalidateCameraPermissionOperation() {
        cameraPermissionOperationID = UUID()
        isRequestingCameraPermission = false
        isCameraPresented = false
    }

    private func applyCurrentCameraAccessState() {
        guard cameraAccess.isCameraAvailable() else {
            isCameraPresented = false
            cameraMessage = .unavailable
            return
        }
        switch cameraAccess.authorizationStatus() {
        case .authorized:
            isCameraPresented = true
            cameraMessage = nil
        case .denied, .notDetermined:
            isCameraPresented = false
            cameraMessage = .denied
        case .restricted:
            isCameraPresented = false
            cameraMessage = .restricted
        }
    }
}

struct CaptureView: View {
    @ObservedObject var acquisition: CaptureAcquisitionModel
    let isPreparingPreview: Bool
    let onCancelPreparation: () -> Void
    let content: CaptureConsentContent

    @State private var photoItem: PhotosPickerItem?
    @State private var showsPrivacy = false

    init(
        acquisition: CaptureAcquisitionModel,
        isPreparingPreview: Bool,
        onCancelPreparation: @escaping () -> Void,
        content: CaptureConsentContent = .production
    ) {
        self.acquisition = acquisition
        self.isPreparingPreview = isPreparingPreview
        self.onCancelPreparation = onCancelPreparation
        self.content = content
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                acquisitionActions
                if acquisition.isRequestingCameraPermission {
                    cameraPermissionStatus
                }
                if acquisition.isLoadingPhoto || isPreparingPreview {
                    preparationStatus
                }
                if let message = acquisition.photoMessage {
                    Text(message.explanation)
                        .font(.body)
                        .foregroundStyle(.primary)
                        .accessibilityIdentifier("capture.photoError")
                }
                privacyButton
                purposeNote
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(content.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: cameraBinding) {
            CameraPicker(
                onImageData: acquisition.receiveCapturedImage,
                onCancel: acquisition.cancelCamera
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showsPrivacy) {
            PrivacySheet(content: content)
        }
        .alert(item: cameraMessageBinding) { message in
            Alert(
                title: Text(message.title),
                message: Text(message.explanation),
                dismissButton: .default(Text("確認"))
            )
        }
        .onChange(of: photoItem) { _, newItem in
            guard let newItem else {
                return
            }
            acquisition.loadPhoto(using: PhotosPickerDataLoader(item: newItem))
        }
        .onDisappear {
            acquisition.invalidate()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "house")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(Color("BrandForest"))
                .accessibilityHidden(true)
            Text(content.captureHeading)
                .font(.title.bold())
                .foregroundStyle(.primary)
            Text(content.captureExplanation)
                .font(.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
        .accessibilitySortPriority(10)
        .accessibilityIdentifier("capture.heading")
    }

    private var acquisitionActions: some View {
        VStack(spacing: 12) {
            Button {
                Task { await acquisition.requestCamera() }
            } label: {
                Label(content.cameraAction.label, systemImage: "camera")
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .foregroundStyle(Color("BrandCream"))
            }
            .buttonStyle(.borderedProminent)
            .tint(Color("BrandForest"))
            .accessibilitySortPriority(8)
            .accessibilityIdentifier(content.cameraAction.identifier)
            .accessibilityHint(content.cameraAction.hint)

            PhotosPicker(selection: $photoItem, matching: .images) {
                Label(content.libraryAction.label, systemImage: "photo")
                    .frame(maxWidth: .infinity, minHeight: 52)
            }
            .buttonStyle(.bordered)
            .tint(Color("BrandForest"))
            .accessibilitySortPriority(7)
            .accessibilityIdentifier(content.libraryAction.identifier)
            .accessibilityHint(content.libraryAction.hint)
        }
        .disabled(
            acquisition.isRequestingCameraPermission
                || acquisition.isLoadingPhoto
                || isPreparingPreview
        )
    }

    private var cameraPermissionStatus: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ProgressView()
                Text("カメラの使用許可を確認しています")
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("カメラの使用許可を確認しています")
            .accessibilityHint("確認が終わるまでお待ちください。")
            .accessibilityIdentifier("capture.cameraPermissionProgress")

            Button(
                content.cancelCameraPermissionAction.label,
                action: acquisition.cancelCamera
            )
            .frame(minHeight: 44)
            .accessibilityIdentifier(content.cancelCameraPermissionAction.identifier)
            .accessibilityHint(content.cancelCameraPermissionAction.hint)
        }
    }

    private var preparationStatus: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ProgressView()
                Text("写真を確認する準備をしています")
                    .font(.body)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("写真を確認する準備をしています")

            Button(content.cancelPreparationAction.label) {
                acquisition.cancelPhotoLoad()
                onCancelPreparation()
                photoItem = nil
            }
            .frame(minHeight: 44)
            .accessibilityIdentifier(content.cancelPreparationAction.identifier)
            .accessibilityHint(content.cancelPreparationAction.hint)
        }
    }

    private var privacyButton: some View {
        Button {
            showsPrivacy = true
        } label: {
            Label(content.privacyAction.label, systemImage: "hand.raised")
                .frame(minHeight: 44)
        }
        .foregroundStyle(Color("BrandForest"))
        .accessibilitySortPriority(6)
        .accessibilityIdentifier(content.privacyAction.identifier)
        .accessibilityHint(content.privacyAction.hint)
    }

    private var purposeNote: some View {
        Text(content.disclosures.first?.text ?? "")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var cameraBinding: Binding<Bool> {
        Binding(
            get: { acquisition.isCameraPresented },
            set: { isPresented in
                if !isPresented {
                    acquisition.cancelCamera()
                }
            }
        )
    }

    private var cameraMessageBinding: Binding<CameraAccessMessage?> {
        Binding(
            get: { acquisition.cameraMessage },
            set: { message in
                if message == nil {
                    acquisition.dismissCameraMessage()
                }
            }
        )
    }
}
