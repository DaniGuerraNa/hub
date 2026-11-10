"""El vocabulario del personaje del secretario (C-0166, decisión 358).

Listas cerradas, sin dependencias: las importan `herramientas` (en
`hub-secretario`) y `api` (en `hub-web`), que no deben cargarse la una a la
otra (decisión 298). Lo que se pinta sale de aquí y de nada más:

- `GESTOS`: la familia de cada herramienta, que decide el accesorio que lleva
  en la mano. El JavaScript sólo conoce esta lista, nunca nombres de
  herramientas: añadir una herramienta es darle un gesto que ya existe.
- `ROLES`: la skin de un acompañante (con el cubo; con un dibujo, la
  insignia de `GESTO_DE_ROL`). Un acompañante es **lo que delegó y
  sigue vivo** —una tarea del orquestador, la sesión que trabaja para ella y
  sus subagentes, un resumen aparte, el modelo mayor—, nunca un compañero
  inventado: el secretario no tiene subagentes (301), y pintar uno que no
  existe es la cifra indefendible de la regla 13.
- `ESTADOS`: lo que puede estar haciendo, con cuándo se enseña cada uno.
- `PERSONAJES`: quién lo hace, a elegir (C-0188, decisión 377). El cubo es el
  SVG de siempre; los demás son dibujos, una hoja por personaje en
  `static/personajes/<id>.webp` con una celda por pose (`POSES`), que monta
  `scripts/personajes.py`. Qué pose toca en cada estado lo dice `pose_de`, y
  lo aplica el CSS (`avatar-secretario.css` lleva una copia literal que un
  test compara): el JavaScript no sabe que existen.
- `PUESTOS`: dónde está, en el modo monitor (C-0202, decisión 389). Cada
  estado y cada gesto tiene su puesto (`puesto_de`); la tabla viaja a la
  página en `api.secretario_monitor`, y `escenario-secretario.js` sólo la
  aplica: no hay una segunda lista en JavaScript.
"""

from __future__ import annotations

import re
import unicodedata

#: gesto → nombre de la familia, para la galería.
GESTOS: dict[str, str] = {
    "leer": "Leer",
    "buscar": "Buscar",
    "mensajes": "Mensajes",
    "agenda": "Agenda",
    "compromisos": "Compromisos",
    "mirar": "Mirar la pantalla",
    "maquina": "El hub y la máquina",
    "carpeta": "Proyectos y archivos",
    "anotar": "Anotar",
    "idea": "Ideas",
    "mostrar": "Enseñar algo",
    "avisar": "Avisar",
    "pc": "Abrir en la PC",
    "grabar": "Grabar",
    "tele": "La tele",
    "hacer": "Hacer (otra acción)",
    "delegar": "Delegar",
    "escalar": "Escalar",
    "hora": "La hora",
}

#: rol → (nombre, qué es). El de un subagente sale de su `subagent_type`
#: con `rol_de`; lo que no casa con ninguno es «otro» y se pinta neutro con
#: su inicial, nunca con una skin que no le toca.
ROLES: dict[str, tuple[str, str]] = {
    "orquestador": ("Orquestador", "una tarea que le encargó al orquestador"),
    "obrero": ("Sesión del proyecto", "la sesión de Claude Code que trabaja esa tarea"),
    "arquitecto": ("Arquitecto", "subagente que revisa el diseño antes de construir"),
    "revisor": ("Revisor", "subagente que revisa lo hecho"),
    "disenador": ("Diseñador", "subagente de diseño"),
    "explorador": ("Explorador", "subagente que busca en el código"),
    "investigador": ("Investigador", "subagente que investiga fuera, o una investigación suya en la web (385)"),
    "planificador": ("Planificador", "subagente que hace el plan"),
    "ayudante": ("Ayudante", "subagente de propósito general"),
    "resumidor": ("Resumidor", "un resumen de sesión que está leyendo aparte"),
    "experto": ("Experto", "el modelo mayor, cuando le pasa el turno"),
    "otro": ("Otro", "un subagente de un tipo que no conoce: neutro, con su inicial"),
}

#: rol → el gesto de `GESTOS` que lleva de insignia cuando quien lo hace es un
#: dibujo (C-0236): cada acompañante es el mismo personaje en pequeño, y lo que
#: dice su rol es lo que lleva, no su ropa. «otro» no lleva ninguna: su
#: inicial. `_personaje.html` lleva una copia literal que un test compara.
GESTO_DE_ROL: dict[str, str] = {
    "orquestador": "delegar",
    "obrero": "pc",
    "arquitecto": "idea",
    "revisor": "compromisos",
    "disenador": "mostrar",
    "explorador": "carpeta",
    "investigador": "buscar",
    "planificador": "agenda",
    "ayudante": "hacer",
    "resumidor": "leer",
    "experto": "escalar",
    "otro": "",
}

