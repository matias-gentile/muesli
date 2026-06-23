"""Listar y cambiar el dispositivo de SALIDA por defecto del sistema (macOS).

Usa CoreAudio vía ctypes, sin dependencias extra. Detecta además qué salidas son
agregadas/multi-salida que incluyen BlackHole (las que mantienen viva la captura de
Muesli), para marcarlas.

Es seguro importar en cualquier plataforma: si CoreAudio no está disponible (p. ej.
fuera de macOS), todas las funciones devuelven valores vacíos sin romper.
"""
from __future__ import annotations

import ctypes
import ctypes.util


def _fourcc(s: str) -> int:
    return (ord(s[0]) << 24) | (ord(s[1]) << 16) | (ord(s[2]) << 8) | ord(s[3])


# --- Constantes de CoreAudio ---
kAudioObjectSystemObject = 1
kAudioHardwarePropertyDevices = _fourcc("dev#")
kAudioHardwarePropertyDefaultOutputDevice = _fourcc("dOut")
kAudioObjectPropertyName = _fourcc("lnam")
kAudioObjectPropertyScopeGlobal = _fourcc("glob")
kAudioObjectPropertyScopeOutput = _fourcc("outp")
kAudioObjectPropertyElementMain = 0
kAudioDevicePropertyStreamConfiguration = _fourcc("slay")
kAudioAggregateDevicePropertyFullSubDeviceList = _fourcc("grup")
kCFStringEncodingUTF8 = 0x08000100


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_AVAILABLE = False
_ca = None
_cf = None

try:
    _ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
    _cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))

    _ca.AudioObjectGetPropertyDataSize.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(AudioObjectPropertyAddress),
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    _ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32

    _ca.AudioObjectGetPropertyData.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(AudioObjectPropertyAddress),
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    _ca.AudioObjectGetPropertyData.restype = ctypes.c_int32

    _ca.AudioObjectSetPropertyData.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(AudioObjectPropertyAddress),
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    _ca.AudioObjectSetPropertyData.restype = ctypes.c_int32

    _cf.CFStringGetCStringPtr.restype = ctypes.c_char_p
    _cf.CFStringGetCStringPtr.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _cf.CFStringGetCString.restype = ctypes.c_bool
    _cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    _cf.CFRelease.argtypes = [ctypes.c_void_p]
    _cf.CFArrayGetCount.restype = ctypes.c_long
    _cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    _cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    _cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


def _addr(selector, scope=kAudioObjectPropertyScopeGlobal):
    return AudioObjectPropertyAddress(selector, scope, kAudioObjectPropertyElementMain)


def _cfstring_to_str(cfstr) -> str:
    if not cfstr:
        return ""
    ptr = _cf.CFStringGetCStringPtr(cfstr, kCFStringEncodingUTF8)
    if ptr:
        return ptr.decode("utf-8", "replace")
    buf = ctypes.create_string_buffer(1024)
    if _cf.CFStringGetCString(cfstr, buf, 1024, kCFStringEncodingUTF8):
        return buf.value.decode("utf-8", "replace")
    return ""


def _all_device_ids() -> list:
    addr = _addr(kAudioHardwarePropertyDevices)
    size = ctypes.c_uint32(0)
    if _ca.AudioObjectGetPropertyDataSize(kAudioObjectSystemObject, ctypes.byref(addr),
                                          0, None, ctypes.byref(size)) != 0:
        return []
    n = size.value // ctypes.sizeof(ctypes.c_uint32)
    arr = (ctypes.c_uint32 * n)()
    if _ca.AudioObjectGetPropertyData(kAudioObjectSystemObject, ctypes.byref(addr),
                                      0, None, ctypes.byref(size), arr) != 0:
        return []
    return list(arr)


def _device_name(dev_id: int) -> str:
    addr = _addr(kAudioObjectPropertyName)
    cfstr = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
    if _ca.AudioObjectGetPropertyData(dev_id, ctypes.byref(addr), 0, None,
                                      ctypes.byref(size), ctypes.byref(cfstr)) != 0:
        return ""
    name = _cfstring_to_str(cfstr)
    if cfstr:
        _cf.CFRelease(cfstr)
    return name


