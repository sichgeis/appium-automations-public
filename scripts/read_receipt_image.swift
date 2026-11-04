// Lokaler ImageIO-/Vision-Leser. Keine Änderung der Quelldatei, kein Netzwerkaufruf.
import Foundation
import ImageIO
import Vision
import CryptoKit

if CommandLine.arguments.count != 2 { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      CGImageSourceGetCount(source) == 1,
      CGImageSourceGetStatus(source) == .statusComplete,
      CGImageSourceGetStatusAtIndex(source, 0) == .statusComplete,
      let image = CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary)
else { exit(3) }
guard image.width > 0, image.height > 0, image.width * image.height <= 100_000_000 else { exit(4) }
guard let pixels = image.dataProvider?.data else { exit(8) }
let pixelHash = SHA256.hash(data: pixels as Data).map { String(format: "%02x", $0) }.joined()
do {
    var observations: [[String: Any]] = []
    let tileHeight = 1800
    let overlap = 200
    for top in stride(from: 0, to: image.height, by: tileHeight - overlap) {
        let height = min(tileHeight, image.height - top)
        guard let tile = image.cropping(to: CGRect(x: 0, y: top, width: image.width, height: height)) else { exit(7) }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["de-DE", "en-US"]
        request.usesLanguageCorrection = false
        request.minimumTextHeight = 0
        try VNImageRequestHandler(cgImage: tile, options: [:]).perform([request])
        for observation in request.results ?? [] {
            guard let text = observation.topCandidates(1).first else { continue }
            let box = observation.boundingBox
            let middleFromTop = Double(top) + Double(height) * (1 - box.midY)
            // Überlappung erhält ganze Zeilen; jeder Zeilenmittelpunkt gehört genau einer Kachel.
            if top > 0 && middleFromTop < Double(top + overlap / 2) { continue }
            if top + height < image.height && middleFromTop >= Double(top + height - overlap / 2) { continue }
            observations.append(["text": text.string, "confidence": text.confidence,
                "x": box.minX, "y": 1 - (Double(top) + Double(height) * (1 - box.minY)) / Double(image.height),
                "width": box.width, "height": box.height * Double(height) / Double(image.height)])
        }
    }
    guard !observations.isEmpty else { exit(5) }
    let result: [String: Any] = ["complete": true, "width": image.width, "height": image.height,
        "format": (CGImageSourceGetType(source) as String?) ?? "unknown", "observations": observations,
        "pixel_sha256": pixelHash, "pixel_layout": [image.bitsPerComponent, image.bitsPerPixel, image.bytesPerRow]]
    let data = try JSONSerialization.data(withJSONObject: result)
    FileHandle.standardOutput.write(data)
} catch { exit(6) }
