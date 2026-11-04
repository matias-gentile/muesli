"""Persistencia: guarda cada reunión como Markdown y la indexa en SQLite."""
import datetime
import json
import re
import shutil
import sqlite3
import threading
import uuid as uuidlib
from pathlib import Path

import config
from config import NOTES_DIR, DB_PATH, RECORDINGS_DIR

# Lo apunta server_sync.start(): se llama cuando una nota cambia, para mandarla enseguida a Memoria.
on_change = None

# La base se prepara (tablas y columnas nuevas) una sola vez por arranque. Con un candado: al abrir el panel
# llegan varios pedidos juntos y, con una base recién creada, dos querían agregar la misma columna a la vez
# («duplicate column name») y uno fallaba.
_schema_lock = threading.Lock()
_schema_ok = False


def _conn():
    global _schema_ok
    c = sqlite3.connect(DB_PATH)
    if not _schema_ok:
        with _schema_lock:
            if not _schema_ok:
                _prepare(c)
                _schema_ok = True
    return c


def _prepare(c):
    c.execute(
        """CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            created_at TEXT,
            path TEXT,
            transcript TEXT,
            summary TEXT,
            manual_notes TEXT,
            audio_dir TEXT,
            ctype TEXT
        )"""
    )
    # Migración para bases viejas: agrega columnas nuevas si faltan.
    cols = [r[1] for r in c.execute("PRAGMA table_info(notes)").fetchall()]
    if "audio_dir" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN audio_dir TEXT")
    if "ctype" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN ctype TEXT")
    if "enhanced_notes" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN enhanced_notes TEXT")
    if "dialogue" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN dialogue TEXT")
    if "segments" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN segments TEXT")        # timestamps por segmento
    if "chunk_map" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN chunk_map TEXT")        # tramos de audio
    if "key_moments" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN key_moments TEXT")      # momentos clave (cache)
    if "uuid" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN uuid TEXT")             # id global (Memoria, el server de casa)
    if "updated_at" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN updated_at TEXT")       # última edición (para sincronizar)
    # Notas de antes de sincronizar con Memoria: les falta el id global o la fecha de edición.
    if c.execute("SELECT 1 FROM notes WHERE uuid IS NULL OR updated_at IS NULL LIMIT 1").fetchone():
        for (nid,) in c.execute("SELECT id FROM notes WHERE uuid IS NULL").fetchall():
            c.execute("UPDATE notes SET uuid=? WHERE id=?", (str(uuidlib.uuid4()), nid))
        c.execute("UPDATE notes SET updated_at=substr(created_at, 1, 19) WHERE updated_at IS NULL")
    if "started_at" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN started_at TEXT")       # cuándo empezó la grabación
        for nid, created_at, audio_dir, chunk_map in c.execute(
                "SELECT id, created_at, audio_dir, chunk_map FROM notes").fetchall():
            try:
                chunks = json.loads(chunk_map) if chunk_map else []
                started = _started_at(audio_dir, datetime.datetime.fromisoformat(created_at), chunks)
                c.execute("UPDATE notes SET started_at=? WHERE id=?", (started, nid))
            except Exception:
                pass
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS notes_uuid ON notes(uuid)")
    # Cola de lo que falta mandar a Memoria (la vacía server_sync.py): una fila por nota, 'put' o 'delete'.
    c.execute(
        """CREATE TABLE IF NOT EXISTS sync_outbox (
            uuid TEXT PRIMARY KEY,
            op TEXT NOT NULL,
            queued_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
        )"""
    )
    c.commit()


