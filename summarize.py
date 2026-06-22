"""Resumen de la grabación con la API de Claude.

Combina la transcripción automática con tus notas manuales y el TIPO de
grabación (reunión, clase, entrevista, etc.) para producir un resumen
estructurado en Markdown, adaptado al contexto. Es el equivalente a las
"plantillas" de apps como Muesli.
"""
from anthropic import Anthropic

from config import CLAUDE_MODEL

BASE_SYSTEM = """Eres un asistente experto en sintetizar lo que ocurre en una \
grabación de audio transcrita automáticamente. Recibes:
- el TIPO de grabación y, opcionalmente, contexto extra que da la persona,
- las NOTAS MANUALES que tomó la persona (reflejan lo que le importó),
- la TRANSCRIPCIÓN automática (puede tener errores o ruido).

Reglas:
- Responde SIEMPRE en español y en Markdown, usando exactamente las secciones \
de la plantilla indicada. Omite las secciones que queden vacías.
- Da prioridad a las notas manuales para decidir el énfasis.
- Sé concreto y conciso. No inventes información que no esté en la transcripción \
ni en las notas.
- Si la transcripción es muy ruidosa o incompleta, indícalo en una línea al final."""

# Cada plantilla define la estructura de secciones para ese tipo de grabación.
TEMPLATES = {
    "reunion": {
        "label": "Reunión",
        "structure": """## Resumen ejecutivo
(2-4 frases con lo esencial)

## Puntos clave
- ...

## Decisiones
- ...

## Action items
- [ ] Tarea — responsable (si se menciona) — fecha límite (si se menciona)

## Preguntas abiertas / pendientes
- ...""",
    },
    "clase": {
        "label": "Clase / charla",
        "structure": """## Resumen
(qué se enseñó, en 2-4 frases)

## Conceptos clave
- **Término** — explicación breve

## Ejemplos y casos
- ...

## Para estudiar / repasar
- ...

## Dudas o preguntas que surgieron
- ...""",
    },
    "entrevista": {
        "label": "Entrevista",
        "structure": """## Resumen
(perfil e impresión general, 2-4 frases)

## Puntos fuertes
- ...

## Áreas de preocupación / a profundizar
- ...

## Respuestas destacadas
- ...

## Recomendación / próximos pasos
- ...""",
    },
    "video": {
        "label": "Video / podcast",
        "structure": """## Resumen
(de qué trata, 2-4 frases)

## Ideas principales
- ...

## Conclusiones / takeaways
- ...

## Citas o momentos destacados
- ...

## Recursos / referencias mencionadas
- ...""",
    },
    "uno_a_uno": {
        "label": "1:1 / feedback",
        "structure": """## Resumen
(2-4 frases)

## Temas tratados
- ...

## Feedback (dado y recibido)
- ...

## Compromisos / follow-ups
- [ ] ...

## Notas personales / a recordar
- ...""",
    },
    "brainstorm": {
        "label": "Brainstorming",
        "structure": """## Resumen
(objetivo de la sesión, 2-4 frases)

## Ideas generadas
- ...

## Temas y patrones
- ...

## Decisiones provisionales
- ...

## Próximos pasos
- ...""",
    },
    "general": {
        "label": "General / otro",
        "structure": """## Resumen
- ...

## Puntos clave
- ...

## Pendientes / próximos pasos
- ...""",
    },
}

DEFAULT_TYPE = "reunion"


def list_templates():
    """Para el frontend: [{'value': 'reunion', 'label': 'Reunión'}, ...]."""
    return [{"value": k, "label": v["label"]} for k, v in TEMPLATES.items()]


def type_label(context_type):
    """Devuelve la etiqueta legible de un tipo (p. ej. 'reunion' -> 'Reunión')."""
    return TEMPLATES.get(context_type, TEMPLATES[DEFAULT_TYPE])["label"]


def summarize(transcript, manual_notes="", title="", context_type=DEFAULT_TYPE, context=""):
    template = TEMPLATES.get(context_type, TEMPLATES[DEFAULT_TYPE])
    system = (
        BASE_SYSTEM
        + f"\n\n=== PLANTILLA A USAR (tipo: {template['label']}) ===\n"
        + template["structure"]
    )

    parts = [f"TIPO DE GRABACIÓN: {template['label']}"]
    if title:
        parts.append(f"TÍTULO: {title}")
    if context:
        parts.append(f"CONTEXTO ADICIONAL: {context}")
    parts.append("\n=== NOTAS MANUALES ===\n" + (manual_notes.strip() or "(sin notas manuales)"))
    parts.append("\n=== TRANSCRIPCIÓN AUTOMÁTICA ===\n" + (transcript.strip() or "(transcripción vacía)"))
    user_content = "\n".join(parts)

    client = Anthropic()  # lee ANTHROPIC_API_KEY del entorno
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(
        b.text for b in message.content if getattr(b, "type", None) == "text"
    ).strip()


if __name__ == "__main__":
    demo = ("Hablamos del lanzamiento. Juan se encarga del copy para el viernes. "
            "Decidimos posponer la campaña de ads hasta tener métricas.")
    print(summarize(demo, manual_notes="lanzamiento - ads?",
                    title="Sync marketing", context_type="reunion",
                    context="Equipo de growth, sprint 14"))
