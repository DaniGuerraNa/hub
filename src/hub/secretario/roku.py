"""Cliente mínimo de ECP, el control externo de una tele Roku (decisión 321).

ECP es HTTP sin contraseña al puerto 8060 **de la tele**: las peticiones salen
de la PC hacia ella, igual que cualquier visita a una web. El hub no abre nada
ni escucha en la red local (regla dura 8): si algún día hiciera falta que la
tele le pidiera algo al hub, estaría mal planteado.

Sólo lo que las acciones de `acciones/tele.py` usan: el estado, una lista
cerrada de teclas, las apps y abrir una. Escribir texto (`Lit_…`) y mandar
datos a una app (`/input`) quedan fuera a propósito: con ellos el modelo
podría teclear lo que quisiera en la tele.

Sin dependencias: urllib, sin proxy (una IP de casa no se alcanza por el proxy
de nadie) y con timeouts cortos, porque quien espera es una conversación.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import quote

PUERTO = 8060
#: Segundos por petición. La tele en la misma red contesta en milisegundos;
#: más de esto es que no está o no escucha.
TIMEOUT_S = 3.0
#: Lo más que se lee de una respuesta: device-info y la lista de apps ocupan
#: unos KB, y lo que pase de aquí no es una tele.
MAX_BYTES = 512 * 1024

#: Las únicas teclas que se mandan. Nada de `Lit_*` (escribir) ni `Search`.
TECLAS = frozenset({
    "PowerOn", "PowerOff",
    "Home", "Back", "Select", "Up", "Down", "Left", "Right", "Info",
    "Play", "Rev", "Fwd", "InstantReplay",
    "VolumeUp", "VolumeDown", "VolumeMute",
    "InputTuner", "InputHDMI1", "InputHDMI2", "InputHDMI3", "InputHDMI4", "InputAV1",
})
ENTRADAS = frozenset(t for t in TECLAS if t.startswith("Input"))

#: `power-mode` de device-info. Sólo `PowerOn` es pantalla encendida; el resto
#: es algún modo de espera (con Fast TV Start la tele sigue contestando).
ENCENDIDA = "PowerOn"

_ID_APP = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

AJUSTE = ("Ajustes → Sistema → Ajustes avanzados → «Control por apps móviles» "
          "en «Habilitado»")


class TeleError(RuntimeError):
    """Algo que el dueño puede arreglar, dicho para él."""


def validar_ip(ip: str) -> str:
    """Una IP de la red de casa, o error. Una pública no es una tele del cuarto:
    es un `secretario.yml` mal escrito, y no se le mandan teclas a internet."""
    try:
        d = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        raise TeleError(f"«{ip}» no es una IP: pon la de la tele, p. ej. 192.168.1.50") from None
    if not (d.is_private or d.is_loopback or d.is_link_local):
        raise TeleError(f"{d} no es una dirección de tu red de casa: la tele tiene una como 192.168.x.x")
    return str(d)


class Tele:
    def __init__(self, ip: str, puerto: int = PUERTO, timeout: float | None = None):
        self.ip = validar_ip(ip)
        self.puerto = int(puerto)
        self.timeout = TIMEOUT_S if timeout is None else timeout
        host = f"[{self.ip}]" if ":" in self.ip else self.ip
        self.base = f"http://{host}:{self.puerto}"
        # Sin proxy: `http_proxy` en el entorno mandaría la petición fuera de casa.
        self._abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _pedir(self, metodo: str, ruta: str) -> bytes:
        req = urllib.request.Request(self.base + ruta, data=b"" if metodo == "POST" else None, method=metodo)
        try:
            with self._abridor.open(req, timeout=self.timeout) as r:
                return r.read(MAX_BYTES)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # Lo que contesta desde Roku OS 14.1 con el ajuste en «Limitado».
                raise TeleError(f"la tele rechazó la orden (403): pon {AJUSTE}") from None
            raise TeleError(f"la tele contestó {exc.code} a {ruta}") from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
            raise TeleError(f"la tele no contesta en {self.ip}: ¿está enchufada y en la misma red? "
                            f"¿Está activado {AJUSTE}? Si estaba apagada, sin «Fast TV Start» "
                            "desaparece de la red") from None

    def _xml(self, ruta: str) -> ET.Element:
        try:
            return ET.fromstring(self._pedir("GET", ruta))
        except ET.ParseError:
            raise TeleError(f"lo que contesta {self.ip}:{self.puerto} no parece una tele Roku") from None

    # ── lo que se usa ───────────────────────────────────────────────────────

    def estado(self) -> dict:
        """`power-mode`, modelo y nombre, de `/query/device-info`."""
        x = self._xml("/query/device-info")

        def campo(n):
            return (x.findtext(n) or "").strip()

        modo = campo("power-mode")
        return {
            "encendida": modo == ENCENDIDA,
            "power_mode": modo or "desconocido",
            "modelo": " ".join(p for p in (campo("vendor-name"), campo("model-name")) if p),
            "nombre": campo("user-device-name") or campo("friendly-device-name") or campo("default-device-name"),
        }

    def activa(self) -> dict:
        """La app o la entrada que se ve: `{id, nombre}` (`tvinput.hdmi2` en una entrada)."""
        x = self._xml("/query/active-app")
        app = x.find("app")
        if app is None:
            return {"id": "", "nombre": ""}
        return {"id": app.get("id") or "", "nombre": (app.text or "").strip()}

    def tecla(self, nombre: str) -> None:
        if nombre not in TECLAS:
            raise TeleError(f"la tecla «{nombre}» no está permitida (hay: {', '.join(sorted(TECLAS))})")
        self._pedir("POST", f"/keypress/{nombre}")

    def apps(self) -> list[dict]:
        x = self._xml("/query/apps")
        return [{"id": a.get("id") or "", "nombre": (a.text or "").strip()}
                for a in x.findall("app") if a.get("id")]

    def abrir_app(self, app_id: str) -> None:
        if not _ID_APP.match(str(app_id)):
            raise TeleError(f"«{app_id}» no es un id de app de Roku")
        self._pedir("POST", f"/launch/{quote(str(app_id), safe='')}")


def id_de_entrada(tecla: str) -> str:
    """Cómo aparece una entrada en `/query/active-app`: InputHDMI2 → tvinput.hdmi2."""
    if tecla == "InputTuner":
        return "tvinput.dtv"
    return "tvinput." + tecla.removeprefix("Input").lower()
