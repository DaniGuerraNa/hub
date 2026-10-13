"""La puerta del hub.

🔴 Estos tests están escritos al revés que casi todos los demás: lo que
comprueban sobre todo es lo que tiene que **fallar**. Es la lista del §8 de
`PLAN-REMOTO.md`, y está ahí porque los dos fallos que más han dolido en este
proyecto tenían la suite entera en verde. Un endpoint que da shell no se prueba
viendo que funciona; se prueba viendo que se cierra.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hub import acceso, web

FUERA = "desktop.tail1a2b3c.ts.net"


@pytest.fixture(autouse=True)
def _interruptor_limpio():
    """El interruptor vive en memoria (decisión 163), o sea que es estado global
    del proceso: sin esto un test que lo abre se lo deja abierto al siguiente."""
    acceso.abrir_terminal_remota(False)
    yield
    acceso.abrir_terminal_remota(False)


@pytest.fixture
def acceso_yml():
    """Un `acceso.yml` que declara el nombre de la red privada."""
    ruta = acceso.archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump({"hosts": [FUERA]}), encoding="utf-8")
    return ruta


@pytest.fixture
def de_fuera(acceso_yml):
    """Un navegador que entra por el nombre de la red privada, sin dar de alta."""
    return TestClient(web.app, base_url=f"https://{FUERA}")


@pytest.fixture
def de_casa():
    return TestClient(web.app)


# ── Lo que tiene que fallar ──────────────────────────────────────────────────

def test_un_aparato_sin_dar_de_alta_no_pasa_de_la_puerta(de_fuera):
    """§8.5. El caso entero: la red privada es la puerta de fuera, ésta la de
    dentro, y perder el móvil con la sesión viva no puede entregar la casa."""
    r = de_fuera.get("/")
    assert r.status_code == 403
    assert "no está dado de alta" in r.text


def test_un_aparato_sin_dar_de_alta_tampoco_abre_la_terminal(de_fuera):
    """§8.5, la otra mitad. Ésta es la que importa: el WebSocket es el único
    sitio del hub que da una shell, y comprobar sólo el HTTP dejaría abierta
    justo esa."""
    acceso.abrir_terminal_remota(True)
    _se_cierra_sin_aceptar(de_fuera)


def test_la_terminal_remota_esta_cerrada_de_fabrica(de_fuera):
    """§8.6. Con el aparato dado de alta pero el interruptor apagado, que es el
    estado en que arranca `hub-web` siempre."""
    testigo = _dar_de_alta(de_fuera, "Móvil")
    de_fuera.cookies.set(acceso.COOKIE, testigo)
    assert not acceso.terminal_remota()
    _se_cierra_sin_aceptar(de_fuera)


def test_desde_casa_la_terminal_SIGUE_abriendose_sin_aparato_dado_de_alta(de_casa):
    """🔴 El test que faltaba, y su ausencia costó tener el hub roto.

    La primera versión exigía aparato dado de alta en **todos** los WebSockets
    de terminal, razonando que con `tailscale serve` el tráfico remoto llega por
    loopback y «parece local» no prueba nada. Como no había ningún aparato dado
    de alta, cerró **todas las terminales de la máquina**: el hub servía las
    pantallas perfectas y ninguna ventana se veía. Había test de que la puerta
    cierra desde fuera y ninguno de que sigue abierta desde dentro.

    Se pide un destino que no existe a propósito: así el handler acepta y luego
    se queja por el socket, sin necesitar tmux. Recibir el mensaje **prueba que
    hubo `accept()`**, que es justo lo que la versión rota no hacía.
    """
    with de_casa.websocket_connect("/ws/terminal/no vale este nombre") as ws:
        assert b"[hub]" in ws.receive_bytes(), "aceptó pero no explicó qué pasaba"


def test_desde_fuera_con_aparato_y_el_interruptor_abierto_la_terminal_se_abre(de_fuera):
    """La otra mitad: cerrarla desde fuera no puede significar cerrarla siempre."""
    de_fuera.cookies.set(acceso.COOKIE, _dar_de_alta(de_fuera, "Móvil"))
    acceso.abrir_terminal_remota(True)
    with de_fuera.websocket_connect("/ws/terminal/no vale este nombre",
                                    headers={"host": FUERA}) as ws:
        assert b"[hub]" in ws.receive_bytes()


def test_un_nombre_que_no_esta_en_la_lista_se_rechaza_diciendo_que_hacer(acceso_yml):
    """§8.7. `TrustedHostMiddleware` contestaba «Invalid host header» y ya: es
    literalmente lo primero que se ve al abrir el hub desde el móvil, y no dice
    que falte un nombre en un archivo."""
    otro = TestClient(web.app, base_url="https://otra-maquina.ts.net")
    r = otro.get("/")
    assert r.status_code == 400
    assert "otra-maquina.ts.net" in r.text
    assert str(acceso.archivo()) in r.text


def test_revocar_deja_fuera_al_aparato_en_la_peticion_siguiente(de_fuera):
    """§8.8. No en la próxima caducidad: en la siguiente.

    Es la razón de que el archivo guarde el hash del testigo en vez de firmar
    una cookie. Una firma válida lo es para siempre y no hay dónde borrarla.
    """
    testigo = _dar_de_alta(de_fuera, "Móvil que se pierde")
    de_fuera.cookies.set(acceso.COOKIE, testigo)
    assert de_fuera.get("/").status_code == 200

    acceso.revocar(acceso.dispositivos()[0]["id"])
    assert de_fuera.get("/").status_code == 403


def test_un_comodin_en_la_lista_de_nombres_se_levanta_y_no_se_ignora(acceso_yml):
    """Decisión 162. Sin validar el `Host` los nombres de sesión se enumeran por
    DNS-rebinding: un `*` reabre exactamente el agujero que la lista cerró.
    Dejarlo pasar con un aviso en el registro es dejarlo pasar."""
    acceso_yml.write_text(yaml.safe_dump({"hosts": ["*.ts.net"]}), encoding="utf-8")
    with pytest.raises(acceso.AccesoInvalido) as exc:
        acceso.hosts()
    assert "comodín" in str(exc.value)


def test_un_acceso_roto_no_deja_al_hub_inalcanzable_desde_casa(acceso_yml, de_casa):
    """Si un archivo mal escrito cerrara también la puerta de casa, arreglarlo
    exigiría entrar al hub."""
    acceso_yml.write_text("esto: [no es\n  una lista", encoding="utf-8")
    assert de_casa.get("/").status_code == 200


def test_un_codigo_de_alta_sirve_una_sola_vez(de_fuera):
    codigo = acceso.alta_pendiente("Móvil")
    primera = de_fuera.get(f"/acceso/alta/{codigo}", follow_redirects=False)
    assert primera.status_code == 303
    segunda = de_fuera.get(f"/acceso/alta/{codigo}", follow_redirects=False)
    assert segunda.status_code == 410


def test_un_codigo_caducado_no_da_de_alta_nada(de_fuera, monkeypatch):
    monkeypatch.setattr(acceso, "MINUTOS_DE_ALTA", -1)
    codigo = acceso.alta_pendiente("Móvil tardón")
    assert de_fuera.get(f"/acceso/alta/{codigo}", follow_redirects=False).status_code == 410
    assert acceso.dispositivos() == []


# ── Lo que tiene que funcionar ───────────────────────────────────────────────

def test_desde_casa_se_entra_sin_dar_de_alta_nada(de_casa):
    """La puerta se pone donde el argumento de `web.py` deja de valer, y en
    local sigue valiendo: quien puede ejecutar `curl` aquí ya puede ejecutar
    `bash`, así que pedirle una cookie no defendería de nada y rompería el CLI
    del asistente, que habla HTTP sin `Origin` desde otro repo."""
    assert de_casa.get("/").status_code == 200


def test_un_aparato_dado_de_alta_entra_y_queda_con_su_nombre(de_fuera):
    testigo = _dar_de_alta(de_fuera, "Móvil del viaje")
    de_fuera.cookies.set(acceso.COOKIE, testigo)
    assert de_fuera.get("/").status_code == 200
    guardado = acceso.dispositivos()[0]
    assert guardado["nombre"] == "Móvil del viaje"
    assert guardado["ultimo_uso"], "no se anotó que se hubiera usado"


def test_el_archivo_guarda_el_hash_y_nunca_el_testigo(de_fuera):
    """Quien lea `acceso.yml` no puede entrar con lo que hay dentro."""
    testigo = _dar_de_alta(de_fuera, "Móvil")
    assert testigo not in acceso.archivo().read_text(encoding="utf-8")


def test_el_interruptor_de_la_terminal_no_se_persiste(de_fuera):
    """La mitad de la decisión 163 que es fácil de perder: si esto acabara en un
    archivo, «abrir la terminal remota» dejaría de ser una decisión cada vez."""
    acceso.abrir_terminal_remota(True)
    if acceso.archivo().is_file():
        assert "terminal" not in acceso.archivo().read_text(encoding="utf-8")


def test_la_pantalla_pinta_el_qr_del_alta_recien_creada(de_casa):
    """🔴 Pedir `/acceso` a secas daba 200 y no probaba nada: sin código no hay
    QR, así que la rama que lo dibuja no se ejecutaba. Con `currentColor` —que
    segno rechaza— la pantalla daba un 500 y la suite seguía en verde."""
    codigo = acceso.alta_pendiente("Móvil")
    r = de_casa.get(f"/acceso?codigo={codigo}")
    assert r.status_code == 200
    assert "<svg" in r.text, "no se pintó el QR"
    assert f"/acceso/alta/{codigo}" in r.text, "el QR no lleva al alta"


def test_el_qr_apunta_al_nombre_por_el_que_se_esta_mirando(de_fuera):
    """Armarlo con `127.0.0.1` daría un QR que sólo funciona en la máquina que ya
    está dentro — justo el aparato que no hace falta dar de alta."""
    testigo = _dar_de_alta(de_fuera, "Primero")
    de_fuera.cookies.set(acceso.COOKIE, testigo)
    codigo = acceso.alta_pendiente("Segundo")
    assert f"https://{FUERA}/acceso/alta/{codigo}" in de_fuera.get(f"/acceso?codigo={codigo}").text


def _se_cierra_sin_aceptar(cliente) -> None:
    """🔴 Se comprueba el CÓDIGO, no que reviente.

    Un `pytest.raises(Exception)` a secas pasaría igual si el socket muriera por
    cualquier otro motivo —tmux ausente, un fallo al abrir el espejo— y entonces
    el test diría que la puerta cierra cuando lo que pasa es que el hub está
    roto. 1008 es «política»: se rechazó ANTES del `accept()`.
    """
    with pytest.raises(WebSocketDisconnect) as exc:
        with cliente.websocket_connect("/ws/terminal/loquesea",
                                       headers={"host": FUERA}):
            pass
    assert exc.value.code == 1008


def _dar_de_alta(cliente, nombre: str) -> str:
    """Recorre el alta como la recorrería el aparato, y devuelve su testigo."""
    codigo = acceso.alta_pendiente(nombre)
    r = cliente.get(f"/acceso/alta/{codigo}", follow_redirects=False)
    assert r.status_code == 303, r.text
    testigo = r.cookies.get(acceso.COOKIE)
    assert testigo, "el alta no dejó cookie"
    return testigo


# ── El manifiesto (tarea 4) ──────────────────────────────────────────────────

def test_el_manifiesto_se_sirve_y_apunta_a_iconos_que_existen(de_casa):
    """Un manifiesto con un icono roto no falla: el móvil pone una letra en un
    círculo gris y nadie se entera de por qué."""
    import json

    r = de_casa.get("/static/manifest.json")
    assert r.status_code == 200
    manifiesto = json.loads(r.text)
    assert manifiesto["display"] == "standalone"
    for icono in manifiesto["icons"]:
        assert de_casa.get(icono["src"]).status_code == 200, icono["src"]


def test_el_manifiesto_no_declara_ningun_service_worker(de_casa):
    """Decisión 168. Un service worker cachea, y enseñaría una pantalla vieja
    como si fuera de ahora — la forma exacta de mentir que este hub prohíbe."""
    assert "serviceWorker" not in de_casa.get("/").text
    assert not list((__import__("pathlib").Path(web.__file__).parent / "static").glob("*sw*.js"))


def test_el_manifiesto_se_puede_pedir_sin_haber_dado_de_alta_el_aparato(de_fuera):
    """El navegador lo pide antes de tener cookie: detrás de la puerta, la
    pantalla de alta se vería sin icono y sin estilos."""
    assert de_fuera.get("/static/manifest.json").status_code == 200


def test_un_websocket_sin_cabecera_host_no_cuenta_como_de_casa(de_casa):
    """🔴 Al revés que en el resto del hub, y a propósito.

    `es_host_local(None)` devuelve `True` porque un `Host` ausente significa que
    no lo mandó un navegador —`curl`, el CLI del asistente— y para leer
    proyectos eso está bien. Aquí no: éste es el endpoint que da una shell, y un
    valor por defecto que abre es la clase de descuido que sólo se ve después.
    """
    _se_cierra_sin_aceptar_con(de_casa, {"host": ""})


def _se_cierra_sin_aceptar_con(cliente, cabeceras) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with cliente.websocket_connect("/ws/terminal/loquesea", headers=cabeceras):
            pass
    assert exc.value.code == 1008


# ── La puerta que no cerraba (decisión 183) ──────────────────────────────────
#
# 🔴 Estos tres tests existen porque la suite entera estaba verde con la puerta
# abierta de par en par. Lo que faltaba no era una comprobación más fina: era
# recorrer el alta **como la recorrería un intruso**, por HTTP y desde fuera, en
# vez de llamar a `acceso.alta_pendiente()` desde dentro del proceso como hacía
# el ayudante `_dar_de_alta`. Un atajo en el arnés se lleva por delante la única
# parte que se estaba probando.

def test_un_aparato_de_fuera_no_puede_pedirse_un_alta_a_si_mismo(de_fuera):
    """🔴 El agujero, medido: `SIN_PUERTA` casaba por prefijo y sin mirar el
    método, así que el POST que **crea** un código de alta entraba por la misma
    exención que el GET que lo canjea. Desde fuera bastaba con pedir el alta,
    leer el código en la cabecera `Location` y canjearlo: el aparato se daba de
    alta solo y a partir de ahí tenía el hub entero, incluido el interruptor que
    abre la terminal."""
    r = de_fuera.post("/acceso/alta", data={"nombre": "Intruso"},
                      follow_redirects=False)
    assert r.status_code == 403, "un aparato sin dar de alta se pidió su propia alta"
    assert "codigo" not in (r.headers.get("location") or ""), \
        "el código de alta viajó en la redirección"
    assert acceso.dispositivos() == []


def test_desde_fuera_no_se_revoca_ni_se_abre_la_terminal_sin_estar_dado_de_alta(de_fuera):
    """La misma exención cubría cualquier POST bajo `/acceso/alta…`; esto fija
    que ninguna de las otras acciones de la pantalla se alcanza desde fuera."""
    assert de_fuera.post("/acceso/revocar", data={"dispositivo_id": "x"},
                         follow_redirects=False).status_code == 403
    assert de_fuera.post("/acceso/terminal", data={"abrir": 1},
                         follow_redirects=False).status_code == 403
    assert not acceso.terminal_remota()


def test_canjear_un_alta_SIGUE_entrando_sin_cookie(de_fuera):
    """La otra mitad, y la que se rompe al arreglar la primera de un tijeretazo.
    Si canjear dejara de estar exento no habría forma de dar de alta el primer
    aparato desde fuera, que es para lo que existe la exención."""
    testigo = _dar_de_alta(de_fuera, "Móvil del viaje")
    de_fuera.cookies.set(acceso.COOKIE, testigo)
    assert de_fuera.get("/").status_code == 200


def test_los_estaticos_se_sirven_sin_cookie_pero_no_se_les_puede_escribir(de_fuera):
    """Sin los estáticos la pantalla de alta se ve en blanco; con la exención
    dada por método, pedirlos sigue valiendo y nada más."""
    assert de_fuera.get("/static/manifest.json").status_code == 200
    assert de_fuera.post("/static/manifest.json").status_code == 403


# ── Un solo escritor cada vez (decisión 184) ─────────────────────────────────

@pytest.fixture
def sin_freno(monkeypatch):
    """Quita el freno de `marcar_uso` para dejar la carrera a la vista.

    🔴 Sin esto los tests de aquí abajo **pasan aunque se quite el cerrojo**: el
    freno escribe una vez por minuto, así que dos escritores casi nunca coinciden
    y la carrera no se reproduce. Comprobado quitando el cerrojo a mano.

    El freno es una mitigación y tiene su propio test; lo que estos cubren es el
    cerrojo, así que el arnés reproduce el caso peor: cada petición, escritura.
    """
    monkeypatch.setattr(acceso, "SEGUNDOS_ENTRE_MARCAS", 0)


def _con_el_movil_a_medias(aparato_id: str, accion):
    """Ejecuta `accion` **entre la lectura y la escritura** de otra petición.

    🔴 El entrelazado se fuerza en vez de esperar a que salga por repetición. La
    primera versión de estos tests lo dejaba al azar: fallaban 2 de cada 5 veces
    con el cerrojo quitado, o sea que pasaban 3 de cada 5 con el fallo abierto.
    Un test así se acaba marcando como flaky y se deja de mirar, que es cómo se
    pierde la única cosa que vigila un endpoint que da acceso al hub entero.

    Con cerrojo, `accion` se queda esperando su turno —por eso va en su propio
    hilo— y lee la lista ya escrita. Sin cerrojo, se cuela en medio y la
    escritura de la petición en vuelo la pisa con datos viejos.
    """
    import threading

    leido, seguir = threading.Event(), threading.Event()
    original = acceso._leer

    def leer_despacio():
        datos = original()
        if threading.current_thread().name == "movil":
            leido.set()
            seguir.wait(timeout=5)
        return datos

    acceso._leer = leer_despacio
    devuelto = []
    try:
        movil = threading.Thread(target=lambda: acceso.marcar_uso(aparato_id),
                                 name="movil", daemon=True)
        movil.start()
        assert leido.wait(timeout=5), "la petición en vuelo no llegó a leer"

        entre = threading.Thread(target=lambda: devuelto.append(accion()), daemon=True)
        entre.start()
        entre.join(timeout=0.2)
        seguir.set()
        movil.join(timeout=5)
        entre.join(timeout=5)
    finally:
        acceso._leer = original
        seguir.set()
    return devuelto


def test_dar_de_alta_un_aparato_mientras_otro_usa_el_hub_no_lo_pierde(acceso_yml, sin_freno):
    """🔴 Medido antes de arreglarlo: fallaba **15 de 15**.

    El `marcar_uso` de cada petición leía el archivo entero, lo modificaba y lo
    reescribía sin cerrojo. El móvil late cada 5 s desde la vista de trabajo, así
    que dar de alta el portátil en mitad de eso reescribía la lista **sin** el
    portátil. El síntoma sería «escaneé el QR y no entra», desde otro país y sin
    forma de arreglarlo.
    """
    testigo_movil = acceso.canjear(acceso.alta_pendiente("Móvil"))
    movil = acceso.reconocer(testigo_movil)

    salida = _con_el_movil_a_medias(
        movil["id"], lambda: acceso.canjear(acceso.alta_pendiente("Portátil")))

    assert acceso.reconocer(salida[0]), "el alta se perdió por una petición en vuelo"
    assert acceso.reconocer(testigo_movil), "y se llevó por delante al que ya estaba"


def test_revocar_un_aparato_que_esta_usando_el_hub_no_se_deshace_solo(acceso_yml, sin_freno):
    """🔴 §8.8 del plan, del lado en que fallaba: fallaba **15 de 15**.

    Una revocación que se deshace sola es peor que no tener revocación: se cree
    que el móvil perdido quedó fuera, y sigue dentro.
    """
    testigo = acceso.canjear(acceso.alta_pendiente("Móvil perdido"))
    aparato = acceso.reconocer(testigo)

    assert _con_el_movil_a_medias(aparato["id"], lambda: acceso.revocar(aparato["id"])) == [True]
    assert acceso.reconocer(testigo) is None, \
        "la petición en vuelo del propio aparato deshizo su revocación"


def test_la_marca_de_uso_no_reescribe_el_archivo_en_cada_peticion(acceso_yml, monkeypatch):
    """La vista de trabajo late cada 5 s. Sin freno, un móvil abierto reescribe
    doce veces por minuto el archivo que decide quién entra."""
    testigo = acceso.canjear(acceso.alta_pendiente("Móvil"))
    aparato = acceso.reconocer(testigo)

    escrituras = []
    original = acceso._escribir
    monkeypatch.setattr(acceso, "_escribir",
                        lambda datos: (escrituras.append(1), original(datos))[1])

    for _ in range(20):
        acceso.marcar_uso(aparato["id"])
    assert len(escrituras) <= 1, f"{len(escrituras)} escrituras para 20 peticiones seguidas"
    assert acceso.dispositivos()[0]["ultimo_uso"], "y aun así se anotó el uso"


# ── El QR detrás del proxy (decisión 185) ────────────────────────────────────

def test_el_qr_generado_desde_casa_apunta_a_la_red_privada_y_no_a_localhost(acceso_yml, de_casa):
    """🔴 El caso real y el que fallaba mudo: dar de alta el móvil **desde casa**,
    con el hub abierto en `http://127.0.0.1:8787`. El enlace se armaba con el
    nombre de la petición, así que el QR decía `http://127.0.0.1:8787/...` — un
    código perfectamente legible que no lleva a ninguna parte desde un móvil, y
    sin un solo error por ningún lado."""
    codigo = acceso.alta_pendiente("Móvil")
    r = de_casa.get(f"/acceso?codigo={codigo}")
    assert r.status_code == 200
    assert f"https://{FUERA}/acceso/alta/{codigo}" in r.text
    assert "127.0.0.1" not in r.text.split("Dar de alta")[-1].split("Aparatos")[0]


def test_sin_nombre_de_red_privada_el_qr_se_arma_con_el_de_la_peticion(de_casa):
    """Sin `acceso.yml` no hay a dónde apuntar, y un QR a `127.0.0.1` al menos
    enseña el formato. Lo que no puede es inventarse un nombre."""
    codigo = acceso.alta_pendiente("Móvil")
    r = de_casa.get(f"/acceso?codigo={codigo}")
    assert f"/acceso/alta/{codigo}" in r.text


def test_desde_un_aparato_ya_dado_de_alta_el_qr_usa_https_aunque_uvicorn_vea_http(
    acceso_yml, de_fuera
):
    """`tailscale serve` habla con el hub por `http://127.0.0.1:8787`, así que
    `request.url.scheme` dice http aunque el móvil haya entrado por https."""
    de_fuera.cookies.set(acceso.COOKIE, _dar_de_alta(de_fuera, "Móvil"))
    codigo = acceso.alta_pendiente("Portátil")
    r = de_fuera.get(f"/acceso?codigo={codigo}", headers={"x-forwarded-proto": "https"})
    assert r.status_code == 200
    assert f"https://{FUERA}/acceso/alta/{codigo}" in r.text
    assert f"http://{FUERA}" not in r.text


def test_dandose_de_alta_desde_casa_la_cookie_no_se_marca_segura(de_casa):
    """Marcarla siempre haría que el navegador la tirara al dar de alta por
    `http://127.0.0.1:8787`: el aparato quedaría en el archivo y fuera del hub."""
    codigo = acceso.alta_pendiente("Portátil de casa")
    r = de_casa.get(f"/acceso/alta/{codigo}", follow_redirects=False)
    assert r.status_code == 303
    assert "secure" not in r.headers["set-cookie"].lower()


def test_dandose_de_alta_por_https_la_cookie_va_marcada_segura(acceso_yml, de_casa):
    codigo = acceso.alta_pendiente("Móvil")
    r = de_casa.get(f"/acceso/alta/{codigo}",
                    headers={"host": FUERA, "x-forwarded-proto": "https"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "secure" in r.headers["set-cookie"].lower()


def test_el_mensaje_de_la_puerta_manda_a_un_comando_que_existe(de_fuera, capsys):
    """🔴 Decía `hub-acceso alta "…"`, y ese comando **no existe**: no hay
    `[project.scripts]` en `pyproject.toml` y el único `hub` del PATH es el CLI
    del asistente, que es otro repo.

    Este es el texto que se lee desde otro país, con el móvil fuera del hub y sin
    nadie a quien preguntar. Mandar ahí a un comando inventado no es una errata:
    es dejar sin salida el único camino de vuelta. Se comprueba **ejecutando** el
    parser, no leyendo la cadena, porque lo que rota es el comando y no el texto.
    """
    texto = de_fuera.get("/").text
    assert "python -m hub.acceso alta" in texto

    assert acceso._cli(["alta", "Un aparato", "--host", FUERA]) == 0
    assert acceso.pendientes(), "el comando que dice el mensaje no dio de alta nada"
