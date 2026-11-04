"""Manda las charlas a Memoria, el server de casa que junta las de todas tus Macs.

Cómo funciona:
  - Cada vez que una nota se guarda, cambia o se borra, storage.py la deja en una cola (tabla
    sync_outbox). Solo si esta Mac está conectada a Memoria.
  - Un hilo vacía esa cola: PUT /api/v1/charlas/<uuid> con el texto de la nota (nunca el audio)
    o DELETE si la borraste (en Memoria va a la papelera).
  - Si el server no responde (estás fuera de casa, está apagado) la nota espera en la cola y se
    reintenta más tarde, cada vez con más espera (de 30 segundos a 10 minutos).
  - Cada 30 minutos compara con lo que tiene el server y encola lo que falte: así se manda la carga
    inicial al conectarse y se arregla cualquier envío que se haya perdido.
  - Los resúmenes semanales no se mandan: Memoria arma el suyo con las charlas de todas las Macs.

La Mac se conecta con un código de 8 números que se crea en Memoria → Compus (pair()).
Contrato de la API: casa-hub/apps/memoria/README.md.
"""
from __future__ import annotations

import datetime
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import storage

DEFAULT_URL = "http://memoria.local"
TIMEOUT = 20
RECONCILE_EVERY = 30 * 60
BACKOFF_MIN, BACKOFF_MAX = 30, 10 * 60
DEBOUNCE = 2  # segundos: junta los cambios seguidos de una misma nota (guardar + momentos clave…)

OFFLINE_MSG = "No llego al server de casa. Si estás fuera de casa, se mandan solas cuando vuelvas."
REVOKED_MSG = "Memoria desconectó esta Mac. Para seguir mandando notas, conectala de nuevo con un código nuevo."

_wake = threading.Event()
_force = threading.Event()  # «Mandar ahora»: comparar con el server sin esperar los 30 minutos
_lock = threading.Lock()
_thread = None
_state = {"last_ok": None, "error": None, "offline": False, "revoked": False}


class ServerError(Exception):
    """El server respondió, pero con un error (status HTTP). status 0 = no es un Memoria.
    from_memoria: la respuesta la armó Memoria (y no, por ejemplo, el login del edge)."""

    def __init__(self, status: int, message: str, from_memoria: bool = True):
        super().__init__(message)
        self.status = status
        self.from_memoria = from_memoria


# --- HTTP ---------------------------------------------------------------------------------------

def normalize_url(raw) -> str:
    """'memoria.local', 'http://192.168.1.3:8007/compus' → 'http://…' sin camino ni barra final."""
    raw = (raw or "").strip()
    if not raw:
        return DEFAULT_URL
    if "://" not in raw:
        raw = "http://" + raw
    u = urllib.parse.urlsplit(raw)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("Esa dirección no parece válida. Probá con memoria.local.")
    return f"{u.scheme}://{u.netloc}"


def _request(method, path, body=None, token=None, url=None, timeout=TIMEOUT):
    base = url or config.get("MEMORIA_URL") or DEFAULT_URL
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + "/api/v1" + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    token = config.get("MEMORIA_TOKEN") if token is None else token
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = None
        try:
            detail = json.loads(e.read() or b"{}").get("detail")
        except Exception:
            pass
        if detail is None and e.code in (401, 404):
            raise ServerError(e.code, "En esa dirección no hay un Memoria (o pide contraseña para la API).",
                              from_memoria=False)
        if not isinstance(detail, str):  # los errores de validación vienen como lista: no sirven para mostrar
            detail = None
        raise ServerError(e.code, detail or f"El server respondió con un error ({e.code}).")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        raise ServerError(0, "En esa dirección hay otra cosa, no un Memoria.")


# --- Qué se manda -------------------------------------------------------------------------------

def payload(n: dict) -> dict:
    dur = sum(float(ch.get("dur") or 0) for ch in (n.get("chunk_map") or []) if isinstance(ch, dict))
    moments = []
    for m in n.get("key_moments") or []:
        try:
            moments.append({"t": max(0.0, float(m["t"])), "label": str(m["label"])[:500]})
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "title": (n.get("title") or "")[:300],
        "started_at": n.get("started_at") or n["created_at"],
        "updated_at": n.get("updated_at") or n["created_at"][:19],
        "ctype": n.get("ctype"),
        "duration_sec": int(round(dur)) if dur else None,
        "local_id": n.get("id"),
        "summary": n.get("summary") or "",
        "manual_notes": n.get("manual_notes") or "",
        "transcript": n.get("transcript") or "",
        "enhanced_notes": n.get("enhanced_notes") or "",
        "dialogue": n.get("dialogue") or "",
        "key_moments": moments[:200],
    }


def _send(item):
    uuid, queued_at = item["uuid"], item["queued_at"]
    try:
        if item["op"] == "delete":
            try:
                _request("DELETE", f"/charlas/{uuid}")
            except ServerError as e:
                if e.status != 404 or not e.from_memoria:  # 404 de Memoria = nunca la tuvo: nada que borrar
                    raise
        else:
            n = storage.get_note_by_uuid(uuid)
            if n is not None:
                _request("PUT", f"/charlas/{uuid}", payload(n))
    except ServerError as e:
        if not e.from_memoria or e.status in (0, 401, 408, 429) or e.status >= 500:
            raise  # problema del server o de la conexión: se reintenta toda la cola más tarde
        storage.outbox_park(uuid, queued_at, str(e))  # la rechazó (400, 409, 422…): no insistir
        return
    storage.outbox_done(uuid, queued_at)


