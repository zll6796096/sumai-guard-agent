import CoreText
import Foundation
import PDFKit
import UIKit

struct SafetyPDFDocument: Equatable, Sendable {
    struct VisibleRisk: Equatable, Sendable {
        let label: String
        let evidence: String
        let basis: String
    }

    struct Action: Equatable, Sendable {
        let title: String
        let description: String
        let why: String
        let disclaimer: String
        let costLabel: String?
    }

    static let approvedDisclaimer = "このPDFは、写真1枚に写っている範囲だけをもとにした一般的な安全上の注意と相談の目安です。\n写真に写っていない危険や、AIが見落とした危険がある可能性があります。\n医療・介護認定・保険・法令適合・施工可否・見積もり、その他の専門判断を行うものではありません。\n実際の状況を現地で確認し、必要に応じてケアマネジャー、福祉用具専門相談員、施工の専門家へ相談してください。\nこのPOCは、アップロードした写真や生成したPDFを保存しません。"

    let title: String
    let visibleRisks: [VisibleRisk]
    let familyActions: [Action]
    let careManagerActions: [Action]
    let contractorActions: [Action]
    let approvedDisclaimer: String

    private init(
        title: String,
        visibleRisks: [VisibleRisk],
        familyActions: [Action],
        careManagerActions: [Action],
        contractorActions: [Action]
    ) throws {
        guard
            !visibleRisks.isEmpty,
            !(familyActions + careManagerActions + contractorActions).isEmpty,
            visibleRisks.count <= PresentationResponseValidator.maxFindings,
            familyActions.count <= PresentationResponseValidator.maxActionsPerTier,
            careManagerActions.count <= PresentationResponseValidator.maxActionsPerTier,
            contractorActions.count <= PresentationResponseValidator.maxActionsPerTier
        else {
            throw SafetyPDFError.invalidDocument
        }

        let fixedDisclaimer = Self.approvedDisclaimer
        let inputFields = [title]
            + visibleRisks.flatMap { [$0.label, $0.evidence, $0.basis] }
            + (familyActions + careManagerActions + contractorActions).flatMap {
                [$0.title, $0.description, $0.why, $0.disclaimer] + [$0.costLabel].compactMap { $0 }
            }
        let fields = inputFields + [fixedDisclaimer]
        guard
            inputFields.allSatisfy(Self.isSafePDFInput),
            PresentationResponseValidator.isSafeDisplayText(fixedDisclaimer),
            fields.reduce(into: 0, { $0 += $1.utf8.count }) <= PresentationResponseValidator.maxTotalDisplayUTF8Bytes
        else {
            throw SafetyPDFError.invalidDocument
        }

        self.title = title
        self.visibleRisks = visibleRisks
        self.familyActions = familyActions
        self.careManagerActions = careManagerActions
        self.contractorActions = contractorActions
        approvedDisclaimer = fixedDisclaimer
    }

    init(validatedResponse: ValidatedPresentationResponse) throws {
        let response = validatedResponse.response
        guard
            !response.isNotApplicable,
            !response.findings.isEmpty,
            !response.actionPlan.isEmpty
        else {
            throw SafetyPDFError.invalidDocument
        }

        try self.init(
            title: "実家あんしんチェック 安全のためにできること",
            visibleRisks: response.findings.map {
                VisibleRisk(
                    label: $0.labelJA,
                    evidence: $0.evidenceJA,
                    basis: $0.basisSummaryJA
                )
            },
            familyActions: response.actionPlan.familyNoCost.map(Self.action),
            careManagerActions: response.actionPlan.careManagerPurchase.map(Self.action),
            contractorActions: response.actionPlan.contractorConstruction.map(Self.action)
        )
    }

    private static func action(_ item: ActionItem) -> Action {
        let costLabel: String = switch item.costLevel {
        case .zero: "費用の目安：費用なし"
        case .low: "費用の目安：低め"
        case .medium: "費用の目安：中程度"
        case .high: "費用の目安：高め"
        }
        return Action(
            title: item.titleJA,
            description: item.descriptionJA,
            why: item.whyJA,
            disclaimer: item.disclaimerJA,
            costLabel: costLabel
        )
    }

