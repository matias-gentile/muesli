"""App Flask: panel de control para grabar, transcribir y resumir reuniones.

La grabación se hace en chunks y el procesado (transcripción + resumen) corre en
segundo plano; /api/stop devuelve enseguida y el frontend consulta /api/status.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

# sounddevice solo lo necesita el backend BlackHole; opcional para builds solo-SCK.
try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory

import config
import notion_sync
import storage
import transcribe
import assistant
from audio_capture import ChunkedRecorder, find_input_device, record_test
from config import RECORDINGS_DIR
from screen_capture import ScreenCaptureRecorder
from session import Session
from summarize import list_templates, summarize, type_label


def _resource(rel: str) -> str:
    """Ruta a un recurso empaquetado (templates/assets). En el .app está bajo _MEIPASS."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


app = Flask(__name__, template_folder=_resource("templates"))
recorder: ChunkedRecorder | None = None
session: Session | None = None
auto_stop_reason: str | None = None  # motivo si la última grabación se detuvo sola


def _finish_recording(title="", notes="", ctype="reunion", context="", auto_reason=None) -> bool:
    """Detiene la grabación en curso y arranca el procesado. Compartido por /api/stop
    y el auto-stop. Devuelve False si no había nada grabando."""
    global recorder, session, auto_stop_reason
    if recorder is None or not recorder.recording:
        return False
    auto_stop_reason = auto_reason
    total = recorder.stop()
    session.finish(total, recorder.peak, title, notes, ctype, context, str(recorder.session_dir))
    return True


def _auto_stop_monitor(rec):
    """Corre en segundo plano mientras se graba: corta sola si hay demasiado silencio
    seguido, o si se pasa del límite máximo de duración."""
    silence_limit = config.get_int("AUTO_STOP_SILENCE_MIN", 0) * 60
    max_limit = config.get_int("MAX_RECORDING_MIN", 0) * 60
    started = time.time()
    while True:
        time.sleep(3)
        if rec is not recorder or not rec.recording:
            return  # se frenó, o ya hay otra grabación
        reason = None
        if silence_limit and rec.silent_seconds >= silence_limit:
            reason = f"{silence_limit // 60} min sin audio"
        elif max_limit and (time.time() - started) >= max_limit:
            reason = f"límite de {max_limit // 60} min"
        if reason:
            _finish_recording(auto_reason=reason)
            return


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.png")
def favicon_png():
    return send_from_directory(_resource("assets"), "favicon.png")


@app.route("/favicon.ico")
def favicon_ico():
    return send_from_directory(_resource("assets"), "favicon.png")


@app.route("/api/devices")
def devices():
    if sd is None:
        return jsonify({"configured": config.get("AUDIO_DEVICE_NAME"), "devices": []})
    out = [{"index": i, "name": d["name"], "channels": d["max_input_channels"]}
           for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    return jsonify({"configured": config.get("AUDIO_DEVICE_NAME"), "devices": out})


@app.route("/api/templates")
def templates():
    return jsonify(list_templates())


@app.route("/api/settings", methods=["GET"])
def get_settings():
    out = {}
    for k, v in config.get_all().items():
        if k in config.SECRET_KEYS:
            out[k] = ""                 # nunca devolvemos el secreto en claro
            out[k + "_set"] = bool(v)    # solo si está configurado
        else:
            out[k] = v
    return jsonify(out)


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.get_json(silent=True) or {}
    config.update(data)
    transcribe.reset_model()  # por si cambió el modelo de Whisper
    return jsonify({"status": "ok"})


@app.route("/api/test-audio", methods=["POST"])
def test_audio():
    if recorder is not None and recorder.recording:
        return jsonify({"ok": False, "error": "Hay una grabación en curso."}), 400
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "full")
    device = config.get("AUDIO_DEVICE_OUTPUT_ONLY") if mode == "output" else config.get("AUDIO_DEVICE_NAME")
    try:
        return jsonify(record_test(device, seconds=3.0))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/start", methods=["POST"])
