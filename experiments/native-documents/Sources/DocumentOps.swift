// SPDX-License-Identifier: MIT
import Foundation
import PDFKit
import CoreGraphics
import CryptoKit
import Darwin

struct DocumentError: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

struct InputPDF {
    let url: URL
    let bytes: Data
    let document: PDFDocument
    let sha256: String
    init(_ path: String) throws {
        url = URL(fileURLWithPath: path).standardizedFileURL
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber, size.intValue <= 256 * 1024 * 1024 else {
            throw DocumentError("Input must be a regular PDF no larger than 256 MiB.")
        }
        bytes = try Data(contentsOf: url)
        guard bytes.prefix(1024).range(of: Data("%PDF-".utf8)) != nil,
              let loaded = PDFDocument(data: bytes) else { throw DocumentError("Unreadable or malformed PDF: \(url.lastPathComponent)") }
        guard !loaded.isEncrypted && !loaded.isLocked else {
            throw DocumentError("Encrypted PDFs are not processed. Export an unlocked working copy in Preview first; the encrypted original stays intact.")
        }
        if let catalog = loaded.documentRef?.catalog {
            for key in ["Perms", "AcroForm"] {
                var special: CGPDFObjectRef?
                if CGPDFDictionaryGetObject(catalog, key, &special) {
                    throw DocumentError("Form or certified/signature PDF catalog is unsupported. Export a working copy in Preview first; retain the original.")
                }
            }
        }
        guard loaded.pageCount > 0 && loaded.pageCount <= 2000 else { throw DocumentError("PDF must contain 1–2000 pages.") }
        for index in 0..<loaded.pageCount {
            guard let page = loaded.page(at: index), page.pageRef != nil else { throw DocumentError("Unreadable PDF page \(index + 1).") }
            guard !page.annotations.contains(where: { $0.type == "Widget" }) else {
                throw DocumentError("Interactive form/signature widgets are not supported. Make a print/export copy in Preview for this workflow; retain the original form.")
            }
            let box = page.bounds(for: .mediaBox)
            guard box.width.isFinite && box.height.isFinite && box.width > 0 && box.height > 0 && box.width <= 14400 && box.height <= 14400 else {
                throw DocumentError("Invalid or excessive page dimensions at page \(index + 1).")
            }
        }
        document = loaded
        sha256 = Self.digest(bytes)
    }
    static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
}

struct PageSummary: Codable {
    let number: Int
    let label: String
    let rotation: Int
    let mediaBox: [Double]
    let cropBox: [Double]
    let textCharacters: Int
    let annotations: Int
}
func rectangle(_ box: CGRect) -> [Double] { [box.minX, box.minY, box.width, box.height].map(Double.init) }
func summarize(_ document: PDFDocument) -> [PageSummary] {
    (0..<document.pageCount).map { index in
        let p = document.page(at: index)!
        return PageSummary(number: index + 1, label: p.label ?? "", rotation: p.rotation,
            mediaBox: rectangle(p.bounds(for: .mediaBox)), cropBox: rectangle(p.bounds(for: .cropBox)),
            textCharacters: p.numberOfCharacters, annotations: p.annotations.count)
    }
}
struct ProcessReport: Codable {
    var schemaVersion = 1
    let action: String
    let inputSHA256: [String]
    let outputSHA256: String
    let outputPages: [PageSummary]
    let sourcePageMapping: [[String]]
    let removedPages: [Int]
    let addedBlankSlots: Int
    let notes: [String]
}
struct OperationResult {
    let data: Data
    let report: ProcessReport
}

// Only a page with no annotations, text, or content commands can be removed.
// A raster scan of white paper is intentionally retained: faint content/noise is
// not proof of a blank page. Graphics-state q/Q and comments are harmless.
func definitelyEmpty(_ page: PDFPage) -> Bool {
    guard page.annotations.isEmpty, page.string?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false,
          let dictionary = page.pageRef?.dictionary else { return false }
    var object: CGPDFObjectRef?
    guard CGPDFDictionaryGetObject(dictionary, "Contents", &object), let contents = object else { return true }
    func emptyStream(_ stream: CGPDFStreamRef) -> Bool {
        var format = CGPDFDataFormat.raw
        guard let copied = CGPDFStreamCopyData(stream, &format), format == .raw else { return false }
        let bytes = copied as Data
        guard let text = String(data: bytes, encoding: .ascii) else { return false }
        let withoutComments = text.split(separator: "\n", omittingEmptySubsequences: false).map {
            $0.split(separator: "%", maxSplits: 1, omittingEmptySubsequences: false).first ?? ""
        }.joined(separator: "\n")
        return withoutComments.split(whereSeparator: { $0.isWhitespace || $0 == "\0" }).allSatisfy { $0 == "q" || $0 == "Q" }
    }
    switch CGPDFObjectGetType(contents) {
    case .null: return true
    case .stream:
        var stream: CGPDFStreamRef?
        return CGPDFObjectGetValue(contents, .stream, &stream) && stream.map(emptyStream) == true
    case .array:
        var array: CGPDFArrayRef?
        guard CGPDFObjectGetValue(contents, .array, &array), let array else { return false }
        for index in 0..<CGPDFArrayGetCount(array) {
            var stream: CGPDFStreamRef?
            guard CGPDFArrayGetStream(array, index, &stream), let stream, emptyStream(stream) else { return false }
        }
        return true
    default: return false
    }
}

