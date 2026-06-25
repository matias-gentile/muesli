// muesli-capture — captura el AUDIO DEL SISTEMA (y, opcional, el MICRÓFONO) con
// ScreenCaptureKit, sin BlackHole ni configuración de Audio MIDI. Escribe chunks WAV
// rotativos que después la app Python transcribe.
//
// Con --include-mic (macOS 15+), grada el micrófono en archivos paralelos:
//   chunk-000001.wav  (sistema)   +   mic-000001.wav  (micrófono)
// Python mezcla cada par antes de transcribir (audio_mix.py).
//
// Uso:
//   muesli-capture --out-dir <dir> [--chunk-seconds 600] [--max-seconds 0] [--include-mic]
//   --max-seconds 0 = sin límite (corta con Ctrl-C / SIGTERM).
//
// Salida (stderr, una línea por evento):
//   OUT_DIR <ruta>   READY | READY mic   CHUNK chunk-000001.wav   LEVEL 0.0123
//   STOPPED          FATAL: ...          STREAM_ERROR ...         PERMISO: ...

import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia
import CoreGraphics

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
let includeMic = CommandLine.arguments.contains("--include-mic")

let outDir = URL(fileURLWithPath: outDirPath, isDirectory: true)
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

@available(macOS 13.0, *)
final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    let outDir: URL
    let chunkSeconds: Double
    let includeMic: Bool
    var stream: SCStream?

    var sysFile: AVAudioFile?
    var micFile: AVAudioFile?
    var chunkIndex = 0
    var chunkStart = Date()

    let queue = DispatchQueue(label: "muesli.capture.audio")
    var levelMax: Float = 0
    var lastLevelEmit = Date.distantPast

    init(outDir: URL, chunkSeconds: Double, includeMic: Bool) {
        self.outDir = outDir
        self.chunkSeconds = chunkSeconds
        self.includeMic = includeMic
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

        var micOn = includeMic
        if micOn {
            if #available(macOS 15.0, *) {
                config.captureMicrophone = true   // micrófono sincronizado por SCK
            } else {
                emit("AVISO: el micrófono por ScreenCaptureKit requiere macOS 15; grabo solo el sistema.")
                micOn = false
            }
        }

        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        // Algunas versiones de macOS piden también una salida de pantalla para arrancar.
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        if micOn, #available(macOS 15.0, *) {
            try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: queue)
        }
        try await stream.startCapture()
        self.stream = stream
        emit(micOn ? "READY mic" : "READY")
    }

    func stop() async {
        try? await stream?.stopCapture()
        sysFile = nil    // cierra/flushea el último chunk de sistema
        micFile = nil    // y el de micrófono
        emit("STOPPED")
    }

    private func openWav(prefix: String, index: Int, format: AVAudioFormat) -> AVAudioFile? {
        let url = outDir.appendingPathComponent(String(format: "\(prefix)-%06d.wav", index))
        // WAV PCM 16-bit entrelazado en disco; en memoria seguimos el formato de la fuente.
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: format.channelCount,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        do {
            return try AVAudioFile(forWriting: url, settings: settings,
                                   commonFormat: format.commonFormat,
                                   interleaved: format.isInterleaved)
        } catch {
            emit("ERROR abriendo \(prefix): \(error)")
            return nil
        }
    }

    // Rota AMBOS archivos a la vez (los cierra/flushea antes de abrir el siguiente).
    private func rotate(sysFormat: AVAudioFormat) {
        sysFile = nil
        micFile = nil
        chunkIndex += 1
        chunkStart = Date()
        sysFile = openWav(prefix: "chunk", index: chunkIndex, format: sysFormat)
        if sysFile != nil {
            emit("CHUNK " + String(format: "chunk-%06d.wav", chunkIndex))
        }
    }

    private func accumulatePeak(_ pcm: AVAudioPCMBuffer) {
        if pcm.format.commonFormat == .pcmFormatFloat32, let ch = pcm.floatChannelData {
            let frames = Int(pcm.frameLength)
            let chans = Int(pcm.format.channelCount)
            for c in 0..<chans {
                let p = ch[c]
                for i in 0..<frames { let v = abs(p[i]); if v > levelMax { levelMax = v } }
            }
        }
    }

    private func emitLevelIfDue() {
        let now = Date()
        if now.timeIntervalSince(lastLevelEmit) >= 0.5 {
            emit(String(format: "LEVEL %.4f", levelMax))
            levelMax = 0
            lastLevelEmit = now
        }
    }

    private func pcmFrom(_ sampleBuffer: CMSampleBuffer, _ body: (AVAudioPCMBuffer) -> Void) {
        do {
            try sampleBuffer.withAudioBufferList { abl, _ in
                guard var asbd = sampleBuffer.formatDescription?.audioStreamBasicDescription,
                      let fmt = AVAudioFormat(streamDescription: &asbd),
                      let pcm = AVAudioPCMBuffer(pcmFormat: fmt, bufferListNoCopy: abl.unsafePointer)
                else { return }
                body(pcm)
            }
        } catch {
            emit("ERROR audio buffer: \(error)")
        }
    }

    private func handleSystem(_ sampleBuffer: CMSampleBuffer) {
        pcmFrom(sampleBuffer) { pcm in
            if sysFile == nil || Date().timeIntervalSince(chunkStart) >= chunkSeconds {
                rotate(sysFormat: pcm.format)
            }
            do { try sysFile?.write(from: pcm) } catch { emit("ERROR escribiendo sys: \(error)") }
            accumulatePeak(pcm)
            emitLevelIfDue()
        }
    }

    private func handleMic(_ sampleBuffer: CMSampleBuffer) {
        if chunkIndex < 1 { return }   // esperá a que el sistema abra el primer chunk
        pcmFrom(sampleBuffer) { pcm in
            if micFile == nil {
                micFile = openWav(prefix: "mic", index: chunkIndex, format: pcm.format)
            }
            do { try micFile?.write(from: pcm) } catch { emit("ERROR escribiendo mic: \(error)") }
            accumulatePeak(pcm)   // el nivel combina sistema + micrófono (para el auto-stop)
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard sampleBuffer.isValid else { return }
        if type == .audio {
            handleSystem(sampleBuffer)
        } else {
            if #available(macOS 15.0, *) {
                if type == .microphone { handleMic(sampleBuffer) }
            }
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emit("STREAM_ERROR \(error)")
    }
}

