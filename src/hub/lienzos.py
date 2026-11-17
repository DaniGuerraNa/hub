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
import hashlib
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from . import config
from .reloj import ahora

# El mismo patrón que `catalogo.leer_frontmatter`. No se reutiliza aquella
# función porque corta el archivo a 4000 caracteres —le basta para leer la
# cabecera de una skill— y aquí hace falta el cuerpo entero, que ES el lienzo.
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)

# Un id de lienzo es un nombre de archivo: si viniera de una URL sin validar,
# `../../..` saldría de la carpeta del proyecto. Mismo criterio que el id de
# una conversación (`modelos.es_sesion`).
ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

# Igual para el proyecto, que también compone una ruta.
PROYECTO_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

PLANTILLAS = ("decisiones", "arquitectura", "pasos", "comparativa")


class SinPermiso(Exception):
    """Se iba a pisar algo del usuario. Lleva dentro qué hacer en su lugar."""


class Conflicto(Exception):
    """Lo que se iba a guardar parte de una versión que ya no es la del disco."""


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
            datos = config.leer_yaml(m.group(1))
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
    cuerpo = normalizar_cuerpo(plantilla, cuerpo)

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
        publicado_en=ahora(),
        cuerpo=cuerpo,
        extra=previo.extra if previo and previo.id == base else {},
    )
    _volcar(lienzo)
    return lienzo


# --------------------------------------------------------------------------- #
# Un valor por línea (C-0387)
# --------------------------------------------------------------------------- #
#
# 🔴 El único lector del cuerpo es el panel (`static/lienzos.js`), y lee línea a
# línea: un valor en bloque YAML (`justificacion: >-` y el texto debajo) se
# pintaba como «>-» y el texto se perdía. Que cada agente recordara escribir en
# una línea no bastó. Lo garantiza esta puerta, sin abrir un segundo lector:
# aquí sólo se reescribe cómo va escrito un valor, nunca qué dice.

# `clave: valor` o `- clave: valor`, con la sangría y el guion aparte.
_LINEA_CLAVE = re.compile(r"^(\s*)(-\s+)?([^\W\d][\w-]*)\s*:(?:\s+(.*?))?\s*$")
# Un valor que es sólo el indicador de un bloque: `|`, `>-`, `|+2`, `>2-`…
_INDICADOR_BLOQUE = re.compile(r"^[|>](?:[1-9][+-]?|[+-][1-9]?)?(?:\s+#.*)?$")

#: Las claves que el panel lee de cada plantilla (`static/lienzos.js`:
#: `leerPuntos`, `leerComparativa`, `leerGrafo`). Un valor partido sólo rompe
#: lo que se ve si es de una de éstas: lo demás el panel no lo mira, y un
#: lienzo que se publicaba y se veía bien no puede empezar a rechazarse
#: (revisión cruzada de C-0387). Una plantilla que no está aquí se enseña
#: cruda, así que tampoco se toca.
CLAVES_DEL_PANEL = {
    "decisiones": frozenset({"id", "punto", "justificacion", "decision", "propone", "respuesta"}),
    "comparativa": frozenset({"criterios", "valores", "eleccion", "porque", "nombre", "nota"}),
    "arquitectura": frozenset({"piezas", "flujo", "orientacion"}),
    "pasos": frozenset({"piezas", "flujo", "orientacion"}),
}

_COMO_ESCRIBIRLO = ('escríbelo en una línea, entre comillas, con \\n donde vaya '
                    'un salto: clave: "primera línea\\nsegunda"')