    private static func isSafePDFInput(_ text: String) -> Bool {
        PresentationResponseValidator.isSafeDisplayText(text)
            && text.unicodeScalars.allSatisfy {
                $0.value >= 0x20
                    && $0.properties.generalCategory != .lineSeparator
                    && $0.properties.generalCategory != .paragraphSeparator
            }
    }
}

enum SafetyPDFError: Error, Equatable, Sendable {
    case invalidDocument
    case renderingFailed
}

protocol SafetyPDFRendering: Sendable {
    func render(_ document: SafetyPDFDocument) async throws -> Data
}

struct SafetyPDFRenderer: SafetyPDFRendering {
    private static let pageBounds = CGRect(x: 0, y: 0, width: 595.2, height: 841.8)
    private static let pageMargin: CGFloat = 44
    private static let maximumPageCount = 32

    func render(_ document: SafetyPDFDocument) async throws -> Data {
        try Task.checkCancellation()
        let content = Self.attributedContent(for: document)
        let framesetter = CTFramesetterCreateWithAttributedString(content)
        let format = UIGraphicsPDFRendererFormat()
        format.documentInfo = [
            kCGPDFContextTitle as String: "実家あんしんチェック 安全のためにできること",
            kCGPDFContextCreator as String: "SumaiGuard",
        ]
        let renderer = UIGraphicsPDFRenderer(bounds: Self.pageBounds, format: format)
        var cancelled = false
        var stalled = false
        var exceededPageLimit = false
        let data = renderer.pdfData { rendererContext in
            var location = 0
            var pageCount = 0
            while location < CFAttributedStringGetLength(content) {
                if Task.isCancelled {
                    cancelled = true
                    return
                }
                guard pageCount < Self.maximumPageCount else {
                    exceededPageLimit = true
                    return
                }
                rendererContext.beginPage()
                pageCount += 1
                let context = rendererContext.cgContext
                context.saveGState()
                context.textMatrix = .identity
                context.translateBy(x: 0, y: Self.pageBounds.height)
                context.scaleBy(x: 1, y: -1)
                let textBounds = Self.pageBounds.insetBy(dx: Self.pageMargin, dy: Self.pageMargin)
                let path = CGPath(rect: textBounds, transform: nil)
                let frame = CTFramesetterCreateFrame(
                    framesetter,
                    CFRange(location: location, length: 0),
                    path,
                    nil
                )
                CTFrameDraw(frame, context)
                context.restoreGState()

                let visibleRange = CTFrameGetVisibleStringRange(frame)
                guard visibleRange.length > 0 else {
                    stalled = true
                    return
                }
                location += visibleRange.length
            }
        }
        if cancelled {
            throw CancellationError()
        }
        try Task.checkCancellation()
        guard !stalled, !exceededPageLimit, !data.isEmpty else {
            throw SafetyPDFError.renderingFailed
        }
        let normalizedData = try Self.normalizedMetadata(in: data)
        try Task.checkCancellation()
        return normalizedData
    }

    private static func normalizedMetadata(in data: Data) throws -> Data {
        let approvedInfo = approvedInfoDictionary()
        guard
            let dictionaryRange = infoDictionaryRange(in: data),
            approvedInfo.count <= dictionaryRange.count
        else {
            throw SafetyPDFError.renderingFailed
        }
        var normalizedData = data
        let padding = Data(repeating: 0x20, count: dictionaryRange.count - approvedInfo.count)
        normalizedData.replaceSubrange(dictionaryRange, with: approvedInfo + padding)
        guard
            hasOnlyApprovedMetadata(normalizedData)
        else {
            throw SafetyPDFError.renderingFailed
        }
        return normalizedData
    }

    private static func approvedInfoDictionary() -> Data {
        var titleBytes = [UInt8](arrayLiteral: 0xFE, 0xFF)
        for codeUnit in "実家あんしんチェック 安全のためにできること".utf16 {
            titleBytes.append(UInt8(codeUnit >> 8))
            titleBytes.append(UInt8(codeUnit & 0xFF))
        }
        let titleHex = titleBytes.map { String(format: "%02X", $0) }.joined()
        return Data("<< /Title <\(titleHex)> /Creator (SumaiGuard) >>".utf8)
    }