guard #available(macOS 13.0, *) else {
    emit("FATAL: se requiere macOS 13 o superior (ScreenCaptureKit).")
    exit(1)
}

// Permiso de Grabación de pantalla (TCC).
if !CGPreflightScreenCaptureAccess() {
    emit("PERMISO: falta 'Grabación de pantalla'. Pidiéndolo al sistema…")
    let granted = CGRequestScreenCaptureAccess()
    if !granted {
        emit("FATAL: la app desde la que corrés esto no tiene permiso de 'Grabación de pantalla'.")
        emit("Arreglo:")
        emit("  1) Ajustes del Sistema → Privacidad y seguridad → Grabación de pantalla.")
        emit("  2) Activá (o agregá con +) la app que usás para correr esto:")
        emit("     Terminal.app, iTerm, o 'Code' si es la terminal de VS Code.")
        emit("  3) IMPORTANTE: cerrá esa app por completo (Cmd+Q) y volvé a abrirla.")
        emit("  4) Reintentá. (Un primer 'Deny' deja el permiso bloqueado: hay que activarlo a mano.)")
        exit(1)
    }
    emit("PERMISO: concedido.")
}

if includeMic {
    emit("MIC: pedido. Necesita permiso de Micrófono para la app que corre esto")
    emit("     (Ajustes → Privacidad y seguridad → Micrófono → activá tu terminal y reabrila).")
}

let cap = Capture(outDir: outDir, chunkSeconds: chunkSeconds, includeMic: includeMic)
emit("OUT_DIR \(outDir.path)")

Task {
    do {
        try await cap.start()
    } catch {
        emit("FATAL: no se pudo iniciar la captura: \(error)")
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
