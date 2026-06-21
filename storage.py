"""Persistencia: guarda cada reunión como Markdown y la indexa en SQLite."""
import datetime
import sqlite3

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
            manual_notes TEXT
        )"""
    )
    return c


def _slugify(title: str) -> str:
    safe = "".join(ch for ch in title if ch.isalnum() or ch in " -_").strip()
    return safe.replace(" ", "-") or "reunion"


def save_note(title: str, transcript: str, summary: str, manual_notes: str = "") -> dict:
    created = datetime.datetime.now()
    title = title.strip() or "Reunión"
    fname = f"{created.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}.md"
    path = NOTES_DIR / fname

    md = (
        f"# {title}\n\n"
        f"_{created.strftime('%Y-%m-%d %H:%M')}_\n\n"
        f"{summary}\n\n"
        f"---\n\n"
        f"## Mis notas\n\n{manual_notes.strip() or '_(sin notas manuales)_'}\n\n"
        f"## Transcripción completa\n\n{transcript.strip() or '_(vacía)_'}\n"
    )
    path.write_text(md, encoding="utf-8")

    c = _conn()
    cur = c.execute(
        "INSERT INTO notes (title, created_at, path, transcript, summary, manual_notes) "
        "VALUES (?,?,?,?,?,?)",
        (title, created.isoformat(), str(path), transcript, summary, manual_notes),
    )
    c.commit()
    note_id = cur.lastrowid
    c.close()
    return {
        "id": note_id,
        "title": title,
        "created_at": created.isoformat(),
        "path": str(path),
        "summary": summary,
    }


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
