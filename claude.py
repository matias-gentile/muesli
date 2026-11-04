"""Una sola forma de pedirle texto a Claude, para el resumen, el semanal y el asistente.

- Los modelos nuevos razonan antes de contestar y ese razonamiento cuenta dentro de max_tokens: por eso se le suma
  un margen al largo pedido (si no, una respuesta corta podría cortarse a la mitad o quedar vacía).
- `esfuerzo` dice cuánto razona («low» para tareas chicas, «medium» para resúmenes). Solo se manda a los modelos que
  lo aceptan (ver modelos.py), así un modelo personalizado viejo sigue andando.
- Si los filtros de seguridad de Claude rechazan el pedido (pasa raramente con algo inofensivo), la API lo reintenta
  sola en otro modelo cuando el modelo lo admite. Si igual queda rechazado, se avisa con ClaudeRechazo en vez de
  guardar un resumen vacío.
- Si la respuesta se corta por largo, le pide que siga desde donde quedó (hasta `vueltas` veces).
- Va por streaming: con razonamiento, un resumen largo puede tardar más que el tiempo de espera de un pedido
  común; así el tiempo de espera cuenta entre pedazo y pedazo, no para la respuesta entera.
"""
from __future__ import annotations

from anthropic import Anthropic

import config
import modelos
import usage

MARGEN_RAZONAMIENTO = 8000   # tokens extra para que razone sin comerse la respuesta
TOPE = 16000                 # techo por pedido (si hace falta más, sigue en otra vuelta)
REINTENTO_BETA = "server-side-fallback-2026-07-01"


class ClaudeRechazo(RuntimeError):
    """Claude no quiso responder (filtro de seguridad), incluso después del reintento en otro modelo."""


def _cliente(timeout):
    return Anthropic(api_key=config.get("ANTHROPIC_API_KEY") or None, max_retries=4, timeout=timeout)


def completar(system, messages, *, largo, tipo, esfuerzo="medium", model=None, seguir=None,
              vueltas=5, timeout=180) -> str:
    """Devuelve el texto de la respuesta. `largo`: cuántos tokens de respuesta se esperan como mucho.
    `tipo`: para el registro de gasto («resumen», «semanal», «asistente»). `seguir`: qué decirle si se corta."""
    model = model or modelos.actualizar(config.get("CLAUDE_MODEL"))
    seguir = seguir or "Seguí exactamente desde donde se cortó, sin repetir lo ya escrito."
    client = _cliente(timeout)
    msgs = list(messages)
    pedido = {"model": model, "system": system, "max_tokens": min(TOPE, largo + MARGEN_RAZONAMIENTO)}
    if modelos.acepta_esfuerzo(model):
        pedido["output_config"] = {"effort": esfuerzo}
    full = ""
    if modelos.acepta_reintento(model):
        api, extra = client.beta.messages, {"betas": [REINTENTO_BETA], "fallbacks": "default"}
    else:
        api, extra = client.messages, {}
    for _ in range(vueltas):
        with api.stream(messages=msgs, **pedido, **extra) as st:
            m = st.get_final_message()
        usage.record_response(model, m, tipo)  # si lo resolvió otro modelo, se cobra a la tarifa de ese
        if getattr(m, "stop_reason", None) == "refusal":
            raise ClaudeRechazo(_mensaje_rechazo(m))
        part = "".join(b.text for b in m.content if getattr(b, "type", None) == "text")
        full += part
        if getattr(m, "stop_reason", None) != "max_tokens" or not part:
            break  # terminó (o se fue todo en razonar y no hay de dónde seguir)
        msgs = msgs + [{"role": "assistant", "content": part}, {"role": "user", "content": seguir}]
    return full.strip()


_TEMAS = {"cyber": "seguridad informática", "bio": "biología", "frontier_llm": "desarrollo de modelos de IA"}


def _mensaje_rechazo(m) -> str:
    tema = _TEMAS.get(getattr(getattr(m, "stop_details", None), "category", None))
    porque = f" (lo tomaron como un tema de {tema})" if tema else ""
    return ("Claude no quiso procesar esta grabación: sus filtros de seguridad la frenaron" + porque + ". "
            "A veces pasa con charlas que no tienen nada de malo. "
            "Probá con otro modelo: se elige al regenerar o en ⚙ Configuración.")
