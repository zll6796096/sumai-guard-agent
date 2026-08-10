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
#if DEBUG
            if let scene = AppStoreScreenshotScene.current {
                AppStoreScreenshotRoot(scene: scene)
            } else {
                RootView()
            }
#else
            RootView()
#endif
        }
    }
}
