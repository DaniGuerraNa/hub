"""Lienzos: lo que Claude publica para que se vea en la web.

Un lienzo es **markdown con frontmatter**, como las skills y los kits, en una
carpeta por proyecto dentro de `HUB_HOME`:

    ~/.local/share/hub/lienzos/<proyecto_id>/<id>.md

🔴 **La carpeta es la fuente de verdad; no hay índice.** Es la regla dura 1
aplicada: borrar un archivo lo borra del panel y copiar uno lo añade, sin
migración ni base que mantener. El título vive en el frontmatter del propio
archivo, así que no hay dos sitios donde pueda quedar desincronizado.

🔴 **Por proyecto y no por slot**, aunque un lienzo nazca en un slot. `slot.id`
es un `INTEGER AUTOINCREMENT` de SQLite —un índice que la regla dura 1 permite
regenerar— y los slots se archivan y se borran; el `proyecto.id` es la identidad
que «no cambia nunca». Colgar archivos permanentes del primero los dejaría
huérfanos en carpetas cuyo slot ya no existe. El slot va como campo, por nombre,
y sirve para ORDENAR el panel, no para separar.

🔴 **Un lienzo que ha tocado el usuario no se sobrescribe sin decirlo.** Es el
único punto donde este módulo puede destruir trabajo que no es suyo: el ciclo
normal es que Claude publique, el usuario corrija en la web y Claude regenere —
y ahí, sin guarda, la regeneración se lleva por delante veinte minutos de
correcciones **sin que se note**, porque el panel enseña un lienzo válido igual.
Ver `escribir()`.
"""

from __future__ import annotations

import contextlib
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from . import config

# El mismo patrón que `catalogo.leer_frontmatter`. No se reutiliza aquella
# función porque corta el archivo a 4000 caracteres —le basta para leer la
# cabecera de una skill— y aquí hace falta el cuerpo entero, que ES el lienzo.
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)

# Un id de lienzo es un nombre de archivo: si viniera de una URL sin validar,
# `../../..` saldría de la carpeta del proyecto. Mismo criterio que
# `transcripts.ID_SESION`.
ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

# Igual para el proyecto, que también compone una ruta.
PROYECTO_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

PLANTILLAS = ("decisiones", "arquitectura", "pasos", "comparativa")


class SinPermiso(Exception):
    """Se iba a pisar algo del usuario. Lleva dentro qué hacer en su lugar."""


class Lienzo(BaseModel):
    id: str
    titulo: str
    plantilla: str = "decisiones"
    proyecto_id: str
    # Por NOMBRE, no por id: el id de un slot no sobrevive a reconstruir el
    # índice, y el lienzo tiene que seguir sabiendo dónde nació.
    slot: str | None = None
    # Cuándo lo escribió el agente. Comparado con el mtime, es lo que dice si
    # después lo ha tocado una persona — sin llevar ninguna contabilidad.
    publicado_en: str | None = None
    # Cuándo se archivó, o None si está en uso. Archivar NO es borrar: el
    # archivo se queda donde está y lo sigue encontrando el buscador.
    archivado_en: str | None = None
    cuerpo: str = ""
    extra: dict = Field(default_factory=dict)

    @property
    def ruta(self) -> Path:
        return carpeta_de(self.proyecto_id) / f"{self.id}.md"

    def editado_por_el_usuario(self) -> bool:
        """Si el archivo es más nuevo que su publicación, lo tocó alguien que no fue Claude.

        Un margen de 2 s absorbe la resolución del sistema de archivos y el
        tiempo entre que se compone el texto y se escribe: sin él, un lienzo
        recién publicado se declara «editado por ti» y la protección de
        `escribir()` salta siempre, que es la forma de que se acabe ignorando.

        🔴 **Sin `publicado_en` se responde que SÍ.** Un lienzo sin esa marca es
        uno traído a mano, o uno cuyo frontmatter se rompió al editarlo fuera de
        la web — y en los dos casos el hub no puede afirmar que lo escribiera
        Claude. Devolver `False` «porque no consta» convertía justo esos dos
        casos en los únicos donde la republicación pisa sin avisar, que es al
        revés de como tiene que fallar esto: ante la duda, no se destruye.
        """
        try:
            mtime = self.ruta.stat().st_mtime
        except OSError:
            return False
        publicado = _a_epoch(self.publicado_en)
        if publicado is None:
            return True
        return mtime > publicado + 2


