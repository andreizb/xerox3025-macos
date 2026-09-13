// SPDX-License-Identifier: MIT
// Explicit PDF derivative; neither OCR nor document text is added to the output.
import Foundation
import CoreGraphics
import PDFKit
import Vision
import CryptoKit
import Darwin

struct Failure: Error, CustomStringConvertible { let description: String; init(_ s: String) { description = s } }
struct Decision: Codable {
    let page: Int
    let status: String
    let detectedDegrees: Double?
    let correctionDegrees: Double
    let eligibleLines: Int
    let agreeingLines: Int
    let inputWidth: Double
    let inputHeight: Double
    let outputWidth: Double
    let outputHeight: Double
}
struct Report: Codable {
    let schema: Int
    let operation: String
    let inputSHA256: String
    let outputSHA256: String
    let sourcePreserved: Bool
    let ocrLayerAdded: Bool
    let pages: [Decision]
}
func hash(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }
func median(_ a: [Double]) -> Double {
    let s = a.sorted(), n = s.count
    return n % 2 == 1 ? s[n/2] : (s[n/2-1] + s[n/2])/2
}
func size(_ p: CGPDFPage) -> CGSize {
    let b = p.getBoxRect(.mediaBox)
    return abs(p.rotationAngle) % 180 == 90 ? CGSize(width: b.height, height: b.width) : b.size
}
func refineAngle(_ c: CGContext, around angle: Double) -> Double {
    guard let raw = c.data?.assumingMemoryBound(to: UInt8.self) else { return angle }
    let w=c.width, h=c.height, stride=c.bytesPerRow
    var points: [(Double,Double)] = []
    // Projection is only used after Vision establishes at least five agreeing text lines.
    // Ignore the extreme page boundary. All rows avoid a 2-pixel sampling alias at zero degrees.
    for y in Swift.stride(from: 4, to: h-4, by: 1) {
        for x in Swift.stride(from: 4, to: w-4, by: 1) {
            let i=y*stride+x*4
            if Int(raw[i])+Int(raw[i+1])+Int(raw[i+2]) < 450 {
                points.append((Double(x-w/2),Double(y-h/2)))
            }
        }
    }
    guard points.count >= 400 else { return angle }
    var best=angle, bestScore = -Double.infinity
    let length=Int(ceil(hypot(Double(w),Double(h))))+8
    for delta in -24...24 {
        let candidate=angle+Double(delta)*0.05, a=candidate * .pi / 180
        let co=cos(a), si=sin(a)
        var bins=[Int](repeating:0,count:length)
        for (x,y) in points {
            // Bitmap rows run downwards; Vision/PDF coordinates run upwards.
            let b=Int((y*co+x*si).rounded())+length/2
            if b>=0 && b<length { bins[b] += 1 }
        }
        let score=bins.reduce(0.0) { $0+Double($1*$1) }
        if score>bestScore { bestScore=score; best=candidate }
    }
    return best
}
func decision(_ p: CGPDFPage, number: Int) throws -> Decision {
    let s = size(p)
    // Render at up to 144 dpi, with a bounded pixel count. Never write raster pixels into output.
    let scale = min(2, 2400/max(s.width, s.height))
    let w = max(1, Int(ceil(s.width * scale))), h = max(1, Int(ceil(s.height * scale)))
    guard let c = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
    else { throw Failure("Cannot render page \(number)") }
    let r = CGRect(x: 0, y: 0, width: w, height: h)
    c.setFillColor(gray: 1, alpha: 1); c.fill(r)
    c.concatenate(p.getDrawingTransform(.mediaBox, rect: r, rotate: 0, preserveAspectRatio: true))
    c.drawPDFPage(p)
    guard let image = c.makeImage() else { throw Failure("Cannot render page \(number)") }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    // Vision runs locally to measure baselines. Recognized strings are neither saved nor added to PDF.
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([req])
    let lines = (req.results ?? []).filter {
        $0.boundingBox.width >= 0.18 && ($0.topCandidates(1).first?.confidence ?? 0) >= 0.4
    }
    let angles = lines.map { o -> Double in
        let dx = ((o.bottomRight.x-o.bottomLeft.x)+(o.topRight.x-o.topLeft.x))/2*Double(w)
        let dy = ((o.bottomRight.y-o.bottomLeft.y)+(o.topRight.y-o.topLeft.y))/2*Double(h)
        return atan2(dy, dx)*180 / .pi
    }
    let detected = angles.isEmpty ? nil : median(angles)
    let inliers = detected.map { m in angles.filter { abs($0-m) <= 0.8 } } ?? []
    var robust = inliers.isEmpty ? detected : median(inliers)
    let status: String, correction: Double
    if angles.count < 5 { status = "skipped-insufficient-text"; correction = 0 }
    else if inliers.count < 5 || Double(inliers.count)/Double(angles.count) < 0.75 {
        status = "skipped-inconsistent-lines"; correction = 0
    } else if abs(robust!) > 8 { status = "skipped-angle-outside-range"; correction = 0 }
    else if abs(robust!) < 0.25 { status = "skipped-already-straight"; correction = 0 }
    else {
        robust = refineAngle(c, around: robust!)
        if abs(robust!) > 8 { status = "skipped-angle-outside-range"; correction = 0 }
        else if abs(robust!) < 0.25 { status = "skipped-already-straight"; correction = 0 }
        else { status = "corrected"; correction = -robust! }
    }
    let a = correction * .pi / 180
    return Decision(page: number, status: status, detectedDegrees: robust, correctionDegrees: correction,
                    eligibleLines: angles.count, agreeingLines: inliers.count,
                    inputWidth: s.width, inputHeight: s.height,
                    outputWidth: s.width*abs(cos(a))+s.height*abs(sin(a)),
                    outputHeight: s.width*abs(sin(a))+s.height*abs(cos(a)))
}