def _primer_valor_partido(cuerpo: str, claves: frozenset[str],
                          continuacion: bool) -> tuple[int, str] | None:
    """La línea (desde 1) y la clave del primer valor de `claves` que no cabe
    en su línea.

    Dos formas: el valor es un indicador de bloque, o —con `continuacion`— la
    línea de abajo sigue al valor (más sangrada que su clave y sin ser otra
    clave). Una línea suelta que no sigue a ningún valor —un cuerpo de texto
    libre, una lista de viñetas— no es un valor partido: el panel la enseña
    cruda, como siempre. Lo de una clave que el panel no lee, tampoco.
    """
    previa: tuple[int, str, int] | None = None     # (columna, clave, línea)
    for n, linea in enumerate(cuerpo.split("\n"), start=1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        m = _LINEA_CLAVE.match(linea)
        if m:
            clave, valor = m.group(3), m.group(4) or ""
            if clave in claves and _INDICADOR_BLOQUE.match(valor):
                return n, clave
            columna = len(m.group(1)) + len(m.group(2) or "")
            previa = (columna, clave, n) if valor and clave in claves else None
            continue
        sangria = len(linea) - len(linea.lstrip())
        if continuacion and previa and sangria > previa[0]:
            return previa[2], previa[1]
        previa = None
    return None


def _entre_comillas(valor: str) -> str:
    # Lo mismo que escribe `escaparYaml` y deshace `desescapar` en el panel.
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def normalizar_cuerpo(plantilla: str, cuerpo: str) -> str:
    """El cuerpo con cada valor en su línea, o `ValueError` con el porqué.

    Sólo mira las claves que el panel lee de esa plantilla
    (`CLAVES_DEL_PANEL`): un lienzo que se publicaba y se veía bien se sigue
    publicando tal cual.

    - Si no hay nada partido, vuelve **sin tocar un byte**: comentarios,
      comillas, campos desconocidos y hasta un cuerpo que YAML estricto no
      acepta pero el panel lee bien.
    - En `decisiones`, un valor partido de un punto (en bloque o que sigue
      abajo) se reescribe en su línea, entre comillas y con los saltos
      escapados; el resto de líneas no se toca. Se lee con `BaseLoader`, todo
      como texto: `safe_load` convertiría `decision: no` en `False`. Si el
      YAML no se entiende, se rechaza.
    - En las demás plantillas sólo se rechaza un indicador de bloque (`|`,
      `>`) como valor de una clave que el panel lee, que es lo que se pintaría
      como «>-»: diciendo la línea, la clave y cómo escribirlo.
    """
    claves = CLAVES_DEL_PANEL.get(plantilla, frozenset())
    decisiones = plantilla == "decisiones"
    partido = _primer_valor_partido(cuerpo or "", claves, continuacion=decisiones)
    if partido is None:
        return cuerpo
    n, clave = partido
    donde = f"línea {n}, «{clave}»: el valor ocupa varias líneas y el panel sólo lee la primera"
    if not decisiones:
        raise ValueError(f"{donde}; {_COMO_ESCRIBIRLO}")
    try:
        raiz_ = yaml.compose(cuerpo, Loader=yaml.BaseLoader)
        leido = yaml.load(cuerpo, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"{donde}, y el cuerpo no es YAML válido "
                         f"({getattr(exc, 'problem', None) or exc}); {_COMO_ESCRIBIRLO}") from exc

    lineas = cuerpo.split("\n")
    cambios: list[tuple[int, int, str]] = []       # (desde, hasta, línea nueva)

    def recorrer(nodo) -> None:
        if isinstance(nodo, yaml.SequenceNode):
            for hijo in nodo.value:
                if (isinstance(hijo, yaml.ScalarNode)
                        and (hijo.style in ("|", ">") or hijo.start_mark.line != hijo.end_mark.line)):
                    raise ValueError(f"línea {hijo.start_mark.line + 1}: un elemento de lista "
                                     f"ocupa varias líneas; {_COMO_ESCRIBIRLO}")
                recorrer(hijo)
        elif isinstance(nodo, yaml.MappingNode):
            for k, v in nodo.value:
                if not isinstance(v, yaml.ScalarNode):
                    recorrer(v)
                    continue
                # Un bloque acaba al principio de la línea siguiente; un
                # escalar plano o entre comillas, en su última línea.
                hasta = v.end_mark.line - (1 if v.end_mark.column == 0 else 0)
                if v.style not in ("|", ">") and hasta <= k.start_mark.line:
                    continue
                # Las líneas en blanco del final se quedan: separan puntos.
                while hasta > k.start_mark.line and not lineas[hasta].strip():
                    hasta -= 1
                prefijo = lineas[k.start_mark.line][:k.start_mark.column]
                if prefijo.strip() not in ("", "-") or k.start_mark.line != k.end_mark.line:
                    raise ValueError(f"línea {k.start_mark.line + 1}, «{k.value}»: "
                                     f"{_COMO_ESCRIBIRLO}")
                texto_clave = lineas[k.start_mark.line][k.start_mark.column:k.end_mark.column]
                cambios.append((k.start_mark.line, hasta,
                                f"{prefijo}{texto_clave}: {_entre_comillas(v.value)}"))

    recorrer(raiz_)
    for desde, hasta, nueva in sorted(cambios, reverse=True):
        lineas[desde:hasta + 1] = [nueva]
    salida = "\n".join(lineas)
    # Lo que se lee tiene que ser lo mismo: sólo cambia cómo va escrito.
    try:
        igual = yaml.load(salida, Loader=yaml.BaseLoader) == leido
    except yaml.YAMLError:
        igual = False
    if not igual:
        raise ValueError(f"{donde}, y no se pudo pasar a una línea sin cambiar lo que dice; "
                         f"{_COMO_ESCRIBIRLO}")
    return salida


def version(lienzo: Lienzo) -> str:
    """Una huella del cuerpo: lo que el panel leyó, para guardar encima de eso
    y no de otra cosa (C-0383). Del cuerpo y no del mtime: es lo que el panel
    reescribe, y archivar cambia el archivo sin cambiar el cuerpo."""
    return hashlib.sha256(lienzo.cuerpo.encode("utf-8")).hexdigest()[:16]


def guardar_edicion(lienzo: Lienzo, cuerpo: str, base: str | None = None) -> Lienzo:
    """Guarda lo que ha editado el usuario en la web.

    🔴 `publicado_en` NO se toca: es la marca de la última vez que escribió
    Claude, y es contra ella contra la que se decide si hay algo que proteger.
    Refrescarla aquí borraría la señal justo al crearse.

    🔴 Con `base`, sólo si el cuerpo del disco sigue siendo el que se leyó
    (`version`). El panel manda el cuerpo entero reescrito desde su copia: si
    el agente publicó una corrección mientras tanto, guardarlo la pisaría sin
    que nadie lo notara (C-0383). Entonces `Conflicto`, y no se escribe nada.
    """
    if base is not None and base != version(lienzo):
        raise Conflicto(f"«{lienzo.id}» cambió desde que lo abriste")
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
    lienzo.archivado_en = ahora() if archivar else None
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
