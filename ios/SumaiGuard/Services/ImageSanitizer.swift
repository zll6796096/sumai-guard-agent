import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

struct SanitizedImage: Equatable, Sendable {
    let data: Data
    let pixelWidth: Int
    let pixelHeight: Int
    let mimeType: String
    let filename: String
}

enum ImageSanitizerError: Error, Equatable, Sendable {
    case invalidImage
    case sourceTooLarge
    case encodingFailed
    case outputTooLarge
}

enum JPEGMetadataStripper {
    private enum State {
        case marker
        case entropy
    }

    static func removeMetadata(from source: Data) -> Data? {
        let bytes = [UInt8](source)
        guard bytes.count >= 4, bytes[0] == 0xFF, bytes[1] == 0xD8 else {
            return nil
        }

        var sanitized: [UInt8] = [0xFF, 0xD8]
        sanitized.reserveCapacity(bytes.count)
        var cursor = 2
        var state = State.marker
        var sawScan = false

        while cursor < bytes.count {
            switch state {
            case .marker:
                let markerStart = cursor
                guard bytes[cursor] == 0xFF else {
                    return nil
                }
                while cursor < bytes.count, bytes[cursor] == 0xFF {
                    cursor += 1
                }
                guard cursor < bytes.count else {
                    return nil
                }

                let marker = bytes[cursor]
                cursor += 1
                switch marker {
                case 0xD9:
                    guard sawScan, cursor == bytes.count else {
                        return nil
                    }
                    sanitized.append(contentsOf: bytes[markerStart..<cursor])
                    return Data(sanitized)
                case 0x00, 0xD8, 0xD0...0xD7:
                    return nil
                case 0x01:
                    sanitized.append(contentsOf: bytes[markerStart..<cursor])
                default:
                    guard let segmentEnd = segmentEnd(in: bytes, lengthOffset: cursor) else {
                        return nil
                    }
                    if marker == 0xDA {
                        guard validScanHeader(in: bytes, lengthOffset: cursor) else {
                            return nil
                        }
                        sawScan = true
                        sanitized.append(contentsOf: bytes[markerStart..<segmentEnd])
                        state = .entropy
                    } else if !(0xE0...0xEF).contains(marker), marker != 0xFE {
                        sanitized.append(contentsOf: bytes[markerStart..<segmentEnd])
                    }
                    cursor = segmentEnd
                }

            case .entropy:
                guard bytes[cursor] == 0xFF else {
                    sanitized.append(bytes[cursor])
                    cursor += 1
                    continue
                }

                let markerStart = cursor
                while cursor < bytes.count, bytes[cursor] == 0xFF {
                    cursor += 1
                }
                guard cursor < bytes.count else {
                    return nil
                }

                let marker = bytes[cursor]
                if marker == 0x00 || (0xD0...0xD7).contains(marker) {
                    cursor += 1
                    sanitized.append(contentsOf: bytes[markerStart..<cursor])
                } else if marker == 0x01 {
                    cursor += 1
                    sanitized.append(contentsOf: bytes[markerStart..<cursor])
                } else if marker == 0xDC {
                    cursor += 1
                    guard let segmentEnd = segmentEnd(in: bytes, lengthOffset: cursor) else {
                        return nil
                    }
                    sanitized.append(contentsOf: bytes[markerStart..<segmentEnd])
                    cursor = segmentEnd
                } else {
                    cursor = markerStart
                    state = .marker
                }
            }
        }

        return nil
    }

    private static func segmentEnd(in bytes: [UInt8], lengthOffset: Int) -> Int? {
        guard lengthOffset <= bytes.count - 2 else {
            return nil
        }
        let segmentLength = Int(bytes[lengthOffset]) << 8 | Int(bytes[lengthOffset + 1])
        guard segmentLength >= 2, segmentLength <= bytes.count - lengthOffset else {
            return nil
        }
        return lengthOffset + segmentLength
    }

    private static func validScanHeader(in bytes: [UInt8], lengthOffset: Int) -> Bool {
        guard
            let end = segmentEnd(in: bytes, lengthOffset: lengthOffset),
            lengthOffset + 2 < end
        else {
            return false
        }
        let componentCount = Int(bytes[lengthOffset + 2])
        return componentCount > 0 && end - lengthOffset == 6 + 2 * componentCount
    }
}