func run() throws {
    guard CommandLine.arguments.count == 3 else { throw Failure("Usage: xerox-pdf-deskew INPUT.pdf OUTPUT.pdf") }
    let input = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
    let output = URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL
    guard input.resolvingSymlinksInPath() != output.resolvingSymlinksInPath() else { throw Failure("Input and output must differ") }
    let fm = FileManager.default
    guard !fm.fileExists(atPath: output.path) else { throw Failure("Output already exists") }
    let attrs = try fm.attributesOfItem(atPath: input.path)
    guard let bytes = attrs[.size] as? NSNumber, bytes.uint64Value <= 512*1024*1024 else { throw Failure("Input limit is 512 MiB") }
    let data = try Data(contentsOf: input), sourceHash = hash(data)
    guard let doc = PDFDocument(data: data), !doc.isEncrypted, !doc.isLocked,
          let provider = CGDataProvider(data: data as CFData), let cgdoc = CGPDFDocument(provider)
    else { throw Failure("Input must be a readable, unencrypted PDF") }
    guard (1...300).contains(doc.pageCount), doc.pageCount == cgdoc.numberOfPages else { throw Failure("PDF must have 1 to 300 pages") }
    guard doc.outlineRoot == nil else { throw Failure("Bookmarked PDFs require an editor that preserves their outlines") }
    if let catalog = cgdoc.catalog {
        for key in ["AcroForm", "Names", "StructTreeRoot", "OCProperties", "Collection"] {
            var object: CGPDFObjectRef?
            if CGPDFDictionaryGetObject(catalog, key, &object) { throw Failure("PDF contains unsupported document structure: \(key)") }
        }
    }
    var decisions: [Decision] = []
    for n in 1...doc.pageCount {
        guard let page = doc.page(at: n-1), let cgpage = cgdoc.page(at: n), page.annotations.isEmpty else {
            throw Failure("Annotated or form PDFs must be edited in Preview; page \(n) is unsupported")
        }
        let media = cgpage.getBoxRect(.mediaBox), crop = cgpage.getBoxRect(.cropBox)
        guard media.width > 0, media.height > 0, media.width <= 14400, media.height <= 14400 else { throw Failure("Invalid or oversized page \(n)") }
        guard media == crop else { throw Failure("Page \(n) has a custom crop box; deskew refuses to discard hidden content") }
        decisions.append(try autoreleasepool { try decision(cgpage, number: n) })
    }
    let result: Data
    if decisions.allSatisfy({ $0.correctionDegrees == 0 }) {
        result = data  // Byte-identical when there is no confident correction.
    } else {
        let out = NSMutableData()
        guard let consumer = CGDataConsumer(data: out as CFMutableData),
              let c = CGContext(consumer: consumer, mediaBox: nil, nil) else { throw Failure("Cannot create PDF") }
        for (index, d) in decisions.enumerated() {
            var media = CGRect(x: 0, y: 0, width: d.outputWidth, height: d.outputHeight)
            let box = Data(bytes: &media, count: MemoryLayout<CGRect>.size)
            c.beginPDFPage([kCGPDFContextMediaBox as String: box] as CFDictionary)
            c.saveGState()
            c.translateBy(x: d.outputWidth/2, y: d.outputHeight/2)
            c.rotate(by: d.correctionDegrees * .pi / 180)
            c.translateBy(x: -d.inputWidth/2, y: -d.inputHeight/2)
            let page = cgdoc.page(at: index+1)!
            c.concatenate(page.getDrawingTransform(.mediaBox,
                rect: CGRect(x: 0, y: 0, width: d.inputWidth, height: d.inputHeight), rotate: 0, preserveAspectRatio: true))
            c.drawPDFPage(page)
            c.restoreGState(); c.endPDFPage()
        }
        c.closePDF()
        result = out as Data
        guard let check = PDFDocument(data: result), check.pageCount == doc.pageCount else { throw Failure("Generated PDF failed validation") }
        // Affine drawing must not drop the input's existing selectable text / OCR.
        for i in 0..<doc.pageCount {
            let before = doc.page(at: i)?.string?.filter { !$0.isWhitespace } ?? ""
            let after = check.page(at: i)?.string?.filter { !$0.isWhitespace } ?? ""
            guard before == after else { throw Failure("Page \(i+1) text changed; output was not written") }
        }
    }
    guard hash(try Data(contentsOf: input)) == sourceHash else { throw Failure("Input changed during processing") }
    // Exclusive creation prevents races, symlink traversal and overwriting any existing file.
    let fd = open(output.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, S_IRUSR | S_IWUSR)
    guard fd >= 0 else { throw Failure("Cannot create output exclusively: \(String(cString: strerror(errno)))") }
    var written = 0
    let ok = result.withUnsafeBytes { raw -> Bool in
        while written < raw.count {
            let n = write(fd, raw.baseAddress!.advanced(by: written), raw.count-written)
            if n < 0 && errno == EINTR { continue }
            if n <= 0 { return false }; written += n
        }
        return fsync(fd) == 0
    }
    let closeResult = close(fd)
    guard ok && closeResult == 0 else { try? fm.removeItem(at: output); throw Failure("Failed writing output") }
    let report = Report(schema: 1, operation: "conservative-deskew", inputSHA256: sourceHash,
                        outputSHA256: hash(result), sourcePreserved: true, ocrLayerAdded: false, pages: decisions)
    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    FileHandle.standardOutput.write(try encoder.encode(report)); print("")
}
do { try run() } catch {
    FileHandle.standardError.write(Data(("xerox-pdf-deskew: \(error)\n").utf8))
    exit(1)
}