def _started_at(audio_dir, created, chunk_map) -> str:
    """Hora de inicio de la grabación: sale del nombre de su carpeta (20261103-143000) y, si ya no
    está, de la hora en que se guardó la nota menos lo que duró el audio."""
    m = re.search(r"(\d{8}-\d{6})", Path(audio_dir).name) if audio_dir else None
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S").isoformat(timespec="seconds")
        except ValueError:
            pass
    dur = sum(float(ch.get("dur") or 0) for ch in (chunk_map or []) if isinstance(ch, dict))
    return (created - datetime.timedelta(seconds=dur)).isoformat(timespec="seconds")


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _enqueue(c, note_uuid, op, replace=True):
    """Deja la nota en la cola para Memoria (solo si esta Mac está conectada a un server de casa)."""
    if not note_uuid or not config.get("MEMORIA_TOKEN"):
        return
    queued = datetime.datetime.now().isoformat()  # con microsegundos: distingue dos cambios seguidos
    if replace:
        c.execute(
            "INSERT INTO sync_outbox (uuid, op, queued_at) VALUES (?,?,?) ON CONFLICT(uuid) DO UPDATE SET "
            "op=excluded.op, queued_at=excluded.queued_at, attempts=0, last_error=NULL",
            (note_uuid, op, queued))
    else:
        c.execute("INSERT OR IGNORE INTO sync_outbox (uuid, op, queued_at) VALUES (?,?,?)",
                  (note_uuid, op, queued))


def _touch(c, note_id):
    """Marca la nota como editada y la encola para Memoria (los resúmenes semanales no se mandan)."""
    c.execute("UPDATE notes SET updated_at=? WHERE id=?", (_now(), note_id))
    row = c.execute("SELECT uuid, ctype FROM notes WHERE id=?", (note_id,)).fetchone()
    if row and row[1] != "semanal":
        _enqueue(c, row[0], "put")


def _notify():
    if on_change:
        try:
            on_change()
        except Exception:
            pass


def _slugify(title: str) -> str:
    safe = "".join(ch for ch in title if ch.isalnum() or ch in " -_").strip()
    return safe.replace(" ", "-") or "reunion"


def _render_md(title, created, summary, manual_notes, transcript) -> str:
    return (
        f"# {title}\n\n"
        f"_{created.strftime('%Y-%m-%d %H:%M')}_\n\n"
        f"{summary}\n\n"
        f"---\n\n"
        f"## Mis notas\n\n{(manual_notes or '').strip() or '_(sin notas manuales)_'}\n\n"
        f"## Transcripción completa\n\n{(transcript or '').strip() or '_(vacía)_'}\n"
    )


def save_note(title, transcript, summary, manual_notes="", audio_dir=None, ctype=None,
              segments=None, chunk_map=None) -> dict:
    created = datetime.datetime.now()
    title = (title or "").strip() or "Reunión"
    fname = f"{created.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}.md"
    path = NOTES_DIR / fname

    path.write_text(_render_md(title, created, summary, manual_notes, transcript), encoding="utf-8")

    note_uuid = str(uuidlib.uuid4())
    c = _conn()
    cur = c.execute(
        "INSERT INTO notes (title, created_at, path, transcript, summary, manual_notes, "
        "audio_dir, ctype, segments, chunk_map, uuid, updated_at, started_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (title, created.isoformat(), str(path), transcript, summary, manual_notes,
         str(audio_dir) if audio_dir else None, ctype,
         json.dumps(segments or [], ensure_ascii=False),
         json.dumps(chunk_map or [], ensure_ascii=False), note_uuid, _now(),
         _started_at(audio_dir, created, chunk_map)),
    )
    note_id = cur.lastrowid
    if ctype != "semanal":
        _enqueue(c, note_uuid, "put")
    c.commit()
    c.close()
    _notify()
    return {
        "id": note_id, "title": title, "created_at": created.isoformat(),
        "path": str(path), "summary": summary, "ctype": ctype,
        "manual_notes": manual_notes, "uuid": note_uuid,
    }