# --------------------------------------------------------------------------- #
# Dónde viven
# --------------------------------------------------------------------------- #


def raiz() -> Path:
    """Se resuelve en cada llamada, no al importar: los tests mueven `HUB_HOME`
    con `monkeypatch.setattr` y una constante se quedaría con la ruta vieja —
    que es como la suite acabaría escribiendo en los datos de verdad."""
    return config.HUB_HOME / "lienzos"


def carpeta_de(proyecto_id: str) -> Path:
    if not PROYECTO_VALIDO.match(proyecto_id or ""):
        raise ValueError(f"id de proyecto inválido: {proyecto_id!r}")
    return raiz() / proyecto_id


def slug(titulo: str) -> str:
    """Un título en un nombre de archivo estable. Vacío si no queda nada usable."""
    plano = unicodedata.normalize("NFKD", titulo or "")
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = re.sub(r"[^a-zA-Z0-9]+", "-", plano).strip("-").lower()
    return plano[:80].strip("-")


def _libre(proyecto_id: str, base: str) -> str:
    """`base`, o `base-2`, `base-3`… El sufijo empieza en 2 porque el primero no
    lo lleva: `ejemplo-c` y `ejemplo-c-2` se leen como lo que son."""
    carpeta = carpeta_de(proyecto_id)
    if not (carpeta / f"{base}.md").exists():
        return base
    for n in range(2, 1000):
        if not (carpeta / f"{base}-{n}.md").exists():
            return f"{base}-{n}"
    raise ValueError(f"demasiados lienzos llamados «{base}»")


# --------------------------------------------------------------------------- #
# Leer
# --------------------------------------------------------------------------- #


def _de_archivo(ruta: Path, proyecto_id: str) -> Lienzo | None:
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    cabecera: dict = {}
    cuerpo = texto
    m = _FRONTMATTER.match(texto)
    if m:
        try:
            datos = yaml.safe_load(m.group(1))
            cabecera = datos if isinstance(datos, dict) else {}
        except yaml.YAMLError:
            # Un frontmatter roto no puede esconder el lienzo: se enseña con lo
            # que se pueda y el cuerpo intacto, que es lo que el usuario quiere
            # recuperar. Reventar aquí dejaría el panel vacío sin decir por qué.
            cabecera = {}
        cuerpo = texto[m.end():]

    conocidos = {"titulo", "plantilla", "slot", "publicado_en", "archivado_en"}
    return Lienzo(
        id=ruta.stem,
        titulo=str(cabecera.get("titulo") or ruta.stem),
        plantilla=str(cabecera.get("plantilla") or "decisiones"),
        proyecto_id=proyecto_id,
        slot=(str(cabecera["slot"]) if cabecera.get("slot") else None),
        publicado_en=(str(cabecera["publicado_en"]) if cabecera.get("publicado_en") else None),
        archivado_en=(str(cabecera["archivado_en"]) if cabecera.get("archivado_en") else None),
        cuerpo=cuerpo,
        # Lo que una plantilla futura añada se conserva al reescribir. Sin esto,
        # editar desde la web borraría campos que el hub aún no conoce.
        extra={k: v for k, v in cabecera.items() if k not in conocidos},
    )


def leer(proyecto_id: str, lienzo_id: str) -> Lienzo | None:
    if not ID_VALIDO.match(lienzo_id or ""):
        return None
    ruta = carpeta_de(proyecto_id) / f"{lienzo_id}.md"
    return _de_archivo(ruta, proyecto_id) if ruta.is_file() else None


