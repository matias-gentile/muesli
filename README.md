# Muesli — Notas de reuniones (para uso personal)

Graba el **audio del sistema + tu micrófono** en un Mac, transcribe en **local**
con Whisper y genera un **resumen estructurado** con la API de Claude, adaptado
al **tipo** de grabación (reunión, clase, entrevista, podcast…). Tus notas
manuales guían el énfasis. Todo se guarda como Markdown.

## Cómo funciona

```
Audio del sistema + micrófono
   └─ BlackHole (dispositivo agregado) ─→ WAV (local)
        └─ faster-whisper ─→ transcripción (local)
             └─ Claude ─→ resumen por tipo + action items (combinado con tus notas)
                  └─ Markdown en notes/ + índice en SQLite
```

El audio **nunca sale de tu Mac** (Whisper corre localmente). Solo el **texto**
—la transcripción y tus notas— se envía a la API de Claude para el resumen.

## Tipos de grabación (plantillas)

Antes de grabar elegís un tipo y el resumen se estructura para ese caso:

| Tipo | Secciones del resumen |
|---|---|
| **Reunión** | Resumen ejecutivo · Puntos clave · Decisiones · Action items · Pendientes |
| **Clase / charla** | Resumen · Conceptos clave · Ejemplos · Para repasar · Dudas |
| **Entrevista** | Resumen · Puntos fuertes · Áreas a profundizar · Respuestas destacadas · Recomendación |
| **Video / podcast** | Resumen · Ideas principales · Takeaways · Citas · Recursos |
| **1:1 / feedback** | Resumen · Temas · Feedback · Compromisos · Notas personales |
| **Brainstorming** | Resumen · Ideas · Patrones · Decisiones provisionales · Próximos pasos |
| **General / otro** | Resumen · Puntos clave · Pendientes |

Además podés escribir un **contexto** libre (tema, asistentes, materia) que mejora
bastante el resultado. Las plantillas viven en `summarize.py` → `TEMPLATES`, así
que agregar una nueva es trivial.

## Requisitos previos

- macOS (Apple Silicon o Intel)
- Python 3.9+ — comprobá con `python3 --version`
- Homebrew — https://brew.sh
- Una API key de Anthropic — https://console.anthropic.com

---

## Paso 1 — Captura de audio (BlackHole)

macOS no deja grabar el audio del sistema de fábrica. Se resuelve con
**BlackHole**, un driver de audio virtual gratuito que funciona como un "cable"
interno por el que pasa el sonido.

### 1.1 Instalar BlackHole
```bash
brew install blackhole-2ch
```
Te va a pedir tu contraseña (instala un componente de sistema). Si `brew` falla o
no lo usás, descargá el `.pkg` de **BlackHole2ch** directo desde GitHub releases
(sin tener que dar tu email): https://github.com/ExistentialAudio/BlackHole/releases

**Importante:** después de instalar, **reiniciá el Mac**. macOS carga el driver de
audio recién al reiniciar, y es la causa #1 de que "BlackHole no aparezca" en
Configuración de Audio MIDI. Si no querés reiniciar, podés refrescar el servicio
de audio con:
```bash
sudo killall coreaudiod
```
Si al instalar saltó un aviso de *"software del sistema bloqueado"*, andá a
*Ajustes del Sistema → Privacidad y seguridad*, dale **Permitir** y reiniciá.

### 1.2 Abrir "Configuración de Audio MIDI"
Spotlight (⌘+Espacio) → escribí **Configuración de Audio MIDI** (Audio MIDI Setup).

### 1.3 Crear un *Multi-Output Device* (para seguir escuchando)
Si mandás todo el audio a BlackHole, dejarías de oírlo. Este dispositivo lo manda
a la vez a BlackHole y a tus parlantes.
1. Botón `+` (abajo a la izquierda) → **Crear dispositivo de salida múltiple**.
2. Marcá **BlackHole 2ch** y tu salida normal (*MacBook Speakers* o tus auriculares).
3. (Opcional) Renombralo, p. ej. "Muesli salida".

### 1.4 Crear un *Aggregate Device* (lo que graba la app)
Combina lo que entra por BlackHole (el audio de la reunión) con tu micrófono (tu voz).
1. Botón `+` → **Crear dispositivo agregado**.
2. Marcá **BlackHole 2ch** y tu **micrófono** (*MacBook Microphone*).
3. Renombralo de forma que el nombre contenga `Aggregate` (o ajustá
   `AUDIO_DEVICE_NAME` en `.env` para que coincida con el nombre que le pongas).

### 1.5 Antes de cada grabación
- Poné la **salida** del sistema en el *Multi-Output Device* (menú de volumen, o
  Ajustes del Sistema → Sonido → Salida).
- La app graba sola desde el *Aggregate Device*; no tenés que tocar la entrada.

