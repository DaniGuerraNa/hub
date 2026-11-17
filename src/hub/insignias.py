"""Cómo se ve un estado sin tener que leerlo.

Nace de un fallo de reconocimiento: la interfaz decía «personal · activo · ask»
y había que **leer las tres palabras** para saber qué eran, cuál era cuál y si
alguna pedía atención. Con doce proyectos, eso es doce lecturas para responder
«¿hay algo parado?».

Tres reglas, y las tres importan:

1. **El color codifica una sola cosa en toda la interfaz: cuánta atención pide
   esto.** Verde = como debe estar. Ámbar = detenido o pendiente, no roto.
   Coral = en riesgo, hay algo que hacer. Gris = neutro, o una decisión
   deliberada que no es un problema. Si el verde significara «activo» en una
   columna y «seguro» en otra, no se aprende ninguno de los dos.

2. **La forma codifica el valor concreto**, para no depender del color: un
   monitor malo, la luz del sol o un daltonismo dejan la mitad de la interfaz
   muda si el color es el único portador. Cada valor tiene glifo propio dentro
   de su familia.

3. **El texto no se va.** Esto añade una capa de reconocimiento rápido; no
   sustituye a la palabra. Un símbolo sin su nombre es un acertijo la primera
   vez que se ve.

Vive en Python y no en un macro de Jinja para poder afirmar con un test que
**todo valor que existe en la base tiene insignia** — un valor nuevo saldría
mudo en la UI, y mudo es exactamente el fallo que esto viene a arreglar.
"""

from __future__ import annotations

from typing import NamedTuple

from hub import reloj


class Insignia(NamedTuple):
    glifo: str
    tono: str     # nombre del token CSS, sin `var()`
    texto: str    # la palabra, que siempre acompaña
    porque: str   # se convierte en `title=`: qué significa, en una frase


#: Cómo se dice cada nivel de confianza (UI-36, C-0371). El valor (`auto`,
#: `ask`, `never`) es el que se guarda y se envía, y su semántica no cambia
#: (regla dura 7): esto es sólo su nombre en pantalla, para no tener que
#: recordar qué significa cada clave. Lo comparten el guardrail de un proyecto
#: y la confianza del secretario, que usan los mismos tres.
NIVELES = {"auto": "Lo hace solo", "ask": "Te pregunta", "never": "Nunca"}


def nombre_nivel(valor: str | None) -> str:
    """El nombre en pantalla de un nivel; lo que no es un nivel, tal cual."""
    crudo = str(valor or "")
    return NIVELES.get(crudo.strip().lower(), crudo)


# `tono` sólo puede ser uno de estos cuatro. La escala es el contrato.
OK = "ok"          # verde  — como debe estar
ESPERA = "espera"  # ámbar  — detenido o pendiente, no roto
RIESGO = "riesgo"  # coral  — hay algo que hacer
NEUTRO = "neutro"  # gris   — sin carga, o decisión deliberada