def listar(proyecto_id: str, archivados: bool | None = False) -> list[Lienzo]:
    """Los del proyecto, del más reciente al más viejo.

    Por defecto **sin los archivados**: el panel lista todo lo del proyecto para
    siempre y el hub no poda nada solo (principio 9), así que con dos ya cuesta
    y el que terminaste de usar estorba al que estás usando.

    `archivados=True` da sólo los archivados, y `None` los da todos — que es lo
    que necesita el buscador: archivar los quita de la lista, no de la memoria,
    y ésa es toda la diferencia con borrar.

    🔴 Un id inválido levanta `ValueError`; NO devuelve lista vacía. Tragárselo
    era seguro —`carpeta_de` ya impide salir de la carpeta— pero hacía
    indistinguible «este proyecto no tiene lienzos» de «me has pasado
    `../../etc`», y quien pregunta se queda sin saber cuál de las dos. Es la
    regla dura 21: si se atrapa un error, se dice en voz alta.
    """
    carpeta = carpeta_de(proyecto_id)
    if not carpeta.is_dir():
        return []
    try:
        archivos = [a for a in carpeta.iterdir() if a.is_file() and a.suffix == ".md"]
    except OSError:
        return []
    archivos.sort(key=lambda a: _mtime(a), reverse=True)
    todos_ = [l for a in archivos if (l := _de_archivo(a, proyecto_id))]
    if archivados is None:
        return todos_
    return [l for l in todos_ if bool(l.archivado_en) == archivados]


def todos() -> list[Lienzo]:
    """Todos los de todos los proyectos, **archivados incluidos**.

    Es lo que consume la búsqueda global, y ahí tienen que estar: buscar es la
    forma de recuperar algo que quitaste de la lista. Cuando `listar` empezó a
    filtrarlos por defecto, la búsqueda dejó de encontrarlos sin que nada lo
    dijera — lo cazó el test, no la lectura.
    """
    base = raiz()
    if not base.is_dir():
        return []
    salida: list[Lienzo] = []
    try:
        carpetas = sorted(d for d in base.iterdir() if d.is_dir())
    except OSError:
        return []
    for carpeta in carpetas:
        # Aquí los nombres vienen del disco, no de una petición: una carpeta con
        # un nombre que no valida se salta en vez de tumbar la búsqueda entera.
        try:
            salida.extend(listar(carpeta.name, archivados=None))
        except ValueError:
            continue
    salida.sort(key=lambda l: _mtime(l.ruta), reverse=True)
    return salida


def buscar(consulta: str, limite: int = 20) -> list[Lienzo]:
    q = (consulta or "").strip().lower()
    if not q:
        return []
    hallados = [l for l in todos() if q in l.titulo.lower() or q in l.id]
    return hallados[:limite]


# --------------------------------------------------------------------------- #
# Escribir
# --------------------------------------------------------------------------- #


def escribir(
    proyecto_id: str,
    titulo: str,
    cuerpo: str = "",
    plantilla: str = "decisiones",
    slot: str | None = None,
    lienzo_id: str | None = None,
    forzar: bool = False,
    revisar: bool = False,
) -> Lienzo:
    """Publica un lienzo. **No pisa lo que haya editado el usuario.**

    Tres caminos cuando el destino ya existe:

    - lo escribió Claude y nadie lo tocó → se actualiza, que es lo esperado;
    - lo tocó el usuario y `revisar=True` → se crea **al lado** (`-2`);
    - lo tocó el usuario y no se dice nada → `SinPermiso`, con las dos salidas.

    La tercera es la que importa. Sin ella el ciclo normal —Claude publica, el
    usuario corrige, Claude regenera— destruye la corrección en silencio.
    """
    base = lienzo_id or slug(titulo)
    if not ID_VALIDO.match(base or ""):
        raise ValueError(f"del título «{titulo}» no sale un nombre usable")

    previo = leer(proyecto_id, base)
    if previo is not None and not forzar:
        if previo.editado_por_el_usuario():
            if not revisar:
                raise SinPermiso(
                    f"«{base}» ya existe y lo editaste tú. "
                    f"Usa --revisar para publicarlo al lado, o --forzar para pisarlo."
                )
            base = _libre(proyecto_id, base)

    lienzo = Lienzo(
        id=base,
        titulo=titulo or base,
        plantilla=plantilla,
        proyecto_id=proyecto_id,
        slot=slot,
        publicado_en=_ahora(),
        cuerpo=cuerpo,
        extra=previo.extra if previo and previo.id == base else {},
    )
    _volcar(lienzo)
    return lienzo


