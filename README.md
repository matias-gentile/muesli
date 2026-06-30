# Muesli — Notas de reuniones (para uso personal)

Graba el **audio del sistema + tu micrófono** en un Mac, transcribe en **local**
con Whisper y genera un **resumen estructurado** con la API de Claude, adaptado
al **tipo** de grabación (reunión, clase, entrevista, podcast…). Tus notas
manuales guían el énfasis. Todo se guarda como Markdown.

## Cómo funciona

```
Audio del sistema + micrófono
   └─ ScreenCaptureKit (API nativa de macOS) ─→ WAV (local)
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

- macOS 13 (Ventura) o posterior — la captura usa ScreenCaptureKit. Para sumar tu
  **micrófono** conviene macOS 14.4+ (en Apple Silicon anda mejor).
- Python 3.9+ — comprobá con `python3 --version`
- Herramientas de línea de comandos de Xcode (para compilar el helper de captura):
  `xcode-select --install`
- Una API key de Anthropic — https://console.anthropic.com

---

## Paso 1 — Captura de audio (ScreenCaptureKit)

Muesli graba el audio del sistema con **ScreenCaptureKit**, la API nativa de macOS.
**No hay que instalar BlackHole ni configurar "Audio MIDI Setup"**: macOS captura el
sonido de las apps directamente y vos seguís escuchando normal, sin rutear nada.

### 1.1 Compilar el helper de captura (una sola vez)
La captura la hace un pequeño helper en Swift que se compila localmente:
```bash
cd native && ./build.sh && cd ..
```
Necesitás las **Herramientas de línea de comandos de Xcode**. Si no las tenés:
```bash
xcode-select --install
```
> La app empaquetada (`.app`) ya viene con el helper compilado adentro, así que este
> paso es solo para correr desde el código fuente.

### 1.2 Tu voz (micrófono)
En el grabador hay un toggle **Salida + micrófono**:
- **Activado:** mezcla tu micrófono con el audio del sistema — ideal para
  videollamadas donde querés que quede registrado también lo que decís vos.
- **Desactivado:** graba solo el audio del sistema (lo que suena en la Mac).

Los permisos de macOS (Grabación de pantalla y, si corresponde, Micrófono) se
piden automáticamente la primera vez que grabás — ver el Paso 3.

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

La primera vez que grabes, macOS va a pedir permiso de **Grabación de pantalla**
(es lo que habilita capturar el audio del sistema con ScreenCaptureKit) y, si usás
el modo "Salida + micrófono", también de **Micrófono**. Concedelos en *Ajustes del
Sistema → Privacidad y seguridad → Grabación de pantalla* (y → *Micrófono*),
activando tu terminal o la app. Después de darlos puede que tengas que reiniciar la app.

---

## Paso 4 — Cómo usarlo

1. Escribí un **título**.
2. Elegí el **tipo** de grabación en el selector.
3. (Recomendado) Agregá **contexto**: p. ej. "Sprint 14, equipo backend, tema
   migración a Postgres".
4. Elegí **qué grabar** con el toggle: **"Salida + micrófono"** (vos y los demás) o
   **"Solo salida"** (solo lo que suena en el sistema, sin tu voz — útil para
   videos, podcasts o llamadas donde no querés grabarte).
5. **Grabar**. Mientras grabás vas a ver un **medidor de audio en vivo** (con un
   aviso **"Capturando ✓"** o **"Sin señal ⚠"** si el ruteo está mal — así te enterás
   en segundos, no después de una hora) y la **transcripción en vivo** a medida que se
   completan los segmentos. Podés **pausar/reanudar** con el botón **⏸ Pausar** (lo que
   pase durante la pausa no se graba ni cuenta en el cronómetro). Anotá lo que te importa
   en el área de notas — guían el resumen.
6. **Detener y resumir**. La app transcribe, resume con Claude según el tipo y guarda.
   Si arrancaste por error o no querés guardar nada, usá **✕ Cancelar**: descarta la
   grabación y borra el audio, sin transcribir ni crear ninguna nota. (También está en
   la barra de menú como *✕ Cancelar grabación*.)
7. El resumen aparece en pantalla. Podés **renombrar** la reunión (clic en el título),
   **editar el resumen** (✎), **copiarlo** (⧉) o **descargarlo** como `.md` (⤓). En la
   barra lateral, las reuniones se **agrupan por día**, muestran su **tipo** y se pueden
   **buscar** por título. Todo queda también como `.md` en `notes/`.

**Atajos de teclado:** <kbd>espacio</kbd> graba/detiene · <kbd>/</kbd> enfoca la búsqueda ·
<kbd>Esc</kbd> cierra Configuración. (El espacio no interfiere cuando estás escribiendo en
un campo.)

**Primer uso:** si falta la **API key de Claude** (lo único imprescindible), arriba
aparece un **checklist de bienvenida** que te dice exactamente qué configurar. El
mismo estado lo tenés siempre dentro de **⚙ Configuración**. La primera vez también se abre
un **tutorial guiado**; podés volver a verlo cuando quieras con **❓ Cómo usar Muesli** (abajo
a la izquierda).

**API key de Claude:** podés pegarla directamente en **⚙ Configuración → API key de Claude**
(se guarda local en tu Mac). Es la forma recomendada para la app empaquetada (`.app`), que no
usa `.env`. En desarrollo también podés ponerla en el `.env`.

**Gasto estimado y presupuesto:** Muesli cuenta los **tokens reales** que devuelve cada
respuesta de la API y los multiplica por el precio del modelo, así tenés una idea de cuánto
llevás gastado **este mes** (lo ves en la barra lateral y en detalle dentro de **⚙ Configuración →
Uso y gasto**). Podés fijar un **presupuesto mensual** y ver una barra de progreso. No es el saldo
oficial de tu cuenta —ese vive en console.anthropic.com— sino un estimado local de lo que gastás
con Muesli.

### Asistente sobre cada nota
Dentro de una nota guardada tenés tres ayudas que usan tu API key de Claude y se basan
**solo en el material de esa reunión** (no inventan):

- **Preguntale a esta reunión:** un chat para consultar la nota en lenguaje natural
  ("¿qué quedó pendiente para mí?", "¿qué dijo Juan del precio?"). Mantiene el hilo de la
  conversación mientras tengas la nota abierta.
- **✉ Email de seguimiento:** redacta un follow-up listo para copiar (asunto + cuerpo).
- **✓ Pendientes:** extrae los action items en una lista con responsables y fechas.
- **✨ Realzar mis notas:** si tomaste notas durante la reunión, completa **tus** notas
  con el detalle de lo que se dijo, en una sección aparte. Mantiene tus palabras y resalta
  (atenuado) lo que agrega la IA, para que veas qué es tuyo y qué completó Claude. El resumen
  normal no se toca.
- **💬 Diálogo:** reformatea la transcripción como conversación, infiriendo los cambios de
  orador del texto ("Orador 1", "Orador 2"). Es una aproximación (no detecta voces, no usa
  el audio), pero suele alcanzar para leer quién dijo qué. Se guarda para no regenerarlo.
- **⚡ Momentos clave (audio anclado):** Claude marca los momentos importantes de la reunión
  con su minuto exacto (decisiones, compromisos, datos). Si conservás el audio (auto-borrado
  apagado), **tocás un momento y saltás a esa parte de la grabación** para escuchar las
  palabras textuales — algo que apps en la nube no pueden hacer porque borran el audio. Si ya
  borraste el audio, los momentos igual se muestran como referencia.

Todo se genera localmente contra la API de Claude; nada se manda a terceros.

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
  cronómetro (● 00:34). Al detener te pide un nombre para la reunión.
- **Indicador flotante**: mientras grabás aparece una pastilla flotante (● + cronómetro)
  sobre cualquier app y en todos los escritorios, para que nunca dudes si está grabando
  (estilo Granola). La podés arrastrar a donde quieras; desaparece al detener.
- **✕ Cancelar grabación**: descarta lo que estás grabando (borra el audio, no guarda
  nota). Pide confirmación.
- **Estado en vivo**: "Transcribiendo 3/12…", "Resumiendo con Claude…", y una
  **notificación nativa** cuando el resumen está listo.
- **Salida + micrófono**: un toggle para incluir (o no) tu micrófono además del
  audio del sistema.
- **🔊 Salida de audio**: cambiá el dispositivo de salida del sistema (bocinas, AirPods,
  etc.) con un clic, sin ir a Ajustes. La salida actual queda tildada. (Si acabás de
  conectar/desconectar AirPods, "↻ Actualizar lista".)
- **Abrir panel**: abre la interfaz completa (historial, notas, tipo de reunión,
  resúmenes) en una **ventana nativa** — la misma UI, pero sin navegador.

> **Con ScreenCaptureKit podés cambiar de salida (bocinas ↔ AirPods) en cualquier
> momento sin afectar la grabación:** la captura del audio del sistema es independiente
> del dispositivo de salida. (Antes, con BlackHole, había que rutear todo por "Audio MIDI
> Setup"; ahora ya no hace falta nada de eso.)

La barra de menú y el panel comparten el mismo estado: si arrancás a grabar en uno,
el otro lo refleja. Para una captura rápida alcanza con la barra (usa un nombre por
defecto que podés cambiar al parar); si querés tomar notas o elegir el tipo de
reunión, usá el panel.

> **Notas:** la app web (`python app.py`) sigue funcionando igual si preferís el
> navegador. Para que la barra arranque sola al iniciar sesión, podés crear un
> *LaunchAgent* que ejecute `python menubar.py`. Y si las notificaciones no
> aparecen, dale permiso en Ajustes → Notificaciones.

---

## Abrir Muesli con doble clic (ejecutable en el Escritorio)

Hay **dos formas** de tener un `Muesli.app`:

### A) App standalone (recomendada) — `build_standalone.command`
Un `.app` **autocontenido**: trae Python, todas las dependencias y el helper de captura
adentro. Funciona con **doble clic, sin venv ni `python menubar.py`**, y usa
**ScreenCaptureKit por defecto** (audio del sistema + micrófono, **sin BlackHole ni Audio
MIDI**). Es la versión "producto".

```bash
./build_standalone.command
```
Esto compila el helper, empaqueta con **PyInstaller** y deja `Muesli.app` en tu Escritorio.
Requisitos: macOS 13+, herramientas de Xcode (`xcode-select --install`) y tu venv con las
dependencias instaladas. Notas:
- **Primera vez:** abrilo con **botón derecho → Abrir** (Gatekeeper, porque no está
  notarizada). Concedé **Grabación de pantalla** y **Micrófono** (Ajustes → Privacidad).
- La **primera transcripción** baja el modelo de Whisper (necesita internet una vez).
- Tus datos (notas, grabaciones, settings) se guardan en
  `~/Library/Application Support/Muesli` (no dentro del `.app`).
- Empaquetar con PyInstaller puede pedir un par de ajustes la primera vez; si falla, mirá
  los errores que imprime.

### B) Lanzador liviano — `build_app.command`
Genera un `.app` chico que **abre tu instalación actual** (necesita la carpeta del proyecto
y el venv donde están). Útil para desarrollo. Abre la app en **modo barra de menú** (ícono
🎙️ arriba, sin Terminal ni navegador).

**Una sola vez**, doble clic en **`build_app.command`** (está en la carpeta del proyecto).
Eso crea `Muesli.app` en tu Escritorio. Listo: a partir de ahí abrís Muesli con doble clic.

```bash
# (alternativa por Terminal, si preferís)
./build_app.command
```

Detalles:

- El `.app` apunta al **entorno virtual** del proyecto si existe (`.venv/`), o al
  `python3` del sistema. Asegurate de tener las dependencias instaladas en ese entorno
  (`pip install -r requirements.txt`) — el script te avisa si falta `rumps`.
- La **primera vez**, macOS pide permiso de **micrófono**: dale *Permitir* (o cargalo en
  Ajustes → Privacidad y seguridad → Micrófono).
- Como lo generás vos mismo en tu Mac, **no aparece la alerta de Gatekeeper** de apps de
  desarrolladores no identificados.
- ¿No abre nada al doble clic? Mirá el log en **`~/Library/Logs/Muesli.log`**.
- **No aparece ningún micrófono / la lista de dispositivos está vacía** (en
  `http://localhost:5001/api/devices` ves `"devices": []`): es el **permiso de
  micrófono**. En macOS reciente, hasta que lo concedés, los dispositivos de entrada se
  reportan con 0 canales y no aparecen. La app ahora **pide el permiso al arrancar** y el
  `.app` se **firma (ad-hoc)** para que macOS muestre el diálogo y lo atribuya a *Muesli*.
  Si lo ves: `git pull`, `pip install -r requirements.txt` (suma una dependencia de
  macOS), `./build_app.command`, reabrí Muesli y dale **Permitir** al diálogo de
  micrófono (o activalo en Ajustes → Privacidad y seguridad → Micrófono).
