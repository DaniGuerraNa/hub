"""Avisos por Web Push a la app del teléfono (decisiones 310 y 311).

El mensaje va cifrado de punta a punta (`cifrado_push`): el servicio de push
del navegador (Google para Chrome, Apple para Safari) lo transporta pero no
lo puede leer. Por eso puede llevar el texto del aviso (decisión 302) y no
sólo un «tienes algo».

🔴 **La clave VAPID es una llave** (regla dura 5): quien la tenga puede mandar
avisos a los aparatos suscritos. Vive en `~/.secretos/secretario-webpush/`
con permisos 600 y sólo la abre `hub-secretario`. Lo que `hub-web` necesita
—la mitad pública, para que el navegador se suscriba— se escribe aparte en
`HUB_HOME/secretario/push_publica.txt`.

Respuestas del servicio de push que importan: 201 es «aceptado»; 404 y 410
son una suscripción muerta (desinstaló la app, revocó el permiso) y se borra;
lo demás cuenta como fallo de ese aparato y se dice en la pantalla.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ... import llavero
from .. import cifrado_push as cp
from .. import memoria, piezas
from . import Aviso, Canal

#: El texto se recorta para que el mensaje cifrado no pase de ~4 KB.
TOPE_TEXTO = 1500
#: Lo que de verdad manda es el tamaño en BYTES (C-0432): 4 096 de cuerpo
#: cifrado es lo que el RFC 8030 garantiza y lo que admiten FCM y Apple. Al
#: cifrar se suman la cabecera (sal 16 + tamaño de registro 4 + largo de la
#: clave 1 + clave 65) y el delimitador (1) con la etiqueta de AES-GCM (16):
#: quedan 3 993 bytes para el JSON. Contar caracteres dejaba pasar 1 500
#: emoji (6 240 bytes cifrados): el servicio lo rechazaba y no llegaba.
TOPE_BYTES = 4096 - (16 + 4 + 1 + 65) - (1 + 16)
#: Un título más largo no se lee en una notificación; recortarlo es lo
#: primero cuando no cabe.
TOPE_TITULO = 120
#: Un aviso que no se pudo entregar en un día ya no sirve.
TTL = 24 * 3600


def carpeta() -> Path:
    return Path(os.environ.get("HUB_SECRETARIO_WEBPUSH", "~/.secretos/secretario-webpush")).expanduser()


#: Para el inventario del llavero (C-0143): dónde vive, nunca el valor.
LLAVES = (llavero.Llave("secretario-webpush", "las llaves VAPID de los avisos al teléfono", lambda: str(carpeta())),)


def _ruta_publica(crear: bool = False) -> Path:
    return memoria.carpeta(crear=crear) / "push_publica.txt"


def preparar() -> str:
    """Crea el par VAPID si no existe y deja la pública donde la lee la web. Devuelve la pública."""
    d = carpeta()
    privada_ruta = d / "vapid.key"
    if not privada_ruta.is_file():
        from cryptography.hazmat.primitives.asymmetric import ec
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        clave = ec.generate_private_key(ec.SECP256R1())
        crudo = clave.private_numbers().private_value.to_bytes(32, "big")
        privada_ruta.write_text(cp.b64(crudo), encoding="utf-8")
        os.chmod(privada_ruta, 0o600)
    publica = cp.b64(cp.publica_cruda(_privada()))
    if not _ruta_publica().is_file() or _ruta_publica().read_text(encoding="utf-8").strip() != publica:
        _ruta_publica(crear=True).write_text(publica, encoding="utf-8")
    return publica


def _privada():
    return cp.privada_desde_cruda(cp.d64((carpeta() / "vapid.key").read_text(encoding="utf-8")))


def publica() -> str | None:
    """La pública, para la web. None si el servicio aún no la preparó."""
    try:
        return _ruta_publica().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _contacto() -> str:
    """El `sub` de VAPID: a quién escribe el servicio de push si hay un problema.

    Apple rechaza el JWT (`BadJwtToken`) si no es un `mailto:` o un `https:`
    con forma válida, así que se valida aquí y no se manda uno inventado.
    """
    c = str(piezas.ajuste("contacto_push") or "").strip()
    if c.startswith("https://") or (c.startswith("mailto:") and "@" in c):
        return c
    return "mailto:secretario@hub.invalid"


def _enviar(sub: dict, cuerpo: bytes, urgente: bool) -> int:
    origen = urlparse(sub["endpoint"])
    cabeceras = {
        "TTL": str(TTL),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "Urgency": "high" if urgente else "normal",
        "Authorization": cp.vapid(f"{origen.scheme}://{origen.netloc}", _contacto(), _privada()),
    }
    req = urllib.request.Request(sub["endpoint"], data=cuerpo, method="POST", headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def carga(aviso: Aviso, origen: str) -> dict:
    """Lo que viaja dentro del mensaje cifrado.

    En el formato **declarativo** de Apple (`web_push: 8030`, iOS 18.4+): el
    sistema enseña la notificación aunque el service worker falle, y en iOS
    un push que no acaba en notificación hace que Safari retire el permiso.
    El service worker lee lo mismo (`notification`) más lo propio
    (`secretario`), así que un navegador sin declarativo lo pinta igual.
    """
    destino = (origen.rstrip("/") + (aviso.enlace or "/secretario")) if origen else (aviso.enlace or "/secretario")
    datos: dict = {"web_push": 8030, "notification": {
        "title": aviso.titulo, "body": aviso.texto[:TOPE_TEXTO], "navigate": destino}}
    if aviso.solicitud is not None:
        datos["secretario"] = {"solicitud": aviso.solicitud, "decidir": aviso.decidir_desde_aviso}
    elif aviso.compromiso is not None:
        datos["secretario"] = {"compromiso": aviso.compromiso}
    return _que_quepa(datos)


def claro(datos: dict) -> bytes:
    """Lo que se cifra, tal como viaja: lo que mide el tope es esto."""
    return json.dumps(datos, ensure_ascii=False).encode()


def _que_quepa(datos: dict) -> dict:
    """Recorta título y cuerpo hasta que `claro(datos)` quepa en `TOPE_BYTES`
    (C-0432). Primero el título, a `TOPE_TITULO`; luego el cuerpo, lo justo,
    con «…». Se recorta por caracteres y se mide en bytes del JSON ya
    codificado (lo que escapa JSON cuenta), así que nunca se parte un
    carácter en UTF-8."""
    n = datos["notification"]

    def cabe() -> bool:
        return len(claro(datos)) <= TOPE_BYTES

    if cabe():
        return datos
    titulo = str(n["title"] or "")
    if len(titulo) > TOPE_TITULO:
        n["title"] = titulo[:TOPE_TITULO - 1].rstrip() + "…"
        if cabe():
            return datos
    cuerpo = str(n["body"] or "")
    # El trozo más largo que cabe con su «…»: por bisección, que con 1 500
    # caracteres son once medidas y no mil.
    bajo, alto = 0, len(cuerpo)
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        n["body"] = cuerpo[:medio].rstrip() + "…"
        if cabe():
            bajo = medio
        else:
            alto = medio - 1
    n["body"] = cuerpo[:bajo].rstrip() + "…"
    return datos


class CanalWebPush(Canal):
    id = "webpush"
    nombre = "la app del teléfono"

    def disponible(self):
        if not (carpeta() / "vapid.key").is_file():
            return "falta preparar las claves (lo hace el servicio al arrancar)"
        # Sólo mira: lo pinta también `hub-web`, que no crea ni migra la
        # memoria (C-0061, C-0099). Sin base, no hay aparatos.
        con = memoria.abrir_lectura()
        if con is None:
            return "ningún aparato tiene los avisos activados"
        try:
            if not memoria.suscripciones(con):
                return "ningún aparato tiene los avisos activados"
        finally:
            con.close()
        return None

    def mandar(self, aviso: Aviso) -> None:
        con = memoria.conectar()
        try:
            entregados, errores = 0, []
            for s in memoria.suscripciones(con):
                # Cada aparato en su `try`, y con todo (C-0433): una dirección
                # mal formada lanza `http.client.InvalidURL`, que no es `OSError`
                # ni `ValueError`, y cortaba el bucle sin probar los demás ni
                # apuntar en cuál fue. Lo que falle se anota en el suyo.
                try:
                    mensaje = claro(carga(aviso, s["origen"]))
                    estado = _enviar(s, cp.cifrar(mensaje, s["p256dh"], s["auth"]), aviso.solicitud is not None)
                except Exception as exc:  # noqa: BLE001 — se apunta en ese aparato y se sigue
                    estado, motivo = 0, str(exc) or type(exc).__name__
                else:
                    motivo = f"el servicio de push respondió {estado}"
                if 200 <= estado < 300:
                    entregados += 1
                    memoria.anotar_entrega(con, s["id"], ok=True)
                elif estado in (404, 410):
                    # El aparato ya no existe para el servicio: se borra y se dice.
                    memoria.desuscribir(con, sid=s["id"])
                    memoria.apuntar(con, "avisos", resultado=f"aparato dado de baja ({estado}): {s['aparato']}")
                else:
                    errores.append(motivo)
                    memoria.anotar_entrega(con, s["id"], ok=False, error=motivo)
        finally:
            con.close()
        if not entregados:
            raise RuntimeError("; ".join(errores) or "ningún aparato aceptó el aviso")


PROVEEDOR = CanalWebPush()
