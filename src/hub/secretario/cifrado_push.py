"""El cifrado de Web Push, a mano y sin `pywebpush` (decisión 311).

Dos RFC y nada más:

- **RFC 8291** (cifrado del mensaje, `aes128gcm`): ECDH P-256 con la clave
  del navegador, HKDF y AES-128-GCM en un solo registro. El servicio de push
  (Google, Apple, Mozilla) lleva el mensaje pero **no puede leerlo**: sólo lo
  descifra el aparato que se suscribió.
- **RFC 8292** (VAPID): un JWT ES256 firmado con la clave del secretario, que
  le dice al servicio de push que el remitente es quien creó la suscripción.

`pywebpush` hace lo mismo arrastrando `requests`, `aiohttp`, `http-ece` y
`py-vapid`; aquí son unas cien líneas sobre `cryptography`, comprobadas
contra los valores del apéndice A del RFC 8291
(`tests/test_secretario_push.py`), que es lo que de verdad dice que está bien.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: Un solo registro: el mensaje entero cabe (el tope práctico es ~4 KB).
TAM_REGISTRO = 4096


def b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def d64(texto: str) -> bytes:
    texto = "".join(texto.split())
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _hkdf(sal: bytes, ikm: bytes, info: bytes, largo: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=largo, salt=sal, info=info).derive(ikm)


def publica_cruda(clave: ec.EllipticCurvePrivateKey) -> bytes:
    """La pública sin comprimir (65 bytes, empieza por 0x04): lo que piden el navegador y VAPID."""
    return clave.public_key().public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint)


def cifrar(mensaje: bytes, p256dh: str, auth: str, *, privada_efimera: ec.EllipticCurvePrivateKey | None = None,
           sal: bytes | None = None) -> bytes:
    """El cuerpo `aes128gcm` listo para mandar: cabecera + texto cifrado.

    `privada_efimera` y `sal` sólo se pasan en los tests, para reproducir el
    apéndice A; en uso real se generan nuevas en cada mensaje.
    """
    ua_publica = d64(p256dh)
    secreto_auth = d64(auth)
    efimera = privada_efimera or ec.generate_private_key(ec.SECP256R1())
    as_publica = publica_cruda(efimera)
    sal = sal or os.urandom(16)

    ua = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_publica)
    ecdh = efimera.exchange(ec.ECDH(), ua)
    ikm = _hkdf(secreto_auth, ecdh, b"WebPush: info\x00" + ua_publica + as_publica, 32)
    cek = _hkdf(sal, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(sal, ikm, b"Content-Encoding: nonce\x00", 12)
    # 0x02 marca el último (y único) registro.
    cifrado = AESGCM(cek).encrypt(nonce, mensaje + b"\x02", None)
    cabecera = sal + struct.pack("!I", TAM_REGISTRO) + bytes([len(as_publica)]) + as_publica
    return cabecera + cifrado


def vapid(audiencia: str, contacto: str, privada: ec.EllipticCurvePrivateKey, ahora: float | None = None) -> str:
    """La cabecera `Authorization` de VAPID para el servicio de push de `audiencia`."""
    def parte(d: dict) -> str:
        return b64(json.dumps(d, separators=(",", ":")).encode())

    cuerpo = parte({"typ": "JWT", "alg": "ES256"}) + "." + parte(
        {"aud": audiencia, "exp": int((ahora or time.time()) + 12 * 3600), "sub": contacto})
    r, s = decode_dss_signature(privada.sign(cuerpo.encode(), ec.ECDSA(hashes.SHA256())))
    firma = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={cuerpo}.{b64(firma)}, k={b64(publica_cruda(privada))}"


def privada_desde_cruda(d: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(d, "big"), ec.SECP256R1())
