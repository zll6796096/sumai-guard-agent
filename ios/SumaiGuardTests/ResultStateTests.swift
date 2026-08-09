import CoreGraphics
import Foundation
import ImageIO
import SwiftUI
@testable import SumaiGuard
import UniformTypeIdentifiers
import XCTest
import zlib

@MainActor
final class ResultStateTests: XCTestCase {
    func testProcessingContentIsIndeterminateAndCancelCallsOnlyItsAction() {
        let content = ResultStateContent.production
        var cancelCount = 0
        let actions = ProcessingActions(cancelProcessing: { cancelCount += 1 })

        XCTAssertEqual(content.processingHeading, "写真で見える注意候補を確認しています")
        XCTAssertEqual(content.processingCancelLabel, "確認を中止する")
        XCTAssertTrue(content.processingUsesIndeterminateProgress)
        XCTAssertFalse(content.processingVisibleText.contains("%"))
        XCTAssertFalse(content.processingVisibleText.contains("ステップ"))
        XCTAssertEqual(content.processingPrivacyNote, "処理中も、SumaiGuard アプリは写真を保存しません。")

        actions.cancelProcessing()
        XCTAssertEqual(cancelCount, 1)
    }

    func testProcessingPresentationAndViewUseTheSelectedInMemoryPreview() throws {
        let preview = try syntheticCGImage(width: 3, height: 5)
        let selection = SelectedImage(preview: preview)
        let presentation = ProcessingPresentation(selection: selection)

        XCTAssertTrue(presentation.preview === preview)
        XCTAssertEqual(presentation.preview.width, 3)
        XCTAssertEqual(presentation.preview.height, 5)
        XCTAssertEqual(presentation.previewAccessibilityLabel, "確認中の住まいの写真")

        let renderer = ImageRenderer(
            content: ProcessingView(
                selection: selection,
                actions: .init(cancelProcessing: {})
            )
            .frame(width: 390, height: 844)
        )
        renderer.scale = 1
        XCTAssertNotNil(renderer.uiImage)
    }

    func testResultPresentationPreservesImageAndFindingOrderWithCautiousScores() throws {
        let response = try fixture("analysis-applicable")
        let presentation = try XCTUnwrap(ResultPresentation(response: response))

        XCTAssertEqual(presentation.heading, "写真で確認できた注意箇所")
        XCTAssertEqual(presentation.images.map(\.role), [.evidence, .improvement])
        XCTAssertEqual(presentation.images.map(\.heading), ["確認できた箇所", "改善イメージ"])
        XCTAssertEqual(
            presentation.images.map(\.base64),
            [response.annotatedImageBase64, response.improvementImageBase64]
        )
        XCTAssertEqual(presentation.findings.map(\.id), response.findings.map(\.id))
        XCTAssertEqual(presentation.findings.map(\.label), response.findings.map(\.labelJA))
        XCTAssertEqual(presentation.findings.map(\.description), response.findings.map(\.descriptionJA))
        XCTAssertEqual(presentation.findings.map(\.evidence), response.findings.map(\.evidenceJA))
        XCTAssertEqual(presentation.findings.map(\.basisLabel), response.findings.map(\.basisLabelJA))
        XCTAssertEqual(presentation.findings.map(\.basisSummary), response.findings.map(\.basisSummaryJA))
        XCTAssertTrue(presentation.findings.allSatisfy(\.needsHumanConfirmation))
        XCTAssertTrue(presentation.findings.allSatisfy { $0.confidenceLabel.contains("未校正のモデル参考スコア") })
        XCTAssertTrue(presentation.findings.allSatisfy { $0.confidenceExplanation == "危害発生確率ではありません" })
        XCTAssertEqual(presentation.showAdviceLabel, "安全のためにできること")
        XCTAssertFalse(presentation.visibleText.contains("accuracy"))
        XCTAssertFalse(presentation.visibleText.contains("正解率"))
        XCTAssertFalse(presentation.visibleText.contains("リスク確率"))
    }

    func testResultLimitationsAreConsolidatedAndExcludeDebugMetadata() throws {
        let response = try fixture("analysis-applicable")
        let presentation = try XCTUnwrap(ResultPresentation(response: response))

        XCTAssertEqual(presentation.limitationsHeading, "この結果の限界")
        XCTAssertEqual(presentation.limitationsRegionCount, 1)
        XCTAssertTrue(presentation.limitations.contains { $0.contains("写真で見える範囲") })
        XCTAssertTrue(presentation.limitations.contains { $0.contains("見落としや誤検出") })
        XCTAssertTrue(presentation.limitations.contains { $0.contains("人や専門職による現地確認") })
        XCTAssertEqual(
            presentation.limitations,
            [
                "写真で見える範囲に限った結果です。",
                "見落としや誤検出があり得ます。",
                "人や専門職による現地確認が必要です。",
                "医療・介護認定・保険・法令適合・施工可否・見積もりの判断に代わるものではありません。",
            ]
        )

        for hidden in [
            response.analysisID,
            response.model,
            response.resultKey,
            response.semanticHash,
            response.schemaVersion,
            response.ontologyVersion,
            response.preprocessVersion,
            response.inferenceConfigVersion,
            "stage_timings_ms",
        ] {
            XCTAssertFalse(presentation.visibleText.contains(hidden))
        }
    }

    func testResultFailsClosedForNotApplicableEmptyFindingsOrEmptyActions() throws {
        XCTAssertNil(ResultPresentation(response: try fixture("analysis-not-applicable")))
        XCTAssertNil(ResultPresentation(response: try modifiedApplicableFixture { $0["findings"] = [] }))
        XCTAssertNil(ResultPresentation(response: try modifiedApplicableFixture { object in
            object["action_plan"] = [
                "family_no_cost": [],
                "care_manager_purchase": [],
                "contractor_construction": [],
            ]
        }))
    }

    func testAdviceRendersExactlyThreeServerOrderedTiersWithoutChangingItems() throws {
        let response = try fixture("analysis-applicable")
        let presentation = AdvicePresentation(response: response)

        XCTAssertEqual(
            presentation.sections.map(\.heading),
            ["家族で今日できること", "ケアマネ・福祉用具に相談", "専門施工・現地確認"]
        )
        XCTAssertEqual(presentation.sections.count, 3)
        XCTAssertEqual(
            presentation.sections[0].items.map(\.title),
            response.actionPlan.familyNoCost.map(\.titleJA)
        )
        XCTAssertEqual(
            presentation.sections[1].items.map(\.title),
            response.actionPlan.careManagerPurchase.map(\.titleJA)
        )
        XCTAssertEqual(
            presentation.sections[2].items.map(\.title),
            response.actionPlan.contractorConstruction.map(\.titleJA)
        )
        XCTAssertEqual(presentation.sections[0].items.map(\.description), response.actionPlan.familyNoCost.map(\.descriptionJA))
        XCTAssertEqual(presentation.sections[1].items.map(\.why), response.actionPlan.careManagerPurchase.map(\.whyJA))
        XCTAssertEqual(presentation.sections[2].items.map(\.disclaimer), response.actionPlan.contractorConstruction.map(\.disclaimerJA))
        XCTAssertFalse(presentation.visibleText.contains("新しく購入"))
    }

