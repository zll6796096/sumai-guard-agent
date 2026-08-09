import CoreGraphics
import Foundation
import PDFKit
import SwiftUI
@testable import SumaiGuard
import UniformTypeIdentifiers
import UIKit
import XCTest

final class SafetyPDFRendererTests: XCTestCase {
    func testDocumentIsNarrowAndFactoryCopiesOnlyValidatedPresentationText() async throws {
        let response = try fixture("analysis-applicable")
        let validated = try XCTUnwrap(ValidatedPresentationResponse(response: response))
        let document = try SafetyPDFDocument(validatedResponse: validated)

        XCTAssertEqual(document.visibleRisks.map(\.label), response.findings.map(\.labelJA))
        XCTAssertEqual(document.visibleRisks.map(\.evidence), response.findings.map(\.evidenceJA))
        XCTAssertEqual(document.familyActions.map(\.title), response.actionPlan.familyNoCost.map(\.titleJA))
        XCTAssertEqual(document.careManagerActions.map(\.title), response.actionPlan.careManagerPurchase.map(\.titleJA))
        XCTAssertEqual(document.contractorActions.map(\.title), response.actionPlan.contractorConstruction.map(\.titleJA))

        let forbiddenFragments = [
            "image", "base64", "model", "analysisid", "resultkey", "hash", "version",
            "timing", "token", "request", "identifier", "basislabel",
        ]
        let labels = recursivePropertyLabels(of: document).map { $0.lowercased() }
        for forbidden in forbiddenFragments {
            XCTAssertFalse(labels.contains { $0.contains(forbidden) }, "Narrow PDF document leaked field: \(forbidden)")
        }
        XCTAssertFalse(labels.contains("id"))

        let untrustedBasisLabel = "外部入力ラベル"
        let markedResponse = try modifiedFixture { object in
            var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
            findings[0]["basis_label_ja"] = untrustedBasisLabel
            object["findings"] = findings
        }
        let markedValidated = try XCTUnwrap(ValidatedPresentationResponse(response: markedResponse))
        let markedDocument = try SafetyPDFDocument(validatedResponse: markedValidated)
        let markedText = try extractedText(await SafetyPDFRenderer().render(markedDocument))
        XCTAssertTrue(markedText.contains("判断の根拠"))
        XCTAssertTrue(markedText.contains(markedResponse.findings[0].basisSummaryJA))
        XCTAssertFalse(markedText.contains(untrustedBasisLabel))
    }

    func testRenderedPDFContainsJapaneseVisibleBasisThreeTiersDisclaimerAndLastMultipageItem() async throws {
        let document = try longDocument()
        let data = try await SafetyPDFRenderer().render(document)
        let pdf = try XCTUnwrap(PDFDocument(data: data))
        let text = (0..<pdf.pageCount)
            .compactMap { pdf.page(at: $0)?.string }
            .joined(separator: "\n")

        XCTAssertGreaterThan(pdf.pageCount, 1)
        XCTAssertTrue(text.contains("実家あんしんチェック 安全のためにできること"))
        XCTAssertTrue(text.contains("写真で確認できた注意箇所"))
        XCTAssertTrue(text.contains("玄関の通路に物が見えます"))
        XCTAssertTrue(text.contains("写真上の根拠"))
        XCTAssertTrue(text.contains("家族で今日できること"))
        XCTAssertTrue(text.contains("ケアマネ・福祉用具に相談"))
        XCTAssertTrue(text.contains("専門施工・現地確認"))
        XCTAssertTrue(text.contains("写真1枚に写っている範囲だけ"))
        XCTAssertTrue(text.contains("AIが見落とした危険がある可能性があります"))
        XCTAssertTrue(text.contains("医療・介護認定・保険・法令適合・施工可否・見積もり"))
        XCTAssertTrue(text.contains("このPOCは、アップロードした写真や生成したPDFを保存しません"))
        XCTAssertTrue(text.contains("最終項目：現地で床の状態を確認する"))
    }

    func testRenderedPDFPreservesActionOrderWithoutTruncatingOrInventingActions() async throws {
        let document = try sampleDocument(
            familyTitles: ["順序一", "順序二", "順序三"],
            contractorTitles: ["既存施工一", "既存施工二"]
        )
        let data = try await SafetyPDFRenderer().render(document)
        let text = try extractedText(data)

        let first = try XCTUnwrap(text.range(of: "順序一"))
        let second = try XCTUnwrap(text.range(of: "順序二"))
        let third = try XCTUnwrap(text.range(of: "順序三"))
        XCTAssertLessThan(first.lowerBound, second.lowerBound)
        XCTAssertLessThan(second.lowerBound, third.lowerBound)
        XCTAssertTrue(text.contains("既存施工一"))
        XCTAssertTrue(text.contains("既存施工二"))
        XCTAssertFalse(text.contains("新しく購入"))
        XCTAssertFalse(text.contains("…"))
    }