def start():
    global recorder, session
    if recorder is not None and recorder.recording:
        return jsonify({"status": "already_recording"})

    data = request.get_json(silent=True) or {}
    # "full" = salida del sistema + micrófono; "output" = solo salida del sistema.
    mode = data.get("mode", "full")
    device = config.get("AUDIO_DEVICE_OUTPUT_ONLY") if mode == "output" else config.get("AUDIO_DEVICE_NAME")
    backend = config.get("CAPTURE_BACKEND", "blackhole")

    global auto_stop_reason
    auto_stop_reason = None
    try:
        session = Session()
        chunk_seconds = config.get_int("CHUNK_SECONDS", 600)
        if backend == "screencapturekit":
            # Captura del audio del sistema con el helper nativo (sin Audio MIDI).
            # "full" = sistema + micrófono; "output" = solo sistema.
            recorder = ScreenCaptureRecorder(on_chunk=session.add_chunk,
                                             chunk_seconds=chunk_seconds,
                                             include_mic=(mode != "output"))
        else:
            recorder = ChunkedRecorder(device_name=device, on_chunk=session.add_chunk,
                                       chunk_seconds=chunk_seconds)
        recorder.start()
    except Exception as e:  # dispositivo/binario no encontrado, permisos, etc.
        return jsonify({"error": str(e)}), 400

    # Monitor de auto-stop (silencio / duración máxima), si alguno está activo.
    if config.get_int("AUTO_STOP_SILENCE_MIN", 0) > 0 or config.get_int("MAX_RECORDING_MIN", 0) > 0:
        threading.Thread(target=_auto_stop_monitor, args=(recorder,), daemon=True).start()
    return jsonify({"status": "recording", "mode": mode, "backend": backend})


@app.route("/api/stop", methods=["POST"])
def stop():
    global recorder, session
    if recorder is None or not recorder.recording:
        return jsonify({"error": "no se está grabando"}), 400

    data = request.get_json(silent=True) or {}
    _finish_recording(
        data.get("title", ""), data.get("notes", ""),
        data.get("context_type", "reunion"), data.get("context", ""),
    )
    return jsonify({"status": "processing"})


@app.route("/api/cancel", methods=["POST"])
def cancel():
    """Aborta la grabación en curso: no transcribe ni guarda, y borra el audio."""
    global recorder, session, auto_stop_reason
    if recorder is None or not recorder.recording:
        return jsonify({"error": "no se está grabando"}), 400

    auto_stop_reason = None
    session_dir = recorder.session_dir
    recorder.stop()              # cierra el stream (el último chunk se descarta igual)
    if session is not None:
        session.cancel()         # el worker corta sin guardar nada
    # Descartá el audio grabado: esta sesión no se va a procesar.
    try:
        if session_dir and Path(session_dir).exists():
            shutil.rmtree(session_dir, ignore_errors=True)
    except Exception as e:
        print(f"[cancel] no se pudo borrar {session_dir}: {e}")
    recorder = None
    session = None
    return jsonify({"status": "cancelled"})


@app.route("/api/status")
def status():
    snap = session.snapshot() if session is not None else {"status": "idle"}
    snap["recording"] = bool(recorder is not None and recorder.recording)
    snap["auto_stop_reason"] = auto_stop_reason
    return jsonify(snap)


@app.route("/api/level")
def level():
    """Poll liviano durante la grabación: nivel de audio + transcripción parcial."""
    rec = bool(recorder is not None and recorder.recording)
    live = session.live_state() if session is not None else {"partial": "", "done_chunks": 0}
    return jsonify({
        "recording": rec,
        "paused": bool(recorder is not None and recorder.paused) if rec else False,
        "level": float(recorder.level) if rec else 0.0,
        "peak": float(recorder.peak) if rec else 0.0,
        "partial": live["partial"],
        "done_chunks": live["done_chunks"],
        "auto_stop_reason": auto_stop_reason,
    })


@app.route("/api/pause", methods=["POST"])
def pause():
    if recorder is None or not recorder.recording:
        return jsonify({"error": "no se está grabando"}), 400
    recorder.pause()
    return jsonify({"status": "paused"})


@app.route("/api/resume", methods=["POST"])
def resume():
    if recorder is None or not recorder.recording:
        return jsonify({"error": "no se está grabando"}), 400
    recorder.resume()
    return jsonify({"status": "recording"})


@app.route("/api/health")
def health():
    names = [d["name"].lower() for d in sd.query_devices()] if sd is not None else []
    dev_name = config.get("AUDIO_DEVICE_NAME")
    return jsonify({
        "backend": config.get("CAPTURE_BACKEND"),
        "blackhole": any("blackhole" in n for n in names),
        "device": {"ok": find_input_device(dev_name) is not None, "name": dev_name},
        "api_key": bool(config.get("ANTHROPIC_API_KEY")),
        "notion": notion_sync.is_enabled(),
        "has_notes": len(storage.list_notes()) > 0,
    })


@app.route("/api/notes")
def notes():
    return jsonify(storage.list_notes())


