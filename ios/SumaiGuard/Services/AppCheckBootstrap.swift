import FirebaseAppCheck
import FirebaseCore
import Foundation

enum AppCheckBuildMode: Equatable, Sendable {
    case debug
    case release

    static var compiled: Self {
#if DEBUG
        .debug
#else
        .release
#endif
    }
}

enum AppCheckProviderKind: Equatable, Sendable {
    case appAttest
    case debug

    static func forBuildMode(_ mode: AppCheckBuildMode) -> Self {
        switch mode {
        case .debug:
            .debug
        case .release:
            .appAttest
        }
    }
}

enum FirebaseBootstrapReadiness: Equatable, Sendable {
    case missingConfiguration
    case ready
    case alreadyConfigured
}

enum AppCheckBootstrapResult: Equatable, Sendable {
    case configured(AppCheckProviderKind)
    case missingConfiguration
    case configuredOutOfOrder
    case alreadyConfigured
}

@MainActor
protocol AppCheckBootstrapBackend: AnyObject {
    var readiness: FirebaseBootstrapReadiness { get }
    func installProvider(_ kind: AppCheckProviderKind)
    func configureFirebase()
}

@MainActor
final class AppCheckBootstrapController {
    private var isConfigured = false
    private let didConfigure: () -> Void

    init(didConfigure: @escaping () -> Void = {}) {
        self.didConfigure = didConfigure
    }

    func configure(
        mode: AppCheckBuildMode,
        backend: any AppCheckBootstrapBackend
    ) -> AppCheckBootstrapResult {
        guard !isConfigured else {
            return .alreadyConfigured
        }

        switch backend.readiness {
        case .missingConfiguration:
            return .missingConfiguration
        case .alreadyConfigured:
            return .configuredOutOfOrder
        case .ready:
            let provider = AppCheckProviderKind.forBuildMode(mode)
            backend.installProvider(provider)
            backend.configureFirebase()
            isConfigured = true
            didConfigure()
            return .configured(provider)
        }
    }
}

@MainActor
enum AppCheckBootstrap {
    private static let controller = AppCheckBootstrapController {
        AppCheckRuntimeReadiness.shared.markReady()
    }

    @discardableResult
    static func configure() -> AppCheckBootstrapResult {
        controller.configure(
            mode: .compiled,
            backend: FirebaseAppCheckBootstrapBackend()
        )
    }
}

enum AppCheckProviderFactoryConstruction {
    static func make(for kind: AppCheckProviderKind) -> any AppCheckProviderFactory {
#if DEBUG
        switch kind {
        case .appAttest:
            AppAttestProviderFactory()
        case .debug:
            AppCheckDebugProviderFactory()
        }
#else
        AppAttestProviderFactory()
#endif
    }
}

@MainActor
private final class FirebaseAppCheckBootstrapBackend: AppCheckBootstrapBackend {
    var readiness: FirebaseBootstrapReadiness {
        guard FirebaseApp.allApps?.isEmpty != false else {
            return .alreadyConfigured
        }
        guard
            let configurationPath = Bundle.main.path(
                forResource: "GoogleService-Info",
                ofType: "plist"
            ),
            let options = FirebaseOptions(contentsOfFile: configurationPath),
            options.bundleID == Bundle.main.bundleIdentifier,
            !options.googleAppID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            !options.gcmSenderID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            let apiKey = options.apiKey,
            !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            let projectID = options.projectID,
            !projectID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            return .missingConfiguration
        }
        return .ready
    }

    func installProvider(_ kind: AppCheckProviderKind) {
        AppCheck.setAppCheckProviderFactory(
            AppCheckProviderFactoryConstruction.make(for: kind)
        )
    }

    func configureFirebase() {
        FirebaseApp.configure()
    }
}

enum AppCheckTokenError: Error, Equatable, Sendable {
    case notConfigured
    case unavailable
}

private final class AppCheckRuntimeReadiness: @unchecked Sendable {
    static let shared = AppCheckRuntimeReadiness()

    private let lock = NSLock()
    private var ready = false

    var isReady: Bool {
        lock.withLock { ready }
    }

    func markReady() {
        lock.withLock { ready = true }
    }
}

struct FirebaseAppCheckTokenProvider: AppCheckTokenProviding {
    private let isFirebaseConfigured: @Sendable () -> Bool
    private let isBootstrapReady: @Sendable () -> Bool

    init() {
        isFirebaseConfigured = {
            FirebaseApp.app() != nil
        }
        isBootstrapReady = {
            AppCheckRuntimeReadiness.shared.isReady
        }
    }

    init(
        isFirebaseConfigured: @escaping @Sendable () -> Bool,
        isBootstrapReady: @escaping @Sendable () -> Bool
    ) {
        self.isFirebaseConfigured = isFirebaseConfigured
        self.isBootstrapReady = isBootstrapReady
    }

    func token() async throws -> String {
        try Task.checkCancellation()
        guard isBootstrapReady(), isFirebaseConfigured() else {
            throw AppCheckTokenError.notConfigured
        }

        let result: AppCheckToken
        do {
            result = try await AppCheck.appCheck().token(forcingRefresh: false)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw AppCheckTokenError.unavailable
        }

        try Task.checkCancellation()
        guard !result.token.isEmpty else {
            throw AppCheckTokenError.unavailable
        }
        return result.token
    }
}
