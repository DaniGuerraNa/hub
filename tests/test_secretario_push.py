"""Web Push: el cifrado contra el RFC y el envío contra un servicio de push fingido (decisión 311)."""

from __future__ import annotations

import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from hub.secretario import cifrado_push as cp

# RFC 8291, apéndice A.
TEXTO = "V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24"
AS_PRIVADA = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLICA = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
SAL = "DGv6ra1nlYgDCS1FRnbzlw"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
# El mensaje completo de la sección 5: cabecera de 86 bytes y lo cifrado.
ESPERADO = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
            "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
            "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_el_cifrado_da_exactamente_lo_del_rfc_8291():
    cuerpo = cp.cifrar(cp.d64(TEXTO), UA_PUBLICA, AUTH,
                       privada_efimera=cp.privada_desde_cruda(cp.d64(AS_PRIVADA)), sal=cp.d64(SAL))
    # (El ejemplo del RFC pone `Content-Length: 145`, pero 86 + 41 + 1 + 16 son 144.)
    assert cuerpo == cp.d64(ESPERADO)


def test_lo_cifrado_lo_descifra_quien_tiene_la_clave_del_navegador():
    """El camino inverso, como lo haría el navegador: sin esto, el test del RFC
    sólo prueba un caso fijo, no que cualquier mensaje llegue entero."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    navegador = ec.generate_private_key(ec.SECP256R1())
    ua = cp.publica_cruda(navegador)
    auth = b"0123456789abcdef"
    cuerpo = cp.cifrar("¿Aprobar «crear slot»? ✅".encode(), cp.b64(ua), cp.b64(auth))
    sal, as_pub, cifrado = cuerpo[:16], cuerpo[21:86], cuerpo[86:]
    assert cuerpo[20] == 65
    ecdh = navegador.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = cp._hkdf(auth, ecdh, b"WebPush: info\x00" + ua + as_pub, 32)
    claro = AESGCM(cp._hkdf(sal, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(
        cp._hkdf(sal, ikm, b"Content-Encoding: nonce\x00", 12), cifrado, None)
    assert claro == "¿Aprobar «crear slot»? ✅".encode() + b"\x02"


def test_el_jwt_de_vapid_va_firmado_con_la_clave_que_anuncia():
    privada = ec.generate_private_key(ec.SECP256R1())
    cab = cp.vapid("https://web.push.apple.com", "mailto:quien@ejemplo.org", privada, ahora=1000)
    t = cab.split("t=")[1].split(",")[0]
    k = cab.split("k=")[1]
    cabeza, cuerpo, firma = t.split(".")
    datos = json.loads(cp.d64(cuerpo))
    assert datos == {"aud": "https://web.push.apple.com", "exp": 1000 + 12 * 3600, "sub": "mailto:quien@ejemplo.org"}
    assert json.loads(cp.d64(cabeza))["alg"] == "ES256"
    crudo = cp.d64(firma)
    publica = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), cp.d64(k))
    publica.verify(encode_dss_signature(int.from_bytes(crudo[:32], "big"), int.from_bytes(crudo[32:], "big")),
                   f"{cabeza}.{cuerpo}".encode(), ec.ECDSA(hashes.SHA256()))


# ── el canal de avisos, con un servicio de push fingido ─────────────────────

import os  # noqa: E402

import pytest  # noqa: E402

from hub.secretario import avisos, memoria, recordatorios  # noqa: E402
from hub.secretario.avisos import webpush  # noqa: E402


def _descifrar(cuerpo: bytes, navegador, auth: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua = cp.publica_cruda(navegador)
    sal, as_pub, cifrado = cuerpo[:16], cuerpo[21:86], cuerpo[86:]
    ecdh = navegador.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = cp._hkdf(auth, ecdh, b"WebPush: info\x00" + ua + as_pub, 32)
    claro = AESGCM(cp._hkdf(sal, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(
        cp._hkdf(sal, ikm, b"Content-Encoding: nonce\x00", 12), cifrado, None)
    return json.loads(claro[:-1])


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def aparato(con):
    """Un navegador suscrito, con su clave privada para leer lo que le llega."""
    webpush.preparar()
    navegador = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    memoria.suscribir(con, "https://push.ejemplo.org/abc", cp.b64(cp.publica_cruda(navegador)), cp.b64(auth),
                      "iPhone · Safari (app)", "https://hub.ejemplo.ts.net")
    return navegador, auth


@pytest.fixture
def servicio_push(monkeypatch):
    """Lo que recibiría el servicio de push; contesta lo que se le diga."""
    llegado = {"respuesta": 201, "envios": []}

    def enviar(sub, cuerpo, urgente):
        llegado["envios"].append({"sub": sub, "cuerpo": cuerpo, "urgente": urgente})
        return llegado["respuesta"]

    monkeypatch.setattr(webpush, "_enviar", enviar)
    return llegado


def test_preparar_crea_la_llave_privada_fuera_y_la_publica_para_la_web():
    publica = webpush.preparar()
    llave = webpush.carpeta() / "vapid.key"
    assert oct(llave.stat().st_mode & 0o777) == "0o600"
    assert webpush.publica() == publica and len(cp.d64(publica)) == 65
    assert webpush.preparar() == publica, "preparar dos veces no cambia la llave"
    assert not str(llave).startswith(str(memoria.carpeta())), "la llave no vive en HUB_HOME"


def test_un_aviso_llega_cifrado_y_el_aparato_lo_lee_en_formato_declarativo(con, aparato, servicio_push):
    navegador, auth = aparato
    assert avisos.mandar("Llamar a Ana", titulo="⏰ Recordatorio", enlace="/secretario?p=pendientes") == "webpush"
    datos = _descifrar(servicio_push["envios"][0]["cuerpo"], navegador, auth)
    assert datos["web_push"] == 8030
    assert datos["notification"] == {"title": "⏰ Recordatorio", "body": "Llamar a Ana",
                                     "navigate": "https://hub.ejemplo.ts.net/secretario?p=pendientes"}
    assert memoria.suscripciones(con)[0]["ultimo_ok"]


def test_una_solicitud_lleva_su_id_y_si_se_puede_decidir_desde_el_aviso(con, aparato, servicio_push):
    navegador, auth = aparato
    avisos.mandar("Crear un slot", solicitud=7, decidir_desde_aviso=True)
    envio = servicio_push["envios"][0]
    assert envio["urgente"] is True
    assert _descifrar(envio["cuerpo"], navegador, auth)["secretario"] == {"solicitud": 7, "decidir": True}


def test_lo_irreversible_llega_sin_botones(con, aparato, servicio_push, monkeypatch):
    from hub.secretario import herramientas, piezas

    class Borrar(piezas.Accion):
        id, riesgo, nivel_inicial, nombre = "borrar", "irreversible", "ask", "Borrar algo"

    navegador, auth = aparato
    herramientas.usar_accion(con, Borrar(), {}, motivo="me lo pidió")
    assert _descifrar(servicio_push["envios"][0]["cuerpo"], navegador, auth)["secretario"]["decidir"] is False


def test_un_aparato_que_ya_no_existe_se_borra_y_el_aviso_sale_por_telegram(con, aparato, servicio_push, canal_telegram):
    from hub import orquestador
    servicio_push["respuesta"] = 410
    assert avisos.mandar("hola") == "telegram"
    assert memoria.suscripciones(con) == []
    assert orquestador.timbres_pendientes()


def test_un_servicio_de_push_caido_deja_paso_al_respaldo_y_lo_apunta_en_el_aparato(con, aparato, servicio_push,
                                                                                    canal_telegram):
    servicio_push["respuesta"] = 500
    assert avisos.mandar("hola") == "telegram"
    s = memoria.suscripciones(con)[0]
    assert s["fallos"] == 1 and "500" in s["error"]


def test_sin_ningun_canal_el_recordatorio_espera_y_se_dice_una_vez(con):
    memoria.comprometer(con, "Llamar a Ana", recordar_en="2020-01-01T00:00:00+00:00")
    assert recordatorios.revisar(con) == 0
    assert recordatorios.revisar(con) == 0
    assert memoria.compromisos(con)[0]["recordado"] is None, "no se marca: se reintenta"
    assert "Telegram" in memoria.leer(con, "avisos_error")
    assert len([b for b in memoria.bitacora(con) if b["accion"] == "recordatorio"]) == 1


def test_el_respaldo_de_telegram_no_cuenta_como_listo_si_el_aviso_no_va_a_llegar(con):
    """C-0060: bastaba con que existiera `canal.yml`. Sin dueño en /canal el
    relé descarta el timbre, y sin un token que `hub-canal` haya leído se queda
    en la cola: en los dos casos la cadena apuntaba «salió por telegram» y el
    aviso no llegaba a nadie. Respaldo no es caer en silencio (306)."""
    from hub import canal, config, db, rele_base
    from hub.secretario.avisos import telegram as respaldo

    config.canal_yml().parent.mkdir(parents=True, exist_ok=True)
    config.canal_yml().write_text("token_ref: env:TOKEN_DE_PRUEBA\n", encoding="utf-8")
    assert "hub-canal" in respaldo.PROVEEDOR.disponible()

    rele_base.anotar_token("canal", "env:TOKEN_DE_PRUEBA", None)
    assert "dueño" in respaldo.PROVEEDOR.disponible()
    with pytest.raises(avisos.SinCanal):
        avisos.mandar("hola")

    h = db.conectar()
    db.inicializar(h)
    canal.anotar_contacto(h, 7, "quien", "Quien")
    canal.marcar_dueno(h, 7)
    h.close()
    assert respaldo.PROVEEDOR.disponible() is None
    assert avisos.mandar("hola") == "telegram"


def test_cuando_vuelve_a_haber_canal_sale_y_se_borra_el_error(con, canal_telegram):
    memoria.poner(con, "avisos_error", "nada")
    memoria.comprometer(con, "Llamar a Ana", recordar_en="2020-01-01T00:00:00+00:00")
    assert recordatorios.revisar(con) == 1
    assert memoria.leer(con, "avisos_error") is None


def test_el_aviso_de_prueba_lo_pide_la_web_y_lo_manda_el_servicio(con, aparato, servicio_push):
    from hub.secretario import servicio
    assert servicio.aviso_de_prueba(con) is None
    memoria.poner(con, "aviso_prueba", memoria.ahora())
    assert servicio.aviso_de_prueba(con) == "webpush"
    assert servicio.aviso_de_prueba(con) is None, "una vez por pulsación"


def test_una_suscripcion_sin_https_o_sin_claves_no_se_guarda(con):
    with pytest.raises(ValueError):
        memoria.suscribir(con, "http://push.ejemplo.org/x", "a", "b")
    with pytest.raises(ValueError):
        memoria.suscribir(con, "https://push.ejemplo.org/x", "", "b")