@app.route("/api/notes/<int:note_id>")
def note(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    n = dict(n)
    n["segments_count"] = len(n.get("segments") or [])  # el front solo necesita saber si hay
    n.pop("segments", None)                               # (los segmentos completos pesan)
    n.pop("audio_dir", None)                              # no exponemos la ruta del disco
    return jsonify(n)


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    if not storage.delete_note(note_id):
        return jsonify({"error": "not_found"}), 404
    return jsonify({"status": "deleted", "id": note_id})


@app.route("/api/notes/<int:note_id>", methods=["PATCH"])
def edit_note(note_id):
    data = request.get_json(silent=True) or {}
    title = data.get("title")
    summary = data.get("summary")
    if title is None and summary is None:
        return jsonify({"error": "nada para actualizar"}), 400
    if not storage.update_note(note_id, title=title, summary=summary):
        return jsonify({"error": "not_found"}), 404
    return jsonify(storage.get_note(note_id))


@app.route("/api/notes/<int:note_id>/resummarize", methods=["POST"])
def resummarize(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    transcript = (n.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"error": "Esta nota no tiene transcripción para resumir."}), 400

    data = request.get_json(silent=True) or {}
    ctype = data.get("context_type", "reunion")
    try:
        summary = summarize(transcript, n.get("manual_notes", ""), n.get("title", ""), ctype, "")
    except Exception as e:  # error de red/API: lo devolvemos para reintentar
        return jsonify({"error": f"No se pudo generar el resumen: {e}"}), 502

    storage.update_summary(note_id, summary)
    return jsonify({"summary": summary, "id": note_id})


def _note_or_404(note_id):
    """Carga la nota validando que tenga material; devuelve (note, error_response)."""
    n = storage.get_note(note_id)
    if not n:
        return None, (jsonify({"error": "not_found"}), 404)
    if not (n.get("transcript") or "").strip() and not (n.get("summary") or "").strip():
        return None, (jsonify({"error": "Esta nota no tiene contenido para analizar."}), 400)
    if not config.get("ANTHROPIC_API_KEY"):
        return None, (jsonify({"error": "Falta la API key de Claude (cargala en ⚙ Configuración)."}), 400)
    return n, None


@app.route("/api/notes/<int:note_id>/ask", methods=["POST"])
def ask_note(note_id):
    n, err = _note_or_404(note_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Escribí una pregunta."}), 400
    history = data.get("history") or []
    try:
        answer = assistant.ask(n, question, history)
    except Exception as e:
        return jsonify({"error": f"No pude responder: {e}"}), 502
    return jsonify({"answer": answer})


@app.route("/api/notes/<int:note_id>/followup", methods=["POST"])
def followup_note(note_id):
    n, err = _note_or_404(note_id)
    if err:
        return err
    try:
        text = assistant.followup_email(n)
    except Exception as e:
        return jsonify({"error": f"No pude redactar el email: {e}"}), 502
    return jsonify({"text": text})


@app.route("/api/notes/<int:note_id>/action-items", methods=["POST"])
def action_items_note(note_id):
    n, err = _note_or_404(note_id)
    if err:
        return err
    try:
        text = assistant.action_items(n)
    except Exception as e:
        return jsonify({"error": f"No pude extraer los pendientes: {e}"}), 502
    return jsonify({"text": text})


@app.route("/api/notes/<int:note_id>/moments", methods=["POST"])
def moments_note(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    payload = {"chunk_map": n.get("chunk_map") or [], "has_audio": bool(n.get("has_audio"))}
    if n.get("key_moments"):
        payload["moments"] = n["key_moments"]
        return jsonify(payload)
    if not (n.get("segments") or []):
        return jsonify({"error": "Esta nota no tiene marcas de tiempo (se grabó antes de esta función)."}), 400
    if not config.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "Falta la API key de Claude (cargala en ⚙ Configuración)."}), 400
    try:
        moments = assistant.key_moments(n)
    except Exception as e:
        return jsonify({"error": f"No pude detectar los momentos: {e}"}), 502
    storage.update_key_moments(note_id, moments)
    payload["moments"] = moments
    return jsonify(payload)


@app.route("/api/notes/<int:note_id>/audio/<int:chunk_index>")
def note_audio(note_id, chunk_index):
    """Sirve el WAV del tramo pedido (con soporte de rango, para poder buscar)."""
    n = storage.get_note(note_id)
    if not n or not n.get("audio_dir"):
        return jsonify({"error": "sin audio"}), 404
    entry = next((e for e in (n.get("chunk_map") or []) if e.get("i") == chunk_index), None)
    if not entry:
        return jsonify({"error": "tramo inexistente"}), 404
    fpath = Path(n["audio_dir"]) / entry["file"]
    if not fpath.exists():
        return jsonify({"error": "el audio de esta nota ya no está"}), 404
    return send_file(str(fpath), mimetype="audio/wav", conditional=True)


@app.route("/api/notes/<int:note_id>/dialogue", methods=["POST"])
def dialogue_note(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    if (n.get("dialogue") or "").strip():
        return jsonify({"text": n["dialogue"]})  # ya estaba generado: lo devolvemos cacheado
    if not (n.get("transcript") or "").strip():
        return jsonify({"error": "Esta nota no tiene transcripción para formatear."}), 400
    if not config.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "Falta la API key de Claude (cargala en ⚙ Configuración)."}), 400
    try:
        text = assistant.dialogue(n)
    except Exception as e:
        return jsonify({"error": f"No pude armar el diálogo: {e}"}), 502
    storage.update_dialogue(note_id, text)
    return jsonify({"text": text})


