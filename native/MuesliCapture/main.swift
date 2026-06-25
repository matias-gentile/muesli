// muesli-capture — captura el AUDIO DEL SISTEMA con ScreenCaptureKit (macOS 13+),
// sin BlackHole ni configuración de Audio MIDI. Escribe chunks WAV rotativos en un
// directorio, que después la app Python transcribe con el pipeline de siempre.
//
// Es el primer paso de la "opción 2": reemplazar la captura por driver virtual.
// El resto de la app (Python) NO se toca y sigue usando BlackHole por defecto.
//
// Uso:
//   muesli-capture --out-dir <dir> [--chunk-seconds 600] [--max-seconds 0]
//   --max-seconds 0 = sin límite (corta con Ctrl-C / SIGTERM).
//
// Salida (a stderr, una línea por evento) para que se pueda monitorear:
//   OUT_DIR <ruta>      READY            CHUNK chunk-000001.wav
//   LEVEL 0.0123        STOPPED          FATAL: ...      STREAM_ERROR ...

import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia

func emit(_ s: String) {
    FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
}

func argValue(_ name: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: name), i + 1 < a.count { return a[i + 1] }
    return nil
}

let outDirPath = argValue("--out-dir") ?? (NSTemporaryDirectory() + "muesli-capture")
let chunkSeconds = Double(argValue("--chunk-seconds") ?? "600") ?? 600
let maxSeconds = Double(argValue("--max-seconds") ?? "0") ?? 0

let outDir = URL(fileURLWithPath: outDirPath, isDirectory: true)
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

@available(macOS 13.0, *)
final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    let outDir: URL
    let chunkSeconds: Double
    var stream: SCStream?
    var audioFile: AVAudioFile?
    var chunkIndex = 0
    var chunkStart = Date()
    let queue = DispatchQueue(label: "muesli.capture.audio")
    var levelMax: Float = 0
    var lastLevelEmit = Date.distantPast

    init(outDir: URL, chunkSeconds: Double) {
        self.outDir = outDir
        self.chunkSeconds = chunkSeconds
        super.init()
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else {
            throw NSError(domain: "muesli", code: 1, userInfo:
                [NSLocalizedDescriptionKey: "No se encontró ninguna pantalla para capturar."])
        }
        let filter = SCContentFilter(display: display,
                                     excludingApplications: [], exceptingWindows: [])

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true   // no captures el audio de este proceso
        // Solo nos interesa el audio: mínimo de video (2x2 a 1 fps) para no gastar nada.
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.showsCursor = false
        config.queueDepth = 6

        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        // Algunas versiones de macOS piden también una salida de pantalla para arrancar.
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        try await stream.startCapture()
        self.stream = stream
        emit("READY")
    }

    func stop() async {
        try? await stream?.stopCapture()
        audioFile = nil   // cierra el último chunk
        emit("STOPPED")
    }

    private func openNewChunk(format: AVAudioFormat) {
        audioFile = nil
        chunkIndex += 1
        let url = outDir.appendingPathComponent(String(format: "chunk-%06d.wav", chunkIndex))
        do {
            audioFile = try AVAudioFile(forWriting: url, settings: format.settings)
            chunkStart = Date()
            emit("CHUNK \(url.lastPathComponent)")
        } catch {
            emit("ERROR abriendo chunk: \(error)")
        }
    }

    // SCStreamOutput: llega un buffer de audio (o de pantalla, que ignoramos).
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid else { return }
        do {
            try sampleBuffer.withAudioBufferList { abl, _ in
                guard var asbd = sampleBuffer.formatDescription?.audioStreamBasicDescription,
                      let fmt = AVAudioFormat(streamDescription: &asbd),
                      let pcm = AVAudioPCMBuffer(pcmFormat: fmt, bufferListNoCopy: abl.unsafePointer)
                else { return }

                if audioFile == nil || Date().timeIntervalSince(chunkStart) >= chunkSeconds {
                    openNewChunk(format: fmt)
                }
                do { try audioFile?.write(from: pcm) }
                catch { emit("ERROR escribiendo: \(error)") }

                emitLevel(pcm)
            }
        } catch {
            emit("ERROR audio buffer: \(error)")
        }
    }

    private func emitLevel(_ pcm: AVAudioPCMBuffer) {
        if pcm.format.commonFormat == .pcmFormatFloat32, let ch = pcm.floatChannelData {
            let frames = Int(pcm.frameLength)
            let chans = Int(pcm.format.channelCount)
            for c in 0..<chans {
                let p = ch[c]
                for i in 0..<frames { let v = abs(p[i]); if v > levelMax { levelMax = v } }
            }
        }
        let now = Date()
        if now.timeIntervalSince(lastLevelEmit) >= 0.5 {
            emit(String(format: "LEVEL %.4f", levelMax))
            levelMax = 0
            lastLevelEmit = now
        }
    }

    // SCStreamDelegate
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emit("STREAM_ERROR \(error)")
    }
}

guard #available(macOS 13.0, *) else {
    emit("FATAL: se requiere macOS 13 o superior (ScreenCaptureKit).")
    exit(1)
}

let cap = Capture(outDir: outDir, chunkSeconds: chunkSeconds)
emit("OUT_DIR \(outDir.path)")

Task {
    do {
        try await cap.start()
    } catch {
        emit("FATAL: no se pudo iniciar la captura: \(error)")
        emit("¿Le diste permiso de 'Grabación de pantalla' a la Terminal (o a la app)?")
        exit(1)
    }
}

// Frenado limpio con Ctrl-C / SIGTERM.
var signalSources: [DispatchSourceSignal] = []
func installSignal(_ sig: Int32) {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { Task { await cap.stop(); exit(0) } }
    src.resume()
    signalSources.append(src)
}
installSignal(SIGINT)
installSignal(SIGTERM)

if maxSeconds > 0 {
    DispatchQueue.main.asyncAfter(deadline: .now() + maxSeconds) {
        Task { await cap.stop(); exit(0) }
    }
}

RunLoop.main.run()