    func testRenderedPDFHasNoImagesSensitiveMarkersOrSensitiveDocumentInfo() async throws {
        let data = try await SafetyPDFRenderer().render(try sampleDocument())
        let text = try extractedText(data)
        for forbidden in [
            "analysis_id", "data:image/", "annotated_image_base64", "response image",
            "gemini-2", "model marker", "token", "stage_timings_ms", "request ID",
            "request_id", "semantic_hash",
        ] {
            XCTAssertFalse(text.localizedCaseInsensitiveContains(forbidden), forbidden)
        }
        XCTAssertEqual(try pdfImageXObjectCount(data), 0)

        let pdf = try XCTUnwrap(PDFDocument(data: data))
        let attributes = pdf.documentAttributes ?? [:]
        let titleKey = PDFDocumentAttribute.titleAttribute
        let creatorKey = PDFDocumentAttribute.creatorAttribute
        XCTAssertEqual(Set(attributes.keys), Set([AnyHashable(titleKey), AnyHashable(creatorKey)]))
        XCTAssertEqual(
            attributes[titleKey] as? String,
            "実家あんしんチェック 安全のためにできること"
        )
        XCTAssertEqual(attributes[creatorKey] as? String, "SumaiGuard")
        let metadata = attributes.map { "\($0.key)=\($0.value)" }.joined(separator: "\n")
        for forbidden in ["analysis", "request", "token", "model", "base64", "timing", "hash"] {
            XCTAssertFalse(metadata.localizedCaseInsensitiveContains(forbidden), metadata)
        }
        let privacyAudit = try pdfPrivacyAudit(data)
        XCTAssertEqual(privacyAudit.imageXObjectCount, 0)
        XCTAssertEqual(privacyAudit.inlineImageCount, 0)
        XCTAssertFalse(privacyAudit.hasCatalogMetadata)
        XCTAssertFalse(privacyAudit.hasEmbeddedFiles)
        XCTAssertEqual(privacyAudit.infoKeys, ["Creator", "Title"])
        let rawPDF = String(decoding: data, as: UTF8.self)
        for forbiddenKey in ["/CreationDate", "/ModDate", "/Producer", "/Metadata", "/EmbeddedFiles"] {
            XCTAssertFalse(rawPDF.contains(forbiddenKey), forbiddenKey)
        }
    }

    func testPrivacyScannerDetectsImagesAcrossReachablePDFGraphs() throws {
        XCTAssertGreaterThan(try pdfImageXObjectCount(syntheticInlineImagePDF()), 0)
        XCTAssertGreaterThan(try pdfImageXObjectCount(syntheticInheritedCyclicFormImagePDF()), 0)
        XCTAssertGreaterThan(try pdfImageXObjectCount(syntheticAnnotationAppearanceImagePDF()), 0)
        XCTAssertGreaterThan(try pdfImageXObjectCount(syntheticPatternImagePDF()), 0)
    }

    func testPrivacyScannerDetectsCatalogMetadataAndEmbeddedFilesFixture() throws {
        let audit = try pdfPrivacyAudit(syntheticMetadataAndAttachmentPDF())
        XCTAssertTrue(audit.hasCatalogMetadata)
        XCTAssertTrue(audit.hasEmbeddedFiles)
        XCTAssertTrue(audit.infoKeys.contains("CreationDate"))
    }

    func testRawDocumentConstructionIsPrivateAndCrossTierInputFailsClosed() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(
            contentsOf: root.appending(path: "SumaiGuard/Services/SafetyPDFRenderer.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(source.contains("private init(\n        title: String,"))

        let crossTier = try modifiedFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            var family = try XCTUnwrap(plan["family_no_cost"] as? [[String: Any]])
            family[0]["tier"] = "CONTRACTOR_CONSTRUCTION"
            plan["family_no_cost"] = family
            object["action_plan"] = plan
        }
        XCTAssertNil(ValidatedPresentationResponse(response: crossTier))
        XCTAssertNil(RootPDFRouting.document(for: .advice(crossTier)))
    }

    func testDocumentRejectsCountFieldAggregateControlAndBidiViolations() throws {
        XCTAssertThrowsError(try sampleDocument(visibleRiskCount: 0))
        XCTAssertThrowsError(
            try sampleDocument(
                familyActionCount: 0,
                careActionCount: 0,
                contractorActionCount: 0
            )
        )
        XCTAssertThrowsError(try sampleDocument(visibleRiskCount: PresentationResponseValidator.maxFindings + 1))
        XCTAssertThrowsError(try sampleDocument(familyActionCount: PresentationResponseValidator.maxActionsPerTier + 1))
        XCTAssertThrowsError(try sampleDocument(repeatedField: String(repeating: "長", count: 4_097)))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\ttoken"))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\ntoken"))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\u{0000}token"))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\u{0085}token"))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\u{2028}token"))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\u{2029}token"))
        XCTAssertThrowsError(try sampleDocument(repeatedField: "危険\u{2067}token"))

        let large = String(repeating: "長", count: 4_000)
        XCTAssertThrowsError(
            try sampleDocument(
                visibleRiskCount: 50,
                familyActionCount: 5,
                careActionCount: 5,
                contractorActionCount: 5,
                repeatedField: large
            )
        )
    }

    func testRendererFailsClosedBeforePublishingWhenContentExceedsHardPageLimit() async throws {
        let document = try sampleDocument(
            visibleRiskCount: PresentationResponseValidator.maxFindings,
            familyActionCount: PresentationResponseValidator.maxActionsPerTier,
            careActionCount: PresentationResponseValidator.maxActionsPerTier,
            contractorActionCount: PresentationResponseValidator.maxActionsPerTier,
            repeatedField: String(repeating: "x", count: 1_200)
        )

        do {
            _ = try await SafetyPDFRenderer().render(document)
            XCTFail("Page-limit overflow must not publish a partial PDF")
        } catch {
            XCTAssertEqual(error as? SafetyPDFError, .renderingFailed)
        }
    }

    func testRendererHonorsCancellationWithoutPublishingBytes() async throws {
        let document = try longDocument()
        let renderTask = Task {
            try await SafetyPDFRenderer().render(document)
        }
        renderTask.cancel()

        do {
            _ = try await renderTask.value
            XCTFail("A cancelled render must not publish PDF bytes")
        } catch {
            XCTAssertTrue(error is CancellationError)
        }
    }

    func testFactoryRejectsInvalidAndFailClosedResponses() throws {
        let invalid = try modifiedFixture { object in
            var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
            findings[0]["label_ja"] = "危険\u{202E}token"
            object["findings"] = findings
        }
        XCTAssertNil(ValidatedPresentationResponse(response: invalid))
        XCTAssertNil(RootPDFRouting.document(for: .advice(invalid)))
        XCTAssertNil(RootPDFRouting.document(for: .result(try fixture("analysis-applicable"))))
        XCTAssertNil(RootPDFRouting.document(for: .notApplicable("対象外")))
    }

    private func recursivePropertyLabels(of value: Any) -> [String] {
        let mirror = Mirror(reflecting: value)
        return mirror.children.flatMap { child in
            (child.label.map { [$0] } ?? []) + recursivePropertyLabels(of: child.value)
        }
    }

    private func extractedText(_ data: Data) throws -> String {
        let document = try XCTUnwrap(PDFDocument(data: data))
        return (0..<document.pageCount).compactMap { document.page(at: $0)?.string }.joined(separator: "\n")
    }

    private func pdfImageXObjectCount(_ data: Data) throws -> Int {
        let audit = try pdfPrivacyAudit(data)
        return audit.imageXObjectCount + audit.inlineImageCount
    }
}