MAPA: dict[str, dict[str, Insignia]] = {
    "status": {
        "activo": Insignia("●", OK, "activo", "En marcha"),
        "pausado": Insignia("◐", ESPERA, "pausado", "Parado a propósito, se puede retomar"),
        "archivado": Insignia("○", NEUTRO, "archivado", "Se conserva ubicado, no se trabaja"),
    },
    # Cuánto puede hacer el hub sin preguntarte. Ninguno está «mal», así que
    # ninguno es coral: sólo `auto` pide atención, porque es el único que actúa
    # sin ti.
    "guardrail": {
        "auto": Insignia("◉", ESPERA, NIVELES["auto"].lower(), "El hub puede lanzar agentes aquí sin preguntar"),
        "ask": Insignia("◆", NEUTRO, NIVELES["ask"].lower(), "Pregunta antes de actuar"),
        "never": Insignia("○", NEUTRO, NIVELES["never"].lower(), "Nunca actúa solo en este proyecto"),
    },
    # De quién es el trabajo. No es un estado: no lleva color, sólo forma.
    "dominio": {
        "personal": Insignia("◇", NEUTRO, "personal", "Proyecto propio"),
        "laboral": Insignia("■", NEUTRO, "laboral", "Trabajo remunerado"),
    },
    "tipo": {
        "proyecto": Insignia("□", NEUTRO, "proyecto", "Un proyecto"),
        "kit": Insignia("▪", NEUTRO, "kit", "Kit reutilizable por otros proyectos"),
        "asistente": Insignia("★", NEUTRO, "asistente", "El asistente del hub"),
    },
    # Dónde puede aterrizar el trabajo de este repo si la máquina se apaga.
    "regimen": {
        "con-upstream": Insignia("✓", OK, "con upstream", "La rama sigue a un remoto: un push la sube"),
        "sin-upstream": Insignia("▲", ESPERA, "sin upstream",
                                 "Hay remoto, pero esta rama no lo sigue: `push` sin `-u` no funciona"),
        "sin-remoto": Insignia("○", NEUTRO, "sin remoto",
                               "Repo local puro. No es un descuido: es una decisión"),
    },
    "servicio": {
        "running": Insignia("●", OK, "corriendo", "El contenedor está en marcha"),
        "exited": Insignia("○", NEUTRO, "parado", "El contenedor terminó"),
        "created": Insignia("□", ESPERA, "creado", "Creado pero nunca arrancado"),
        "paused": Insignia("◐", ESPERA, "en pausa", "Congelado, no terminado"),
        "restarting": Insignia("↻", ESPERA, "reiniciando", "Está reiniciándose"),
        "dead": Insignia("✕", RIESGO, "muerto", "Docker no pudo pararlo limpiamente"),
    },
    # Las comprobaciones de «Salud del hub» (`salud.revisar`, decisión 289).
    # «bien» iba sólo con color y palabra (C-0378): el glifo es lo que deja
    # distinguir un «aviso» de un «mal» sin leer.
    "salud": {
        "ok": Insignia("✓", OK, "bien", "Está como tiene que estar"),
        "aviso": Insignia("▲", ESPERA, "aviso", "Funciona, pero algo pide un arreglo"),
        "mal": Insignia("✕", RIESGO, "mal", "No está en pie: tiene su arreglo al lado"),
    },
}


def de(dimension: str, valor: str | None) -> Insignia | None:
    """La insignia de un valor, o None si no se conoce.

    Devolver None y no un símbolo de relleno es deliberado: la plantilla cae de
    vuelta al texto pelado, que es correcto aunque sea menos rápido de leer.
    Inventar un glifo para un valor desconocido diría algo que no sabemos.
    """
    if valor is None:
        return None
    return MAPA.get(dimension, {}).get(str(valor).strip().lower())


def registrar(env) -> None:
    """Cuelga `insignia()` de un entorno Jinja.

    Existe porque hay DOS entornos: el de la app y el del arnés de tests. Cuando
    sólo lo registraba web.py, el arnés renderizaba las mismas plantillas sin
    esta función y reventaba — es decir, probaba algo distinto de lo que se
    sirve. Un único punto de configuración es lo que impide que vuelvan a
    divergir en silencio.

    Por la misma razón cuelga también el filtro `cuando` (`reloj.cuando`), con
    el que `ui.cuando` pinta toda fecha (C-0396): el arnés pinta Proyecto,
    Inventario o Trabajo, y sin él cada fecha de esas pantallas reventaría
    allí y no en la app.
    """
    env.globals["insignia"] = de
    env.globals["nombre_nivel"] = nombre_nivel
    env.filters["cuando"] = reloj.cuando
    # Un lapso en su unidad («2 h» y no «7200 s»), con los mismos cortes que
    # el «hace» de `cuando` (tras la revisión de C-0396).
    env.filters["duracion"] = reloj.duracion
