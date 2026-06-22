#!/usr/bin/env python3
"""Abre el panel de Muesli (la UI web) en una ventana nativa de macOS, sin navegador.

Se lanza desde la app de barra de menú (menubar.py) cuando elegís "Abrir panel".
Apunta al servidor Flask local que ya está corriendo.
"""
import webview

if __name__ == "__main__":
    webview.create_window("Muesli", "http://127.0.0.1:5001", width=1080, height=760)
    webview.start()