@MainActor
final class PDFSharingTests: XCTestCase {
    func testActivityItemSourceReturnsDataAndPDFTypeNeverURL() throws {
        let data = Data("%PDF-1.7 synthetic".utf8)
        let source = PDFActivityItemSource(data: data)
        let controller = UIActivityViewController(activityItems: [], applicationActivities: nil)

        XCTAssertTrue(source.activityViewControllerPlaceholderItem(controller) is Data)
        let item = source.activityViewController(controller, itemForActivityType: nil)
        XCTAssertTrue(item is Data)
        XCTAssertFalse(item is URL)
        XCTAssertEqual(item as? Data, data)
        XCTAssertEqual(
            source.activityViewController(controller, dataTypeIdentifierForActivityType: nil),
            UTType.pdf.identifier
        )
        XCTAssertEqual(source.dataForTesting, data)
    }

    func testActivityItemSourceIsImmutableNonisolatedAndCallableOffMain() async throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let sourceText = try String(
            contentsOf: root.appending(path: "SumaiGuard/Views/ShareSheet.swift"),
            encoding: .utf8
        )
        let sourceStart = try XCTUnwrap(sourceText.range(of: "final class PDFActivityItemSource"))
        let sourceEnd = try XCTUnwrap(sourceText.range(of: "@MainActor\nfinal class ShareCompletionGate"))
        let itemSourceText = String(sourceText[sourceStart.lowerBound..<sourceEnd.lowerBound])
        XCTAssertFalse(itemSourceText.contains("@preconcurrency UIActivityItemSource"))
        XCTAssertFalse(itemSourceText.contains("@MainActor"))
        XCTAssertFalse(itemSourceText.contains("private var data"))
        XCTAssertFalse(itemSourceText.contains("func clear()"))

        let expected = Data("%PDF-1.7 detached".utf8)
        let concreteSource = PDFActivityItemSource(data: expected)
        let controller = UIActivityViewController(activityItems: [], applicationActivities: nil)
        let callback = UncheckedSendableBox(
            value: (
                source: concreteSource as any UIActivityItemSource,
                controller: controller
            )
        )
        let observation: OffMainActivityObservation = await withCheckedContinuation {
            (continuation: CheckedContinuation<OffMainActivityObservation, Never>) in
            DispatchQueue.global(qos: .userInitiated).async {
                let placeholder = callback.value.source.activityViewControllerPlaceholderItem(
                    callback.value.controller
                )
                let item = callback.value.source.activityViewController(
                    callback.value.controller,
                    itemForActivityType: nil
                )
                let type = callback.value.source.activityViewController?(
                    callback.value.controller,
                    dataTypeIdentifierForActivityType: nil
                )
                continuation.resume(
                    returning: OffMainActivityObservation(
                        ranOnMainThread: Thread.isMainThread,
                        placeholderIsData: placeholder is Data,
                        itemData: item as? Data,
                        itemIsURL: item is URL,
                        typeIdentifier: type
                    )
                )
            }
        }