def update_note(note_id, title=None, summary=None) -> bool:
    """Actualiza título y/o resumen de una nota y reescribe su .md."""
    c = _conn()
    row = c.execute(
        "SELECT title, created_at, path, transcript, summary, manual_notes FROM notes WHERE id=?",
        (note_id,),
    ).fetchone()
    if not row:
        c.close()
        return False
    cur_title, created_at, path, transcript, cur_summary, manual_notes = row
    new_title = (title if title is not None else cur_title)
    new_title = (new_title or "").strip() or "Reunión"
    new_summary = summary if summary is not None else cur_summary
    c.execute("UPDATE notes SET title=?, summary=? WHERE id=?", (new_title, new_summary, note_id))
    _touch(c, note_id)
    c.commit()
    c.close()
    _notify()
    if path:
        try:
            created = datetime.datetime.fromisoformat(created_at)
            Path(path).write_text(
                _render_md(new_title, created, new_summary, manual_notes, transcript), encoding="utf-8")
        except Exception:
            pass
    return True


def update_summary(note_id, summary) -> bool:
    """Reemplaza solo el resumen de una nota (usado al regenerar)."""
    return update_note(note_id, summary=summary)


def used_audio_dirs() -> set:
    """Carpetas de audio que ya tienen una nota asociada (para no re-procesarlas)."""
    c = _conn()
    rows = c.execute("SELECT audio_dir FROM notes WHERE audio_dir IS NOT NULL").fetchall()
    c.close()
    return {r[0] for r in rows if r[0]}


def _dir_size(path) -> int:
    """Tamaño total en bytes de una carpeta (0 si no existe)."""
    p = Path(path)
    total = 0
    if p.exists():
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total


def audio_usage() -> dict:
    """Espacio ocupado por las grabaciones, separando 'procesadas' (con nota) de
    'sin procesar' (carpetas sueltas que todavía no se transcribieron)."""
    used = used_audio_dirs()
    used_resolved = {str(Path(d).resolve()) for d in used}
    processed_bytes = sum(_dir_size(d) for d in used)

    orphan_bytes = 0
    orphan_count = 0
    if RECORDINGS_DIR.exists():
        for sub in RECORDINGS_DIR.iterdir():
            if sub.is_dir() and str(sub.resolve()) not in used_resolved:
                orphan_bytes += _dir_size(sub)
                orphan_count += 1

    return {
        "processed_count": len(used),
        "processed_bytes": processed_bytes,
        "orphan_count": orphan_count,
        "orphan_bytes": orphan_bytes,
        "total_bytes": processed_bytes + orphan_bytes,
    }


def purge_processed_audio() -> dict:
    """Borra los .wav de las grabaciones YA PROCESADAS (las que tienen nota), dejando
    intactas la transcripción y el resumen. Marca esas notas como sin audio."""
    used = used_audio_dirs()
    removed = 0
    freed = 0
    for d in used:
        freed += _dir_size(d)
        shutil.rmtree(d, ignore_errors=True)
        if not Path(d).exists():
            removed += 1
    c = _conn()
    c.execute("UPDATE notes SET audio_dir=NULL WHERE audio_dir IS NOT NULL")
    c.commit()
    c.close()
    return {"removed": removed, "freed_bytes": freed}


def purge_orphan_audio(exclude=None) -> dict:
    """Borra carpetas de grabación SIN nota asociada (sin procesar). `exclude` permite
    excluir la grabación en curso para no tocarla."""
    used_resolved = {str(Path(d).resolve()) for d in used_audio_dirs()}
    if exclude:
        used_resolved.add(str(Path(exclude).resolve()))
    removed = 0
    freed = 0
    if RECORDINGS_DIR.exists():
        for sub in list(RECORDINGS_DIR.iterdir()):
            if sub.is_dir() and str(sub.resolve()) not in used_resolved:
                freed += _dir_size(sub)
                shutil.rmtree(sub, ignore_errors=True)
                if not sub.exists():
                    removed += 1
    return {"removed": removed, "freed_bytes": freed}


def purge_note_audio(note_id: int) -> dict:
    """Borra solo el audio de una nota puntual, conservando la nota."""
    c = _conn()
    row = c.execute("SELECT audio_dir FROM notes WHERE id=?", (note_id,)).fetchone()
    if not row or not row[0]:
        c.close()
        return {"removed": 0, "freed_bytes": 0}
    audio_dir = row[0]
    freed = _dir_size(audio_dir)
    shutil.rmtree(audio_dir, ignore_errors=True)
    c.execute("UPDATE notes SET audio_dir=NULL WHERE id=?", (note_id,))
    c.commit()
    c.close()
    return {"removed": 1, "freed_bytes": freed}


