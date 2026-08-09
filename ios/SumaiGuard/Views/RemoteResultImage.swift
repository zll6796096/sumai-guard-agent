import CoreGraphics
import CoreImage
import Foundation
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

enum ResultImageError: Error, Equatable, Sendable {
    case invalidBase64
    case encodedDataTooLarge
    case decodedDataTooLarge
    case unsupportedImage
    case sourceTooLarge
    case decodeFailed
}

struct ResultImageLimits: Equatable, Sendable {
    let maxBase64Characters: Int
    let maxDecodedBytes: Int
    let maxSourcePixels: Int
    let maxLongSide: Int

    static let production = ResultImageLimits(
        maxBase64Characters: 14_000_000,
        maxDecodedBytes: 10 * 1_024 * 1_024,
        maxSourcePixels: 25_000_000,
        maxLongSide: 1_600
    )

    init(
        maxBase64Characters: Int,
        maxDecodedBytes: Int,
        maxSourcePixels: Int,
        maxLongSide: Int
    ) {
        precondition(maxBase64Characters > 0)
        precondition(maxDecodedBytes > 0)
        precondition(maxSourcePixels > 0)
        precondition(maxLongSide > 0)
        self.maxBase64Characters = maxBase64Characters
        self.maxDecodedBytes = maxDecodedBytes
        self.maxSourcePixels = maxSourcePixels
        self.maxLongSide = maxLongSide
    }
}

protocol ResultImageDecoding: Sendable {
    func decode(_ base64: String) async throws -> CGImage
}

protocol ResultImageSourceCreating: Sendable {
    func makeSource(from data: Data) async -> ResultImageSourceHandle?
}

final class ResultImageSourceHandle: @unchecked Sendable {
    let source: CGImageSource

    init(source: CGImageSource) {
        self.source = source
    }
}

struct SystemResultImageSourceFactory: ResultImageSourceCreating {
    func makeSource(from data: Data) async -> ResultImageSourceHandle? {
        let options = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, options) else {
            return nil
        }
        return ResultImageSourceHandle(source: source)
    }
}

private enum ResultImageContainer {
    case jpeg(data: Data, orientation: Int32)
    case png(data: Data)

    var data: Data {
        switch self {
        case let .jpeg(data, _), let .png(data): data
        }
    }

    var typeIdentifier: String {
        switch self {
        case .jpeg: UTType.jpeg.identifier
        case .png: UTType.png.identifier
        }
    }

    var explicitOrientation: Int32? {
        switch self {
        case let .jpeg(_, orientation): orientation
        case .png: nil
        }
    }
}

enum JPEGExifOrientationParser {
    private enum State {
        case marker
        case entropy
    }

    private enum ByteOrder {
        case little
        case big
    }

    private static let exifPrefix = [UInt8]("Exif\0\0".utf8)
    private static let maxExifPayloadBytes = 16 * 1_024

    static func orientation(in data: Data) -> Int32? {
        let bytes = [UInt8](data)
        guard bytes.count >= 4, bytes[0] == 0xFF, bytes[1] == 0xD8 else {
            return nil
        }

        var cursor = 2
        var state = State.marker
        var sawScan = false
        var sawExif = false
        var orientation: Int32 = 1

        while cursor < bytes.count {
            switch state {
            case .marker:
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
                    return sawScan && cursor == bytes.count ? orientation : nil
                case 0x00, 0xD8, 0xD0...0xD7:
                    return nil
                case 0x01:
                    continue
                default:
                    guard let segmentEnd = segmentEnd(in: bytes, lengthOffset: cursor) else {
                        return nil
                    }
                    let payloadStart = cursor + 2
                    if marker == 0xE1,
                       segmentEnd - payloadStart >= exifPrefix.count,
                       Array(bytes[payloadStart..<(payloadStart + exifPrefix.count)]) == exifPrefix {
                        let payloadLength = segmentEnd - payloadStart
                        guard
                            !sawExif,
                            !sawScan,
                            payloadLength <= maxExifPayloadBytes,
                            let parsed = tiffOrientation(
                                in: Array(bytes[payloadStart..<segmentEnd])
                            )
                        else {
                            return nil
                        }
                        sawExif = true
                        orientation = parsed
                    }
                    if marker == 0xDA {
                        guard validScanHeader(in: bytes, lengthOffset: cursor) else {
                            return nil
                        }
                        sawScan = true
                        state = .entropy
                    }
                    cursor = segmentEnd
                }

            case .entropy:
                guard bytes[cursor] == 0xFF else {
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
                if marker == 0x00 || marker == 0x01 || (0xD0...0xD7).contains(marker) {
                    cursor += 1
                } else if marker == 0xDC {
                    cursor += 1
                    guard let end = segmentEnd(in: bytes, lengthOffset: cursor) else {
                        return nil
                    }
                    cursor = end
                } else {
                    cursor = markerStart
                    state = .marker
                }
            }
        }
        return nil
    }