    private static func infoDictionaryRange(in data: Data) -> Range<Data.Index>? {
        let bytes = [UInt8](data)
        guard let startXRefMarker = lastRange(of: Array("startxref".utf8), in: bytes) else {
            return nil
        }
        var startXRefCursor = startXRefMarker.upperBound
        guard
            let xrefOffset = readInteger(in: bytes, index: &startXRefCursor),
            xrefOffset >= 0,
            xrefOffset < bytes.count
        else {
            return nil
        }

        var xrefIndex = xrefOffset
        guard readToken(in: bytes, index: &xrefIndex) == Array("xref".utf8) else {
            return nil
        }
        guard let trailerIndex = findToken(Array("trailer".utf8), in: bytes, from: xrefIndex) else {
            return nil
        }
        var trailerCursor = trailerIndex + "trailer".utf8.count
        guard
            let infoIndex = findToken(Array("/Info".utf8), in: bytes, from: trailerCursor),
            infoIndex < startXRefMarker.lowerBound
        else {
            return nil
        }
        trailerCursor = infoIndex + "/Info".utf8.count
        guard
            let infoObject = readInteger(in: bytes, index: &trailerCursor),
            let infoGeneration = readInteger(in: bytes, index: &trailerCursor),
            readToken(in: bytes, index: &trailerCursor) == Array("R".utf8),
            let objectOffset = xrefObjectOffset(
                object: infoObject,
                generation: infoGeneration,
                in: bytes,
                xrefOffset: xrefOffset,
                trailerIndex: trailerIndex
            )
        else {
            return nil
        }

        var objectCursor = objectOffset
        guard
            readInteger(in: bytes, index: &objectCursor) == infoObject,
            readInteger(in: bytes, index: &objectCursor) == infoGeneration,
            readToken(in: bytes, index: &objectCursor) == Array("obj".utf8),
            let dictionaryStart = findToken(Array("<<".utf8), in: bytes, from: objectCursor),
            let dictionaryEnd = matchingDictionaryEnd(in: bytes, from: dictionaryStart)
        else {
            return nil
        }
        return dictionaryStart..<dictionaryEnd
    }

    private static func xrefObjectOffset(
        object targetObject: Int,
        generation targetGeneration: Int,
        in bytes: [UInt8],
        xrefOffset: Int,
        trailerIndex: Int
    ) -> Int? {
        var cursor = xrefOffset
        guard readToken(in: bytes, index: &cursor) == Array("xref".utf8) else { return nil }
        while cursor < trailerIndex {
            skipPDFWhitespace(in: bytes, index: &cursor)
            guard cursor < trailerIndex else { break }
            guard
                let firstObject = readInteger(in: bytes, index: &cursor),
                let objectCount = readInteger(in: bytes, index: &cursor),
                objectCount >= 0
            else {
                return nil
            }
            for entry in 0..<objectCount {
                guard
                    let offset = readInteger(in: bytes, index: &cursor),
                    let generation = readInteger(in: bytes, index: &cursor),
                    let state = readToken(in: bytes, index: &cursor)
                else {
                    return nil
                }
                if firstObject + entry == targetObject,
                   generation == targetGeneration,
                   state == Array("n".utf8) {
                    return offset
                }
            }
        }
        return nil
    }

