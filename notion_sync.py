"""Sincronización opcional con Notion.

Si NOTION_API_KEY y NOTION_DATABASE_ID están definidos en el entorno, crea una
página por grabación en la base de datos indicada, con el resumen formateado.
Si no están definidos, no hace nada (la app sigue guardando los .md locales).

Setup (ver README):
1. Crear una integración en https://www.notion.so/my-integrations y copiar el token.
2. Crear una base de datos en Notion (con una propiedad de título; opcionalmente
   'Tipo' tipo select y 'Fecha' tipo date).
3. Compartir esa base con la integración (••• -> Conexiones).
4. Poner NOTION_API_KEY y NOTION_DATABASE_ID en .env.
"""
from __future__ import annotations

import re

from config import NOTION_API_KEY, NOTION_DATABASE_ID


def is_enabled() -> bool:
    return bool(NOTION_API_KEY and NOTION_DATABASE_ID)


def _rich_text(text: str):
    """Convierte una línea con **negrita** en rich_text de Notion."""
    parts = []
    # re.split con grupo de captura: los índices impares son el texto en negrita.
    for i, seg in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if seg == "":
            continue
        parts.append({
            "type": "text",
            "text": {"content": seg[:2000]},
            "annotations": {"bold": i % 2 == 1},
        })
    return parts or [{"type": "text", "text": {"content": ""}}]


def _md_to_blocks(md: str):
    """Markdown simple (##, -, - [ ], **negrita**, párrafos) -> bloques de Notion."""
    blocks = []
    for raw in md.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": _rich_text(line[3:])}})
        elif line.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                           "heading_1": {"rich_text": _rich_text(line[2:])}})
        elif line[:6] in ("- [ ] ", "- [x] "):
            blocks.append({"object": "block", "type": "to_do",
                           "to_do": {"rich_text": _rich_text(line[6:]),
                                     "checked": line[3] == "x"}})
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _rich_text(line[2:])}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": _rich_text(line)}})
    return blocks


def sync(title: str, summary: str, type_label: str = "", created_iso: str = "") -> str | None:
    """Crea la página en Notion y devuelve su URL. None si Notion está desactivado."""
    if not is_enabled():
        return None

    from notion_client import Client  # import perezoso: solo si Notion está activo

    client = Client(auth=NOTION_API_KEY)
    schema = client.databases.retrieve(database_id=NOTION_DATABASE_ID)["properties"]

    # Encuentra el nombre real de la propiedad de título (robusto al idioma).
    title_prop = next((k for k, v in schema.items() if v["type"] == "title"), None)
    properties = {}
    if title_prop:
        properties[title_prop] = {
            "title": [{"text": {"content": (title or "Reunión")[:2000]}}]
        }
    # Propiedades opcionales: solo se setean si existen en la base.
    if type_label and schema.get("Tipo", {}).get("type") == "select":
        properties["Tipo"] = {"select": {"name": type_label}}
    if created_iso and schema.get("Fecha", {}).get("type") == "date":
        properties["Fecha"] = {"date": {"start": created_iso}}

    page = client.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
        children=_md_to_blocks(summary)[:100],  # Notion permite 100 bloques por request
    )
    return page.get("url")


if __name__ == "__main__":
    demo = "## Resumen ejecutivo\nProbando **Muesli** con Notion.\n\n## Action items\n- [ ] Revisar la página creada"
    import json
    print(json.dumps(_md_to_blocks(demo), indent=2, ensure_ascii=False))
    print("\nNotion habilitado:", is_enabled())
