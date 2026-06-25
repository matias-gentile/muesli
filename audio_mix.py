"""Mezcla dos WAV (audio del sistema + micrófono) en un único WAV mono.

Lo usa el backend ScreenCaptureKit cuando además se captura el micrófono: el helper
nativo escribe sistema y mic por separado, y acá los combinamos antes de transcribir.
Sin dependencias pesadas: módulo `wave` (stdlib) + numpy. Salida mono 16-bit a la
frecuencia del audio del sistema (para Whisper, mono alcanza y pesa menos).
"""
from __future__ import annotations

import wave

import numpy as np


def _read_wav_mono(path):
    """Devuelve (muestras_float[-1..1], samplerate). Downmix a mono si hace falta."""
    with wave.open(str(path), "rb") as w:
        ch, sr, sw, n = (w.getnchannels(), w.getframerate(),
                         w.getsampwidth(), w.getnframes())
        raw = w.readframes(n)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise ValueError(f"sampwidth no soportado: {sw}")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def _resample(x, sr_from, sr_to):
    """Remuestreo por interpolación lineal (suficiente para voz)."""
    if sr_from == sr_to or len(x) == 0:
        return x
    n_to = int(round(len(x) * sr_to / sr_from))
    if n_to <= 0:
        return np.zeros(0, dtype=np.float32)
    xp = np.linspace(0.0, 1.0, num=len(x), endpoint=False)
    xq = np.linspace(0.0, 1.0, num=n_to, endpoint=False)
    return np.interp(xq, xp, x).astype(np.float32)


def mix_wavs(sys_path, mic_path, out_path, mic_gain=1.0, sys_gain=1.0):
    """Mezcla sistema + micrófono en un WAV mono 16-bit a la frecuencia del sistema.

    - Lleva ambos a mono y a la misma frecuencia (la del sistema).
    - Suma con ganancias opcionales; si el pico se pasa de 1.0, normaliza (anti-clip).
    - Rellena con silencio el más corto para que duren igual.
    """
    sysd, sysr = _read_wav_mono(sys_path)
    micd, micr = _read_wav_mono(mic_path)
    micd = _resample(micd, micr, sysr) * mic_gain
    sysd = sysd * sys_gain

    n = max(len(sysd), len(micd))
    sysd = np.pad(sysd, (0, n - len(sysd)))
    micd = np.pad(micd, (0, n - len(micd)))
    mixed = sysd + micd

    peak = float(np.max(np.abs(mixed))) if n else 0.0
    if peak > 1.0:
        mixed = mixed / peak  # anti-clip: normaliza si se pasó

    out = np.clip(mixed * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sysr)
        w.writeframes(out.tobytes())
    return str(out_path)
