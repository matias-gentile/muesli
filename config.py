"""Configuración central de la app.

Los valores salen de tres capas, en orden de prioridad:
  1) settings.json  (lo que el usuario guarda desde el panel de Configuración)
  2) variables de entorno / .env
  3) valores por defecto

Usá config.get("CLAVE") para leer en vivo (toma cambios sin reiniciar) y
config.update({...}) para guardar desde el panel.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv()

# Datos del usuario (grabaciones, notas, settings). En desarrollo viven en la carpeta del
# proyecto; cuando la app está empaquetada (.app) van a una carpeta ESCRIBIBLE del usuario
# (dentro del bundle sería de solo lectura y se perdería al actualizar).
if getattr(sys, "frozen", False):
    DATA_DIR = Path.home() / "Library" / "Application Support" / "Muesli"
else:
    DATA_DIR = BASE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

RECORDINGS_DIR = DATA_DIR / "recordings"
NOTES_DIR = DATA_DIR / "notes"
DB_PATH = DATA_DIR / "notes.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

RECORDINGS_DIR.mkdir(exist_ok=True)
NOTES_DIR.mkdir(exist_ok=True)

# Claves configurables y su valor por defecto (desde .env o hardcodeado).
_DEFAULTS = {
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    "CLAUDE_MODEL": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    "WHISPER_MODEL": os.getenv("WHISPER_MODEL", "base"),
    "WHISPER_VAD": os.getenv("WHISPER_VAD", "0"),
    "AUDIO_DEVICE_NAME": os.getenv("AUDIO_DEVICE_NAME", "Aggregate"),
    "AUDIO_DEVICE_OUTPUT_ONLY": os.getenv("AUDIO_DEVICE_OUTPUT_ONLY", "BlackHole"),
    # Backend de captura: "blackhole" (sounddevice + driver virtual, sistema+mic) o
    # "screencapturekit" (helper nativo, audio del sistema sin configurar Audio MIDI).
    # Es el único backend que expone la app (BlackHole queda solo para power users vía .env).
    "CAPTURE_BACKEND": os.getenv("CAPTURE_BACKEND", "screencapturekit"),
    "CHUNK_SECONDS": os.getenv("CHUNK_SECONDS", "600"),
    "AUTO_STOP_SILENCE_MIN": os.getenv("AUTO_STOP_SILENCE_MIN", "15"),
    "MAX_RECORDING_MIN": os.getenv("MAX_RECORDING_MIN", "180"),
    # Si está en "1", borra el audio (.wav) automáticamente al terminar de transcribir.
    "AUTO_PURGE_AUDIO": os.getenv("AUTO_PURGE_AUDIO", "0"),
    # Presupuesto mensual estimado para la API de Claude (USD). "0" = sin presupuesto.
    "MONTHLY_BUDGET_USD": os.getenv("MONTHLY_BUDGET_USD", "0"),
    "NOTION_API_KEY": os.getenv("NOTION_API_KEY", ""),
    "NOTION_DATABASE_ID": os.getenv("NOTION_DATABASE_ID", ""),
}

# Claves que son secretos (no se devuelven en claro al frontend).
SECRET_KEYS = {"ANTHROPIC_API_KEY", "NOTION_API_KEY"}

_overrides = {}
if SETTINGS_PATH.exists():
    try:
        _overrides = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        _overrides = {}


def get(key, default=None):
    v = _overrides.get(key)
    if v not in (None, ""):
        return v
    d = _DEFAULTS.get(key, default)
    return d if d is not None else default


def get_bool(key):
    return str(get(key)).strip().lower() in ("1", "true", "yes", "on")


def get_int(key, default=0):
    try:
        return int(get(key))
    except (TypeError, ValueError):
        return default


def get_float(key, default=0.0):
    try:
        return float(get(key))
    except (TypeError, ValueError):
        return default


def get_all():
    return {k: get(k) for k in _DEFAULTS}


def update(new: dict):
    """Guarda en settings.json solo las claves conocidas (ignora secretos vacíos)."""
    for k, v in new.items():
        if k not in _DEFAULTS:
            continue
        # No pisar un secreto ya configurado con un valor vacío.
        if k in SECRET_KEYS and (v is None or str(v).strip() == ""):
            continue
        _overrides[k] = v
    SETTINGS_PATH.write_text(json.dumps(_overrides, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Constantes de compatibilidad (valor inicial; para live usar config.get()). ---
ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = get("CLAUDE_MODEL")
WHISPER_MODEL = get("WHISPER_MODEL")
WHISPER_VAD = get_bool("WHISPER_VAD")
AUDIO_DEVICE_NAME = get("AUDIO_DEVICE_NAME")
AUDIO_DEVICE_OUTPUT_ONLY = get("AUDIO_DEVICE_OUTPUT_ONLY")
CHUNK_SECONDS = get_int("CHUNK_SECONDS", 600)
NOTION_API_KEY = get("NOTION_API_KEY")
NOTION_DATABASE_ID = get("NOTION_DATABASE_ID")