@app.route("/api/notes/<int:note_id>/enhance", methods=["POST"])
def enhance_note(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    if not (n.get("manual_notes") or "").strip():
        return jsonify({"error": "Esta nota no tiene notas manuales para realzar."}), 400
    if not config.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "Falta la API key de Claude (cargala en ⚙ Configuración)."}), 400
    try:
        text = assistant.enhance_notes(n)
    except Exception as e:
        return jsonify({"error": f"No pude realzar las notas: {e}"}), 502
    storage.update_enhanced_notes(note_id, text)
    return jsonify({"text": text})


@app.route("/api/notes/<int:note_id>/purge-audio", methods=["POST"])
def purge_one_note_audio(note_id):
    """Libera el audio (.wav) de una sola nota, conservando la nota."""
    if not storage.get_note(note_id):
        return jsonify({"error": "not_found"}), 404
    return jsonify(storage.purge_note_audio(note_id))


@app.route("/api/notes/<int:note_id>/download")
def download_note(note_id):
    md = storage.note_markdown(note_id)
    if md is None:
        return jsonify({"error": "not_found"}), 404
    n = storage.get_note(note_id)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", (n.get("title") or "reunion")).strip("-") or "reunion"
    return Response(md, mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.md"'})


@app.route("/api/recoverable")
def recoverable():
    """Carpetas de grabación que todavía no tienen una nota (audio sin procesar)."""
    used = {os.path.abspath(p) for p in storage.used_audio_dirs()}
    out = []
    for d in sorted(RECORDINGS_DIR.glob("meeting-*")):
        if not d.is_dir() or os.path.abspath(str(d)) in used:
            continue
        chunks = sorted(d.glob("chunk_*.wav")) or sorted(d.glob("*.wav"))
        if chunks:
            out.append({"folder": str(d), "name": d.name, "chunks": len(chunks)})
    return jsonify(out)


@app.route("/api/recover", methods=["POST"])
def recover():
    """Recupera una grabación desde sus .wav: re-transcribe y resume (reusa Session)."""
    global session, recorder
    if recorder is not None and recorder.recording:
        return jsonify({"error": "Hay una grabación en curso; esperá a que termine."}), 400

    data = request.get_json(silent=True) or {}
    folder = data.get("folder", "")
    p = Path(folder)
    if not folder or not p.exists():
        return jsonify({"error": "No encontré esa carpeta de grabación."}), 404
    chunks = sorted(p.glob("chunk_*.wav")) or sorted(p.glob("*.wav"))
    if not chunks:
        return jsonify({"error": "No hay archivos .wav en esa carpeta."}), 400

    title = (data.get("title") or "").strip() or f"Recuperada {p.name.replace('meeting-', '')}"
    ctype = data.get("context_type", "reunion")
    session = Session()
    for i, ch in enumerate(chunks):
        session.add_chunk(i, str(ch))
    # peak=1.0: ya no medimos nivel; si las transcripciones salen vacías avisa "sin voz".
    session.finish(len(chunks), 1.0, title, data.get("notes", ""), ctype, "", str(p))
    return jsonify({"status": "processing"})


@app.route("/api/audio-usage")
def audio_usage():
    """Cuánto espacio ocupan las grabaciones (procesadas vs. sin procesar)."""
    return jsonify(storage.audio_usage())


@app.route("/api/audio/purge-processed", methods=["POST"])
def purge_processed():
    """Libera los .wav de las grabaciones ya procesadas; conserva notas y resúmenes."""
    return jsonify(storage.purge_processed_audio())


@app.route("/api/audio/purge-orphans", methods=["POST"])
def purge_orphans():
    """Borra grabaciones sin procesar (sin nota). Excluye la grabación en curso."""
    exclude = recorder.session_dir if (recorder is not None and recorder.recording) else None
    return jsonify(storage.purge_orphan_audio(exclude=exclude))


if __name__ == "__main__":
    # Pedí permiso de micrófono al iniciar (sin esto, los dispositivos de entrada
    # pueden aparecer con 0 canales hasta concederlo).
    from mic_permission import request_microphone_access
    request_microphone_access()
    # Puerto 5001 para evitar el conflicto con AirPlay (5000) en macOS.
    app.run(debug=True, port=5001)