#: estado → (nombre, cuándo).
ESTADOS: dict[str, tuple[str, str]] = {
    "quieto": ("Quieto", "sin nada en curso: respira y parpadea"),
    "dormido": ("Descansando", "tres minutos sin nada que hacer"),
    "escuchando": ("Te escucha", "con el micrófono abierto"),
    "transcribiendo": ("Transcribiendo", "el audio ya va camino del texto"),
    "pensando": ("Pensando", "con el turno abierto y aún sin herramienta"),
    "pensando-fondo": ("Pensándolo a fondo", "el turno pasó al modelo mayor"),
    "trabajando": ("Trabajando", "usando una herramienta: el accesorio dice cuál"),
    "escribiendo": ("Escribiendo", "la respuesta está llegando"),
    "hablando": ("Hablando", "te lee la respuesta en voz alta"),
    "esperando": ("Espera tu sí", "una acción pide tu permiso"),
    "esperando-otro": ("Esperando a otro", "lo que delegó sigue trabajando"),
    "en-cola": ("En cola", "tu mensaje aún no lo ha cogido"),
    "hecho": ("Listo", "acaba de contestar (se va solo)"),
    "error": ("Algo falló", "el turno acabó en error (se va solo)"),
    "pausa": ("En pausa", "el modo voz está en pausa"),
    "sin-hub": ("Sin hub", "la pantalla no consigue hablar con el hub"),
}

#: id → (nombre, familia). El primero es el de siempre y el de por omisión.
#: Cada id salvo el cubo tiene su hoja en `static/personajes/` (lo comprueba
#: un test, y también que no sobre ninguna).
PERSONAJES: dict[str, tuple[str, str]] = {
    "cubo": ("El cubo", "Original"),
    "rana-mochi": ("Ranita mochi", "Ranas"),
    "rana-nenufar": ("Ranita con nenúfar", "Ranas"),
    "rana-lentes": ("Ranita secretaria", "Ranas"),
    "renacuajo": ("Ranita bebé", "Ranas"),
    "rana-gomita": ("Ranita gomita", "Ranas"),
    "hongo-amanita": ("Hongito amanita", "Hongos"),
    "hongo-cartero": ("Champiñón cartero", "Hongos"),
    "hongo-luz": ("Hongito de luz", "Hongos"),
    "hongo-familia": ("Hongo y sus ayudantes", "Hongos"),
    "rana-sombrero-hongo": ("Rana con sombrero de hongo", "Las dos"),
    "rana-bajo-hongo": ("Rana bajo su hongo", "Las dos"),
}
POR_OMISION = "cubo"
#: La clave en la memoria del secretario, como el modo inglés (C-0159): vale
#: en todos los aparatos.
CLAVE = "personaje"

#: Las celdas de cada hoja, en orden: de izquierda a derecha y de arriba abajo,
#: tres por fila. El orden lo comparten el importador y el CSS.
POSES = ("base", "escuchando", "pensando", "buscando", "anotando", "hablando", "esperando", "listo", "dormido")

#: Todos los estados salvo «trabajando», que va por gesto. Los dibujos de
#: «esperando» llevan un «?» y los de «listo» un ✓ pintados: «esperando-otro»
#: (lo delegado trabaja) y «en-cola» no te preguntan nada, así que van con la
#: base y lo que los distingue es quién está a su lado y el reloj de arena.
#: Error, pausa y sin hub son la base con su filtro y su insignia.
POSE_DE_ESTADO: dict[str, str] = {
    "quieto": "base",
    "dormido": "dormido",
    "escuchando": "escuchando",
    "transcribiendo": "escuchando",
    "pensando": "pensando",
    "pensando-fondo": "pensando",
    "escribiendo": "anotando",
    "hablando": "hablando",
    "esperando": "esperando",
    "esperando-otro": "base",
    "en-cola": "base",
    "hecho": "listo",
    "error": "base",
    "pausa": "base",
    "sin-hub": "base",
}

#: Trabajando, la pose sale del gesto; el objeto concreto lo sigue diciendo
#: la insignia que lleva encima (`.pj-accesorio`). Enumerados los 19: una regla
#: genérica para «trabajando» más otra por gesto encenderían dos capas.
POSE_DE_GESTO: dict[str, str] = {
    "leer": "buscando",
    "buscar": "buscando",
    "mensajes": "buscando",
    "agenda": "anotando",
    "compromisos": "anotando",
    "mirar": "buscando",
    "maquina": "buscando",
    "carpeta": "buscando",
    "anotar": "anotando",
    "idea": "anotando",
    "mostrar": "buscando",
    "avisar": "buscando",
    "pc": "buscando",
    "grabar": "buscando",
    "tele": "buscando",
    "hacer": "buscando",
    "delegar": "buscando",
    "escalar": "buscando",
    "hora": "buscando",
}


