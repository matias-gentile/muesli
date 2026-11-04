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

import modelos

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
    "CLAUDE_MODEL": os.getenv("CLAUDE_MODEL", modelos.POR_DEFECTO),
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
    # Avisar (notificación) cuando otra app empieza a usar el micrófono ≈ estás en
    # una llamada. Solo avisa: nunca graba solo.
    "CALL_DETECT": os.getenv("CALL_DETECT", "1"),
    "NOTION_API_KEY": os.getenv("NOTION_API_KEY", ""),
    "NOTION_DATABASE_ID": os.getenv("NOTION_DATABASE_ID", ""),
    # Memoria, el server de casa que junta las charlas de todas las Macs (ver server_sync.py).
    # Se conectan desde Configuración → «Server de casa» con un código; no se editan a mano.
    "MEMORIA_URL": os.getenv("MEMORIA_URL", ""),
    "MEMORIA_TOKEN": os.getenv("MEMORIA_TOKEN", ""),
    "MEMORIA_DEVICE": "",   # nombre de esta Mac en Memoria
    "MEMORIA_AMBITO": "",   # carpeta donde caen sus charlas: personal o trabajo
}

# Claves que son secretos (no se devuelven en claro al frontend).
SECRET_KEYS = {"ANTHROPIC_API_KEY", "NOTION_API_KEY", "MEMORIA_TOKEN"}

# Claves que maneja la propia app (server_sync), no el formulario de Configuración.
MANAGED_KEYS = {"MEMORIA_URL", "MEMORIA_TOKEN", "MEMORIA_DEVICE", "MEMORIA_AMBITO"}

_overrides = {}
if SETTINGS_PATH.exists():
    try:
        _overrides = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        _overrides = {}


def get(key, default=None):
    v = _overrides.get(key)
    if v in (None, ""):
        v = _DEFAULTS.get(key, default)
        if v is None:
            v = default
    if key == "CLAUDE_MODEL":
        v = modelos.actualizar(v)  # quien tenía un modelo de antes pasa al mismo nivel, generación actual
    return v


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
    return {k: get(k) for k in _DEFAULTS if k not in MANAGED_KEYS}


def _save():
    SETTINGS_PATH.write_text(json.dumps(_overrides, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        SETTINGS_PATH.chmod(0o600)  # tiene claves: que solo lo lea tu usuario
    except OSError:
        pass


def update(new: dict, managed: bool = False):
    """Guarda en settings.json solo las claves conocidas (ignora secretos vacíos).
    Las de MANAGED_KEYS solo se guardan si las manda la propia app (managed=True)."""
    for k, v in new.items():
        if k not in _DEFAULTS or (k in MANAGED_KEYS and not managed):
            continue
        # No pisar un secreto ya configurado con un valor vacío.
        if k in SECRET_KEYS and (v is None or str(v).strip() == ""):
            continue
        _overrides[k] = v
    _save()


def clear(keys):
    """Borra claves de settings.json (vuelven a su valor por defecto)."""
    for k in keys:
        _overrides.pop(k, None)
    _save()


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