actor ImageSanitizer {
    static let maxLongSide = 1_600
    static let maxSourcePixels = 25_000_000
    static let maxBytes = 10 * 1_024 * 1_024

    struct Limits: Equatable, Sendable {
        let maxLongSide: Int
        let maxSourcePixels: Int
        let maxOutputBytes: Int

        static let production = Limits(
            maxLongSide: ImageSanitizer.maxLongSide,
            maxSourcePixels: ImageSanitizer.maxSourcePixels,
            maxOutputBytes: ImageSanitizer.maxBytes
        )

        init(maxLongSide: Int, maxSourcePixels: Int, maxOutputBytes: Int) {
            precondition(maxLongSide > 0)
            precondition(maxSourcePixels > 0)
            precondition(maxOutputBytes > 0)
            self.maxLongSide = maxLongSide
            self.maxSourcePixels = maxSourcePixels
            self.maxOutputBytes = maxOutputBytes
        }
    }

    private let limits: Limits

    init(limits: Limits = .production) {
        self.limits = limits
    }

    func sanitize(_ sourceData: Data) throws -> SanitizedImage {
        try Task.checkCancellation()
        guard !sourceData.isEmpty else {
            throw ImageSanitizerError.invalidImage
        }

        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard
            let source = CGImageSourceCreateWithData(sourceData as CFData, sourceOptions),
            CGImageSourceGetCount(source) > 0,
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, sourceOptions)
                as? [CFString: Any],
            let sourceWidth = integerProperty(properties[kCGImagePropertyPixelWidth]),
            let sourceHeight = integerProperty(properties[kCGImagePropertyPixelHeight]),
            sourceWidth > 0,
            sourceHeight > 0
        else {
            throw ImageSanitizerError.invalidImage
        }

        guard sourceWidth <= limits.maxSourcePixels / sourceHeight else {
            throw ImageSanitizerError.sourceTooLarge
        }
        try Task.checkCancellation()

        let thumbnailOptions: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: limits.maxLongSide,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let normalized = CGImageSourceCreateThumbnailAtIndex(
            source,
            0,
            thumbnailOptions as CFDictionary
        ) else {
            throw ImageSanitizerError.invalidImage
        }
        try Task.checkCancellation()

        guard
            normalized.width > 0,
            normalized.height > 0,
            max(normalized.width, normalized.height) <= limits.maxLongSide,
            let freshPixels = redrawIntoFreshRGBBuffer(normalized)
        else {
            throw ImageSanitizerError.invalidImage
        }
        try Task.checkCancellation()

        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            output,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else {
            throw ImageSanitizerError.encodingFailed
        }
        let destinationProperties = [
            kCGImageDestinationLossyCompressionQuality: 0.86,
        ] as CFDictionary
        CGImageDestinationAddImage(destination, freshPixels, destinationProperties)
        guard CGImageDestinationFinalize(destination) else {
            throw ImageSanitizerError.encodingFailed
        }
        try Task.checkCancellation()

        guard
            let encoded = JPEGMetadataStripper.removeMetadata(from: output as Data),
            !encoded.isEmpty
        else {
            throw ImageSanitizerError.encodingFailed
        }
        guard encoded.count <= limits.maxOutputBytes else {
            throw ImageSanitizerError.outputTooLarge
        }
        try Task.checkCancellation()

        return SanitizedImage(
            data: encoded,
            pixelWidth: freshPixels.width,
            pixelHeight: freshPixels.height,
            mimeType: "image/jpeg",
            filename: "sumaiguard-upload.jpg"
        )
    }
}

private extension ImageSanitizer {
    func integerProperty(_ value: Any?) -> Int? {
        (value as? NSNumber)?.intValue
    }

    func redrawIntoFreshRGBBuffer(_ source: CGImage) -> CGImage? {
        let width = source.width
        let height = source.height
        let bytesPerPixel = 4
        guard width <= Int.max / bytesPerPixel else {
            return nil
        }

        let bitmapInfo = CGBitmapInfo.byteOrder32Big.rawValue
            | CGImageAlphaInfo.noneSkipLast.rawValue
        guard let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * bytesPerPixel,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: bitmapInfo
        ) else {
            return nil
        }

        context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.interpolationQuality = .high
        context.draw(source, in: CGRect(x: 0, y: 0, width: width, height: height))
        return context.makeImage()
    }

}