def pose_de(estado: str, gesto: str = "") -> str:
    """La pose (una de `POSES`) de un personaje dibujado en ese estado."""
    if estado == "trabajando":
        return POSE_DE_GESTO.get(gesto, "buscando")
    return POSE_DE_ESTADO.get(estado, "base")


# ── el modo monitor (C-0202, decisión 389) ──

#: puesto → (nombre, qué hay ahí, el accesorio que lo dibuja: un gesto de
#: `GESTOS`, cuyo símbolo `#acc-<gesto>` ya pinta `_personaje.html`). El orden
#: es el de la pantalla. Lista cerrada, como los gestos: un puesto al que no
#: lleva ningún estado ni gesto sería un decorado que no dice nada (lo
#: comprueba un test).
PUESTOS: dict[str, tuple[str, str, str]] = {
    "agenda": ("Agenda", "tu calendario y la hora", "agenda"),
    "mensajes": ("Mensajes", "lo que ha leído: mensajes y reuniones", "mensajes"),
    "asuntos": ("Te espera", "lo que espera tu sí o tu respuesta", "compromisos"),
    "proyectos": ("Proyectos", "tus proyectos, sus archivos y las ideas", "carpeta"),
    "escritorio": ("Su mesa", "piensa, te escucha y te contesta", "anotar"),
    "orquestador": ("Orquestador", "lo que encarga y sigue en marcha", "delegar"),
    "maquina": ("Máquina", "el hub, la máquina y tu pantalla", "maquina"),
    "web": ("Navegador", "lo que te abre o te enseña en pantalla", "pc"),
}
#: Donde descansa: sin nada en curso, vuelve aquí.
REPOSO = "escritorio"

#: Todos los estados salvo «trabajando», que va por gesto. Espera tu sí junto
#: a tus asuntos; lo delegado, junto al orquestador; lo demás —escuchar,
#: pensar, escribir, hablar— lo hace en su mesa.
PUESTO_DE_ESTADO: dict[str, str] = {
    "quieto": "escritorio",
    "dormido": "escritorio",
    "escuchando": "escritorio",
    "transcribiendo": "escritorio",
    "pensando": "escritorio",
    "pensando-fondo": "escritorio",
    "escribiendo": "escritorio",
    "hablando": "escritorio",
    "esperando": "asuntos",
    "esperando-otro": "orquestador",
    "en-cola": "escritorio",
    "hecho": "escritorio",
    "error": "escritorio",
    "pausa": "escritorio",
    "sin-hub": "escritorio",
}

#: Trabajando, el puesto sale de la familia de la herramienta. Un gesto es una
#: familia y no una herramienta: «leer» lee un mensaje o un archivo, y va a
#: Mensajes; el rótulo que lleva encima dice qué lee.
PUESTO_DE_GESTO: dict[str, str] = {
    "leer": "mensajes",
    "buscar": "mensajes",
    "mensajes": "mensajes",
    "avisar": "mensajes",
    "agenda": "agenda",
    "hora": "agenda",
    "compromisos": "asuntos",
    "carpeta": "proyectos",
    "idea": "proyectos",
    "maquina": "maquina",
    "mirar": "maquina",
    "grabar": "maquina",
    "tele": "maquina",
    "pc": "web",
    "mostrar": "web",
    "delegar": "orquestador",
    "anotar": "escritorio",
    "escalar": "escritorio",
    # El genérico: el de una acción sin gesto propio (`piezas.Accion.gesto`),
    # el de una herramienta fuera del catálogo y aquel en que el JS convierte
    # uno que no conoce. No dice de qué es, así que lo hace en su mesa.
    "hacer": "escritorio",
}

#: Los puestos de espera, que ceden a tus asuntos si algo te espera: lo que
#: espera de ti va antes que lo que espera de otros.
CEDEN_A_ASUNTOS = ("escritorio", "orquestador")


def puesto_de(estado: str, gesto: str = "", nuevas: int = 0) -> str:
    """El puesto (una clave de `PUESTOS`) donde se pone en ese estado.

    `nuevas`, lo que te espera sin haberlo visto (`secretario_espera`, los
    asuntos): mientras haya algo, lo que haga en su mesa o esperando a otros
    lo hace junto a tus asuntos. Trabajando, va a donde le lleve el trabajo."""
    if estado == "trabajando":
        puesto = PUESTO_DE_GESTO.get(gesto, REPOSO)
    else:
        puesto = PUESTO_DE_ESTADO.get(estado, REPOSO)
        if nuevas > 0 and puesto in CEDEN_A_ASUNTOS:
            return "asuntos"
    return puesto


