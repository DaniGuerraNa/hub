"""Registro de proyectos.

`projects.yml` es la fuente de verdad de qué proyectos existen (decisión 7): un
archivo editable a mano, para que un problema se arregle con un editor de texto y
no con una consulta SQL. La base sólo lo indexa.

Sin descubrimiento automático (decisión 8): los proyectos son fijos y los nuevos
se registran al crearse.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import sqlite3
import tempfile
from pathlib import Path

import yaml

from . import config
from .models import Conexion, Proyecto, Ruta


@contextlib.contextmanager
def _en_exclusiva(ruta: Path):
    """Una sola escritura del registro a la vez, en toda la máquina.

    🔴 Medido, no supuesto: con ocho altas simultáneas el `projects.yml` acabó
    **ilegible** —una línea `l` suelta, resto de «personal» truncado a medias—
    porque cada hilo leía el archivo, le añadía su bloque y lo reescribía
    entero, pisándose unos a otros. La comprobación de duplicados que hay más
    abajo no protegía de nada: entre leer y escribir no había cerrojo.

    Y no hacen falta dos personas para provocarlo. El snapshotter lee este
    archivo cada 20 s mientras la web lo reescribe.

    El cerrojo es de fichero (`flock`) y no un `threading.Lock` porque los que
    compiten son **procesos distintos** —web y snapshotter—, no dos hilos.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cerrojo = ruta.with_name(ruta.name + ".lock")
    with open(cerrojo, "w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            _barrer_temporales(ruta)
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _barrer_temporales(ruta: Path) -> None:
    """Restos de escrituras que no llegaron a terminar.

    Un `SIGKILL` o un corte de luz entre el `write` y el `os.replace` deja un
    `.tmp` que nadie recoge. Se midió: 40 muertes a mitad de escritura dejaron
    38 huérfanos. No rompen nada, pero se acumulan en el directorio que el
    usuario abre con un editor para tocar su registro a mano — y basura ahí
    hace dudar de cuál es el archivo bueno.

    Se barre **bajo el cerrojo**, que es lo que lo hace seguro: aquí no hay
    ninguna escritura en curso con la que competir.
    """
    for resto in ruta.parent.glob(f"{ruta.name}.*.tmp"):
        with contextlib.suppress(OSError):
            resto.unlink()


def _escribir_atomico(ruta: Path, texto: str) -> None:
    """Escribe entero o no escribe: nunca deja el registro a medias.

    `write_text` trunca el archivo y *después* escribe, así que cualquier lector
    que llegue en ese hueco ve un archivo vacío o cortado. Se midió: 104 de 230
    lecturas concurrentes vieron CERO proyectos — y una lectura vacía dispara
    los `DELETE FROM` de respaldo, inventario y conexiones.

    Con `os.replace` el cambio es atómico a nivel de inode: quien lea verá la
    versión vieja completa o la nueva completa. Nunca un trozo de cada. El
    `fsync` es lo que hace que un corte de luz tampoco lo rompa.
    """
    # Si es un enlace simbólico se escribe sobre su DESTINO, no sobre el enlace:
    # `os.replace` lo sustituiría por un fichero normal y el archivo real —al
    # que alguien apuntó a propósito— dejaría de recibir las altas sin que nada
    # lo dijera.
    destino = ruta.resolve() if ruta.is_symlink() else ruta

    # El modo previo se conserva. `NamedTemporaryFile` crea con 0600, así que
    # sin esto cada alta cambiaba un `projects.yml` de 0644 a 0600 en silencio.
    try:
        modo = destino.stat().st_mode & 0o777
    except OSError:
        modo = 0o644

    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=destino.parent,
        prefix=destino.name + ".", suffix=".tmp", delete=False,
    )
    try:
        tmp.write(texto)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.chmod(tmp.name, modo)
        os.replace(tmp.name, destino)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)
        raise


class _SinDuplicados(yaml.SafeLoader):
    """YAML que se queja si una clave aparece dos veces.

    🔴 Por defecto PyYAML se queda con la última y no dice nada. En un registro
    editado a mano —copiar un bloque, pegarlo abajo y olvidar borrar la línea
    `proyectos:`— eso significa **perder medio registro en silencio**: los
    proyectos del primer bloque desaparecen del hub, y con ellos sus slots y sus
    notas dejan de verse. Es la misma pérdida callada que ya se cerró para los
    ids repetidos, por otra puerta.
    """


