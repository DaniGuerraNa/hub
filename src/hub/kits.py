"""Kits: capas que aportan una capacidad a un proyecto, resueltas como dependencias.

Un kit es *«una librería que aporta funcionalidades al aplicarse sobre un
proyecto»* — el kit de orquestación da la capacidad de trabajar de forma
semiautónoma, y así con cada uno. Un proyecto es la capa base obligatoria más
0..N kits.

**El hub es el gestor; los kits son los artefactos.** Un JAR funciona sin Maven
—lo pones en el classpath a mano— pero nadie lo hace, porque cablearlo es el
trabajo que el gestor quita. De ahí la línea que separa las dos cosas:

    🔴 Un kit no puede exigir el hub para que su CONTENIDO funcione; sólo para
       organizarlo. Sus documentos se leen y sus scripts corren a mano. Lo que
       requiere el hub es aplicarlo, resolverlo por `id`, medirlo y mantenerlo.

Tres archivos forman el contrato:

* `kit.yml` en la raíz del kit — qué es, qué expone, qué consume y qué aplica.
* `kits.yml` — el catálogo: `id → repo git → versión`. El del repo trae los
  públicos; el del usuario, en `HUB_HOME`, se fusiona encima.
* `.claude/hub/kits.yml` en el consumidor — qué kits tiene y qué escribieron.
  Es el `pom.xml` del proyecto: vive dentro, versionado, y viaja con él.

Lo que este módulo NO hace: escribir dentro de un proyecto ajeno. Calcula el
plan de aplicación y lo propone; quien escribe es un agente corriendo en ese
repo, con el humano mirando. El hub indexa; el proyecto decide.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import config

# Qué versión de la capa base exige el hub. La base es el kit obligatorio: sólo
# entra en ella lo que necesitan TODOS los proyectos, y añadir algo sube `major`
# y obliga a migrarlos.
VERSION_BASE = "1.0"

ID_BASE = "base"

# `major.minor`, sin más: los rangos de versión de Maven están desaconsejados
# por el propio Maven, porque hacen que una instalación deje de ser reproducible.
_VERSION = re.compile(r"^\d+\.\d+$")

# El `id` de un kit se convierte en nombre de carpeta dentro del repositorio
# local y en clave del catálogo. Misma forma que un id de proyecto: existía la
# validación para las capacidades (`_CAPACIDAD`) y no para esto.
_ID_KIT = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# `dominio#verbo-objeto`. El dominio nombra el CONTRATO, nunca al proveedor:
# `notificar#enviar-mensaje`, no `telegram#enviar-mensaje`. Con el proveedor
# dentro del nombre, sustituirlo deja de ser posible — y poder sustituirlo es
# todo el motivo de que las capacidades existan.
_CAPACIDAD = re.compile(r"^[a-z0-9-]+#[a-z0-9-]+$")

MODOS = ("apuntador", "materializado", "copia")


class KitInvalido(Exception):
    """El manifiesto no cumple el contrato. Se dice qué falta, no «error»."""


# ───────────────────────── el manifiesto ─────────────────────────


@dataclass
class Aplicacion:
    """Un archivo del kit y dónde va en el consumidor."""

    origen: str
    destino: str
    modo: str = "apuntador"
    parametros: list[str] = field(default_factory=list)


@dataclass
class Kit:
    id: str
    version: str
    nombre: str = ""
    descripcion: str = ""
    expone: list[dict] = field(default_factory=list)
    consume: list[dict] = field(default_factory=list)
    binarios: list[str] = field(default_factory=list)
    aplica: list[Aplicacion] = field(default_factory=list)
    mantenimiento: dict = field(default_factory=dict)
    instalar: str = ""
    raiz: Path | None = None

    @property
    def de_maquina(self) -> bool:
        """No propaga archivos a ningún proyecto: instala algo en la máquina.

        Salió de migrar un kit real: ponía dos comandos en
        `~/.local/bin` y no tocaba ningún proyecto. Su `aplica:` está vacío con
        razón, y forzarle destinos habría sido inventar un consumidor que no
        existe. Un kit así se instala una vez por máquina, no una por proyecto.
        """
        return not self.aplica and bool(self.instalar)

    @property
    def capacidades_expuestas(self) -> list[str]:
        return [c["id"] for c in self.expone]

    def requiere(self, opcionales: bool = False) -> list[str]:
        """Capacidades que necesita. Sin opcionales, las que son obligatorias."""
        return [
            c["id"] for c in self.consume
            if opcionales or not c.get("opcional")
        ]


def leer_manifiesto(raiz: Path) -> Kit:
    """Lee `kit.yml` y valida el contrato.

    Se valida al leer y no al usar: un manifiesto roto descubierto a mitad de
    aplicar un kit deja el proyecto a medias, que es el peor momento posible.
    """
    ruta = Path(raiz) / "kit.yml"
    if not ruta.is_file():
        raise KitInvalido(f"no hay kit.yml en {raiz}")
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise KitInvalido(f"kit.yml no es YAML válido: {e}") from e
    if not isinstance(datos, dict):
        raise KitInvalido("kit.yml debe ser un mapa")

    id_ = str(datos.get("id") or "").strip()
    if not id_:
        raise KitInvalido("falta `id`: es cómo se resuelve el kit, y no puede faltar")
    if not _ID_KIT.match(id_):
        # El `id` acaba siendo nombre de carpeta en el repositorio local y clave
        # del catálogo: se le pide la misma forma que a un id de proyecto.
        raise KitInvalido(
            f"«{id_}» no sirve como `id`: minúsculas, números y guiones, "
            "empezando por letra o número. Es el nombre de su carpeta."
        )

    # 🔴 La versión se lee CRUDA para ver si venía entrecomillada. Sin comillas,
    # YAML convierte `1.10` en el número 1.1 y `str()` lo casa con el patrón sin
    # una queja: el kit se publica como `v1.10`, la carpeta se llama `1.10`, y
    # el hub trabaja con `1.1` — `resolver` devuelve None y el consumidor queda
    # irresoluble. Un cero que desaparece en silencio es justo lo que el resto
    # de este módulo existe para impedir.
    cruda = datos.get("version")
    if cruda is not None and not isinstance(cruda, str):
        raise KitInvalido(
            f"`version` tiene que ir entre comillas: `version: \"{cruda}\"`. "
            "Sin ellas YAML la lee como número y pierde los ceros finales "
            "(1.10 se convierte en 1.1)."
        )
    version = str(cruda or "").strip()
    if not _VERSION.match(version):
        raise KitInvalido(
            f"`version` debe ser major.minor (p. ej. 1.0); llegó «{version}»"
        )

    aplica = []
    for i, entrada in enumerate(datos.get("aplica") or [], 1):
        if not isinstance(entrada, dict):
            raise KitInvalido(f"`aplica[{i}]` debe ser un mapa")
        origen, destino = entrada.get("origen"), entrada.get("destino")
        if not origen or not destino:
            raise KitInvalido(f"`aplica[{i}]` necesita `origen` y `destino`")
        modo = entrada.get("modo", "apuntador")
        if modo not in MODOS:
            raise KitInvalido(
                f"`aplica[{i}].modo` = «{modo}»; los modos son {', '.join(MODOS)}"
            )
        # Un destino absoluto o con `..` escribiría fuera del proyecto. Un kit
        # puede venir de cualquier sitio: esto no es paranoia, es la puerta.
        #
        # 🔴 El `origen` necesita la MISMA guarda, y durante un tiempo no la tuvo:
        # sólo se vigilaba la salida. Un kit con `origen: ../../../.ssh/config` y
        # un destino inocente pasaba `verificar` en verde y copiaba la credencial
        # dentro de un repo que después se commitea. Peor todavía: el prompt que
        # se le da al agente lista el destino y NO el origen, así que quien
        # revisa el plan no tiene dónde verlo. Una puerta se cierra por los dos
        # lados o no está cerrada.
        rutas = {"origen": (str(origen), "kit"), "destino": (str(destino), "proyecto")}
        for campo, (valor, donde) in rutas.items():
            if valor.startswith("/") or ".." in Path(valor).parts:
                raise KitInvalido(
                    f"`aplica[{i}].{campo}` sale del {donde}: «{valor}». Debe ser relativo."
                )
        aplica.append(
            Aplicacion(
                origen=rutas["origen"][0], destino=rutas["destino"][0], modo=modo,
                parametros=list(entrada.get("parametros") or []),
            )
        )

    expone = list(datos.get("expone") or [])
    consume = list(datos.get("consume") or [])
    for lista, campo in ((expone, "expone"), (consume, "consume")):
        for entrada in lista:
            # 🔴 La forma corta —`- notificar#enviar-mensaje` en vez de
            # `- id: notificar#enviar-mensaje`— es el error que sale solo al
            # escribir un kit a mano, y reventaba con un `AttributeError`
            # desnudo desde dentro del parser. Esta clase existe para decir qué
            # falta, no «error»: sin esto, quien escribe su primer kit ve un
            # traceback del hub y no tiene forma de saber que le sobra un guion.
            if not isinstance(entrada, dict):
                raise KitInvalido(
                    f"`{campo}` trae «{entrada}» suelto. Cada capacidad va como"
                    f" `- id: dominio#verbo-objeto`, no como texto a secas."
                )
            cid = str(entrada.get("id") or "")
            if not _CAPACIDAD.match(cid):
                raise KitInvalido(
                    f"`{campo}` trae «{cid}»: una capacidad se nombra"
                    " `dominio#verbo-objeto`, en minúsculas y con guiones."
                )

    # Un instalador propio: el kit se pone en la máquina, no en un proyecto. Se
    # valida que exista, pero NO se ejecuta al instalar el kit — correr un script
    # de un repositorio ajeno sin permiso es justo lo que el hub no hace.
    instalar_ = str(datos.get("instalar") or "").strip()
    if instalar_:
        if instalar_.startswith("/") or ".." in Path(instalar_).parts:
            raise KitInvalido(f"`instalar` debe ser una ruta dentro del kit: «{instalar_}»")
        if not (Path(raiz) / instalar_).is_file():
            raise KitInvalido(f"`instalar` apunta a «{instalar_}», que no está en el kit")

    requiere = datos.get("requiere") or {}
    return Kit(
        id=id_,
        version=version,
        nombre=str(datos.get("nombre") or id_),
        descripcion=str(datos.get("descripcion") or ""),
        expone=expone,
        consume=consume,
        binarios=list(requiere.get("binarios") or []),
        aplica=aplica,
        mantenimiento=dict(datos.get("mantenimiento") or {}),
        instalar=instalar_,
        raiz=Path(raiz),
    )


# ───────────────────────── el repositorio local ─────────────────────────


def ruta_de(id_kit: str, version: str) -> Path:
    """Dónde vive un kit instalado.

    `<HUB_KITS>/<id>/<version>/`, con la versión EN LA RUTA, como
    `~/.m2/repository`. Con una sola carpeta por kit, el día que un proyecto se
    quede en 1.2 y otro pase a 2.0 habría que migrarlos a la vez.
    """
    return config.HUB_KITS / id_kit / version


def instalados() -> dict[str, list[str]]:
    """Qué kits hay en disco y en qué versiones, ordenadas."""
    encontrados: dict[str, list[str]] = {}
    if not config.HUB_KITS.is_dir():
        return encontrados
    for carpeta in sorted(config.HUB_KITS.iterdir()):
        if not carpeta.is_dir():
            continue
        versiones = sorted(
            (v.name for v in carpeta.iterdir() if v.is_dir() and _VERSION.match(v.name)),
            key=_orden_version,
        )
        if versiones:
            encontrados[carpeta.name] = versiones
    return encontrados


def version_mas_nueva(id_kit: str, declarada: str | None) -> str | None:
    """Una versión posterior a la que el consumidor declara, si la hay.

    Es lo que hacía falta para que `mantener-kit` fuera ejecutable: el
    procedimiento dice «aplica a cada consumidor, uno por uno» y no había
    ninguna forma de saber **cuáles** estaban atrasados. Se leía a mano el
    `.claude/hub/kits.yml` de cada proyecto.

    Se mira lo instalado y el catálogo a la vez: publicar la versión nueva y
    todavía no haberla instalado es el estado normal justo después de sacarla,
    y es cuando más interesa que el hub lo diga.

    Devuelve `None` si no hay nada más nuevo — o si la versión declarada no se
    puede comparar, porque inventarse un orden sería peor que callar.
    """
    if not declarada or not _VERSION.match(str(declarada)):
        return None
    candidatas = list(instalados().get(id_kit, []))
    del_catalogo = str((catalogo().get(id_kit) or {}).get("version") or "")
    if _VERSION.match(del_catalogo):
        candidatas.append(del_catalogo)
    if not candidatas:
        return None
    mayor = max(candidatas, key=_orden_version)
    return mayor if _orden_version(mayor) > _orden_version(str(declarada)) else None


def colisiones(manifiestos: list[Kit]) -> dict[str, list[str]]:
    """Destinos que más de un kit quiere escribir en el mismo proyecto.

    🔴 Sin esto el proyecto queda en un estado **imposible de arreglar**:
    aplicar un kit deja al otro en `difiere`, aplicar el otro deshace el
    primero, y el hub presenta las dos cosas como diagnósticos independientes.
    Quien lo vea sólo sabe que algo no cuadra, no que se están pisando.

    El diseño decía que «un único punto de composición ⇒ dos kits no pueden
    pelearse por el mismo destino», y es cierto **sólo para los `apuntador`**,
    que se componen en un bloque del `CLAUDE.md`. Los `materializado` y los
    `copia` son archivos de verdad, y ahí la colisión es posible.

    Se ignoran los `apuntador` justamente por eso: dos kits referenciados desde
    el mismo bloque no se estorban.
    """
    de_quien: dict[str, list[str]] = {}
    for kit in manifiestos:
        for a in kit.aplica:
            if a.modo == "apuntador":
                continue
            de_quien.setdefault(a.destino, []).append(kit.id)
    return {d: quienes for d, quienes in de_quien.items() if len(quienes) > 1}


def _orden_version(v: str) -> tuple[int, int]:
    mayor, _, menor = v.partition(".")
    return (int(mayor or 0), int(menor or 0))


def resolver(id_kit: str, version: str | None = None) -> Path | None:
    """La ruta de un kit instalado. Sin versión, la más alta que haya.

    Devuelve `None` si no está: que un kit no esté instalado es una respuesta,
    no un error — el hub lo dice y ofrece instalarlo.
    """
    versiones = instalados().get(id_kit)
    if not versiones:
        return None
    if version is None:
        return ruta_de(id_kit, versiones[-1])
    return ruta_de(id_kit, version) if version in versiones else None


def resolver_en_desarrollo(id_kit: str, proyectos: list) -> Path | None:
    """El kit que estás escribiendo, resuelto desde el registro de proyectos.

    Un kit declarado con `tipo: kit` se resuelve a su asiento sin pasar por el
    repositorio local. Es lo que permite editarlo y medir el efecto en el mismo
    minuto: obligar a publicar un tag y clonar para ver cada cambio haría el
    ciclo insoportable, y acabaría con alguien moviendo un tag ya publicado —
    que es lo único que no puede pasar.

    No es un SNAPSHOT encubierto: **se dice en voz alta** en cada salida, para
    que nadie confunda «el kit que estoy tocando» con «la versión 1.0».
    """
    for p in proyectos:
        if getattr(p, "tipo", None) == "kit" and p.id == id_kit and p.asiento:
            raiz = Path(p.asiento)
            if (raiz / "kit.yml").is_file():
                return raiz
    return None


def instalar(id_kit: str, version: str, origen: str) -> Path:
    """Clona el kit en el tag de su versión.

    Un tag publicado NO se mueve: si hay que cambiar algo, se publica `1.3`. Si
    un tag se reescribiera, todo lo que midió deriva contra él pasaría a mentir
    sin avisar — que es la regla dura 13 aplicada a los kits.
    """
    destino = ruta_de(id_kit, version)
    if destino.is_dir():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    orden = ["git", "clone", "--depth", "1", "--branch", f"v{version}", origen, str(destino)]
    r = subprocess.run(orden, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise KitInvalido(
            f"no se pudo obtener {id_kit} {version} de {origen}:\n{r.stderr.strip()}"
        )
    return destino


# ───────────────────────── el catálogo ─────────────────────────


def catalogo() -> dict[str, dict]:
    """Los kits declarados, fusionando el del repo con el del usuario.

    Gana el del usuario: así se añaden kits propios sin tocar el repo, que es la
    misma separación producto/datos que el registro de proyectos.
    """
    fusionado: dict[str, dict] = {}
    for ruta in (config.RAIZ_REPO / "kits.yml", config.HUB_HOME / "kits.yml"):
        if not ruta.is_file():
            continue
        try:
            datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for entrada in datos.get("kits") or []:
            if isinstance(entrada, dict) and entrada.get("id"):
                fusionado[entrada["id"]] = {**entrada, "declarado_en": str(ruta)}
    return fusionado


# ───────────────────────── el registro del consumidor ─────────────────────────


def carpeta_base(raices: list[str]) -> Path | None:
    """Dónde está el `.claude/hub/` de un proyecto, si lo tiene."""
    for base in raices:
        carpeta = Path(base) / ".claude" / "hub"
        if carpeta.is_dir():
            return carpeta
    return None


def raiz_de(raices: list[str]) -> Path | None:
    """Contra qué carpeta se miden los destinos de un kit.

    Un proyecto puede tener varias rutas —se han medido seis en uno solo, que se
    orquesta desde una carpeta y tiene el código en otras cuatro—, y la primera de
    la lista no tiene por qué ser donde se aplican los kits. Manda la que tenga
    `.claude/hub/`; sólo si ninguna la tiene se cae a la primera.

    Medirlo contra la primera a secas daba «falta» en los tres archivos de la
    capa base **con los tres archivos escritos y en su sitio**: la cifra estaba
    mal, no el proyecto.
    """
    if not raices:
        return None
    carpeta = carpeta_base(raices)
    return carpeta.parent.parent if carpeta else Path(raices[0])


def kits_declarados(raices: list[str]) -> list[dict]:
    """Qué kits dice tener el proyecto, según su propio registro.

    La declaración vive en el consumidor y no en el kit: un kit no puede llevar
    el censo de los proyectos de otra persona, y sin invertir esto los kits sólo
    funcionan mientras el único usuario sea quien los escribe.
    """
    carpeta = carpeta_base(raices)
    if not carpeta:
        return []
    ruta = carpeta / "kits.yml"
    if not ruta.is_file():
        return []
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return [k for k in (datos.get("kits") or []) if isinstance(k, dict) and k.get("id")]


# ───────────────────────── la medición ─────────────────────────


def _hash(ruta: Path) -> str | None:
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except OSError:
        return None


# El bloque que la skill `aplicar-kit` manda escribir en el `CLAUDE.md` del
# consumidor. Es el ÚNICO punto de composición: por eso dos kits no se pelean
# por el mismo destino con los apuntadores.
MARCA_BLOQUE = "<!-- kits — generado, no editar a mano -->"

# Cuántas líneas de cabecera se toleran al principio de un `materializado`.
# Suficiente para un comentario de varias líneas; corto para que una diferencia
# de verdad al principio del archivo no se cuele como si fuera cabecera.
# 🔴 Doce y no seis. En una skill la cabecera NO puede ir la primera —`---` tiene
# que abrir el archivo o el frontmatter no parsea— así que va detrás de él, y un
# frontmatter con `name`, `description` larga y algún campo más ya empuja la
# cabecera más allá de la sexta línea. Cuando eso pasa no falla nada visible:
# el archivo se queda en `difiere` para siempre y nadie sabe por qué.
_LINEAS_CABECERA = 12


def _sin_cabecera(texto: str, kit_id: str) -> str:
    """El contenido de un `materializado`, sin la cabecera que la skill obliga.

    🔴 Sin esto, seguir el procedimiento producía deriva permanente. La skill
    `aplicar-kit` **obliga** a copiar cada `materializado` con una cabecera «del
    kit X vN — no editar aquí» —y el prompt que genera el propio hub la repite—
    mientras la medición comparaba los bytes del origen con los del destino. El
    destino tenía una línea más, así que salía `difiere` para siempre; ponerlo
    en verde exigía desobedecer la skill.

    Es el mismo defecto que se arregló para `apuntador`, en la rama de al lado,
    y no se replicó aquí. `materializado` es el modo de las skills, los agentes
    y los hooks: el contenido más habitual de un kit.

    Se busca la marca en las primeras líneas y se corta ahí, en vez de exigir un
    formato exacto, porque la cabecera la escribe un agente en el lenguaje de
    comentario que toque —`#`, `<!-- -->`, `//`— y fijar la sintaxis obligaría a
    conocer de antemano todos los tipos de archivo que un kit puede propagar.
    """
    lineas = texto.splitlines(keepends=True)
    ultima = -1
    for i, linea in enumerate(lineas[:_LINEAS_CABECERA]):
        if f"del kit {kit_id}" in linea or f"kit `{kit_id}`" in linea:
            ultima = i
    if ultima < 0:
        return texto

    # 🔴 Se quita LA CABECERA, no todo lo que hay antes de ella. Devolver
    # `lineas[ultima+1:]` daba por bueno el caso en que la cabecera abre el
    # archivo y rompía el que de verdad importa: **una skill**. Un `SKILL.md`
    # necesita `---` en su PRIMERA línea o el frontmatter no parsea y la skill
    # deja de existir para quien la busca, así que la cabecera tiene que ir
    # detrás del frontmatter — y entonces el recorte se llevaba el frontmatter
    # entero del destino, dejándolo distinto del origen para siempre. `difiere`
    # eterno en el modo que existe precisamente para skills, agentes y hooks.
    #
    # Con la cabecera al principio el resultado es idéntico al de antes, así que
    # esto no cambia nada de lo que ya estaba medido.
    antes = lineas[:ultima]
    resto = lineas[ultima + 1:]
    while resto and not resto[0].strip():          # y la línea en blanco que la separa
        resto = resto[1:]
    return "".join(antes + resto)


def _mismo_contenido(origen: Path, destino: Path, kit: Kit) -> bool:
    """Iguales salvo la cabecera generada. Compara bytes si no son texto."""
    try:
        texto_destino = destino.read_text(encoding="utf-8")
        texto_origen = origen.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Binarios, o un archivo ilegible: se cae al hash de siempre.
        return _hash(origen) == _hash(destino)

    limpio = _sin_cabecera(texto_destino, kit.id)
    if limpio == _sin_cabecera(texto_origen, kit.id):
        return True

    # 🔴 Y si sólo baila el espaciado ALREDEDOR de donde estaba la cabecera, es
    # el mismo archivo.
    #
    # `_sin_cabecera` se lleva la cabecera y las líneas en blanco que la siguen,
    # pero el origen conserva las suyas: si el contenido empezaba con una blanca
    # justo donde se insertó la cabecera —el caso de una skill, que es
    # `---` + frontmatter + `---` + blanca + título—, el destino se quedaba con
    # una línea menos y salía `difiere` PARA SIEMPRE.
    #
    # Dependía de un detalle invisible: poner la cabecera pegada al `---` o
    # después de la blanca daba resultados distintos, y ninguna instrucción lo
    # decía. Medido el 2026-09-03 sobre dos consumidores del mismo kit: el que
    # la puso tras la blanca salía al día y el que la pegó al `---`, en rojo.
    #
    # Se relaja SÓLO cuando había cabecera —si no la hay, la comparación sigue
    # siendo exacta al byte— y sólo en líneas vacías: cualquier cambio de
    # contenido real sigue saliendo.
    if limpio == texto_destino:
        return False        # no había cabecera: nada que perdonar
    return _sin_vacias(limpio) == _sin_vacias(texto_origen)


def _sin_vacias(texto: str) -> list[str]:
    return [l for l in texto.splitlines() if l.strip()]


def _apunta_al_kit(raiz_proyecto: Path | None, kit: Kit) -> bool:
    """¿El `CLAUDE.md` del proyecto referencia este kit?

    Es lo que significa «tener aplicado un apuntador»: no que exista un archivo
    copiado, sino que el proyecto declare que usa el kit y sepa dónde buscarlo.

    Se busca el id dentro del bloque generado y no en todo el archivo, porque
    `CLAUDE.md` puede nombrar un kit de pasada —«esto lo hereda de
    orquestacion»— y eso no es haberlo aplicado.
    """
    if raiz_proyecto is None:
        return False
    try:
        texto = (raiz_proyecto / "CLAUDE.md").read_text(encoding="utf-8")
    except OSError:
        return False

    # 🔴 El marcador se busca de forma TOLERANTE, no byte a byte. La primera
    # versión exigía la cadena exacta —con su raya larga `—` y su coma—, así que
    # escribir un guion normal daba `falta`, y quien lo hubiera aplicado bien
    # veía deriva sin entender por qué. Lo que identifica al bloque es que sea
    # un comentario HTML que hable de kits generados.
    marca = re.search(r"<!--\s*kits\b[^>]*-->", texto, re.IGNORECASE)
    if not marca:
        return False

    # 🔴 Y el bloque llega hasta el final del comentario o hasta el siguiente
    # encabezado, no hasta la primera línea en blanco: una línea en blanco tras
    # el marcador —o una lista markdown de varios párrafos, que es como lo
    # escribe un agente— cortaba el bloque en vacío y devolvía `falta`.
    resto = texto[marca.end():]
    bloque = re.split(r"\n#{1,6}\s|\n<!--", resto, maxsplit=1)[0]

    # `\b` trata el guion como frontera, así que `telegram` casaba dentro de
    # `notificar-telegram` y un kit salía aplicado por el nombre de otro. Se
    # exige que el id no esté pegado a más letras, dígitos, guiones ni guiones
    # bajos por ninguno de los dos lados.
    return re.search(
        rf"(?<![\w-]){re.escape(kit.id)}(?![\w-])", bloque
    ) is not None


def medir(raices: list[str], kit: Kit, declarado: dict | None = None) -> list[dict]:
    """Compara lo que el kit puso con lo que hay hoy en el proyecto.

    Cada modo se mide con la vara que le corresponde, y esto no es una renuncia:

    * `apuntador` y `materializado` — por contenido. Nadie debería editarlos allí.
    * `copia` — **por procedencia**, nunca por contenido. Una plantilla de agente
      existe para divergir; compararla byte a byte marcaría como defecto justo lo
      que se esperaba que pasara, y una señal que se enciende siempre se aprende
      a ignorar.
    """
    raiz_proyecto = raiz_de(raices)
    resultado = []
    version_aplicada = (declarado or {}).get("version")

    # Lo que este consumidor decidió no heredar, o heredar distinto, **con su
    # motivo escrito**. Una divergencia sin declarar es un defecto; declarada, es
    # una decisión — y sin esto, migrar un kit con excepciones reales las
    # convertiría todas en defectos aparentes, que es la forma más rápida de que
    # una medición deje de mirarse.
    excepciones = (declarado or {}).get("excepciones") or {}

    for a in kit.aplica:
        origen = (kit.raiz / a.origen) if kit.raiz else None
        destino = (raiz_proyecto / a.destino) if raiz_proyecto else None

        if a.destino in excepciones:
            estado = "declarada"
        elif a.modo == "apuntador" and _apunta_al_kit(raiz_proyecto, kit):
            # 🔴 Un `apuntador` NO se copia: el contenido vive en el kit y el
            # proyecto lo referencia desde su `CLAUDE.md`. Eso es lo que manda
            # la skill —«NO copies el archivo»— y lo que dice el prompt que el
            # propio hub genera.
            #
            # Y era exactamente lo que la medición contaba como error: al no
            # existir el archivo en el consumidor, salía `falta`. Seguir el
            # procedimiento producía deriva permanente e irreparable, y ponerlo
            # en verde exigía duplicar el contenido — el error que este modo
            # existe para impedir. El único modo pensado para «una sola verdad»
            # era el único que la medición no sabía reconocer.
            estado = "apuntado"
        elif destino is None or not destino.exists():
            estado = "falta"
        elif a.modo == "copia":
            # Se compara de qué versión salió, no su contenido.
            estado = "al-dia" if version_aplicada == kit.version else "origen-cambiado"
        elif origen is None or not origen.is_file():
            # `is_file()` y no `exists()`: un `origen` que apunta a una CARPETA
            # existe, y con `exists()` seguía adelante hasta `_hash`, que se
            # tragaba el `IsADirectoryError` —es un `OSError`— y devolvía None
            # en los dos lados. `None == None` daba «igual»: verde eterno sobre
            # algo que no se estaba midiendo. «Quiero propagar una carpeta
            # entera» es un error de novato natural, y el hub lo aplaudía.
            estado = "sin-origen"
        else:
            estado = "igual" if _mismo_contenido(origen, destino, kit) else "difiere"

        resultado.append({
            "kit_id": kit.id, "origen": a.origen, "destino": a.destino,
            "modo": a.modo, "estado": estado,
            "motivo": excepciones.get(a.destino, ""),
        })
    return resultado


def huerfanos(raices: list[str], kit: Kit, declarado: dict) -> list[str]:
    """Archivos que puso una versión anterior y la actual ya no pone.

    Quitar una dependencia en Maven limpia el classpath y ya; aquí los archivos
    se quedan dentro del repo. Sin esto, el proyecto acumula basura y la deriva
    empieza a medir contra cosas que ya no respalda nadie.

    No se borra nada: se dice qué quedó suelto. Borrar dentro del repo de alguien
    sigue siendo del agente, con el humano mirando.
    """
    puestos = set(declarado.get("destinos") or [])
    actuales = {a.destino for a in kit.aplica}
    raiz = raiz_de(raices)
    sobran = sorted(puestos - actuales)
    if raiz is None:
        return sobran
    return [d for d in sobran if (raiz / d).exists()]


# ───────────────────────── capacidades ─────────────────────────


def resolver_capacidades(kits: list[Kit]) -> dict:
    """Quién provee qué, y qué se pide sin que nadie lo provea.

    La dependencia es de la CAPACIDAD, no del kit: el de orquestación no depende
    de «telegram», depende de «algo que sepa enviar un mensaje». El día que sea
    Slack, se escribe otro kit que exponga el mismo contrato y nadie más cambia.

    Lo que falta se dice **en voz alta**. Una capacidad ausente y callada es un
    instrumento en verde que nadie ha visto funcionar.
    """
    proveedores: dict[str, list[str]] = {}
    for k in kits:
        for cid in k.capacidades_expuestas:
            proveedores.setdefault(cid, []).append(k.id)

    faltan, degradados = [], []
    for k in kits:
        for c in k.consume:
            cid = c["id"]
            if cid in proveedores:
                continue
            (degradados if c.get("opcional") else faltan).append(
                {"kit_id": k.id, "capacidad": cid}
            )
    return {"proveedores": proveedores, "faltan": faltan, "degradados": degradados}


# ───────────────────────── el plan de aplicación ─────────────────────────


def plan_de_aplicacion(raices: list[str], kit: Kit, declarado: dict | None = None) -> dict:
    """Qué haría falta hacer para que el proyecto tenga este kit al día.

    El hub calcula y propone; **no escribe**. Escribir dentro de un proyecto
    ajeno es lo que la primera regla del hub prohíbe, y lo hace un agente que
    corre en ese repo.
    """
    medido = medir(raices, kit, declarado)
    return {
        "kit": kit.id,
        "version": kit.version,
        "version_aplicada": (declarado or {}).get("version"),
        "archivos": medido,
        "pendientes": [m for m in medido if m["estado"] in ("falta", "difiere")],
        "huerfanos": huerfanos(raices, kit, declarado) if declarado else [],
        "binarios_ausentes": [b for b in kit.binarios if not _hay_binario(b)],
    }


def _hay_binario(nombre: str) -> bool:
    import shutil

    # `shutil.which` y no `command -v`: éste resuelve también alias y funciones
    # del shell, que no existen para un subproceso. Ya pasó con `rg`.
    return shutil.which(nombre) is not None


def prompt_aplicar(proyecto_nombre: str, raiz: str, kit: Kit, plan: dict) -> str:
    """La propuesta editable que ejecuta el agente dentro del proyecto."""
    lineas = [
        f"Aplica el kit `{kit.id}` v{kit.version} al proyecto {proyecto_nombre} (`{raiz}`).",
        "",
        "Archivos, con lo que hay que hacer en cada uno:",
    ]
    for a in plan["archivos"]:
        que = {
            "falta": "crear",
            "difiere": "actualizar (revisa antes si el cambio local era a propósito)",
            "igual": "nada, está al día",
            "apuntado": "nada: el proyecto ya lo referencia y NO debe copiarse",
            "al-dia": "nada, salió de esta misma versión",
            "origen-cambiado": "el kit cambió de versión; es una copia, decide tú si la rehaces",
            "sin-origen": "🔴 el kit ya no trae ese archivo",
            "declarada": "**no tocar**: este proyecto lo declaró como excepción",
        }[a["estado"]]
        lineas.append(f"- `{a['destino']}` ({a['modo']}) — {que}")
        if a.get("motivo"):
            lineas.append(f"    motivo declarado: {a['motivo']}")

    if plan["huerfanos"]:
        lineas += [
            "",
            "Sobran de una versión anterior (NO los borres sin preguntar):",
            *(f"- `{h}`" for h in plan["huerfanos"]),
        ]
    if plan["binarios_ausentes"]:
        lineas += [
            "",
            f"⚠️ El kit necesita: {', '.join(plan['binarios_ausentes'])} — no están en el PATH.",
        ]

    lineas += [
        "",
        "Al terminar, actualiza `.claude/hub/kits.yml` del proyecto con el `id`, la",
        f"`version` (`{kit.version}`), la fecha y la lista de `destinos` escritos.",
        "",
        "Reglas:",
        "- Lo marcado `apuntador` NO se copia: el contenido vive en el kit y el",
        "  proyecto sólo lo referencia. Una sola verdad.",
        "- Lo `materializado` sí se copia, con cabecera «del kit"
        f" {kit.id} v{kit.version} — no editar aquí».",
        "- Lo `copia` es semilla: se personaliza, y divergir es lo correcto.",
        "- Si algo difiere y el cambio local era deliberado, **decláralo** en vez de",
        "  pisarlo. Una divergencia sin declarar es un defecto; declarada, es una decisión.",
    ]
    return "\n".join(lineas)
