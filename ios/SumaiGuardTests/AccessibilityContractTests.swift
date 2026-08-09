import CoreGraphics
import SwiftUI
import XCTest
@testable import SumaiGuard

@MainActor
final class AccessibilityContractTests: XCTestCase {
    func testEveryStateRendersSyntheticJapaneseContentAcrossAccessibilitySizesAndAppearances() throws {
        let response = try applicableFixture()
        let sizes: [DynamicTypeSize] = [
            .accessibility1,
            .accessibility2,
            .accessibility3,
            .accessibility4,
            .accessibility5,
        ]
        let appearances: [ColorScheme] = [.light, .dark]

        for size in sizes {
            for scheme in appearances {
                for (name, view) in try syntheticJapaneseViews(response: response) {
                    let rendered = view
                        .environment(\.locale, Locale(identifier: "ja_JP"))
                        .environment(\.dynamicTypeSize, size)
                        .environment(\.colorScheme, scheme)
                        .frame(width: 390, height: 844)
                    let renderer = ImageRenderer(content: rendered)
                    renderer.scale = 1

                    XCTAssertNotNil(
                        renderer.uiImage,
                        "\(name) must render at \(size), \(scheme)"
                    )
                }
            }
        }
    }

    func testVoiceOverReadingOrderIsExplicitForCaptureConsentAndProcessing() throws {
        let capture = try source("CaptureView.swift")
        assertPriority(capture, marker: #".accessibilityIdentifier("capture.heading")"#, priority: "10")
        assertPriority(
            capture,
            marker: ".accessibilityIdentifier(content.cameraAction.identifier)",
            priority: "8"
        )
        assertPriority(
            capture,
            marker: ".accessibilityIdentifier(content.libraryAction.identifier)",
            priority: "7"
        )
        assertPriority(
            capture,
            marker: ".accessibilityIdentifier(content.privacyAction.identifier)",
            priority: "6"
        )

        let consent = try source("ConsentView.swift")
        assertPriority(consent, marker: #".accessibilityIdentifier("consent.heading")"#, priority: "10")
        assertPriority(consent, marker: #".accessibilityIdentifier("consent.preview")"#, priority: "9")
        assertPriority(consent, marker: #".accessibilityIdentifier("consent.disclosures")"#, priority: "8")
        assertPriority(
            consent,
            marker: ".accessibilityIdentifier(content.agreeAction.identifier)",
            priority: "7"
        )
        assertPriority(
            consent,
            marker: ".accessibilityIdentifier(content.cancelConsentAction.identifier)",
            priority: "6"
        )
        assertPriority(consent, marker: #".accessibilityIdentifier("consent.privacy")"#, priority: "5")

        let processing = try source("ProcessingView.swift")
        assertPriority(processing, marker: #".accessibilityIdentifier("processing.heading")"#, priority: "10")
        assertPriority(
            processing,
            marker: #".accessibilityIdentifier("processing.explanation")"#,
            priority: "9"
        )
        assertPriority(
            processing,
            marker: #".accessibilityIdentifier("processing.progress.indeterminate")"#,
            priority: "8"
        )
        assertPriority(processing, marker: #".accessibilityIdentifier("processing.preview")"#, priority: "7")
        assertPriority(
            processing,
            marker: #".accessibilityIdentifier("processing.privacy")"#,
            priority: "6"
        )
        assertPriority(processing, marker: #".accessibilityIdentifier("processing.cancel")"#, priority: "5")
    }

    func testVoiceOverReadingOrderIsExplicitForResultAdviceAndTerminalStates() throws {
        let result = try source("ResultView.swift")
        assertPriority(result, marker: #".accessibilityIdentifier("result.heading")"#, priority: "10")
        assertPriority(result, marker: #".accessibilityIdentifier("result.findings")"#, priority: "6")
        assertPriority(result, marker: #".accessibilityIdentifier("result.limitations")"#, priority: "5")
        assertPriority(result, marker: #".accessibilityIdentifier("result.showAdvice")"#, priority: "4")
        assertPriority(result, marker: #".accessibilityIdentifier("result.returnHome")"#, priority: "3")

        let advice = try source("AdviceView.swift")
        assertPriority(advice, marker: #".accessibilityIdentifier("advice.heading")"#, priority: "10")
        assertPriority(advice, marker: #".accessibilityIdentifier("advice.disclaimer")"#, priority: "4")
        assertPriority(advice, marker: #".accessibilityIdentifier("advice.sharePDF")"#, priority: "3")
        assertPriority(advice, marker: #".accessibilityIdentifier("advice.returnHome")"#, priority: "2")

        let terminalContracts: [(String, String, String)] = [
            ("NoFindingsView.swift", "noFindings.heading", "noFindings.returnHome"),
            ("NotApplicableView.swift", "notApplicable.heading", "notApplicable.returnHome"),
            ("ErrorView.swift", "error.heading", "error.returnHome"),
        ]
        for (file, heading, action) in terminalContracts {
            let text = try source(file)
            assertPriority(
                text,
                marker: ".accessibilityIdentifier(\"\(heading)\")",
                priority: "10"
            )
            assertPriority(
                text,
                marker: ".accessibilityIdentifier(\"\(action)\")",
                priority: "3"
            )
        }
    }

    func testEveryInteractiveControlHasAtLeastFortyFourPointTouchContract() throws {
        let contracts: [(String, [String])] = [
            (
                "CaptureView.swift",
                [
                    ".accessibilityIdentifier(content.cameraAction.identifier)",
                    ".accessibilityIdentifier(content.libraryAction.identifier)",
                    ".accessibilityIdentifier(content.cancelCameraPermissionAction.identifier)",
                    ".accessibilityIdentifier(content.cancelPreparationAction.identifier)",
                    ".accessibilityIdentifier(content.privacyAction.identifier)",
                ]
            ),
            (
                "ConsentView.swift",
                [
                    ".accessibilityIdentifier(content.agreeAction.identifier)",
                    ".accessibilityIdentifier(content.cancelConsentAction.identifier)",
                    #".accessibilityIdentifier("consent.privacy")"#,
                ]
            ),
            ("PrivacySheet.swift", [#".accessibilityIdentifier("privacy.close")"#]),
            ("ProcessingView.swift", [#".accessibilityIdentifier("processing.cancel")"#]),
            (
                "ResultView.swift",
                [
                    #".accessibilityIdentifier("result.showAdvice")"#,
                    #".accessibilityIdentifier("result.returnHome")"#,
                    #".accessibilityIdentifier("result.failClosed.returnHome")"#,
                ]
            ),
            (
                "AdviceView.swift",
                [
                    #".accessibilityIdentifier("advice.sharePDF")"#,
                    #".accessibilityIdentifier("advice.cancelPDF")"#,
                    #".accessibilityIdentifier("advice.returnHome")"#,
                ]
            ),
            ("NoFindingsView.swift", [#".accessibilityIdentifier("noFindings.returnHome")"#]),
            ("NotApplicableView.swift", [#".accessibilityIdentifier("notApplicable.returnHome")"#]),
            (
                "ErrorView.swift",
                [
                    #".accessibilityIdentifier("error.retry")"#,
                    #".accessibilityIdentifier("error.returnHome")"#,
                ]
            ),
        ]

        for (file, markers) in contracts {
            let text = try source(file)
            for marker in markers {
                let markerRange = try XCTUnwrap(text.range(of: marker), "missing \(marker) in \(file)")
                let prefix = String(text[..<markerRange.lowerBound].suffix(700))
                XCTAssertTrue(
                    prefix.contains("minHeight: 44") || prefix.contains("minHeight: 52"),
                    "\(marker) in \(file) must have a 44-point or larger control frame"
                )
            }
        }
    }

    func testBrandColorsProvideLightDarkAndHighContrastVariants() throws {
        let forest = try colors(named: "BrandForest")
        let cream = try colors(named: "BrandCream")
        let gold = try colors(named: "BrandGold")
        let expectedAppearances = Set(["standard", "dark", "high", "dark+high"])

        XCTAssertEqual(Set(forest.keys), expectedAppearances)
        XCTAssertEqual(Set(cream.keys), expectedAppearances)
        XCTAssertEqual(Set(gold.keys), expectedAppearances)
        for appearance in expectedAppearances {
            let foreground = try XCTUnwrap(forest[appearance])
            let background = try XCTUnwrap(cream[appearance])
            XCTAssertGreaterThanOrEqual(
                contrastRatio(foreground, background),
                4.5,
                "BrandForest on BrandCream must meet WCAG AA for \(appearance)"
            )
            XCTAssertEqual(foreground.alpha, 1)
            XCTAssertEqual(background.alpha, 1)
            XCTAssertEqual(try XCTUnwrap(gold[appearance]).alpha, 1)
        }

        let viewSources = try [
            "CaptureView.swift",
            "ConsentView.swift",
            "ProcessingView.swift",
            "ResultView.swift",
            "AdviceView.swift",
        ].map(source).joined(separator: "\n")
        XCTAssertFalse(viewSources.contains(#"foregroundStyle(Color("BrandGold"))"#))
    }

    func testReduceMotionHasNoCustomMotionPathAndDynamicTextIsNotClamped() throws {
        let files = [
            "CaptureView.swift",
            "ConsentView.swift",
            "PrivacySheet.swift",
            "ProcessingView.swift",
            "ResultView.swift",
            "AdviceView.swift",
            "NoFindingsView.swift",
            "NotApplicableView.swift",
            "ErrorView.swift",
        ]
        let forbiddenMotion = ["withAnimation(", ".animation(", "repeatForever(", "TimelineView", "Canvas {"]
        let forbiddenClamping = [".lineLimit(1)", ".minimumScaleFactor("]

        for file in files {
            let text = try source(file)
            for marker in forbiddenMotion + forbiddenClamping {
                XCTAssertFalse(text.contains(marker), "\(file) must not contain \(marker)")
            }
        }
    }

    func testJapaneseAccessibilityLabelsCoverTheFullConsentAndResultFlow() throws {
        let capture = CaptureConsentContent.production
        XCTAssertTrue(capture.allAccessibilityText.allSatisfy(containsJapaneseText))
        XCTAssertEqual(capture.disclosures.map(\.id), [
            .purpose,
            .recipients,
            .privateContext,
            .noStorage,
            .noConsentNoSend,
            .professionalBoundary,
        ])
        XCTAssertTrue(capture.disclosures.map(\.text).allSatisfy(containsJapaneseText))

        let response = try applicableFixture()
        let result = try XCTUnwrap(ResultPresentation(response: response))
        let advice = AdvicePresentation(response: response)
        XCTAssertEqual(result.heading, "写真で確認できた注意箇所")
        XCTAssertEqual(result.images.map(\.accessibilityLabel), [
            "赤枠で示した注意候補の画像",
            "注意候補に対応した改善イメージ",
        ])
        XCTAssertEqual(advice.sections.map(\.heading), [
            "家族で今日できること",
            "ケアマネ・福祉用具に相談",
            "専門施工・現地確認",
        ])
        XCTAssertTrue(containsJapaneseText(result.visibleText))
        XCTAssertTrue(containsJapaneseText(advice.visibleText))
    }

    private func syntheticJapaneseViews(response: AnalysisResponse) throws -> [(String, AnyView)] {
        let selection = SelectedImage(preview: try syntheticImage())
        let acquisition = CaptureAcquisitionModel(cameraAccess: UnavailableCameraAccess()) { _ in }
        return [
            (
                "capture",
                AnyView(CaptureView(
                    acquisition: acquisition,
                    isPreparingPreview: false,
                    onCancelPreparation: {}
                ))
            ),
            (
                "consent",
                AnyView(ConsentView(
                    selection: selection,
                    actions: .init(agree: {}, cancel: {})
                ))
            ),
            (
                "privacy",
                AnyView(PrivacySheet(content: .production))
            ),
            (
                "processing",
                AnyView(ProcessingView(
                    selection: selection,
                    actions: .init(cancelProcessing: {})
                ))
            ),
            (
                "result",
                AnyView(ResultView(
                    response: response,
                    actions: .init(showAdvice: {}, returnHome: {})
                ))
            ),
            (
                "advice",
                AnyView(AdviceView(
                    response: response,
                    actions: .init(returnHome: {}, shareAdvice: {}, cancelPDF: {})
                ))
            ),
            ("noFindings", AnyView(NoFindingsView(actions: .init(returnHome: {})))),
            (
                "notApplicable",
                AnyView(NotApplicableView(
                    reason: "室内を確認できる写真ではありませんでした。",
                    actions: .init(returnHome: {})
                ))
            ),
            (
                "error",
                AnyView(ErrorView(
                    error: .network,
                    actions: .init(retry: {}, returnHome: {})
                ))
            ),
        ]
    }

    private func assertPriority(
        _ source: String,
        marker: String,
        priority: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard let markerRange = source.range(of: marker) else {
            XCTFail("missing accessibility marker \(marker)", file: file, line: line)
            return
        }
        let prefix = String(source[..<markerRange.lowerBound].suffix(320))
        XCTAssertTrue(
            prefix.contains(".accessibilitySortPriority(\(priority))"),
            "\(marker) must declare VoiceOver priority \(priority)",
            file: file,
            line: line
        )
    }

    private func source(_ name: String) throws -> String {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "SumaiGuard/Views/\(name)")
        return try String(contentsOf: url, encoding: .utf8)
    }

    private func colors(named name: String) throws -> [String: RGBA] {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "SumaiGuard/Resources/Assets.xcassets/\(name).colorset/Contents.json")
        let root = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
        )
        let entries = try XCTUnwrap(root["colors"] as? [[String: Any]])
        var result: [String: RGBA] = [:]
        for entry in entries {
            let color = try XCTUnwrap(entry["color"] as? [String: Any])
            let components = try XCTUnwrap(color["components"] as? [String: String])
            let appearances = entry["appearances"] as? [[String: String]] ?? []
            let isDark = appearances.contains { $0["appearance"] == "luminosity" && $0["value"] == "dark" }
            let isHigh = appearances.contains { $0["appearance"] == "contrast" && $0["value"] == "high" }
            let key = switch (isDark, isHigh) {
            case (false, false): "standard"
            case (true, false): "dark"
            case (false, true): "high"
            case (true, true): "dark+high"
            }
            result[key] = try RGBA(components: components)
        }
        return result
    }

    private func contrastRatio(_ first: RGBA, _ second: RGBA) -> Double {
        let firstLuminance = relativeLuminance(first)
        let secondLuminance = relativeLuminance(second)
        return (max(firstLuminance, secondLuminance) + 0.05)
            / (min(firstLuminance, secondLuminance) + 0.05)
    }

    private func relativeLuminance(_ color: RGBA) -> Double {
        func linear(_ component: Double) -> Double {
            component <= 0.04045
                ? component / 12.92
                : pow((component + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(color.red)
            + 0.7152 * linear(color.green)
            + 0.0722 * linear(color.blue)
    }

    private func containsJapaneseText(_ value: String) -> Bool {
        value.unicodeScalars.contains { scalar in
            (0x3040...0x30FF).contains(scalar.value)
                || (0x4E00...0x9FFF).contains(scalar.value)
        }
    }

    private func applicableFixture() throws -> AnalysisResponse {
        let url = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "analysis-applicable", withExtension: "json")
        )
        return try JSONDecoder.sumai.decode(AnalysisResponse.self, from: Data(contentsOf: url))
    }

    private func syntheticImage() throws -> CGImage {
        guard
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: 8,
                height: 8,
                bitsPerComponent: 8,
                bytesPerRow: 32,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            )
        else {
            throw AccessibilityTestError.imageCreationFailed
        }
        context.setFillColor(CGColor(red: 0.09, green: 0.24, blue: 0.20, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: 8, height: 8))
        guard let image = context.makeImage() else {
            throw AccessibilityTestError.imageCreationFailed
        }
        return image
    }
}

private struct RGBA {
    let red: Double
    let green: Double
    let blue: Double
    let alpha: Double

    init(components: [String: String]) throws {
        guard
            let red = Double(components["red"] ?? ""),
            let green = Double(components["green"] ?? ""),
            let blue = Double(components["blue"] ?? ""),
            let alpha = Double(components["alpha"] ?? "")
        else {
            throw AccessibilityTestError.invalidColor
        }
        self.red = red
        self.green = green
        self.blue = blue
        self.alpha = alpha
    }
}

@MainActor
private final class UnavailableCameraAccess: CameraAccessProviding {
    func isCameraAvailable() -> Bool { false }
    func authorizationStatus() -> CameraAuthorizationState { .denied }
    func requestAccess() async -> Bool { false }
}

private enum AccessibilityTestError: Error {
    case imageCreationFailed
    case invalidColor
}
