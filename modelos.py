"""Los modelos de Claude que ofrece Muesli: un solo lugar con sus nombres, precios y qué admite cada uno.

Lo usan Configuración (el desplegable), el panel de «Regenerar», la validación de app.py, el cálculo del gasto
(usage.py) y claude.py (cómo se llama a cada modelo). Para sumar o actualizar un modelo, se cambia solo acá.
"""
from __future__ import annotations

import re

# Los que se eligen en Configuración, del más barato al más capaz.
MODELOS = [
    {"id": "claude-haiku-5-5", "nombre": "Haiku 5.5", "corto": "Haiku",
     "pista": "el más barato y rápido", "breve": "más barato y rápido", "precio": "$0,10 / $0,50"},
    {"id": "claude-sonnet-5-5", "nombre": "Sonnet 5.5", "corto": "Sonnet",
     "pista": "equilibrado (recomendado)", "breve": "equilibrado", "precio": "$2 / $10"},
    {"id": "claude-opus-5-5", "nombre": "Opus 5.5", "corto": "Opus",
     "pista": "el más capaz", "breve": "el más capaz", "precio": "$4 / $20"},
]
POR_DEFECTO = "claude-sonnet-5-5"
IDS = [m["id"] for m in MODELOS]

# Lo que se podía elegir antes en Configuración → el mismo nivel, generación nueva. Así quien tenía «Sonnet»
# sigue en Sonnet sin tocar nada.
ANTERIORES = {
    "claude-haiku-4-5": "claude-haiku-5-5",
    "claude-haiku-4-5-20251001": "claude-haiku-5-5",
    "claude-sonnet-4-6": "claude-sonnet-5-5",
    "claude-sonnet-4-5-20250929": "claude-sonnet-5-5",
    "claude-opus-4-8": "claude-opus-5-5",
}

# Precio por millón de tokens (USD): (entrada, salida). Tarifas de la API de Anthropic, octubre 2026.
# Se guardan también los modelos viejos para que el gasto ya registrado se siga calculando bien.
PRECIOS = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Haiku 5.5 cobra más cuando el pedido supera los 100.000 tokens de entrada.
PRECIOS_PEDIDO_LARGO = {"claude-haiku-5-5": (100_000, (0.50, 2.50))}

# Modelos que razonan siempre (o por defecto) y aceptan elegir cuánto: output_config.effort.
CON_ESFUERZO = {"claude-fable-5-1", "claude-fable-5", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8",
                "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6",
                "claude-haiku-5-5"}
# Modelos cuyos filtros de seguridad pueden rechazar un pedido y que aceptan que la API lo reintente sola en otro
# modelo («fallbacks»: "default"). Haiku 5.5 puede rechazar pero no tiene ese reintento.
CON_REINTENTO = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


def normalizar(model_id):
    """Quita el sufijo de fecha (claude-haiku-4-5-20251001 → claude-haiku-4-5) y espacios."""
    return re.sub(r"-\d{8}$", "", (model_id or "").strip())


def actualizar(model_id):
    """El modelo guardado en Configuración, pasado a la generación actual si era uno de los de antes."""
    return ANTERIORES.get((model_id or "").strip(), (model_id or "").strip()) or POR_DEFECTO


def precio(model_id, input_tokens=0):
    """(entrada, salida) por millón de tokens, o None si no se conoce el modelo."""
    m = normalizar(model_id)
    largo = PRECIOS_PEDIDO_LARGO.get(m)
    if largo and input_tokens > largo[0]:
        return largo[1]
    return PRECIOS.get(m)


def acepta_esfuerzo(model_id) -> bool:
    return normalizar(model_id) in CON_ESFUERZO


def acepta_reintento(model_id) -> bool:
    return normalizar(model_id) in CON_REINTENTO
