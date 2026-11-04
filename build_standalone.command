#!/bin/bash
# Construye Muesli como .app STANDALONE (con Python + dependencias + helper adentro) desde el código de esta carpeta
# y la deja en el Escritorio. Para instalar la versión publicada no hace falta: usá instalar.sh (ver README).
# Doble clic para correr; no necesita venv ni "python menubar.py".
#
# Requisitos: macOS 14+, herramientas de Xcode con el SDK de macOS 15 o más nuevo (swiftc) y tu venv con las
# dependencias ya instaladas (las mismas que usás para correr la app).
set -e
cd "$(dirname "$0")"
echo "════════════════════════════════════════════"
echo "  Muesli · build standalone (.app)"
echo "════════════════════════════════════════════"

# Elegí el Python del venv si existe.
PY="python3"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"
echo "Python: $PY"

# Asegurar PyInstaller (con pip si el venv lo tiene; si es un venv de uv, con uv).
echo ""
echo "Asegurando PyInstaller…"
if "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --upgrade "pyinstaller>=6.10,<7"
elif command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$PY" "pyinstaller>=6.10,<7"
else
  echo "✗ No encuentro pip ni uv para instalar PyInstaller en $PY."
  exit 1
fi

# Armar (lo mismo que hace GitHub al publicar una versión).
echo ""
PY="$PY" ./build_release.sh "0.0.0"

APP="dist/Muesli.app"
DEST="$HOME/Desktop/Muesli.app"
rm -rf "$DEST"
cp -R "$APP" "$DEST"
touch "$DEST"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST" 2>/dev/null || true
# Refrescar el caché de íconos para que el ícono nuevo aparezca enseguida.
killall Dock 2>/dev/null || true

echo ""
echo "✓ Listo:  $DEST"
echo ""
echo "Primera vez:"
echo "  • Abrila con doble clic (si macOS la frena, botón derecho → Abrir)."
echo "  • Concedé permisos: Grabación de pantalla y Micrófono (Ajustes → Privacidad)."
echo "  • El ícono 🎙️ aparece en la barra de menú (es app de barra, sin Dock)."
echo "  • La primera transcripción baja el modelo de Whisper (necesita internet una vez)."
