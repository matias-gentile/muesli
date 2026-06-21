"""Transcripción local con faster-whisper.

El modelo se descarga la primera vez que se usa y queda cacheado.
En Apple Silicon corre en CPU con cuantización int8 (suficientemente rápido
para 'base'/'small'). Para algo aún más veloz en Mac, mira la nota sobre
mlx-whisper en el README.
"""
from faster_whisper import WhisperModel

from config import WHISPER_MODEL

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(f"[whisper] cargando modelo '{WHISPER_MODEL}'...")
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(wav_path) -> str:
    """Devuelve la transcripción completa como texto plano."""
    model = _get_model()
    segments, info = model.transcribe(str(wav_path), vad_filter=True)
    print(f"[whisper] idioma detectado: {info.language} (p={info.language_probability:.2f})")
    parts = [seg.text.strip() for seg in segments]
    return " ".join(p for p in parts if p).strip()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python transcribe.py <archivo.wav>")
        raise SystemExit(1)
    print(transcribe(sys.argv[1]))