    private static func tiffOrientation(in payload: [UInt8]) -> Int32? {
        guard payload.count >= exifPrefix.count + 8,
              Array(payload.prefix(exifPrefix.count)) == exifPrefix else {
            return nil
        }
        let tiff = Array(payload.dropFirst(exifPrefix.count))
        let byteOrder: ByteOrder
        switch (tiff[0], tiff[1]) {
        case (0x49, 0x49): byteOrder = .little
        case (0x4D, 0x4D): byteOrder = .big
        default: return nil
        }
        guard readUInt16(tiff, at: 2, order: byteOrder) == 42,
              let rawIFDOffset = readUInt32(tiff, at: 4, order: byteOrder) else {
            return nil
        }
        let ifdOffset = Int(rawIFDOffset)
        guard ifdOffset >= 8,
              let entryCountValue = readUInt16(tiff, at: ifdOffset, order: byteOrder) else {
            return nil
        }
        let entryCount = Int(entryCountValue)
        let entriesStart = ifdOffset + 2
        guard entriesStart <= tiff.count - 4,
              entryCount <= (tiff.count - entriesStart - 4) / 12 else {
            return nil
        }

        var foundOrientation: Int32?
        for index in 0..<entryCount {
            let entryOffset = entriesStart + index * 12
            guard
                let tag = readUInt16(tiff, at: entryOffset, order: byteOrder),
                let type = readUInt16(tiff, at: entryOffset + 2, order: byteOrder),
                let count = readUInt32(tiff, at: entryOffset + 4, order: byteOrder)
            else {
                return nil
            }
            if tag == 0x0112 {
                guard
                    foundOrientation == nil,
                    type == 3,
                    count == 1,
                    let rawOrientation = readUInt16(
                        tiff,
                        at: entryOffset + 8,
                        order: byteOrder
                    ),
                    (1...8).contains(rawOrientation)
                else {
                    return nil
                }
                foundOrientation = Int32(rawOrientation)
            }
        }

        let nextIFDOffset = entriesStart + entryCount * 12
        guard readUInt32(tiff, at: nextIFDOffset, order: byteOrder) == 0 else {
            return nil
        }
        return foundOrientation ?? 1
    }

    private static func readUInt16(
        _ bytes: [UInt8],
        at offset: Int,
        order: ByteOrder
    ) -> UInt16? {
        guard offset >= 0, offset <= bytes.count - 2 else {
            return nil
        }
        switch order {
        case .little:
            return UInt16(bytes[offset]) | UInt16(bytes[offset + 1]) << 8
        case .big:
            return UInt16(bytes[offset]) << 8 | UInt16(bytes[offset + 1])
        }
    }

    private static func readUInt32(
        _ bytes: [UInt8],
        at offset: Int,
        order: ByteOrder
    ) -> UInt32? {
        guard offset >= 0, offset <= bytes.count - 4 else {
            return nil
        }
        switch order {
        case .little:
            return UInt32(bytes[offset])
                | UInt32(bytes[offset + 1]) << 8
                | UInt32(bytes[offset + 2]) << 16
                | UInt32(bytes[offset + 3]) << 24
        case .big:
            return UInt32(bytes[offset]) << 24
                | UInt32(bytes[offset + 1]) << 16
                | UInt32(bytes[offset + 2]) << 8
                | UInt32(bytes[offset + 3])
        }
    }