- **Ícono propio:** el `.app` usa el ícono de Muesli (`assets/icon.icns`). Si tras
  regenerarlo macOS sigue mostrando el ícono viejo/genérico, es el caché: probá
  `killall Dock` (y `killall Finder`), o mové el `.app` a otra carpeta y volvé.
- Si **movés la carpeta** del proyecto, volvé a correr `build_app.command` (el `.app`
  guarda la ruta absoluta).
- Podés arrastrar `Muesli.app` a **Aplicaciones**, y/o agregarlo a **Ajustes → General →
  Ítems de inicio** para que se abra solo al encender la Mac.

> ¿Preferís el panel completo en vez del menú? Desde el ícono 🎙️ → **Abrir panel** se
> abre la ventana nativa con todo (historial, notas, tipos, resúmenes).

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

## Que se apague sola (auto-stop)

Para no depender de acordarte de frenar la grabación cuando la reunión termina,
Muesli puede **cortar solo** y procesar lo grabado. Hay dos cortes, ambos en
**⚙ Configuración**:

- **Auto-detener tras silencio** *(por defecto: 15 min)*: si pasan X minutos
  seguidos **sin audio** (por debajo de un umbral), corta sola. Una sola palabra
  (o cualquier sonido) reinicia el contador, así que no te va a cortar una reunión
  que sigue, aunque tenga pausas largas — solo cuando de verdad quedó en silencio.
  Opciones: *Desactivado / 5 / 10 / 15 / 30 min*.
