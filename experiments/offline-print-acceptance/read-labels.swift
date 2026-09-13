// SPDX-License-Identifier: MIT
// OCR local, synthetic raster previews using Apple's public Vision framework.
import Foundation
import Vision
import ImageIO

var output: [[String: Any]] = []
let arguments = Array(CommandLine.arguments.dropFirst())
let grid = arguments.first == "--grid=4" ? 4 : 1
for path in arguments.dropFirst(grid == 4 ? 1 : 0) {
    let url = URL(fileURLWithPath: path)
    do {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            fputs("Cannot open local synthetic preview\n", stderr); exit(1)
        }
        var observations: [[String: Any]] = []
        for row in 0..<grid { for col in 0..<grid {
            let x0 = col * image.width / grid, x1 = (col + 1) * image.width / grid
            let y0 = row * image.height / grid, y1 = (row + 1) * image.height / grid
            guard let tile = image.cropping(to: CGRect(x: x0, y: y0, width: x1-x0, height: y1-y0)) else { exit(1) }
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["en-US"]
            request.usesLanguageCorrection = false
            try VNImageRequestHandler(cgImage: tile, orientation: .up).perform([request])
            observations += (request.results ?? []).compactMap { observation in
                guard let candidate = observation.topCandidates(1).first else { return nil }
                let b = observation.boundingBox
                let sx = Double(x1-x0)/Double(image.width), sy = Double(y1-y0)/Double(image.height)
                let box = [Double(x0)/Double(image.width)+b.origin.x*sx,
                           Double(image.height-y1)/Double(image.height)+b.origin.y*sy,
                           b.width*sx,b.height*sy]
                return ["text": candidate.string, "confidence": candidate.confidence,
                        "box_normalized_bottom_left": box, "ocr_grid_cell": [col,row]]
            }
        } }
        output.append(["path": path, "ocr_grid": grid, "observations": observations])
    } catch {
        fputs("OCR error for \(path): \(error)\n", stderr)
        exit(1)
    }
}
let data = try JSONSerialization.data(withJSONObject: output, options: [.prettyPrinted,.sortedKeys])
FileHandle.standardOutput.write(data)
