"""Resumen de la reunión con la API de Claude.

Combina la transcripción automática con tus notas manuales para producir
un resumen estructurado en Markdown, al estilo de Muesli.
"""
from anthropic import Anthropic

from config import CLAUDE_MODEL

SYSTEM_PROMPT = """Eres un asistente experto en sintetizar reuniones. \
Recibes la transcripción automática de una reunión y, opcionalmente, las notas \
manuales que tomó la persona durante la misma. Las notas manuales reflejan lo \
que a la persona le importó: dales prioridad y úsalas para orientar el énfasis.

Devuelve SIEMPRE Markdown con esta estructura, en español, omitiendo las \
secciones que no apliquen:

## Resumen ejecutivo
(2-4 frases con lo esencial)

## Puntos clave
- ...

## Decisiones
- ...

## Action items
- [ ] Tarea — responsable (si se menciona) — fecha límite (si se menciona)

## Preguntas abiertas / pendientes
- ...

Sé conciso y concreto. No inventes información que no esté en la transcripción \
ni en las notas. Si la transcripción es muy ruidosa o incompleta, indícalo \
brevemente al final."""


def summarize(transcript: str, manual_notes: str = "", meeting_title: str = "") -> str:
    client = Anthropic()  # lee ANTHROPIC_API_KEY del entorno

    user_content = ""
    if meeting_title:
        user_content += f"Título de la reunión: {meeting_title}\n\n"
    user_content += "=== NOTAS MANUALES ===\n"
    user_content += (manual_notes.strip() or "(la persona no tomó notas manuales)") + "\n\n"
    user_content += "=== TRANSCRIPCIÓN AUTOMÁTICA ===\n"
    user_content += transcript.strip() or "(transcripción vacía)"

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    # La respuesta es una lista de bloques; concatenamos el texto.
    return "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    ).strip()


if __name__ == "__main__":
    demo = "Hablamos del lanzamiento. Juan se encarga del copy para el viernes. " \
           "Decidimos posponer la campaña de ads hasta tener métricas."
    print(summarize(demo, manual_notes="lanzamiento - ads?", meeting_title="Sync marketing"))