- **Límite máximo de grabación** *(por defecto: 3 h)*: un tope duro, sin importar
  el audio, por si quedó algo sonando de fondo. Opciones: *Desactivado / 1–4 h*.

El control corre en el **backend**, así que funciona igual la dispares desde el
navegador o desde la **barra de menú**. Cuando se apaga sola te **avisa** (notificación
del sistema en modo barra de menú; mensaje en el panel) y arranca el resumen como
siempre. La nota queda con un **título por defecto** (la grabación automática no toma
el título que tipeaste en el panel) — la podés **renombrar** después.

> El umbral de "silencio" depende de tu ambiente (ruido de fondo, hum del aire, etc.).
> Si tu sala tiene un zumbido constante por encima del umbral, el corte por silencio
> podría no dispararse: para esos casos está el **límite máximo de duración**, que es
> independiente del audio. El umbral vive en `SILENCE_LEVEL` (en `audio_capture.py`).

---

## Si el resumen falla (cortes de red, etc.)

El resumen es el único paso que usa internet (la llamada a la API de Claude). Si
justo ahí se corta la conexión, **no perdés la grabación**:

- La **transcripción se guarda igual**, con un aviso de que el resumen falló. En el
  panel, abrí la nota y tocá **"↻ Regenerar"** para reintentar. Al regenerar podés elegir
  el **nivel de detalle** (corto / normal / **extenso**, para charlas largas que ameritan un
  resumen más completo) y el **modelo** (Haiku / Sonnet / Opus) solo para esa regeneración.
  La llamada reintenta sola ante cortes breves.
