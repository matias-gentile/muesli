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
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import rumps

import app as flask_app  # importa la app Flask (no la arranca: eso pasa en start_flask)
import call_detect
import config
import server_sync

BASE = "http://127.0.0.1:5001"
HERE = os.path.dirname(os.path.abspath(__file__))


def _resource(rel: str) -> str:
    """Ruta a un recurso (assets) — dentro del bundle cuando está empaquetado."""
    base = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(base, rel)


MENUBAR_ICON = _resource(os.path.join("assets", "menubar.png"))


# WKWebView no maneja por sí solo los diálogos de JS (alert/confirm/prompt) ni los links
# con target="_blank": hay que darle un WKUIDelegate. Lo definimos una sola vez (subclasear
# una clase ObjC dos veces tira error) y lo cacheamos.
_PANEL_UI_DELEGATE_CLASS = None


def _panel_ui_delegate_class():
    global _PANEL_UI_DELEGATE_CLASS
    if _PANEL_UI_DELEGATE_CLASS is not None:
        return _PANEL_UI_DELEGATE_CLASS
    from Foundation import NSObject
    from AppKit import NSAlert

    def _alert(message, with_cancel):
        a = NSAlert.alloc().init()
        a.setMessageText_("Muesli")
        a.setInformativeText_(message or "")
        a.addButtonWithTitle_("Aceptar")
        if with_cancel:
            a.addButtonWithTitle_("Cancelar")
        return a.runModal() == 1000  # NSAlertFirstButtonReturn

    class _PanelUIDelegate(NSObject):
        # Links target="_blank" / window.open → abrir en el navegador del sistema.
        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
                self, webView, configuration, navigationAction, windowFeatures):
            try:
                u = navigationAction.request().URL()
                if u is not None:
                    import webbrowser
                    webbrowser.open(u.absoluteString())
            except Exception:
                pass
            return None

        def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
                self, webView, message, frame, completionHandler):
            try:
                _alert(message, False)
            finally:
                completionHandler()

        def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
                self, webView, message, frame, completionHandler):
            ok = False
            try:
                ok = _alert(message, True)
            finally:
                completionHandler(bool(ok))

        def webView_runJavaScriptTextInputPanelWithPrompt_defaultText_initiatedByFrame_completionHandler_(
                self, webView, prompt, defaultText, frame, completionHandler):
            completionHandler(defaultText)

    _PANEL_UI_DELEGATE_CLASS = _PanelUIDelegate
    return _PanelUIDelegate


_PANEL_WIN_DELEGATE_CLASS = None


def _panel_window_delegate_class():
    """Delegate del panel: al cerrarlo, volvemos a 'accessory' (sin ícono en el Dock).

    Mientras el panel está abierto la app corre como 'regular' para aparecer en Cmd+Tab.
    """
    global _PANEL_WIN_DELEGATE_CLASS
    if _PANEL_WIN_DELEGATE_CLASS is not None:
        return _PANEL_WIN_DELEGATE_CLASS
    from Foundation import NSObject
    from AppKit import NSApp, NSApplicationActivationPolicyAccessory

    class _PanelWindowDelegate(NSObject):
        def windowWillClose_(self, notification):
            try:
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            except Exception:
                pass

    _PANEL_WIN_DELEGATE_CLASS = _PanelWindowDelegate
    return _PanelWindowDelegate


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
    server_sync.start()  # manda las charlas a Memoria (el server de casa), si esta Mac está conectada
    flask_app.app.run(host="127.0.0.1", port=5001, debug=False,
                      use_reloader=False, threaded=True)


# --- Instancia única -------------------------------------------------------
# Evita que aparezcan varios íconos de Muesli en la barra: si por lo que sea se
# lanza un segundo proceso (macOS relanza la .app, un ítem de inicio, doble clic,
# una carrera al abrir), el segundo detecta que ya hay uno corriendo y sale antes
# de dibujar el ícono. Usamos un lock de archivo exclusivo: el SO lo libera solo
# cuando el proceso termina —incluso si lo matan—, así que nunca queda "trabado".
_SINGLE_INSTANCE_FH = None  # se mantiene abierto toda la vida del proceso (NO cerrar)


def _lock_path() -> str:
    base = os.path.expanduser("~/Library/Application Support/Muesli")
    try:
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "menubar.lock")
    except Exception:
        return os.path.join(tempfile.gettempdir(), "muesli-menubar.lock")