    func testAdviceEmptyTierStatesDoNotInventActions() throws {
        let response = try modifiedApplicableFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            plan["care_manager_purchase"] = []
            object["action_plan"] = plan
        }
        let presentation = AdvicePresentation(response: response)

        XCTAssertEqual(presentation.sections.count, 3)
        XCTAssertTrue(presentation.sections[1].items.isEmpty)
        XCTAssertEqual(presentation.sections[1].emptyMessage, "該当する提案はありません")
    }

    func testAdviceFailsClosedWhenAnyServerArrayContainsTheWrongTier() throws {
        let mismatches = [
            ("family_no_cost", "CARE_MANAGER_PURCHASE"),
            ("care_manager_purchase", "CONTRACTOR_CONSTRUCTION"),
            ("contractor_construction", "FAMILY_NO_COST"),
        ]

        for (arrayKey, wrongTier) in mismatches {
            let response = try modifiedApplicableFixture { object in
                var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
                var items = try XCTUnwrap(plan[arrayKey] as? [[String: Any]])
                items[0]["tier"] = wrongTier
                plan[arrayKey] = items
                object["action_plan"] = plan
            }
            let presentation = AdvicePresentation(response: response)

            XCTAssertTrue(
                presentation.sections.flatMap(\.items).isEmpty,
                "A mismatch in \(arrayKey) must hide every action instead of crossing tiers"
            )
            XCTAssertTrue(presentation.visibleText.contains("提案を安全に表示できません"))
        }
    }

    func testPresentationsFailClosedForExcessiveCountsAndUnsafeIdentifiers() throws {
        let tooManyFindings = try modifiedApplicableFixture { object in
            let original = try XCTUnwrap((object["findings"] as? [[String: Any]])?.first)
            object["findings"] = (0...50).map { index in
                var finding = original
                finding["id"] = index == 0 ? "risk-fixture-001" : "risk-extra-\(index)"
                return finding
            }
        }
        assertPresentationsFailClosed(tooManyFindings)

        let tooManyActions = try modifiedApplicableFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            let original = try XCTUnwrap((plan["family_no_cost"] as? [[String: Any]])?.first)
            plan["family_no_cost"] = (0..<6).map { index in
                var action = original
                action["id"] = "family-extra-\(index)"
                return action
            }
            object["action_plan"] = plan
        }
        assertPresentationsFailClosed(tooManyActions)

        let duplicateFindingID = try modifiedApplicableFixture { object in
            var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
            findings[1]["id"] = findings[0]["id"]
            object["findings"] = findings
        }
        assertPresentationsFailClosed(duplicateFindingID)

        let unsafeFindingID = try modifiedApplicableFixture { object in
            var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
            findings[0]["id"] = String(repeating: "i", count: 129)
            object["findings"] = findings
        }
        assertPresentationsFailClosed(unsafeFindingID)

        let emptyFindingID = try modifiedApplicableFixture { object in
            var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
            findings[0]["id"] = ""
            object["findings"] = findings
        }
        assertPresentationsFailClosed(emptyFindingID)

        let duplicateActionID = try modifiedApplicableFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            let family = try XCTUnwrap(plan["family_no_cost"] as? [[String: Any]])
            var care = try XCTUnwrap(plan["care_manager_purchase"] as? [[String: Any]])
            care[0]["id"] = family[0]["id"]
            plan["care_manager_purchase"] = care
            object["action_plan"] = plan
        }
        assertPresentationsFailClosed(duplicateActionID)

        let emptyActionID = try modifiedApplicableFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            var family = try XCTUnwrap(plan["family_no_cost"] as? [[String: Any]])
            family[0]["id"] = ""
            plan["family_no_cost"] = family
            object["action_plan"] = plan
        }
        assertPresentationsFailClosed(emptyActionID)

        let orphanAction = try modifiedApplicableFixture { object in
            var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
            var family = try XCTUnwrap(plan["family_no_cost"] as? [[String: Any]])
            family[0]["risk_id"] = "risk-does-not-exist"
            plan["family_no_cost"] = family
            object["action_plan"] = plan
        }
        assertPresentationsFailClosed(orphanAction)
    }

    func testPresentationsFailClosedForTierCostAndProfessionalMismatches() throws {
        let mismatches: [(String, String, Any)] = [
            ("family_no_cost", "cost_level", "LOW"),
            ("family_no_cost", "requires_professional", true),
            ("care_manager_purchase", "cost_level", "ZERO"),
            ("care_manager_purchase", "requires_professional", false),
            ("contractor_construction", "cost_level", "MEDIUM"),
            ("contractor_construction", "requires_professional", false),
        ]

        for (arrayKey, field, value) in mismatches {
            let response = try modifiedApplicableFixture { object in
                var plan = try XCTUnwrap(object["action_plan"] as? [String: Any])
                var items = try XCTUnwrap(plan[arrayKey] as? [[String: Any]])
                items[0][field] = value
                plan[arrayKey] = items
                object["action_plan"] = plan
            }
            assertPresentationsFailClosed(response)
        }
    }

    func testPresentationsFailClosedForOversizedControlBidiAndAggregateText() throws {
        let oversizedField = try modifiedApplicableFixture { object in
            var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
            findings[0]["description_ja"] = String(repeating: "a", count: 4_097)
            object["findings"] = findings
        }
        assertPresentationsFailClosed(oversizedField)

        for unsafeText in [
            "visible\u{0000}raw-token",
            "visible\u{061C}raw-token",
            "visible\u{200E}raw-token",
            "visible\u{200F}raw-token",
            "visible\u{202E}raw-token",
            "visible\u{2067}raw-token",
        ] {
            let response = try modifiedApplicableFixture { object in
                var findings = try XCTUnwrap(object["findings"] as? [[String: Any]])
                findings[0]["label_ja"] = unsafeText
                object["findings"] = findings
            }
            assertPresentationsFailClosed(response, hiddenMarker: unsafeText)
        }

        let aggregateOverflow = try modifiedApplicableFixture { object in
            let original = try XCTUnwrap((object["findings"] as? [[String: Any]])?.first)
            let longButIndividuallyValid = String(repeating: "z", count: 1_100)
            object["findings"] = (0..<50).map { index in
                var finding = original
                finding["id"] = index == 0 ? "risk-fixture-001" : "risk-budget-\(index)"
                finding["label_ja"] = longButIndividuallyValid
                finding["description_ja"] = longButIndividuallyValid
                finding["evidence_ja"] = longButIndividuallyValid
                finding["basis_label_ja"] = longButIndividuallyValid
                finding["basis_summary_ja"] = longButIndividuallyValid
                return finding
            }
        }
        assertPresentationsFailClosed(aggregateOverflow)
    }

    func testServerDisclaimerCannotEnterTheFixedLimitationsPresentation() throws {
        let injected = "MODEL=raw-provider-token https://debug.invalid 重複"
        let response = try modifiedApplicableFixture { object in
            object["disclaimer_ja"] = injected
        }
        let presentation = try XCTUnwrap(ResultPresentation(response: response))

        XCTAssertEqual(presentation.limitations.count, 4)
        XCTAssertFalse(presentation.visibleText.contains(injected))
        XCTAssertFalse(presentation.visibleText.contains("debug.invalid"))
    }

    func testNoFindingsAndNotApplicableContentStayNarrow() throws {
        let content = ResultStateContent.production
        let noFindings = NoFindingsPresentation(content: content)
        let notApplicable = NotApplicablePresentation(
            reason: "屋外の写真のため、住まいの室内を確認できませんでした。",
            content: content
        )

        XCTAssertEqual(
            noFindings.heading,
            "写真で見える範囲では、明らかな注意候補を確認できませんでした"
        )
        XCTAssertEqual(noFindings.limitation, "住まい全体の安全を示すものではありません")
        XCTAssertFalse(noFindings.visibleText.contains("安全です"))
        XCTAssertFalse(noFindings.visibleText.contains("問題ありません"))
        XCTAssertEqual(notApplicable.reason, "屋外の写真のため、住まいの室内を確認できませんでした。")
        XCTAssertTrue(notApplicable.guidance.contains("室内写真"))
        XCTAssertFalse(notApplicable.visibleText.contains("注意度"))
        XCTAssertFalse(notApplicable.visibleText.contains("次にできること"))
    }

    func testNotApplicableRejectsUnsafeServerReason() {
        let content = ResultStateContent.production
        let tooLong = String(repeating: "a", count: 4_097)
        let control = "reason\u{0000}token"
        let bidi = "reason\u{2067}token"

        XCTAssertEqual(
            NotApplicablePresentation(reason: tooLong, content: content).reason,
            content.notApplicableFallbackReason
        )
        XCTAssertEqual(
            NotApplicablePresentation(reason: control, content: content).reason,
            content.notApplicableFallbackReason
        )
        XCTAssertEqual(
            NotApplicablePresentation(reason: bidi, content: content).reason,
            content.notApplicableFallbackReason
        )
    }

    func testProductionSourcesContainNoForbiddenSafetyAssertions() throws {
        let sourceRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "SumaiGuard")
        let enumerator = try XCTUnwrap(FileManager.default.enumerator(at: sourceRoot, includingPropertiesForKeys: nil))
        let swiftFiles = enumerator.compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" }
        let source = try swiftFiles.map { try String(contentsOf: $0, encoding: .utf8) }.joined(separator: "\n")

        XCTAssertFalse(source.contains("安全です"))
        XCTAssertFalse(source.contains("問題ありません"))
    }

    func testErrorPresentationUsesOnlyStableUserFacingMessage() {
        for error in [
            UserFacingError.invalidImage,
            .imageTooLarge,
            .verificationUnavailable,
            .serviceBusy,
            .serviceUnavailable,
            .invalidResponse,
            .network,
            .unexpected,
        ] {
            let presentation = ErrorPresentation(error: error)
            XCTAssertEqual(presentation.message, error.messageJA)
            XCTAssertEqual(presentation.retryLabel, "写真を確認してもう一度試す")
            XCTAssertFalse(presentation.visibleText.localizedCaseInsensitiveContains("firebase"))
            XCTAssertFalse(presentation.visibleText.localizedCaseInsensitiveContains("gemini"))
            XCTAssertFalse(presentation.visibleText.localizedCaseInsensitiveContains("token"))
            XCTAssertFalse(presentation.visibleText.contains("https://"))
        }
    }

    func testActionModelsInvokeOnlyTheirNamedCoordinatorTransitions() {
        var processingCancel = 0
        ProcessingActions(cancelProcessing: { processingCancel += 1 }).cancelProcessing()

        var advice = 0
        var resultHome = 0
        let resultActions = ResultActions(
            showAdvice: { advice += 1 },
            returnHome: { resultHome += 1 }
        )
        resultActions.showAdvice()
        resultActions.returnHome()

        var adviceHome = 0
        AdviceActions(returnHome: { adviceHome += 1 }).returnHome()
        var noFindingsHome = 0
        NoFindingsActions(returnHome: { noFindingsHome += 1 }).returnHome()
        var notApplicableHome = 0
        NotApplicableActions(returnHome: { notApplicableHome += 1 }).returnHome()
        var retry = 0
        var errorHome = 0
        let errorActions = ErrorActions(
            retry: { retry += 1 },
            returnHome: { errorHome += 1 }
        )
        errorActions.retry()
        errorActions.returnHome()

        XCTAssertEqual(processingCancel, 1)
        XCTAssertEqual(advice, 1)
        XCTAssertEqual(resultHome, 1)
        XCTAssertEqual(adviceHome, 1)
        XCTAssertEqual(noFindingsHome, 1)
        XCTAssertEqual(notApplicableHome, 1)
        XCTAssertEqual(retry, 1)
        XCTAssertEqual(errorHome, 1)
    }

    func testRootRoutingCoversEveryFormalResultState() throws {
        let selection = SelectedImage(preview: try syntheticCGImage(width: 2, height: 2))
        let applicable = try fixture("analysis-applicable")
        let notApplicable = try fixture("analysis-not-applicable")

        XCTAssertEqual(RootRouting.route(for: .processing(selection)), .processing(selection))
        XCTAssertEqual(RootRouting.route(for: .result(applicable)), .result(applicable))
        XCTAssertEqual(RootRouting.route(for: .advice(applicable)), .advice(applicable))
        XCTAssertEqual(RootRouting.route(for: .noFindings(applicable)), .noFindings(applicable))
        XCTAssertEqual(RootRouting.route(for: .notApplicable(notApplicable.notApplicableReasonJA!)), .notApplicable(notApplicable.notApplicableReasonJA!))
        XCTAssertEqual(RootRouting.route(for: .error(.network)), .error(.network))
    }

    func testRemoteDecoderAcceptsSingleFrameJPEGAndPNGAndNormalizesOrientation() async throws {
        let decoder = ResultImageDecoder()
        let jpeg = try imageData(type: .jpeg, width: 80, height: 120, orientation: 6)
        let png = try imageData(type: .png, width: 9, height: 7)

        let oriented = try await decoder.decode(jpeg.base64EncodedString())
        let decodedPNG = try await decoder.decode(png.base64EncodedString())

        XCTAssertEqual(oriented.width, 120)
        XCTAssertEqual(oriented.height, 80)
        XCTAssertEqual(decodedPNG.width, 9)
        XCTAssertEqual(decodedPNG.height, 7)
    }

    func testRemoteDecoderRejectsInvalidWhitespaceOversizePixelBombAndMultipleFrames() async throws {
        let strict = ResultImageDecoder(
            limits: .init(
                maxBase64Characters: 32,
                maxDecodedBytes: 8,
                maxSourcePixels: 100,
                maxLongSide: 20
            )
        )

        await assertDecodeError("not base64!", decoder: strict, expected: .invalidBase64)
        await assertDecodeError(" YQ==", decoder: strict, expected: .invalidBase64)
        await assertDecodeError(String(repeating: "A", count: 36), decoder: strict, expected: .encodedDataTooLarge)
        await assertDecodeError(Data(repeating: 0x01, count: 9).base64EncodedString(), decoder: strict, expected: .decodedDataTooLarge)

        let pixelDecoder = ResultImageDecoder(
            limits: .init(
                maxBase64Characters: 100_000,
                maxDecodedBytes: 100_000,
                maxSourcePixels: 100,
                maxLongSide: 20
            )
        )
        let pixelBomb = try imageData(type: .png, width: 11, height: 10)
        await assertDecodeError(pixelBomb.base64EncodedString(), decoder: pixelDecoder, expected: .sourceTooLarge)

        let gif = try multiFrameGIF()
        await assertDecodeError(gif.base64EncodedString(), decoder: pixelDecoder, expected: .unsupportedImage)
    }

    func testRemoteDecoderRejectsNonCanonicalBase64AndContainerPolyglots() async throws {
        let decoder = ResultImageDecoder(
            limits: .init(
                maxBase64Characters: 1_000_000,
                maxDecodedBytes: 1_000_000,
                maxSourcePixels: 1_000_000,
                maxLongSide: 1_600
            )
        )
        let png = try imageData(type: .png, width: 9, height: 7)
        let jpeg = try imageData(type: .jpeg, width: 9, height: 7)
        let gif = try multiFrameGIF()

        let paddedJPEG = try jpegWithBase64Padding(jpeg)
        let nonCanonical = try XCTUnwrap(nonCanonicalBase64(for: paddedJPEG))
        XCTAssertEqual(Data(base64Encoded: nonCanonical), paddedJPEG)
        await assertDecodeError(nonCanonical, decoder: decoder, expected: .invalidBase64)
        let canonicalPadded = paddedJPEG.base64EncodedString()
        await assertDecodeError(canonicalPadded + "=", decoder: decoder, expected: .invalidBase64)
        await assertDecodeError(String(canonicalPadded.dropLast()), decoder: decoder, expected: .invalidBase64)
        await assertDecodeError("\(png.base64EncodedString())\n", decoder: decoder, expected: .invalidBase64)

        var pngWithGIF = png
        pngWithGIF.append(gif)
        await assertDecodeError(pngWithGIF.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        var jpegWithZIP = jpeg
        jpegWithZIP.append(contentsOf: [0x50, 0x4B, 0x03, 0x04, 0x00, 0x00])
        await assertDecodeError(jpegWithZIP.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        await assertDecodeError(png.dropLast().base64EncodedString(), decoder: decoder, expected: .unsupportedImage)
        await assertDecodeError(jpeg.dropLast().base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        var overflowingPNG = png
        overflowingPNG.replaceSubrange(8..<12, with: [0xFF, 0xFF, 0xFF, 0xFF])
        await assertDecodeError(overflowingPNG.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        var utiSpoof = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        utiSpoof.append(gif)
        await assertDecodeError(utiSpoof.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)
    }

    func testRemoteDecoderRejectsPNGCRCAndChunkOrderingViolations() async throws {
        let decoder = ResultImageDecoder()
        let png = try imageData(type: .png, width: 9, height: 7)

        for type in ["IHDR", "IDAT", "IEND"] {
            let corrupted = try pngByFlippingCRC(of: type, in: png)
            await assertDecodeError(corrupted.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)
        }

        let unknownCritical = try pngByInsertingChunk(
            type: "ABCD",
            payload: Data(),
            before: "IDAT",
            in: png
        )
        await assertDecodeError(unknownCritical.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        let paletteAfterData = try pngByInsertingChunk(
            type: "PLTE",
            payload: Data([0x00, 0x00, 0x00]),
            before: "IEND",
            in: png
        )
        await assertDecodeError(paletteAfterData.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        let noncontiguousData = try pngBySplittingIDATWithAncillaryChunk(png)
        await assertDecodeError(noncontiguousData.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        let onePalette = try pngByInsertingChunk(
            type: "PLTE",
            payload: Data([0x00, 0x00, 0x00]),
            before: "IDAT",
            in: png
        )
        let duplicatePalette = try pngByInsertingChunk(
            type: "PLTE",
            payload: Data([0xFF, 0xFF, 0xFF]),
            before: "IDAT",
            in: onePalette
        )
        await assertDecodeError(duplicatePalette.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)

        let invalidReservedBit = try pngByInsertingChunk(
            type: "abca",
            payload: Data(),
            before: "IDAT",
            in: png
        )
        await assertDecodeError(invalidReservedBit.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)
    }

    func testRemoteDecoderRejectsCompressedPNGMetadataBeforeImageIO() async throws {
        let factory = RecordingRejectingResultImageSourceFactory()
        let decoder = ResultImageDecoder(sourceFactory: factory)
        let png = try imageData(type: .png, width: 1, height: 1)
        let expansionBytes = 50 * 1_024 * 1_024
        let compressedExpansion = try zlibCompressed(
            Data(repeating: 0, count: expansionBytes)
        )
        XCTAssertLessThan(compressedExpansion.count, 256 * 1_024)

        var iccp = Data("fixture-profile\0".utf8)
        iccp.append(0)
        iccp.append(compressedExpansion)
        var ztxt = Data("Comment\0".utf8)
        ztxt.append(0)
        ztxt.append(try zlibCompressed(Data("compressed text".utf8)))
        var itxt = Data("Comment\0".utf8)
        itxt.append(contentsOf: [1, 0, 0, 0])
        itxt.append(try zlibCompressed(Data("compressed international text".utf8)))

        for (type, payload) in [("iCCP", iccp), ("zTXt", ztxt), ("iTXt", itxt)] {
            let raw = try pngByInsertingChunk(
                type: type,
                payload: payload,
                before: "IDAT",
                in: png
            )
            await assertDecodeError(
                raw.base64EncodedString(),
                decoder: decoder,
                expected: .unsupportedImage
            )
        }

        let compressedMetadataInputs = await factory.receivedInputs
        XCTAssertTrue(compressedMetadataInputs.isEmpty)
    }

    func testRemoteDecoderStripsPNGMetadataButKeepsValidTransparency() async throws {
        let factory = CapturingResultImageSourceFactory()
        let decoder = ResultImageDecoder(sourceFactory: factory)
        let transparentPNG = try indexedTransparentPNG()
        let withExif = try pngByInsertingChunk(
            type: "eXIf",
            payload: Data([0x49, 0x49, 0x2A, 0x00, 0x08, 0x00, 0x00, 0x00]),
            before: "IDAT",
            in: transparentPNG
        )
        let raw = try pngByInsertingChunk(
            type: "vpAg",
            payload: Data("private metadata".utf8),
            before: "IDAT",
            in: withExif
        )

        let image = try await decoder.decode(raw.base64EncodedString())
        let inputs = await factory.receivedInputs

        XCTAssertEqual(image.width, 1)
        XCTAssertEqual(image.height, 1)
        XCTAssertEqual(inputs, [transparentPNG])
        XCTAssertNotEqual(inputs, [raw])
        XCTAssertNotNil(try? pngChunk(named: "tRNS", in: inputs[0]))
        XCTAssertNil(try? pngChunk(named: "eXIf", in: inputs[0]))
        XCTAssertNil(try? pngChunk(named: "vpAg", in: inputs[0]))
    }

    func testRemoteDecoderRejectsPNGBudgetExhaustionBeforeImageIO() async throws {
        let factory = RecordingRejectingResultImageSourceFactory()
        let decoder = ResultImageDecoder(sourceFactory: factory)
        let png = try imageData(type: .png, width: 1, height: 1)

        let tooManyChunks = try pngByInsertingRepeatedChunk(
            type: "vpAg",
            payload: Data(),
            count: 257,
            before: "IDAT",
            in: png
        )
        await assertDecodeError(
            tooManyChunks.base64EncodedString(),
            decoder: decoder,
            expected: .unsupportedImage
        )

        let tooManyIDATs = try pngByExpandingIDATCount(to: 129, in: png)
        await assertDecodeError(
            tooManyIDATs.base64EncodedString(),
            decoder: decoder,
            expected: .unsupportedImage
        )

        let excessiveAncillaryBytes = try pngByInsertingChunk(
            type: "vpAg",
            payload: Data(repeating: 0x41, count: 256 * 1_024 + 1),
            before: "IDAT",
            in: png
        )
        await assertDecodeError(
            excessiveAncillaryBytes.base64EncodedString(),
            decoder: decoder,
            expected: .unsupportedImage
        )

        let budgetExhaustionInputs = await factory.receivedInputs
        XCTAssertTrue(budgetExhaustionInputs.isEmpty)
    }

    func testRemoteDecoderRejectsMalformedOrDuplicateJPEGExif() async throws {
        let decoder = ResultImageDecoder()
        let encodedJPEG = try imageData(type: .jpeg, width: 9, height: 7)
        let jpeg = try XCTUnwrap(JPEGMetadataStripper.removeMetadata(from: encodedJPEG))
        let validExif = jpegExifPayload(orientation: 6)

        var badEndian = validExif
        badEndian.replaceSubrange(6..<8, with: [0x5A, 0x5A])
        var outOfBoundsIFD = validExif
        outOfBoundsIFD.replaceSubrange(10..<14, with: [0xFF, 0xFF, 0xFF, 0x7F])
        var badOrientationCount = validExif
        badOrientationCount.replaceSubrange(20..<24, with: [0x02, 0x00, 0x00, 0x00])
        var nonzeroNextIFD = validExif
        nonzeroNextIFD.replaceSubrange(28..<32, with: [0x08, 0x00, 0x00, 0x00])

        let malformedPayloads = [
            badEndian,
            outOfBoundsIFD,
            badOrientationCount,
            nonzeroNextIFD,
            jpegExifPayload(orientation: 9),
            jpegExifPayload(orientation: 6, orientationEntryCount: 2),
            Data("Exif\0\0".utf8) + Data(repeating: 0, count: 20_000),
        ]
        for payload in malformedPayloads {
            let malformed = try jpegByInsertingAPP1(payload, into: jpeg)
            await assertDecodeError(malformed.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)
        }

        let once = try jpegByInsertingAPP1(validExif, into: jpeg)
        let duplicateExif = try jpegByInsertingAPP1(validExif, into: once)
        await assertDecodeError(duplicateExif.base64EncodedString(), decoder: decoder, expected: .unsupportedImage)
    }

    func testJPEGImageIOSourceReceivesOnlyMetadataStrippedBytes() async throws {
        let factory = CapturingResultImageSourceFactory()
        let decoder = ResultImageDecoder(sourceFactory: factory)
        let jpeg = try imageData(type: .jpeg, width: 9, height: 7)
        let metadataFreeJPEG = try XCTUnwrap(JPEGMetadataStripper.removeMetadata(from: jpeg))
        let withXMP = try jpegByInsertingSegment(
            marker: 0xE1,
            payload: Data("http://ns.adobe.com/xap/1.0/\0fixture".utf8),
            into: metadataFreeJPEG
        )
        let withICC = try jpegByInsertingSegment(
            marker: 0xE2,
            payload: Data("ICC_PROFILE\0fixture".utf8),
            into: withXMP
        )
        let rawWithExif = try jpegByInsertingAPP1(
            jpegExifPayload(orientation: 6),
            into: withICC
        )
        let expectedStripped = try XCTUnwrap(JPEGMetadataStripper.removeMetadata(from: rawWithExif))

        let image = try await decoder.decode(rawWithExif.base64EncodedString())
        let inputs = await factory.receivedInputs

        XCTAssertEqual(image.width, 7)
        XCTAssertEqual(image.height, 9)
        XCTAssertEqual(inputs, [expectedStripped])
        XCTAssertNotEqual(inputs, [rawWithExif])
    }

    func testJPEGMarkerWalkerHandlesStuffingRestartAndMultipleScans() {
        var jpeg = Data([0xFF, 0xD8])
        let exif = jpegExifPayload(orientation: 6)
        let segmentLength = exif.count + 2
        jpeg.append(contentsOf: [
            0xFF, 0xE1,
            UInt8((segmentLength >> 8) & 0xFF), UInt8(segmentLength & 0xFF),
        ])
        jpeg.append(exif)
        let scanHeader = Data([
            0xFF, 0xDA, 0x00, 0x08,
            0x01, 0x01, 0x00, 0x00, 0x3F, 0x00,
        ])
        jpeg.append(scanHeader)
        jpeg.append(contentsOf: [0x11, 0xFF, 0x00, 0x22, 0xFF, 0xD0, 0x33])
        jpeg.append(scanHeader)
        jpeg.append(contentsOf: [0x44, 0xFF, 0xD1, 0x55, 0xFF, 0xD9])

        XCTAssertEqual(JPEGExifOrientationParser.orientation(in: jpeg), 6)

        let bigEndianExif = jpegExifPayload(orientation: 8, byteOrder: .big)
        var bigEndianJPEG = Data([0xFF, 0xD8])
        let bigEndianSegmentLength = bigEndianExif.count + 2
        bigEndianJPEG.append(contentsOf: [
            0xFF, 0xE1,
            UInt8((bigEndianSegmentLength >> 8) & 0xFF),
            UInt8(bigEndianSegmentLength & 0xFF),
        ])
        bigEndianJPEG.append(bigEndianExif)
        bigEndianJPEG.append(scanHeader)
        bigEndianJPEG.append(contentsOf: [0x44, 0xFF, 0xD9])
        XCTAssertEqual(JPEGExifOrientationParser.orientation(in: bigEndianJPEG), 8)
    }

    func testRemoteDecoderBoundsLongSideAndHonorsCancellation() async throws {
        let decoder = ResultImageDecoder(
            limits: .init(
                maxBase64Characters: 1_000_000,
                maxDecodedBytes: 1_000_000,
                maxSourcePixels: 1_000_000,
                maxLongSide: 160
            )
        )
        let large = try imageData(type: .jpeg, width: 800, height: 400)
        let image = try await decoder.decode(large.base64EncodedString())
        XCTAssertEqual(image.width, 160)
        XCTAssertEqual(image.height, 80)

        let task = Task {
            try await decoder.decode(large.base64EncodedString())
        }
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("A cancelled result-image decode must not publish pixels")
        } catch {
            XCTAssertTrue(error is CancellationError)
        }
    }

    func testRemoteImageModelIgnoresOldLateSuccessErrorAndDisappearCompletion() async throws {
        let decoder = ControlledResultImageDecoder()
        let model = RemoteResultImageModel(decoder: decoder)
        let oldImage = try syntheticCGImage(width: 2, height: 2)
        let newImage = try syntheticCGImage(width: 3, height: 3)

        let oldSuccess = Task { await model.load("old-success") }
        try await waitUntil { await decoder.callCount == 1 }
        let newSuccess = Task { await model.load("new-success") }
        try await waitUntil { await decoder.callCount == 2 }
        await decoder.succeed(call: 1, image: newImage)
        await newSuccess.value
        XCTAssertTrue(model.image === newImage)
        XCTAssertFalse(model.isUnavailable)

        await decoder.succeed(call: 0, image: oldImage)
        await oldSuccess.value
        XCTAssertTrue(model.image === newImage)
        XCTAssertFalse(model.isUnavailable)

        let oldFailure = Task { await model.load("old-failure") }
        try await waitUntil { await decoder.callCount == 3 }
        let replacement = Task { await model.load("replacement") }
        try await waitUntil { await decoder.callCount == 4 }
        await decoder.succeed(call: 3, image: newImage)
        await replacement.value
        await decoder.fail(call: 2)
        await oldFailure.value
        XCTAssertTrue(model.image === newImage)
        XCTAssertFalse(model.isUnavailable)

        let oldCancellation = Task { await model.load("old-cancel") }
        try await waitUntil { await decoder.callCount == 5 }
        let afterCancellation = Task { await model.load("after-cancel") }
        try await waitUntil { await decoder.callCount == 6 }
        await decoder.succeed(call: 5, image: newImage)
        await afterCancellation.value
        await decoder.cancel(call: 4)
        await oldCancellation.value
        XCTAssertTrue(model.image === newImage)
        XCTAssertFalse(model.isUnavailable)

        let disappearing = Task { await model.load("disappear") }
        try await waitUntil { await decoder.callCount == 7 }
        model.invalidate()
        await decoder.succeed(call: 6, image: oldImage)
        await disappearing.value
        XCTAssertNil(model.image)
        XCTAssertFalse(model.isUnavailable)
        XCTAssertFalse(model.isLoading)
    }

    func testRemoteResultImageSourceHasNoPersistenceCacheOrLoggingAPI() throws {
        let sourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "SumaiGuard/Views/RemoteResultImage.swift")
        let source = try String(contentsOf: sourceURL, encoding: .utf8)

        for forbidden in ["FileManager", "UserDefaults", "URLCache", "NSCache", "UIImageWriteToSavedPhotosAlbum", "Logger(", "os_log", "print("] {
            XCTAssertFalse(source.contains(forbidden), "Remote result images must stay memory-only: \(forbidden)")
        }
        XCTAssertTrue(source.contains(".task(id:"))
        XCTAssertTrue(source.contains("Task.checkCancellation"))
    }

    func testEveryFormalStateRendersFromSyntheticContent() throws {
        let applicable = try fixture("analysis-applicable")
        let views: [AnyView] = [
            AnyView(ProcessingView(
                selection: SelectedImage(preview: try syntheticCGImage(width: 3, height: 5)),
                actions: .init(cancelProcessing: {})
            )),
            AnyView(ResultView(response: applicable, actions: .init(showAdvice: {}, returnHome: {}))),
            AnyView(AdviceView(response: applicable, actions: .init(returnHome: {}))),
            AnyView(NoFindingsView(actions: .init(returnHome: {}))),
            AnyView(NotApplicableView(reason: "室内を確認できる写真ではありませんでした。", actions: .init(returnHome: {}))),
            AnyView(ErrorView(error: .network, actions: .init(retry: {}, returnHome: {}))),
        ]

        for view in views {
            let renderer = ImageRenderer(content: view.frame(width: 390, height: 844))
            renderer.scale = 1
            XCTAssertNotNil(renderer.uiImage)
        }
    }

    private func fixture(_ name: String) throws -> AnalysisResponse {
        let url = Bundle(for: Self.self).url(forResource: name, withExtension: "json")!
        return try JSONDecoder.sumai.decode(AnalysisResponse.self, from: Data(contentsOf: url))
    }

    private func modifiedApplicableFixture(
        _ update: (inout [String: Any]) throws -> Void
    ) throws -> AnalysisResponse {
        let url = Bundle(for: Self.self).url(forResource: "analysis-applicable", withExtension: "json")!
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
        )
        try update(&object)
        return try JSONDecoder.sumai.decode(
            AnalysisResponse.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
    }

    private func assertPresentationsFailClosed(
        _ response: AnalysisResponse,
        hiddenMarker: String? = nil,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertNil(ResultPresentation(response: response), file: file, line: line)
        let advice = AdvicePresentation(response: response)
        XCTAssertEqual(advice.failureMessage, "提案を安全に表示できません", file: file, line: line)
        XCTAssertTrue(advice.sections.flatMap(\.items).isEmpty, file: file, line: line)
        if let hiddenMarker {
            XCTAssertFalse(advice.visibleText.contains(hiddenMarker), file: file, line: line)
        }
    }

    private func assertDecodeError(
        _ base64: String,
        decoder: ResultImageDecoder,
        expected: ResultImageError,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            _ = try await decoder.decode(base64)
            XCTFail("Expected \(expected)", file: file, line: line)
        } catch {
            XCTAssertEqual(error as? ResultImageError, expected, file: file, line: line)
        }
    }

    private func syntheticCGImage(width: Int, height: Int) throws -> CGImage {
        guard
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * 4,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ),
            let image = context.makeImage()
        else {
            throw SyntheticImageError.creationFailed
        }
        context.setFillColor(CGColor(red: 0.1, green: 0.3, blue: 0.2, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return image
    }

    private func imageData(
        type: UTType,
        width: Int,
        height: Int,
        orientation: Int? = nil
    ) throws -> Data {
        let image = try syntheticCGImage(width: width, height: height)
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            data,
            type.identifier as CFString,
            1,
            nil
        ) else {
            throw SyntheticImageError.creationFailed
        }
        var properties: [CFString: Any] = [:]
        if let orientation {
            properties[kCGImagePropertyOrientation] = orientation
        }
        CGImageDestinationAddImage(destination, image, properties as CFDictionary)
        guard CGImageDestinationFinalize(destination) else {
            throw SyntheticImageError.creationFailed
        }
        return data as Data
    }

    private func multiFrameGIF() throws -> Data {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            data,
            UTType.gif.identifier as CFString,
            2,
            nil
        ) else {
            throw SyntheticImageError.creationFailed
        }
        CGImageDestinationAddImage(destination, try syntheticCGImage(width: 2, height: 2), nil)
        CGImageDestinationAddImage(destination, try syntheticCGImage(width: 2, height: 2), nil)
        guard CGImageDestinationFinalize(destination) else {
            throw SyntheticImageError.creationFailed
        }
        return data as Data
    }

    private func nonCanonicalBase64(for data: Data) -> String? {
        let canonical = data.base64EncodedString()
        guard let paddingIndex = canonical.firstIndex(of: "=") else {
            return nil
        }
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
        let significantIndex = canonical.index(before: paddingIndex)
        guard let canonicalValue = alphabet.firstIndex(of: canonical[significantIndex]) else {
            return nil
        }
        let paddingCount = canonical[paddingIndex...].count
        let replacementValue: Int
        if paddingCount == 2 {
            replacementValue = (canonicalValue & 0b11_0000) | 0b0001
        } else if paddingCount == 1 {
            replacementValue = (canonicalValue & 0b11_1100) | 0b0001
        } else {
            return nil
        }
        var mutated = canonical
        mutated.replaceSubrange(significantIndex...significantIndex, with: String(alphabet[replacementValue]))
        return mutated
    }

    private func jpegWithBase64Padding(_ jpeg: Data) throws -> Data {
        guard jpeg.starts(with: [0xFF, 0xD8]) else {
            throw SyntheticImageError.creationFailed
        }
        for payloadCount in 1...3 {
            var candidate = Data([0xFF, 0xD8, 0xFF, 0xE1, 0x00, UInt8(payloadCount + 2)])
            candidate.append(Data(repeating: 0, count: payloadCount))
            candidate.append(jpeg.dropFirst(2))
            if candidate.count % 3 != 0 {
                return candidate
            }
        }
        throw SyntheticImageError.creationFailed
    }

    private func pngByFlippingCRC(of type: String, in png: Data) throws -> Data {
        let chunk = try pngChunk(named: type, in: png)
        var result = png
        let crcOffset = chunk.start + 8 + chunk.payloadLength
        result[crcOffset] ^= 0x01
        return result
    }

    private func pngByInsertingChunk(
        type: String,
        payload: Data,
        before nextType: String,
        in png: Data
    ) throws -> Data {
        let next = try pngChunk(named: nextType, in: png)
        var result = png
        result.insert(contentsOf: pngChunk(type: type, payload: payload), at: next.start)
        return result
    }

    private func pngBySplittingIDATWithAncillaryChunk(_ png: Data) throws -> Data {
        let idat = try pngChunk(named: "IDAT", in: png)
        let payloadStart = idat.start + 8
        let payload = png[payloadStart..<(payloadStart + idat.payloadLength)]
        let split = max(1, payload.count / 2)
        var replacement = pngChunk(type: "IDAT", payload: Data(payload.prefix(split)))
        replacement.append(pngChunk(type: "tEXt", payload: Data("note\0value".utf8)))
        replacement.append(pngChunk(type: "IDAT", payload: Data(payload.dropFirst(split))))

        var result = png
        result.replaceSubrange(idat.start..<idat.end, with: replacement)
        return result
    }

    private func pngByInsertingRepeatedChunk(
        type: String,
        payload: Data,
        count: Int,
        before nextType: String,
        in png: Data
    ) throws -> Data {
        let next = try pngChunk(named: nextType, in: png)
        var inserted = Data()
        for _ in 0..<count {
            inserted.append(pngChunk(type: type, payload: payload))
        }
        var result = png
        result.insert(contentsOf: inserted, at: next.start)
        return result
    }

    private func pngByExpandingIDATCount(to count: Int, in png: Data) throws -> Data {
        let idat = try pngChunk(named: "IDAT", in: png)
        let payloadStart = idat.start + 8
        let payload = Data(png[payloadStart..<(payloadStart + idat.payloadLength)])
        var replacement = pngChunk(type: "IDAT", payload: payload)
        for _ in 1..<count {
            replacement.append(pngChunk(type: "IDAT", payload: Data()))
        }
        var result = png
        result.replaceSubrange(idat.start..<idat.end, with: replacement)
        return result
    }

    private func indexedTransparentPNG() throws -> Data {
        var result = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        let ihdr = Data([
            0x00, 0x00, 0x00, 0x01,
            0x00, 0x00, 0x00, 0x01,
            0x08, 0x03, 0x00, 0x00, 0x00,
        ])
        result.append(pngChunk(type: "IHDR", payload: ihdr))
        result.append(pngChunk(type: "PLTE", payload: Data([0xFF, 0x00, 0x00])))
        result.append(pngChunk(type: "tRNS", payload: Data([0x80])))
        result.append(
            pngChunk(
                type: "IDAT",
                payload: try zlibCompressed(Data([0x00, 0x00]))
            )
        )
        result.append(pngChunk(type: "IEND", payload: Data()))
        return result
    }

    private func zlibCompressed(_ source: Data) throws -> Data {
        let bound = compressBound(uLong(source.count))
        guard bound <= Int.max else {
            throw SyntheticImageError.creationFailed
        }
        var destination = Data(count: Int(bound))
        var encodedSize = uLongf(bound)
        let status = source.withUnsafeBytes { sourceBytes in
            destination.withUnsafeMutableBytes { destinationBytes in
                guard
                    let sourceAddress = sourceBytes.bindMemory(to: UInt8.self).baseAddress,
                    let destinationAddress = destinationBytes.bindMemory(to: UInt8.self).baseAddress
                else {
                    return Z_STREAM_ERROR
                }
                return compress2(
                    destinationAddress,
                    &encodedSize,
                    sourceAddress,
                    uLong(source.count),
                    Z_BEST_COMPRESSION
                )
            }
        }
        guard status == Z_OK, encodedSize > 0, encodedSize <= destination.count else {
            throw SyntheticImageError.creationFailed
        }
        destination.removeSubrange(Int(encodedSize)..<destination.count)
        return destination
    }

    private func pngChunk(named name: String, in png: Data) throws -> PNGChunkLocation {
        var cursor = 8
        while cursor <= png.count - 12 {
            let length = Int(png[cursor]) << 24
                | Int(png[cursor + 1]) << 16
                | Int(png[cursor + 2]) << 8
                | Int(png[cursor + 3])
            guard length <= png.count - cursor - 12 else {
                break
            }
            let type = String(bytes: png[(cursor + 4)..<(cursor + 8)], encoding: .ascii)
            if type == name {
                return PNGChunkLocation(start: cursor, payloadLength: length, end: cursor + 12 + length)
            }
            cursor += 12 + length
        }
        throw SyntheticImageError.creationFailed
    }

    private func pngChunk(type: String, payload: Data) -> Data {
        let typeBytes = Data(type.utf8)
        var result = Data()
        appendBigEndian(UInt32(payload.count), to: &result)
        result.append(typeBytes)
        result.append(payload)
        appendBigEndian(pngCRC32(typeBytes + payload), to: &result)
        return result
    }

    private func pngCRC32(_ data: Data) -> UInt32 {
        var crc = UInt32.max
        for byte in data {
            crc ^= UInt32(byte)
            for _ in 0..<8 {
                crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xEDB8_8320 : crc >> 1
            }
        }
        return crc ^ UInt32.max
    }

    private func appendBigEndian(_ value: UInt32, to data: inout Data) {
        data.append(UInt8((value >> 24) & 0xFF))
        data.append(UInt8((value >> 16) & 0xFF))
        data.append(UInt8((value >> 8) & 0xFF))
        data.append(UInt8(value & 0xFF))
    }

    private func jpegByInsertingAPP1(_ payload: Data, into jpeg: Data) throws -> Data {
        try jpegByInsertingSegment(marker: 0xE1, payload: payload, into: jpeg)
    }

    private func jpegByInsertingSegment(
        marker: UInt8,
        payload: Data,
        into jpeg: Data
    ) throws -> Data {
        guard
            jpeg.starts(with: [0xFF, 0xD8]),
            (0xE0...0xEF).contains(marker),
            payload.count <= 65_533
        else {
            throw SyntheticImageError.creationFailed
        }
        let segmentLength = payload.count + 2
        var segment = Data([
            0xFF,
            marker,
            UInt8((segmentLength >> 8) & 0xFF),
            UInt8(segmentLength & 0xFF),
        ])
        segment.append(payload)
        var result = Data(jpeg.prefix(2))
        result.append(segment)
        result.append(jpeg.dropFirst(2))
        return result
    }

    private func jpegExifPayload(
        orientation: UInt16,
        orientationEntryCount: Int = 1,
        byteOrder: SyntheticTIFFByteOrder = .little
    ) -> Data {
        var payload = Data("Exif\0\0".utf8)
        switch byteOrder {
        case .little:
            payload.append(contentsOf: [
                0x49, 0x49, 0x2A, 0x00,
                0x08, 0x00, 0x00, 0x00,
                UInt8(orientationEntryCount), 0x00,
            ])
        case .big:
            payload.append(contentsOf: [
                0x4D, 0x4D, 0x00, 0x2A,
                0x00, 0x00, 0x00, 0x08,
                0x00, UInt8(orientationEntryCount),
            ])
        }
        for _ in 0..<orientationEntryCount {
            switch byteOrder {
            case .little:
                payload.append(contentsOf: [
                    0x12, 0x01,
                    0x03, 0x00,
                    0x01, 0x00, 0x00, 0x00,
                    UInt8(orientation & 0xFF), UInt8((orientation >> 8) & 0xFF), 0x00, 0x00,
                ])
            case .big:
                payload.append(contentsOf: [
                    0x01, 0x12,
                    0x00, 0x03,
                    0x00, 0x00, 0x00, 0x01,
                    UInt8((orientation >> 8) & 0xFF), UInt8(orientation & 0xFF), 0x00, 0x00,
                ])
            }
        }
        payload.append(contentsOf: [0x00, 0x00, 0x00, 0x00])
        return payload
    }

    private func waitUntil(
        timeout: Duration = .seconds(2),
        _ condition: @escaping @Sendable () async -> Bool
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !(await condition()) {
            guard clock.now < deadline else {
                throw SyntheticImageError.timedOut
            }
            await Task.yield()
        }
    }
}

private enum SyntheticImageError: Error {
    case creationFailed
    case timedOut
}

private struct PNGChunkLocation {
    let start: Int
    let payloadLength: Int
    let end: Int
}

private enum SyntheticTIFFByteOrder {
    case little
    case big
}

private actor ControlledResultImageDecoder: ResultImageDecoding {
    private var continuations: [CheckedContinuation<CGImage, any Error>] = []

    var callCount: Int { continuations.count }

    func decode(_ base64: String) async throws -> CGImage {
        _ = base64
        return try await withCheckedThrowingContinuation { continuation in
            continuations.append(continuation)
        }
    }

    func succeed(call: Int, image: CGImage) {
        continuations[call].resume(returning: image)
    }

    func fail(call: Int) {
        continuations[call].resume(throwing: ResultImageError.decodeFailed)
    }

    func cancel(call: Int) {
        continuations[call].resume(throwing: CancellationError())
    }
}

private actor CapturingResultImageSourceFactory: ResultImageSourceCreating {
    private(set) var receivedInputs: [Data] = []

    func makeSource(from data: Data) async -> ResultImageSourceHandle? {
        receivedInputs.append(data)
        let options = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, options) else {
            return nil
        }
        return ResultImageSourceHandle(source: source)
    }
}

private actor RecordingRejectingResultImageSourceFactory: ResultImageSourceCreating {
    private(set) var receivedInputs: [Data] = []

    func makeSource(from data: Data) async -> ResultImageSourceHandle? {
        receivedInputs.append(data)
        return nil
    }
}