def _mapa_sin_duplicados(loader, nodo, deep=False):
    visto = set()
    for clave, _ in nodo.value:
        k = loader.construct_object(clave, deep=deep)
        if k in visto:
            raise yaml.constructor.ConstructorError(
                None, None,
                f"la clave «{k}» está dos veces; el segundo bloque haría "
                "desaparecer al primero sin avisar",
                clave.start_mark,
            )
        visto.add(k)
    return yaml.SafeLoader.construct_mapping(loader, nodo, deep)


_SinDuplicados.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapa_sin_duplicados
)


def _leer(ruta: Path | None) -> dict:
    ruta = ruta or config.projects_yml()
    if not ruta.exists():
        return {}
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # 🔴 Un editor de Windows guarda en latin-1 sin avisar, y este registro
        # lleva nombres con tildes. `UnicodeDecodeError` es `ValueError`, no
        # `YAMLError`, así que se escapaba y salía como 500 desnudo — el mismo
        # síntoma que todo esto vino a quitar.
        raise YamlInvalido(
            f"`{ruta}` no está guardado en UTF-8, así que no se puede leer.\n\n"
            "Vuelve a guardarlo con codificación UTF-8 (en VS Code, abajo a la "
            f"derecha: «Guardar con codificación»).\n\nDetalle: {exc}"
        ) from exc
    except OSError as exc:
        raise YamlInvalido(f"No se puede leer `{ruta}`: {exc}") from exc

    try:
        return yaml.load(crudo, _SinDuplicados) or {}
    except yaml.YAMLError as exc:
        # Con la línea y la columna que trae PyYAML: es lo único que sirve para
        # arreglar un archivo que se edita a mano.
        raise YamlInvalido(f"`{ruta}` no es YAML válido.\n\n{exc}") from exc


def cargar(ruta: Path | None = None) -> list[Proyecto]:
    """Los proyectos declarados, o `YamlInvalido` diciendo qué está mal.

    🔴 Todo error de formato sale por `YamlInvalido` y ninguno como `KeyError`,
    `TypeError` o `AttributeError` crudos. La diferencia se midió: de 20
    variantes de `projects.yml` roto, **9 producían un 500 desnudo** en las
    acciones que releen el archivo, mientras las demás pantallas seguían en 200
    enseñando datos viejos. El usuario veía «Internal Server Error» sin saber
    qué línea de su archivo lo causaba — y este archivo se edita a mano a
    propósito (decisión 7), así que equivocarse al escribirlo es lo normal, no
    un caso raro.
    """
    datos = _leer(ruta)
    if not isinstance(datos, dict):
        raise YamlInvalido(
            "`projects.yml` debe empezar por `proyectos:` con la lista debajo."
        )
    crudos = datos.get("proyectos") or []
    if not isinstance(crudos, list):
        raise YamlInvalido("`proyectos:` tiene que ser una lista.")

    proyectos = []
    for i, crudo in enumerate(crudos, 1):
        if not isinstance(crudo, dict):
            raise YamlInvalido(
                f"El proyecto nº{i} no es un bloque de campos: «{crudo}». "
                "Cada uno empieza por `- id:`."
            )
        if not crudo.get("id"):
            raise YamlInvalido(
                f"El proyecto nº{i} no tiene `id`, y el id es su identidad."
            )
        id_ = str(crudo["id"])
        declaradas = crudo.get("rutas") or []
        if isinstance(declaradas, str):
            # 🔴 `rutas: /home/x/dev/mio` en vez de una lista. Python itera la
            # CADENA carácter a carácter, así que salían 18 «rutas» de un
            # carácter —incluida la vacía— y con una ruta vacía el `Atribuidor`
            # le adjudicaba a ese proyecto TODOS los paneles de la máquina. Una
            # coma que falta y el inventario entero pasa a ser de un proyecto.
            raise YamlInvalido(
                f"Las `rutas` de «{id_}» son una lista, aunque sólo haya una:\n\n"
                f"    rutas:\n      - ruta: {declaradas}"
            )
        if not isinstance(declaradas, list):
            raise YamlInvalido(f"Las `rutas` de «{id_}» tienen que ser una lista.")
        asiento = _normalizar(str(crudo["asiento"])) if crudo.get("asiento") else None
        try:
            rutas: list[Ruta] = []
            for r in declaradas:
                if isinstance(r, dict) and "patron" in r:
                    rutas.extend(_expandir_patron(asiento, str(r["patron"]), id_))
                elif isinstance(r, dict):
                    rutas.append(Ruta(ruta=_normalizar(r["ruta"]), tipo=r.get("tipo", "repo")))
                else:
                    rutas.append(Ruta(ruta=_normalizar(str(r))))
        except (KeyError, TypeError) as exc:
            raise YamlInvalido(
                f"Las `rutas` de «{id_}» están mal: cada una es una ruta, un "
                f"bloque con `ruta:` o un bloque con `patron:`. ({exc})"
            ) from exc
        try:
            proyectos.append(
                Proyecto(
                    id=id_,
                    nombre=str(crudo.get("nombre", id_)),
                    dominio=crudo.get("dominio", "personal"),
                    tipo=crudo.get("tipo", "proyecto"),
                    asiento=asiento,
                    rutas=rutas,
                    estado_ref=crudo.get("estado_ref"),
                    base_version=crudo.get("base_version"),
                    guardrail=crudo.get("guardrail", "ask"),
                    status=crudo.get("status", "activo"),
                    nota=crudo.get("nota", ""),
                    contenedores=[str(c) for c in crudo.get("contenedores", []) or []],
                )
            )
        except Exception as exc:  # pydantic y cía.
            raise YamlInvalido(f"El proyecto «{id_}» no es válido: {exc}") from exc

    repetidos = {p.id for p in proyectos if [x.id for x in proyectos].count(p.id) > 1}
    if repetidos:
        # Antes ganaba el último y los demás desaparecían sin decir nada. Un id
        # es la identidad de la que cuelgan slots, notas e índice: perder uno en
        # silencio es perder sus notas.
        raise YamlInvalido(
            f"Hay más de un proyecto con el mismo id: {', '.join(sorted(repetidos))}."
        )
    return proyectos


