"""Configuración central de la app."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
RECORDINGS_DIR = BASE_DIR / "recordings"
NOTES_DIR = BASE_DIR / "notes"
DB_PATH = BASE_DIR / "notes.db"

RECORDINGS_DIR.mkdir(exist_ok=True)
NOTES_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# Substring para localizar el dispositivo de entrada agregado
# (BlackHole + micrófono) en Audio MIDI Setup.
AUDIO_DEVICE_NAME = os.getenv("AUDIO_DEVICE_NAME", "Aggregate")

# Notion (opcional): si ambos están definidos, cada grabación se sincroniza
# como una página en la base de datos indicada.
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
