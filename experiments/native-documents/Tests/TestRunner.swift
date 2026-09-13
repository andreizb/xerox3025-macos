// SPDX-License-Identifier: MIT
import Foundation
import PDFKit
import CoreGraphics
import CoreText

@main struct NativeTests {
    static func main() throws {
        let dir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var checks: [String] = []
        func check(_ condition: @autoclosure () throws -> Bool, _ description: String) throws {
            guard try condition() else { throw DocumentError("FAIL: \(description)") }
            checks.append(description)
        }
        func fixture(_ file: String, labels: [String], rotations: Bool = false, card: Bool = false) throws -> InputPDF {
            let data = NSMutableData(); var box = card ? CGRect(x: 0, y: 0, width: 242.6456692913386, height: 153.0141732283465) : CGRect(x: 0, y: 0, width: 400, height: 600)
            let ctx = CGContext(consumer: CGDataConsumer(data: data as CFMutableData)!, mediaBox: &box, nil)!
            let font = CTFontCreateWithName("Helvetica" as CFString, card ? 12 : 18, nil)
            for (index, label) in labels.enumerated() {
                ctx.beginPDFPage(nil)
                if !label.isEmpty {
                    ctx.setFillColor(CGColor(red: 0.85, green: 0.08, blue: 0.08, alpha: 1))
                    ctx.fill(CGRect(x: box.width * 0.10, y: box.height * 0.80, width: box.width * 0.10, height: box.height * 0.08))
                    ctx.setFillColor(CGColor(gray: 0, alpha: 1))
                    for (line, text) in [label, "Existing OCR: România"].enumerated() {
                        ctx.textPosition = CGPoint(x: box.width * 0.10, y: box.height * 0.64 - CGFloat(line) * (card ? 18 : 26))
                        CTLineDraw(CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: [.font: font])), ctx)
                    }
                    if index % 2 == 1 { ctx.stroke(CGRect(x: box.width * 0.1, y: box.height * 0.12, width: box.width * 0.5, height: box.height * 0.08)) }
                }
                ctx.endPDFPage()
            }
            ctx.closePDF()
            let document = PDFDocument(data: data as Data)!
            if rotations {
                for i in 0..<document.pageCount {
                    let page = document.page(at: i)!
                    page.rotation = (i % 4) * 90
                    page.setBounds(CGRect(x: 20, y: 30, width: 350, height: 520), for: .cropBox)
                }
                let annotation = PDFAnnotation(bounds: CGRect(x: 50, y: 120, width: 150, height: 25), forType: .freeText, withProperties: nil)
                annotation.contents = "Note kept"
                document.page(at: 0)!.addAnnotation(annotation)
            }
            let url = dir.appendingPathComponent(file)
            try document.dataRepresentation()!.write(to: url)
            return try InputPDF(url.path)
        }
        func save(_ result: OperationResult, _ name: String) throws -> PDFDocument {
            try writeExclusive(result.data, to: dir.appendingPathComponent(name + ".pdf").path)
            try writeExclusive(reportData(result.report), to: dir.appendingPathComponent(name + ".json").path)
            return PDFDocument(data: result.data)!
        }
        func pixels(_ page: PDFPage) -> Data {
            let width = 300, height = 300
            var data = Data(count: width * height * 4)
            data.withUnsafeMutableBytes { buffer in
                let context = CGContext(data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8,
                    bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.setFillColor(CGColor(gray: 1, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: width, height: height))
                drawPage(page, in: CGRect(x: 0, y: 0, width: width, height: height), context: context)
            }
            return data
        }
        let fronts = try fixture("fronts.pdf", labels: ["PAGE 1", "PAGE 3", "PAGE 5"], rotations: true)
        let backs = try fixture("backs.pdf", labels: ["PAGE 4", "PAGE 2"], rotations: true)
        let inter = try interleave(fronts, backs, reverseBacks: true)
        let combined = try save(inter, "interleave-reverse")
        try check(combined.pageCount == 5, "odd duplex produces exactly 5 pages")
        for (i, expected) in ["PAGE 1", "PAGE 2", "PAGE 3", "PAGE 4", "PAGE 5"].enumerated() {
            try check(combined.page(at: i)!.string!.contains(expected), "interleave semantic order page \(i + 1)")
            try check(combined.page(at: i)!.string!.contains("România"), "interleave existing Unicode OCR page \(i + 1)")
            try check(combined.page(at: i)!.label == String(i + 1), "output label normalized page \(i + 1)")
        }
        let originalPages = [fronts.document.page(at: 0)!, backs.document.page(at: 1)!, fronts.document.page(at: 1)!, backs.document.page(at: 0)!, fronts.document.page(at: 2)!]
        for i in 0..<5 {
            let original = originalPages[i], output = combined.page(at: i)!
            try check(output.rotation == original.rotation, "rotation preserved page \(i + 1)")
            try check(output.bounds(for: .mediaBox) == original.bounds(for: .mediaBox), "media box preserved page \(i + 1)")
            try check(output.bounds(for: .cropBox) == original.bounds(for: .cropBox), "crop box preserved page \(i + 1)")
            try check(output.annotations.count == original.annotations.count, "annotations preserved page \(i + 1)")
            try check(pixels(output) == pixels(original), "rendered page pixels identical page \(i + 1)")
        }
        let same = try save(interleave(fronts, backs, reverseBacks: false), "interleave-same")
        try check(same.page(at: 1)!.string!.contains("PAGE 4"), "explicit same-order backs honored")
        let offsetDoc = PDFDocument(data: fronts.bytes)!
        while offsetDoc.pageCount > 1 { offsetDoc.removePage(at: 1) }
        offsetDoc.page(at: 0)!.setBounds(CGRect(x: -10, y: -20, width: 430, height: 650), for: .mediaBox)
        offsetDoc.page(at: 0)!.setBounds(CGRect(x: 30, y: 40, width: 340, height: 500), for: .cropBox)
        offsetDoc.page(at: 0)!.rotation = 270
        let offsetURL = dir.appendingPathComponent("offset-media.pdf")
        try offsetDoc.dataRepresentation()!.write(to: offsetURL)
        let offset = try InputPDF(offsetURL.path)
        let offsetOutput = try save(removeEmptyPages(offset), "offset-media-copy")
        try check(offsetOutput.page(at: 0)!.bounds(for: .mediaBox) == offset.document.page(at: 0)!.bounds(for: .mediaBox), "actual source media box preserved after fixture serialization")
        try check(offsetOutput.page(at: 0)!.bounds(for: .cropBox) == offset.document.page(at: 0)!.bounds(for: .cropBox) && offsetOutput.page(at: 0)!.rotation == 270, "nonzero crop origin and 270 degree rotation preserved together")
        try check(pixels(offsetOutput.page(at: 0)!) == pixels(offset.document.page(at: 0)!), "nonzero media/crop/rotation rendered pixels unchanged")
        // PDFKit normalizes an assigned MediaBox origin while writing fixtures.
        // Build an independent minimal valid PDF to retain a genuine raw origin.
        let commands = "BT /F1 16 Tf 50 200 Td (OFFSET TEXT) Tj ET\n"
        let objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [-10 -20 420 630] /CropBox [30 40 370 540] /Rotate 270 /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", "<< /Length \(commands.utf8.count) >>\nstream\n\(commands)endstream"]
        var manual = "%PDF-1.4\n", offsets = [0]
        for (index, object) in objects.enumerated() { offsets.append(manual.utf8.count); manual += "\(index + 1) 0 obj\n\(object)\nendobj\n" }
        let xref = manual.utf8.count
        manual += "xref\n0 6\n0000000000 65535 f \n"
        for offset in offsets.dropFirst() { manual += String(format: "%010d 00000 n \n", offset) }
        manual += "trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n\(xref)\n%%EOF\n"
        let rawOffsetURL = dir.appendingPathComponent("raw-nonzero-media.pdf")
        try Data(manual.utf8).write(to: rawOffsetURL)
        let rawOffset = try InputPDF(rawOffsetURL.path)
        try check(rawOffset.document.page(at: 0)!.bounds(for: .mediaBox).origin == CGPoint(x: -10, y: -20), "independent fixture contains genuine nonzero MediaBox origin")
        do { _ = try removeEmptyPages(rawOffset); throw DocumentError("Accepted normalized source geometry") }
        catch { try check(String(describing: error).contains("geometry"), "PDFKit nonzero-origin normalization refused before output") }
        let one = try fixture("one.pdf", labels: ["SINGLE"])
        do { _ = try interleave(fronts, one, reverseBacks: false); throw DocumentError("Accepted mismatched counts") }
        catch { try check(String(describing: error).contains("counts must match"), "invalid duplex count refused") }
        do { _ = try interleave(fronts, fronts, reverseBacks: false); throw DocumentError("Accepted same input") }
        catch { try check(String(describing: error).contains("different PDF files"), "duplicate duplex input refused") }
        let empties = try fixture("with-empty.pdf", labels: ["FIRST", "", "LAST"])
        try check(definitelyEmpty(empties.document.page(at: 1)!), "native empty page classified structurally empty")
        let trimmed = try save(removeEmptyPages(empties), "empty-removed")
        try check(trimmed.pageCount == 2 && trimmed.page(at: 1)!.string!.contains("LAST"), "empty page removal retains semantic order")
        let allEmpty = try fixture("all-empty.pdf", labels: ["", ""])
        do { _ = try removeEmptyPages(allEmpty); throw DocumentError("Accepted zero pages") }
        catch { try check(String(describing: error).contains("Every page"), "all-empty document refused without output") }
        let annotated = allEmpty.document.page(at: 0)!
        let note = PDFAnnotation(bounds: CGRect(x: 10, y: 10, width: 50, height: 20), forType: .text, withProperties: nil)
        note.contents = "Do not remove"; annotated.addAnnotation(note)
        try check(!definitelyEmpty(annotated), "annotation-only page retained")
        let bookletInput = try fixture("five-page.pdf", labels: (1...5).map { "BOOK PAGE \($0)" }, rotations: true)
        let imposed = try compose(bookletInput, kind: "booklet")
        let book = try save(imposed, "booklet-five")
        try check(book.pageCount == 4 && imposed.report.addedBlankSlots == 3, "five pages padded to eight slots across four booklet faces")
        try check(imposed.report.sourcePageMapping == [["blank", "input:1"], ["input:2", "blank"], ["blank", "input:3"], ["input:4", "input:5"]], "left-bound booklet front/back slot order")
        for i in 1...5 { try check(book.string?.contains("BOOK PAGE \(i)") == true, "booklet retains selectable text page \(i)") }
        for i in 0..<4 { try check(abs(book.page(at: i)!.bounds(for: .mediaBox).width - a4Portrait.height) < 0.02 && book.page(at: i)!.rotation == 0, "booklet A4 landscape media/rotation face \(i + 1)") }
        let pair = try fixture("card-pair.pdf", labels: ["CARD FRONT", "CARD BACK"], card: true)
        let card = try save(compose(pair, kind: "id-card"), "card-a4")
        try check(card.pageCount == 1 && card.string!.contains("CARD FRONT") && card.string!.contains("CARD BACK"), "ID-card composition keeps both texts on one A4 page")
        do { _ = try compose(fronts, kind: "id-card"); throw DocumentError("Accepted three card sides") }
        catch { try check(String(describing: error).contains("exactly two"), "ID-card count guard") }
        do { _ = try compose(backs, kind: "id-card"); throw DocumentError("Accepted uncropped card input") }
        catch { try check(String(describing: error).contains("Crop each card"), "uncropped A4-like card input refused") }
        let malformed = dir.appendingPathComponent("malformed.pdf")
        try Data("%PDF-1.7\nnot a valid document".utf8).write(to: malformed)
        do { _ = try InputPDF(malformed.path); throw DocumentError("Accepted malformed input") }
        catch { try check(String(describing: error).contains("malformed"), "malformed PDF refused") }
        let locked = dir.appendingPathComponent("encrypted.pdf")
        let lockedResult = pair.document.write(to: locked, withOptions: [.userPasswordOption: "fixture-password", .ownerPasswordOption: "fixture-owner"])
        try check(lockedResult, "native encrypted fixture created")
        do { _ = try InputPDF(locked.path); throw DocumentError("Accepted encrypted input") }
        catch { try check(String(describing: error).contains("Encrypted"), "password PDF refused without decrypting") }
        let unlocked = PDFDocument(url: locked)!
        try check(unlocked.isLocked && !unlocked.unlock(withPassword: "wrong"), "PDFKit native encryption rejects wrong password")
        try check(unlocked.unlock(withPassword: "fixture-password") && unlocked.string!.contains("CARD FRONT"), "PDFKit native decryption preserves text with correct password")
        let edited = PDFDocument(data: fronts.bytes)!
        let moved = edited.page(at: 0)!
        edited.removePage(at: 0); edited.insert(moved, at: 2); edited.removePage(at: 1)
        let reopenedEdit = PDFDocument(data: edited.dataRepresentation()!)!
        try check(reopenedEdit.pageCount == 2 && reopenedEdit.page(at: 0)!.string!.contains("PAGE 3") && reopenedEdit.page(at: 1)!.string!.contains("PAGE 1"), "PDFKit page reorder and delete preserve requested text order")
        try check(reopenedEdit.page(at: 1)!.annotations.count == 1, "PDFKit reorder/delete preserves surviving annotation")
        let imageData = NSMutableData(); var imageBox = CGRect(x: 0, y: 0, width: 100, height: 100)
        let imageContext = CGContext(consumer: CGDataConsumer(data: imageData as CFMutableData)!, mediaBox: &imageBox, nil)!
        imageContext.beginPDFPage(nil)
        let white = Data(repeating: 255, count: 10 * 10 * 3)
        let whiteImage = CGImage(width: 10, height: 10, bitsPerComponent: 8, bitsPerPixel: 24, bytesPerRow: 30,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: [], provider: CGDataProvider(data: white as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
        imageContext.draw(whiteImage, in: imageBox); imageContext.endPDFPage()
        imageContext.beginPDFPage(nil); imageContext.setTextDrawingMode(.invisible)
        imageContext.textPosition = CGPoint(x: 2, y: 40)
        CTLineDraw(CTLineCreateWithAttributedString(NSAttributedString(string: "Invisible OCR", attributes: [.font: CTFontCreateWithName("Helvetica" as CFString, 8, nil)])), imageContext)
        imageContext.endPDFPage(); imageContext.closePDF()
        let careful = PDFDocument(data: imageData as Data)!
        try check(!definitelyEmpty(careful.page(at: 0)!), "visually white raster page retained")
        try check(!definitelyEmpty(careful.page(at: 1)!), "invisible OCR page retained")
        let widgetDoc = PDFDocument(data: one.bytes)!
        widgetDoc.page(at: 0)!.addAnnotation(PDFAnnotation(bounds: CGRect(x: 50, y: 50, width: 100, height: 20), forType: .widget, withProperties: nil))
        let widgetPath = dir.appendingPathComponent("form-widget.pdf")
        try widgetDoc.dataRepresentation()!.write(to: widgetPath)
        do { _ = try InputPDF(widgetPath.path); throw DocumentError("Accepted form widgets") }
        catch { try check(String(describing: error).contains("form/signature"), "interactive form/signature widget input refused") }
        let protected = dir.appendingPathComponent("protected.pdf")
        try Data("original-sentinel".utf8).write(to: protected)
        do { try writeExclusive(imposed.data, to: protected.path); throw DocumentError("Overwrote output") }
        catch { try check(String(describing: error).contains("overwrite"), "existing output overwrite refused") }
        try check(try Data(contentsOf: protected) == Data("original-sentinel".utf8), "existing output bytes unchanged")
        let symlink = dir.appendingPathComponent("output-link.pdf")
        try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: protected)
        do { try writeExclusive(imposed.data, to: symlink.path); throw DocumentError("Followed output symlink") }
        catch { try check(String(describing: error).contains("overwrite"), "output symlink refused") }
        for original in [fronts, backs, empties, bookletInput, pair] {
            try check(InputPDF.digest(try Data(contentsOf: original.url)) == original.sha256, "source hash unchanged \(original.url.lastPathComponent)")
        }
        let summary: [String: Any] = ["passed": true, "checks": checks, "count": checks.count, "system": ProcessInfo.processInfo.operatingSystemVersionString,
            "nativeFrameworks": ["PDFKit", "CoreGraphics", "CoreText", "CryptoKit"], "uiTested": false, "physicalPrintingTested": false]
        let summaryData = try JSONSerialization.data(withJSONObject: summary, options: [.prettyPrinted, .sortedKeys])
        try summaryData.write(to: dir.appendingPathComponent("native-tests.json"))
        FileHandle.standardOutput.write(summaryData); print("")
    }
}
