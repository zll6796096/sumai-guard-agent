import CoreGraphics
import Foundation
import ImageIO
@testable import SumaiGuard
import UniformTypeIdentifiers
import XCTest

@MainActor
final class ImageSanitizerTests: XCTestCase {
    func testNormalizesEveryEXIFOrientationIntoPixels() async throws {
        let cases: [(orientation: UInt32, width: Int, height: Int, corners: [CornerColor])] = [
            (1, 80, 120, [.red, .green, .blue, .yellow]),
            (2, 80, 120, [.green, .red, .yellow, .blue]),
            (3, 80, 120, [.yellow, .blue, .green, .red]),
            (4, 80, 120, [.blue, .yellow, .red, .green]),
            (5, 120, 80, [.red, .blue, .green, .yellow]),
            (6, 120, 80, [.blue, .red, .yellow, .green]),
            (7, 120, 80, [.yellow, .green, .blue, .red]),
            (8, 120, 80, [.green, .yellow, .red, .blue]),
        ]

        for testCase in cases {
            let source = try syntheticJPEG(
                width: 80,
                height: 120,
                orientation: testCase.orientation,
                usesFourCornerPattern: true
            )
            let sourceProperties = try imageProperties(source)
            XCTAssertEqual(
                sourceProperties[kCGImagePropertyOrientation] as? UInt32,
                testCase.orientation
            )

            let result = try await ImageSanitizer().sanitize(source)

            XCTAssertEqual(result.pixelWidth, testCase.width, "orientation \(testCase.orientation)")
            XCTAssertEqual(result.pixelHeight, testCase.height, "orientation \(testCase.orientation)")
            XCTAssertEqual(
                try decodedCornerColors(result.data),
                testCase.corners,
                "orientation \(testCase.orientation)"
            )
        }
    }

    func testLimitsLongestSideTo1600() async throws {
        let source = try syntheticJPEG(width: 2_000, height: 1_000)

        let result = try await ImageSanitizer().sanitize(source)

        XCTAssertEqual(result.pixelWidth, 1_600)
        XCTAssertEqual(result.pixelHeight, 800)
    }

    func testOutputIsJPEGWithStableUploadContractAndNoSourceMetadata() async throws {
        let source = try syntheticJPEG(
            width: 40,
            height: 60,
            orientation: 6,
            includesFakeGPS: true
        )
        let sourceProperties = try imageProperties(source)
        XCTAssertEqual(sourceProperties[kCGImagePropertyOrientation] as? UInt32, 6)
        XCTAssertNotNil(sourceProperties[kCGImagePropertyGPSDictionary])

        let result = try await ImageSanitizer().sanitize(source)

        XCTAssertEqual(result.mimeType, "image/jpeg")
        XCTAssertEqual(result.filename, "sumaiguard-upload.jpg")
        XCTAssertLessThanOrEqual(result.data.count, ImageSanitizer.maxBytes)
        let outputSource = try XCTUnwrap(CGImageSourceCreateWithData(result.data as CFData, nil))
        XCTAssertEqual(CGImageSourceGetType(outputSource) as String?, UTType.jpeg.identifier)
        let properties = try imageProperties(result.data)
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        XCTAssertNil(properties[kCGImagePropertyExifDictionary])
        XCTAssertNil(properties[kCGImagePropertyTIFFDictionary])
        XCTAssertNil(properties[kCGImagePropertyIPTCDictionary])
        if let orientation = properties[kCGImagePropertyOrientation] as? UInt32 {
            XCTAssertEqual(orientation, 1)
        }
    }

    func testMetadataStripperPreservesEntropyAcrossScansAndRemovesEveryMetadataMarker() {
        let table = jpegSegment(marker: 0xDB, payload: [0x00])
        let firstScan = jpegSegment(marker: 0xDA, payload: [0x01, 0x01, 0x00, 0x00, 0x3F, 0x00])
        let restartMarkers = (0...7).flatMap { marker in
            [UInt8(0xFF), UInt8(0xD0 + marker), UInt8(marker)]
        }
        let firstEntropy = [UInt8(0x11), 0xFF, 0x00, 0x22]
            + restartMarkers
            + [0x33]
        let metadata = (0xE0...0xEF).flatMap { marker in
            jpegSegment(marker: UInt8(marker), payload: [UInt8(marker - 0xE0)])
        } + jpegSegment(marker: 0xFE, payload: [0x43, 0x4F, 0x4D])
        let secondScan = jpegSegment(marker: 0xDA, payload: [0x01, 0x01, 0x00, 0x00, 0x3F, 0x00])
        let secondEntropy = [UInt8(0x44), 0xFF, 0x00, 0x55]
        let source = Data(
            [0xFF, 0xD8]
                + table
                + firstScan
                + firstEntropy
                + metadata
                + secondScan
                + secondEntropy
                + [0xFF, 0xD9]
        )
        let expected = Data(
            [0xFF, 0xD8]
                + table
                + firstScan
                + firstEntropy
                + secondScan
                + secondEntropy
                + [0xFF, 0xD9]
        )

        XCTAssertEqual(JPEGMetadataStripper.removeMetadata(from: source), expected)
    }

