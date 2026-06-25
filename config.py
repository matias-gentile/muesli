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
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv()

RECORDINGS_DIR = BASE_DIR / "recordings"
NOTES_DIR = BASE_DIR / "notes"
DB_PATH = BASE_DIR / "notes.db"
SETTINGS_PATH = BASE_DIR / "settings.json"

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
    "CHUNK_SECONDS": os.getenv("CHUNK_SECONDS", "600"),
    "AUTO_STOP_SILENCE_MIN": os.getenv("AUTO_STOP_SILENCE_MIN", "15"),
    "MAX_RECORDING_MIN": os.getenv("MAX_RECORDING_MIN", "180"),
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
