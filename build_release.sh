#!/bin/bash
# Arma Muesli.app y el .zip que se publica en GitHub (Releases), para la arquitectura de esta Mac.
# Lo usa el armado automático (.github/workflows/armar.yml) y también build_standalone.command.
#
# Requisitos: herramientas de Xcode (swiftc) y un Python con requirements.txt + pyinstaller instalados.
# Uso:  ./build_release.sh [versión]        (por ejemplo ./build_release.sh 1.1.0)
#   PY=/ruta/a/python ./build_release.sh    para elegir el Python (si no, usa .venv o python3)
#
# Deja:  dist/Muesli.app  y  dist/Muesli-Mac-chip-Apple.zip  (o  dist/Muesli-Mac-Intel.zip)
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${1:-0.0.0}"
MIN_MACOS="14.0"   # el mínimo que declara la app; el paso 4 revisa que ningún binario de adentro pida más
if [ -z "${PY:-}" ]; then
  PY="python3"
  [ -x ".venv/bin/python" ] && PY=".venv/bin/python"
fi
case "$(uname -m)" in
  arm64) CHIP="chip-Apple" ;;
  x86_64) CHIP="Intel" ;;
  *) echo "✗ Arquitectura desconocida: $(uname -m)"; exit 1 ;;
esac
ZIP="dist/Muesli-Mac-${CHIP}.zip"
echo "Muesli ${VERSION} · Mac ${CHIP} · Python: ${PY}"

# 1) Helper de captura (Swift, ScreenCaptureKit).
echo ""
echo "1/5 · Compilando el helper de captura…"
( cd native && ./build.sh >/dev/null )

# 2) Ícono .icns nativo (iconutil) a partir de assets/icon.png, en build/ para no tocar el del repo.
echo "2/5 · Armando el ícono…"
rm -rf build dist
mkdir -p build
ICON="assets/icon.icns"
if [ -f assets/icon.png ]; then
  ICONSET="build/icon.iconset"
  mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s assets/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
    sips -z $((s * 2)) $((s * 2)) assets/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  if iconutil -c icns "$ICONSET" -o build/icon.icns 2>/dev/null; then
    ICON="build/icon.icns"
  else
    echo "   (iconutil falló; uso assets/icon.icns)"
  fi
fi

# 3) Empaquetar.
echo "3/5 · Empaquetando con PyInstaller (tarda unos minutos)…"
MUESLI_VERSION="$VERSION" MUESLI_ICON="$ICON" MUESLI_MIN_MACOS="$MIN_MACOS" "$PY" -m PyInstaller --noconfirm --log-level WARN muesli.spec
APP="dist/Muesli.app"
[ -d "$APP" ] || { echo "✗ No se generó $APP. Mirá los errores de PyInstaller arriba."; exit 1; }

# 4) Que ninguna librería de adentro pida un macOS más nuevo que el que declara la app (si una dependencia sube su
#    mínimo, el armado falla acá en vez de dejar una app que no abre en algunas Macs).
echo "4/5 · Revisando que ande desde macOS ${MIN_MACOS}…"
NEEDS=$(find "$APP" -type f -print0 | xargs -0 file | grep 'Mach-O' | grep -v '(for architecture' | cut -d: -f1 | sort -u | while IFS= read -r f; do
  otool -l "$f" | awk '/LC_BUILD_VERSION/{b=1} b&&/minos/{print $2; exit} /LC_VERSION_MIN_MACOSX/{m=1} m&&/ version/{print $2; exit}'
done | sort -V | tail -1)
if [ "$(printf '%s\n%s\n' "$MIN_MACOS" "$NEEDS" | sort -V | tail -1)" != "$MIN_MACOS" ]; then
  echo "✗ Algo adentro de la app pide macOS ${NEEDS} (la app declara ${MIN_MACOS}). Revisá qué dependencia subió."
  exit 1
fi

# 5) Firmar (ad-hoc: sin cuenta de Apple; en Apple Silicon todo binario tiene que estar firmado) y comprimir.
echo "5/5 · Firmando y comprimiendo…"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo ""
echo "✓ $APP"
echo "✓ $ZIP ($(du -h "$ZIP" | cut -f1 | tr -d ' '))"