    func testMetadataStripperRejectsMissingEndOfImage() {
        let scan = jpegSegment(marker: 0xDA, payload: [0x01, 0x01, 0x00, 0x00, 0x3F, 0x00])
        let source = Data([0xFF, 0xD8] + scan + [0x11, 0xFF, 0x00, 0x22])

        XCTAssertNil(JPEGMetadataStripper.removeMetadata(from: source))
    }

    func testMetadataStripperRejectsTruncatedSegment() {
        let source = Data([0xFF, 0xD8, 0xFF, 0xE1, 0x00, 0x06, 0x01, 0x02])

        XCTAssertNil(JPEGMetadataStripper.removeMetadata(from: source))
    }

    func testMetadataStripperRejectsTruncatedScanHeader() {
        let source = Data([0xFF, 0xD8, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01])

        XCTAssertNil(JPEGMetadataStripper.removeMetadata(from: source))
    }

    func testRejectsUndecodableBytes() async {
        do {
            _ = try await ImageSanitizer().sanitize(Data("not an image".utf8))
            XCTFail("Undecodable input must fail closed")
        } catch {
            XCTAssertEqual(error as? ImageSanitizerError, .invalidImage)
        }
    }

    func testRejectsSourceAbovePixelLimitBeforeDecode() async throws {
        let source = try syntheticJPEG(width: 11, height: 10)
        let sanitizer = ImageSanitizer(
            limits: .init(maxLongSide: 1_600, maxSourcePixels: 100, maxOutputBytes: 10 * 1_024 * 1_024)
        )

        do {
            _ = try await sanitizer.sanitize(source)
            XCTFail("Source above the pixel limit must fail closed")
        } catch {
            XCTAssertEqual(error as? ImageSanitizerError, .sourceTooLarge)
        }
    }

    func testRejectsEncodedOutputAboveByteLimit() async throws {
        let source = try syntheticJPEG(width: 40, height: 60)
        let sanitizer = ImageSanitizer(
            limits: .init(maxLongSide: 1_600, maxSourcePixels: 25_000_000, maxOutputBytes: 1)
        )

        do {
            _ = try await sanitizer.sanitize(source)
            XCTFail("Encoded output above the byte limit must fail closed")
        } catch {
            XCTAssertEqual(error as? ImageSanitizerError, .outputTooLarge)
        }
    }

    func testCancellationDoesNotReturnBytes() async throws {
        let source = try syntheticJPEG(width: 40, height: 60)
        let sanitizer = ImageSanitizer()
        let task = Task<SanitizedImage, Error> {
            withUnsafeCurrentTask { currentTask in
                currentTask?.cancel()
            }
            return try await sanitizer.sanitize(source)
        }

        do {
            _ = try await task.value
            XCTFail("A cancelled task must not return sanitized bytes")
        } catch is CancellationError {
            // Expected: cancellation is preserved instead of being mapped to image failure.
        } catch {
            XCTFail("Expected CancellationError, received \(type(of: error))")
        }
    }
}

private extension ImageSanitizerTests {
    struct RGBAPixel {
        let red: UInt8
        let green: UInt8
        let blue: UInt8
        let alpha: UInt8
    }

    struct PixelBuffer {
        let width: Int
        let height: Int
        let pixels: [RGBAPixel]

        func index(x: Int, y: Int) -> Int {
            y * width + x
        }

        subscript(index: Int) -> RGBAPixel {
            pixels[index]
        }
    }

    enum CornerColor: CaseIterable {
        case red
        case green
        case blue
        case yellow

        var rgb: (red: Int, green: Int, blue: Int) {
            switch self {
            case .red:
                (230, 20, 20)
            case .green:
                (20, 220, 20)
            case .blue:
                (20, 20, 230)
            case .yellow:
                (230, 220, 20)
            }
        }
    }

    enum SyntheticImageError: Error {
        case couldNotCreateProvider
        case couldNotCreateImage
        case couldNotCreateDestination
        case couldNotFinalizeDestination
        case couldNotCreateContext
        case couldNotDecodeImage
        case missingProperties
    }