        XCTAssertFalse(observation.ranOnMainThread)
        XCTAssertTrue(observation.placeholderIsData)
        XCTAssertEqual(observation.itemData, expected)
        XCTAssertFalse(observation.itemIsURL)
        XCTAssertEqual(observation.typeIdentifier, UTType.pdf.identifier)
    }

    func testShareCompletionGateCallsCompletionExactlyOnceAndReleasesSourceReference() {
        var completions = 0
        weak var sourceReference: PDFActivityItemSource?
        var gate: ShareCompletionGate!
        do {
            let source = PDFActivityItemSource(data: Data("%PDF".utf8))
            sourceReference = source
            gate = ShareCompletionGate(itemSource: source) { completions += 1 }
        }
        XCTAssertNotNil(sourceReference)

        gate.finish()
        gate.finish()

        XCTAssertEqual(completions, 1)
        XCTAssertNil(sourceReference)
    }

    func testControllerShowsRealGeneratingStateCachesAndSharesData() async throws {
        let renderer = ControlledPDFRenderer()
        var cached: Data?
        var clearCount = 0
        let controller = PDFShareController(
            renderer: renderer,
            cachePDF: { cached = $0 },
            clearCachedPDF: { cached = nil; clearCount += 1 }
        )

        controller.generate(try sampleDocument())
        await renderer.waitForCallCount(1)
        XCTAssertTrue(controller.isGenerating)
        XCTAssertTrue(controller.isShareButtonDisabled)
        XCTAssertNil(controller.payload)
        XCTAssertNil(controller.errorMessage)

        let pdf = Data("%PDF-1.7 generated".utf8)
        await renderer.succeed(call: 0, data: pdf)
        await waitUntil { controller.payload != nil }
        XCTAssertFalse(controller.isGenerating)
        XCTAssertEqual(cached, pdf)
        XCTAssertEqual(controller.payload?.itemSource.dataForTesting, pdf)
        XCTAssertEqual(clearCount, 1)
    }

    func testControllerCancellationClearsPayloadCacheAndIgnoresLateResult() async throws {
        let renderer = ControlledPDFRenderer()
        var cached: Data?
        let controller = PDFShareController(
            renderer: renderer,
            cachePDF: { cached = $0 },
            clearCachedPDF: { cached = nil }
        )
        controller.generate(try sampleDocument())
        await renderer.waitForCallCount(1)

        controller.cancelGeneration()
        XCTAssertFalse(controller.isGenerating)
        XCTAssertNil(controller.payload)
        XCTAssertNil(cached)
        await renderer.succeed(call: 0, data: Data("%PDF late".utf8))
        await Task.yield()
        XCTAssertNil(controller.payload)
        XCTAssertNil(cached)
        XCTAssertNil(controller.errorMessage)
    }

    func testControllerReplacementGenerationRejectsOldLatePayload() async throws {
        let renderer = ControlledPDFRenderer()
        var cached: Data?
        let controller = PDFShareController(
            renderer: renderer,
            cachePDF: { cached = $0 },
            clearCachedPDF: { cached = nil }
        )
        controller.generate(try sampleDocument())
        await renderer.waitForCallCount(1)
        controller.generate(try sampleDocument())
        await renderer.waitForCallCount(2)

        await renderer.succeed(call: 0, data: Data("%PDF old".utf8))
        await Task.yield()
        XCTAssertNil(controller.payload)
        await renderer.succeed(call: 1, data: Data("%PDF new".utf8))
        await waitUntil { controller.payload != nil }
        XCTAssertEqual(cached, Data("%PDF new".utf8))
    }

    func testControllerUsesSafeErrorAndAllExitPathsClearMemory() async throws {
        let renderer = ControlledPDFRenderer()
        var cached: Data?
        let controller = PDFShareController(
            renderer: renderer,
            cachePDF: { cached = $0 },
            clearCachedPDF: { cached = nil }
        )
        controller.generate(try sampleDocument())
        await renderer.waitForCallCount(1)
        await renderer.fail(call: 0, error: SensitiveRendererError())
        await waitUntil { controller.errorMessage != nil }
        XCTAssertEqual(controller.errorMessage, "PDFを作成できませんでした。時間をおいてもう一度お試しください。")
        XCTAssertFalse(controller.errorMessage?.contains("provider-token") == true)
        XCTAssertNil(controller.payload)
        XCTAssertNil(cached)

        for clear: (PDFShareController) -> Void in [
            { $0.activityDidComplete() },
            { $0.shareSheetDidDismiss() },
            { $0.returnHome() },
        ] {
            let immediate = ImmediatePDFRenderer(data: Data("%PDF clear".utf8))
            let subject = PDFShareController(
                renderer: immediate,
                cachePDF: { cached = $0 },
                clearCachedPDF: { cached = nil }
            )
            subject.generate(try sampleDocument())
            await waitUntil { subject.payload != nil }
            XCTAssertNotNil(cached)
            clear(subject)
            XCTAssertNil(subject.payload)
            XCTAssertNil(cached)
            XCTAssertFalse(subject.isGenerating)
        }
    }

    func testRootRoutesShareOnlyForValidatedAdviceAndAdviceRendersSyntheticProgressAndError() throws {
        let response = try fixture("analysis-applicable")
        XCTAssertNotNil(RootPDFRouting.document(for: .advice(response)))
        XCTAssertNil(RootPDFRouting.document(for: .result(response)))

        let invalid = try modifiedFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            var actions = try XCTUnwrap(plan["family_no_cost"] as? [[String: Any]])
            actions[0]["description_ja"] = "unsafe\u{2066}marker"
            plan["family_no_cost"] = actions
            object["action_plan"] = plan
        }
        XCTAssertNil(RootPDFRouting.document(for: .advice(invalid)))

        let progressView = AdviceView(
            response: response,
            actions: .init(returnHome: {}, shareAdvice: {}, cancelPDF: {}),
            pdfState: .generating
        )
        let progressRenderer = ImageRenderer(content: progressView.frame(width: 390, height: 844))
        progressRenderer.scale = 1
        XCTAssertNotNil(progressRenderer.uiImage)
        XCTAssertTrue(PDFShareViewState.generating.visibleText.contains("作成しています"))
        XCTAssertTrue(PDFShareViewState.generating.isShareButtonDisabled)

        let error = PDFShareViewState.failed("固定エラー")
        XCTAssertEqual(error.visibleText, "固定エラー")
        XCTAssertFalse(error.isShareButtonDisabled)
    }

    func testPDFSourcesContainNoFilesystemPersistencePhotoLibraryCacheOrLogging() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let paths = [
            root.appending(path: "SumaiGuard/Services/SafetyPDFRenderer.swift"),
            root.appending(path: "SumaiGuard/Views/ShareSheet.swift"),
        ]
        let source = try paths.map { try String(contentsOf: $0, encoding: .utf8) }.joined(separator: "\n")
        for forbidden in [
            "FileManager", "temporaryDirectory", "write(to:", "UserDefaults", "URLCache", "NSCache",
            "UIImageWriteToSavedPhotosAlbum", "Logger(", "os_log", "print(", "AnalysisResponse",
        ] {
            XCTAssertFalse(source.contains(forbidden), forbidden)
        }
    }
}

