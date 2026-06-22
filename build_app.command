#!/bin/bash
# build_app.command
# Crea "Muesli.app" en el Escritorio para abrir Muesli con doble clic, en modo
# barra de menú (ícono 🎙️ arriba, sin Terminal ni navegador).
#
# Cómo usarlo: doble clic en este archivo (o ejecutalo desde la Terminal).
# Si movés la carpeta del proyecto, volvé a correrlo.

set -e

# 1) Carpeta del proyecto = donde vive este script.
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 2) Intérprete de Python: preferimos el entorno virtual si existe.
if [ -x "$PROJECT_DIR/.venv/bin/python3" ]; then
  PYBIN="$PROJECT_DIR/.venv/bin/python3"
elif [ -x "$PROJECT_DIR/venv/bin/python3" ]; then
  PYBIN="$PROJECT_DIR/venv/bin/python3"
else
  PYBIN="$(command -v python3 || true)"
fi

if [ -z "$PYBIN" ]; then
  echo "✗ No encontré Python 3. Instalalo o creá el venv primero (ver README)."
  echo "Presioná una tecla para cerrar."; read -r -n 1
  exit 1
fi
echo "Python: $PYBIN"

# 3) Aviso temprano si al entorno le faltan dependencias de la barra de menú.
if ! "$PYBIN" -c "import rumps" >/dev/null 2>&1; then
  echo ""
  echo "⚠  Ese Python no tiene 'rumps' instalado (la barra de menú no abriría)."
  echo "   Instalá las dependencias en ese entorno y volvé a correr esto:"
  echo "     \"$PYBIN\" -m pip install -r \"$PROJECT_DIR/requirements.txt\""
  echo ""
fi

# 3b) Aviso si el proyecto vive en una carpeta protegida por la privacidad de macOS
#     (Escritorio/Documentos/Descargas): al abrir con doble clic, macOS puede
#     bloquear el acceso al .venv con "Operation not permitted".
case "$PROJECT_DIR/" in
  "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*)
    echo "⚠  El proyecto está dentro de una carpeta protegida por macOS (Escritorio/Documentos/Descargas)."
    echo "   Al abrir con doble clic, macOS puede bloquear el acceso al entorno (.venv) con"
    echo "   'Operation not permitted'. Para que el .app funcione, elegí una:"
    echo "     1) Dale a Muesli.app 'Acceso a disco completo' en Ajustes → Privacidad y seguridad."
    echo "     2) (recomendado) Mové el proyecto fuera de esas carpetas, p. ej. a ~/Developer/muesli,"
    echo "        recreá el venv ahí (python3 -m venv .venv && pip install -r requirements.txt)"
    echo "        y volvé a correr este script."
    echo ""
    ;;
esac

# 4) Armamos el bundle .app en el Escritorio.
APP="$HOME/Desktop/Muesli.app"
echo "Creando $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

# 4a) Info.plist — LSUIElement=true => app de barra de menú, sin ícono en el Dock.
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Muesli</string>
  <key>CFBundleDisplayName</key><string>Muesli</string>
  <key>CFBundleIdentifier</key><string>com.matiasgentile.muesli</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Muesli</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Muesli graba el audio de tus reuniones para transcribirlas localmente.</string>
</dict>
</plist>
PLIST

# 4b) Ejecutable del bundle: arranca Muesli en modo barra de menú.
#     Los logs van a ~/Library/Logs/Muesli.log (útil si algo no abre).
cat > "$APP/Contents/MacOS/Muesli" <<LAUNCH
#!/bin/bash
cd "$PROJECT_DIR"
exec "$PYBIN" menubar.py >> "\$HOME/Library/Logs/Muesli.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/Muesli"

# 5) Refrescamos el registro de LaunchServices (para que Finder lo tome enseguida).
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" >/dev/null 2>&1 || true

echo ""
echo "✓ Listo: $APP"
echo "  • Doble clic en 'Muesli' (Escritorio) para abrirlo → ícono 🎙️ en la barra de menú."
echo "  • La primera vez, macOS va a pedir permiso de micrófono: dale Permitir."
echo "  • Logs (si algo no abre): ~/Library/Logs/Muesli.log"
echo "  • Si movés la carpeta del proyecto, volvé a correr este script."
echo ""
echo "Presioná una tecla para cerrar."; read -r -n 1
