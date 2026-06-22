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
4. Elegí **qué grabar** con el toggle: **"Salida + micrófono"** (vos y los demás) o
   **"Solo salida"** (solo lo que suena en el sistema, sin tu voz — útil para
   videos, podcasts o llamadas donde no querés grabarte).
5. **Grabar**. Mientras hablan, anotá lo que te importa en el área de notas — esas
   notas guían el resumen.
6. **Detener y resumir**. La app transcribe, resume con Claude según el tipo y guarda.
7. El resumen aparece en pantalla; las grabaciones quedan en la barra lateral y
   como `.md` en `notes/`.

---

## Usar desde la barra de menú (sin navegador)

En vez de abrir el navegador, podés usar Muesli desde la **barra de menú de macOS**
(arriba a la derecha, estilo Granola). Corre el servidor por detrás y te deja
grabar/parar y ver el estado desde un ícono 🎙️.

**Instalá las dependencias de macOS** (rumps y pywebview) y arrancá así:

```bash
pip install -r requirements.txt
python menubar.py
```

Vas a ver un 🎙️ en la barra de menú. Desde ahí:

- **● Grabar / ■ Detener**: graba y para. Mientras grabás, el ícono muestra el
  cronómetro (🔴 00:34). Al detener te pide un nombre para la reunión.
- **Estado en vivo**: "Transcribiendo 3/12…", "Resumiendo con Claude…", y una
  **notificación nativa** cuando el resumen está listo.
- **Fuente de audio**: elegís "Salida + micrófono" o "Solo salida del sistema".
- **Abrir panel**: abre la interfaz completa (historial, notas, tipo de reunión,
  resúmenes) en una **ventana nativa** — la misma UI, pero sin navegador.

La barra de menú y el panel comparten el mismo estado: si arrancás a grabar en uno,
el otro lo refleja. Para una captura rápida alcanza con la barra (usa un nombre por
defecto que podés cambiar al parar); si querés tomar notas o elegir el tipo de
reunión, usá el panel.

> **Notas:** la app web (`python app.py`) sigue funcionando igual si preferís el
> navegador. Para que la barra arranque sola al iniciar sesión, podés crear un
> *LaunchAgent* que ejecute `python menubar.py`. Y si las notificaciones no
> aparecen, dale permiso en Ajustes → Notificaciones.

---

## Reuniones largas

Muesli graba en **segmentos de ~10 min** (`CHUNK_SECONDS`) y los va transcribiendo
**en segundo plano mientras seguís grabando**. Esto da tres cosas:

- **Procesado rápido al final**: cuando le das Detener, casi todo ya está
  transcripto; solo falta el último pedazo y el resumen.
- **Resiliencia**: si algo se corta, los chunks ya cerrados quedan guardados y
  válidos en `recordings/meeting-<fecha>/` (no perdés la reunión entera).
- **Progreso visible**: al detener, la app no se bloquea — muestra
  "Transcribiendo segmentos… 8 / 12" y luego "Resumiendo con Claude…".

Al final se concatenan todas las transcripciones en orden y se genera **un único
resumen**. El **resumen se adapta a la duración**: las reuniones largas generan un
resumen más detallado y exhaustivo (recorriendo los temas uno por uno), priorizando
capturar bien lo discutido por sobre la brevedad. Probado para reuniones de hasta
~2 h. Si transcribir mientras grabás hiciera glitchear el audio (CPU saturada), usá
un `WHISPER_MODEL` más chico.

---

## Si el resumen falla (cortes de red, etc.)

El resumen es el único paso que usa internet (la llamada a la API de Claude). Si
justo ahí se corta la conexión, **no perdés la grabación**:

- La **transcripción se guarda igual**, con un aviso de que el resumen falló. En el
  panel, abrí la nota y tocá **"↻ Regenerar resumen"** para reintentar (también sirve
  si querés un resumen distinto). La llamada ahora reintenta sola ante cortes breves.
