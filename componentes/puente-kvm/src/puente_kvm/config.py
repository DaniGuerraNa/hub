"""Dónde vive cada cosa y qué ajustes hay.

Cuatro sitios, y ninguno depende de dónde se clonó el código:
- el **código** (`CODIGO`): este repositorio, esté donde esté;
- los **datos del puente** (`PUENTE_HOME`, por omisión `~/.local/share/puente-kvm`):
  ajustes, bitácora, lecturas y cambios;
- el **espacio de trabajo** de Claude (`PUENTE_TRABAJO`, por omisión la carpeta
  del código): donde corre su sesión y donde está `trabajo/`, lo que se trae
  del Mac. Fuera del código, lo leído no queda dentro de un clon, y Claude no
  carga el `CLAUDE.md` de otro repositorio que contenga a éste;
- la **contraseña** del JetKVM (`PUENTE_ENTORNO`, por omisión
  `~/.config/puente-kvm/entorno`, permisos 600), que sólo lee el servicio.

Los ajustes están en `PUENTE_HOME/ajustes.json`. **Ninguna contraseña se
guarda ahí**: la del JetKVM se lee de la variable que diga `clave_env`
(por omisión `JETKVM_CLAVE`). En el archivo sólo está el puntero.
"""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from pathlib import Path

CODIGO = Path(__file__).resolve().parents[2]

PUERTO = int(os.environ.get("PUENTE_PUERTO", "8794"))
HOST = "127.0.0.1"
# Los únicos nombres por los que se admite una petición, sin comodines.
# Escuchar en 127.0.0.1 no basta: una web ajena que se haga resolver a
# 127.0.0.1 (DNS rebinding) manda su propio Host y su propio Origin, que
# coinciden entre sí. Con una terminal dentro, eso es una shell.
HOSTS = {f"127.0.0.1:{PUERTO}", f"localhost:{PUERTO}"}


def _version() -> str:
    """La del `pyproject.toml` que había al arrancar: si después se actualiza el
    código y el servicio no se reinicia, el estado sigue diciendo la vieja, que
    es justo lo que se quiere ver."""
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', (CODIGO / "pyproject.toml").read_text(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("puente-kvm")
    except PackageNotFoundError:
        return "desconocida"


VERSION = _version()


class Codigo:
    """El código Python con que arrancó este proceso, para saber si el disco ya es otro.

    La versión no basta: no cambia en cada arreglo. Tras actualizar sin
    reiniciar, las pantallas (que se leen del disco en cada visita) salían
    nuevas y lo que hacían era lo de antes, sin que nada lo dijera (18-nov).
    Se miran tamaño y fecha de cada `.py`, que es barato; sólo si cambian se
    compara el contenido, una vez por cambio: un checkout que vuelve a
    escribir lo mismo no es código nuevo.
    """

    def __init__(self, carpeta: Path = Path(__file__).resolve().parent):
        self.carpeta = carpeta
        self._marcas = self._leer_marcas()
        self._contenido = self._leer_contenido()
        self._ultima: tuple[dict, str] = (self._marcas, self._contenido)

    def _leer_marcas(self) -> dict[str, tuple[int, int]]:
        marcas = {}
        for f in sorted(self.carpeta.rglob("*.py")):
            try:
                st = f.stat()
            except OSError:
                continue
            marcas[str(f.relative_to(self.carpeta))] = (st.st_size, st.st_mtime_ns)
        return marcas

    def _leer_contenido(self) -> str:
        import hashlib

        h = hashlib.sha1()
        for nombre in sorted(self._leer_marcas()):
            h.update(nombre.encode() + b"\0")
            try:
                h.update((self.carpeta / nombre).read_bytes())
            except OSError:
                h.update(b"\0ilegible")
        return h.hexdigest()

    def huella_disco(self) -> str:
        """La huella del código que hay AHORA en el disco. La guarda cada
        conversación al abrirse (su servidor MCP nace con ese código), para
        saber después si sus herramientas son de antes de actualizar."""
        marcas = self._leer_marcas()
        if marcas != self._ultima[0]:
            self._ultima = (marcas, self._leer_contenido())
        return self._ultima[1]

    def viejo(self) -> bool:
        return self.huella_disco() != self._contenido


CODIGO_EN_MARCHA = Codigo()


def hogar() -> Path:
    ruta = Path(os.environ.get("PUENTE_HOME", Path.home() / ".local/share/puente-kvm"))
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def espacio() -> Path:
    """Donde corre la sesión de Claude: la carpeta del código, o `PUENTE_TRABAJO`."""
    otro = os.environ.get("PUENTE_TRABAJO")
    return Path(otro).expanduser().resolve() if otro else CODIGO


def trabajo() -> Path:
    """Lo que se trae del Mac y lo que Claude hace con ello. No entra en git."""
    return espacio() / "trabajo"


def entorno() -> Path:
    """El archivo con la contraseña del JetKVM (lo carga systemd o `arrancar.sh`)."""
    return Path(os.environ.get("PUENTE_ENTORNO", Path.home() / ".config/puente-kvm/entorno")).expanduser()


