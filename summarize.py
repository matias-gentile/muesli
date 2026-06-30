"""Resumen de la grabación con la API de Claude.

Combina la transcripción automática con tus notas manuales y el TIPO de
grabación (reunión, clase, entrevista, etc.) para producir un resumen
estructurado en Markdown, adaptado al contexto. Es el equivalente a las
"plantillas" de apps como Muesli.
"""
from anthropic import Anthropic

import datetime as _dt

import config
import usage

BASE_SYSTEM = """Eres un asistente experto en sintetizar lo que ocurre en una \
grabación de audio transcrita automáticamente. Recibes:
- el TIPO de grabación y, opcionalmente, contexto extra que da la persona,
- las NOTAS MANUALES que tomó la persona (reflejan lo que le importó),
- la TRANSCRIPCIÓN automática (puede tener errores o ruido).

Reglas:
- Responde SIEMPRE en español y en Markdown, usando exactamente las secciones \
de la plantilla indicada. Omite las secciones que queden vacías.
- Da prioridad a las notas manuales para decidir el énfasis.
- Priorizá CAPTURAR FIELMENTE lo que se habló por encima de la brevedad. La \
extensión del resumen debe ser proporcional a la reunión: si fue larga y con \
mucho contenido, sé detallado y cubrí todos los temas a fondo; si fue corta, sé \
breve. No omitas temas, decisiones ni detalles importantes.
- No inventes información que no esté en la transcripción ni en las notas.
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


def summarize(transcript, manual_notes="", title="", context_type=DEFAULT_TYPE, context="",
              detail="normal", model=None):
    template = TEMPLATES.get(context_type, TEMPLATES[DEFAULT_TYPE])

    words = len(transcript.split())
    # Presupuesto de salida proporcional a la longitud: cuanto más larga la
    # reunión, más detallado puede ser el resumen (sin un tope fijo que lo recorte).
    max_tokens = min(8000, max(1500, int(words * 0.35)))
    if detail == "corto":
        max_tokens = min(max_tokens, 1200)
    elif detail == "extenso":
        max_tokens = min(8000, max(4000, int(words * 0.6)))

    system = (
        BASE_SYSTEM
        + f"\n\n=== PLANTILLA A USAR (tipo: {template['label']}) ===\n"
        + template["structure"]
    )
    if detail == "corto":
        system += (
            "\n\n=== NIVEL DE DETALLE: BREVE ===\n"
            "Hacé un resumen CONCISO: solo lo esencial, las decisiones y los pendientes "
            "principales, en la menor cantidad de texto posible. Evitá el detalle fino."
        )
    elif detail == "extenso":
        system += (
            "\n\n=== NIVEL DE DETALLE: EXTENSO ===\n"
            "Hacé un resumen MUY DETALLADO y exhaustivo, aprovechando todo el contexto. En "
            "'Puntos clave' recorré los temas uno por uno con la sustancia de cada discusión "
            "(qué se planteó, qué posturas hubo, los datos y números mencionados, en qué se "
            "quedó), no solo títulos. Incluí matices y ejemplos concretos. Es preferible un "
            "resumen largo y completo a uno breve que se pierda cosas."
        )
    elif words > 3500:  # 'normal' pero reunión larga (~25+ min): pedir exhaustividad igual
        system += (
            f"\n\n=== REUNIÓN LARGA (~{words} palabras) ===\n"
            "Hacé un resumen DETALLADO y exhaustivo. En 'Puntos clave' recorré los temas "
            "tratados uno por uno, con la sustancia de cada discusión (qué se planteó, qué "
            "posturas hubo, en qué se quedó), no solo títulos. Es preferible un resumen "
            "largo y completo a uno breve que se pierda cosas."
        )

    parts = [f"TIPO DE GRABACIÓN: {template['label']}"]
    if title:
        parts.append(f"TÍTULO: {title}")
    if context:
        parts.append(f"CONTEXTO ADICIONAL: {context}")
    parts.append("\n=== NOTAS MANUALES ===\n" + (manual_notes.strip() or "(sin notas manuales)"))
    parts.append("\n=== TRANSCRIPCIÓN AUTOMÁTICA ===\n" + (transcript.strip() or "(transcripción vacía)"))
    user_content = "\n".join(parts)

    client = Anthropic(api_key=config.get("ANTHROPIC_API_KEY") or None,
                       max_retries=4, timeout=180)  # reintenta cortes de red transitorios
    messages = [{"role": "user", "content": user_content}]
    model = model or config.get("CLAUDE_MODEL")  # permite override por llamada
    full = ""
    for _ in range(5):  # si la respuesta se corta por longitud, la continúa
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        usage.record_response(model, message, "resumen")
        part = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        full += part
        if getattr(message, "stop_reason", None) != "max_tokens":
            break  # terminó normalmente
        # se cortó por el tope: pedile que siga desde donde quedó
        messages.append({"role": "assistant", "content": part})
        messages.append({"role": "user",
                         "content": "Seguí el resumen exactamente desde donde se cortó, sin "
                                    "repetir lo ya escrito ni reabrir secciones ya cerradas."})
    return full.strip()


_WEEKLY_SYSTEM = """Sos un asistente que sintetiza la semana de trabajo de una persona \
a partir de los resúmenes de sus reuniones. Te paso varios resúmenes (ya condensados) de \
las reuniones de los últimos 7 días, en orden cronológico. Producí UN resumen semanal en \
español, claro y accionable, en Markdown, con esta estructura exacta:

