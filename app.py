"""App Flask: panel de control para grabar, transcribir y resumir reuniones."""
from __future__ import annotations

import sounddevice as sd
from flask import Flask, jsonify, render_template, request

import storage
import notion_sync
from audio_capture import Recorder
from config import AUDIO_DEVICE_NAME, AUDIO_DEVICE_OUTPUT_ONLY
from summarize import list_templates, summarize, type_label
from transcribe import transcribe

app = Flask(__name__)
recorder: Recorder | None = None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices")
def devices():
    out = [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]
    return jsonify({"configured": AUDIO_DEVICE_NAME, "devices": out})


@app.route("/api/templates")
def templates():
    """Tipos de grabación disponibles para el selector del frontend."""
    return jsonify(list_templates())


@app.route("/api/start", methods=["POST"])
def start():
    global recorder
    if recorder is not None and recorder.recording:
        return jsonify({"status": "already_recording"})

    data = request.get_json(silent=True) or {}
    # "full" = salida del sistema + micrófono; "output" = solo salida del sistema.
    mode = data.get("mode", "full")
    device = AUDIO_DEVICE_OUTPUT_ONLY if mode == "output" else AUDIO_DEVICE_NAME

    try:
        recorder = Recorder(device_name=device)
        path = recorder.start()
    except Exception as e:  # dispositivo no encontrado, permisos, etc.
        return jsonify({"error": str(e)}), 400
    return jsonify({"status": "recording", "file": str(path), "mode": mode})


@app.route("/api/stop", methods=["POST"])
def stop():
    global recorder
    if recorder is None or not recorder.recording:
        return jsonify({"error": "no se está grabando"}), 400

    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    manual_notes = data.get("notes", "")
    context_type = data.get("context_type", "reunion")
    context = data.get("context", "")

    wav_path = recorder.stop()

    # Si no entró audio (nivel ≈ 0), avisamos en vez de resumir el vacío.
    if getattr(recorder, "peak", 1.0) < 0.001:
        return jsonify({"error": "No se detectó audio (nivel ≈ 0). Antes de grabar, poné "
                                 "la salida del sistema en el Multi-Output Device. En modo "
                                 "'solo salida', BlackHole solo capta si el sonido del "
                                 "sistema pasa por ahí."}), 200

    try:
        transcript = transcribe(wav_path)
    except Exception as e:
        return jsonify({"error": f"fallo transcribiendo: {e}"}), 500

    if not transcript.strip():
        return jsonify({"error": "Se grabó audio pero no se detectó voz para transcribir. "
                                 "Puede ser contenido sin habla, volumen muy bajo o ruido. "
                                 "Probá subir el volumen de la fuente o acercar el micrófono."}), 200

    try:
        summary = summarize(transcript, manual_notes, title, context_type, context)
    except Exception as e:
        return jsonify({"error": f"fallo resumiendo: {e}"}), 500

    note = storage.save_note(title, transcript, summary, manual_notes)

    # Sincronización opcional con Notion (no rompe el guardado local si falla).
    notion_url = None
    try:
        notion_url = notion_sync.sync(title, summary, type_label(context_type), note["created_at"])
    except Exception as e:
        print(f"[notion] no se pudo sincronizar: {e}")

    return jsonify({"status": "done", "note": note, "transcript": transcript,
                    "summary": summary, "notion_url": notion_url})


@app.route("/api/notes")
def notes():
    return jsonify(storage.list_notes())


@app.route("/api/notes/<int:note_id>")
def note(note_id):
    n = storage.get_note(note_id)
    if not n:
        return jsonify({"error": "not_found"}), 404
    return jsonify(n)


if __name__ == "__main__":
    # Puerto 5001 para evitar el conflicto con AirPlay (5000) en macOS.
    app.run(debug=True, port=5001)
