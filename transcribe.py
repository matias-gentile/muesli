"""Transcripción local con faster-whisper.

El modelo se descarga la primera vez que se usa y queda cacheado. Si cambiás el
modelo desde el panel de Configuración, se recarga al siguiente uso.
En Apple Silicon corre en CPU con cuantización int8 (suficientemente rápido
para 'base'/'small').
"""
from faster_whisper import WhisperModel

import config

_model = None
_model_name = None


def reset_model():
    """Fuerza recargar el modelo (p. ej. tras cambiar WHISPER_MODEL en Configuración)."""
    global _model, _model_name
    _model = None
    _model_name = None


def _get_model() -> WhisperModel:
    global _model, _model_name
    want = config.get("WHISPER_MODEL")
    if _model is None or _model_name != want:
        print(f"[whisper] cargando modelo '{want}'...")
        _model = WhisperModel(want, device="cpu", compute_type="int8")
        _model_name = want
    return _model


def transcribe(wav_path) -> str:
    """Devuelve la transcripción completa como texto plano."""
    model = _get_model()
    segments, info = model.transcribe(str(wav_path), vad_filter=config.get_bool("WHISPER_VAD"))
    print(f"[whisper] idioma detectado: {info.language} (p={info.language_probability:.2f})")
    parts = [seg.text.strip() for seg in segments]
    return " ".join(p for p in parts if p).strip()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python transcribe.py <archivo.wav>")
        raise SystemExit(1)
    print(transcribe(sys.argv[1]))
