"""Estimación local del gasto de la API de Claude.

Cuenta los tokens REALES que devuelve cada respuesta (``response.usage``) y los
multiplica por el precio del modelo. No es el saldo oficial de Anthropic —eso
solo se ve en console.anthropic.com— pero da un estimado preciso de lo que se
gasta con Muesli, mes a mes.
"""
import datetime
import sqlite3

from config import DB_PATH

# Precio por millón de tokens (USD): (entrada, salida). Aprox. junio 2026.
PRICING = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS usage ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, model TEXT, "
        "kind TEXT, input_tokens INTEGER, output_tokens INTEGER)"
    )
    return c


def cost_of(model, inp, out):
    """Costo en USD, o None si no conocemos el precio de ese modelo."""
    p = PRICING.get(model)
    if not p:
        return None
    return inp / 1_000_000 * p[0] + out / 1_000_000 * p[1]


def record(model, input_tokens, output_tokens, kind="asistente"):
    """Guarda una llamada a la API (tokens reales) en la base local."""
    if not (input_tokens or output_tokens):
        return
    try:
        c = _conn()
        c.execute(
            "INSERT INTO usage (created_at, model, kind, input_tokens, output_tokens) "
            "VALUES (?,?,?,?,?)",
            (datetime.datetime.now().isoformat(), model or "?", kind,
             int(input_tokens or 0), int(output_tokens or 0)),
        )
        c.commit()
        c.close()
    except Exception as e:
        print(f"[usage] no pude registrar el uso: {e}")


def record_response(model, resp, kind="asistente"):
    """Registra el uso a partir de una respuesta del SDK de Anthropic."""
    try:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        record(model, getattr(u, "input_tokens", 0) or 0,
               getattr(u, "output_tokens", 0) or 0, kind)
    except Exception:
        pass


def _bucket(rows):
    """Agrega filas (model, input, output) por modelo y calcula el costo total."""
    by_model = {}
    for model, inp, out in rows:
        d = by_model.setdefault(model, {"input": 0, "output": 0, "calls": 0})
        d["input"] += inp
        d["output"] += out
        d["calls"] += 1
    total_cost, total_in, total_out, calls, unknown = 0.0, 0, 0, 0, False
    models = []
    for model, d in sorted(by_model.items(), key=lambda kv: -(kv[1]["input"] + kv[1]["output"])):
        cst = cost_of(model, d["input"], d["output"])
        if cst is None:
            unknown = True
        total_cost += (cst or 0.0)
        total_in += d["input"]
        total_out += d["output"]
        calls += d["calls"]
        models.append({"model": model, "input": d["input"], "output": d["output"],
                       "calls": d["calls"],
                       "cost": (round(cst, 4) if cst is not None else None)})
    return {"cost": round(total_cost, 4), "input_tokens": total_in,
            "output_tokens": total_out, "calls": calls,
            "by_model": models, "has_unknown": unknown}


def summary():
    """Resumen de gasto del mes actual y de todo el historial."""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT model, input_tokens, output_tokens, created_at FROM usage").fetchall()
        c.close()
    except Exception:
        rows = []
    month_prefix = datetime.datetime.now().strftime("%Y-%m")
    month_rows = [(m, i, o) for (m, i, o, ts) in rows if (ts or "").startswith(month_prefix)]
    all_rows = [(m, i, o) for (m, i, o, ts) in rows]
    return {
        "month": _bucket(month_rows),
        "all_time": _bucket(all_rows),
        "month_label": month_prefix,
    }


def reset():
    """Borra todo el historial de uso (no afecta las notas)."""
    try:
        c = _conn()
        c.execute("DELETE FROM usage")
        c.commit()
        c.close()
        return True
    except Exception:
        return False