def guardar_edicion(lienzo: Lienzo, cuerpo: str) -> Lienzo:
    """Guarda lo que ha editado el usuario en la web.

    🔴 `publicado_en` NO se toca: es la marca de la última vez que escribió
    Claude, y es contra ella contra la que se decide si hay algo que proteger.
    Refrescarla aquí borraría la señal justo al crearse.
    """
    lienzo.cuerpo = cuerpo
    _volcar(lienzo)
    return lienzo


def archivar(proyecto_id: str, lienzo_id: str, archivar: bool = True) -> Lienzo | None:
    """Fuera de la lista, pero no del disco. Reversible siempre.

    🔴 **Se preserva el mtime.** Archivar no es editar: sin esto, mover un
    lienzo a archivados lo marcaría como «editado por ti» para siempre —
    `editado_por_el_usuario()` compara el mtime con `publicado_en`— y la
    protección de `escribir()` saltaría en un archivo que nadie tocó. Un aviso
    que salta sin motivo se aprende a ignorar, y ése protege de destruir
    correcciones a mano.

    Tampoco se mueve a otra carpeta, que era la otra forma de hacerlo: la
    carpeta es la fuente de verdad (regla dura 1) y dos sitios posibles para el
    mismo lienzo obligan a buscar en ambos en cada lectura, cada borrado y cada
    búsqueda. Un campo es un solo sitio.
    """
    lienzo = leer(proyecto_id, lienzo_id)
    if lienzo is None:
        return None
    lienzo.archivado_en = _ahora() if archivar else None
    antes = lienzo.ruta.stat()
    _volcar(lienzo)
    with contextlib.suppress(OSError):
        os.utime(lienzo.ruta, (antes.st_atime, antes.st_mtime))
    return lienzo


def borrar(proyecto_id: str, lienzo_id: str) -> bool:
    """Borrar es del usuario, nunca del hub por su cuenta (regla dura 3)."""
    lienzo = leer(proyecto_id, lienzo_id)
    if lienzo is None:
        return False
    try:
        lienzo.ruta.unlink()
        return True
    except OSError:
        return False


def _volcar(lienzo: Lienzo) -> None:
    cabecera = {
        "titulo": lienzo.titulo,
        "plantilla": lienzo.plantilla,
        **({"slot": lienzo.slot} if lienzo.slot else {}),
        **({"publicado_en": lienzo.publicado_en} if lienzo.publicado_en else {}),
        **({"archivado_en": lienzo.archivado_en} if lienzo.archivado_en else {}),
        **lienzo.extra,
    }
    texto = (
        "---\n"
        + yaml.safe_dump(cabecera, allow_unicode=True, sort_keys=False)
        + "---\n"
        + lienzo.cuerpo
    )
    ruta = lienzo.ruta
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atómica: un corte a mitad dejaría un lienzo truncado que el panel
    # enseñaría como si fuera bueno. `replace` es atómico dentro del mismo
    # sistema de archivos, y el temporal es hermano justamente para eso.
    tmp = ruta.with_suffix(".md.tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(ruta)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _a_epoch(cuando: str | None) -> float | None:
    if not cuando:
        return None
    try:
        momento = datetime.fromisoformat(str(cuando).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.timestamp()


def _mtime(ruta: Path) -> float:
    try:
        return ruta.stat().st_mtime
    except OSError:
        return 0.0