def _ensure_single_instance() -> bool:
    """True si somos la única instancia; False si ya hay otra corriendo."""
    global _SINGLE_INSTANCE_FH
    try:
        fh = open(_lock_path(), "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False   # otra instancia ya tiene el lock
    except Exception:
        return True    # ante cualquier otro problema, no bloqueamos el arranque
    _SINGLE_INSTANCE_FH = fh  # guardamos la referencia para que no se cierre el fd
    return True


# Cadencia del sondeo de estado: rápido cuando hay actividad, lento en reposo
# (para no despertar la CPU ni hacer requests cada segundo sin necesidad → menos batería).
ACTIVE_INTERVAL = 1.0    # grabando o procesando
IDLE_INTERVAL = 10.0     # en reposo


def _prompt_target_class():
    """Objeto ObjC que recibe los clics de los botones del aviso de llamada.
    (PyObjC exige un NSObject como target; lo creamos perezosamente para no
    importar AppKit al arrancar.)"""
    import objc
    from Foundation import NSObject

    class _MuesliPromptTarget(NSObject):
        def initWithBar_(self, bar):
            self = objc.super(_MuesliPromptTarget, self).init()
            if self is None:
                return None
            self._bar = bar
            return self

        def record_(self, _sender):
            try:
                self._bar._call_prompt_record()
            except Exception as e:
                print(f"[call_prompt] error al grabar: {e}", flush=True)

        def dismiss_(self, _sender):
            try:
                self._bar._call_prompt_dismiss()
            except Exception:
                pass

    return _MuesliPromptTarget


class MuesliBar(rumps.App):
    def __init__(self):
        self._has_icon = os.path.exists(MENUBAR_ICON)
        self._idle_title = "" if self._has_icon else "🎙️"
        if self._has_icon:
            # Ícono template (silueta monocroma que se adapta a barra clara/oscura).
            super().__init__("Muesli", icon=MENUBAR_ICON, template=True,
                             title="", quit_button=None)
        else:
            super().__init__("Muesli", title="🎙️", quit_button=None)
        self.mode = "full"
        self.recording = False
        self._t0 = None
        self._notified = True  # arranca en True para no notificar al abrir
        # Detección de llamada (micrófono en uso por otra app). Solo avisa.
        self._call_streak = 0        # ciclos seguidos con el mic en uso
        self._call_prompted = False  # ya avisamos para esta llamada
        self._call_idle = 0          # ciclos seguidos sin mic (para resetear)
        self._call_active = False    # hay una llamada en curso (mic en uso)
        self._call_dismissed = False # tocaste "Ahora no" en esta llamada

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
            rumps.MenuItem("✕ Cancelar grabación", callback=self.cancel_record),
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

        self._interval = ACTIVE_INTERVAL
        self.timer = rumps.Timer(self.tick, ACTIVE_INTERVAL)
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
            self.title = "● 00:00"
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
            self.title = "…"

    def cancel_record(self, _):
        if not self.recording:
            notify("Muesli", "No hay ninguna grabación en curso.")
            return
        if rumps.alert("Cancelar grabación",
                       "Se descarta el audio y no se guarda ninguna nota. ¿Seguro?",
                       ok="Cancelar grabación", cancel="Volver") != 1:
            return
        try:
            api_post("/api/cancel", {})
        except Exception as e:
            notify("Muesli", f"No se pudo cancelar: {e}")
        self.recording = False
        self._t0 = None
        self._notified = True  # no dispares la notificación de "detenida sola"
        self.record_item.title = "● Grabar"
        self.title = self._idle_title
        self.status_item.title = "Grabación cancelada"

    # ---- panel (ventana nativa con WKWebView, sin navegador ni subprocesos) ----
    def open_panel(self, _):
        # Si ya está abierta, traela al frente.
        if getattr(self, "_panel_window", None) is not None:
            try:
                from AppKit import NSApp, NSApplicationActivationPolicyRegular
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)  # aparece en Cmd+Tab
                self._panel_window.makeKeyAndOrderFront_(None)
                NSApp.activateIgnoringOtherApps_(True)
                return
            except Exception:
                self._panel_window = None
        try:
            from AppKit import (NSWindow, NSBackingStoreBuffered, NSApp,
                                NSApplicationActivationPolicyRegular,
                                NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
                                NSWindowStyleMaskResizable, NSWindowStyleMaskMiniaturizable)
            from WebKit import WKWebView, WKWebViewConfiguration
            from Foundation import NSURL, NSURLRequest

            rect = ((0.0, 0.0), (1040.0, 720.0))
            style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                     NSWindowStyleMaskResizable | NSWindowStyleMaskMiniaturizable)
            win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, NSBackingStoreBuffered, False)
            win.setTitle_("Muesli")
            win.setReleasedWhenClosed_(False)
            # Al cerrar el panel volvemos a 'accessory' (sin Dock); ver delegate.
            try:
                self._panel_win_delegate = _panel_window_delegate_class().alloc().init()
                win.setDelegate_(self._panel_win_delegate)
            except Exception:
                pass
            web = WKWebView.alloc().initWithFrame_configuration_(
                rect, WKWebViewConfiguration.alloc().init())
            # Diálogos JS (confirm/alert) y links target="_blank" del panel.
            try:
                self._panel_ui_delegate = _panel_ui_delegate_class().alloc().init()
                web.setUIDelegate_(self._panel_ui_delegate)
            except Exception:
                pass
            win.setContentView_(web)
            web.loadRequest_(NSURLRequest.requestWithURL_(
                NSURL.URLWithString_("http://127.0.0.1:5001")))
            win.center()
            # 'regular' mientras el panel está abierto → la app aparece en Cmd+Tab y en el Dock.
            try:
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            except Exception:
                pass
            win.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            self._panel_window = win
        except Exception as e:
            # Si WebKit no está disponible, caé al navegador para no quedar sin panel.
            notify("Muesli", f"Abro el panel en el navegador ({e}).")
            import webbrowser
            webbrowser.open("http://127.0.0.1:5001")

    def quit_app(self, _):
        if self._panel_proc is not None and self._panel_proc.poll() is None:
            self._panel_proc.terminate()
        rumps.quit_application()

    # ---- indicador flotante de grabación (mini-ventana siempre visible) ----
    def _ensure_float(self):
        if getattr(self, "_float_win", None) is not None:
            return self._float_win
        try:
            from AppKit import (
                NSPanel, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
                NSBackingStoreBuffered, NSColor, NSTextField, NSView, NSFont, NSScreen,
                NSStatusWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary, NSWindowCollectionBehaviorFullScreenAuxiliary)
            w, h = 116.0, 34.0
            rect = ((0.0, 0.0), (w, h))
            style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
            win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, NSBackingStoreBuffered, False)
            win.setOpaque_(False)
            win.setBackgroundColor_(NSColor.clearColor())
            win.setLevel_(NSStatusWindowLevel)         # flota por encima de otras apps
            win.setHasShadow_(True)
            win.setMovableByWindowBackground_(True)     # se puede arrastrar
            win.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorFullScreenAuxiliary)  # en todos los escritorios

            content = NSView.alloc().initWithFrame_(rect)
            content.setWantsLayer_(True)
            content.layer().setCornerRadius_(13.0)
            content.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.09, 0.08, 0.07, 0.93).CGColor())
            win.setContentView_(content)

            dot = NSView.alloc().initWithFrame_(((14.0, h / 2 - 4.5), (9.0, 9.0)))
            dot.setWantsLayer_(True)
            dot.layer().setCornerRadius_(4.5)
            dot.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.88, 0.29, 0.24, 1.0).CGColor())
            content.addSubview_(dot)

            label = NSTextField.alloc().initWithFrame_(((30.0, 7.0), (w - 38.0, 20.0)))
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setTextColor_(NSColor.whiteColor())
            label.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13.0, 0.0))
            label.setStringValue_("00:00")
            content.addSubview_(label)
            self._float_label = label

            try:  # arriba-centro, justo debajo de la barra de menú
                vf = NSScreen.mainScreen().visibleFrame()
                x = vf.origin.x + (vf.size.width - w) / 2.0
                y = vf.origin.y + vf.size.height - h - 8.0
                win.setFrameOrigin_((x, y))
            except Exception:
                pass

            self._float_win = win
            return win
        except Exception as e:
            print(f"[float] no pude crear el indicador flotante: {e}")
            self._float_win = None
            return None

    def _show_float(self, text):
        win = self._ensure_float()
        if win is None:
            return
        try:
            self._float_label.setStringValue_(text)
            if not win.isVisible():
                win.orderFrontRegardless()
        except Exception:
            pass

    def _hide_float(self):
        win = getattr(self, "_float_win", None)
        if win is not None and win.isVisible():
            try:
                win.orderOut_(None)
            except Exception:
                pass

    # ---- aviso flotante de llamada detectada ----
    def _ensure_call_prompt(self):
        """Panel flotante con '¿Grabar esta llamada?' + botones. No depende del
        permiso de notificaciones de macOS (que suele bloquear las de osascript)."""
        if getattr(self, "_prompt_win", None) is not None:
            return self._prompt_win
        try:
            from AppKit import (
                NSPanel, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
                NSBackingStoreBuffered, NSColor, NSTextField, NSView, NSFont, NSScreen,
                NSButton, NSStatusWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary, NSWindowCollectionBehaviorFullScreenAuxiliary)
            w, h = 288.0, 62.0
            rect = ((0.0, 0.0), (w, h))
            style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
            win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, NSBackingStoreBuffered, False)
            win.setOpaque_(False)
            win.setBackgroundColor_(NSColor.clearColor())
            win.setLevel_(NSStatusWindowLevel)
            win.setHasShadow_(True)
            win.setMovableByWindowBackground_(True)
            win.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorFullScreenAuxiliary)

            content = NSView.alloc().initWithFrame_(rect)
            content.setWantsLayer_(True)
            content.layer().setCornerRadius_(14.0)
            content.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.09, 0.08, 0.07, 0.95).CGColor())
            win.setContentView_(content)

            dot = NSView.alloc().initWithFrame_(((14.0, h - 26.0), (9.0, 9.0)))
            dot.setWantsLayer_(True)
            dot.layer().setCornerRadius_(4.5)
            dot.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.93, 0.62, 0.18, 1.0).CGColor())
            content.addSubview_(dot)

            label = NSTextField.alloc().initWithFrame_(((30.0, h - 29.0), (w - 40.0, 18.0)))
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setTextColor_(NSColor.whiteColor())
            label.setFont_(NSFont.systemFontOfSize_(13.0))
            label.setStringValue_("¿Grabar esta llamada?")
            content.addSubview_(label)

            target_cls = _prompt_target_class()
            self._prompt_target = target_cls.alloc().initWithBar_(self)

            rec_btn = NSButton.alloc().initWithFrame_(((14.0, 10.0), (108.0, 24.0)))
            rec_btn.setTitle_("● Grabar")
            rec_btn.setBezelStyle_(1)
            rec_btn.setTarget_(self._prompt_target)
            rec_btn.setAction_("record:")
            content.addSubview_(rec_btn)

            no_btn = NSButton.alloc().initWithFrame_(((130.0, 10.0), (108.0, 24.0)))
            no_btn.setTitle_("Ahora no")
            no_btn.setBezelStyle_(1)
            no_btn.setTarget_(self._prompt_target)
            no_btn.setAction_("dismiss:")
            content.addSubview_(no_btn)

            try:  # arriba a la derecha, para no tapar el centro de la pantalla
                vf = NSScreen.mainScreen().visibleFrame()
                x = vf.origin.x + vf.size.width - w - 16.0
                y = vf.origin.y + vf.size.height - h - 8.0
                win.setFrameOrigin_((x, y))
            except Exception:
                pass

            self._prompt_win = win
            return win
        except Exception as e:
            print(f"[call_prompt] no pude crear el aviso flotante: {e}", flush=True)
            self._prompt_win = None
            return None

    def _show_call_prompt(self):
        win = self._ensure_call_prompt()
        if win is None:
            return
        try:
            if not win.isVisible():
                win.orderFrontRegardless()
        except Exception:
            pass

    def _hide_call_prompt(self):
        win = getattr(self, "_prompt_win", None)
        if win is not None:
            try:
                if win.isVisible():
                    win.orderOut_(None)
            except Exception:
                pass

    def _call_prompt_record(self):
        """Botón '● Grabar' del aviso: arranca la grabación como desde el menú."""
        self._hide_call_prompt()
        self._call_dismissed = True   # ya decidiste: no volver a mostrarlo en esta llamada
        if not self._recording_now():
            self.toggle_record(None)

    def _call_prompt_dismiss(self):
        """Botón 'Ahora no': lo cierra hasta la próxima llamada."""
        self._hide_call_prompt()
        self._call_dismissed = True

    def _recording_now(self) -> bool:
        try:
            return bool(api_get("/api/status").get("recording"))
        except Exception:
            return False

    # ---- polling de estado ----
    def _set_interval(self, interval):
        """Cambia la cadencia del timer (rápido/lento) sin recrearlo a mano."""
        if abs(interval - self._interval) < 0.01:
            return
        self._interval = interval
        try:
            self.timer.stop()
            self.timer.interval = interval
            self.timer.start()
        except Exception:
            pass

    def _check_call(self, recording_now: bool):
        """Si otra app empieza a usar el micrófono (≈ entraste a una llamada), avisa
        UNA vez para que decidas grabar. Nunca arranca a grabar solo."""
        if not config.get_bool("CALL_DETECT"):
            return
        if recording_now:
            # ya estás grabando: no molestar, y dejar listo el aviso para la próxima
            self._call_streak = 0
            self._call_prompted = True
            self._hide_call_prompt()
            return
        try:
            in_use = call_detect.mic_in_use()
        except Exception:
            return
        if in_use:
            self._call_idle = 0
            self._call_streak += 1
            self._call_active = True
            # mientras confirmamos, sondeá rápido para avisarte en ~10 s y no en ~30
            if not self._call_prompted:
                self._set_interval(ACTIVE_INTERVAL)
            # ~3 ciclos seguidos para no saltar por un sonido corto (Siri, un "hola")
            if self._call_streak >= 3 and not self._call_prompted:
                self._call_prompted = True
                print("[call_detect] micrófono en uso → aviso de llamada", flush=True)
                if not getattr(self, "_call_dismissed", False):
                    self._show_call_prompt()   # aviso visible, sin depender de permisos
                notify("¿Estás en una llamada?",
                       "Muesli detectó el micrófono en uso. Abrí el menú y tocá "
                       "\"● Grabar\" si querés grabarla.")
        else:
            self._call_streak = 0
            self._call_idle += 1
            # tras un rato sin micrófono, la llamada terminó: rearmamos el aviso
            if self._call_idle >= 3:
                self._call_active = False
                self._call_prompted = False
                self._call_dismissed = False
                self._hide_call_prompt()

    def tick(self, _):
        try:
            s = api_get("/api/status")
        except Exception:
            return  # Flask todavía arrancando o sin respuesta momentánea

        rec = bool(s.get("recording"))
        st = s.get("status")
        # cadencia adaptativa: rápido si hay actividad, lento en reposo (ahorra batería)
        busy = rec or st in ("transcribing", "summarizing")
        self._set_interval(ACTIVE_INTERVAL if busy else IDLE_INTERVAL)
        self._check_call(rec)

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
            # si se cortó sola (silencio/duración), avisá; el "Resumen listo" llega después.
            if s.get("auto_stop_reason"):
                notify("Muesli", f"Grabación detenida sola ({s['auto_stop_reason']}). Procesando…")

        if rec:
            el = int(time.time() - (self._t0 or time.time()))
            self.title = f"● {el // 60:02d}:{el % 60:02d}"
            self.status_item.title = "Grabando…"
            self._show_float(f"{el // 60:02d}:{el % 60:02d}")
            return
        self._hide_float()  # cualquier estado que no sea grabando: ocultá el flotante

        if st == "transcribing":
            done = s.get("done_chunks", 0)
            tot = s.get("total_chunks")
            self.status_item.title = f"Transcribiendo {done}/{tot if tot else '…'}"
            self.title = "…"
        elif st == "summarizing":
            self.status_item.title = "Resumiendo con Claude…"
            self.title = "…"
        elif st == "done":
            self.status_item.title = "✓ Listo y guardado"
            self.title = self._idle_title
            if not self._notified:
                res = s.get("result") or {}
                note = res.get("note") or {}
                extra = " · en Notion" if res.get("notion_url") else ""
                notify("Muesli", f"Resumen listo: {note.get('title', 'tu reunión')}{extra}")
                self._notified = True
        elif st == "error":
            self.status_item.title = "⚠️ Error (mirá el panel)"
            self.title = self._idle_title
            if not self._notified:
                notify("Muesli", s.get("error") or "Falló el procesado")
                self._notified = True
        else:
            if getattr(self, "_call_prompted", False) and getattr(self, "_call_active", False):
                # Aviso VISIBLE (no depende del permiso de notificaciones de macOS):
                # se ve en el menú y con un puntito en el ícono de la barra.
                self.status_item.title = "🔴 Llamada detectada — tocá ● Grabar"
                self.title = "•" if self._has_icon else "🔴"
            else:
                self.status_item.title = "Listo"
                self.title = self._idle_title


def main():
    # Instancia única: si ya hay un Muesli corriendo, avisamos y salimos SIN dibujar
    # otro ícono en la barra (así no se "duplica solo").
    if not _ensure_single_instance():
        notify("Muesli ya está abierto", "Ya hay una instancia corriendo en la barra de menú.")
        sys.exit(0)

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
