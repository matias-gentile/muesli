#!/usr/bin/env python3
"""Recupera una grabación a partir de sus .wav (cuando el procesado falló).

Re-transcribe los segmentos de una carpeta de grabación y regenera el resumen,
sin volver a grabar. Útil si el resumen falló (p.ej. un corte de red con la API)
pero los .wav siguen en disco.

Uso:
    python recover.py                          # usa la grabación más reciente
    python recover.py recordings/meeting-XXXX  # una carpeta específica
    python recover.py --title "Reunión semanal" --type reunion
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import notion_sync
import storage
from config import RECORDINGS_DIR
from summarize import summarize, type_label
from transcribe import transcribe


def _latest_meeting_dir():
    dirs = sorted(RECORDINGS_DIR.glob("meeting-*"), key=lambda p: p.stat().st_mtime)
    return dirs[-1] if dirs else None


def main():
    parser = argparse.ArgumentParser(
        description="Recupera el resumen de una grabación desde sus .wav")
    parser.add_argument("folder", nargs="?",
                        help="Carpeta de la grabación (por defecto, la más reciente)")
    parser.add_argument("--title", default="", help="Título de la reunión")
    parser.add_argument("--type", default="reunion", dest="ctype",
                        help="Tipo: reunion, clase, entrevista, video, uno_a_uno, brainstorm, general")
    parser.add_argument("--notes", default="", help="Notas manuales (opcional)")
    args = parser.parse_args()

    folder = Path(args.folder) if args.folder else _latest_meeting_dir()
    if not folder or not folder.exists():
        print("No encontré una carpeta de grabación. Pasá la ruta como argumento, p.ej.:")
        print("  python recover.py recordings/meeting-20260622-143000")
        sys.exit(1)

    chunks = sorted(folder.glob("chunk_*.wav")) or sorted(folder.glob("*.wav"))
    if not chunks:
        print(f"No encontré archivos .wav en {folder}")
        sys.exit(1)

    print(f"Recuperando {len(chunks)} segmento(s) desde {folder}\n")
    texts = []
    for i, ch in enumerate(chunks, 1):
        print(f"  [{i}/{len(chunks)}] transcribiendo {ch.name} …", flush=True)
        texts.append(transcribe(str(ch)))
    transcript = "\n".join(texts).strip()

    if not transcript:
        print("\nLas transcripciones quedaron vacías (¿el audio estaba en silencio?).")
        sys.exit(1)

    title = args.title or f"Recuperada {folder.name.replace('meeting-', '')}"
    print(f"\nGenerando resumen ({type_label(args.ctype)}) con Claude …")
    try:
        summary = summarize(transcript, args.notes, title, args.ctype, "")
    except Exception as e:
        # Aun si el resumen vuelve a fallar, guardamos la transcripción para no perderla.
        print(f"\n⚠️  El resumen falló de nuevo ({e}). Guardo la transcripción igual; "
              f"podés reintentar el resumen desde el panel (botón 'Regenerar resumen').")
        summary = (f"_El resumen automático falló ({e}). La transcripción está guardada — "
                   f"regenerá el resumen desde el panel._")

    note = storage.save_note(title, transcript, summary, args.notes, str(folder), args.ctype)
    print(f"\n✓ Guardado: {note['path']}")

    if notion_sync.is_enabled() and not summary.startswith("_El resumen"):
        try:
            url = notion_sync.sync(title, summary, type_label(args.ctype), note["created_at"])
            if url:
                print(f"✓ En Notion: {url}")
        except Exception as e:
            print(f"(Notion falló: {e})")

    print("\nListo. Abrí Muesli para verla en el historial.")


if __name__ == "__main__":
    main()
