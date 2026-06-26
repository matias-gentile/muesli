"""Asistente sobre una nota: preguntar (chat), email de seguimiento y pendientes.

Todo corre con tu propia API key de Claude (config.get("ANTHROPIC_API_KEY")) y se apoya
SOLO en el material de la nota (transcripción + resumen + notas manuales). No inventa datos.
"""
from __future__ import annotations

import re

import config
from anthropic import Anthropic

# Tope de caracteres del material que mandamos como contexto (evita prompts gigantes en
# reuniones muy largas). ~48k chars ≈ bastante contexto sin pasarnos.
_MAX_CONTEXT_CHARS = 48000


def _client() -> Anthropic:
    return Anthropic(api_key=config.get("ANTHROPIC_API_KEY") or None,
                     max_retries=4, timeout=120)


def _note_context(note: dict) -> str:
    """Arma el material de la reunión para pasarle a Claude."""
    parts = []
    if (note.get("title") or "").strip():
        parts.append(f"TÍTULO: {note['title'].strip()}")
    if (note.get("manual_notes") or "").strip():
        parts.append("NOTAS MANUALES DEL USUARIO:\n" + note["manual_notes"].strip())
    if (note.get("summary") or "").strip():
        parts.append("RESUMEN:\n" + note["summary"].strip())
    transcript = (note.get("transcript") or "").strip()
    parts.append("TRANSCRIPCIÓN:\n" + (transcript or "(transcripción vacía)"))
    ctx = "\n\n".join(parts)
    if len(ctx) > _MAX_CONTEXT_CHARS:
        ctx = ctx[:_MAX_CONTEXT_CHARS] + "\n\n[...material recortado por longitud...]"
    return ctx


def _complete(system: str, messages: list, max_tokens: int = 1200) -> str:
    """Llama a Claude con continuación si la respuesta se corta por longitud."""
    client = _client()
    full = ""
    msgs = list(messages)
    for _ in range(4):
        m = client.messages.create(
            model=config.get("CLAUDE_MODEL"),
            max_tokens=max_tokens,
            system=system,
            messages=msgs,
        )
        part = "".join(b.text for b in m.content if getattr(b, "type", None) == "text")
        full += part
        if getattr(m, "stop_reason", None) != "max_tokens":
            break
        msgs = msgs + [
            {"role": "assistant", "content": part},
            {"role": "user", "content": "Seguí exactamente desde donde cortaste, sin repetir."},
        ]
    return full.strip()


def ask(note: dict, question: str, history: list | None = None) -> str:
    """Responde una pregunta sobre la nota, con historial de chat opcional."""
    system = (
        "Sos un asistente que responde preguntas sobre una reunión grabada, basándote ÚNICAMENTE "
        "en el material que se te da (transcripción, resumen y notas). Si algo no está en el "
        "material, decílo claramente en vez de inventar. Respondé en español, conciso y al grano. "
        "Cuando ayude, citá brevemente lo que se dijo."
    )
    messages = [
        {"role": "user", "content": "=== MATERIAL DE LA REUNIÓN ===\n" + _note_context(note)},
        {"role": "assistant", "content": "Tengo el material de la reunión. ¿Qué querés saber?"},
    ]
    for h in (history or [])[-8:]:  # últimas vueltas, para no inflar el prompt
        role = "user" if h.get("role") == "user" else "assistant"
        content = (h.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question.strip()})
    return _complete(system, messages, max_tokens=1200)


def followup_email(note: dict) -> str:
    """Redacta un email de seguimiento listo para enviar."""
    system = (
        "Redactá un email de seguimiento (follow-up) de la reunión, en español, listo para enviar. "
        "Tono profesional y cordial. Estructura: saludo, una o dos frases de contexto, los puntos y "
        "decisiones clave en viñetas, los próximos pasos con responsables y fechas si se mencionan, "
        "y un cierre breve. La PRIMERA línea debe ser 'Asunto: ...' y luego el cuerpo. Devolvé SOLO "
        "el email, sin comentarios tuyos. No inventes datos que no estén en el material."
    )
    return _complete(system, [{"role": "user", "content": _note_context(note)}], max_tokens=1200)


def action_items(note: dict) -> str:
    """Extrae los pendientes/action items en una lista Markdown con checkboxes."""
    system = (
        "Extraé los action items / pendientes de la reunión, en español. Devolvé SOLO una lista en "
        "Markdown, una línea por pendiente, con responsable y fecha si se mencionan, en el formato: "
        "'- [ ] <tarea> — <responsable> (<fecha si hay>)'. Si no hay pendientes claros, devolvé "
        "exactamente: 'No se identificaron pendientes concretos.'. No inventes nada que no esté en "
        "el material."
    )
    return _complete(system, [{"role": "user", "content": _note_context(note)}], max_tokens=800)


