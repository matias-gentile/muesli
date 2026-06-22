"""Procesamiento en segundo plano de una sesión de grabación.

Transcribe los chunks a medida que llegan (mientras se sigue grabando) y, al
finalizar, concatena las transcripciones en orden y genera un único resumen con
Claude. Expone un snapshot de estado para que el frontend muestre el progreso.

Estados: recording -> transcribing -> summarizing -> done | error
"""
from __future__ import annotations

import queue
import threading

import notion_sync
import storage
from summarize import summarize, type_label
from transcribe import transcribe


class Session:
    def __init__(self):
        self.status = "recording"
        self.total_chunks = None
        self.done_chunks = 0
        self.peak = 1.0
        self.result = None
        self.error = None
        self.title = ""
        self.manual_notes = ""
        self.context_type = "reunion"
        self.context = ""
        self.audio_dir = None
        self._transcripts: dict[int, str] = {}
        self._lock = threading.Lock()
        self._queue: "queue.Queue" = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---- API usada por app.py -------------------------------------------
    def add_chunk(self, index, path):
        """Encola un chunk recién cerrado para transcribir (FIFO, en orden)."""
        self._queue.put((index, str(path)))

    def finish(self, total_chunks, peak, title, manual_notes, context_type, context, audio_dir=None):
        """Señala que la grabación terminó; dispara el resumen final."""
        with self._lock:
            self.total_chunks = total_chunks
            self.peak = peak
            self.title = title
            self.manual_notes = manual_notes
            self.context_type = context_type
            self.context = context
            self.audio_dir = audio_dir
        self._queue.put(None)  # centinela: no hay más chunks

    def snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "done_chunks": self.done_chunks,
                "total_chunks": self.total_chunks,
                "result": self.result,
                "error": self.error,
            }

    # ---- interno ---------------------------------------------------------
    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _run(self):
        try:
            # Transcribe cada chunk a medida que llega (incluso durante la grabación).
            while True:
                item = self._queue.get()
                if item is None:
                    break
                index, path = item
                self._set(status="transcribing")
                text = transcribe(path)
                with self._lock:
                    self._transcripts[index] = text
                    self.done_chunks += 1

            transcript = "\n".join(
                self._transcripts[i] for i in sorted(self._transcripts)
            ).strip()

            if not transcript:
                if self.peak < 0.001:
                    self._set(status="error", error=(
                        "No se detectó audio (nivel ≈ 0). Poné la salida del sistema en "
                        "un Multi-Output Device que incluya BlackHole y volvé a probar."))
                else:
                    self._set(status="error", error=(
                        "Se grabó audio pero no se detectó voz para transcribir. Probá "
                        "subir el volumen de la fuente o acercar el micrófono."))
                return

            # El resumen llama a la API: si falla (p.ej. corte de red), NO perdemos la
            # transcripción. Guardamos igual y dejamos el resumen regenerable.
            self._set(status="summarizing")
            summary, summary_error = None, None
            try:
                summary = summarize(transcript, self.manual_notes, self.title,
                                    self.context_type, self.context)
            except Exception as e:
                summary_error = str(e)
                summary = (f"_El resumen automático falló ({e}). La transcripción está "
                           f"guardada — podés regenerar el resumen desde el panel._")

            note = storage.save_note(self.title, transcript, summary,
                                     self.manual_notes, self.audio_dir)

            notion_url, notion_error = None, None
            if summary_error is None and notion_sync.is_enabled():
                try:
                    notion_url = notion_sync.sync(
                        self.title, summary, type_label(self.context_type), note["created_at"])
                except Exception as e:
                    notion_error = str(e)
                    print(f"[notion] no se pudo sincronizar: {e}")

            self._set(result={"summary": summary, "transcript": transcript,
                              "note": note, "notion_url": notion_url,
                              "notion_error": notion_error, "summary_error": summary_error},
                      status="done")
        except Exception as e:
            self._set(status="error", error=f"fallo procesando: {e}")