    private static func matchingDictionaryEnd(in bytes: [UInt8], from start: Int) -> Int? {
        guard start + 1 < bytes.count, bytes[start] == 0x3C, bytes[start + 1] == 0x3C else {
            return nil
        }
        var cursor = start
        var depth = 0
        while cursor + 1 < bytes.count {
            if bytes[cursor] == 0x25 {
                while cursor < bytes.count, bytes[cursor] != 0x0A, bytes[cursor] != 0x0D { cursor += 1 }
                continue
            }
            if bytes[cursor] == 0x28 {
                skipPDFLiteralString(in: bytes, index: &cursor)
                continue
            }
            if bytes[cursor] == 0x3C, bytes[cursor + 1] != 0x3C {
                cursor += 1
                while cursor < bytes.count, bytes[cursor] != 0x3E { cursor += 1 }
                cursor = min(cursor + 1, bytes.count)
                continue
            }
            if bytes[cursor] == 0x3C, bytes[cursor + 1] == 0x3C {
                depth += 1
                cursor += 2
                continue
            }
            if bytes[cursor] == 0x3E, bytes[cursor + 1] == 0x3E {
                depth -= 1
                cursor += 2
                if depth == 0 { return cursor }
                continue
            }
            cursor += 1
        }
        return nil
    }