def enhance_notes(note: dict) -> str:
    """Realza las notas manuales del usuario: mantiene sus palabras y completa con lo dicho.

    Lo que AGREGA la IA va envuelto en {{...}} para poder pintarlo distinto en el front.
    """
    manual = (note.get("manual_notes") or "").strip()
    transcript = (note.get("transcript") or "").strip()
    system = (
        "Te paso las NOTAS que tomó una persona durante una reunión (sueltas, abreviadas) y la "
        "TRANSCRIPCIÓN de lo que se dijo. Devolvé las notas REALZADAS siguiendo estas reglas estrictas:\n"
        "1. Mantené las palabras y el orden de las notas del usuario TAL CUAL (no las reescribas).\n"
        "2. Completá cada punto con el detalle real de la transcripción (datos, números, quién dijo "
        "qué, contexto). TODO lo que agregues vos, envolvelo entre dobles llaves: {{texto agregado}}.\n"
        "3. Si algo importante apareció en la reunión y el usuario no lo anotó, agregalo como una "
        "línea nueva COMPLETAMENTE entre llaves: {{- nuevo punto}}.\n"
        "4. No inventes nada que no esté en la transcripción. Si un punto del usuario no se tocó en "
        "la reunión, dejalo sin agregado.\n"
        "5. Respondé en español, conservando el formato de lista. Devolvé SOLO las notas realzadas, "
        "sin encabezados ni comentarios tuyos."
    )
    content = f"=== NOTAS DEL USUARIO ===\n{manual or '(sin notas)'}\n\n=== TRANSCRIPCIÓN ===\n{transcript or '(vacía)'}"
    return _complete(system, [{"role": "user", "content": content}], max_tokens=1600)


def dialogue(note: dict) -> str:
    """Reformatea la transcripción como diálogo, infiriendo los cambios de orador del texto.

    No es diarización real (no usa el audio): Claude deduce los turnos por el contenido.
    Etiqueta 'Orador 1', 'Orador 2', etc., sin cambiar las palabras.
    """
    transcript = (note.get("transcript") or "").strip()
    system = (
        "Te paso la TRANSCRIPCIÓN corrida de una conversación, sin marcas de quién habla. "
        "Reformateala como un DIÁLOGO infiriendo los cambios de orador por el contenido "
        "(preguntas y respuestas, cambios de tema, tono). Reglas estrictas:\n"
        "1. NO cambies las palabras: solo separá en turnos y agregá la etiqueta de orador.\n"
        "2. Etiquetá a los participantes como 'Orador 1', 'Orador 2', etc. Si por el contexto "
        "queda clarísimo un nombre propio, podés usarlo; si no, dejá 'Orador N'.\n"
        "3. Cada turno en su propio párrafo, con la etiqueta en negrita, así: "
        "'**Orador 1:** ...'. Separá los turnos con una línea en blanco.\n"
        "4. Es una inferencia, no una certeza: ante la duda, mantené el mismo orador.\n"
        "5. Respondé en el idioma de la transcripción. Devolvé SOLO el diálogo, sin comentarios."
    )
    return _complete(system, [{"role": "user", "content": transcript or "(vacía)"}], max_tokens=2200)


def _fmt_ts(sec) -> str:
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def key_moments(note: dict) -> list:
    """Detecta momentos clave y los ancla a un timestamp (usando los segmentos)."""
    segs = note.get("segments") or []
    if not segs:
        return []
    lines, total = [], 0
    for s in segs:
        line = f"[{_fmt_ts(s.get('start', 0))}] {s.get('text', '')}"
        total += len(line) + 1
        if total > _MAX_CONTEXT_CHARS:
            break
        lines.append(line)
    system = (
        "Te paso la transcripción de una reunión con marcas de tiempo [MM:SS]. Identificá los "
        "MOMENTOS CLAVE (decisiones, compromisos, datos importantes, puntos de giro). Devolvé SOLO "
        "una lista, UNA por línea, en el formato exacto 'MM:SS — etiqueta corta' (en español, "
        "máximo ~8 palabras). Usá la marca de tiempo del momento en que ocurre. Entre 3 y 8 "
        "momentos. No inventes nada que no esté en la transcripción."
    )
    raw = _complete(system, [{"role": "user", "content": "\n".join(lines)}], max_tokens=600)
    moments = []
    for line in raw.splitlines():
        m = re.match(r"\s*(?:[-*]\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*[—\-–:]\s*(.+)", line)
        if not m:
            continue
        if m.group(3):
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        else:
            t = int(m.group(1)) * 60 + int(m.group(2))
        label = m.group(4).strip().strip('"').strip()
        if label:
            moments.append({"t": t, "label": label})
    return moments
