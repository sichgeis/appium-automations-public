// Fordert ausschließlich den lokalen Download einer vorhandenen iCloud-Datei an.
// Kein Verschieben/Löschen und keine Datei-Inhalte auf stdout/stderr.
import Foundation
if CommandLine.arguments.count != 2 { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
do {
    let values = try url.resourceValues(forKeys: [.isUbiquitousItemKey])
    guard values.isUbiquitousItem == true else { exit(3) }
    try FileManager.default.startDownloadingUbiquitousItem(at: url)
    exit(0)
} catch { exit(4) }