    private static func segmentEnd(in bytes: [UInt8], lengthOffset: Int) -> Int? {
        guard lengthOffset >= 0, lengthOffset <= bytes.count - 2 else {
            return nil
        }
        let length = Int(bytes[lengthOffset]) << 8 | Int(bytes[lengthOffset + 1])
        guard length >= 2, length <= bytes.count - lengthOffset else {
            return nil
        }
        return lengthOffset + length
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

actor ResultImageDecoder: ResultImageDecoding {
    private let limits: ResultImageLimits
    private let sourceFactory: any ResultImageSourceCreating

    init(
        limits: ResultImageLimits = .production,
        sourceFactory: any ResultImageSourceCreating = SystemResultImageSourceFactory()
    ) {
        self.limits = limits
        self.sourceFactory = sourceFactory
    }

    func decode(_ base64: String) async throws -> CGImage {
        try Task.checkCancellation()

        guard
            !base64.isEmpty,
            base64.utf8.count <= limits.maxBase64Characters
        else {
            if base64.isEmpty {
                throw ResultImageError.invalidBase64
            }
            throw ResultImageError.encodedDataTooLarge
        }
        guard base64.unicodeScalars.allSatisfy({ $0.isASCII && !$0.properties.isWhitespace }) else {
            throw ResultImageError.invalidBase64
        }
        guard let decodedData = Data(base64Encoded: base64), !decodedData.isEmpty else {
            throw ResultImageError.invalidBase64
        }
        guard decodedData.base64EncodedString() == base64 else {
            throw ResultImageError.invalidBase64
        }
        guard decodedData.count <= limits.maxDecodedBytes else {
            throw ResultImageError.decodedDataTooLarge
        }
        try Task.checkCancellation()

        let container: ResultImageContainer
        if decodedData.starts(with: Self.pngSignature) {
            guard let canonicalPNG = try Self.canonicalPNGData(decodedData) else {
                throw ResultImageError.unsupportedImage
            }
            container = .png(data: canonicalPNG)
        } else if decodedData.starts(with: [0xFF, 0xD8]) {
            guard
                let stripped = JPEGMetadataStripper.removeMetadata(from: decodedData),
                let orientation = JPEGExifOrientationParser.orientation(in: decodedData)
            else {
                throw ResultImageError.unsupportedImage
            }
            container = .jpeg(
                data: stripped,
                orientation: orientation
            )
        } else {
            throw ResultImageError.unsupportedImage
        }
        let data = container.data

        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard
            let sourceHandle = await sourceFactory.makeSource(from: data),
            !Task.isCancelled,
            CGImageSourceGetCount(sourceHandle.source) == 1,
            let sourceType = CGImageSourceGetType(sourceHandle.source)
        else {
            try Task.checkCancellation()
            throw ResultImageError.unsupportedImage
        }
        let source = sourceHandle.source
        guard sourceType as String == container.typeIdentifier else {
            throw ResultImageError.unsupportedImage
        }
        guard
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, sourceOptions)
                as? [CFString: Any],
            let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
            let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
            width > 0,
            height > 0
        else {
            throw ResultImageError.decodeFailed
        }
        guard width <= limits.maxSourcePixels / height else {
            throw ResultImageError.sourceTooLarge
        }
        try Task.checkCancellation()

        let thumbnailOptions: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: false,
            kCGImageSourceThumbnailMaxPixelSize: limits.maxLongSide,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let decoded = CGImageSourceCreateThumbnailAtIndex(
            source,
            0,
            thumbnailOptions as CFDictionary
        ) else {
            throw ResultImageError.decodeFailed
        }
        try Task.checkCancellation()

        let oriented = try Self.applyOrientation(
            decoded,
            exifOrientation: container.explicitOrientation
                ?? Self.imageOrientation(in: properties)
        )
        let freshImage = try Self.redraw(oriented)
        try Task.checkCancellation()
        return freshImage
    }

    private static func redraw(_ source: CGImage) throws -> CGImage {
        let width = source.width
        let height = source.height
        let bytesPerPixel = 4
        guard
            width > 0,
            height > 0,
            width <= Int.max / bytesPerPixel,
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * bytesPerPixel,
                space: colorSpace,
                bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue
                    | CGImageAlphaInfo.premultipliedLast.rawValue
            )
        else {
            throw ResultImageError.decodeFailed
        }

        context.interpolationQuality = .high
        context.draw(source, in: CGRect(x: 0, y: 0, width: width, height: height))
        guard let image = context.makeImage() else {
            throw ResultImageError.decodeFailed
        }
        return image
    }

