import Foundation
@testable import SumaiGuard
import UIKit
import XCTest

final class AnalysisResponseTests: XCTestCase {
    func testDecodesApplicableResponseExactly() throws {
        let response = try JSONDecoder.sumai.decode(
            AnalysisResponse.self,
            from: fixture("analysis-applicable")
        )

        XCTAssertEqual(response.id, "analysis-fixture-001")
        XCTAssertEqual(response.roomType, .genkan)
        XCTAssertEqual(response.overallRiskLevel, .high)
        XCTAssertEqual(response.findings.count, 2)
        XCTAssertEqual(response.findings[0].severity, 4)
        XCTAssertEqual(response.findings[0].confidence, 0.94)
        XCTAssertEqual(response.findings[0].bbox, BoundingBox(x: 0.1, y: 0.55, w: 0.3, h: 0.2))
        XCTAssertEqual(response.findings[0].displayBBox, BoundingBox(x: 0.08, y: 0.53, w: 0.34, h: 0.24))
        XCTAssertEqual(response.findings[0].evidenceSourceIDs, ["entity-mat-1"])
        XCTAssertEqual(response.findings[0].ontologyRuleKind, .visibleHazard)
        XCTAssertEqual(response.findings[1].ontologyRuleKind, .expectedFeature)
        XCTAssertNil(response.findings[1].displayBBox)

        XCTAssertEqual(response.actionPlan.familyNoCost.first?.tier, .familyNoCost)
        XCTAssertEqual(response.actionPlan.familyNoCost.first?.costLevel, .zero)
        XCTAssertEqual(response.actionPlan.careManagerPurchase.first?.tier, .careManagerPurchase)
        XCTAssertEqual(response.actionPlan.careManagerPurchase.first?.costLevel, .low)
        XCTAssertEqual(response.actionPlan.contractorConstruction.first?.tier, .contractorConstruction)
        XCTAssertEqual(response.actionPlan.contractorConstruction.first?.costLevel, .high)

        XCTAssertEqual(response.annotatedImageBase64, Self.syntheticPixelBase64)
        XCTAssertEqual(response.improvementImageBase64, Self.syntheticPixelBase64)
        XCTAssertEqual(response.model, "fictional-vision-model")
        XCTAssertEqual(response.resultKey, "fixture-result-key")
        XCTAssertEqual(response.semanticHash, "fixture-semantic-hash")
        XCTAssertEqual(response.schemaVersion, "2.0.0")
        XCTAssertEqual(response.ontologyVersion, "1.0.0")
        XCTAssertEqual(response.preprocessVersion, "1.0.0")
        XCTAssertEqual(response.inferenceConfigVersion, "1.0.0")
        XCTAssertEqual(response.stageTimingsMS["total"], 120)
        XCTAssertTrue(response.isHomeEnvironment)
        XCTAssertFalse(response.isNotApplicable)
        XCTAssertNil(response.notApplicableReasonJA)
    }

    func testDecodesValidNotApplicableResponse() throws {
        let response = try JSONDecoder.sumai.decode(
            AnalysisResponse.self,
            from: fixture("analysis-not-applicable")
        )

        XCTAssertEqual(response.roomType, .auto)
        XCTAssertEqual(response.overallRiskLevel, .low)
        XCTAssertFalse(response.isHomeEnvironment)
        XCTAssertTrue(response.isNotApplicable)
        XCTAssertEqual(response.notApplicableReasonJA, "住まいの室内を確認できる写真ではありません。")
        XCTAssertTrue(response.findings.isEmpty)
        XCTAssertTrue(response.actionPlan.familyNoCost.isEmpty)
        XCTAssertTrue(response.actionPlan.careManagerPurchase.isEmpty)
        XCTAssertTrue(response.actionPlan.contractorConstruction.isEmpty)
    }

