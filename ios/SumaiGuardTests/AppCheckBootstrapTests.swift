import Foundation
import FirebaseAppCheck
@testable import SumaiGuard
import XCTest

@MainActor
final class AppCheckBootstrapTests: XCTestCase {
    func testReleaseBuildSelectsAppAttestProvider() {
        XCTAssertEqual(AppCheckProviderKind.forBuildMode(.release), .appAttest)
    }

    func testDebugBuildSelectsDebugProvider() {
        XCTAssertEqual(AppCheckProviderKind.forBuildMode(.debug), .debug)
    }

    func testReleaseSelectionConstructsFirebaseAppAttestFactory() {
        let factory = AppCheckProviderFactoryConstruction.make(for: .appAttest)

        XCTAssertTrue(factory is AppAttestProviderFactory)
        XCTAssertFalse(factory is AppCheckDebugProviderFactory)
    }

    func testProductionFactoryIsBuildIsolatedWhenDebugIsRequested() {
        let factory = AppCheckProviderFactoryConstruction.make(for: .debug)

#if DEBUG
        XCTAssertTrue(factory is AppCheckDebugProviderFactory)
        XCTAssertFalse(factory is AppAttestProviderFactory)
#else
        XCTAssertTrue(factory is AppAttestProviderFactory)
        XCTAssertFalse(factory is AppCheckDebugProviderFactory)
#endif
    }

    func testCompiledProviderMatchesCurrentBuildConfiguration() {
#if DEBUG
        XCTAssertEqual(AppCheckBuildMode.compiled, .debug)
#else
        XCTAssertEqual(AppCheckBuildMode.compiled, .release)
#endif
    }

    func testProviderIsInstalledBeforeFirebaseAndOnlyOnce() {
        let backend = RecordingBootstrapBackend(readiness: .ready)
        let controller = AppCheckBootstrapController()

        XCTAssertEqual(controller.configure(mode: .release, backend: backend), .configured(.appAttest))
        XCTAssertEqual(controller.configure(mode: .debug, backend: backend), .alreadyConfigured)
        XCTAssertEqual(backend.events, [.provider(.appAttest), .firebase])
    }

    func testMissingFirebaseConfigurationRemainsUnconfiguredAndCanRetryLater() {
        let backend = RecordingBootstrapBackend(readiness: .missingConfiguration)
        let controller = AppCheckBootstrapController()

        XCTAssertEqual(controller.configure(mode: .release, backend: backend), .missingConfiguration)
        XCTAssertTrue(backend.events.isEmpty)

        backend.readiness = .ready
        XCTAssertEqual(controller.configure(mode: .release, backend: backend), .configured(.appAttest))
        XCTAssertEqual(backend.events, [.provider(.appAttest), .firebase])
    }

    func testAlreadyConfiguredFirebaseFailsClosedBeforeInstallingProvider() {
        let backend = RecordingBootstrapBackend(readiness: .alreadyConfigured)
        let controller = AppCheckBootstrapController()

        XCTAssertEqual(controller.configure(mode: .release, backend: backend), .configuredOutOfOrder)
        XCTAssertTrue(backend.events.isEmpty)
    }

    func testFirebaseTokenProviderFailsStablyWhenFirebaseIsUnconfigured() async {
        let provider = FirebaseAppCheckTokenProvider(
            isFirebaseConfigured: { false },
            isBootstrapReady: { false }
        )

        do {
            _ = try await provider.token()
            XCTFail("Missing Firebase configuration must not produce a token")
        } catch {
            XCTAssertEqual(error as? AppCheckTokenError, .notConfigured)
            XCTAssertFalse(String(describing: error).contains("GoogleService"))
        }
    }

    func testFirebaseTokenProviderFailsClosedWhenFirebaseWasConfiguredOutOfOrder() async {
        let provider = FirebaseAppCheckTokenProvider(
            isFirebaseConfigured: { true },
            isBootstrapReady: { false }
        )

        do {
            _ = try await provider.token()
            XCTFail("Out-of-order Firebase configuration must not use a default provider")
        } catch {
            XCTAssertEqual(error as? AppCheckTokenError, .notConfigured)
        }
    }
}

@MainActor
private final class RecordingBootstrapBackend: AppCheckBootstrapBackend {
    enum Event: Equatable {
        case provider(AppCheckProviderKind)
        case firebase
    }

    var readiness: FirebaseBootstrapReadiness
    private(set) var events: [Event] = []

    init(readiness: FirebaseBootstrapReadiness) {
        self.readiness = readiness
    }

    func installProvider(_ kind: AppCheckProviderKind) {
        events.append(.provider(kind))
    }

    func configureFirebase() {
        events.append(.firebase)
    }
}
