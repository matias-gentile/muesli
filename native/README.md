# Captura nativa con ScreenCaptureKit (sin BlackHole)

Este `muesli-capture` es un helper en Swift que graba el **audio del sistema** usando
**ScreenCaptureKit** (macOS 13+), **sin** BlackHole y **sin** configurar Audio MIDI.
Es el primer paso de la migración: por ahora vive acá, aislado, y **no toca** la app
Python — el flujo actual (`menubar.py` + BlackHole + Agregado/Multi-Output) sigue
funcionando igual.

## Qué hace
- Captura la mezcla de audio que sale del sistema (lo que escucharías por los parlantes).
- Con `--include-mic` (macOS 15+) además graba el **micrófono** en archivos paralelos
  (`mic-000001.wav` junto a `chunk-000001.wav`); la app Python los **mezcla** antes de
  transcribir (`audio_mix.py`).
- Escribe **chunks WAV rotativos** (`chunk-000001.wav`, …) en un directorio. Ese es el
  mismo formato que el pipeline de Python ya sabe transcribir.
- Pide permiso de **Grabación de pantalla** (y de **Micrófono** si usás `--include-mic`).

> **Permiso de micrófono:** igual que la grabación de pantalla, va a la app desde la que
> lo corrés. Ajustes del Sistema → **Privacidad y seguridad → Micrófono** → activá tu
> terminal y **reabrila**. (En macOS 13–14 el `--include-mic` se ignora: graba solo el
> sistema; el mic por ScreenCaptureKit necesita macOS 15+.)

## Compilar
Necesitás las herramientas de línea de comandos de Xcode (si no: `xcode-select --install`).

```bash
cd native
./build.sh
```

Queda el binario `native/muesli-capture`.

## Permiso (una sola vez)
ScreenCaptureKit necesita permiso de **Grabación de pantalla**. Dos trampas típicas:

- **Va a la app EXACTA desde la que lanzás el binario**, no a un "Terminal" genérico:
  Terminal.app → activá *Terminal*; iTerm → *iTerm*; terminal de **VS Code** → *Code*.
- **No alcanza con tildar el toggle**: cerrá esa app por completo con **Cmd+Q** (no solo
  la ventana) y reabrila. Recién ahí toma efecto.

Pasos:
1. Ajustes del Sistema → **Privacidad y seguridad** → **Grabación de pantalla**.
2. Activá (o agregá con **+**) la app que estés usando.
3. **Cmd+Q** en esa app y reabrila.
4. Reintentá. (Si la primera vez tocaste "Deny", el permiso queda bloqueado y no vuelve a
   preguntar: hay que activarlo a mano acá.)

(Cuando más adelante esto viva dentro del `.app`, el permiso se lo va a pedir la app, no
la Terminal.)

## Probar
```bash
cd native
# Graba 20 segundos en chunks de 10s. Mientras tanto, REPRODUCÍ algo (música, un video).
./muesli-capture --out-dir /tmp/muesli-cap --chunk-seconds 10 --max-seconds 20
# Con micrófono (macOS 15+): agregá --include-mic y hablá mientras grabás.
./muesli-capture --out-dir /tmp/muesli-cap --chunk-seconds 10 --max-seconds 20 --include-mic
```

Con `--include-mic` vas a ver, además de `chunk-0000xx.wav`, archivos `mic-0000xx.wav`.
La mezcla la hace Python; para probar el flujo completo desde Python:
`python screen_capture.py 15 mic`.

Qué deberías ver (en la consola): `OUT_DIR …`, `READY`, líneas `LEVEL 0.xxxx` que
**suben cuando hay audio**, y `CHUNK chunk-0000xx.wav` cada 10s.

Después escuchá lo grabado:
```bash
afplay /tmp/muesli-cap/chunk-000001.wav
```

Si `LEVEL` queda en `0.0000` con audio sonando, o ves un `FATAL`/`STREAM_ERROR`,
copiame la salida y lo ajustamos (suele ser el permiso de Grabación de pantalla).

## Cómo se va a integrar (siguiente paso)
La idea es que la app Python pueda elegir el **backend de captura**:
- `blackhole` (actual, por defecto, no se rompe nada), o
- `screencapturekit` (lanza este helper, vigila el directorio de chunks y los transcribe
  con el mismo `Session` de hoy).

Eso se selecciona en Configuración. El helper se invoca como subproceso y se frena con
una señal (ya maneja Ctrl-C / SIGTERM).
