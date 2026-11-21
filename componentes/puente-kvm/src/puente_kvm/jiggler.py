"""El jiggler del JetKVM: que el Mac no se bloquee ni se ponga «ausente» (C-0463).

Lo hace el aparato, no el puente: mueve el ratón un poco cuando lleva un rato
sin que nadie lo toque, en las horas de su horario. Queda guardado en él, así
que **sigue aunque se cierre el puente**, y la pantalla lo dice.

Aquí sólo está lo que decide el puente antes de mandárselo:

- los preajustes de la web del JetKVM (`ui/src/routes/devices.$id.settings.mouse.tsx`),
  con «Frecuente - 30 s» como el que pone el botón;
- el horario (un cron de seis campos, con segundos) con una gramática cerrada,
  porque el aparato toma uno malo en memoria, para el jiggler y no lo dice hasta
  reiniciarse (`rpcSetJigglerConfig` en su `jiggler.go`);
- y cómo se dice en la pantalla lo que tiene puesto.
"""

from __future__ import annotations

import re

#: id → (nombre en pantalla, config). Los de su web, con sus números.
PREAJUSTES: dict[str, tuple[str, dict]] = {
    "frecuente": ("Frecuente, cada 30 s",
                  {"inactivity_limit_seconds": 30, "jitter_percentage": 25, "schedule_cron_tab": "*/30 * * * * *"}),
    "estandar": ("Estándar, cada minuto",
                 {"inactivity_limit_seconds": 60, "jitter_percentage": 25, "schedule_cron_tab": "0 * * * * *"}),
    "ligero": ("Ligero, cada 5 min",
               {"inactivity_limit_seconds": 300, "jitter_percentage": 25, "schedule_cron_tab": "0 */5 * * * *"}),
}
#: Lo que pone el botón al encenderlo, salvo que haya un horario propio guardado.
POR_OMISION = "frecuente"
VARIACION = 25  # % de variación sobre el horario, el de todos sus preajustes
# Lo más corto, el preajuste más corto: con menos, el ratón se mueve en cuanto
# la persona deja de tocarlo para leer algo.
INACTIVIDAD_MIN, INACTIVIDAD_MAX = 30, 3600
PASO_MIN_S = 10  # en segundos, «*/n» con n de 10 o más: «*» lo movería cada segundo

# segundos, minutos, horas, día del mes, mes, día de la semana (0 = domingo)
_CAMPOS = (("segundos", 0, 59), ("minutos", 0, 59), ("horas", 0, 23),
           ("día del mes", 1, 31), ("mes", 1, 12), ("día de la semana", 0, 6))
# [0-9] y no \d: «٣» es un dígito para Python y no para el cron del aparato.
_TROZO = re.compile(r"^(\*|[0-9]+(?:-[0-9]+)?)(?:/([0-9]+))?$")
_DIAS = ("domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado")


def validar_horario(texto: str) -> str:
    """El cron de seis campos, limpio; ValueError con el porqué si no vale.

    Sólo números, `*`, rangos `a-b`, pasos `/n` y listas con comas: lo que
    entiende cualquier cron. Ni nombres (MON), ni `?`, ni `TZ=` (la zona va aparte).
    """
    campos = texto.split()
    if len(campos) != 6:
        raise ValueError("el horario lleva seis campos: segundos minutos horas día-del-mes mes "
                         f"día-de-la-semana (p. ej. «*/30 * 9-17 * * 1-5»); tiene {len(campos)}")
    for valor, (nombre, menor, mayor) in zip(campos, _CAMPOS):
        for trozo in valor.split(","):
            m = _TROZO.match(trozo)
            if not m:
                raise ValueError(f"«{trozo}» no vale en {nombre}: sólo números, *, a-b, /n y comas")
            base, paso = m.groups()
            if paso is not None and int(paso) == 0:
                raise ValueError(f"un paso de 0 en {nombre} no avanza nunca")
            if nombre == "segundos" and not base.isdigit() and (paso is None or int(paso) < PASO_MIN_S):
                raise ValueError(f"en segundos, un número o «*/n» con n de {PASO_MIN_S} o más: "
                                 f"«{trozo}» movería el ratón cada segundo")
            if base != "*":
                a, _, b = base.partition("-")
                desde, hasta = int(a), int(b or a)
                if not (menor <= desde <= mayor and menor <= hasta <= mayor):
                    raise ValueError(f"{nombre} va de {menor} a {mayor}: «{trozo}» se sale")
                if desde > hasta:
                    raise ValueError(f"en {nombre}, «{trozo}» va hacia atrás")
    return " ".join(campos)