def escenario() -> dict:
    """La tabla que aplica `escenario-secretario.js`, tal cual: así el JS no
    lleva una segunda copia que se quede vieja."""
    return {"estado": dict(PUESTO_DE_ESTADO), "gesto": dict(PUESTO_DE_GESTO),
            "accesorio": {p: acc for p, (_n, _q, acc) in PUESTOS.items()},
            "reposo": REPOSO, "ceden": list(CEDEN_A_ASUNTOS)}


def elegido(valor) -> str:
    """El id que se pinta para lo guardado: lo que no está en el catálogo
    (un personaje retirado, un valor roto) es el de por omisión."""
    return valor if isinstance(valor, str) and valor in PERSONAJES else POR_OMISION


def hoja(pid: str) -> str:
    """La URL de la hoja de un personaje; el cubo no tiene (es SVG)."""
    pid = elegido(pid)
    return "" if pid == POR_OMISION else f"/static/personajes/{pid}.webp"


#: Cómo se llama (C-0226, idea 10 del tablero): «Secretario» es el rol, no un
#: nombre para llamarlo a cada rato. Como el personaje, en su memoria y para
#: todos los aparatos. El código, las rutas y la documentación siguen diciendo
#: «secretario»: es lo que es, no cómo se llama.
NOMBRE_POR_OMISION = "Secretario"
CLAVE_NOMBRE = "nombre"
NOMBRE_MAXIMO = 24
# Letras de cualquier idioma, números, espacios y unos pocos signos de nombre
# («Sr. Pérez», «R2-D2», «Ana María»). Nada de `<>` ni saltos: va en el menú,
# en títulos y en el prompt, y un nombre no necesita más.
_NOMBRE = re.compile(r"[^\W_](?:[\w .'’-]*[^\W_.])?")


def nombre_de(valor) -> str:
    """El nombre que se usa para lo guardado: lo vacío o roto es «Secretario»."""
    bueno = isinstance(valor, str) and len(valor) <= NOMBRE_MAXIMO and _NOMBRE.fullmatch(valor)
    return valor if bueno else NOMBRE_POR_OMISION


def nombrar(con, valor: str) -> str:
    """Guarda cómo se llama. Vacío vuelve al de por omisión; lo que no es un
    nombre (`<`, saltos, más de 24 letras) es `ValueError` y no se guarda."""
    limpio = " ".join(str(valor or "").split())
    if limpio and (len(limpio) > NOMBRE_MAXIMO or not _NOMBRE.fullmatch(limpio)):
        raise ValueError(f"«{limpio[:40]}» no vale como nombre: hasta {NOMBRE_MAXIMO} letras, "
                         "números, espacios, punto, guion o apóstrofo")
    from . import memoria
    memoria.poner(con, CLAVE_NOMBRE, limpio or NOMBRE_POR_OMISION)
    return limpio or NOMBRE_POR_OMISION


def elegir(con, pid: str) -> str:
    """Guarda el personaje elegido en la memoria del secretario. Sólo los del
    catálogo: lo demás es `ValueError` y no se guarda nada."""
    if pid not in PERSONAJES:
        raise ValueError(f"no hay ningún personaje «{pid}»")
    # Dentro: este módulo es una hoja sin dependencias, y así lo pueden
    # importar `herramientas` y `api` sin arrastrarse nada (decisión 298).
    from . import memoria
    memoria.poner(con, CLAVE, pid)
    return pid

# Palabras del `subagent_type` → rol. Por PALABRAS y no por subcadena («ui»
# está dentro de «guide»), y por raíz sólo las de más de cuatro letras: las
# cortas, enteras («plan» no es «planta»). «claud» es la raíz de «claude»: el
# literal entero lo toma el lint de `test_modelos` por un arranque sin modelo.
_PISTAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("arquitecto", ("arquitect", "architect")),
    ("revisor", ("revis", "review", "auditor")),
    ("disenador", ("disen", "design", "ux", "ui", "visual")),
    ("explorador", ("explor", "buscador")),
    ("investigador", ("investig", "research")),
    ("planificador", ("plan", "planner", "planific")),
    ("resumidor", ("resum", "summar")),
    ("orquestador", ("orquest", "orchestr")),
    ("ayudante", ("general", "claud", "ayudante", "helper", "assistant")),
)
_RAIZ_MIN = 5


def _palabras(texto: str) -> list[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return [p for p in re.split(r"[^a-z0-9]+", sin_tildes.lower()) if p]


def rol_de(tipo: str) -> str:
    """El rol (una clave de `ROLES`) de un subagente por su `subagent_type`."""
    for palabra in _palabras(tipo):
        for rol, raices in _PISTAS:
            if any(palabra == r or (len(r) >= _RAIZ_MIN and palabra.startswith(r)) for r in raices):
                return rol
    return "otro"


def inicial(tipo: str) -> str:
    """La letra que lleva un acompañante sin skin propia."""
    p = _palabras(tipo)
    return p[0][0].upper() if p else "?"
