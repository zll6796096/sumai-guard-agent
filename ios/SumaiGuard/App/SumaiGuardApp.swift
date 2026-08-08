import SwiftUI
import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        AppCheckBootstrap.configure()
        return true
    }
}

@main
struct SumaiGuardApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            CapturePlaceholderView()
        }
    }
}

private struct CapturePlaceholderView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView {
                Label("安全チェックをはじめる", systemImage: "camera.viewfinder")
            } description: {
                Text("住まいの写真から、目に見える転倒・滑り・つまずきの危険を確認します。")
            } actions: {
                Button("写真を撮る") {}
                    .buttonStyle(.borderedProminent)
                    .disabled(true)
            }
            .navigationTitle("実家あんしんチェック")
            .background(Color(uiColor: .systemGroupedBackground))
        }
    }
}