    private static func imageOrientation(in properties: [CFString: Any]) -> Int32 {
        guard
            let orientation = properties[kCGImagePropertyOrientation] as? NSNumber,
            (1...8).contains(orientation.intValue)
        else {
            return 1
        }
        return orientation.int32Value
    }

    private static func applyOrientation(
        _ source: CGImage,
        exifOrientation: Int32
    ) throws -> CGImage {
        guard exifOrientation != 1 else {
            return source
        }
        let input = CIImage(cgImage: source)
        let oriented = input.oriented(forExifOrientation: exifOrientation)
        let bounds = oriented.extent.integral
        guard
            !bounds.isEmpty,
            !bounds.isInfinite,
            let image = CIContext(options: [
                .cacheIntermediates: false,
                .useSoftwareRenderer: true,
            ]).createCGImage(oriented, from: bounds)
        else {
            throw ResultImageError.decodeFailed
        }
        return image
    }

    private static let pngSignature = Data([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
    ])

    private struct PNGHeader {
        let bitDepth: UInt8
        let colorType: UInt8
    }

    private static let maxPNGChunks = 256
    private static let maxPNGIDATChunks = 128
    private static let maxPNGAncillaryInputBytes = 256 * 1_024

    private static func canonicalPNGData(_ data: Data) throws -> Data? {
        guard data.starts(with: pngSignature) else {
            return nil
        }
        let ihdr = [UInt8]("IHDR".utf8)
        let plte = [UInt8]("PLTE".utf8)
        let idat = [UInt8]("IDAT".utf8)
        let iend = [UInt8]("IEND".utf8)
        let trns = [UInt8]("tRNS".utf8)
        let rejectedCompressedMetadata = [
            [UInt8]("iCCP".utf8),
            [UInt8]("zTXt".utf8),
            [UInt8]("iTXt".utf8),
        ]
        var cursor = pngSignature.count
        var header: PNGHeader?
        var paletteEntries: Int?
        var sawIHDR = false
        var sawPLTE = false
        var sawTRNS = false
        var sawIDAT = false
        var endedIDATSequence = false
        var chunkCount = 0
        var idatCount = 0
        var ancillaryInputBytes = 0
        var canonical = pngSignature

        while cursor <= data.count {
            try Task.checkCancellation()
            chunkCount += 1
            guard chunkCount <= maxPNGChunks else {
                return nil
            }
            let bytesRemaining = data.count - cursor
            guard bytesRemaining >= 12,
                  let length = uint32Length(in: data, at: cursor),
                  length <= bytesRemaining - 12 else {
                return nil
            }
            let typeStart = cursor + 4
            let typeEnd = typeStart + 4
            let payloadStart = typeEnd
            let payloadEnd = payloadStart + length
            let crcEnd = payloadEnd + 4
            let type = Array(data[typeStart..<typeEnd])
            guard
                type.allSatisfy(Self.isPNGChunkTypeByte),
                (65...90).contains(type[2]),
                let storedCRC = uint32(in: data, at: payloadEnd),
                storedCRC == (try pngCRC32(data[typeStart..<payloadEnd]))
            else {
                return nil
            }
            let isCritical = (65...90).contains(type[0])
            let isKnownCritical = type == ihdr || type == plte
                || type == idat || type == iend
            guard !isCritical || isKnownCritical else {
                return nil
            }
            if !isCritical {
                let chunkBytes = length + 12
                guard chunkBytes <= maxPNGAncillaryInputBytes - ancillaryInputBytes else {
                    return nil
                }
                ancillaryInputBytes += chunkBytes
                guard !rejectedCompressedMetadata.contains(type) else {
                    return nil
                }
            }

            if !sawIHDR {
                guard
                    type == ihdr,
                    length == 13,
                    let parsedHeader = validPNGHeader(data[payloadStart..<payloadEnd])
                else {
                    return nil
                }
                header = parsedHeader
                sawIHDR = true
            } else if type == ihdr {
                return nil
            }

            var keepChunk = isCritical
            if type == plte {
                guard
                    !sawPLTE,
                    !sawTRNS,
                    !sawIDAT,
                    header?.colorType != 0,
                    header?.colorType != 4,
                    length > 0,
                    length.isMultiple(of: 3),
                    length <= 768
                else {
                    return nil
                }
                let entries = length / 3
                if let header, header.colorType == 3,
                   entries > 1 << Int(header.bitDepth) {
                    return nil
                }
                sawPLTE = true
                paletteEntries = entries
            } else if type == trns {
                guard
                    !sawTRNS,
                    !sawIDAT,
                    let header,
                    validTransparencyChunk(
                        length: length,
                        header: header,
                        sawPLTE: sawPLTE,
                        paletteEntries: paletteEntries
                    )
                else {
                    return nil
                }
                sawTRNS = true
                keepChunk = true
            } else if type == idat {
                idatCount += 1
                guard !endedIDATSequence, idatCount <= maxPNGIDATChunks else {
                    return nil
                }
                sawIDAT = true
            } else if sawIDAT, type != iend {
                endedIDATSequence = true
            } else if type == iend {
                guard
                    length == 0,
                    sawIDAT,
                    header?.colorType != 3 || sawPLTE,
                    crcEnd == data.count
                else {
                    return nil
                }
                canonical.append(contentsOf: data[cursor..<crcEnd])
                return canonical
            }
            if keepChunk {
                canonical.append(contentsOf: data[cursor..<crcEnd])
            }
            cursor = crcEnd
        }
        return nil
    }