def list_notes() -> list:
    c = _conn()
    rows = c.execute(
        "SELECT id, title, created_at, ctype FROM notes ORDER BY created_at DESC"
    ).fetchall()
    c.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "ctype": r[3]} for r in rows]


def notes_for_weekly(since_iso: str) -> list:
    """Notas creadas desde `since_iso` con su resumen, para el digest semanal.
    Excluye los resúmenes semanales (ctype 'semanal') para que no se incluyan a sí mismos.
    Orden cronológico ascendente (como transcurrió la semana)."""
    c = _conn()
    rows = c.execute(
        "SELECT id, title, created_at, ctype, summary FROM notes "
        "WHERE created_at >= ? AND (ctype IS NULL OR ctype != 'semanal') "
        "ORDER BY created_at ASC",
        (since_iso,),
    ).fetchall()
    c.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "ctype": r[3],
             "summary": r[4] or ""} for r in rows]


def get_note(note_id: int):
    c = _conn()
    r = c.execute(
        f"SELECT {_NOTE_COLS} FROM notes WHERE id=?", (note_id,)
    ).fetchone()
    c.close()
    return _note_dict(r)


_NOTE_COLS = ("id, title, created_at, path, transcript, summary, manual_notes, ctype, "
              "audio_dir, enhanced_notes, dialogue, segments, chunk_map, key_moments, uuid, updated_at, "
              "started_at")


def _note_dict(r):
    if not r:
        return None

    def _loads(s):
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    return {
        "id": r[0], "title": r[1], "created_at": r[2], "path": r[3],
        "transcript": r[4], "summary": r[5], "manual_notes": r[6], "ctype": r[7],
        "has_audio": bool(r[8]), "audio_dir": r[8],
        "enhanced_notes": r[9] or "", "dialogue": r[10] or "",
        "segments": _loads(r[11]), "chunk_map": _loads(r[12]),
        "key_moments": _loads(r[13]), "uuid": r[14], "updated_at": r[15],
        "started_at": r[16] or r[2],
    }


def get_note_by_uuid(note_uuid: str):
    c = _conn()
    r = c.execute(f"SELECT {_NOTE_COLS} FROM notes WHERE uuid=?", (note_uuid,)).fetchone()
    c.close()
    return _note_dict(r)


def update_key_moments(note_id: int, moments: list) -> bool:
    """Guarda los momentos clave (cache) de una nota."""
    c = _conn()
    cur = c.execute("UPDATE notes SET key_moments=? WHERE id=?",
                    (json.dumps(moments or [], ensure_ascii=False), note_id))
    ok = cur.rowcount > 0
    if ok:
        _touch(c, note_id)
    c.commit()
    c.close()
    if ok:
        _notify()
    return ok


def update_enhanced_notes(note_id: int, enhanced_notes: str) -> bool:
    """Guarda las notas realzadas (modo 'notas + IA') de una nota."""
    c = _conn()
    cur = c.execute("UPDATE notes SET enhanced_notes=? WHERE id=?", (enhanced_notes, note_id))
    ok = cur.rowcount > 0
    if ok:
        _touch(c, note_id)
    c.commit()
    c.close()
    if ok:
        _notify()
    return ok


def update_dialogue(note_id: int, dialogue: str) -> bool:
    """Guarda la transcripción formateada como diálogo (oradores inferidos)."""
    c = _conn()
    cur = c.execute("UPDATE notes SET dialogue=? WHERE id=?", (dialogue, note_id))
    ok = cur.rowcount > 0
    if ok:
        _touch(c, note_id)
    c.commit()
    c.close()
    if ok:
        _notify()
    return ok


def note_markdown(note_id: int):
    """Reconstruye el Markdown de una nota desde la DB (para exportar/descargar)."""
    n = get_note(note_id)
    if not n:
        return None
    created = datetime.datetime.fromisoformat(n["created_at"])
    return _render_md(n["title"], created, n["summary"], n["manual_notes"], n["transcript"])


