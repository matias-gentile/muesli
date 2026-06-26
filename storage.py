"""Persistencia: guarda cada reunión como Markdown y la indexa en SQLite."""
import datetime
import shutil
import sqlite3
from pathlib import Path

from config import NOTES_DIR, DB_PATH, RECORDINGS_DIR


def _conn():
    c = sqlite3.connect(DB_PATH)
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
    c.commit()
    return c


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


def save_note(title, transcript, summary, manual_notes="", audio_dir=None, ctype=None) -> dict:
    created = datetime.datetime.now()
    title = (title or "").strip() or "Reunión"
    fname = f"{created.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}.md"
    path = NOTES_DIR / fname

    path.write_text(_render_md(title, created, summary, manual_notes, transcript), encoding="utf-8")

    c = _conn()
    cur = c.execute(
        "INSERT INTO notes (title, created_at, path, transcript, summary, manual_notes, audio_dir, ctype) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (title, created.isoformat(), str(path), transcript, summary, manual_notes,
         str(audio_dir) if audio_dir else None, ctype),
    )
    c.commit()
    note_id = cur.lastrowid
    c.close()
    return {
        "id": note_id, "title": title, "created_at": created.isoformat(),
        "path": str(path), "summary": summary, "ctype": ctype,
        "manual_notes": manual_notes,
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
    c.commit()
    c.close()
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


def get_note(note_id: int):
    c = _conn()
    r = c.execute(
        "SELECT id, title, created_at, path, transcript, summary, manual_notes, ctype, "
        "audio_dir, enhanced_notes FROM notes WHERE id=?",
        (note_id,),
    ).fetchone()
    c.close()
    if not r:
        return None
    return {
        "id": r[0], "title": r[1], "created_at": r[2], "path": r[3],
        "transcript": r[4], "summary": r[5], "manual_notes": r[6], "ctype": r[7],
        "has_audio": bool(r[8]), "enhanced_notes": r[9] or "",
    }


def update_enhanced_notes(note_id: int, enhanced_notes: str) -> bool:
    """Guarda las notas realzadas (modo 'notas + IA') de una nota."""
    c = _conn()
    cur = c.execute("UPDATE notes SET enhanced_notes=? WHERE id=?", (enhanced_notes, note_id))
    c.commit()
    ok = cur.rowcount > 0
    c.close()
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
    row = c.execute("SELECT path, audio_dir FROM notes WHERE id=?", (note_id,)).fetchone()
    if not row:
        c.close()
        return False
    md_path, audio_dir = row
    c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    c.commit()
    c.close()

    if md_path:
        try:
            Path(md_path).unlink()
        except OSError:
            pass
    if audio_dir:
        shutil.rmtree(audio_dir, ignore_errors=True)
    return True