    private static func validPNGHeader(_ payload: Data.SubSequence) -> PNGHeader? {
        guard payload.count == 13 else {
            return nil
        }
        let bytes = Array(payload)
        let width = UInt32(bytes[0]) << 24
            | UInt32(bytes[1]) << 16
            | UInt32(bytes[2]) << 8
            | UInt32(bytes[3])
        let height = UInt32(bytes[4]) << 24
            | UInt32(bytes[5]) << 16
            | UInt32(bytes[6]) << 8
            | UInt32(bytes[7])
        let bitDepth = bytes[8]
        let colorType = bytes[9]
        let validBitDepths: [UInt8]
        switch colorType {
        case 0: validBitDepths = [1, 2, 4, 8, 16]
        case 2: validBitDepths = [8, 16]
        case 3: validBitDepths = [1, 2, 4, 8]
        case 4, 6: validBitDepths = [8, 16]
        default: return nil
        }
        guard
            width > 0,
            height > 0,
            validBitDepths.contains(bitDepth),
            bytes[10] == 0,
            bytes[11] == 0,
            bytes[12] <= 1
        else {
            return nil
        }
        return PNGHeader(bitDepth: bitDepth, colorType: colorType)
    }

    private static func validTransparencyChunk(
        length: Int,
        header: PNGHeader,
        sawPLTE: Bool,
        paletteEntries: Int?
    ) -> Bool {
        switch header.colorType {
        case 0:
            return !sawPLTE && length == 2
        case 2:
            return length == 6
        case 3:
            return sawPLTE
                && length > 0
                && length <= (paletteEntries ?? 0)
        case 4, 6:
            return false
        default:
            return false
        }
    }

    private static func uint32Length(in data: Data, at offset: Int) -> Int? {
        guard offset >= 0, offset <= data.count - 4 else {
            return nil
        }
        return Int(data[offset]) << 24
            | Int(data[offset + 1]) << 16
            | Int(data[offset + 2]) << 8
            | Int(data[offset + 3])
    }