def cargar_conexiones(ruta: Path | None = None) -> list[Conexion]:
    """Conexiones declaradas en el mismo `projects.yml`, bajo `conexiones:`.

    Van en el mismo archivo a propósito: son pocas y separarlas crearía un
    segundo sitio que recordar, que es el problema que el hub existe para
    resolver. Nunca llevan el secreto, sólo un puntero (decisión 28).
    """
    from .conexiones import revisar_secretos

    cargadas = []
    for crudo in _leer(ruta).get("conexiones", []) or []:
        # Si alguien pegó una contraseña "temporalmente", se dice en voz alta y
        # el campo se ignora. Guardarla en silencio sería exactamente lo que la
        # decisión 28 existe para impedir.
        sospechosos = revisar_secretos(crudo)
        if sospechosos:
            print(
                f"[registry] «{crudo.get('alias')}» trae {', '.join(sospechosos)} en "
                f"projects.yml. El hub NO guarda secretos: se ignoran. Deja sólo un "
                f"puntero en `referencia_secreto`.",
                flush=True,
            )
        cargadas.append(
            Conexion(
                alias=crudo["alias"],
                host=crudo.get("host"),
                usuario=crudo.get("usuario"),
                proposito=crudo.get("proposito", ""),
                proyectos=[str(p) for p in crudo.get("proyectos", []) or []],
                referencia_secreto=crudo.get("referencia_secreto"),
                nota=crudo.get("nota", ""),
            )
        )
    return cargadas


class YamlInvalido(RuntimeError):
    """El registro no se puede usar, y el mensaje dice por qué.

    Vale para las dos direcciones: al ESCRIBIR («el archivo quedaría roto: no se
    escribe nada») y al LEER, que es lo que se añadió después de ver que 9 de 20
    variantes de `projects.yml` mal escrito salían como `KeyError` o `TypeError`
    crudos y acababan en un 500 sin texto.

    El mensaje es la mitad del valor: este archivo se edita a mano a propósito,
    así que hay que decir qué proyecto y qué campo, no sólo que algo falla.
    """


