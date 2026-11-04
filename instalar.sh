#!/bin/bash
# Instala Muesli en esta Mac, o la actualiza, con la última versión publicada en GitHub (Releases).
# Elige sola la versión para tu Mac (chip Apple o Intel). Tus notas y tu configuración no se tocan:
# viven en ~/Library/Application Support/Muesli.
#
# Uso (en la app Terminal):
#   curl -fsSL https://raw.githubusercontent.com/matias-gentile/muesli/main/instalar.sh | bash
set -euo pipefail

REPO="matias-gentile/muesli"
APP_ID="com.matiasgentile.muesli"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "✗ Muesli es para Mac."; exit 1
fi
MACOS="$(sw_vers -productVersion)"
if [ "${MACOS%%.*}" -lt 14 ]; then
  echo "✗ Esta Mac tiene macOS ${MACOS}. Muesli necesita macOS 14 (Sonoma) o más nuevo:"
  echo "  actualizalo en Ajustes del Sistema → General → Actualización de software."
  exit 1
fi

# hw.optional.arm64 dice la verdad aunque la Terminal corra con Rosetta (ahí uname -m miente).
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
  CHIP="chip-Apple"; CHIP_TXT="chip Apple"
else
  CHIP="Intel"; CHIP_TXT="Intel"
fi
URL="https://github.com/${REPO}/releases/latest/download/Muesli-Mac-${CHIP}.zip"

# /Applications si se puede escribir (cuentas de administrador); si no, la carpeta Aplicaciones personal.
DEST="/Applications"
if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Bajando Muesli para Mac con ${CHIP_TXT}…"
if ! curl -fL --progress-bar -o "$TMP/Muesli.zip" "$URL"; then
  echo "✗ No pude bajarla. Fijate de tener internet y volvé a probar."
  exit 1
fi
ditto -x -k "$TMP/Muesli.zip" "$TMP/app"
[ -d "$TMP/app/Muesli.app" ] || { echo "✗ La descarga vino rota. Volvé a probar."; exit 1; }

# Si está abierta, cerrarla para reemplazarla.
if pgrep -x Muesli >/dev/null 2>&1; then
  echo "Cerrando Muesli para actualizarla…"
  osascript -e "tell application id \"${APP_ID}\" to quit" >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do pgrep -x Muesli >/dev/null 2>&1 || break; sleep 1; done
  pkill -x Muesli 2>/dev/null || true
fi

UPDATING=0
[ -d "$DEST/Muesli.app" ] && UPDATING=1
rm -rf "$DEST/Muesli.app"
mv "$TMP/app/Muesli.app" "$DEST/Muesli.app"
# Bajada con curl no queda en cuarentena, pero por las dudas: así macOS no la frena por no venir del App Store.
xattr -dr com.apple.quarantine "$DEST/Muesli.app" 2>/dev/null || true
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$DEST/Muesli.app/Contents/Info.plist" 2>/dev/null || echo "?")"

open "$DEST/Muesli.app"

echo ""
if [ "$UPDATING" = 1 ]; then
  echo "✓ Muesli ${VERSION} actualizada en ${DEST} y abierta."
  echo ""
  echo "Si al grabar macOS vuelve a pedir permiso de Grabación de pantalla, dáselo de nuevo:"
  echo "cada versión nueva cuenta como otra app para macOS."
else
  echo "✓ Muesli ${VERSION} instalada en ${DEST} y abierta."
  echo ""
  echo "Lo que sigue (en la ventana de Muesli que se acaba de abrir):"
  echo "  1. ⚙ Configuración → API key de Claude: pegá tu clave."
  echo "  2. ⚙ Configuración → Server de casa → poné el código que te da Memoria → Compus → Conectar una compu."
  echo "  3. La primera vez que grabes, macOS pide permiso de Grabación de pantalla y Micrófono: aceptalos."
  echo ""
  echo "Después, Muesli vive en la barra de arriba (el ícono del micrófono)."
fi
if [ -d "$HOME/Desktop/Muesli.app" ] && [ "$DEST" != "$HOME/Desktop" ]; then
  echo ""
  echo "Ojo: en el Escritorio hay otra Muesli.app vieja. Borrala para no abrir esa por error."
fi
