"""Qué puede hacer el navegador: la política, y la clasificación de cada petición.

La política vive en un YAML que escribe el dueño, no Claude. La decisión se toma
sobre la PETICIÓN DE RED, no sobre el clic: un clic en «Eliminar» no dice nada,
la petición DeleteRestApi que dispara sí. Y es lo que de verdad cambia algo en la
cuenta, así que es ahí donde hay que pararlo.

Pero no es la garantía. 🔴 La garantía es que la sesión del navegador tenga un rol
de solo lectura en IAM: esto es la segunda red, que además deja registro y permite
pedir permiso. Clasificar por nombre de acción se equivoca con una API que
nombre mal sus operaciones, y IAM no.
"""
import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import yaml

METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
ACCIONES_LECTURA = (r"^(Describe|List|Get|Search|Lookup|Filter|BatchGet|Query|Scan|"
                    r"StartQuery|StopQuery|GetQueryResults|Select|Head|Check|Validate|Test)")


@dataclass
class Politica:
    nombre: str = "sin-nombre"
    modo: str = "lectura"            # lectura | preguntar | libre
    origenes: list[str] = field(default_factory=list)
    acciones_lectura: str = ACCIONES_LECTURA
    silenciar: list[str] = field(default_factory=list)   # telemetría: se bloquea sin preguntar
    permitir: list[str] = field(default_factory=list)    # acciones concretas siempre permitidas
    avisar: str = ""                 # "telegram": cada pregunta toca el timbre del hub

    @classmethod
    def cargar(cls, ruta: Path) -> "Politica":
        d = yaml.safe_load(Path(ruta).read_text()) or {}
        p = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        if p.modo not in ("lectura", "preguntar", "libre"):
            raise ValueError(f"modo desconocido: {p.modo}")
        return p

    def origen_permitido(self, url: str) -> bool:
        s = urlsplit(url)
        if s.scheme in ("about", "data", "blob", "chrome", "devtools"):
            return True
        origen = f"{s.scheme}://{s.netloc}"
        return any(fnmatch.fnmatch(origen, o) for o in self.origenes)


def accion_de(metodo: str, url: str, cabeceras: dict, cuerpo: str | None) -> str:
    """El nombre de la operación, de donde lo ponga cada API de AWS.

    JSON 1.1 (Logs, DynamoDB…) lo lleva en X-Amz-Target; las API de consulta
    (EC2, IAM…) en Action=; las REST (API Gateway…) en el método y la ruta. La
    consola real a veces lo envuelve en un proxy propio con el mismo dato dentro
    del cuerpo, de ahí mirar también `operation`.
    """
    cab = {k.lower(): v for k, v in cabeceras.items()}
    if "x-amz-target" in cab:
        return cab["x-amz-target"].rsplit(".", 1)[-1]
    s = urlsplit(url)
    q = parse_qs(s.query)
    if "Action" in q:
        return q["Action"][0]
    if cuerpo:
        try:
            j = json.loads(cuerpo)
            for k in ("operation", "Action", "action"):
                if isinstance(j, dict) and isinstance(j.get(k), str):
                    return j[k]
        except ValueError:
            m = re.search(r"(?:^|&)Action=([A-Za-z]+)", cuerpo)
            if m:
                return m.group(1)
    return s.path.rstrip("/").rsplit("/", 1)[-1] or metodo


@dataclass
class Veredicto:
    decision: str      # permitir | bloquear | preguntar
    motivo: str
    accion: str = ""


def decidir(p: Politica, metodo: str, url: str, tipo: str,
            cabeceras: dict, cuerpo: str | None) -> Veredicto:
    if tipo == "Document" and not p.origen_permitido(url):
        return Veredicto("bloquear", "navegación fuera de los orígenes permitidos")
    if any(fnmatch.fnmatch(url, s) for s in p.silenciar):
        return Veredicto("bloquear", "silenciado (telemetría)")
    if metodo.upper() in METODOS_LECTURA:
        return Veredicto("permitir", "método de lectura")
    accion = accion_de(metodo, url, cabeceras, cuerpo)
    if accion in p.permitir or re.match(p.acciones_lectura, accion):
        return Veredicto("permitir", "acción de lectura", accion)
    if p.modo == "libre":
        return Veredicto("permitir", "modo libre", accion)
    if p.modo == "preguntar":
        return Veredicto("preguntar", "acción que modifica", accion)
    return Veredicto("bloquear", "acción que modifica, modo lectura", accion)