def añadir_conexion(datos: dict, ruta: Path | None = None) -> None:
    """Añade una conexión a `projects.yml` sin reescribir el archivo.

    Escribe TEXTO, no un volcado de YAML. `safe_dump` del documento entero
    devolvería un archivo equivalente pero distinto: sin comentarios, sin el
    orden en que están las cosas y con las comillas que le apetezcan. Y este
    archivo es la fuente de verdad *editable a mano* (decisión 7) — su formato
    es parte de lo que lo hace editable. Así que se inserta un bloque y lo demás
    se queda exactamente como estaba.

    Nunca escribe un secreto (decisión 28): los campos sospechosos se descartan
    aquí, igual que al leer. Un formulario que aceptara una contraseña «sólo por
    esta vez» convertiría el índice en un almacén de credenciales.
    """
    alias = (datos.get("alias") or "").strip()
    if not alias:
        raise YamlInvalido("La conexión necesita un alias.")

    ruta = ruta or config.projects_yml()
    actual = _leer(ruta)
    if any(c.get("alias") == alias for c in (actual.get("conexiones") or [])):
        raise YamlInvalido(f"Ya existe una conexión con el alias «{alias}».")

    # Sólo estos campos, y en este orden. Una lista blanca y no `datos` entero:
    # así un campo nuevo en el formulario no puede acabar en el archivo sin que
    # alguien lo haya decidido aquí.
    campos = ["alias", "host", "usuario", "proposito", "referencia_secreto", "nota"]
    limpio = {k: (datos.get(k) or "").strip() for k in campos}
    limpio = {k: v for k, v in limpio.items() if v}
    limpio["alias"] = alias
    proyectos = [p.strip() for p in (datos.get("proyectos") or []) if p.strip()]

    # No hace falta pasar `revisar_secretos` sobre esto: la lista blanca de
    # arriba ya hace imposible que llegue un campo con nombre de credencial. La
    # comprobación sigue viva donde sí puede pasar — al LEER el archivo, que
    # alguien edita a mano.
    if proyectos:
        limpio["proyectos"] = proyectos

    _insertar(ruta, "conexiones", limpio, "alias", alias,
              duplicado=f"Ya existe una conexión con el alias «{alias}».")


def añadir_proyecto(datos: dict, ruta: Path | None = None) -> None:
    """Da de alta un proyecto en `projects.yml`, con el mismo cuidado.

    El alta la hace el HUB y no el agente que crea el proyecto, y no es un
    reparto arbitrario: `projects.yml` es el registro del hub —suyo, no de nadie
    más—, mientras que el contenido del proyecto es del proyecto. Dejárselo al
    agente obligaría a darle permiso de escritura fuera de la carpeta que se le
    acota, y ese permiso es justo lo que no queremos conceder.
    """
    id_ = (datos.get("id") or "").strip()
    if not id_:
        raise YamlInvalido("El proyecto necesita un `id`.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", id_):
        raise YamlInvalido(
            f"«{id_}» no sirve como id: minúsculas, números y guiones, y empieza"
            " por letra o número. El id no se puede cambiar después."
        )

    ruta = ruta or config.projects_yml()
    actual = _leer(ruta)
    if any(str(p.get("id") or "") == id_ for p in (actual.get("proyectos") or [])):
        raise YamlInvalido(f"Ya hay un proyecto con el id «{id_}».")

    # `tipo` está en la lista porque un kit se da de alta por aquí igual que un
    # proyecto, y sin él nacía como `proyecto`: el hub lo medía, pero no salía en
    # la vista de kits ni el CLI lo reconocía como tal. Los vacíos se filtran
    # justo debajo, así que un alta que no lo traiga sigue sin escribirlo.
    campos = ["id", "nombre", "tipo", "dominio", "asiento", "estado_ref",
              "guardrail", "status", "nota"]
    limpio = {k: str(datos.get(k) or "").strip() for k in campos}
    limpio = {k: v for k, v in limpio.items() if v}
    limpio["id"] = id_

    # `rutas` va aparte porque es una LISTA y no un escalar, y porque su forma
    # —`- ruta: …`— es la que lee `cargar()`. Sin esto, un proyecto cuyo código
    # vive fuera del asiento sólo se podía declarar editando el YAML a mano: el
    # caso de quien orquesta desde una carpeta y tiene los repos en otras, que
    # es exactamente el que no puede tocar esos repos.
    rutas = datos.get("rutas") or []
    if isinstance(rutas, str):
        raise YamlInvalido(
            f"Las `rutas` de «{id_}» son una lista, aunque sólo haya una:\n\n"
            f"    rutas:\n      - ruta: {rutas}"
        )
    limpias = [str(r).strip() for r in rutas if str(r).strip()]
    if limpias:
        limpio["rutas"] = [{"ruta": r} for r in limpias]

    _insertar(ruta, "proyectos", limpio, "id", id_,
              duplicado=f"Ya hay un proyecto con el id «{id_}».")