def preajuste_de(config: dict | None) -> str | None:
    """El preajuste que es `config` (la zona no cuenta: sus preajustes no la llevan)."""
    if not config:
        return None
    for pid, (_, c) in PREAJUSTES.items():
        if all(config.get(k) == v for k, v in c.items()):
            return pid
    return None


def config_nueva(actual: dict | None, horario: str = "", zona: str = "",
                 inactividad_s: int | None = None) -> dict | None:
    """Lo que hay que guardar en el aparato al encenderlo, o None si se deja lo suyo.

    Con `horario`, ése. Sin él, «Frecuente» si lo guardado es un preajuste (el
    aparato viene con «Estándar»), y si es un horario propio, no se pisa: lo
    habrá puesto Claude a petición de la persona.
    """
    if horario:
        if not zona:
            # Sin ella el aparato usa UTC: «de 9 a 18» en México correría de 3 a 12.
            raise ValueError("falta la zona de esas horas (p. ej. «America/Mexico_City»)")
        inactividad = int(inactividad_s if inactividad_s is not None else 30)
        if not INACTIVIDAD_MIN <= inactividad <= INACTIVIDAD_MAX:
            raise ValueError(f"la inactividad va de {INACTIVIDAD_MIN} a {INACTIVIDAD_MAX} segundos")
        return {"inactivity_limit_seconds": inactividad, "jitter_percentage": VARIACION,
                "schedule_cron_tab": validar_horario(horario), "timezone": zona}
    if zona or inactividad_s is not None:
        raise ValueError("la zona y la inactividad van con un horario")
    if actual and preajuste_de(actual) is None:
        return None
    return dict(PREAJUSTES[POR_OMISION][1])


def _horas(campo: str) -> str | None:
    m = re.fullmatch(r"(\d+)-(\d+)", campo)
    return f"de {int(m.group(1))}:00 a {int(m.group(2)) + 1}:00" if m else None


def _dias(campo: str) -> str | None:
    if campo == "1-5":
        return "entre semana"
    if campo in ("0,6", "6,0"):
        return "los fines de semana"
    m = re.fullmatch(r"(\d)-(\d)", campo)
    return f"de {_DIAS[int(m.group(1))]} a {_DIAS[int(m.group(2))]}" if m else None


def _cada(segundos: str, minutos: str) -> str | None:
    """Cada cuánto, si se puede decir en una frase; si no, None."""
    m = re.fullmatch(r"\*/(\d+)", segundos)
    if m and minutos == "*":
        return f"cada {m.group(1)} s"
    if segundos == "0":
        if minutos == "*":
            return "cada minuto"
        if minutos == "0":
            return "cada hora"
        m = re.fullmatch(r"\*/(\d+)", minutos)
        if m:
            return f"cada {m.group(1)} min"
    return None


def describir(jiggler: dict | None) -> str:
    """En palabras, para la placa: «apagado», «Frecuente, cada 30 s», «entre semana de 9:00 a 18:00»…"""
    if not jiggler:
        return "sin leer"
    if not jiggler.get("encendido"):
        return "apagado"
    config = jiggler.get("config") or {}
    pid = preajuste_de(config)
    if pid:
        return PREAJUSTES[pid][0]
    cron = str(config.get("schedule_cron_tab", ""))
    campos = cron.split()
    texto = f"horario «{cron}»"
    # En palabras sólo lo que se puede decir entero; si no, el cron tal cual: una
    # frase que callara un campo prometería más (o menos) de lo que hace.
    if len(campos) == 6 and campos[3] == "*" and campos[4] == "*" and (cada := _cada(campos[0], campos[1])):
        dias = _dias(campos[5]) if campos[5] != "*" else "todos los días"
        horas = _horas(campos[2]) if campos[2] != "*" else "a todas horas"
        if dias and horas:
            texto = f"{dias} {horas}, {cada}"
    # Un horario propio lleva siempre su zona: sin ella, las horas no dicen nada.
    return f"{texto} ({config.get('timezone') or 'UTC'})"
