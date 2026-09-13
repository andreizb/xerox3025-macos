// SPDX-License-Identifier: MIT
import Foundation
import PDFKit
import Darwin

let usage = """
xerox-document ACTION --input FILE --output NEW.pdf [--report NEW.json]
  ACTION: remove-empty | booklet | id-card
xerox-document interleave --fronts FILE --backs FILE --back-order same|reverse --output NEW.pdf [--report NEW.json]
xerox-document inspect --input FILE

Never prints, contacts the network, overwrites a file, or performs OCR. Page labels
are regenerated. Originals stay intact. Booklet refeeding requires a physical test.
"""
do {
    let args = Array(CommandLine.arguments.dropFirst())
    guard let action = args.first, !["--help", "-h"].contains(action) else { print(usage); exit(0) }
    var opts: [String: String] = [:]
    var index = 1
    while index < args.count {
        let name = args[index]
        guard ["--input", "--fronts", "--backs", "--back-order", "--output", "--report"].contains(name), index + 1 < args.count, opts[name] == nil else { throw DocumentError("Invalid or duplicate argument: \(name)") }
        opts[name] = args[index + 1]; index += 2
    }
    func required(_ key: String) throws -> String { guard let value = opts[key] else { throw DocumentError("Missing \(key).\n\(usage)") }; return value }
    let processed: OperationResult
    if action == "interleave" {
        guard opts["--input"] == nil else { throw DocumentError("Use --fronts and --backs for interleave.") }
        let order = try required("--back-order")
        guard ["same", "reverse"].contains(order) else { throw DocumentError("--back-order must be same or reverse.") }
        processed = try interleave(InputPDF(required("--fronts")), InputPDF(required("--backs")), reverseBacks: order == "reverse")
    } else {
        guard opts["--fronts"] == nil && opts["--backs"] == nil && opts["--back-order"] == nil else { throw DocumentError("Front/back arguments require interleave.") }
        let input = try InputPDF(required("--input"))
        if action == "inspect" {
            guard opts["--output"] == nil && opts["--report"] == nil else { throw DocumentError("inspect does not write files.") }
            FileHandle.standardOutput.write(try reportData(summarize(input.document))); print(""); exit(0)
        }
        switch action {
        case "remove-empty": processed = try removeEmptyPages(input)
        case "booklet", "id-card": processed = try compose(input, kind: action)
        default: throw DocumentError("Unknown action: \(action)")
        }
    }
    let output = try required("--output")
    // Preflight both paths before creating either; the exclusive writes still
    // guard against a concurrent creator. Reports never replace originals.
    for path in [output, opts["--report"]].compactMap({ $0 }) {
        if FileManager.default.fileExists(atPath: path) { throw DocumentError("Output already exists: \(path)") }
    }
    if let report = opts["--report"], URL(fileURLWithPath: report).standardizedFileURL == URL(fileURLWithPath: output).standardizedFileURL {
        throw DocumentError("PDF and report paths must differ.")
    }
    let report = try reportData(processed.report)
    try writeExclusive(processed.data, to: output)
    if let reportPath = opts["--report"] { try writeExclusive(report, to: reportPath) }
    FileHandle.standardOutput.write(report); print("")
} catch {
    FileHandle.standardError.write(Data("xerox-document: \(error)\n".utf8))
    exit(1)
}
