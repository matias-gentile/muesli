#!/bin/bash
# Construye Muesli como .app STANDALONE (con Python + dependencias + helper adentro).
# Doble clic para correr; no necesita venv ni "python menubar.py".
#
# Requisitos: macOS 13+, herramientas de Xcode (swiftc) y tu venv con las dependencias
# ya instaladas (las mismas que usás para correr la app).
set -e
cd "$(dirname "$0")"
echo "════════════════════════════════════════════"
echo "  Muesli · build standalone (.app)"
echo "════════════════════════════════════════════"

# Elegí el Python del venv si existe.
PY="python3"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"
echo "Python: $PY"

# 1) Compilar el helper de captura (Swift) para que quede dentro del bundle.
echo ""
echo "1/4 · Compilando el helper de captura (ScreenCaptureKit)…"
( cd native && ./build.sh )

# 2) Asegurar PyInstaller.
echo ""
echo "2/4 · Asegurando PyInstaller…"
$PY -m pip install --quiet --upgrade pyinstaller

# 3) Empaquetar.
echo ""
echo "3/4 · Empaquetando con PyInstaller (puede tardar)…"
rm -rf build dist
$PY -m PyInstaller --noconfirm muesli.spec

APP="dist/Muesli.app"
if [ ! -d "$APP" ]; then
  echo "✗ No se generó $APP. Mirá los errores de PyInstaller arriba."
  exit 1
fi

# 4) Firmar ad-hoc + copiar al Escritorio.
echo ""
echo "4/4 · Firmando (ad-hoc) y copiando al Escritorio…"
codesign --force --deep --sign - "$APP" 2>/dev/null || \
  echo "   (codesign ad-hoc falló; vas a poder abrir igual con botón derecho → Abrir)"

DEST="$HOME/Desktop/Muesli.app"
rm -rf "$DEST"
cp -R "$APP" "$DEST"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST" 2>/dev/null || true

echo ""
echo "✓ Listo:  $DEST"
echo ""
echo "Primera vez:"
echo "  • Abrilo con botón derecho → Abrir (Gatekeeper, por no estar notarizada)."
echo "  • Concedé permisos: Grabación de pantalla y Micrófono (Ajustes → Privacidad)."
echo "  • El ícono 🎙️ aparece en la barra de menú (es app de barra, sin Dock)."
echo "  • La primera transcripción baja el modelo de Whisper (necesita internet una vez)."