- Si la nota no llegó a guardarse (versión vieja, o cerraste la app), el audio sigue
  en `recordings/meeting-<fecha>/`. En el panel, esas grabaciones aparecen abajo en
  **"Sin procesar"** con un botón **"Recuperar"**, que las re-transcribe y resume sin
  re-grabar. (También podés hacerlo por consola, útil si la app no abre:)

  ```bash
  python recover.py                          # usa la grabación más reciente
  python recover.py recordings/meeting-XXXX  # una carpeta puntual
  python recover.py --title "Reunión semanal" --type reunion
  ```

---

## Configuración (`.env`)

> ### Captura de audio: ScreenCaptureKit
> Muesli graba con **ScreenCaptureKit**, la API nativa de macOS: **audio del sistema sin
> BlackHole ni "Audio MIDI Setup"** (macOS 13+). En **macOS 14.4+** además puede sumar tu
> **micrófono** (el toggle "Salida + micrófono" del grabador lo controla; la mezcla la hace
> Muesli). Pide permiso de **Grabación de pantalla** (y de **Micrófono** si sumás el mic).
> Todavía **no permite pausar**. Para correr desde el código fuente hay que compilar el
> helper una vez: `cd native && ./build.sh` (ver [`native/README.md`](native/README.md)); la
> `.app` empaquetada ya lo trae compilado.
>
> (Existe un backend `blackhole` heredado, pero quedó fuera de la interfaz; ver la tabla de
> variables más abajo si sos power user.)

