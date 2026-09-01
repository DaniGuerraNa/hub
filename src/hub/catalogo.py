"""Inventario de capacidades y dependencias de kits.

Ataca el segundo dolor: *"construyo algo, funciona, lo uso y luego me olvido que
existe"*. Es un problema de descubrimiento, no de gestión.

Todo lo de aquí es **derivado**: se escanea el filesystem y se reconstruye. La
fuente de verdad siguen siendo los archivos de cada proyecto.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .models import Proyecto

TRANSCRIPTS = Path.home() / ".claude" / "projects"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_MAPA = re.compile(r"^MAPA:\s*(\S+)\s*->\s*(\S+)", re.M)
_DIVERGE = re.compile(r"^DIVERGE:\s*(\S+)\s*(?:#\s*(.*))?$", re.M)
_RUTA = re.compile(r"^RUTA:\s*(\S+)", re.M)


def _fecha(ruta: Path) -> str | None:
    try:
        return datetime.fromtimestamp(ruta.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
    except OSError:
        return None


def leer_frontmatter(ruta: Path) -> dict:
    """Agentes y skills son markdown con frontmatter YAML."""
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return {}
    m = _FRONTMATTER.match(texto)
    if not m:
        return {}
    try:
        datos = yaml.safe_load(m.group(1))
        return datos if isinstance(datos, dict) else {}
    except yaml.YAMLError:
        return {}


def _hash(ruta: Path) -> str | None:
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except OSError:
        return None


# ───────────────────────── descubrimiento ─────────────────────────


def capacidades_de(proyecto: Proyecto) -> list[dict]:
    """Escanea por convención: todos los proyectos tienen la misma base `.claude/`."""
    encontradas: list[dict] = []
    vistas: set[str] = set()

    for base in proyecto.todas_las_rutas():
        raiz = Path(base)
        if not raiz.is_dir():
            continue

        for archivo in sorted(raiz.glob(".claude/agents/*.md")):
            encontradas.append(_capacidad(proyecto, archivo, "agente", vistas))

        # El case del archivo importa: `skill.md` en minúsculas fue deuda real
        # detectada en el inventario de junio, así que se aceptan ambos.
        for patron in (".claude/skills/*/SKILL.md", ".claude/skills/*/skill.md"):
            for archivo in sorted(raiz.glob(patron)):
                encontradas.append(_capacidad(proyecto, archivo, "skill", vistas))

        if proyecto.tipo == "kit":
            encontradas.extend(_capacidades_de_kit(proyecto, raiz, vistas))

    return [c for c in encontradas if c]


# Cada kit organiza sus cosas a su manera. Medido sobre tres kits reales: uno usa
# `metodo/` y `herramientas/`, otro `bin/` y `lib/`, y el tercero deja el método
# suelto en la raíz. Se cubren todas en vez de asumir una.
_DIRS_SCRIPT = ("herramientas", "bin", "tools", "scripts", "lib")
_DIRS_METODO = ("metodo", "metodos", "docs/equipo")
# Meta del propio kit, no capacidades suyas.
_DOCS_META = {"readme.md", "leeme.md", "license", "license.md", "claude.md", "agents.md"}


def _capacidades_de_kit(proyecto: Proyecto, raiz: Path, vistas: set) -> list[dict]:
    salida = []
    for carpeta in _DIRS_METODO:
        for archivo in sorted(raiz.glob(f"{carpeta}/*.md")):
            salida.append(_capacidad(proyecto, archivo, "metodo", vistas))
    # Método suelto en la raíz, descartando la meta del kit.
    for archivo in sorted(raiz.glob("*.md")):
        if archivo.name.lower() not in _DOCS_META:
            salida.append(_capacidad(proyecto, archivo, "metodo", vistas))

    for carpeta in _DIRS_SCRIPT:
        for archivo in sorted(raiz.glob(f"{carpeta}/*")):
            if archivo.is_file():
                salida.append(_capacidad(proyecto, archivo, "script", vistas))
    for patron in ("*.sh", "*.py"):
        for archivo in sorted(raiz.glob(patron)):
            salida.append(_capacidad(proyecto, archivo, "script", vistas))

    for archivo in sorted(raiz.glob("plantillas/**/*")):
        if archivo.is_file():
            salida.append(_capacidad(proyecto, archivo, "plantilla", vistas))
    return salida


def _capacidad(proyecto: Proyecto, archivo: Path, tipo: str, vistas: set) -> dict | None:
    ruta = str(archivo)
    if ruta in vistas:
        return None
    vistas.add(ruta)

    meta = leer_frontmatter(archivo) if archivo.suffix == ".md" else {}
    nombre = str(meta.get("name") or archivo.stem)
    if tipo == "skill" and not meta.get("name"):
        nombre = archivo.parent.name

    descripcion = " ".join(str(meta.get("description", "")).split())
    # Un SKILL.md de 0 bytes fue deuda real: se marca en vez de aparecer sano.
    vacio = archivo.stat().st_size == 0 if archivo.exists() else True

    return {
        "proyecto_id": proyecto.id,
        "tipo": tipo,
        "nombre": nombre,
        "ruta": ruta,
        "descripcion": descripcion[:400],
        "modelo": meta.get("model"),
        "status": "incompleto" if vacio else "activo",
        "origen": "convencion",
        "modificado": _fecha(archivo),
        "riesgos": None,
    }


def enriquecer_con_registry(proyecto: Proyecto, capacidades: list[dict]) -> None:
    """Absorbe los `registry.yaml` que ya existen.

    Un `registry.yaml` de proyecto lleva metadatos que el filesystem no tiene:
    status declarado, zonas de riesgo y contratos. El hub los lee; no los
    reescribe — el proyecto es el dueño de lo suyo.
    """
    por_nombre = {c["nombre"]: c for c in capacidades}

    for base in proyecto.todas_las_rutas():
        for candidato in (Path(base) / "registry.yaml", *sorted(Path(base).glob("registry/*.yaml"))):
            if not candidato.is_file():
                continue
            try:
                datos = yaml.safe_load(candidato.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            for comp in datos.get("components", []) or []:
                if not isinstance(comp, dict):
                    continue
                destino = por_nombre.get(comp.get("name"))
                if not destino:
                    continue
                if comp.get("status"):
                    destino["status"] = str(comp["status"])
                if comp.get("model"):
                    destino["modelo"] = str(comp["model"])
                if comp.get("risk_zones"):
                    destino["riesgos"] = json.dumps(comp["risk_zones"], ensure_ascii=False)
                destino["origen"] = "registry"


# ───────────────────────── dependencias de kits ─────────────────────────


def _dependencias_por_manifiesto(
    kit: Proyecto, raiz_kit: Path, proyectos: list[Proyecto]
) -> tuple[list[dict], list[dict]]:
    """La misma medida, pero con el kit declarando y el consumidor confirmando.

    El censo lo lleva el consumidor: un kit no puede listar los proyectos de otra
    persona, y mientras la relación viviera dentro del kit sólo funcionaba para
    quien lo escribía.
    """
    from . import kits as _kits

    enlaces: list[dict] = []
    try:
        manifiesto = _kits.leer_manifiesto(raiz_kit)
    except _kits.KitInvalido:
        return enlaces, []

    for p in proyectos:
        if p.id == kit.id:
            continue
        declarado = next(
            (d for d in _kits.kits_declarados(p.todas_las_rutas()) if d.get("id") == kit.id),
            None,
        )
        if not declarado:
            continue
        for medido in _kits.medir(p.todas_las_rutas(), manifiesto, declarado):
            enlaces.append({
                "kit_id": kit.id,
                "consumidor_id": p.id,
                "origen": medido["origen"],
                "destino": medido["destino"],
                # `al-dia` es el veredicto de una copia, que no se mide por
                # contenido; para la vista de deriva cuenta como al día.
                "estado": "igual" if medido["estado"] == "al-dia" else medido["estado"],
            })
    # Con manifiesto no hay `DIVERGE:`: una copia diverge por diseño y lo demás
    # se declara en el propio proyecto.
    return enlaces, []


def dependencias_de_kit(kit: Proyecto, proyectos: list[Proyecto]) -> tuple[list[dict], list[dict]]:
    """Qué archivos suyos están en cada consumidor, y cuáles han derivado.

    **Dos formatos, y se soportan los dos.** Si el kit trae `kit.yml`, manda el
    manifiesto y los consumidores son los proyectos que lo declaran en su
    `.claude/hub/kits.yml`. Si no, se leen sus fichas `consumidores/*.md` con sus
    `MAPA:` y `DIVERGE:`, como hasta ahora.

    La compatibilidad no es cortesía: migrar un kit con cinco consumidores es una
    decisión aparte, y romper una medición que funciona para estrenar el
    mecanismo sería cambiar algo que funciona por algo que aún no.
    """
    raiz_kit = Path(kit.asiento or "")
    if (raiz_kit / "kit.yml").is_file():
        return _dependencias_por_manifiesto(kit, raiz_kit, proyectos)

    enlaces: list[dict] = []
    divergencias: list[dict] = []

    carpeta = raiz_kit / "consumidores"
    if not carpeta.is_dir():
        return enlaces, divergencias

    por_ruta = {r: p.id for p in proyectos for r in p.todas_las_rutas()}

    for ficha in sorted(carpeta.glob("*.md")):
        try:
            texto = ficha.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        m = _RUTA.search(texto)
        raiz_consumidor = Path(m.group(1)) if m else None
        consumidor_id = por_ruta.get(str(raiz_consumidor).rstrip("/")) if m else None
        consumidor_id = consumidor_id or ficha.stem

        declaradas = {a for a, _ in _DIVERGE.findall(texto)}

        for origen, destino in _MAPA.findall(texto):
            f_origen = raiz_kit / origen
            f_destino = (raiz_consumidor / destino) if raiz_consumidor else None

            if f_destino is None or not f_destino.exists():
                estado = "falta"
            elif not f_origen.exists():
                estado = "sin-origen"
            else:
                igual = _hash(f_origen) == _hash(f_destino)
                estado = "igual" if igual else "difiere"
                if estado == "difiere" and destino in declaradas:
                    estado = "divergencia-declarada"

            enlaces.append(
                {
                    "kit_id": kit.id,
                    "consumidor_id": consumidor_id,
                    "origen": origen,
                    "destino": destino,
                    "estado": estado,
                }
            )

        for archivo, razon in _DIVERGE.findall(texto):
            divergencias.append(
                {
                    "kit_id": kit.id,
                    "consumidor_id": consumidor_id,
                    "archivo": archivo,
                    "razon": " ".join((razon or "").split())[:400],
                }
            )

    return enlaces, divergencias


# ───────────────────────── uso real ─────────────────────────


def buscador() -> list[str] | None:
    """Comando para buscar en los transcripts.

    `shutil.which` es la comprobación buena: `command -v` del shell también
    resuelve alias y funciones, que no existen para `subprocess`. Aquí `rg` era
    justamente un alias, y la medición se saltaba en silencio.
    """
    if shutil.which("rg"):
        return ["rg", "-l", "--glob", "*.jsonl", "-F"]
    if shutil.which("grep"):
        return ["grep", "-rlF", "--include=*.jsonl"]
    return None


def patron_de_uso(capacidad: dict) -> str | None:
    """Cómo se reconoce el uso de cada tipo. `None` = no es medible así.

    Distinguir importa: un método es un documento que se lee, no algo que se
    invoque por nombre. Medirlo con la misma vara lo marcaría como olvidado
    siempre — un falso negativo que envenena justo la señal que da valor a esto.
    """
    if capacidad["tipo"] in ("agente", "skill"):
        # Entrecomillado: aparece así en las invocaciones, y no confunde con
        # prosa que mencione el nombre de pasada.
        return f'"{capacidad["nombre"]}"'
    if capacidad["tipo"] == "script":
        return Path(capacidad["ruta"]).name
    return None


def medir_uso(capacidades: list[dict]) -> dict[str, str]:
    """Última vez que cada capacidad aparece en los transcripts de Claude Code.

    Es la diferencia entre «cuándo lo edité» y «cuándo lo usé», que es lo que de
    verdad contesta si algo se te olvidó. La clave es la ruta, no el nombre:
    `mutar.py` y `mutar.sh` comparten nombre y no son lo mismo.
    """
    comando = buscador()
    if not TRANSCRIPTS.is_dir() or not comando:
        return {}

    cache: dict[str, str | None] = {}
    usos: dict[str, str] = {}

    for capacidad in capacidades:
        patron = patron_de_uso(capacidad)
        if not patron or len(patron) < 5:
            continue

        if patron not in cache:
            try:
                salida = subprocess.run(
                    [*comando, patron, str(TRANSCRIPTS)],
                    capture_output=True, text=True, timeout=60, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                cache[patron] = None
                continue
            reciente = None
            for linea in salida.stdout.splitlines():
                f = _fecha(Path(linea))
                if f and (reciente is None or f > reciente):
                    reciente = f
            cache[patron] = reciente

        if cache[patron]:
            usos[capacidad["ruta"]] = cache[patron]

    return usos


# ───────────────────────── persistencia ─────────────────────────


def escanear(con: sqlite3.Connection, proyectos: list[Proyecto], medir: bool = False) -> dict:
    """Repuebla el catálogo entero. Es un índice: se tira y se rehace."""
    capacidades: list[dict] = []
    for proyecto in proyectos:
        propias = capacidades_de(proyecto)
        enriquecer_con_registry(proyecto, propias)
        capacidades.extend(propias)

    if medir:
        usos = medir_uso(capacidades)
    else:
        # Un reescaneo rápido NO puede borrar la medición de uso: dejaría todo
        # como «sin uso detectado» y eso se lee como «se te olvidó», que es
        # justo la señal que da valor al inventario. Se arrastra lo ya medido.
        usos = {
            f["ruta"]: f["usado"]
            for f in con.execute("SELECT ruta, usado FROM capacidad WHERE usado IS NOT NULL")
        }

    # La misma marca para todas: el catálogo se borra y se rehace entero,
    # así que una fecha por fila sería la misma fecha repetida.
    medido_en = datetime.now(timezone.utc).isoformat()
    con.execute("DELETE FROM capacidad")
    for c in capacidades:
        con.execute(
            """INSERT INTO capacidad (proyecto_id, tipo, nombre, ruta, descripcion,
                                      modelo, status, origen, modificado, usado,
                                      medible, riesgos, medido_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c["proyecto_id"], c["tipo"], c["nombre"], c["ruta"], c["descripcion"],
             c["modelo"], c["status"], c["origen"], c["modificado"],
             usos.get(c["ruta"]), int(patron_de_uso(c) is not None), c["riesgos"],
             medido_en),
        )

    con.execute("DELETE FROM dependencia")
    con.execute("DELETE FROM divergencia")
    kits = [p for p in proyectos if p.tipo == "kit"]
    for kit in kits:
        enlaces, divergencias = dependencias_de_kit(kit, proyectos)
        for e in enlaces:
            con.execute(
                """INSERT OR REPLACE INTO dependencia
                   (kit_id, consumidor_id, origen, destino, estado) VALUES (?,?,?,?,?)""",
                (e["kit_id"], e["consumidor_id"], e["origen"], e["destino"], e["estado"]),
            )
        for d in divergencias:
            con.execute(
                """INSERT OR REPLACE INTO divergencia
                   (kit_id, consumidor_id, archivo, razon) VALUES (?,?,?,?)""",
                (d["kit_id"], d["consumidor_id"], d["archivo"], d["razon"]),
            )

    return {
        "capacidades": len(capacidades),
        "kits": len(kits),
        "uso_medido": bool(usos),
    }