def _insertar(
    ruta: Path, seccion: str, limpio: dict, clave: str, valor: str,
    duplicado: str = "",
) -> None:
    """Un alta en el registro, serializada y atómica.

    El cerrojo envuelve **leer y escribir**, no sólo escribir: el defecto era el
    hueco entre las dos cosas.

    Por eso la comprobación de duplicados se repite AQUÍ aunque quien llama ya
    la haya hecho. La de fuera del cerrojo da un mensaje rápido y no decide
    nada: entre que mira y escribe, otro puede haber escrito. Se midió — dos
    altas del mismo id decían las dos que sí, y sólo quedaba una.
    """
    with _en_exclusiva(ruta):
        if duplicado:
            actual = _leer(ruta)
            if any(
                str(x.get(clave) or "") == valor for x in (actual.get(seccion) or [])
            ):
                raise YamlInvalido(duplicado)
        _insertar_bajo_cerrojo(ruta, seccion, limpio, clave, valor)


def _insertar_bajo_cerrojo(
    ruta: Path, seccion: str, limpio: dict, clave: str, valor: str
) -> None:
    """Mete un bloque en una sección de `projects.yml` sin tocar lo demás.

    Escribe TEXTO, no un volcado de YAML: `safe_dump` del documento entero
    devolvería un archivo equivalente pero distinto —sin comentarios, sin el
    orden en que están las cosas y con las comillas que le apetezcan—, y este
    archivo es la fuente de verdad *editable a mano* (decisión 7). Su formato es
    parte de lo que lo hace editable.
    """
    # El bloque lo serializa PyYAML y aquí sólo se le pone la sangría. Escribir
    # `f"{k}: {v}"` a mano parecía más simple y no lo es: un valor con dos
    # puntos, o una nota con una almohadilla, rompen el archivo.
    cuerpo = yaml.safe_dump(
        limpio, allow_unicode=True, default_flow_style=False, sort_keys=False
    ).rstrip("\n").split("\n")
    bloque = "  - " + cuerpo[0] + "\n" + "".join(f"    {l}\n" for l in cuerpo[1:])

    texto = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    if not texto.endswith("\n") and texto:
        texto += "\n"
    filas = texto.splitlines(keepends=True)

    inicio = next(
        (i for i, l in enumerate(filas) if l.rstrip("\n") == f"{seccion}:"), None
    )
    if inicio is None:
        nuevo = texto + ("\n" if texto else "") + f"{seccion}:\n" + bloque
    else:
        # Hasta la siguiente clave de primer nivel: dentro de la sección van las
        # líneas indentadas, las vacías y los comentarios.
        fin = len(filas)
        for i in range(inicio + 1, len(filas)):
            if filas[i].strip() and not filas[i][0].isspace():
                fin = i
                break
        nuevo = "".join(filas[:fin]) + bloque + "".join(filas[fin:])

    # Se comprueba ANTES de tocar el disco. Dejar `projects.yml` sin parsear
    # dejaría al hub sin proyectos, y por un formulario.
    try:
        comprobado = yaml.safe_load(nuevo) or {}
    except yaml.YAMLError as exc:
        raise YamlInvalido(f"El resultado no sería YAML válido: {exc}") from exc
    if not any(
        str(x.get(clave) or "") == valor for x in (comprobado.get(seccion) or [])
    ):
        raise YamlInvalido("El bloque no habría quedado donde debe. No se escribió.")

    _escribir_atomico(ruta, nuevo)


def _normalizar(ruta: str) -> str:
    return str(Path(ruta).expanduser()).rstrip("/")


