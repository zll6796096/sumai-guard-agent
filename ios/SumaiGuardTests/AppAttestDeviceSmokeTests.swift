import CryptoKit
import Foundation
import UIKit
import XCTest
@testable import SumaiGuard

final class AppAttestDeviceSmokeTests: XCTestCase {
    func testPhysicalDeviceAppAttestCandidateRoundTrip() async throws {
        let bundle = Bundle.main
        let enabled = bundle.object(
            forInfoDictionaryKey: "SUMAI_APP_ATTEST_DEVICE_SMOKE"
        ) as? String
        try XCTSkipUnless(enabled == "YES", "physical-device smoke is opt-in")

        #if targetEnvironment(simulator)
        XCTFail("App Attest smoke must run on a physical iOS device")
        #else
        let sourceSHA = try requiredBundleValue("SUMAI_SOURCE_SHA", bundle: bundle)
        let agentRevision = try requiredBundleValue(
            "SUMAI_AGENT_REVISION",
            bundle: bundle
        )
        let agentURL = try requiredBundleValue("SUMAI_AGENT_URL", bundle: bundle)
        XCTAssertTrue(sourceSHA.range(of: #"^[0-9a-f]{40}$"#, options: .regularExpression) != nil)
        XCTAssertTrue(
            agentRevision.range(
                of: #"^[a-z][a-z0-9-]{0,62}$"#,
                options: .regularExpression
            ) != nil
        )

        let origin = try APIOrigin(agentURL)
        let syntheticSource = syntheticImageData()
        let sanitized = try await ImageSanitizer().sanitize(syntheticSource)
        let authorized = try await APIClient(
            origin: origin,
            tokenProvider: FirebaseAppCheckTokenProvider()
        ).prepareAnalysis()
        _ = try await authorized.analyze(
            image: sanitized,
            roomHint: "リビング"
        )

        let evidence: [String: Any] = [
            "schema_version": 1,
            "source_commit": sourceSHA,
            "agent_revision": agentRevision,
            "agent_url": agentURL,
            "app_attest_provider": "AppAttestProvider",
            "http_status": 200,
            "observed_at": ISO8601DateFormatter().string(from: Date()),
            "synthetic_sample_sha256": SHA256.hash(data: sanitized.data)
                .map { String(format: "%02x", $0) }
                .joined(),
        ]
        let payload = try JSONSerialization.data(
            withJSONObject: evidence,
            options: [.sortedKeys]
        )
        let destination = try XCTUnwrap(
            FileManager.default.urls(
                for: .documentDirectory,
                in: .userDomainMask
            ).first
        ).appending(path: "sumai-device-evidence.json")
        try payload.write(to: destination, options: [.atomic])
        #endif
    }

    private func requiredBundleValue(
        _ key: String,
        bundle: Bundle
    ) throws -> String {
        let value = try XCTUnwrap(bundle.object(forInfoDictionaryKey: key) as? String)
        return try XCTUnwrap(
            value.isEmpty ? nil : value,
            "missing smoke build value"
        )
    }

    private func syntheticImageData() -> Data {
        let renderer = UIGraphicsImageRenderer(
            size: CGSize(width: 96, height: 96)
        )
        return renderer.pngData { context in
            context.cgContext.setFillColor(
                UIColor(
                    red: 0.09,
                    green: 0.24,
                    blue: 0.20,
                    alpha: 1
                ).cgColor
            )
            context.cgContext.fill(
                CGRect(x: 0, y: 0, width: 96, height: 96)
            )
            context.cgContext.setFillColor(UIColor.white.cgColor)
            context.cgContext.fill(
                CGRect(x: 20, y: 50, width: 56, height: 8)
            )
        }
    }
}
