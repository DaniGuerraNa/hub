"""Las conversaciones de Claude que ha tenido un slot, para retomarlas (decisión 290).

Lo pidió quien usa el hub tras perder el hilo: se cerró la consola y tuvo que
abrir otra y contarle a Claude desde cero en qué estaban. La conversación NO
se había perdido —Claude Code la guarda entera en `~/.claude/projects/`—, pero
nada en pantalla decía que existía ni cómo volver a ella. Esto la enseña.

🔴 Se lee, no se escribe: los `.jsonl` son de Claude Code. Retomar es abrir una
ventana con `claude --resume <id>` como proceso, igual que «Lanzar» abre una
con `claude` —es el botón de la persona, no teclas en una shell (decisión 22)—.

Medido el 2026-10-22 con Claude Code 2.1.280: `--resume` conserva el id y
sigue escribiendo en el MISMO archivo, así que retomar no crea otra entrada.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from . import api, transcripts

# Cuántas se enseñan por slot: las de hace semanas se buscan desde la sesión
# misma (`/resume`), no aquí, y cada una cuesta leer su archivo entero.
LIMITE = 8
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# `resumir_sesion` lee el archivo entero, y una sesión larga pesa megas. Se
# guarda la ficha mientras el archivo no cambie (misma fecha y tamaño).
_FICHAS: dict[str, tuple[float, int, dict | None]] = {}


def _ficha(ruta: Path) -> dict | None:
    try:
        st = ruta.stat()
    except OSError:
        return None
    previa = _FICHAS.get(str(ruta))
    if previa and previa[0] == st.st_mtime and previa[1] == st.st_size:
        return previa[2]
    ficha = transcripts.resumir_sesion(ruta)
    _FICHAS[str(ruta)] = (st.st_mtime, st.st_size, ficha)
    return ficha


def _rutas_del_slot(con: sqlite3.Connection, slot: dict) -> list[str]:
    """Donde se abren sus ventanas: la ruta del slot o, sin ella, el asiento."""
    if slot.get("ruta"):
        return [slot["ruta"]]
    proyecto = api.obtener_proyecto(con, slot["proyecto_id"]) or {}
    return [proyecto["asiento"]] if proyecto.get("asiento") else []


def _vistas_en_el_slot(con: sqlite3.Connection, slot_id: int) -> set[str]:
    """Las que el muestreo vio correr en una ventana de ESTE slot.

    La carpeta la comparten todos los slots sin ruta propia del proyecto; esto
    es lo que distingue las suyas. Sólo hay desde la 0.3.0 (`claude_sesion`).
    """
    return {f[0] for f in con.execute(
        "SELECT DISTINCT claude_sesion FROM panel WHERE slot_id = ? AND claude_sesion IS NOT NULL",
        (slot_id,))}


def _vivas(con: sqlite3.Connection) -> dict[str, dict]:
    """`{id: panel}` de las que están abiertas ahora mismo en alguna ventana."""
    return {p["claude_sesion"]: p for p in api.paneles_abiertos(con) if p.get("claude_sesion")}


def de_slot(con: sqlite3.Connection, slot_id: int, limite: int = LIMITE) -> list[dict[str, Any]]:
    """Las últimas conversaciones de la carpeta del slot, la más reciente primero."""
    slot = api.obtener_slot(con, slot_id)
    if not slot:
        return []
    archivos: dict[str, Path] = {}
    for ruta in _rutas_del_slot(con, slot):
        directorio = transcripts.TRANSCRIPTS / transcripts.slug_de(ruta)
        if directorio.is_dir():
            for archivo in transcripts.jsonl_de(directorio):
                archivos[archivo.stem] = archivo
    propias = _vistas_en_el_slot(con, slot_id)
    # Las que corrieron en este slot pero desde otra carpeta (alguien hizo `cd`).
    for sesion in propias - archivos.keys():
        archivo = transcripts.ruta_de_sesion(sesion)
        if archivo:
            archivos[sesion] = archivo

    vivas = _vivas(con)
    salida = []
    for archivo in sorted(archivos.values(), key=transcripts.mtime, reverse=True):
        ficha = _ficha(archivo)
        # Una sin ninguna petición suya es un arranque que no llegó a nada.
        if not ficha or not ficha.get("turnos"):
            continue
        panel = vivas.get(ficha["id"])
        salida.append({**ficha,
                       "de_este_slot": ficha["id"] in propias,
                       "viva": bool(panel),
                       "ventana": ({"session": panel["session"], "ventana": panel["window_idx"]}
                                   if panel else None)})
        if len(salida) >= limite:
            break
    return salida


def retomable(con: sqlite3.Connection, slot_id: int, sesion: str) -> dict:
    """La conversación, si se puede retomar desde este slot. Si no, ValueError.

    Sólo una de las que la lista ofrece: el id viene de un formulario y no se
    reanuda cualquier conversación de la máquina en la carpeta de este slot.
    """
    if not _UUID.match(sesion or ""):
        raise ValueError("esa conversación no tiene un id válido")
    ficha = next((c for c in de_slot(con, slot_id, limite=50) if c["id"] == sesion), None)
    if not ficha:
        raise ValueError("esa conversación no es de este slot")
    if ficha["viva"]:
        # Dos procesos escribiendo el mismo archivo se pisan la conversación.
        raise ValueError("esa conversación ya está abierta en una ventana")
    return ficha
