"""El bot de encargos: las cuatro capacidades que el canal de consulta NO tiene.

🔴 El test que más pesa de este archivo es el que mira la clase `Bot`. Que sean
dos clases y no una con cuatro métodos más es deliberado —está escrito en el
docstring de `BotDeEncargos`—: cada método de `Bot` es una capacidad que alguien
de fuera podría acabar teniendo, y el canal de consulta existe para que sólo haya
dos, preguntar y recibir. Añadir un método «porque es igual y ya está el código»
no rompe nada visible el día que se hace; se ve tres meses después, cuando el
bot que habla con gente de fuera resulta que sabe bajar archivos. Por eso hace
falta que lo rompa un test.

Aquí tampoco se sale a internet: se sustituye `urlopen` por un doble que además
**guarda cada petición**, porque de `enviar_foto` lo que hay que comprobar no es
lo que devuelve sino el cuerpo que arma a mano.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse

import pytest

from hub import telegram


# ── el doble de red ───────────────────────────────────────────────────────────


class _Cuerpo:
    """Lo que `urlopen` devuelve: un contexto con `.read()`."""

    def __init__(self, datos: bytes):
        self._datos = datos

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self._datos


class _CuerpoCortado(_Cuerpo):
    """Una respuesta que revienta a media lectura.

    Es el caso por el que existe el temporal de `descargar`: la conexión se cae
    con el audio a medias y lo que quede en disco parecerá un audio bueno.
    """

    def read(self) -> bytes:
        raise OSError("conexión cortada a media descarga")


class RedFalsa:
    """Sustituye a `urlopen` y apunta lo que se le pidió, en orden.

    Guardar las peticiones no es comodidad: un `multipart/form-data` armado a
    mano cuyo boundary no case con el declarado en la cabecera es una foto que
    Telegram rechaza entera, y eso no se ve en el valor de vuelta.
    """

    def __init__(self, *respuestas):
        self._pendientes = list(respuestas)
        self.peticiones: list = []

    def __call__(self, peticion, timeout=None):
        self.peticiones.append(peticion)
        assert self._pendientes, "la red recibió más llamadas de las previstas"
        siguiente = self._pendientes.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        if isinstance(siguiente, _Cuerpo):
            return siguiente
        if isinstance(siguiente, bytes):
            return _Cuerpo(siguiente)
        return _Cuerpo(json.dumps(siguiente).encode())

    def url(self, i: int) -> str:
        peticion = self.peticiones[i]
        return peticion if isinstance(peticion, str) else peticion.full_url


def montar(monkeypatch, *respuestas) -> tuple[telegram.BotDeEncargos, RedFalsa]:
    red = RedFalsa(*respuestas)
    monkeypatch.setattr(telegram.urllib.request, "urlopen", red)
    return telegram.BotDeEncargos("123:abc"), red


def boundary_de(peticion) -> str:
    """El boundary tal y como lo anuncia la cabecera, que es el que vale."""
    tipo = peticion.get_header("Content-type") or ""
    assert tipo.startswith("multipart/form-data; boundary="), tipo
    return tipo.split("boundary=", 1)[1]


# ── la separación entre los dos bots ─────────────────────────────────────────


def test_el_canal_de_consulta_sigue_teniendo_solo_preguntar_y_recibir():
    """🔴 El test que justifica que haya dos clases.

    `Bot` es el cliente del canal por el que habla gente de fuera. Su cabecera
    promete que sólo sabe hacer dos cosas, y esa promesa es lo que permite
    razonar sobre lo que puede salir de la máquina (regla dura 22). Un método
    más aquí —aunque sea el mismo código que ya existe en la subclase— convierte
    esa frase en mentira sin que ninguna pantalla cambie.
    """
    publicos = {
        nombre for nombre, valor in vars(telegram.Bot).items()
        if callable(valor) and not nombre.startswith("_")
    }
    assert publicos == {"enviar", "actualizaciones"}, (
        "alguien le ha añadido capacidades al bot del canal de consulta: "
        f"{sorted(publicos)}. Si hacen falta, van en `BotDeEncargos`, que es "
        "otro bot con otro token y en otro servicio."
    )


def test_lo_que_hace_falta_para_los_encargos_vive_en_la_subclase():
    """Las cuatro de la decisión 221, ni una más: si aparece una quinta, que se
    escriba aquí con su motivo en vez de colarse."""
    anadidos = {
        nombre for nombre, valor in vars(telegram.BotDeEncargos).items()
        if callable(valor) and not nombre.startswith("_")
    }
    assert anadidos == {"enviar_foto", "responder", "escribiendo", "descargar",
                        # y los botones (237): mandar con ellos, cerrar la
                        # pulsación y retirarlos al decidir. Tres métodos para
                        # una capacidad: que él decida con un dedo.
                        "enviar_con_botones", "pulsado", "quitar_botones"}


# ── mandar una foto ───────────────────────────────────────────────────────────


def test_la_foto_viaja_con_el_boundary_que_declara_la_cabecera(monkeypatch, tmp_path):
    """El cuerpo se arma a mano, así que el boundary está escrito dos veces.

    Si los dos dejan de coincidir, Telegram no ve ningún campo y contesta que
    falta `chat_id` — un mensaje que manda a mirar donde no es.
    """
    imagen = tmp_path / "estilo-e4.png"
    imagen.write_bytes(b"\x89PNG\r\n\x1a\nbytes-de-la-captura")

    bot, red = montar(monkeypatch, {"ok": True, "result": {"message_id": 9}})
    assert bot.enviar_foto(555, imagen) == 9

    peticion = red.peticiones[0]
    limite = boundary_de(peticion)
    cuerpo = peticion.data

    assert red.url(0).endswith("/sendPhoto")
    assert f"--{limite}\r\n".encode() in cuerpo
    assert cuerpo.endswith(f"--{limite}--\r\n".encode())
    # Y los bytes del archivo dentro, no su ruta: es un envío, no un puntero.
    assert b"\x89PNG\r\n\x1a\nbytes-de-la-captura" in cuerpo
    assert b'name="photo"; filename="estilo-e4.png"' in cuerpo
    assert b'name="chat_id"' in cuerpo


def test_el_pie_viaja_como_caption_y_sin_pie_no_va_el_campo(monkeypatch, tmp_path):
    """Un `caption` vacío no es lo mismo que no mandarlo: Telegram pinta el
    hueco igual, y una foto del catálogo con una línea en blanco debajo parece
    un mensaje que salió a medias."""
    imagen = tmp_path / "estilo-e2.png"
    imagen.write_bytes(b"png")

    bot, red = montar(
        monkeypatch,
        {"ok": True, "result": {"message_id": 1}},
        {"ok": True, "result": {"message_id": 2}},
    )
    bot.enviar_foto(555, imagen, "así se vería tu tarjeta")
    bot.enviar_foto(555, imagen)

    con_pie, sin_pie = red.peticiones[0].data, red.peticiones[1].data
    assert b'name="caption"' in con_pie
    assert "así se vería tu tarjeta".encode() in con_pie
    assert b"caption" not in sin_pie


def test_una_imagen_que_no_esta_se_dice_antes_de_tocar_la_red(monkeypatch, tmp_path):
    """Comprobarlo antes y no después importa por lo que cuesta cada una.

    Con la comprobación después, el fallo llega como un error de Telegram sobre
    un cuerpo vacío y hay que ir a buscar qué imagen faltaba; y encima se ha
    gastado una llamada. La red no se usa para descubrir que un archivo no está.
    """
    bot, red = montar(monkeypatch)  # sin ninguna respuesta preparada
    with pytest.raises(telegram.TelegramCaido, match="no existe la imagen"):
        bot.enviar_foto(555, tmp_path / "no-esta.png")
    assert red.peticiones == []


# ── bajar el audio ────────────────────────────────────────────────────────────


def test_el_audio_aterriza_entero_y_sin_dejar_restos(monkeypatch, tmp_path):
    """El destino puede estar en una carpeta que aún no existe: la crea."""
    destino = tmp_path / "audios" / "nota-0001.oga"
    bot, red = montar(
        monkeypatch,
        {"ok": True, "result": {"file_path": "voice/file_7.oga"}},
        b"OggS-la-nota-entera",
    )

    assert bot.descargar("AwACAgQ", destino) == destino
    assert destino.read_bytes() == b"OggS-la-nota-entera"
    assert list(tmp_path.rglob("*.parcial")) == [], "el temporal se queda por ahí"
    assert "/file/bot" in red.url(1) and red.url(1).endswith("voice/file_7.oga")


def test_una_descarga_que_se_corta_no_deja_medio_audio_en_el_destino(monkeypatch, tmp_path):
    """🔴 Lo peor que puede pasar aquí es que salga bien a medias.

    Un `.oga` truncado se transcribe sin quejarse: da la primera mitad de lo que
    alguien contó de su negocio y nada dice que falta la otra. Por eso se escribe
    en un temporal y se hace `replace` — y por eso el destino tiene que seguir
    exactamente como estaba si la descarga revienta.
    """
    destino = tmp_path / "nota-0001.oga"
    destino.write_bytes(b"la descarga buena de antes")

    bot, _ = montar(
        monkeypatch,
        {"ok": True, "result": {"file_path": "voice/file_7.oga"}},
        _CuerpoCortado(b""),
    )
    with pytest.raises(telegram.TelegramCaido, match="no se pudo bajar el audio"):
        bot.descargar("AwACAgQ", destino)

    assert destino.read_bytes() == b"la descarga buena de antes"
    assert list(tmp_path.rglob("*.parcial")) == []


def test_un_getfile_sin_ruta_no_se_intenta_bajar(monkeypatch, tmp_path):
    """Sin `file_path` no hay de dónde bajar. Seguir construiría una URL con un
    `None` dentro y el fallo saldría como un 404 sin relación con la causa."""
    bot, red = montar(monkeypatch, {"ok": True, "result": {}})
    with pytest.raises(telegram.TelegramCaido, match="file_path"):
        bot.descargar("AwACAgQ", tmp_path / "nota.oga")
    assert len(red.peticiones) == 1


# ── el «escribiendo…» ─────────────────────────────────────────────────────────


def test_un_parpadeo_de_red_no_frena_la_vuelta_del_rele(monkeypatch):
    """El indicador es cortesía: perderlo no pierde información.

    Dejarlo subir pararía el relé entero por un adorno, y el precio sería no
    contestar a quien está esperando de verdad.
    """
    bot, _ = montar(monkeypatch, urllib.error.URLError("connection reset"))
    assert bot.escribiendo(555) is None


def test_pero_no_se_traga_cualquier_cosa(monkeypatch):
    """🔴 `except TelegramCaido` y no `except Exception`.

    Lo que se perdona es que la red falle. Un error de programación aquí dentro
    —un `None` donde iba un id, un cuerpo que no es JSON— no es un parpadeo, y
    escondiéndolo se convierte en un bot que nunca escribe y nadie sabe por qué.
    """
    def revienta(peticion, timeout=None):
        raise ValueError("esto no es un fallo de red")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", revienta)
    with pytest.raises(ValueError):
        telegram.BotDeEncargos("123:abc").escribiendo(555)


# ── responder a un mensaje concreto ──────────────────────────────────────────


def test_la_respuesta_va_colgada_del_mensaje_al_que_contesta(monkeypatch):
    """🔴 Es lo que ata una aprobación a un plan (decisión 281).

    Sin `reply_to_message_id` el «sí» de vuelta es un «sí» suelto, y si mientras
    tanto se mandó otra cosa hay que adivinar qué se aprobó. Adivinar aquí es
    construir el negocio equivocado.
    """
    bot, red = montar(monkeypatch, {"ok": True, "result": {"message_id": 77}})
    assert bot.responder(555, "queda así, ¿lo hago?", 4242) == 77

    enviado = urllib.parse.parse_qs(red.peticiones[0].data.decode())
    assert enviado["reply_to_message_id"] == ["4242"]
    assert enviado["chat_id"] == ["555"]
    assert enviado["text"] == ["queda así, ¿lo hago?"]


# ── normalizar lo que llega, con voz ─────────────────────────────────────────


def test_una_nota_de_voz_sin_texto_se_reconoce():
    """Es el caso normal, no el raro: quien cuenta su negocio manda audio."""
    update = {
        "update_id": 12,
        "message": {
            "message_id": 300,
            "from": {"id": 8080, "username": "marta_v", "first_name": "Marta"},
            "voice": {"file_id": "AwACAgQAAx", "duration": 46},
        },
    }
    partes = telegram.partes_con_voz(update)
    assert partes["voz"] == "AwACAgQAAx"
    assert partes["segundos"] == 46
    assert partes["texto"] == ""
    assert partes["message_id"] == 300


def test_el_canal_de_consulta_sigue_sin_ver_las_notas_de_voz():
    """🔴 Es el motivo de que `partes_con_voz` sea otra función y no un flag.

    Allí un `texto` vacío con un `voz` al lado se colaría por caminos que esperan
    texto, y una nota mandada por error al bot equivocado acabaría en un registro
    que nadie sabe explicar.
    """
    update = {
        "update_id": 12,
        "message": {
            "message_id": 300,
            "from": {"id": 8080, "first_name": "Marta"},
            "voice": {"file_id": "AwACAgQAAx", "duration": 46},
        },
    }
    assert telegram.partes_del_mensaje(update) is None
    assert telegram.partes_con_voz(update) is not None


def test_el_pie_de_una_foto_cuenta_como_lo_que_dijo():
    """Mandar una foto con una línea debajo es escribir, no adjuntar. Ignorar el
    `caption` sería tirar justo la frase que explica la foto."""
    update = {
        "update_id": 13,
        "message": {
            "message_id": 301,
            "from": {"id": 8080, "first_name": "Marta", "last_name": "Vera"},
            "photo": [{"file_id": "foto1"}],
            "caption": "algo así pero en verde",
        },
    }
    partes = telegram.partes_con_voz(update)
    assert partes["texto"] == "algo así pero en verde"
    assert partes["nombre"] == "Marta Vera"
    assert partes["voz"] == ""


def test_el_reply_se_conserva_tambien_cuando_lo_que_llega_es_voz():
    """Aprobar un plan con un audio tiene que casar igual que aprobarlo por
    escrito: el casado descansa entero en este campo."""
    update = {
        "update_id": 14,
        "message": {
            "message_id": 302,
            "from": {"id": 8080, "first_name": "Marta"},
            "voice": {"file_id": "AwACAgQAAx", "duration": 4},
            "reply_to_message": {"message_id": 5001},
        },
    }
    assert telegram.partes_con_voz(update)["responde_a"] == 5001


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "message": {"voice": {"file_id": "x"}}},   # sin remitente
        {"update_id": 1, "message": {"from": {"id": 8080}}},        # ni texto ni voz
        {"update_id": 1, "edited_message": {"text": "x"}},          # no es un mensaje
        {"update_id": 1},
    ],
)
def test_lo_que_no_trae_ni_voz_ni_texto_de_alguien_se_descarta(update):
    """Sin `from` no hay a quién contestar, y un update sin contenido no es un
    turno de la conversación: dejarlo pasar metería fichas vacías en la cola."""
    assert telegram.partes_con_voz(update) is None


def test_una_respuesta_que_llega_corta_se_dice_como_fallo_de_red(monkeypatch, tmp_path):
    """🔴 `IncompleteRead` no hereda de `OSError`, así que había que nombrarla.

    Es el caso que el temporal de `descargar` dice cubrir —la descarga que se
    corta a mitad— y hasta que estuvo en el `except` se escapaba sin envolver:
    el relé, que atrapa `TelegramCaido` para aparcar el audio y reintentarlo, se
    llevaba una excepción de otro tipo y el audio no quedaba aparcado con su
    razón. Un corte a media lectura es de lo más normal en una conexión
    doméstica.
    """
    import http.client

    bot = telegram.BotDeEncargos("t", api="http://api.falsa")
    monkeypatch.setattr(
        bot, "_llamar",
        lambda metodo, datos, **k: {"ok": True, "result": {"file_path": "voz/1.ogg"}},
    )

    class RespuestaCortada:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"medio")

    monkeypatch.setattr(telegram.urllib.request, "urlopen",
                        lambda *a, **k: RespuestaCortada())

    with pytest.raises(telegram.TelegramCaido, match="no se pudo bajar"):
        bot.descargar("AUDIO1", tmp_path / "audio.ogg")
    assert not (tmp_path / "audio.ogg").exists()
    assert not list(tmp_path.glob("*.parcial"))


# ── botones (decisión 237) ────────────────────────────────────────────────────


def test_los_botones_viajan_como_teclado_bajo_el_mensaje(monkeypatch):
    bot, red = montar(monkeypatch, {"ok": True, "result": {"message_id": 9}})

    assert bot.enviar_con_botones(1, "¿Va?", [("✅ Aprobar", "aprobado"), ("✖", "no")]) == 9

    cuerpo = red.peticiones[0].data.decode()
    import urllib.parse
    campos = dict(urllib.parse.parse_qsl(cuerpo))
    teclado = json.loads(campos["reply_markup"])
    assert [b["callback_data"] for b in teclado["inline_keyboard"][0]] == ["aprobado", "no"]


def test_una_pulsacion_tiene_la_forma_de_una_respuesta_a_ese_mensaje():
    """`procesar_mensaje` no distingue —ni debe— entre pulsar y escribir."""
    msg = telegram.boton_pulsado({"update_id": 3, "callback_query": {
        "id": "cb-9", "data": "otra ronda",
        "from": {"id": 1, "first_name": "Quien"},
        "message": {"message_id": 44, "chat": {"id": 1}}}})
    assert msg["texto"] == "otra ronda" and msg["responde_a"] == 44 and msg["user_id"] == 1
    assert msg["boton"] is True and msg["callback_id"] == "cb-9" and msg["chat_id"] == 1
    assert telegram.boton_pulsado({"update_id": 3, "message": {"text": "hola"}}) is None


def test_el_canal_de_encargos_pide_tambien_las_pulsaciones(monkeypatch):
    bot, red = montar(monkeypatch, {"ok": True, "result": []})
    bot.actualizaciones()
    import urllib.parse
    campos = dict(urllib.parse.parse_qsl(red.peticiones[0].data.decode()))
    assert json.loads(campos["allowed_updates"]) == ["message", "callback_query"]