> Desde la app podés configurar casi todo sin tocar archivos: botón
> **⚙ Configuración** (barra lateral). Permite elegir el **modelo de Claude**
> (desplegable con costos) y de **Whisper**, la duración de segmento, el
> **auto-detenido por silencio**, el **auto-borrado del audio**, un **presupuesto
> mensual** de la API y las credenciales de **Notion**. Los cambios se aplican en vivo
> (sin reiniciar) y se guardan en `settings.json`. El `.env` sigue funcionando como
> valores por defecto.
>
> En **⚙ Configuración → Almacenamiento** ves cuánto ocupan las grabaciones y podés
> **liberar el audio ya procesado** (borra los `.wav` de las reuniones que ya tienen
> resumen, conservando la nota y la transcripción) o **borrar las grabaciones sin
> procesar** (las que nunca transcribiste).

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | Tu clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` (recomendado), `claude-opus-4-8` (+calidad), `claude-haiku-4-5-20251001` (+barato) |
| `WHISPER_MODEL` | `tiny` · `base` · `small` · `medium` · `large-v3` (más grande = más preciso y lento) |
| `WHISPER_VAD` | `0` (off, más permisivo con audio bajo) o `1` (descarta silencios) |
| `CAPTURE_BACKEND` | `screencapturekit` (por defecto, sin Audio MIDI). `blackhole` es un backend heredado que no aparece en la interfaz y requiere libs de audio + Audio MIDI |
| `CHUNK_SECONDS` | Duración de cada segmento de grabación (por defecto `600` = 10 min) |
| `AUTO_STOP_SILENCE_MIN` | Silencio seguido antes de cortar sola, en minutos (admite decimales: `0.5` = 30 s; `0` = desactivado; por defecto `15`) |
| `MAX_RECORDING_MIN` | Tope duro de duración en minutos (`0` = desactivado; por defecto `180` = 3 h) |
| `AUTO_PURGE_AUDIO` | Borrar el `.wav` automáticamente al terminar de transcribir (`1` = sí, `0` = no; por defecto `0`) |
| `MONTHLY_BUDGET_USD` | Presupuesto mensual estimado para la API (USD); `0` = sin límite. Muesli muestra el gasto estimado y una barra de progreso |
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

**No graba el audio del sistema / la grabación sale en silencio**
Lo más común es que falte el permiso de **Grabación de pantalla** — es lo que habilita
capturar el audio del sistema con ScreenCaptureKit. Activá tu terminal (o la app) en
*Ajustes del Sistema → Privacidad y seguridad → Grabación de pantalla* y reiniciá la app.
Para confirmar, reproducí el último `.wav` en `recordings/`: si no suena, es eso. Muesli
detecta nivel ≈ 0 y te avisa en vez de resumir el vacío.

**Error al iniciar la captura / "no encuentra el helper"**
Si corrés desde el código fuente, compilá el helper de captura una vez:
`cd native && ./build.sh`. Necesitás las Herramientas de línea de comandos de Xcode
(`xcode-select --install`). La `.app` empaquetada ya lo trae compilado.

**El resumen dice "no hay contenido" / sale vacío**
La grabación quedó en silencio (revisá el permiso de Grabación de pantalla, arriba). Si el
audio existe pero estaba muy bajo, podés dejar `WHISPER_VAD=0` para que Whisper sea más
permisivo.

**El resumen no incluye tu voz**
Activá el toggle **Salida + micrófono** en el grabador y concedé el permiso de Micrófono.
(Sumar el micrófono vía ScreenCaptureKit necesita macOS 14.4+.)

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
