"""Persistencia: guarda cada reunión como Markdown y la indexa en SQLite."""
import datetime
import shutil
import sqlite3
from pathlib import Path

from config import NOTES_DIR, DB_PATH


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
            audio_dir TEXT
        )"""
    )
    # Migración para bases viejas: agrega audio_dir si falta.
    cols = [r[1] for r in c.execute("PRAGMA table_info(notes)").fetchall()]
    if "audio_dir" not in cols:
        c.execute("ALTER TABLE notes ADD COLUMN audio_dir TEXT")
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


def save_note(title, transcript, summary, manual_notes="", audio_dir=None) -> dict:
    created = datetime.datetime.now()
    title = (title or "").strip() or "Reunión"
    fname = f"{created.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}.md"
    path = NOTES_DIR / fname

    path.write_text(_render_md(title, created, summary, manual_notes, transcript), encoding="utf-8")

    c = _conn()
    cur = c.execute(
        "INSERT INTO notes (title, created_at, path, transcript, summary, manual_notes, audio_dir) "
        "VALUES (?,?,?,?,?,?,?)",
        (title, created.isoformat(), str(path), transcript, summary, manual_notes,
         str(audio_dir) if audio_dir else None),
    )
    c.commit()
    note_id = cur.lastrowid
    c.close()
    return {
        "id": note_id, "title": title, "created_at": created.isoformat(),
        "path": str(path), "summary": summary,
    }


def update_summary(note_id, summary) -> bool:
    """Reemplaza el resumen de una nota existente (regenerar) y reescribe su .md."""
    c = _conn()
    row = c.execute(
        "SELECT title, created_at, path, transcript, manual_notes FROM notes WHERE id=?",
        (note_id,),
    ).fetchone()
    if not row:
        c.close()
        return False
    title, created_at, path, transcript, manual_notes = row
    c.execute("UPDATE notes SET summary=? WHERE id=?", (summary, note_id))
    c.commit()
    c.close()
    if path:
        try:
            created = datetime.datetime.fromisoformat(created_at)
            Path(path).write_text(
                _render_md(title, created, summary, manual_notes, transcript), encoding="utf-8")
        except Exception:
            pass
    return True


def list_notes() -> list:
    c = _conn()
    rows = c.execute(
        "SELECT id, title, created_at FROM notes ORDER BY created_at DESC"
    ).fetchall()
    c.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]


def get_note(note_id: int):
    c = _conn()
    r = c.execute(
        "SELECT id, title, created_at, path, transcript, summary, manual_notes "
        "FROM notes WHERE id=?",
        (note_id,),
    ).fetchone()
    c.close()
    if not r:
        return None
    return {
        "id": r[0], "title": r[1], "created_at": r[2], "path": r[3],
        "transcript": r[4], "summary": r[5], "manual_notes": r[6],
    }


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
