#!/usr/bin/env swift

import AppKit
import Foundation
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

var output: [String: String] = [:]

for argument in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: argument)
    guard let image = NSImage(contentsOf: url) else {
        fail("image unavailable")
    }
    var proposedRect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
        fail("image conversion failed")
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ja-JP", "en-US"]
    request.usesLanguageCorrection = true

    do {
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
    } catch {
        fail("recognition failed")
    }

    let lines = (request.results ?? []).compactMap { observation in
        observation.topCandidates(1).first?.string
    }
    output[url.lastPathComponent] = lines.joined(separator: "\n")
}

guard JSONSerialization.isValidJSONObject(output),
      let data = try? JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]) else {
    fail("serialization failed")
}
FileHandle.standardOutput.write(data)