    private static func uint32(in data: Data, at offset: Int) -> UInt32? {
        guard offset >= 0, offset <= data.count - 4 else {
            return nil
        }
        return UInt32(data[offset]) << 24
            | UInt32(data[offset + 1]) << 16
            | UInt32(data[offset + 2]) << 8
            | UInt32(data[offset + 3])
    }

    private static let pngCRCTable: [UInt32] = (0..<256).map { value in
        var crc = UInt32(value)
        for _ in 0..<8 {
            crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xEDB8_8320 : crc >> 1
        }
        return crc
    }

    private static func pngCRC32(_ bytes: Data.SubSequence) throws -> UInt32 {
        var crc = UInt32.max
        for (index, byte) in bytes.enumerated() {
            if index.isMultiple(of: 64 * 1_024) {
                try Task.checkCancellation()
            }
            let tableIndex = Int((crc ^ UInt32(byte)) & 0xFF)
            crc = pngCRCTable[tableIndex] ^ (crc >> 8)
        }
        return crc ^ UInt32.max
    }

    private static func isPNGChunkTypeByte(_ byte: UInt8) -> Bool {
        (65...90).contains(byte) || (97...122).contains(byte)
    }
}

@MainActor
final class RemoteResultImageModel: ObservableObject {
    @Published private(set) var image: CGImage?
    @Published private(set) var isUnavailable = false
    @Published private(set) var isLoading = false

    private let decoder: any ResultImageDecoding
    private var currentLoadID = UUID()

    init(decoder: any ResultImageDecoding = ResultImageDecoder()) {
        self.decoder = decoder
    }

    func load(_ base64: String) async {
        let loadID = UUID()
        currentLoadID = loadID
        image = nil
        isUnavailable = false
        isLoading = true

        do {
            let decoded = try await decoder.decode(base64)
            guard currentLoadID == loadID else {
                return
            }
            guard !Task.isCancelled else {
                clearIfCurrent(loadID)
                return
            }
            image = decoded
            isUnavailable = false
            isLoading = false
        } catch {
            guard currentLoadID == loadID else {
                return
            }
            if error is CancellationError || Task.isCancelled {
                clearIfCurrent(loadID)
            } else {
                image = nil
                isUnavailable = true
                isLoading = false
            }
        }
    }

    func invalidate() {
        currentLoadID = UUID()
        image = nil
        isUnavailable = false
        isLoading = false
    }

    private func clearIfCurrent(_ loadID: UUID) {
        guard currentLoadID == loadID else {
            return
        }
        currentLoadID = UUID()
        image = nil
        isUnavailable = false
        isLoading = false
    }
}

struct RemoteResultImage: View {
    let base64: String
    let accessibilityLabel: String
    let identifier: String

    @StateObject private var model: RemoteResultImageModel

    init(
        base64: String,
        accessibilityLabel: String,
        identifier: String,
        decoder: any ResultImageDecoding = ResultImageDecoder()
    ) {
        self.base64 = base64
        self.accessibilityLabel = accessibilityLabel
        self.identifier = identifier
        _model = StateObject(wrappedValue: RemoteResultImageModel(decoder: decoder))
    }

    var body: some View {
        Group {
            if let image = model.image {
                Image(image, scale: 1, label: Text(accessibilityLabel))
                    .resizable()
                    .scaledToFit()
            } else if model.isUnavailable {
                placeholder(
                    systemImage: "photo",
                    text: "画像を安全に表示できませんでした"
                )
            } else {
                placeholder(
                    systemImage: "photo",
                    text: "画像を準備しています"
                )
                    .overlay { ProgressView().accessibilityHidden(true) }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityIdentifier(identifier)
        .task(id: base64) {
            await model.load(base64)
        }
        .onDisappear {
            model.invalidate()
        }
    }

    private func placeholder(systemImage: String, text: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: systemImage)
                .font(.title)
                .accessibilityHidden(true)
            Text(text)
                .font(.callout)
                .multilineTextAlignment(.center)
        }
        .foregroundStyle(.secondary)
        .padding(20)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(text)
    }
}