    private static func skipPDFLiteralString(in bytes: [UInt8], index: inout Int) {
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

    private static func readInteger(in bytes: [UInt8], index: inout Int) -> Int? {
        skipPDFWhitespace(in: bytes, index: &index)
        let start = index
        while index < bytes.count, (0x30...0x39).contains(bytes[index]) { index += 1 }
        guard start < index else { return nil }
        return Int(String(decoding: bytes[start..<index], as: UTF8.self))
    }

    private static func readToken(in bytes: [UInt8], index: inout Int) -> [UInt8]? {
        skipPDFWhitespace(in: bytes, index: &index)
        guard index < bytes.count else { return nil }
        if index + 1 < bytes.count,
           (bytes[index] == 0x3C && bytes[index + 1] == 0x3C
               || bytes[index] == 0x3E && bytes[index + 1] == 0x3E) {
            defer { index += 2 }
            return Array(bytes[index...index + 1])
        }
        let start = index
        while index < bytes.count, !isPDFDelimiterOrWhitespace(bytes[index]) { index += 1 }
        guard start < index else {
            index += 1
            return [bytes[start]]
        }
        return Array(bytes[start..<index])
    }

    private static func skipPDFWhitespace(in bytes: [UInt8], index: inout Int) {
        while index < bytes.count {
            if isPDFWhitespace(bytes[index]) {
                index += 1
            } else if bytes[index] == 0x25 {
                while index < bytes.count, bytes[index] != 0x0A, bytes[index] != 0x0D { index += 1 }
            } else {
                return
            }
        }
    }

    private static func isPDFDelimiterOrWhitespace(_ byte: UInt8) -> Bool {
        isPDFWhitespace(byte) || [0x28, 0x29, 0x3C, 0x3E, 0x5B, 0x5D, 0x7B, 0x7D, 0x2F, 0x25].contains(byte)
    }

    private static func isPDFWhitespace(_ byte: UInt8) -> Bool {
        byte == 0 || byte == 0x09 || byte == 0x0A || byte == 0x0C || byte == 0x0D || byte == 0x20
    }

    private static func findToken(_ token: [UInt8], in bytes: [UInt8], from start: Int) -> Int? {
        guard
            !token.isEmpty,
            start >= 0,
            start <= bytes.count - token.count
        else {
            return nil
        }
        for index in start...(bytes.count - token.count) where bytes[index..<index + token.count].elementsEqual(token) {
            return index
        }
        return nil
    }

    private static func lastRange(of token: [UInt8], in bytes: [UInt8]) -> Range<Int>? {
        guard !token.isEmpty, bytes.count >= token.count else { return nil }
        for index in stride(from: bytes.count - token.count, through: 0, by: -1)
        where bytes[index..<index + token.count].elementsEqual(token) {
            return index..<index + token.count
        }
        return nil
    }

    private static func hasOnlyApprovedMetadata(_ data: Data) -> Bool {
        guard
            let document = PDFDocument(data: data),
            let attributes = document.documentAttributes,
            Set(attributes.keys) == Set([
                AnyHashable(PDFDocumentAttribute.titleAttribute),
                AnyHashable(PDFDocumentAttribute.creatorAttribute),
            ]),
            attributes[PDFDocumentAttribute.titleAttribute] as? String
                == "実家あんしんチェック 安全のためにできること",
            attributes[PDFDocumentAttribute.creatorAttribute] as? String == "SumaiGuard",
            let provider = CGDataProvider(data: data as CFData),
            let coreDocument = CGPDFDocument(provider),
            let catalog = coreDocument.catalog
        else {
            return false
        }

        var metadata: CGPDFObjectRef?
        guard !CGPDFDictionaryGetObject(catalog, "Metadata", &metadata) else {
            return false
        }
        var associatedFiles: CGPDFObjectRef?
        guard !CGPDFDictionaryGetObject(catalog, "AF", &associatedFiles) else {
            return false
        }
        var names: CGPDFDictionaryRef?
        if CGPDFDictionaryGetDictionary(catalog, "Names", &names), let names {
            var embeddedFiles: CGPDFObjectRef?
            guard !CGPDFDictionaryGetObject(names, "EmbeddedFiles", &embeddedFiles) else {
                return false
            }
        }
        return true
    }

    private static func attributedContent(for document: SafetyPDFDocument) -> CFAttributedString {
        let result = NSMutableAttributedString()
        append(document.title, style: .title, to: result)
        append("写真で確認できた注意箇所", style: .section, to: result)
        for (index, risk) in document.visibleRisks.enumerated() {
            append("注意候補 \(index + 1)：\(risk.label)", style: .itemTitle, to: result)
            append("写真上の根拠：\(risk.evidence)", style: .body, to: result)
            append("判断の根拠：\(risk.basis)", style: .body, to: result)
        }
        appendActions(document.familyActions, heading: "家族で今日できること", to: result)
        appendActions(document.careManagerActions, heading: "ケアマネ・福祉用具に相談", to: result)
        appendActions(document.contractorActions, heading: "専門施工・現地確認", to: result)
        append("大切なお知らせ", style: .section, to: result)
        append(document.approvedDisclaimer, style: .disclaimer, to: result, trailingNewlines: 0)
        return result
    }

    private static func appendActions(
        _ actions: [SafetyPDFDocument.Action],
        heading: String,
        to result: NSMutableAttributedString
    ) {
        append(heading, style: .section, to: result)
        if actions.isEmpty {
            append("該当する提案はありません", style: .body, to: result)
            return
        }
        for (index, action) in actions.enumerated() {
            append("\(index + 1). \(action.title)", style: .itemTitle, to: result)
            append(action.description, style: .body, to: result)
            append("理由：\(action.why)", style: .body, to: result)
            if let costLabel = action.costLabel {
                append(costLabel, style: .caption, to: result)
            }
            append(action.disclaimer, style: .caption, to: result)
        }
    }

    private static func append(
        _ text: String,
        style: PDFTextStyle,
        to result: NSMutableAttributedString,
        trailingNewlines: Int = 2
    ) {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byWordWrapping
        paragraph.lineSpacing = style.lineSpacing
        paragraph.paragraphSpacing = style.paragraphSpacing
        result.append(
            NSAttributedString(
                string: text + String(repeating: "\n", count: trailingNewlines),
                attributes: [
                    .font: style.font,
                    .foregroundColor: UIColor.black,
                    .paragraphStyle: paragraph,
                ]
            )
        )
    }
}

private enum PDFTextStyle {
    case title
    case section
    case itemTitle
    case body
    case caption
    case disclaimer

    var font: UIFont {
        switch self {
        case .title: .systemFont(ofSize: 22, weight: .bold)
        case .section: .systemFont(ofSize: 17, weight: .bold)
        case .itemTitle: .systemFont(ofSize: 13, weight: .semibold)
        case .body: .systemFont(ofSize: 12, weight: .regular)
        case .caption: .systemFont(ofSize: 11, weight: .regular)
        case .disclaimer: .systemFont(ofSize: 11, weight: .medium)
        }
    }

    var lineSpacing: CGFloat {
        switch self {
        case .title, .section: 3
        case .itemTitle, .body, .caption, .disclaimer: 2
        }
    }

    var paragraphSpacing: CGFloat {
        switch self {
        case .title: 10
        case .section: 7
        case .itemTitle: 4
        case .body, .caption, .disclaimer: 3
        }
    }
}