func result(_ action: String, _ inputs: [InputPDF], _ document: PDFDocument,
            mapping: [[String]], removed: [Int] = [], blanks: Int = 0, notes: [String] = []) throws -> OperationResult {
    let expectedGeometry = summarize(document)
    let expectedText = (0..<document.pageCount).map { document.page(at: $0)!.string ?? "" }
    guard let data = document.dataRepresentation(), let reopened = PDFDocument(data: data), reopened.pageCount == document.pageCount,
          reopened.pageCount > 0 else { throw DocumentError("Generated PDF failed native validation.") }
    if ["remove-empty", "interleave"].contains(action) {
        for (before, after) in zip(expectedGeometry, summarize(reopened)) {
            guard before.rotation == after.rotation && before.mediaBox == after.mediaBox && before.cropBox == after.cropBox && before.annotations == after.annotations else {
                throw DocumentError("PDFKit changed page geometry or annotations during serialization. This input is refused to preserve the original; nonzero MediaBox origins are a known case.")
            }
        }
        for index in 0..<reopened.pageCount {
            guard (reopened.page(at: index)!.string ?? "") == expectedText[index] else {
                throw DocumentError("PDFKit changed extracted page text during serialization; this input is refused and the original remains unchanged.")
            }
        }
    }
    let report = ProcessReport(action: action, inputSHA256: inputs.map(\.sha256), outputSHA256: InputPDF.digest(data),
        outputPages: summarize(reopened), sourcePageMapping: mapping, removedPages: removed,
        addedBlankSlots: blanks, notes: notes + ["Original files are unchanged. No OCR or rasterization was performed.",
          "PDF page labels are regenerated in output order. Document outlines, signatures and other document-level structures are not preserved."])
    return OperationResult(data: data, report: report)
}

func copiedPages(_ entries: [(InputPDF, Int)]) throws -> PDFDocument {
    let out = PDFDocument()
    for (input, index) in entries {
        guard let page = input.document.page(at: index)?.copy() as? PDFPage else { throw DocumentError("Cannot copy page \(index + 1).") }
        out.insert(page, at: out.pageCount)
    }
    return out
}
func removeEmptyPages(_ input: InputPDF) throws -> OperationResult {
    let removed = (0..<input.document.pageCount).filter { definitelyEmpty(input.document.page(at: $0)!) }
    let removedSet = Set(removed)
    let kept = (0..<input.document.pageCount).filter { !removedSet.contains($0) }
    guard !kept.isEmpty else { throw DocumentError("Every page is structurally empty; no zero-page PDF was created.") }
    return try result("remove-empty", [input], copiedPages(kept.map { (input, $0) }),
        mapping: kept.map { ["input:\($0 + 1)"] }, removed: removed.map { $0 + 1 },
        notes: ["Only structurally empty pages were removed. Scanned white pages, faint marks, annotations and invisible OCR text are retained.",
                "Page content, rotations, boxes and page annotations are copied through PDFKit."])
}
func interleave(_ fronts: InputPDF, _ backs: InputPDF, reverseBacks: Bool) throws -> OperationResult {
    let f = fronts.document.pageCount, b = backs.document.pageCount
    guard f == b || f == b + 1 else { throw DocumentError("Front/back counts must match, or fronts may have exactly one additional final page. Got \(f) fronts and \(b) backs.") }
    guard fronts.url.resolvingSymlinksInPath() != backs.url.resolvingSymlinksInPath() else { throw DocumentError("Fronts and backs must be different PDF files.") }
    var entries: [(InputPDF, Int)] = [], mapping: [[String]] = []
    for index in 0..<f {
        entries.append((fronts, index)); mapping.append(["fronts:\(index + 1)"])
        if index < b {
            let back = reverseBacks ? b - index - 1 : index
            entries.append((backs, back)); mapping.append(["backs:\(back + 1)"])
        }
    }
    return try result("interleave", [fronts, backs], copiedPages(entries), mapping: mapping,
        notes: ["Back-page input order: \(reverseBacks ? "reverse" : "same"). No page was discarded.",
                f == b + 1 ? "The final front has no back, producing an odd-page document." : "Every front has a matching back.",
                "Page rotations, boxes, text/OCR and annotations are copied through PDFKit."])
}