private struct UncheckedSendableBox<Value>: @unchecked Sendable {
    let value: Value
}

private struct OffMainActivityObservation: Sendable {
    let ranOnMainThread: Bool
    let placeholderIsData: Bool
    let itemData: Data?
    let itemIsURL: Bool
    let typeIdentifier: String?
}

private struct PDFPrivacyAudit {
    let imageXObjectCount: Int
    let inlineImageCount: Int
    let hasCatalogMetadata: Bool
    let hasEmbeddedFiles: Bool
    let infoKeys: Set<String>
}

private final class PDFPrivacyAuditContext {
    var imageXObjectCount = 0
    var inlineImageCount = 0
    var hasCatalogMetadata = false
    var hasEmbeddedFiles = false
    var infoKeys = Set<String>()
    var visitedStreams = Set<String>()
    var visitedResourceDictionaries = Set<String>()
    var visitedAppearanceDictionaries = Set<String>()
}

private final class PDFDictionaryVisitorContext {
    let visit: (String, CGPDFObjectRef) -> Void

    init(visit: @escaping (String, CGPDFObjectRef) -> Void) {
        self.visit = visit
    }
}

private func pdfPrivacyAudit(_ data: Data) throws -> PDFPrivacyAudit {
    let provider = try XCTUnwrap(CGDataProvider(data: data as CFData))
    let document = try XCTUnwrap(CGPDFDocument(provider))
    let context = PDFPrivacyAuditContext()

    if let info = document.info {
        applyPDFDictionary(info) { key, _ in
            context.infoKeys.insert(key)
        }
    }
    if let catalog = document.catalog {
        var metadata: CGPDFObjectRef?
        context.hasCatalogMetadata = CGPDFDictionaryGetObject(catalog, "Metadata", &metadata)

        var names: CGPDFDictionaryRef?
        if CGPDFDictionaryGetDictionary(catalog, "Names", &names), let names {
            var embeddedFiles: CGPDFObjectRef?
            context.hasEmbeddedFiles = CGPDFDictionaryGetObject(names, "EmbeddedFiles", &embeddedFiles)
        }
        var associatedFiles: CGPDFObjectRef?
        if CGPDFDictionaryGetObject(catalog, "AF", &associatedFiles) {
            context.hasEmbeddedFiles = true
        }
    }

    if document.numberOfPages > 0 {
        for pageNumber in 1...document.numberOfPages {
            guard let page = document.page(at: pageNumber) else { continue }
            let pageContentStream = CGPDFContentStreamCreateWithPage(page)
            scanPDFContentStream(pageContentStream, context: context)
            if let pageDictionary = page.dictionary {
                if let resources = inheritedPDFResources(from: pageDictionary) {
                    scanPDFResources(resources, parent: pageContentStream, context: context)
                }
                scanPDFAnnotations(pageDictionary, parent: pageContentStream, context: context)
            }
            CGPDFContentStreamRelease(pageContentStream)
        }
    }

    return PDFPrivacyAudit(
        imageXObjectCount: context.imageXObjectCount,
        inlineImageCount: context.inlineImageCount,
        hasCatalogMetadata: context.hasCatalogMetadata,
        hasEmbeddedFiles: context.hasEmbeddedFiles,
        infoKeys: context.infoKeys
    )
}

private func applyPDFDictionary(
    _ dictionary: CGPDFDictionaryRef,
    visit: @escaping (String, CGPDFObjectRef) -> Void
) {
    let context = PDFDictionaryVisitorContext(visit: visit)
    let pointer = Unmanaged.passRetained(context).toOpaque()
    CGPDFDictionaryApplyFunction(dictionary, { key, object, rawContext in
        guard let rawContext else { return }
        let context = Unmanaged<PDFDictionaryVisitorContext>.fromOpaque(rawContext).takeUnretainedValue()
        context.visit(String(cString: key), object)
    }, pointer)
    Unmanaged<PDFDictionaryVisitorContext>.fromOpaque(pointer).release()
}

private func inheritedPDFResources(from pageDictionary: CGPDFDictionaryRef) -> CGPDFDictionaryRef? {
    var current: CGPDFDictionaryRef? = pageDictionary
    var visited = Set<String>()
    while let dictionary = current {
        let identity = String(describing: dictionary)
        guard visited.insert(identity).inserted else { return nil }
        var resources: CGPDFDictionaryRef?
        if CGPDFDictionaryGetDictionary(dictionary, "Resources", &resources), let resources {
            return resources
        }
        var parent: CGPDFDictionaryRef?
        guard CGPDFDictionaryGetDictionary(dictionary, "Parent", &parent) else { return nil }
        current = parent
    }
    return nil
}

private func scanPDFResources(
    _ resources: CGPDFDictionaryRef,
    parent: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    let identity = String(describing: resources)
    guard context.visitedResourceDictionaries.insert(identity).inserted else { return }

    var xObjects: CGPDFDictionaryRef?
    if CGPDFDictionaryGetDictionary(resources, "XObject", &xObjects), let xObjects {
        applyPDFDictionary(xObjects) { _, object in
            scanPDFStreamObject(object, parent: parent, context: context)
        }
    }

    var patterns: CGPDFDictionaryRef?
    if CGPDFDictionaryGetDictionary(resources, "Pattern", &patterns), let patterns {
        applyPDFDictionary(patterns) { _, object in
            var stream: CGPDFStreamRef?
            if CGPDFObjectGetValue(object, .stream, &stream), let stream {
                scanPDFStream(stream, parent: parent, context: context)
                return
            }
            var dictionary: CGPDFDictionaryRef?
            if CGPDFObjectGetValue(object, .dictionary, &dictionary), let dictionary {
                scanNestedPDFResources(dictionary, parent: parent, context: context)
            }
        }
    }
}