## Panorama de la semana
Un párrafo breve (TL;DR): qué pasó en general, el hilo conductor de la semana.

## Temas recurrentes
Los temas que aparecieron en más de una reunión o que dominaron la semana, agrupados. Si \
algo se mencionó en varias reuniones, decilo explícitamente.

## Decisiones
Las decisiones concretas que se tomaron durante la semana (un bullet por decisión).

## Pendientes consolidados
Todos los próximos pasos y tareas pendientes que surgieron, juntados en una sola lista. \
Para cada uno indicá entre paréntesis de qué reunión salió, y el responsable si se sabe.

## Reunión por reunión
Una línea por reunión: el título y, en una frase, lo más importante de esa reunión.

Reglas:
- Basate SOLO en los resúmenes que te paso; no inventes nada que no esté.
- Si una sección no aplica (p. ej. no hubo decisiones), poné "—".
- Sé conciso pero no omitas lo importante: es un digest para retomar la semana de un vistazo."""


def weekly_digest(notes, detail="normal", model=None):
    """Resumen semanal por map-reduce desde los resúmenes ya guardados de cada nota.
    `notes`: lista de dicts con title, created_at, ctype, summary (orden cronológico asc)."""
    blocks, total, cap = [], 0, 60000
    for n in notes:
        try:
            fecha = _dt.datetime.fromisoformat(n.get("created_at", "")).strftime("%d/%m")
        except Exception:
            fecha = (n.get("created_at") or "")[:10]
        label = type_label(n.get("ctype") or DEFAULT_TYPE)
        summary = (n.get("summary") or "").strip() or "(sin resumen)"
        block = f"### {fecha} · {n.get('title') or 'Sin título'} ({label})\n{summary}"
        if total + len(block) > cap:
            blocks.append("… (se omitieron reuniones por longitud) …")
            break
        blocks.append(block)
        total += len(block)
    user_content = (f"Estos son los resúmenes de las reuniones de los últimos 7 días "
                    f"({len(notes)} en total), en orden cronológico:\n\n" + "\n\n".join(blocks))

    # El semanal es síntesis: el detalle ajusta cuánto desarrolla cada sección.
    system, max_tokens = _WEEKLY_SYSTEM, 2000
    if detail == "corto":
        max_tokens = 1000
        system += "\n\nNIVEL DE DETALLE: BREVE. Hacé el digest lo más conciso posible."
    elif detail == "extenso":
        max_tokens = 4000
        system += ("\n\nNIVEL DE DETALLE: EXTENSO. Desarrollá cada sección con más profundidad "
                   "y matices, sin perder la estructura.")

    client = Anthropic(api_key=config.get("ANTHROPIC_API_KEY") or None,
                       max_retries=4, timeout=180)
    messages = [{"role": "user", "content": user_content}]
    model = model or config.get("CLAUDE_MODEL")
    full = ""
    for _ in range(5):  # continúa si se corta por longitud
        message = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages)
        usage.record_response(model, message, "semanal")
        part = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        full += part
        if getattr(message, "stop_reason", None) != "max_tokens":
            break
        messages.append({"role": "assistant", "content": part})
        messages.append({"role": "user",
                         "content": "Seguí exactamente desde donde se cortó, sin repetir lo ya escrito."})
    return full.strip()


if __name__ == "__main__":
    demo = ("Hablamos del lanzamiento. Juan se encarga del copy para el viernes. "
            "Decidimos posponer la campaña de ads hasta tener métricas.")
    print(summarize(demo, manual_notes="lanzamiento - ads?",
                    title="Sync marketing", context_type="reunion",
                    context="Equipo de growth, sprint 14"))
