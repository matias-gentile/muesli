"""Asistente sobre una nota: preguntar (chat), email de seguimiento y pendientes.

Todo corre con tu propia API key de Claude (config.get("ANTHROPIC_API_KEY")) y se apoya
SOLO en el material de la nota (transcripción + resumen + notas manuales). No inventa datos.
"""
from __future__ import annotations

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