    func syntheticJPEG(
        width: Int,
        height: Int,
        orientation: UInt32 = 1,
        includesFakeGPS: Bool = false,
        usesFourCornerPattern: Bool = false
    ) throws -> Data {
        var rgba = [UInt8](repeating: 255, count: width * height * 4)
        for y in 0..<height {
            let isTopHalf = y < height / 2
            for x in 0..<width {
                let offset = (y * width + x) * 4
                let color: CornerColor
                if usesFourCornerPattern {
                    color = switch (isTopHalf, x < width / 2) {
                    case (true, true): .red
                    case (true, false): .green
                    case (false, true): .blue
                    case (false, false): .yellow
                    }
                } else {
                    color = isTopHalf ? .red : .blue
                }
                rgba[offset] = UInt8(color.rgb.red)
                rgba[offset + 1] = UInt8(color.rgb.green)
                rgba[offset + 2] = UInt8(color.rgb.blue)
            }
        }

        guard let provider = CGDataProvider(data: Data(rgba) as CFData) else {
            throw SyntheticImageError.couldNotCreateProvider
        }
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let image = CGImage(
            width: width,
            height: height,
            bitsPerComponent: 8,
            bitsPerPixel: 32,
            bytesPerRow: width * 4,
            space: colorSpace,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ) else {
            throw SyntheticImageError.couldNotCreateImage
        }

        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            output,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else {
            throw SyntheticImageError.couldNotCreateDestination
        }

        var properties: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: 1.0,
            kCGImagePropertyOrientation: orientation,
        ]
        if includesFakeGPS {
            properties[kCGImagePropertyGPSDictionary] = [
                kCGImagePropertyGPSLatitude: 0.0,
                kCGImagePropertyGPSLatitudeRef: "N",
                kCGImagePropertyGPSLongitude: 0.0,
                kCGImagePropertyGPSLongitudeRef: "E",
            ] as [CFString: Any]
        }
        CGImageDestinationAddImage(destination, image, properties as CFDictionary)
        guard CGImageDestinationFinalize(destination) else {
            throw SyntheticImageError.couldNotFinalizeDestination
        }
        return output as Data
    }

    func jpegSegment(marker: UInt8, payload: [UInt8]) -> [UInt8] {
        let length = payload.count + 2
        precondition(length <= Int(UInt16.max))
        return [
            0xFF,
            marker,
            UInt8((length >> 8) & 0xFF),
            UInt8(length & 0xFF),
        ] + payload
    }

    func imageProperties(_ data: Data) throws -> [CFString: Any] {
        guard
            let source = CGImageSourceCreateWithData(data as CFData, nil),
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil)
                as? [CFString: Any]
        else {
            throw SyntheticImageError.missingProperties
        }
        return properties
    }

    func decodedRGBPixels(_ data: Data) throws -> PixelBuffer {
        guard
            let source = CGImageSourceCreateWithData(data as CFData, nil),
            let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else {
            throw SyntheticImageError.couldNotDecodeImage
        }
        let width = image.width
        let height = image.height
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        let didDraw = rgba.withUnsafeMutableBytes { buffer -> Bool in
            guard let baseAddress = buffer.baseAddress else {
                return false
            }
            guard let context = CGContext(
                data: baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else {
                return false
            }
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard didDraw else {
            throw SyntheticImageError.couldNotCreateContext
        }

        let pixels = stride(from: 0, to: rgba.count, by: 4).map { offset in
            RGBAPixel(
                red: rgba[offset],
                green: rgba[offset + 1],
                blue: rgba[offset + 2],
                alpha: rgba[offset + 3]
            )
        }
        return PixelBuffer(width: width, height: height, pixels: pixels)
    }

    func decodedCornerColors(_ data: Data) throws -> [CornerColor] {
        let buffer = try decodedRGBPixels(data)
        let coordinates = [
            (buffer.width / 4, buffer.height / 4),
            (buffer.width * 3 / 4, buffer.height / 4),
            (buffer.width / 4, buffer.height * 3 / 4),
            (buffer.width * 3 / 4, buffer.height * 3 / 4),
        ]
        return coordinates.map { x, y in
            closestCornerColor(to: buffer[buffer.index(x: x, y: y)])
        }
    }

    func closestCornerColor(to pixel: RGBAPixel) -> CornerColor {
        CornerColor.allCases.min { left, right in
            colorDistance(from: pixel, to: left) < colorDistance(from: pixel, to: right)
        } ?? .red
    }

    func colorDistance(from pixel: RGBAPixel, to color: CornerColor) -> Int {
        let red = Int(pixel.red) - color.rgb.red
        let green = Int(pixel.green) - color.rgb.green
        let blue = Int(pixel.blue) - color.rgb.blue
        return red * red + green * green + blue * blue
    }
}
