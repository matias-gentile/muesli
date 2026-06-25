#!/bin/bash
# Compila el helper de captura (ScreenCaptureKit).
# Requisitos: macOS 13+ y las herramientas de línea de comandos de Xcode (swiftc).
#   Si no las tenés:  xcode-select --install
set -e
cd "$(dirname "$0")"

ARCH=$(uname -m)   # arm64 (Apple Silicon) o x86_64 (Intel)
echo "Compilando para ${ARCH} (deployment target macOS 13.0)…"

swiftc -O -target "${ARCH}-apple-macos13.0" \
  -framework ScreenCaptureKit -framework AVFoundation -framework CoreMedia \
  MuesliCapture/main.swift -o muesli-capture

echo ""
echo "OK → $(pwd)/muesli-capture"
echo ""
echo "Probalo (graba 20s, chunks de 10s, a /tmp/muesli-cap):"
echo "  ./muesli-capture --out-dir /tmp/muesli-cap --chunk-seconds 10 --max-seconds 20"
echo "Después reproducí los .wav:  afplay /tmp/muesli-cap/chunk-000001.wav"