> Para ver qué dispositivos detecta Python:
> ```bash
> python audio_capture.py
> ```
> Debe aparecer tu dispositivo agregado en la lista.

---

## Paso 2 — Instalación

```bash
git clone https://github.com/matias-gentile/muesli.git
cd muesli

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # editá .env y poné tu ANTHROPIC_API_KEY
```

La primera transcripción descarga el modelo de Whisper (después queda en caché).

---

## Paso 3 — Primer uso y permisos

```bash
python app.py
```
Abrí **http://localhost:5001**.

La primera vez que grabes, macOS pedirá permiso de micrófono. Concedelo en
*Ajustes del Sistema → Privacidad y seguridad → Micrófono* (para tu terminal o
para Python). Si lo negaste, activalo ahí y reiniciá la app.

---

## Paso 4 — Cómo usarlo

1. Escribí un **título**.
2. Elegí el **tipo** de grabación en el selector.
3. (Recomendado) Agregá **contexto**: p. ej. "Sprint 14, equipo backend, tema
   migración a Postgres".
4. **Grabar**. Mientras hablan, anotá lo que te importa en el área de notas — esas
   notas guían el resumen.
5. **Detener y resumir**. La app transcribe, resume con Claude según el tipo y guarda.
6. El resumen aparece en pantalla; las grabaciones quedan en la barra lateral y
   como `.md` en `notes/`.

---

## Configuración (`.env`)

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | Tu clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` (recomendado), `claude-opus-4-8` (+calidad), `claude-haiku-4-5-20251001` (+barato) |
| `WHISPER_MODEL` | `tiny` · `base` · `small` · `medium` · `large-v3` (más grande = más preciso y lento) |
| `AUDIO_DEVICE_NAME` | Substring del nombre de tu dispositivo agregado |

---

## Solución de problemas

**BlackHole no aparece en Configuración de Audio MIDI**
Casi siempre es porque falta reiniciar después de instalarlo (macOS carga el
driver al reiniciar) o porque no llegó a instalarse. Verificá con
`brew list | grep blackhole`; si no devuelve nada, instalalo (Paso 1.1). Después
**reiniciá el Mac** o corré `sudo killall coreaudiod`. Si hubo un aviso de
software bloqueado, permitilo en *Ajustes del Sistema → Privacidad y seguridad*.
Ojo: *ZoomAudioDevice* no es BlackHole; es el driver de Zoom y no sirve como
loopback general.

**"No encontré un dispositivo de entrada que contenga 'Aggregate'"**
Corré `python audio_capture.py` para ver los nombres reales y poné el substring
correcto en `AUDIO_DEVICE_NAME`. Confirmá que creaste el Aggregate Device.

**Graba, pero el resumen solo tiene tu voz (no lo que dijeron los demás)**
La salida del sistema no está yendo a BlackHole. Poné la salida en el
*Multi-Output Device* antes de grabar.

**No se oye nada durante la reunión**
Estás mandando la salida solo a BlackHole. Cambiá la salida al *Multi-Output
Device* (que incluye tus parlantes).

**Permiso de micrófono denegado**
Ajustes del Sistema → Privacidad y seguridad → Micrófono → activá tu
terminal/Python y reiniciá la app.

**La transcripción tarda demasiado**
Bajá `WHISPER_MODEL` a `base` o `tiny`. En Apple Silicon, mirá `mlx-whisper`
(abajo) para usar la GPU.

**Error de API / 401**
Revisá `ANTHROPIC_API_KEY` en `.env`, que la venv esté activada y que
`python-dotenv` esté instalado.

**`Address already in use` en el puerto 5001**
Hay otra instancia corriendo. Cerrala o cambiá el puerto en `app.py`
(`app.run(..., port=XXXX)`).

---

## Privacidad
El audio se procesa **en local** con Whisper; no se sube a ningún lado. Solo el
texto (transcripción + tus notas) va a la API de Claude para el resumen. Avisá a
los participantes que estás tomando notas con asistencia de IA.

---

## Mejoras posibles
- **Transcripción más rápida en Apple Silicon**: reemplazar `transcribe.py` por
  [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper),
  que usa la GPU del chip M.
- **Diarización** (quién dijo qué): integrar `pyannote.audio` y etiquetar
  hablantes antes de resumir.
- **Buscar entre grabaciones**: ya está todo en `notes.db`; agregar un endpoint
  que mande varias transcripciones a Claude y responda preguntas
  ("¿qué acordamos sobre precios este mes?").
- **Briefs previos**: antes de una reunión, recuperar notas anteriores del mismo
  tema/persona y pedirle contexto a Claude.
- El procesado al detener es **bloqueante** (MVP); para grabaciones largas conviene
  pasarlo a una tarea en segundo plano con polling de estado.
