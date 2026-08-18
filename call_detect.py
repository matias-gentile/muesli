"""Detecta si alguna app está usando el micrófono (≈ estás en una llamada).

Le pregunta a CoreAudio si algún dispositivo de ENTRADA está "corriendo en algún
lado" (kAudioDevicePropertyDeviceIsRunningSomewhere). Eso cubre cualquier app que
tome el micrófono: Zoom, Teams, Slack, o Meet dentro del navegador. No hace falta
saber qué app es ni pedir permisos extra: es una consulta al subsistema de audio.

Se usa solo para AVISARTE (notificación); nunca arranca a grabar por su cuenta.
"""
from __future__ import annotations

import ctypes
import sys

_SYSTEM_OBJECT = 1
_SCOPE_GLOBAL = 0x676C6F62   # 'glob'
_SCOPE_INPUT = 0x696E7074    # 'inpt'
_PROP_DEVICES = 0x64657623   # 'dev#'  lista de dispositivos
_PROP_STREAMS = 0x73746D23   # 'stm#'  streams (para saber si tiene entrada)
_PROP_RUNNING_SOMEWHERE = 0x676F6E65  # 'gone' ¿lo está usando alguien?

_FRAMEWORK = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"


class _Addr(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32),
                ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32)]


_lib = None
_unavailable = False


def _core_audio():
    """Carga CoreAudio una sola vez. Devuelve None si no está (p. ej. fuera de macOS)."""
    global _lib, _unavailable
    if _lib is not None or _unavailable:
        return _lib
    if sys.platform != "darwin":
        _unavailable = True
        return None
    try:
        _lib = ctypes.cdll.LoadLibrary(_FRAMEWORK)
    except Exception:
        _unavailable = True
        return None
    return _lib


def _prop_size(lib, obj_id, selector, scope):
    size = ctypes.c_uint32(0)
    addr = _Addr(selector, scope, 0)
    err = lib.AudioObjectGetPropertyDataSize(
        ctypes.c_uint32(obj_id), ctypes.byref(addr),
        ctypes.c_uint32(0), None, ctypes.byref(size))
    return None if err != 0 else size.value


def _devices(lib):
    size = _prop_size(lib, _SYSTEM_OBJECT, _PROP_DEVICES, _SCOPE_GLOBAL)
    if not size:
        return []
    count = size // ctypes.sizeof(ctypes.c_uint32)
    buf = (ctypes.c_uint32 * count)()
    got = ctypes.c_uint32(size)
    addr = _Addr(_PROP_DEVICES, _SCOPE_GLOBAL, 0)
    err = lib.AudioObjectGetPropertyData(
        ctypes.c_uint32(_SYSTEM_OBJECT), ctypes.byref(addr),
        ctypes.c_uint32(0), None, ctypes.byref(got), buf)
    return [] if err != 0 else list(buf)[:got.value // ctypes.sizeof(ctypes.c_uint32)]


def _has_input(lib, dev_id) -> bool:
    return bool(_prop_size(lib, dev_id, _PROP_STREAMS, _SCOPE_INPUT))


def _is_running(lib, dev_id) -> bool:
    val = ctypes.c_uint32(0)
    got = ctypes.c_uint32(ctypes.sizeof(val))
    addr = _Addr(_PROP_RUNNING_SOMEWHERE, _SCOPE_GLOBAL, 0)
    err = lib.AudioObjectGetPropertyData(
        ctypes.c_uint32(dev_id), ctypes.byref(addr),
        ctypes.c_uint32(0), None, ctypes.byref(got), ctypes.byref(val))
    return err == 0 and val.value != 0


def mic_in_use() -> bool:
    """True si algún dispositivo de entrada está siendo usado por alguna app."""
    lib = _core_audio()
    if lib is None:
        return False
    try:
        for dev in _devices(lib):
            if _has_input(lib, dev) and _is_running(lib, dev):
                return True
    except Exception:
        return False
    return False


def available() -> bool:
    """True si podemos consultar el estado del micrófono en este sistema."""
    return _core_audio() is not None


if __name__ == "__main__":
    print("CoreAudio disponible:", available())
    print("Micrófono en uso ahora:", mic_in_use())
