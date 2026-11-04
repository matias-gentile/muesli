# -*- mode: python ; coding: utf-8 -*-
# Empaqueta Muesli como .app standalone (app de barra de menú).
#
# Build (en tu Mac):
#   cd native && ./build.sh && cd ..      # compila el helper de captura primero
#   pyinstaller --noconfirm muesli.spec   # genera dist/Muesli.app
# (o usá el script build_standalone.command que hace todo).
#
# Notas:
# - El backend por defecto en la app empaquetada es ScreenCaptureKit (no incluye
#   BlackHole/PortAudio: sounddevice/soundfile quedan excluidos).
# - faster-whisper baja el modelo de Whisper la primera vez que transcribís (necesita red).

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Los pasa build_release.sh: la versión (la del tag en GitHub) y el ícono armado con iconutil.
VERSION = os.environ.get('MUESLI_VERSION') or '0.0.0'
ICON = os.environ.get('MUESLI_ICON') or 'assets/icon.icns'
# numpy y onnxruntime (chip Apple) ya piden macOS 14; build_release.sh revisa que nada pida más.
MIN_MACOS = os.environ.get('MUESLI_MIN_MACOS') or '14.0'

datas = [
    ('templates', 'templates'),
    ('assets', 'assets'),
]
binaries = [
    ('native/muesli-capture', '.'),   # helper de captura (queda en la raíz del bundle)
]
hiddenimports = []

# Paquetes con librerías nativas y/o data que hay que recolectar enteros.
for pkg in ('faster_whisper', 'ctranslate2', 'tokenizers', 'av',
            'huggingface_hub', 'onnxruntime'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[muesli.spec] no pude recolectar {pkg}: {e}")

# anthropic (cliente HTTP) y pyobjc (rumps / AVFoundation) por las dudas.
try:
    hiddenimports += collect_submodules('anthropic')
except Exception:
    pass
hiddenimports += [
    'rumps', 'objc', 'Foundation', 'AppKit', 'CoreFoundation',
    'AVFoundation', 'WebKit', 'Quartz',
]

block_cipher = None

a = Analysis(
    ['menubar.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['sounddevice', 'soundfile', 'webview', 'pywebview', 'tkinter', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Muesli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Muesli',
)

app = BUNDLE(
    coll,
    name='Muesli.app',
    icon=ICON,
    bundle_identifier='com.matiasgentile.muesli',
    info_plist={
        'LSUIElement': True,   # app de barra de menú (sin ícono en el Dock)
        'NSMicrophoneUsageDescription':
            'Muesli usa el micrófono para grabar y transcribir tus reuniones.',
        'NSScreenCaptureUsageDescription':
            'Muesli captura el audio del sistema para transcribir tus reuniones.',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'CFBundleName': 'Muesli',
        'LSMinimumSystemVersion': MIN_MACOS,
    },
)