    func testFixtureImagesDecodeAsExactOnePixelImages() throws {
        for fixtureName in ["analysis-applicable", "analysis-not-applicable"] {
            let response = try JSONDecoder.sumai.decode(
                AnalysisResponse.self,
                from: fixture(fixtureName)
            )

            for (fieldName, encodedImage) in [
                ("annotated_image_base64", response.annotatedImageBase64),
                ("improvement_image_base64", response.improvementImageBase64),
            ] {
                let imageData = try XCTUnwrap(
                    Data(base64Encoded: encodedImage),
                    "\(fixtureName).\(fieldName) is not valid base64"
                )
                assertValidPNGChecksums(
                    imageData,
                    context: "\(fixtureName).\(fieldName)"
                )
                let image = try XCTUnwrap(
                    UIImage(data: imageData),
                    "\(fixtureName).\(fieldName) is not a decodable image"
                )
                let pixels = try XCTUnwrap(
                    image.cgImage,
                    "\(fixtureName).\(fieldName) has no CGImage pixels"
                )

                XCTAssertEqual(pixels.width, 1, "\(fixtureName).\(fieldName) width")
                XCTAssertEqual(pixels.height, 1, "\(fixtureName).\(fieldName) height")
            }
        }
    }

    func testRejectsUnknownActionTier() throws {
        let data = try fixture(
            "analysis-applicable",
            replacing: #""tier": "FAMILY_NO_COST""#,
            with: #""tier": "UNKNOWN_TIER""#
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testRejectsBoundingBoxOutsideNormalizedFrame() throws {
        let data = try fixture(
            "analysis-applicable",
            replacing: #""w": 0.3"#,
            with: #""w": 0.95"#
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testRejectsSeverityOutsideOneThroughFive() throws {
        let data = try fixture(
            "analysis-applicable",
            replacing: #""severity": 4"#,
            with: #""severity": 6"#
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testRejectsConfidenceOutsideNormalizedRange() throws {
        let data = try fixture(
            "analysis-applicable",
            replacing: #""confidence": 0.94"#,
            with: #""confidence": 1.01"#
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testRejectsApplicableResponseWithoutHomeEnvironment() throws {
        let data = try fixture(
            "analysis-applicable",
            replacing: #""is_home_environment": true"#,
            with: #""is_home_environment": false"#
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testRejectsNotApplicableResponseWithoutNonblankReason() throws {
        let data = try fixture(
            "analysis-not-applicable",
            replacing: #""not_applicable_reason_ja": "住まいの室内を確認できる写真ではありません。""#,
            with: #""not_applicable_reason_ja": "   ""#
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testRejectsNotApplicableResponseWithFindingsAndActions() throws {
        var text = try fixtureText("analysis-applicable")
        text = try replacing("\"room_type\": \"genkan\"", with: "\"room_type\": \"auto\"", in: text)
        text = try replacing(
            "\"overall_risk_level\": \"high\"",
            with: "\"overall_risk_level\": \"low\"",
            in: text
        )
        text = try replacing(
            "\"is_not_applicable\": false",
            with: "\"is_not_applicable\": true",
            in: text
        )
        text = try replacing(
            "\"not_applicable_reason_ja\": null",
            with: "\"not_applicable_reason_ja\": \"住まいの室内を確認できません。\"",
            in: text
        )

        XCTAssertThrowsError(
            try JSONDecoder.sumai.decode(AnalysisResponse.self, from: Data(text.utf8))
        )
    }

    func testRejectsMissingRequiredResponseField() throws {
        let data = try fixture(
            "analysis-applicable",
            replacing: "  \"schema_version\": \"2.0.0\",\n",
            with: ""
        )

        XCTAssertThrowsError(try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data))
    }

    func testMapsServerErrorFromMatchingHTTPStatusAndStableCode() throws {
        let data = try fixture("error-app-check")
        let envelope = try JSONDecoder.sumai.decode(ServerErrorEnvelope.self, from: data)

        XCTAssertEqual(envelope.code, .appCheckInvalid)
        XCTAssertEqual(ServerErrorEnvelope.map(statusCode: 401, body: data), .appCheckInvalid)
    }

    func testRejectsMismatchedHTTPStatusAndStableCode() throws {
        let data = try fixture("error-app-check")

        XCTAssertEqual(ServerErrorEnvelope.map(statusCode: 500, body: data), .invalidResponse)
    }

    func testUnknownServerPayloadUsesSafeFallback() {
        let data = Data(
            #"{"error":"PROVIDER_SECRET_CODE","message":"SECRET_PROVIDER_DETAIL","detail":"SECRET_BODY"}"#.utf8
        )

        XCTAssertEqual(ServerErrorEnvelope.map(statusCode: 503, body: data), .invalidResponse)
    }

    func testTransportCancellationAndFailureMapWithoutRawDetails() {
        XCTAssertEqual(APIError.fromTransport(CancellationError()), .cancelled)
        XCTAssertEqual(APIError.fromTransport(URLError(.cancelled)), .cancelled)
        XCTAssertEqual(APIError.fromTransport(URLError(.cannotConnectToHost)), .network)
    }
}

private extension AnalysisResponseTests {
    static let syntheticPixelBase64 =
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMQtzUCAAD1AIeGlNxsAAAAAElFTkSuQmCC"

    enum FixtureMutationError: Error {
        case targetNotFound(String)
    }

    func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: name, withExtension: "json"),
            "Missing fixture: \(name).json"
        )
        return try Data(contentsOf: url)
    }

    func fixture(
        _ name: String,
        replacing target: String,
        with replacement: String
    ) throws -> Data {
        let text = try fixtureText(name)
        return Data(try replacing(target, with: replacement, in: text).utf8)
    }

    func fixtureText(_ name: String) throws -> String {
        String(decoding: try fixture(name), as: UTF8.self)
    }

    func replacing(_ target: String, with replacement: String, in text: String) throws -> String {
        guard text.contains(target) else {
            throw FixtureMutationError.targetNotFound(target)
        }
        return text.replacingOccurrences(of: target, with: replacement)
    }

    func assertValidPNGChecksums(
        _ data: Data,
        context: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let bytes = [UInt8](data)
        let signature: [UInt8] = [137, 80, 78, 71, 13, 10, 26, 10]
        guard bytes.starts(with: signature) else {
            XCTFail("\(context) has no PNG signature", file: file, line: line)
            return
        }

        var offset = signature.count
        while offset < bytes.count {
            guard offset + 12 <= bytes.count else {
                XCTFail("\(context) has a truncated PNG chunk", file: file, line: line)
                return
            }

            let payloadLength = Int(bigEndianUInt32(bytes, at: offset))
            let chunkEnd = offset + 12 + payloadLength
            guard chunkEnd <= bytes.count else {
                XCTFail("\(context) has a truncated PNG payload", file: file, line: line)
                return
            }

            let checksumInput = bytes[(offset + 4)..<(offset + 8 + payloadLength)]
            let storedChecksum = bigEndianUInt32(bytes, at: offset + 8 + payloadLength)
            XCTAssertEqual(
                storedChecksum,
                crc32(checksumInput),
                "\(context) has an invalid PNG chunk checksum",
                file: file,
                line: line
            )
            offset = chunkEnd
        }
    }

    func bigEndianUInt32(_ bytes: [UInt8], at offset: Int) -> UInt32 {
        bytes[offset..<(offset + 4)].reduce(0) { value, byte in
            (value << 8) | UInt32(byte)
        }
    }

    func crc32(_ bytes: ArraySlice<UInt8>) -> UInt32 {
        var checksum = UInt32.max
        for byte in bytes {
            checksum ^= UInt32(byte)
            for _ in 0..<8 {
                let lowBitMask = UInt32(0) &- (checksum & 1)
                checksum = (checksum >> 1) ^ (0xEDB8_8320 & lowBitMask)
            }
        }
        return ~checksum
    }
}
