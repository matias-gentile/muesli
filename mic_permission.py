"""Pide permiso de micrófono en macOS (TCC) mostrando el diálogo del sistema.

Por qué hace falta: una app recién creada no tiene permiso de micrófono. En macOS
reciente, hasta que lo concedés, los dispositivos de entrada se reportan con 0 canales
—así que no aparecen en la lista— y el diálogo de permiso no aparece solo a menos que
algo lo pida explícitamente. Esta función lo pide vía AVFoundation.

Es seguro llamarla en cualquier plataforma: si no es macOS o falta pyobjc, no hace nada.
"""
from __future__ import annotations


def request_microphone_access() -> None:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except Exception:
        return  # no es macOS, o falta pyobjc-framework-AVFoundation: seguimos sin romper

    try:
        # authorizationStatus: 0 = sin determinar, 1 = restringido, 2 = denegado, 3 = autorizado
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if status == 0:
            # Dispara el diálogo del sistema. El handler es asíncrono; no lo necesitamos.
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio, lambda granted: None
            )
    except Exception:
        pass


if __name__ == "__main__":
    request_microphone_access()
    print("Solicitud de permiso de micrófono enviada (si corresponde).")
