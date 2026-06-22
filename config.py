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
# Filtro de detección de voz (VAD) de Whisper. Por defecto OFF para no descartar
# audio bajo o sin pausas claras. Poné WHISPER_VAD=1 si ves texto "alucinado"
# en grabaciones con silencios.
WHISPER_VAD = os.getenv("WHISPER_VAD", "0") == "1"

# Dispositivo de entrada para "salida + micrófono": el dispositivo AGREGADO
# (BlackHole + micrófono) que creaste en Audio MIDI Setup.
AUDIO_DEVICE_NAME = os.getenv("AUDIO_DEVICE_NAME", "Aggregate")

# Dispositivo de entrada para "solo salida del sistema": BlackHole directo
# (captura únicamente lo que suena en el sistema, sin tu micrófono).
AUDIO_DEVICE_OUTPUT_ONLY = os.getenv("AUDIO_DEVICE_OUTPUT_ONLY", "BlackHole")

# Duración de cada segmento de grabación, en segundos. Para reuniones largas:
# los chunks se transcriben en segundo plano a medida que se completan, así el
# procesado final es rápido y no se pierde nada si algo se corta. 600 = 10 min.
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "600"))

# Notion (opcional): si ambos están definidos, cada grabación se sincroniza
# como una página en la base de datos indicada.
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
