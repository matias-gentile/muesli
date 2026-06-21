# Muesli — Notas de reuniones (para uso personal)

Graba el **audio del sistema + tu micrófono** en un Mac, transcribe localmente con
Whisper y genera un resumen estructurado con la API de Claude. Tus notas manuales
guían el énfasis del resumen. Todo se guarda como Markdown.

```
Audio sistema + micrófono → BlackHole (agregado) → WAV
        → faster-whisper (transcripción) 
        → Claude (resumen + action items, mezclado con tus notas)
        → Markdown + índice SQLite
```

---

## 1. Captura de audio en macOS (el paso clave)

macOS no deja grabar el audio del sistema directamente. Se resuelve con
**BlackHole**, un driver de audio virtual gratuito.

### Instalar BlackHole
```bash
brew install blackhole-2ch
```
(o descárgalo de https://existential.audio/blackhole/)

### Configurar en "Audio MIDI Setup"
Abre la app **Configuración de Audio MIDI** (Audio MIDI Setup).

**a) Multi-Output Device** — para *oír* el audio mientras se graba:
1. Botón `+` abajo a la izquierda → *Crear dispositivo de salida múltiple*.
2. Marca **BlackHole 2ch** y tu salida normal (p. ej. *MacBook Speakers*).
3. Esto será tu **salida** durante las reuniones (así el audio va a tus oídos
   *y* a BlackHole).

**b) Aggregate Device** — la *entrada* que graba la app:
1. Botón `+` → *Crear dispositivo agregado*.
2. Marca **BlackHole 2ch** (audio de la reunión) **y** tu **micrófono**
   (p. ej. *MacBook Microphone*).
3. Ponle un nombre. Por defecto la app busca uno que contenga `Aggregate`
   (cámbialo en `.env` con `AUDIO_DEVICE_NAME`).

### Antes de cada reunión
- **Salida del sistema** → el *Multi-Output Device* (en Ajustes de Sonido o desde
  el menú de volumen).
- La app graba sola desde el *Aggregate Device*. BlackHole captura lo que dicen
  los demás y el micrófono te captura a ti; se mezclan a una pista mono.

> Verifica qué dispositivos ve Python:
> ```bash
> python audio_capture.py
> ```

---

## 2. Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # añade tu ANTHROPIC_API_KEY
```

La primera vez que transcribas, Whisper descargará el modelo (queda cacheado).

> **Permisos**: la primera grabación pedirá acceso al micrófono. Concédelo en
> *Ajustes del Sistema → Privacidad y seguridad → Micrófono* para tu terminal.

---

## 3. Uso

```bash
python app.py
```
Abre **http://localhost:5001**

1. Escribe un título.
2. **Grabar** → toma notas en el textarea mientras hablan.
3. **Detener y resumir** → transcribe + resume + guarda.
4. El resumen aparece en pantalla; las reuniones pasadas quedan en la barra lateral
   y como `.md` en `notes/`.

---

## 4. Configuración (`.env`)

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | Tu clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` (recomendado), `claude-opus-4-8` (+calidad), `claude-haiku-4-5-20251001` (+barato) |
| `WHISPER_MODEL` | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `AUDIO_DEVICE_NAME` | Substring del nombre de tu dispositivo agregado |

---

## 5. Notas y mejoras posibles

- **Transcripción más rápida en Apple Silicon**: prueba
  [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper),
  que usa la GPU del chip M. Sustituye la implementación en `transcribe.py`.
- **Diarización** (quién dijo qué): añade `pyannote.audio` y etiqueta hablantes
  antes de resumir.
- **Buscar entre reuniones**: ya tienes todo en `notes.db`; podrías añadir un
  endpoint que mande varias transcripciones a Claude y respondas preguntas
  ("¿qué acordamos sobre precios este mes?").
- **Briefs previos**: antes de una reunión, recupera las notas anteriores con esa
  persona/tema y pídele a Claude un resumen de contexto.
- El procesado al detener es **bloqueante** (MVP). Para reuniones largas, conviene
  pasarlo a una tarea en segundo plano y hacer polling del estado.

---

## Privacidad
El audio se procesa **en local** (Whisper). Solo el **texto** de la transcripción
y tus notas se envían a la API de Claude para el resumen. No se sube audio.
Avisa a los participantes de que estás tomando notas con asistencia de IA.
