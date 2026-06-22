"""Captura de audio en chunks rotativos (pensada para reuniones largas).

Graba el audio del sistema (+ micrófono, según el dispositivo) en segmentos WAV
de duración fija. Cada segmento, al cerrarse, se entrega vía on_chunk(index, path)
para que se transcriba en segundo plano mientras la grabación continúa. Así, al
detener, casi todo ya está transcripto y nada se pierde si algo se corta.
"""
from __future__ import annotations

import datetime
import queue
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import RECORDINGS_DIR, AUDIO_DEVICE_NAME, CHUNK_SECONDS


class ChunkedRecorder:
    def __init__(self, device_name: str = AUDIO_DEVICE_NAME, on_chunk=None,
                 chunk_seconds: int = CHUNK_SECONDS, out_dir: Path = RECORDINGS_DIR):
        self.device_index = self._find_device(device_name)
        info = sd.query_devices(self.device_index)
        self.samplerate = int(info["default_samplerate"])
        self.channels = int(info["max_input_channels"])
        self.on_chunk = on_chunk or (lambda i, p: None)
        self.chunk_limit = max(1, int(chunk_seconds * self.samplerate))

        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_dir = Path(out_dir) / f"meeting-{ts}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream = None
        self._writer_thread = None
        self.recording = False
        self.peak = 0.0  # amplitud máxima vista (0..1), para detectar silencio
        self.level = 0.0  # nivel instantáneo (0..1), para el medidor en vivo
        self._chunk_index = 0
        self._chunk_file = None
        self._chunk_path = None
        self._chunk_samples = 0

    # ---- dispositivos ----------------------------------------------------
    @staticmethod
    def list_input_devices():
        return [(i, d["name"], d["max_input_channels"])
                for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]

    def _find_device(self, name: str) -> int:
        for i, d in enumerate(sd.query_devices()):
            if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i
        raise RuntimeError(
            f"No encontré un dispositivo de entrada que contenga '{name}'. "
            f"Ejecuta `python audio_capture.py` para ver los disponibles."
        )

    # ---- grabación -------------------------------------------------------
    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        mono = indata.mean(axis=1, keepdims=True).astype(np.float32)
        lvl = float(np.abs(mono).max()) if mono.size else 0.0
        self.level = lvl
        if lvl > self.peak:
            self.peak = lvl
        self._q.put(mono.copy())

    def _open_chunk(self):
        self._chunk_path = self.session_dir / f"chunk_{self._chunk_index:03d}.wav"
        self._chunk_file = sf.SoundFile(
            self._chunk_path, mode="w", samplerate=self.samplerate,
            channels=1, subtype="PCM_16",
        )
        self._chunk_samples = 0

    def _close_chunk(self):
        if self._chunk_file is None:
            return
        self._chunk_file.close()
        self._chunk_file = None
        if self._chunk_samples > 0:
            self.on_chunk(self._chunk_index, self._chunk_path)
            self._chunk_index += 1
        else:  # chunk vacío (rotación justo al final): descartarlo
            try:
                self._chunk_path.unlink()
            except OSError:
                pass

    def _writer_loop(self):
        self._open_chunk()
        while self.recording or not self._q.empty():
            try:
                data = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            self._chunk_file.write(data)
            self._chunk_samples += len(data)
            if self._chunk_samples >= self.chunk_limit:
                self._close_chunk()
                self._open_chunk()
        self._close_chunk()  # cierra el último chunk (parcial)

    # ---- API pública -----------------------------------------------------
    def start(self):
        self.recording = True
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()
        self._stream = sd.InputStream(
            device=self.device_index, channels=self.channels,
            samplerate=self.samplerate, callback=self._callback,
        )
        self._stream.start()
        print(f"[audio] grabando en chunks -> {self.session_dir}")

    def stop(self) -> int:
        """Detiene, finaliza el último chunk y devuelve la cantidad total de chunks."""
        self.recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._writer_thread is not None:
            self._writer_thread.join()
            self._writer_thread = None
        print(f"[audio] grabación detenida: {self._chunk_index} chunks")
        return self._chunk_index


if __name__ == "__main__":
    print("Dispositivos de entrada disponibles:\n")
    for idx, name, ch in ChunkedRecorder.list_input_devices():
        print(f"  [{idx}] {name}  ({ch} canales)")
    print("\nUsa en .env -> AUDIO_DEVICE_NAME=<parte del nombre> de tu dispositivo agregado.")