def _expandir_patron(asiento: str | None, patron: str, id_: str) -> list[Ruta]:
    """`- patron: "*/repos/*"` → un `Ruta` por cada repo git que encaje (decisión 150).

    Para un asiento que **contiene** repos —un workspace con `{ambiente}/repos/`—
    listarlos uno a uno en `projects.yml` es una lista que caduca en cuanto se
    clona el siguiente. El patrón declara la intención y se resuelve al leer,
    contra el disco, que es lo que la regla dura 1 pide: nada aquí que no se
    pueda reconstruir escaneando.

    Sólo entran las carpetas con `.git` (directorio o archivo, para que los
    worktrees cuenten): lo demás bajo `repos/` no se mide, y medirlo daría un
    cero que se lee como «todo a salvo». Un patrón sin coincidencias no es un
    error: un workspace recién instalado está vacío a propósito.
    """
    if not patron:
        raise KeyError("patron vacío")
    raiz = Path(patron).expanduser()
    if not raiz.is_absolute():
        if not asiento:
            raise YamlInvalido(
                f"El `patron` «{patron}» de «{id_}» es relativo y el proyecto no "
                "tiene `asiento` contra el que resolverlo."
            )
        raiz = Path(asiento)
        relativo = patron
    else:
        # `Path.glob` no acepta patrones absolutos: se separa la raíz fija.
        partes = raiz.parts
        fijas = []
        for parte in partes:
            if any(c in parte for c in "*?["):
                break
            fijas.append(parte)
        raiz = Path(*fijas) if fijas else Path("/")
        relativo = str(Path(*partes[len(fijas):]))
    if not raiz.is_dir():
        return []
    encontradas = sorted(
        str(c).rstrip("/") for c in raiz.glob(relativo)
        if c.is_dir() and (c / ".git").exists()
    )
    return [Ruta(ruta=r) for r in encontradas]


def sincronizar(con: sqlite3.Connection, proyectos: list[Proyecto]) -> None:
    """Refleja projects.yml en el índice. El YAML manda: lo que no está, se va."""
    ids = {p.id for p in proyectos}
    for p in proyectos:
        con.execute(
            """INSERT INTO proyecto (id, nombre, dominio, tipo, asiento, estado_ref,
                                     base_version, guardrail, status, nota)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 nombre=excluded.nombre, dominio=excluded.dominio,
                 tipo=excluded.tipo, asiento=excluded.asiento,
                 estado_ref=excluded.estado_ref,
                 base_version=excluded.base_version, guardrail=excluded.guardrail,
                 status=excluded.status, nota=excluded.nota""",
            (p.id, p.nombre, p.dominio, p.tipo, p.asiento, p.estado_ref,
             p.base_version, p.guardrail, p.status, p.nota),
        )
        con.execute("DELETE FROM proyecto_ruta WHERE proyecto_id=?", (p.id,))
        vistas = set()
        if p.asiento:
            con.execute(
                "INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES (?,?,?)",
                (p.id, p.asiento, "asiento"),
            )
            vistas.add(p.asiento)
        for r in p.rutas:
            if r.ruta in vistas:
                continue
            vistas.add(r.ruta)
            con.execute(
                "INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES (?,?,?)",
                (p.id, r.ruta, r.tipo),
            )
    if ids:
        marcas = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM proyecto WHERE id NOT IN ({marcas})", tuple(ids))


class Atribuidor:
    """Asigna un panel a un proyecto por la ruta más específica que lo contenga.

    Un proyecto tiene asiento y repos, y pueden estar en filesystems distintos:
    se orquesta desde /mnt/c mientras su código vive en ~/dev.
    """

    def __init__(self, proyectos: list[Proyecto]):
        pares: list[tuple[str, str]] = []
        for p in proyectos:
            for ruta in p.todas_las_rutas():
                pares.append((ruta, p.id))
        # Más larga primero: ~/dev/app-front gana sobre ~/dev.
        self._rutas = sorted(pares, key=lambda par: len(par[0]), reverse=True)

    def atribuir(self, cwd: str) -> str | None:
        cwd = _normalizar(cwd)
        for ruta, proyecto_id in self._rutas:
            if cwd == ruta or cwd.startswith(ruta + "/"):
                return proyecto_id
        return None