private func scanPDFStreamObject(
    _ object: CGPDFObjectRef,
    parent: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    var stream: CGPDFStreamRef?
    guard CGPDFObjectGetValue(object, .stream, &stream), let stream else { return }
    scanPDFStream(stream, parent: parent, context: context)
}

private func scanPDFStream(
    _ stream: CGPDFStreamRef,
    parent: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    let identity = String(describing: stream)
    guard context.visitedStreams.insert(identity).inserted else { return }
    guard let dictionary = CGPDFStreamGetDictionary(stream) else { return }

    var subtype: UnsafePointer<CChar>?
    if CGPDFDictionaryGetName(dictionary, "Subtype", &subtype),
       subtype.map({ String(cString: $0) }) == "Image" {
        context.imageXObjectCount += 1
        return
    }

    var resources: CGPDFDictionaryRef?
    let hasResources = CGPDFDictionaryGetDictionary(dictionary, "Resources", &resources)
    let contentResources = hasResources ? resources : dictionary
    if let contentResources {
        let contentStream = CGPDFContentStreamCreateWithStream(stream, contentResources, parent)
        scanPDFContentStream(contentStream, context: context)
        if let resources {
            scanPDFResources(resources, parent: contentStream, context: context)
        }
        CGPDFContentStreamRelease(contentStream)
    }
}

private func scanNestedPDFResources(
    _ dictionary: CGPDFDictionaryRef,
    parent: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    var resources: CGPDFDictionaryRef?
    if CGPDFDictionaryGetDictionary(dictionary, "Resources", &resources), let resources {
        scanPDFResources(resources, parent: parent, context: context)
    }
}

private func scanPDFContentStream(
    _ contentStream: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    guard let streams = CGPDFContentStreamGetStreams(contentStream) else { return }
    for index in 0..<CFArrayGetCount(streams) {
        guard let rawStream = CFArrayGetValueAtIndex(streams, index) else { continue }
        let stream = unsafeBitCast(rawStream, to: CGPDFStreamRef.self)
        var format = CGPDFDataFormat.raw
        guard let bytes = CGPDFStreamCopyData(stream, &format) as Data? else { continue }
        context.inlineImageCount += inlinePDFImageOperatorCount(bytes)
    }
}

private func inlinePDFImageOperatorCount(_ data: Data) -> Int {
    let bytes = Array(data)
    var index = 0
    var count = 0
    var inlineState = 0
    while index < bytes.count {
        skipPDFWhitespaceAndComments(bytes, index: &index)
        guard index < bytes.count else { break }
        if bytes[index] == 0x28 {
            skipPDFLiteralString(bytes, index: &index)
            continue
        }
        if bytes[index] == 0x3C, index + 1 < bytes.count, bytes[index + 1] != 0x3C {
            index += 1
            while index < bytes.count, bytes[index] != 0x3E { index += 1 }
            index = min(index + 1, bytes.count)
            continue
        }
        let start = index
        if bytes[index] == 0x2F { index += 1 }
        while index < bytes.count, !isPDFDelimiterOrWhitespace(bytes[index]) { index += 1 }
        if start < index {
            switch String(decoding: bytes[start..<index], as: UTF8.self) {
            case "BI":
                inlineState = 1
            case "ID" where inlineState == 1:
                inlineState = 2
            case "EI" where inlineState == 2:
                count += 1
                inlineState = 0
            default:
                break
            }
        }
        if start == index { index += 1 }
    }
    return count
}

private func skipPDFWhitespaceAndComments(_ bytes: [UInt8], index: inout Int) {
    while index < bytes.count {
        if isPDFWhitespace(bytes[index]) {
            index += 1
            continue
        }
        if bytes[index] == 0x25 {
            while index < bytes.count, bytes[index] != 0x0A, bytes[index] != 0x0D { index += 1 }
            continue
        }
        return
    }
}

private func skipPDFLiteralString(_ bytes: [UInt8], index: inout Int) {
    var depth = 0
    while index < bytes.count {
        let byte = bytes[index]
        index += 1
        if byte == 0x5C {
            index = min(index + 1, bytes.count)
        } else if byte == 0x28 {
            depth += 1
        } else if byte == 0x29 {
            depth -= 1
            if depth == 0 { return }
        }
    }
}

private func isPDFDelimiterOrWhitespace(_ byte: UInt8) -> Bool {
    isPDFWhitespace(byte) || [0x28, 0x29, 0x3C, 0x3E, 0x5B, 0x5D, 0x7B, 0x7D, 0x2F, 0x25].contains(byte)
}

private func isPDFWhitespace(_ byte: UInt8) -> Bool {
    byte == 0 || byte == 0x09 || byte == 0x0A || byte == 0x0C || byte == 0x0D || byte == 0x20
}

private func scanPDFAnnotations(
    _ pageDictionary: CGPDFDictionaryRef,
    parent: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    var annotations: CGPDFArrayRef?
    guard CGPDFDictionaryGetArray(pageDictionary, "Annots", &annotations), let annotations else { return }
    for index in 0..<CGPDFArrayGetCount(annotations) {
        var annotation: CGPDFDictionaryRef?
        guard CGPDFArrayGetDictionary(annotations, index, &annotation), let annotation else { continue }
        var appearance: CGPDFObjectRef?
        if CGPDFDictionaryGetObject(annotation, "AP", &appearance), let appearance {
            scanPDFAppearanceObject(appearance, parent: parent, context: context)
        }
    }
}

