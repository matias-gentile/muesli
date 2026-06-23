#!/usr/bin/env python3
"""Muesli en la barra de menú de macOS.

Corre el servidor Flask por detrás y pone un ícono en la barra de menú para
grabar/parar y ver el estado, sin abrir el navegador. El panel completo
(historial, notas, resúmenes) se abre en una ventana nativa (pywebview).

Uso:
    python menubar.py

Requiere macOS + rumps + pywebview (ver requirements.txt).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import rumps

import app as flask_app  # importa la app Flask (no la arranca: eso pasa en start_flask)

BASE = "http://127.0.0.1:5001"
HERE = os.path.dirname(os.path.abspath(__file__))


# ---- helpers HTTP a la API local ----------------------------------------
def api_get(path):
    with urllib.request.urlopen(BASE + path, timeout=3) as r:
        return json.loads(r.read().decode())


def api_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def notify(title, text):
    """Notificación nativa vía osascript (anda sin tener que empaquetar la app)."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f"display notification {json.dumps(text)} with title {json.dumps(title)}"],
            check=False,
        )
    except Exception:
        pass


def start_flask():
    flask_app.app.run(host="127.0.0.1", port=5001, debug=False,
                      use_reloader=False, threaded=True)


class MuesliBar(rumps.App):
    def __init__(self):
        super().__init__("Muesli", title="🎙️", quit_button=None)
        self.mode = "full"
        self.recording = False
        self._t0 = None
        self._notified = True  # arranca en True para no notificar al abrir

        self.record_item = rumps.MenuItem("● Grabar", callback=self.toggle_record)
        self.status_item = rumps.MenuItem("Iniciando…")
        self.mode_full = rumps.MenuItem("Salida + micrófono", callback=self.set_mode_full)
        self.mode_out = rumps.MenuItem("Solo salida del sistema", callback=self.set_mode_out)
        self.mode_full.state = True
        mode_menu = rumps.MenuItem("Fuente de audio")
        mode_menu.add(self.mode_full)
        mode_menu.add(self.mode_out)

        self.out_menu = rumps.MenuItem("🔊 Salida de audio")

        self.menu = [
            self.record_item,
            self.status_item,
            None,
            mode_menu,
            self.out_menu,
            rumps.MenuItem("Abrir panel", callback=self.open_panel),
            None,
            rumps.MenuItem("Salir", callback=self.quit_app),
        ]
        self._build_output_menu()
        self._panel_proc = None

        self.timer = rumps.Timer(self.tick, 1.0)
        self.timer.start()

    # ---- modo de audio ----
    def set_mode_full(self, _):
        self.mode = "full"
        self.mode_full.state = True
        self.mode_out.state = False

    def set_mode_out(self, _):
        self.mode = "output"
        self.mode_full.state = False
        self.mode_out.state = True

    # ---- salida de audio del sistema ----
    def _build_output_menu(self):
        try:
            import audio_output
            outs = audio_output.list_outputs()
        except Exception:
            outs = []
        # clear() falla si el submenú todavía no tiene hijos (su NSMenu interno es None);
        # en ese caso (primer armado) no hay nada que limpiar.
        if getattr(self.out_menu, "_menu", None) is not None:
            self.out_menu.clear()
        if not outs:
            self.out_menu.add(rumps.MenuItem("(sin dispositivos de salida)"))
        else:
            for o in outs:
                # 🟢 marca las salidas que incluyen BlackHole (mantienen la captura).
                label = ("🟢 " if o.get("keeps_capture") else "") + o["name"]
                item = rumps.MenuItem(label, callback=self._make_output_cb(o["name"]))
                item.state = 1 if o.get("is_default") else 0
                self.out_menu.add(item)
        self.out_menu.add(rumps.separator)
        self.out_menu.add(rumps.MenuItem("↻ Actualizar lista", callback=lambda _: self._build_output_menu()))

    def _make_output_cb(self, name):
        def cb(_):
            try:
                import audio_output
                ok = audio_output.set_default_output(name)
            except Exception:
                ok = False
            notify("Muesli", f"Salida: {name}" if ok else f"No se pudo cambiar a {name}")
            self._build_output_menu()
        return cb

    # ---- grabar / parar ----
    def toggle_record(self, _):
        if not self.recording:
            try:
                data = api_post("/api/start", {"mode": self.mode})
            except Exception as e:
                notify("Muesli", f"No se pudo iniciar: {e}")
                return
            if data.get("error"):
                notify("Muesli", data["error"])
                return
            self.recording = True
            self._t0 = time.time()
            self._notified = False
            self.record_item.title = "■ Detener"
            self.title = "🔴 00:00"
        else:
            default = f"Reunión {datetime.datetime.now():%d/%m %H:%M}"
            title = default
            try:  # pedimos un nombre (con default), pero sin bloquear si algo falla
                resp = rumps.Window(
                    message="Ponele un nombre a la grabación:",
                    title="Guardar reunión", default_text=default,
                    ok="Guardar", cancel="Sin nombre", dimensions=(360, 22),
                ).run()
                if resp.clicked and resp.text.strip():
                    title = resp.text.strip()
            except Exception:
                pass
            try:
                api_post("/api/stop", {"mode": self.mode, "title": title,
                                       "context_type": "reunion"})
            except Exception as e:
                notify("Muesli", f"Error al detener: {e}")
            self.recording = False
            self._t0 = None
            self.record_item.title = "● Grabar"
            self.title = "⏳"

    # ---- panel (ventana nativa, sin navegador) ----
    def open_panel(self, _):
        if self._panel_proc is not None and self._panel_proc.poll() is None:
            return  # ya está abierto
        self._panel_proc = subprocess.Popen([sys.executable, os.path.join(HERE, "panel.py")])

    def quit_app(self, _):
        if self._panel_proc is not None and self._panel_proc.poll() is None:
            self._panel_proc.terminate()
        rumps.quit_application()

    # ---- polling de estado ----
    def tick(self, _):
        try:
            s = api_get("/api/status")
        except Exception:
            return  # Flask todavía arrancando o sin respuesta momentánea

        rec = bool(s.get("recording"))
        # sincroniza con grabaciones iniciadas/paradas desde el panel
        if rec and not self.recording:
            self.recording = True
            self._t0 = self._t0 or time.time()
            self._notified = False
            self.record_item.title = "■ Detener"
        elif not rec and self.recording:
            self.recording = False
            self._t0 = None
            self.record_item.title = "● Grabar"

        if rec:
            el = int(time.time() - (self._t0 or time.time()))
            self.title = f"🔴 {el // 60:02d}:{el % 60:02d}"
            self.status_item.title = "Grabando…"
            return

        st = s.get("status")
        if st == "transcribing":
            done = s.get("done_chunks", 0)
            tot = s.get("total_chunks")
            self.status_item.title = f"Transcribiendo {done}/{tot if tot else '…'}"
            self.title = "⏳"
        elif st == "summarizing":
            self.status_item.title = "Resumiendo con Claude…"
            self.title = "⏳"
        elif st == "done":
            self.status_item.title = "✓ Listo y guardado"
            self.title = "🎙️"
            if not self._notified:
                res = s.get("result") or {}
                note = res.get("note") or {}
                extra = " · en Notion" if res.get("notion_url") else ""
                notify("Muesli", f"Resumen listo: {note.get('title', 'tu reunión')}{extra}")
                self._notified = True
        elif st == "error":
            self.status_item.title = "⚠️ Error (mirá el panel)"
            self.title = "🎙️"
            if not self._notified:
                notify("Muesli", s.get("error") or "Falló el procesado")
                self._notified = True
        else:
            self.status_item.title = "Listo"
            self.title = "🎙️"


def main():
    # Pedí permiso de micrófono apenas arranca (si no, los dispositivos de entrada
    # aparecen con 0 canales y no se ven). Mostrá el diálogo del sistema temprano.
    from mic_permission import request_microphone_access
    request_microphone_access()

    threading.Thread(target=start_flask, daemon=True).start()
    # esperá a que Flask responda (hasta ~5 s) antes de mostrar la barra
    for _ in range(50):
        try:
            api_get("/api/status")
            break
        except Exception:
            time.sleep(0.1)
    MuesliBar().run()


if __name__ == "__main__":
    main()