let a4Portrait = CGRect(x: 0, y: 0, width: 595.2755905511812, height: 841.8897637795276)
func drawPage(_ page: PDFPage, in target: CGRect, context: CGContext) {
    let source = page.bounds(for: .cropBox)
    let turned = abs(page.rotation) % 180 == 90
    let width = turned ? source.height : source.width, height = turned ? source.width : source.height
    let scale = min(target.width / width, target.height / height)
    context.saveGState()
    context.clip(to: target)
    context.translateBy(x: target.minX + (target.width - width * scale) / 2,
                        y: target.minY + (target.height - height * scale) / 2)
    context.scaleBy(x: scale, y: scale)
    // PDFKit handles the source rotation, crop origin and annotations. Drawing
    // into another PDF context retains vectors and selectable text, not a bitmap.
    page.draw(with: .cropBox, to: context)
    context.restoreGState()
}
func compose(_ input: InputPDF, kind: String) throws -> OperationResult {
    if kind == "id-card" && input.document.pageCount != 2 { throw DocumentError("ID-card composition requires exactly two cropped PDF pages, front then back.") }
    if kind == "id-card" {
        for index in 0..<2 {
            let page = input.document.page(at: index)!, bounds = page.bounds(for: .cropBox)
            let rotated = abs(page.rotation) % 180 == 90
            let ratio = rotated ? bounds.height / bounds.width : bounds.width / bounds.height
            guard abs(ratio / (85.60 / 53.98) - 1) <= 0.10 else {
                throw DocumentError("Crop each card side to its edges in Preview first. Page \(index + 1) is not close to the landscape card aspect ratio; an uncropped A4 scan would shrink the card incorrectly.")
            }
        }
    }
    var box = kind == "booklet" ? CGRect(x: 0, y: 0, width: a4Portrait.height, height: a4Portrait.width) : a4Portrait
    let storage = NSMutableData()
    guard let consumer = CGDataConsumer(data: storage as CFMutableData),
          let context = CGContext(consumer: consumer, mediaBox: &box, nil) else { throw DocumentError("Cannot create PDF context.") }
    var mapping: [[String]] = []
    let margin = 14.1732283464567 // 5 mm software inset, no borderless claim.
    var blanks = 0
    if kind == "booklet" {
        let count = input.document.pageCount
        let padded = ((count + 3) / 4) * 4
        blanks = padded - count
        let rects = [CGRect(x: margin, y: margin, width: box.width / 2 - 2 * margin, height: box.height - 2 * margin),
                     CGRect(x: box.width / 2 + margin, y: margin, width: box.width / 2 - 2 * margin, height: box.height - 2 * margin)]
        for sheet in 0..<(padded / 4) {
            // Outside → inside, front [last, first], back [second, penultimate].
            for pair in [[padded - 1 - sheet * 2, sheet * 2], [sheet * 2 + 1, padded - 2 - sheet * 2]] {
                context.beginPDFPage(nil)
                var labels: [String] = []
                for (slot, page) in pair.enumerated() {
                    if page < count { drawPage(input.document.page(at: page)!, in: rects[slot], context: context); labels.append("input:\(page + 1)") }
                    else { labels.append("blank") }
                }
                mapping.append(labels)
                context.endPDFPage()
            }
        }
    } else if kind == "id-card" {
        context.beginPDFPage(nil)
        let cardWidth = 85.60 / 25.4 * 72, cardHeight = 53.98 / 25.4 * 72
        for index in 0..<2 {
            let target = CGRect(x: (box.width - cardWidth) / 2,
                y: box.height / 2 + (index == 0 ? 14.1732283464567 : -14.1732283464567 - cardHeight), width: cardWidth, height: cardHeight)
            drawPage(input.document.page(at: index)!, in: target, context: context)
        }
        mapping = [["input:1", "input:2"]]
        context.endPDFPage()
    } else { throw DocumentError("Unknown composition.") }
    context.closePDF()
    guard let out = PDFDocument(data: storage as Data) else { throw DocumentError("Cannot reopen composed PDF.") }
    return try result(kind, [input], out, mapping: mapping, blanks: blanks,
        notes: kind == "booklet" ? ["A4 landscape sheets; left binding; 5 mm inset on each half; source crop boxes are fitted proportionally.",
            "Output alternates front/back sheet faces. Native Print → Paper Handling can select odd/even faces. Physical refeed orientation is not calibrated; no print job was submitted.",
            "Page annotations are drawn into the derivative and are no longer editable annotations."] :
          ["Two cropped pages fitted into 85.60 × 53.98 mm areas on A4. No automatic card-edge detection or physical scale calibration is claimed.",
           "Page annotations are drawn into the derivative and are no longer editable annotations."])
}

func writeExclusive(_ data: Data, to path: String) throws {
    let fd = Darwin.open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, S_IRUSR | S_IWUSR)
    guard fd >= 0 else { throw DocumentError("Refusing output overwrite or inaccessible path: \(path) (\(String(cString: strerror(errno))))") }
    var completed = false
    defer { Darwin.close(fd); if !completed { Darwin.unlink(path) } }
    try data.withUnsafeBytes { buffer in
        var remaining = buffer.count, offset = 0
        while remaining > 0 {
            let written = Darwin.write(fd, buffer.baseAddress!.advanced(by: offset), remaining)
            if written < 0 && errno == EINTR { continue }
            guard written > 0 else { throw DocumentError("Output write failed.") }
            remaining -= written; offset += written
        }
    }
    guard fsync(fd) == 0 else { throw DocumentError("Output could not be synchronized.") }
    completed = true
}
func reportData<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    return try encoder.encode(value)
}