private func scanPDFAppearanceObject(
    _ object: CGPDFObjectRef,
    parent: CGPDFContentStreamRef,
    context: PDFPrivacyAuditContext
) {
    var stream: CGPDFStreamRef?
    if CGPDFObjectGetValue(object, .stream, &stream), let stream {
        scanPDFStream(stream, parent: parent, context: context)
        return
    }
    var dictionary: CGPDFDictionaryRef?
    guard CGPDFObjectGetValue(object, .dictionary, &dictionary), let dictionary else { return }
    let identity = String(describing: dictionary)
    guard context.visitedAppearanceDictionaries.insert(identity).inserted else { return }
    applyPDFDictionary(dictionary) { _, nestedObject in
        scanPDFAppearanceObject(nestedObject, parent: parent, context: context)
    }
}

private func syntheticInlineImagePDF() -> Data {
    syntheticPDF(objects: [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R >>",
        pdfStream("q BI /W 1 /H 1 /CS /RGB /BPC 8 ID abc EI Q"),
    ])
}

private func syntheticInheritedCyclicFormImagePDF() -> Data {
    syntheticPDF(objects: [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 /Resources << /XObject << /FmA 4 0 R >> >> >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 7 0 R >>",
        pdfStream("/FmB Do", dictionary: "/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Resources << /XObject << /FmB 5 0 R >> >>"),
        pdfStream("/Im Do /FmA Do", dictionary: "/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Resources << /XObject << /FmA 4 0 R /Im 6 0 R >> >>"),
        pdfStream("abc", dictionary: "/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8"),
        pdfStream("/FmA Do"),
    ])
}

private func syntheticAnnotationAppearanceImagePDF() -> Data {
    syntheticPDF(objects: [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R /Annots [5 0 R] >>",
        pdfStream("q Q"),
        "<< /Type /Annot /Subtype /Widget /Rect [0 0 10 10] /AP << /N 6 0 R >> >>",
        pdfStream("/Im Do", dictionary: "/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Resources << /XObject << /Im 7 0 R >> >>"),
        pdfStream("abc", dictionary: "/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8"),
    ])
}

private func syntheticPatternImagePDF() -> Data {
    syntheticPDF(objects: [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << /Pattern << /P 5 0 R >> >> /Contents 4 0 R >>",
        pdfStream("/Pattern cs /P scn 0 0 10 10 re f"),
        pdfStream("/Im Do", dictionary: "/Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 10 10] /XStep 10 /YStep 10 /Resources << /XObject << /Im 6 0 R >> >>"),
        pdfStream("abc", dictionary: "/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8"),
    ])
}

private func syntheticMetadataAndAttachmentPDF() -> Data {
    syntheticPDF(
        objects: [
            "<< /Type /Catalog /Pages 2 0 R /Metadata 5 0 R /Names << /EmbeddedFiles << /Names [(secret.txt) 6 0 R] >> >> >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R >>",
            pdfStream("q Q"),
            pdfStream("<x:xmpmeta>PRIVATE_XMP</x:xmpmeta>", dictionary: "/Type /Metadata /Subtype /XML"),
            "<< /Type /Filespec /F (secret.txt) /EF << /F 7 0 R >> >>",
            pdfStream("fictional attachment", dictionary: "/Type /EmbeddedFile"),
            "<< /Title (Fixture) /CreationDate (D:20260809000000Z) >>",
        ],
        infoObject: 8
    )
}

private func pdfStream(_ content: String, dictionary: String = "") -> String {
    let length = content.utf8.count
    return "<< /Length \(length) \(dictionary) >>\nstream\n\(content)\nendstream"
}

private func syntheticPDF(objects: [String], rootObject: Int = 1, infoObject: Int? = nil) -> Data {
    var result = Data("%PDF-1.4\n".utf8)
    var offsets = [0]
    for (index, object) in objects.enumerated() {
        offsets.append(result.count)
        result.append(Data("\(index + 1) 0 obj\n\(object)\nendobj\n".utf8))
    }
    let xrefOffset = result.count
    result.append(Data("xref\n0 \(objects.count + 1)\n0000000000 65535 f \n".utf8))
    for offset in offsets.dropFirst() {
        result.append(Data(String(format: "%010d 00000 n \n", offset).utf8))
    }
    let info = infoObject.map { " /Info \($0) 0 R" } ?? ""
    result.append(
        Data(
            "trailer\n<< /Size \(objects.count + 1) /Root \(rootObject) 0 R\(info) >>\nstartxref\n\(xrefOffset)\n%%EOF\n".utf8
        )
    )
    return result
}

private struct SensitiveRendererError: Error, CustomStringConvertible {
    var description: String { "provider-token internal failure" }
}

private actor ControlledPDFRenderer: SafetyPDFRendering {
    private struct Call {
        let continuation: CheckedContinuation<Data, any Error>
    }

    private var calls: [Call] = []

    func render(_ document: SafetyPDFDocument) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            calls.append(Call(continuation: continuation))
        }
    }

    func waitForCallCount(_ expected: Int) async {
        while calls.count < expected { await Task.yield() }
    }

    func succeed(call index: Int, data: Data) {
        calls[index].continuation.resume(returning: data)
    }

    func fail(call index: Int, error: any Error) {
        calls[index].continuation.resume(throwing: error)
    }
}

private struct ImmediatePDFRenderer: SafetyPDFRendering {
    let data: Data

