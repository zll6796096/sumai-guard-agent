import XCTest

final class ProjectContractTests: XCTestCase {
    private var appInfo: [String: Any] {
        Bundle.main.infoDictionary ?? [:]
    }

    func testAppUsesApprovedBundleIdentifier() {
        XCTAssertEqual(Bundle.main.bundleIdentifier, "com.zll.sumaiguard")
    }

    func testAppUsesApprovedJapaneseDisplayName() {
        XCTAssertEqual(appInfo["CFBundleName"] as? String, "実家あんしんチェック")
        XCTAssertEqual(appInfo["CFBundleDisplayName"] as? String, "実家チェック")
    }

    func testAppStartsAtVersionOneBuildThree() {
        XCTAssertEqual(appInfo["CFBundleShortVersionString"] as? String, "1.0")
        XCTAssertEqual(appInfo["CFBundleVersion"] as? String, "3")
    }

    func testAppTargetsIPhoneOnIOS17OrLater() {
        XCTAssertEqual(appInfo["UIDeviceFamily"] as? [Int], [1])
        XCTAssertEqual(appInfo["MinimumOSVersion"] as? String, "17.0")
    }

    func testAppSupportsPortraitOnly() {
        XCTAssertEqual(
            appInfo["UISupportedInterfaceOrientations"] as? [String],
            ["UIInterfaceOrientationPortrait"]
        )
    }

    func testAppStartsWithFailClosedServiceConfiguration() {
        XCTAssertEqual(appInfo["SUMAI_API_ORIGIN"] as? String, "https://invalid.invalid")
        XCTAssertEqual(appInfo["FirebaseAppDelegateProxyEnabled"] as? Bool, false)
    }

    func testAppRequestsCameraAccessWithoutRequestingPhotoLibraryAccess() {
        XCTAssertNotNil(appInfo["NSCameraUsageDescription"] as? String)
        XCTAssertNil(appInfo["NSPhotoLibraryUsageDescription"])
        XCTAssertNil(appInfo["NSPhotoLibraryAddUsageDescription"])
    }
}
