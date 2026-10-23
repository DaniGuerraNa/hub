"""Un subconjunto de la sintaxis de CloudWatch Logs Insights.

Lo justo para que un flujo de consulta tenga resultados que dependan de la
consulta: fields, filter (like /re/, =, !=), sort, limit y stats count(*) by.
Lo que no se entiende se rechaza con un error, como hace la consola real, en vez
de devolver todo: una consulta mal escrita que «funciona» enseñaría a la IA que
estaba bien.
"""
import re

from .datos import EVENTOS


class ErrorDeConsulta(ValueError):
    pass


def _bin(ts: str, minutos: int) -> str:
    h, m = int(ts[11:13]), int(ts[14:16])
    m = (m // minutos) * minutos
    return f"{ts[:11]}{h:02d}:{m:02d}:00.000"


def ejecutar(consulta: str, grupos: list[str]) -> dict:
    if not grupos:
        raise ErrorDeConsulta("Selecciona al menos un grupo de logs.")
    filas = [dict(e) for e in EVENTOS if e["@log"] in grupos]
    campos = None
    limite = 10000
    for paso in [p.strip() for p in consulta.split("|") if p.strip()]:
        cmd, _, resto = paso.partition(" ")
        resto = resto.strip()
        if cmd == "fields":
            campos = [c.strip() for c in resto.split(",") if c.strip()]
        elif cmd == "filter":
            m = re.fullmatch(r"(@?\w+)\s+(not\s+)?like\s+/(.*)/", resto)
            if m:
                campo, neg, patron = m.groups()
                rx = re.compile(patron)
                filas = [f for f in filas if bool(rx.search(str(f.get(campo, "")))) != bool(neg)]
                continue
            m = re.fullmatch(r"(@?\w+)\s*(=|!=)\s*[\"'](.*)[\"']", resto)
            if not m:
                raise ErrorDeConsulta(f"filter no reconocido: {resto}")
            campo, op, valor = m.groups()
            filas = [f for f in filas if (str(f.get(campo, "")) == valor) == (op == "=")]
        elif cmd == "sort":
            m = re.fullmatch(r"(@?\w+)(\s+(asc|desc))?", resto)
            if not m:
                raise ErrorDeConsulta(f"sort no reconocido: {resto}")
            filas.sort(key=lambda f: str(f.get(m.group(1), "")), reverse=m.group(3) == "desc")
        elif cmd == "limit":
            if not resto.isdigit():
                raise ErrorDeConsulta("limit necesita un número")
            limite = int(resto)
        elif cmd == "stats":
            m = re.fullmatch(r"count\(\*\)(\s+as\s+(\w+))?(\s+by\s+(.+))?", resto)
            if not m:
                raise ErrorDeConsulta(f"stats no reconocido (sólo count(*)): {resto}")
            nombre = m.group(2) or "count(*)"
            por = (m.group(4) or "").strip()
            grupos_ = {}
            for f in filas:
                if not por:
                    k = ("",)
                else:
                    b = re.fullmatch(r"bin\((\d+)m\)", por)
                    k = (_bin(f["@timestamp"], int(b.group(1))),) if b else (str(f.get(por, "")),)
                grupos_[k] = grupos_.get(k, 0) + 1
            col = por if por else None
            filas = [({col: k[0]} if col else {}) | {nombre: n} for k, n in sorted(grupos_.items())]
            campos = ([col] if col else []) + [nombre]
        else:
            raise ErrorDeConsulta(f"Comando desconocido: {cmd}")
    filas = filas[:limite]
    if campos is None:
        campos = ["@timestamp", "@message"]
    return {"campos": campos,
            "filas": [[f.get(c, "") for c in campos] for f in filas],
            "registros_escaneados": sum(1 for e in EVENTOS if e["@log"] in grupos)}