def flush() -> int:
    """Manda todo lo que hay en la cola. Corta en el primer problema de conexión."""
    sent = 0
    while True:
        items = storage.outbox_items(20)
        if not items:
            return sent
        for it in items:
            _send(it)
            sent += 1


def reconcile() -> int:
    """Pregunta qué tiene el server de esta Mac y encola lo que le falta."""
    me = _request("GET", "/yo")
    dev = me.get("device") or {}
    if dev.get("name") and (dev["name"] != config.get("MEMORIA_DEVICE") or dev.get("ambito") != config.get("MEMORIA_AMBITO")):
        config.update({"MEMORIA_DEVICE": dev["name"], "MEMORIA_AMBITO": dev.get("ambito") or ""}, managed=True)
    states = {s["uuid"]: s for s in _request("GET", "/charlas").get("charlas", []) if s.get("uuid")}
    return storage.enqueue_missing(states)


# --- El hilo ------------------------------------------------------------------------------------

def _set(**kw):
    with _lock:
        _state.update(kw)


def _loop():
    next_reconcile = 0.0
    backoff = 0
    while True:
        if not config.get("MEMORIA_TOKEN") or _state["revoked"]:
            _wake.wait()
            _wake.clear()
            next_reconcile = 0.0
            continue
        try:
            if _force.is_set() or time.monotonic() >= next_reconcile:
                _force.clear()
                reconcile()
                next_reconcile = time.monotonic() + RECONCILE_EVERY
            flush()
            backoff = 0
            _set(last_ok=datetime.datetime.now().isoformat(timespec="seconds"), error=None, offline=False)
            wait = max(1.0, next_reconcile - time.monotonic())
        except ServerError as e:
            if e.status == 401 and e.from_memoria:
                _set(revoked=True, error=REVOKED_MSG, offline=False)
                continue
            backoff = min(BACKOFF_MAX, max(BACKOFF_MIN, backoff * 2))
            _set(error=str(e), offline=False)
            wait = backoff
        except OSError:  # sin red, el server no responde, tardó demasiado
            backoff = min(BACKOFF_MAX, max(BACKOFF_MIN, backoff * 2))
            _set(error=OFFLINE_MSG, offline=True)
            wait = backoff
        except Exception as e:  # no debería pasar; que no muera el hilo
            backoff = BACKOFF_MAX
            _set(error=f"Algo falló al mandar las notas: {e}", offline=False)
            wait = backoff
        if _wake.wait(wait):
            _wake.clear()
            time.sleep(DEBOUNCE)
            _wake.clear()


def wake():
    _wake.set()


def start():
    """Arranca el hilo (una sola vez). Lo llama la app al iniciar el server."""
    global _thread
    storage.on_change = wake
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="memoria-sync", daemon=True)
        _thread.start()


# --- Lo que usa la pantalla de Configuración ----------------------------------------------------

def pair(code: str, url=None) -> dict:
    """Conecta esta Mac a Memoria con el código de 8 números. Devuelve status() o lanza
    ValueError con un mensaje para mostrar."""
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) != 8:
        raise ValueError("El código tiene 8 números. Lo ves en Memoria → Compus → Conectar una compu.")
    base = normalize_url(url)
    try:
        res = _request("POST", "/pair", {"code": digits}, token="", url=base)
    except ServerError as e:
        raise ValueError(str(e))
    except OSError:
        raise ValueError(f"No encontré el server en {base}. Fijate de estar en casa (en el mismo wifi) "
                         "y de que la dirección esté bien.")
    token, dev = res.get("token"), res.get("device") or {}
    if not token:
        raise ValueError("En esa dirección hay otra cosa, no un Memoria.")
    config.update({"MEMORIA_URL": base, "MEMORIA_TOKEN": token, "MEMORIA_DEVICE": dev.get("name") or "",
                   "MEMORIA_AMBITO": dev.get("ambito") or ""}, managed=True)
    _set(revoked=False, error=None, offline=False, last_ok=None)
    start()
    wake()
    return status()


def disconnect() -> dict:
    """Desconecta esta Mac: deja de mandar. Las charlas que ya están en Memoria quedan ahí."""
    if config.get("MEMORIA_TOKEN"):
        try:
            _request("DELETE", "/yo", timeout=5)  # que también desaparezca de Memoria → Compus
        except Exception:
            pass  # si no llego, igual se desconecta acá; se puede quitar desde Memoria
    config.clear(["MEMORIA_TOKEN", "MEMORIA_DEVICE", "MEMORIA_AMBITO"])
    storage.outbox_clear()
    _set(revoked=False, error=None, offline=False, last_ok=None)
    return status()


def status() -> dict:
    connected = bool(config.get("MEMORIA_TOKEN"))
    with _lock:
        st = dict(_state)
    counts = storage.outbox_counts() if connected else {"pending": 0, "rejected": 0, "rejected_reason": None}
    return {
        "connected": connected,
        "url": config.get("MEMORIA_URL") or DEFAULT_URL,
        "device": config.get("MEMORIA_DEVICE") or "",
        "ambito": config.get("MEMORIA_AMBITO") or "",
        "pending": counts["pending"],
        "rejected": counts["rejected"],
        "rejected_reason": counts["rejected_reason"],
        "last_ok": st["last_ok"],
        "offline": st["offline"],
        "revoked": st["revoked"],
        "error": st["error"],
    }


def sync_now() -> dict:
    """Botón «Mandar ahora»: vuelve a comparar con el server y vacía la cola enseguida."""
    _set(revoked=False)
    _force.set()
    start()
    wake()
    return status()
