"""App Flask: panel de control para grabar, transcribir y resumir reuniones.

La grabación se hace en chunks y el procesado (transcripción + resumen) corre en
segundo plano; /api/stop devuelve enseguida y el frontend consulta /api/status.
"""
from __future__ import annotations

import sounddevice as sd
from flask import Flask, jsonify, render_template, request

import storage
from audio_capture import ChunkedRecorder
from config import AUDIO_DEVICE_NAME, AUDIO_DEVICE_OUTPUT_ONLY, CHUNK_SECONDS
from session import Session
from summarize import list_templates, summarize, type_label

app = Flask(__name__)
recorder: ChunkedRecorder | None = None
session: Session | None = None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices")
def devices():
    out = [{"index": i, "name": d["name"], "channels": d["max_input_channels"]}
           for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    return jsonify({"configured": AUDIO_DEVICE_NAME, "devices": out})


@app.route("/api/templates")
def templates():
    return jsonify(list_templates())


@app.route("/api/start", methods=["POST"])
def start():
    global recorder, session
    if recorder is not None and recorder.recording:
        return jsonify({"status": "already_recording"})

    data = request.get_json(silent=True) or {}
    # "full" = salida del sistema + micrófono; "output" = solo salida del sistema.
    mode = data.get("mode", "full")
    device = AUDIO_DEVICE_OUTPUT_ONLY if mode == "output" else AUDIO_DEVICE_NAME

    try:
        session = Session()
        recorder = ChunkedRecorder(device_name=device, on_chunk=session.add_chunk,
                                   chunk_seconds=CHUNK_SECONDS)
        recorder.start()
    except Exception as e:  # dispositivo no encontrado, permisos, etc.
        return jsonify({"error": str(e)}), 400
    return jsonify({"status": "recording", "mode": mode})


@app.route("/api/stop", methods=["POST"])
def stop():
    global recorder, session
    if recorder is None or not recorder.recording:
        return jsonify({"error": "no se está grabando"}), 400

    data = request.get_json(silent=True) or {}
    total = recorder.stop()  # finaliza el último chunk; los chunks ya fueron encolados
    session.finish(total, recorder.peak,
                   data.get("title", ""), data.get("notes", ""),
                   data.get("context_type", "reunion"), data.get("context", ""),
                   str(recorder.session_dir))
    return jsonify({"status": "processing"})


@app.route("/api/status")
def status():
    snap = session.snapshot() if session is not None else {"status": "idle"}
    snap["recording"] = bool(recorder is not None and recorder.recording)
    return jsonify(snap)


@app.route("/api/notes")
def notes():
    return jsonify(storage.list_notes())


@app.route("/api/notes/<int:note_id>")
def note(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    return jsonify(n)


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    if not storage.delete_note(note_id):
        return jsonify({"error": "not_found"}), 404
    return jsonify({"status": "deleted", "id": note_id})


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


if __name__ == "__main__":
    # Puerto 5001 para evitar el conflicto con AirPlay (5000) en macOS.
    app.run(debug=True, port=5001)
