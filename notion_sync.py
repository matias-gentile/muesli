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

import config


def is_enabled() -> bool:
    return bool(config.get("NOTION_API_KEY") and config.get("NOTION_DATABASE_ID"))


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


def _retrieve_data_source(client, ds_id):
    """Trae un data source (API nueva). Usa el método tipado si existe, si no el crudo."""
    ds_api = getattr(client, "data_sources", None)
    if ds_api is not None and hasattr(ds_api, "retrieve"):
        return ds_api.retrieve(data_source_id=ds_id)
    return client.request(path=f"data_sources/{ds_id}", method="GET")


def sync(title: str, summary: str, type_label: str = "", created_iso: str = "") -> str | None:
    """Crea la página en Notion y devuelve su URL. None si Notion está desactivado."""
    if not is_enabled():
        return None

    from notion_client import Client  # import perezoso: solo si Notion está activo

    db_id = config.get("NOTION_DATABASE_ID")
    client = Client(auth=config.get("NOTION_API_KEY"))
    db = client.databases.retrieve(database_id=db_id)

    # Notion tiene dos formas de API:
    #  - vieja (2022-06-28): las propiedades vienen en database["properties"];
    #  - nueva (data sources): la base trae "data_sources" y las propiedades viven
    #    en el data source. Soportamos ambas para no romper según la versión de la lib.
    sources = db.get("data_sources") or []
    if sources:
        ds_id = sources[0]["id"]
        ds = _retrieve_data_source(client, ds_id)
        schema = ds.get("properties", {})
        parent = {"type": "data_source_id", "data_source_id": ds_id}
    else:
        schema = db.get("properties", {})
        parent = {"database_id": db_id}

    # Encuentra el nombre real de la propiedad de título (robusto al idioma).
    title_prop = next((k for k, v in schema.items() if v.get("type") == "title"), None)
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
        parent=parent,
        properties=properties,
        children=_md_to_blocks(summary)[:100],  # Notion permite 100 bloques por request
    )
    return page.get("url")


if __name__ == "__main__":
    demo = "## Resumen ejecutivo\nProbando **Muesli** con Notion.\n\n## Action items\n- [ ] Revisar la página creada"
    import json
    print(json.dumps(_md_to_blocks(demo), indent=2, ensure_ascii=False))
    print("\nNotion habilitado:", is_enabled())