def variables_de_clave() -> set[str]:
    """Las variables de entorno que pueden llevar la contraseña: nunca salen del servicio."""
    nombres = {"JETKVM_CLAVE"}
    try:
        nombres.add(leer_ajustes()["dispositivo"].get("clave_env") or "JETKVM_CLAVE")
    except Exception:  # unos ajustes ilegibles no pueden dejar pasar la clave
        pass
    return {n for n in nombres if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n)}


# El perfil describe el programa del Mac donde se lee y escribe: sus atajos y
# dónde está el editor en la pantalla. Los valores por omisión son los de
# DBeaver en Mac; los de otro cliente se miden y se cambian en Ajustes.
PERFIL_POR_OMISION = {
    "nombre": "DBeaver (Mac)",
    "region_editor": [300, 98, 1620, 952],  # x, y, ancho, alto en la captura
    "inicio_documento": "cmd+up",
    "fin_documento": "cmd+down",
    "pagina_abajo": "pagedown",
    "ir_a_linea": "cmd+l",
    "fin_de_linea": "cmd+right",
    "distribucion": "mac-us",
    # Lo que el puente no pulsa nunca al teclear texto, ni al sondear el teclado:
    # en DBeaver para Mac, Opción+X es «Ejecutar script», y con ella salen `≈`
    # (U.S.) y `∑` (Español - ISO) (C-0481).
    "reservadas": ["alt+x"],
    "retardo_tecla_ms": 12,
    # Cuánto puede tardar el vídeo del aparato en enseñar una tecla (C-0485): el
    # del JetKVM llegó 1–2 s tarde, y 3 s dejan margen. Es un tope fijo (nada lo
    # baja solo): tras pulsar, el puente espera a VER el cambio hasta este tope
    # más un margen, y por eso sólo cuesta entero al final de un documento.
    "retardo_video_ms": 3000,
    "aparcar_raton": [1900, 1066],  # donde el puntero no tapa el texto
    # Con el desplazamiento natural de macOS la rueda va al revés: lo marca la
    # persona en Ajustes y el puente la invierte, para que «baja» siga bajando.
    "invertir_rueda": False,
}

# El modelo de Claude Code, por su id EXACTO: un alias («opus», «fable»)
# ha resuelto a modelos distintos la misma tarde, y sin `--model` hereda el
# que tenga configurado quien lo usa (así arrancó una vez con uno viejo).
# Ids medidos con Claude Code 2.1.322; Fable 5.2 pide esa versión o posterior.
# "" = sin `--model`: el que diga el Claude Code de la persona.
MODELOS = (
    ("claude-fable-5-2", "Fable 5.2, el más capaz"),
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5", "Sonnet 5"),
    ("", "El de mi Claude Code"),
)
MODELO_POR_OMISION = "claude-fable-5-2"
CLAUDE_CODE_PARA_FABLE = (2, 1, 322)


def validar_modelo(modelo: str) -> str:
    if modelo not in dict(MODELOS):
        raise ValueError("modelo desconocido: elige uno de la lista (Ajustes → Modelo de Claude)")
    return modelo


def texto_modelo(modelo: str) -> str:
    return dict(MODELOS).get(modelo, modelo).split(",")[0]


AJUSTES_POR_OMISION = {
    "dispositivo": {
        "tipo": "simulador",  # o "jetkvm"
        "url": "http://jetkvm.local",
        "clave_env": "JETKVM_CLAVE",
    },
    "perfil": PERFIL_POR_OMISION,
    # saltar_permisos: Claude Code sin pedir permiso para sus herramientas
    # (--dangerously-skip-permissions). Apagado de fábrica; lo enciende la persona.
    "claude": {"modelo": MODELO_POR_OMISION, "saltar_permisos": False},
    # Mediciones de uso sin contenido (C-0483, `mediciones.py`): encendidas de
    # fábrica, con su frase en Ajustes; se quedan en este equipo hasta que la
    # persona las prepare para mandarlas.
    "mediciones": {"activas": True},
    # Qué casillas salen marcadas en el diálogo «Dar el control» (C-0491, decisión
    # 460): sólo eso. El permiso lo da la persona al aceptar el diálogo, nunca este
    # ajuste: dar el control sin diálogo («Leer», «Escribir») no lleva ninguno. Las
    # claves son las de `control.PERMISOS`, lista cerrada.
    "permisos": {"correcciones": False},
}

_cerrojo = threading.Lock()


def permisos_por_omision(ajustes: dict) -> dict[str, bool]:
    """Los de `ajustes["permisos"]`, sólo con sus claves y sólo un verdadero de verdad:
    un ajustes.json escrito a mano no puede marcar por omisión otra cosa."""
    guardados = ajustes.get("permisos") or {}
    return {n: guardados.get(n) is True for n in AJUSTES_POR_OMISION["permisos"]}


def leer_ajustes() -> dict:
    ruta = hogar() / "ajustes.json"
    datos = deepcopy(AJUSTES_POR_OMISION)
    if ruta.exists():
        guardados = json.loads(ruta.read_text())
        for clave in datos:
            datos[clave].update(guardados.get(clave, {}))
    return datos


def guardar_ajustes(datos: dict) -> None:
    for seccion in datos.values():
        for clave in list(seccion):
            if "clave" in clave and clave != "clave_env":
                raise ValueError("los ajustes no guardan contraseñas: usa clave_env")
    ruta = hogar() / "ajustes.json"
    with _cerrojo:
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False))
        tmp.replace(ruta)
