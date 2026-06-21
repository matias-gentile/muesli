"""Captura de audio del Mac (audio del sistema + micrófono).

Graba desde un dispositivo de entrada agregado creado en Audio MIDI Setup
que combine "BlackHole 2ch" (audio del sistema) con tu micrófono.
Mezcla todos los canales a mono y los escribe a un WAV.
"""
import datetime
import queue
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import RECORDINGS_DIR, AUDIO_DEVICE_NAME


class Recorder:
    def __init__(self, device_name: str = AUDIO_DEVICE_NAME, out_dir: Path = RECORDINGS_DIR):
        self.device_index = self._find_device(device_name)
        info = sd.query_devices(self.device_index)
        self.samplerate = int(info["default_samplerate"])
        self.channels = int(info["max_input_channels"])
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(exist_ok=True)

        self._q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream = None
        self._file = None
        self._writer_thread = None
        self.recording = False
        self.path = None

    # ---- utilidades de dispositivos -------------------------------------
    @staticmethod
    def list_input_devices():
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append((i, d["name"], d["max_input_channels"]))
        return devices

    def _find_device(self, name: str) -> int:
        for i, d in enumerate(sd.query_devices()):
            if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i
        raise RuntimeError(
            f"No encontré un dispositivo de entrada que contenga '{name}'. "
            f"Ejecuta `python audio_capture.py` para ver los disponibles."
        )

    # ---- callbacks de grabación -----------------------------------------
    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        # Mezcla todos los canales (sistema + mic) a mono
        mono = indata.mean(axis=1, keepdims=True).astype(np.float32)
        self._q.put(mono.copy())

    def _writer_loop(self):
        while self.recording or not self._q.empty():
            try:
                data = self._q.get(timeout=0.1)
                self._file.write(data)
            except queue.Empty:
                continue

    # ---- API pública -----------------------------------------------------
    def start(self) -> Path:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.out_dir / f"meeting-{ts}.wav"
        self._file = sf.SoundFile(
            self.path, mode="w", samplerate=self.samplerate,
            channels=1, subtype="PCM_16",
        )
        self.recording = True
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()
        self._stream = sd.InputStream(
            device=self.device_index,
            channels=self.channels,
            samplerate=self.samplerate,
            callback=self._callback,
        )
        self._stream.start()
        print(f"[audio] grabando -> {self.path}")
        return self.path

    def stop(self) -> Path:
        self.recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._writer_thread is not None:
            self._writer_thread.join()
            self._writer_thread = None
        if self._file is not None:
            self._file.close()
            self._file = None
        print(f"[audio] guardado -> {self.path}")
        return self.path


if __name__ == "__main__":
    print("Dispositivos de entrada disponibles:\n")
    for idx, name, ch in Recorder.list_input_devices():
        print(f"  [{idx}] {name}  ({ch} canales)")
    print(
        "\nUsa en .env -> AUDIO_DEVICE_NAME=<parte del nombre> "
        "de tu dispositivo agregado (BlackHole + micrófono)."
    )