def delete_note(note_id: int) -> bool:
    """Borra la nota: fila en la DB, su .md y la carpeta de audio (best-effort)."""
    c = _conn()
    row = c.execute("SELECT path, audio_dir, uuid, ctype FROM notes WHERE id=?", (note_id,)).fetchone()
    if not row:
        c.close()
        return False
    md_path, audio_dir, note_uuid, ctype = row
    c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    if ctype != "semanal":
        _enqueue(c, note_uuid, "delete")  # en Memoria va a la papelera
    c.commit()
    c.close()
    _notify()

    if md_path:
        try:
            Path(md_path).unlink()
        except OSError:
            pass
    if audio_dir:
        shutil.rmtree(audio_dir, ignore_errors=True)
    return True


# --- Cola de envíos a Memoria (el server de casa). La usa server_sync.py. ---

OUTBOX_PARKED = 1_000_000  # attempts con este valor = el server la rechazó; se reintenta si la nota cambia


def outbox_items(limit=20) -> list:
    """Lo que falta mandar, lo más viejo primero (sin las que el server rechazó)."""
    c = _conn()
    rows = c.execute(
        "SELECT uuid, op, queued_at FROM sync_outbox WHERE attempts < ? ORDER BY queued_at LIMIT ?",
        (OUTBOX_PARKED, limit),
    ).fetchall()
    c.close()
    return [{"uuid": r[0], "op": r[1], "queued_at": r[2]} for r in rows]


def outbox_done(note_uuid: str, queued_at: str):
    """Saca un envío de la cola, salvo que la nota haya cambiado otra vez mientras se mandaba."""
    c = _conn()
    c.execute("DELETE FROM sync_outbox WHERE uuid=? AND queued_at=?", (note_uuid, queued_at))
    c.commit()
    c.close()


def outbox_park(note_uuid: str, queued_at: str, error: str):
    """El server rechazó este envío: queda apartado (no se reintenta solo) con el motivo."""
    c = _conn()
    c.execute("UPDATE sync_outbox SET attempts=?, last_error=? WHERE uuid=? AND queued_at=?",
              (OUTBOX_PARKED, str(error)[:500], note_uuid, queued_at))
    c.commit()
    c.close()


def outbox_counts() -> dict:
    """Cuántas faltan mandar, cuántas rechazó el server y el último motivo."""
    c = _conn()
    pending = c.execute("SELECT COUNT(*) FROM sync_outbox WHERE attempts < ?", (OUTBOX_PARKED,)).fetchone()[0]
    parked = c.execute(
        "SELECT COUNT(*), MAX(last_error) FROM sync_outbox WHERE attempts >= ?", (OUTBOX_PARKED,)
    ).fetchone()
    c.close()
    return {"pending": pending, "rejected": parked[0], "rejected_reason": parked[1]}


def outbox_clear():
    c = _conn()
    c.execute("DELETE FROM sync_outbox")
    c.commit()
    c.close()


def enqueue_missing(server_states: dict) -> int:
    """Encola las notas que el server no tiene o tiene en una versión más vieja (carga inicial y
    por si algo se perdió). `server_states` es {uuid: {"updated_at": ..., "deleted": bool}}, lo que
    devuelve Memoria. Lo que ya está en la cola no se toca. Devuelve cuántas encoló."""
    c = _conn()
    rows = c.execute(
        "SELECT uuid, updated_at FROM notes WHERE ctype IS NULL OR ctype != 'semanal'"
    ).fetchall()
    n = 0
    for note_uuid, updated_at in rows:
        st = server_states.get(note_uuid)
        if st and not st.get("deleted") and (st.get("updated_at") or "")[:19] >= (updated_at or "")[:19]:
            continue
        before = c.total_changes
        _enqueue(c, note_uuid, "put", replace=False)
        n += c.total_changes - before
    c.commit()
    c.close()
    return n
