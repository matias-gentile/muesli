"""Backend de captura alternativo: maneja el helper nativo `muesli-capture`
(ScreenCaptureKit) en vez de sounddevice + BlackHole. Captura el audio del SISTEMA
sin driver virtual ni Audio MIDI.

Expone la MISMA interfaz que `ChunkedRecorder` (start/stop/level/peak/paused/
silent_seconds/recording/session_dir + callback on_chunk), para que `app.py` lo pueda
usar indistintamente. Por ahora NO está cableado en app.py: el flujo BlackHole sigue
siendo el de siempre.

Cómo funciona: lanza el binario como subproceso y lee su salida (stderr) en un hilo:
  - `LEVEL x`  -> actualiza level/peak y acumula silencio (para el auto-stop)
  - `CHUNK f`  -> el helper abrió un chunk nuevo, así que el ANTERIOR ya está cerrado
                 y completo -> se encola para transcribir
  - al terminar el proceso (stop) -> se encola el último chunk

Limitaciones de esta primera versión:
  - Solo audio del sistema (todavía sin micrófono).
  - Pausa/reanudar no está implementado en el helper: pause()/resume() son no-ops.

Prueba rápida (en la Mac, con el helper ya compilado en native/):
    python screen_capture.py 15
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from config import RECORDINGS_DIR, BASE_DIR
from audio_mix import mix_wavs

# Mismo umbral que audio_capture.py: por debajo se considera "silencio" (auto-stop).
SILENCE_LEVEL = 0.04

# Ubicación del helper nativo: dentro del .app cuando está empaquetado, o en native/ en dev.
if getattr(sys, "frozen", False):
    _HELPER_BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    DEFAULT_HELPER = Path(_HELPER_BASE) / "muesli-capture"
else:
    DEFAULT_HELPER = BASE_DIR / "native" / "muesli-capture"

_LEVEL_RE = re.compile(r"^LEVEL\s+([0-9.]+)")
_CHUNK_RE = re.compile(r"^CHUNK\s+(\S+)")


class ScreenCaptureRecorder:
    def __init__(self, on_chunk=None, chunk_seconds: int = 600,
                 out_dir: Path = RECORDINGS_DIR, helper_path=None, include_mic: bool = False):
        self.on_chunk = on_chunk or (lambda i, p: None)
        self.chunk_seconds = chunk_seconds
        self.include_mic = include_mic
        self.helper_path = Path(helper_path or os.getenv("MUESLI_CAPTURE_BIN") or DEFAULT_HELPER)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = Path(out_dir) / f"sck-{ts}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.recording = False
        self.paused = False          # no soportado por el helper aún (no-op)
        self.level = 0.0
        self.peak = 0.0
        self.silent_seconds = 0.0

        self._proc = None
        self._reader = None
        self._current_chunk = None   # .wav que el helper está escribiendo ahora
        self._enqueued = 0
        self._last_level_ts = None

    # ---- interfaz tipo ChunkedRecorder ----------------------------------
    def start(self):
        if not self.helper_path.exists():
            raise RuntimeError(
                f"No encuentro el helper de captura en {self.helper_path}. "
                f"Compilalo con:  cd native && ./build.sh")
        self.recording = True
        self.silent_seconds = 0.0
        self._last_level_ts = time.time()
        cmd = [str(self.helper_path),
               "--out-dir", str(self.session_dir),
               "--chunk-seconds", str(self.chunk_seconds)]
        if self.include_mic:
            cmd.append("--include-mic")
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def stop(self) -> int:
        if not self.recording:
            return self._enqueued
        self.recording = False
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()   # SIGTERM -> el helper cierra el último chunk y sale
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._reader:
            self._reader.join(timeout=5)   # espera a que encole el último chunk
        self.level = 0.0
        return self._enqueued

    def pause(self):
        self.paused = True    # límite v1: el helper sigue capturando

    def resume(self):
        self.paused = False

    # ---- interno: parseo de la salida del helper ------------------------
    def _read_loop(self):
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for line in proc.stderr:
            line = line.strip()
            m = _LEVEL_RE.match(line)
            if m:
                self._on_level(float(m.group(1)))
                continue
            m = _CHUNK_RE.match(line)
            if m:
                self._on_new_chunk(m.group(1))
                continue
            if line:
                print(f"[sck] {line}")
        # EOF (el proceso terminó): cerrá el último chunk pendiente.
        self._finalize_current()

    def _on_level(self, lvl: float):
        self.level = lvl
        if lvl > self.peak:
            self.peak = lvl
        now = time.time()
        dt = now - (self._last_level_ts or now)
        self._last_level_ts = now
        if lvl < SILENCE_LEVEL:
            self.silent_seconds += dt
        else:
            self.silent_seconds = 0.0

    def _on_new_chunk(self, name: str):
        # Abrir un chunk nuevo => el anterior ya está cerrado y completo.
        if self._current_chunk is not None:
            self._emit_chunk(self._current_chunk)
        self._current_chunk = name

    def _finalize_current(self):
        if self._current_chunk is not None:
            self._emit_chunk(self._current_chunk)
            self._current_chunk = None

    def _emit_chunk(self, name: str):
        self._enqueued += 1
        sys_path = self.session_dir / name
        out_path = sys_path
        # Si grabamos micrófono, mezclá el chunk de sistema con su par de mic.
        if self.include_mic:
            mic_path = self.session_dir / name.replace("chunk-", "mic-")
            if mic_path.exists():
                mixed = self.session_dir / name.replace("chunk-", "mix-")
                try:
                    mix_wavs(sys_path, mic_path, mixed)
                    out_path = mixed
                except Exception as e:
                    print(f"[sck] mezcla falló ({e}); uso solo el sistema")
        try:
            self.on_chunk(self._enqueued, str(out_path))
        except Exception as e:
            print(f"[sck] on_chunk error: {e}")


# ---- modo de prueba independiente -----------------------------------------
if __name__ == "__main__":
    import sys

    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    want_mic = "mic" in sys.argv[2:]

    def cb(i, p):
        size = os.path.getsize(p) if os.path.exists(p) else "??"
        print(f">>> chunk {i} listo: {p} ({size} bytes)")

    rec = ScreenCaptureRecorder(on_chunk=cb, chunk_seconds=5, include_mic=want_mic)
    print(f"Helper:  {rec.helper_path}")
    print(f"Carpeta: {rec.session_dir}")
    print(f"Micrófono: {'SÍ' if want_mic else 'no'}  ·  Grabando {secs}s (Ctrl-C para cortar)…")
    rec.start()
    try:
        t0 = time.time()
        while time.time() - t0 < secs:
            time.sleep(1)
            print(f"  level={rec.level:.3f}  peak={rec.peak:.3f}  silent={rec.silent_seconds:.1f}s")
    except KeyboardInterrupt:
        pass
    n = rec.stop()
    print(f"Listo. Chunks encolados: {n}. Carpeta: {rec.session_dir}")
