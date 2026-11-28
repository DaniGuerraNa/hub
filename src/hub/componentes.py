"""Navegante, Reuniones, el Puente KVM y el estudio: dónde está lo que hace su trabajo y qué le falta.

Las pantallas son del hub, pero el trabajo lo hacen componentes aparte —el
laboratorio del navegador, el procesado de Reuniones y el Puente KVM—, que en
el producto viajan dentro del clon, en `componentes/` (decisión 293). Sin
preparar, cada pantalla enseña sus pasos en vez de un error: quien instala el
hub ve qué es, qué le falta y cómo se consigue, desde la propia pantalla. El
puente es además una herramienta opcional, apagada de fábrica (438): su
pantalla sólo sale en los menús si se enciende.

🔴 **Preparar no instala nada por su cuenta.** Abre una ventana en la carpeta
del componente con un encargo para Claude escrito y SIN Enter —el tercer caso
de la regla dura 15, el mismo de los kits (decisión 287)—. La sesión que
arranca la lanza la persona, y es ella la que da permiso a cada orden. Lo que
pide `sudo` (Node, ffmpeg, Xvfb) se le dice, no se hace.

El estudio no es un componente del clon sino un kit (decisión 461), pero se
prepara por esta misma puerta (C-0503, decisión 463): sus pasos, su encargo y
su ventana. Por eso no está en `NOMBRES`, que es lo que viaja en
`componentes/` (`publicacion.COMPONENTES`), y su ventana se abre en el clon
del hub, donde está `scripts/kit.sh`: el kit puede no estar aún en disco.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import config, maquina, mirar

NOMBRES = ("navegador-lab", "reuniones", "puente-kvm")
# Por el nombre de su pantalla, que es como lo llama quien lo usa.
ALIAS = {"navegante": "navegador-lab", "puente": "puente-kvm"}
# La pantalla de cada uno: a donde se vuelve si prepararlo falla.
PANTALLA = {"navegador-lab": "/navegante", "reuniones": "/reuniones", "puente-kvm": "/puente",
            "estudio": "/estudio"}

# 🔴 Los componentes viven DENTRO del clon, y `actualizar.sh` se niega a
# avanzar con cambios sin commit (paso 1). Por eso se preparan con
# `uv sync --frozen` y `npm ci`, que no reescriben `uv.lock` ni
# `package-lock.json`: un `npm install` que tocara el lock bloquearía la
# siguiente actualización sin que nadie supiera por qué.

# La variable que cambia la carpeta de cada uno. Son las de siempre: quien ya
# los tenía en otro sitio no tiene que tocar nada.
VARIABLE = {"navegador-lab": "NAV_LAB", "reuniones": "REUNIONES_PROYECTO", "puente-kvm": "PUENTE_KVM"}


def carpeta(nombre: str) -> Path:
    """La variable si está; si no, la copia del clon; si no, junto a los proyectos.

    El último caso es el de quien desarrolla el hub, que tiene los componentes
    como repos propios y no dentro del clon.
    """
    declarada = os.environ.get(VARIABLE[nombre])
    if declarada:
        return Path(declarada).expanduser()
    dentro = config.RAIZ_REPO / "componentes" / nombre
    if dentro.is_dir():
        return dentro
    return Path.home() / "projects" / nombre


def _hay_chrome() -> bool:
    # Elegir el navegador es de `mirar` (C-0052): el de Windows no cuenta, como
    # antes, y de la caché de Playwright sólo vale un binario de verdad.
    return bool(os.environ.get("NAV_CHROME") or mirar.cual_linux())


def paso(id_: str, titulo: str, hecho: bool, como: str, opcional: bool = False) -> dict:
    """Un paso de lo que le falta a un componente. Pública porque Reuniones
    cuenta con ella la mitad de Windows (`reuniones.preparacion`), y la
    pantalla pinta las dos mitades igual."""
    return {"id": id_, "titulo": titulo, "hecho": hecho, "como": como, "opcional": opcional}


def pasos_navegante() -> list[dict]:
    """Lo que necesita el laboratorio, en el orden en que se consigue."""
    lab = carpeta("navegador-lab")
    return [
        paso("componente", "El laboratorio está en el clon", (lab / "bin" / "nav").exists(),
              f"El hub lo busca en {lab}. Si lo tienes en otro sitio, arranca el hub con NAV_LAB."),
        paso("entorno", "Su entorno de Python y Node está preparado",
              (lab / ".venv").is_dir() and (lab / "node_modules").is_dir(),
              "uv sync --frozen y npm ci en su carpeta. «Preparar con Claude» lo hace contigo."),
        paso("chrome", "Hay un Chrome o Chromium que abrir", _hay_chrome(),
              "npx playwright install chromium en su carpeta, si no tienes Chrome instalado."),
        paso("xvfb", "Pantalla virtual (Xvfb)", bool(shutil.which("Xvfb")),
              "sudo apt install xvfb. Sin ella el navegador va sin ventana, y algunos sitios lo bloquean.",
              opcional=True),
    ]


def pasos_reuniones_wsl() -> list[dict]:
    """La mitad de WSL de Reuniones: el procesado. La de Windows la cuenta
    `reuniones.preparacion()`, que sabe del agente."""
    proyecto = carpeta("reuniones")
    return [
        paso("componente", "El procesado está en el clon", (proyecto / "pyproject.toml").exists(),
              f"El hub lo busca en {proyecto}. Si lo tienes en otro sitio, arranca el hub con REUNIONES_PROYECTO."),
        paso("entorno", "Su entorno de Python está preparado", (proyecto / ".venv").is_dir(),
              "uv sync --frozen en su carpeta. «Preparar con Claude» lo hace contigo; descarga Whisper, que pesa."),
        paso("ffmpeg", "ffmpeg, para comprimir las grabaciones", bool(shutil.which("ffmpeg")),
              "sudo apt install ffmpeg.", opcional=True),
        # Por `maquina.encontrar` y no `shutil.which`: en WSL está fuera del
        # PATH de la unit de `hub-web` (decisión 81, C-0119).
        paso("gpu", "GPU NVIDIA para transcribir rápido", bool(maquina.encontrar("nvidia-smi")),
              "Sin ella se transcribe en la CPU, mucho más despacio.", opcional=True),
    ]


def pasos_puente(estado: dict | None = None) -> list[dict]:
    """Lo que necesita el Puente KVM, en el orden en que se consigue.

    El último paso, «contesta», sólo va si se da el `estado` que midió
    `puente.estado()`: preguntarle al puente es cosa de su pantalla (438), y un
    paso que no se ha medido no se pinta ni hecho ni por hacer (regla dura 13).
    """
    from . import salud

    raiz = carpeta("puente-kvm")
    servicio = salud.estado_servicio("puente-kvm")
    if servicio is None:
        # Sin systemd no hay servicio que mirar: «parado» sería mentira, y lo
        # que manda entonces es que conteste.
        paso_servicio = paso(
            "servicio", "Su servicio arranca solo", False,
            "Aquí no hay systemd de usuario: arráncalo en su carpeta, en su propia ventana, con "
            f"{TRABAJO_FUERA} bash scripts/arrancar.sh (Ctrl+C lo para). {POR_QUE_TRABAJO_FUERA}",
            opcional=True)
    else:
        paso_servicio = paso(
            "servicio", "Su servicio arranca solo",
            servicio["habilitado"] and servicio["activo"] == "active",
            f"En su carpeta, {TRABAJO_FUERA} bash scripts/servicio.sh unidad enseña lo que "
            f"instalaría, y {TRABAJO_FUERA} bash scripts/servicio.sh instalar lo deja como "
            "servicio de usuario, sólo en esta máquina: con la misma variable delante en las dos, "
            f"para que la unidad que ves sea la que se instala. {POR_QUE_TRABAJO_FUERA} "
            "«Preparar con Claude» lo hace contigo.")
    pasos = [
        paso("componente", "El puente está en el clon", (raiz / "pyproject.toml").is_file(),
             f"Viene con el hub, en componentes/puente-kvm; el hub lo busca en {raiz}. Si lo "
             "tienes en otro sitio, arranca el hub con PUENTE_KVM."),
        paso("entorno", "Su entorno de Python está preparado", (raiz / ".venv").is_dir(),
             "uv sync --frozen en su carpeta, que no reescribe uv.lock. «Preparar con Claude» "
             "lo hace contigo."),
        paso_servicio,
    ]
    if estado is not None:
        pasos.append(paso(
            "contesta", "Contesta en esta máquina", bool(estado.get("vivo")),
            f"Ahora: {estado.get('motivo') or 'no contesta'}. En su carpeta, uv run --frozen "
            "puente-kvm comprobar --sin-entrar dice qué le falta sin entrar en el JetKVM; si el "
            "servicio está instalado, journalctl --user -u puente-kvm dice por qué no arranca."))
    return pasos


# 🔴 Dónde trabaja la sesión de Claude del puente: fuera del clon del hub. Con
# el puente en `componentes/` del clon y sin esto, Claude Code cargaría también
# el `CLAUDE.md` del hub (está en una carpeta de más arriba), y lo leído del Mac
# quedaría dentro de una carpeta que se vuelve a clonar. El puente prepara esa
# carpeta solo (enlaces a sus reglas y skills, y su `.mcp.json`).
TRABAJO_FUERA = 'PUENTE_TRABAJO="$HOME/puente-trabajo"'
POR_QUE_TRABAJO_FUERA = ("PUENTE_TRABAJO es la carpeta donde trabaja Claude: fuera del clon del hub, "
                         "para que lo leído del Mac no quede dentro y Claude no cargue las reglas del hub.")


def pasos_estudio(estado: dict | None = None) -> list[dict]:
    """Lo que necesita el estudio, en el orden en que se consigue (C-0503).

    Como en `pasos_puente`, «contesta» sólo va con el `estado` que midió
    `estudio.estado()`. 🔴 Ningún paso le pide a la persona que escriba un
    comando: lo que falte lo hace la sesión de «Preparar con Claude», y los
    comandos van sólo en su encargo. Sin el kit en el catálogo no hay de dónde
    traerlo, y el paso lo dice sin ofrecer nada."""
    from . import estudio, salud

    hay_systemd = salud.hay_systemd_de_usuario()
    if estudio.en_catalogo():
        como_kit = ("«Preparar con Claude» lo trae del catálogo de kits, en la versión publicada, "
                    "y lo instala contigo.")
    else:
        # El `kits.yml` del repo lo trae (C-0503): esto es un clon al que se
        # lo quitaron, y entonces no hay orden que dar ni botón que ofrecer.
        como_kit = "No está en el catálogo de kits de este hub, así que no hay de dónde traerlo."
    pasos = [
        paso("kit", "El kit «estudio» está en esta máquina", estudio.kit() is not None, como_kit),
        paso("systemd", "Hay systemd de usuario, para que arranque solo", hay_systemd,
             "Aquí no lo hay: «Preparar con Claude» lo instala sin servicio y lo deja corriendo "
             "en una ventana propia. Al reiniciar la máquina no vuelve solo: se arranca otra vez "
             "con «Preparar con Claude».", opcional=True),
    ]
    if estado is not None:
        # 🔴 Ni un comando para la persona (C-0503): instalado y sin contestar
        # también lo resuelve la sesión, que lo arranca y mira por qué no.
        ahora = f"Ahora: {estado.get('motivo') or 'no contesta'}."
        if pasos[0]["hecho"] or estudio.en_catalogo():
            ahora += (" Si ya estaba instalado, «Preparar con Claude» lo arranca, mira contigo por "
                      "qué no contestaba y te lo dice.")
        pasos.append(paso("contesta", "Contesta en esta máquina", bool(estado.get("vivo")), ahora))
    return pasos


def listo(pasos: list[dict]) -> bool:
    return all(p["hecho"] for p in pasos if not p["opcional"])


ENCARGOS = {
    "navegador-lab": (
        "Prepara este laboratorio para la pantalla Navegante del hub, siguiendo README.md "
        "(«Arrancar de cero»), pero con uv sync --frozen y npm ci, que no reescriben los archivos "
        "de bloqueo; si no hay Chrome ni Chromium en el PATH, "
        "npx playwright install chromium. Pide permiso antes de cada orden. Si falta algo del "
        "sistema (Node y npm, Xvfb), dime el comando exacto y espera a que lo instale yo: no uses "
        "sudo. Al terminar comprueba con bin/nav estado y dime que vuelva a la pantalla Navegante."
    ),
    "reuniones": (
        "Prepara el procesado de la pantalla Reuniones del hub en esta carpeta, siguiendo "
        "README.md: uv sync --frozen, que no reescribe uv.lock. Comprueba si hay ffmpeg y una GPU NVIDIA (nvidia-smi). Pide permiso "
        "antes de cada orden. Si falta algo del sistema, dime el comando exacto y espera a que lo "
        "instale yo: no uses sudo. Al terminar dime que siga en la pantalla Reuniones, que "
        "guía la instalación del agente de Windows."
    ),
    # 🔴 La contraseña del JetKVM no la escribe Claude ni la pide: va en el
    # archivo de entorno del puente, fuera del repo, y la pone la persona
    # (regla dura 5). El encargo dice dónde, y nada más.
    "puente-kvm": (
        "Prepara el Puente KVM para la pantalla Puente KVM del hub, siguiendo INSTALAR.md: "
        "uv sync --frozen, que no reescribe uv.lock, y uv run --frozen puente-kvm comprobar "
        "--sin-entrar para ver qué falta. Usa siempre uv run --frozen, y no hagas git pull en "
        "esta carpeta: el hub se actualiza con su propio actualizador. Si esta carpeta está "
        "dentro del clon del hub (componentes/puente-kvm), propón "
        "PUENTE_TRABAJO=\"$HOME/puente-trabajo\" (u otra carpeta fuera del clon que elija yo), "
        "para que lo leído del Mac no quede dentro del clon y la sesión del puente no cargue el "
        "CLAUDE.md del hub. Con systemd, enséñame la unidad con esa variable delante "
        "(PUENTE_TRABAJO=… bash scripts/servicio.sh unidad) y, si te digo que sí, instálala con "
        "la misma (PUENTE_TRABAJO=… bash scripts/servicio.sh instalar); sin systemd, dime que "
        "lo arranque yo en una ventana aparte con PUENTE_TRABAJO=… bash scripts/arrancar.sh. "
        "Pide permiso antes de cada orden. Si falta algo del sistema, dime el comando exacto y "
        "espera a que lo instale yo: no uses sudo. La contraseña del JetKVM NO la escribas, no "
        "la leas ni me la pidas: dime que va en ~/.config/puente-kvm/entorno como "
        "JETKVM_CLAVE=…, con permisos 600, y que la ponga yo; la dirección del aparato se elige "
        "en Ajustes, en la web del puente. Al terminar, uv run --frozen puente-kvm comprobar "
        "--sin-entrar (sin --sin-entrar entraría en el JetKVM y le cerraría su web), y dime que "
        "vuelva a la pantalla Puente KVM del hub, que dice si contesta."
    ),
    # 🔴 La ventana se abre en el clon del hub sólo para usar su scripts/kit.sh:
    # el encargo no toca nada más de esta carpeta. `install.sh` es de otro
    # repositorio y escribe una unidad de usuario: lo lanza esta sesión, con la
    # persona delante y su permiso, nunca `hub-web` (decisiones 121, 138 y 400).
    "estudio": (
        "Deja el estudio del hub funcionando en esta máquina, contestando en "
        "http://127.0.0.1:{puerto}/. Estás en la carpeta del hub sólo para usar su gestor de "
        "kits: no cambies nada de ella. 1) bash scripts/kit.sh ruta estudio dice dónde está el "
        "kit; si dice que no está instalado, o si su versión es más vieja que la versión del "
        "catálogo (la de kits.yml), bash scripts/kit.sh instalar estudio, que clona la "
        "versión del catálogo; usa después esa ruta nueva. Lee su README.md y su install.sh antes de correr nada. 2) Mira si "
        "hay systemd de usuario (systemctl --user show-environment). 3) Con systemd: si la "
        "unidad estudio ya existe (systemctl --user cat estudio), arráncala (systemctl --user "
        "restart estudio), y si acabas de instalar una versión nueva, antes bash \"<ruta del kit>/install.sh\"{opcion_puerto} "
        "para que la unidad apunte a ella y después systemctl --user restart estudio, porque "
        "install.sh no la reinicia si ya corría; si no existe, bash \"<ruta del kit>/install.sh\"{opcion_puerto}, que la deja "
        "y la arranca. Sin systemd: bash \"<ruta del kit>/install.sh\" --sin-servicio"
        "{opcion_puerto}, y arranca el comando que imprime al final en una ventana de tmux "
        "(si ya hay una ventana estudio con una versión vieja corriendo, ciérrala antes, o la "
        "nueva no podrá usar el puerto) "
        "aparte de esta misma sesión (tmux new-window -d -n estudio …), para que siga vivo "
        "cuando cierres esta y yo vea su registro en Trabajo. 4) Comprueba que contesta: "
        "http://127.0.0.1:{puerto}/api/salud tiene que decir \"vivo\": true y su \"version\" la "
        "del catálogo (con curl o con python3). Si no contesta, averigua por qué (con "
        "systemd, journalctl --user -u estudio -n 50; sin él, la ventana de tmux), arréglalo "
        "si está en tu mano y vuelve a comprobar. Pide permiso antes de cada orden. Si falta "
        "python3 3.10 o más, git o claude, dime qué es y el comando exacto, y espera a que lo "
        "instale yo: no uses sudo. Al terminar dime en llano si contesta, y que vuelva a la "
        "pantalla Estudio del hub y pulse «Volver a mirar». Su web escucha sólo en 127.0.0.1: "
        "no la abras a la red ni la publiques."
    ),
}


def _encargo(nombre: str) -> str:
    """El encargo de `ENCARGOS`, con el puerto del estudio puesto: el que busca
    el hub, para que lo instalado sea lo que la pantalla va a mirar."""
    if nombre != "estudio":
        return ENCARGOS[nombre]
    from . import estudio
    n = estudio.puerto()
    opcion = "" if n == estudio.PUERTO_POR_OMISION else f" --puerto {n}"
    return ENCARGOS[nombre].format(puerto=n, opcion_puerto=opcion)


def _donde_se_prepara(nombre: str) -> Path:
    """La carpeta de la ventana: la del componente; la del estudio, el clon del
    hub, porque su kit puede no estar aún en disco."""
    if nombre == "estudio":
        from . import estudio, opcionales
        if not opcionales.encendida("estudio"):
            # Apagado, el hub se ve como si no existiera (438, 461).
            raise ValueError("el estudio está apagado en esta instalación: se enciende en "
                             "Ajustes → Guía, en «Herramientas opcionales»")
        if estudio.kit() is None and not estudio.en_catalogo():
            # Sin kit y sin catálogo el encargo fallaría en su primera orden.
            raise ValueError("el kit «estudio» no está instalado ni en el catálogo de kits de este "
                             "hub, así que no hay de dónde traerlo")
        return config.RAIZ_REPO
    return carpeta(nombre)


def preparar(nombre: str) -> dict:
    """La ventana en la carpeta del componente con el encargo escrito y sin Enter."""
    from . import agentes, slots, tmux

    nombre = ALIAS.get(nombre, nombre)
    if nombre not in ENCARGOS:
        raise ValueError(f"no hay ningún componente «{nombre}»: son navegante, reuniones, puente "
                         "y estudio")
    destino = _donde_se_prepara(nombre)
    if not destino.is_dir():
        raise ValueError(f"no está en {destino}")
    pane_id = slots.abrir_en(str(destino), f"preparar-{nombre}", "hub",
                             agentes.comando(_encargo(nombre)))
    indice = next((p["window_idx"] for p in tmux.listar_paneles() if p["pane_id"] == pane_id), None)
    return {"session": "hub", "ventana": indice}