    func render(_ document: SafetyPDFDocument) async throws -> Data {
        data
    }
}

private extension XCTestCase {
    func fixture(_ name: String) throws -> AnalysisResponse {
        let url = try XCTUnwrap(Bundle(for: SafetyPDFRendererTests.self).url(forResource: name, withExtension: "json"))
        return try JSONDecoder.sumai.decode(AnalysisResponse.self, from: Data(contentsOf: url))
    }

    func modifiedFixture(_ update: (inout [String: Any]) throws -> Void) throws -> AnalysisResponse {
        let url = try XCTUnwrap(Bundle(for: SafetyPDFRendererTests.self).url(forResource: "analysis-applicable", withExtension: "json"))
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        try update(&object)
        return try JSONDecoder.sumai.decode(
            AnalysisResponse.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
    }

    @MainActor
    func waitUntil(
        timeoutNanoseconds: UInt64 = 2_000_000_000,
        condition: @escaping @MainActor () -> Bool
    ) async {
        let deadline = ContinuousClock.now + .nanoseconds(Int64(timeoutNanoseconds))
        while !condition(), ContinuousClock.now < deadline {
            await Task.yield()
        }
        XCTAssertTrue(condition())
    }

    func sampleDocument(
        visibleRiskCount: Int = 1,
        familyActionCount: Int = 1,
        careActionCount: Int = 1,
        contractorActionCount: Int = 1,
        repeatedField: String? = nil,
        familyTitles: [String]? = nil,
        contractorTitles: [String]? = nil
    ) throws -> SafetyPDFDocument {
        let field = repeatedField ?? "玄関の通路に物が見えます"
        return try syntheticDocument(
            visibleRiskCount: visibleRiskCount,
            familyTitles: familyTitles ?? (0..<familyActionCount).map { "通路を片づける\($0 + 1)" },
            careTitles: (0..<careActionCount).map { "福祉用具を相談する\($0 + 1)" },
            contractorTitles: contractorTitles ?? (0..<contractorActionCount).map { "現地確認を依頼する\($0 + 1)" },
            riskField: field,
            familyField: field,
            careField: field,
            contractorField: field
        )
    }

    func longDocument() throws -> SafetyPDFDocument {
        var contractorTitles = (0..<5).map { "専門確認項目\($0 + 1)" }
        contractorTitles[contractorTitles.count - 1] = "最終項目：現地で床の状態を確認する"
        return try syntheticDocument(
            visibleRiskCount: 1,
            familyTitles: (0..<5).map { "家族の対応\($0 + 1)" },
            careTitles: (0..<5).map { "相談項目\($0 + 1)" },
            contractorTitles: contractorTitles,
            riskField: "玄関の通路に物が見えます。"
                + String(repeating: "写真で見える範囲だけを確認します。", count: 40),
            familyField: String(repeating: "無理のない範囲で物を移動します。", count: 25),
            careField: String(repeating: "福祉用具専門職へ現地の状態を相談します。", count: 25),
            contractorField: String(repeating: "床面の状態を現地で慎重に確認します。", count: 30)
        )
    }

    func syntheticDocument(
        visibleRiskCount: Int,
        familyTitles: [String],
        careTitles: [String],
        contractorTitles: [String],
        riskField: String,
        familyField: String,
        careField: String,
        contractorField: String
    ) throws -> SafetyPDFDocument {
        let response = try modifiedFixture { object in
            let findingTemplate = try XCTUnwrap((object["findings"] as? [[String: Any]])?.first)
            object["findings"] = (0..<visibleRiskCount).map { index -> [String: Any] in
                var finding = findingTemplate
                finding["id"] = "synthetic-risk-\(index + 1)"
                finding["label_ja"] = "注意候補\(index + 1)：\(riskField)"
                finding["description_ja"] = "合成データ上の注意候補です。"
                finding["evidence_ja"] = "写真上の根拠：\(riskField)"
                finding["basis_label_ja"] = "固定しない外部ラベル"
                finding["basis_summary_ja"] = riskField
                return finding
            }

            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            let familyTemplate = try XCTUnwrap((plan["family_no_cost"] as? [[String: Any]])?.first)
            let careTemplate = try XCTUnwrap((plan["care_manager_purchase"] as? [[String: Any]])?.first)
            let contractorTemplate = try XCTUnwrap((plan["contractor_construction"] as? [[String: Any]])?.first)
            let riskID = "synthetic-risk-1"

            func actions(
                titles: [String],
                field: String,
                template: [String: Any],
                prefix: String
            ) -> [[String: Any]] {
                titles.enumerated().map { index, title in
                    var action = template
                    action["id"] = "synthetic-\(prefix)-\(index + 1)"
                    action["risk_id"] = riskID
                    action["title_ja"] = title
                    action["description_ja"] = field
                    action["why_ja"] = "理由：\(field)"
                    action["disclaimer_ja"] = "無理に作業せず、必要に応じて相談してください。"
                    return action
                }
            }

            plan["family_no_cost"] = actions(
                titles: familyTitles,
                field: familyField,
                template: familyTemplate,
                prefix: "family"
            )
            plan["care_manager_purchase"] = actions(
                titles: careTitles,
                field: careField,
                template: careTemplate,
                prefix: "care"
            )
            plan["contractor_construction"] = actions(
                titles: contractorTitles,
                field: contractorField,
                template: contractorTemplate,
                prefix: "contractor"
            )
            object["action_plan"] = plan
        }
        guard let validated = ValidatedPresentationResponse(response: response) else {
            throw SafetyPDFError.invalidDocument
        }
        return try SafetyPDFDocument(validatedResponse: validated)
    }
}