def _is_output(dev_id: int) -> bool:
    addr = _addr(kAudioDevicePropertyStreamConfiguration, kAudioObjectPropertyScopeOutput)
    size = ctypes.c_uint32(0)
    if _ca.AudioObjectGetPropertyDataSize(dev_id, ctypes.byref(addr), 0, None,
                                          ctypes.byref(size)) != 0 or size.value == 0:
        return False
    buf = (ctypes.c_byte * size.value)()
    if _ca.AudioObjectGetPropertyData(dev_id, ctypes.byref(addr), 0, None,
                                      ctypes.byref(size), buf) != 0:
        return False
    num_buffers = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[0]
    return num_buffers > 0


def _subdevice_uids(dev_id: int) -> list:
    """UIDs de los sub-dispositivos de un agregado/multi-salida (vacío si no aplica)."""
    addr = _addr(kAudioAggregateDevicePropertyFullSubDeviceList)
    size = ctypes.c_uint32(0)
    if _ca.AudioObjectGetPropertyDataSize(dev_id, ctypes.byref(addr), 0, None,
                                          ctypes.byref(size)) != 0 or size.value == 0:
        return []
    cfarr = ctypes.c_void_p()
    if _ca.AudioObjectGetPropertyData(dev_id, ctypes.byref(addr), 0, None,
                                      ctypes.byref(size), ctypes.byref(cfarr)) != 0 or not cfarr:
        return []
    uids = []
    try:
        count = _cf.CFArrayGetCount(cfarr)
        for i in range(count):
            uids.append(_cfstring_to_str(_cf.CFArrayGetValueAtIndex(cfarr, i)))
    finally:
        _cf.CFRelease(cfarr)
    return uids


def _keeps_capture(dev_id: int) -> bool:
    """True si es agregado/multi-salida e incluye BlackHole (mantiene la captura)."""
    try:
        return any("blackhole" in (u or "").lower() for u in _subdevice_uids(dev_id))
    except Exception:
        return False


def get_default_output_id() -> int:
    if not _AVAILABLE:
        return 0
    addr = _addr(kAudioHardwarePropertyDefaultOutputDevice)
    dev = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_uint32))
    if _ca.AudioObjectGetPropertyData(kAudioObjectSystemObject, ctypes.byref(addr),
                                      0, None, ctypes.byref(size), ctypes.byref(dev)) != 0:
        return 0
    return dev.value


def list_outputs() -> list:
    """Lista de salidas: [{'name', 'is_default', 'keeps_capture'}], sin duplicar nombres."""
    if not _AVAILABLE:
        return []
    default_id = get_default_output_id()
    out = []
    seen = set()
    for d in _all_device_ids():
        try:
            if not _is_output(d):
                continue
            name = _device_name(d)
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({
                "name": name,
                "is_default": d == default_id,
                "keeps_capture": _keeps_capture(d),
            })
        except Exception:
            continue
    return out


def get_default_output_name() -> str:
    if not _AVAILABLE:
        return ""
    did = get_default_output_id()
    try:
        return _device_name(did) if did else ""
    except Exception:
        return ""


def set_default_output(name: str) -> bool:
    """Pone como salida por defecto el dispositivo cuyo nombre coincide (exacto, luego
    por substring). Devuelve True si lo logró."""
    if not _AVAILABLE or not name:
        return False

    def _try(match):
        for d in _all_device_ids():
            try:
                if _is_output(d) and match(_device_name(d)):
                    addr = _addr(kAudioHardwarePropertyDefaultOutputDevice)
                    dev = ctypes.c_uint32(d)
                    ok = _ca.AudioObjectSetPropertyData(
                        kAudioObjectSystemObject, ctypes.byref(addr), 0, None,
                        ctypes.sizeof(ctypes.c_uint32), ctypes.byref(dev)) == 0
                    if ok:
                        return True
            except Exception:
                continue
        return False

    if _try(lambda n: n == name):
        return True
    return _try(lambda n: name.lower() in (n or "").lower())


if __name__ == "__main__":
    if not _AVAILABLE:
        print("CoreAudio no disponible en esta plataforma.")
    else:
        print("Salida actual:", get_default_output_name())
        for o in list_outputs():
            mark = " [captura ✓]" if o["keeps_capture"] else ""
            star = " *" if o["is_default"] else ""
            print(f" - {o['name']}{mark}{star}")