- Si la nota no llegó a guardarse (versión vieja, o cerraste la app), los `.wav`
  siguen en `recordings/meeting-<fecha>/`. Recuperala desde ahí sin re-grabar:

  ```bash
  python recover.py                          # usa la grabación más reciente
  python recover.py recordings/meeting-XXXX  # una carpeta puntual
  python recover.py --title "Reunión semanal" --type reunion
  ```

  Re-transcribe los segmentos, regenera el resumen y la guarda en el historial.

---

## Configuración (`.env`)

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | Tu clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` (recomendado), `claude-opus-4-8` (+calidad), `claude-haiku-4-5-20251001` (+barato) |
| `WHISPER_MODEL` | `tiny` · `base` · `small` · `medium` · `large-v3` (más grande = más preciso y lento) |
| `WHISPER_VAD` | `0` (off, más permisivo con audio bajo) o `1` (descarta silencios) |
| `AUDIO_DEVICE_NAME` | Substring del nombre de tu dispositivo agregado |
| `AUDIO_DEVICE_OUTPUT_ONLY` | Dispositivo para el modo "solo salida" (por defecto `BlackHole`) |
| `CHUNK_SECONDS` | Duración de cada segmento de grabación (por defecto `600` = 10 min) |
| `NOTION_API_KEY` | (Opcional) Token de tu integración de Notion |
| `NOTION_DATABASE_ID` | (Opcional) ID de la base donde se crean las páginas |

---

## Integración con Notion (opcional)

Si la activás, cada grabación se crea como una **página en una base de datos de
Notion**, con el resumen formateado (encabezados, viñetas y checkboxes), más el
tipo y la fecha. Si no la configurás, la app funciona igual con los `.md` locales.

1. **Creá una integración** en https://www.notion.so/my-integrations
   (tipo *Internal*) y copiá el **Internal Integration Token**.
2. **Creá una base de datos** en Notion (página nueva → `/database`). Solo necesita
   la propiedad de **título**. Opcionalmente agregá:
   - **Tipo** (tipo *Select*) → la app la completa con el tipo de grabación.
   - **Fecha** (tipo *Date*) → la app la completa con la fecha.

   Las propiedades opcionales solo se llenan si existen con ese nombre exacto.
3. **Compartí la base con la integración**: en la base, botón `•••` → *Conexiones*
   (Connections) → elegí tu integración. (Sin este paso, la API devuelve 404.)
4. **Conseguí el ID de la base**: está en su URL —
   `notion.so/<workspace>/<DATABASE_ID>?v=...` (los 32 caracteres antes del `?`).
5. **Poné las variables** en `.env`:
   ```
   NOTION_API_KEY=ntn_...
   NOTION_DATABASE_ID=...
   ```

Al detener una grabación vas a ver un botón **"Abrir en Notion"** con el link
directo a la página creada.

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

**El resumen dice "no hay contenido" / sale vacío**
La grabación quedó en silencio. Casi siempre es porque la **salida del sistema no
está en el Multi-Output Device** (entonces BlackHole no captó nada). Ponela ahí y
volvé a probar. Para confirmar, reproducí el último `.wav` en `recordings/`: si no
suena, es eso. Muesli ahora detecta nivel ≈ 0 y te avisa en vez de resumir el vacío.
Si el audio existe pero estaba muy bajo, además podés dejar `WHISPER_VAD=0`.

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

**Notion: error 404 / "object not found"**
La base no está compartida con la integración. Abrí la base → `•••` → *Conexiones*
y agregá tu integración. Verificá también que `NOTION_DATABASE_ID` sea el de la
base (no el de una página suelta).

**Notion: la página se crea pero sin Tipo/Fecha**
Esas propiedades solo se llenan si existen en la base con el nombre exacto
**Tipo** (Select) y **Fecha** (Date). El resumen siempre se escribe igual.

---

## Privacidad
El audio se procesa **en local** con Whisper; no se sube a ningún lado. Solo el
texto (transcripción + tus notas) va a la API de Claude para el resumen, y —si
activás la integración— el resumen se envía a tu Notion. Avisá a los
participantes que estás tomando notas con asistencia de IA.

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
