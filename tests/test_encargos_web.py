"""La pantalla de encargos: `/encargos` y su ficha.

Lo que se protege aquí es lo que la vista puede romper sin que nadie se entere:

- que responda **con la base vacía**. Los dos fallos que más han dolido en este
  proyecto —el 500 de `/trabajo` sin servidor de tmux y el «Cargando…» eterno del
  asistente— tenían la suite entera en verde y sólo aparecían al arrancar de
  cero, que es exactamente el estado en que la instala otra persona;
- que **escribir al bot no dé de alta a nadie**: el alta va al revés a propósito,
  y una pantalla que la concediera sola derribaría esa inversión entera;
- 🔴 que la vista **no manda nada por Telegram**. El token lo lee `hub-encargos`,
  que es un servicio aparte; `hub-web` expone el puerto —y con él una shell,
  regla dura 8— y no debe verlo nunca (regla dura 22). No se comprueba leyendo el
  código: se rompe el único sitio por el que se sale a la red y se recorre la
  pantalla entera.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub import buzon, db, encargos, entrevistador, telegram, web


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """La app contra una base de pruebas, sin canal configurado y sin nadie.

    Sin token a propósito: es el estado en el que se abre la pantalla la primera
    vez, y es el que tiene que seguir dando 200.
    """
    ruta = tmp_path / "hub.db"
    monkeypatch.setenv("HUB_ENCARGOS_YML", str(tmp_path / "encargos.yml"))

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    # 🔴 Sin tmux: dar de alta abre un entrevistador (decisión 229) y aquí eso
    # sería una ventana de verdad. Se apunta a quién se abrió y nada más; el
    # test que necesita que falle lo sustituye por uno que falla.
    abiertos: list[str] = []

    def abrir_de_mentira(con, encargo_id):
        abiertos.append(encargo_id)
        encargos.tocar(con, encargo_id, slot_id=None)
        return {"slot_id": 1, "pane_id": "%1", "session": "encargos",
                "ventana": 0, "ya_estaba": False}

    monkeypatch.setattr(entrevistador, "abrir_agente", abrir_de_mentira)

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    cliente_ = TestClient(web.app)
    cliente_.agentes_abiertos = abiertos
    return cliente_


def _escribe_al_bot(user_id=777, username="tienda_t", nombre="Tienda"):
    """Lo que hace el relé al ver un mensaje: apuntar quién escribió y nada más."""
    con = web.conexion()
    try:
        encargos.anotar_persona(con, user_id, username, nombre)
        con.commit()
    finally:
        con.close()


def _de_alta(cliente, user_id=777, alias="tienda"):
    cliente.post("/encargos/persona",
                 data={"user_id": user_id, "alias": alias, "estado": "activo"})


# ── que arranque de cero ──────────────────────────────────────────────────────


def test_la_pantalla_responde_con_la_base_vacia_y_sin_token(cliente):
    """Sin encargos, sin personas y sin canal configurado: 200 y algo legible.

    Es el primer arranque de quien la instala. Un 500 aquí se lee como «esto no
    funciona» y no hay nada en pantalla que diga por dónde seguir.
    """
    r = cliente.get("/encargos")
    assert r.status_code == 200
    assert "no está configurado" in r.text
    assert "Todavía no ha escrito nadie al bot" in r.text
    assert "Ningún encargo todavía" in r.text


def test_sin_nadie_de_alta_no_se_ofrece_abrir_un_encargo(cliente):
    """Un formulario cuyo desplegable está vacío es una trampa: se rellena, se
    envía y no pasa nada. Se dice que falta el alta y dónde se da."""
    cuerpo = cliente.get("/encargos").text
    assert "No hay nadie de alta" in cuerpo
    assert 'name="encargo_id"' not in cuerpo


def test_la_ficha_de_un_encargo_que_no_existe_no_es_un_500(cliente):
    r = cliente.get("/encargos/no-existe")
    assert r.status_code == 200
    assert "no hay ningún encargo" in r.text


def test_el_enlace_de_navegacion_lleva_a_la_pantalla(cliente):
    """Una vista sin entrada en el raíl sólo se encuentra escribiendo la URL."""
    assert 'href="/encargos"' in cliente.get("/").text


# ── el alta va al revés ───────────────────────────────────────────────────────


def test_escribir_al_bot_no_da_de_alta_a_nadie(cliente):
    """🔴 Aparecer es la única forma de que él pueda decidir, y no concede nada.

    Si escribir diera el alta, el bot sería un canal abierto: cualquiera que
    supiera su nombre podría abrir una conversación y provocar trabajo.
    """
    _escribe_al_bot()
    cuerpo = cliente.get("/encargos").text
    assert "@tienda_t" in cuerpo
    assert "pendiente" in cuerpo

    con = web.conexion()
    try:
        assert encargos.puede_hablar(con, 777) is False
    finally:
        con.close()


def test_darle_de_alta_cambia_su_estado(cliente):
    _escribe_al_bot()
    _de_alta(cliente)
    con = web.conexion()
    try:
        assert encargos.puede_hablar(con, 777) is True
        assert encargos.ver_persona(con, 777)["alias"] == "tienda"
    finally:
        con.close()


def test_darle_de_alta_abre_su_encargo_y_su_entrevistador(cliente):
    """🔴 Dar de alta ES empezar (229): nadie tiene por qué saber que existía
    un segundo paso, y la persona no se queda mirando un silencio."""
    _escribe_al_bot()
    _de_alta(cliente)
    con = web.conexion()
    try:
        abierto = encargos.abierto_de(con, 777)
        assert abierto and abierto["estado"] == "recogiendo"
        assert cliente.agentes_abiertos == [abierto["id"]]
    finally:
        con.close()


def test_lo_que_dijo_antes_del_alta_entra_en_su_encargo(cliente):
    """Sus primeras palabras las lee el entrevistador; no se le pide repetirlas."""
    _escribe_al_bot()
    con = web.conexion()
    try:
        encargos.registrar(con, "falla", "mensaje de alguien sin alta",
                           user_id=777, cuerpo="Hola, tengo una panadería")
        con.commit()
    finally:
        con.close()

    _de_alta(cliente)
    con = web.conexion()
    try:
        encargo_id = encargos.abierto_de(con, 777)["id"]
        assert [m["texto"] for m in buzon.en_cola(con, encargo_id)] == ["Hola, tengo una panadería"]
    finally:
        con.close()


def test_guardar_otra_vez_a_alguien_de_alta_no_abre_otro_encargo(cliente):
    _escribe_al_bot()
    _de_alta(cliente)
    _de_alta(cliente, alias="otro alias")
    con = web.conexion()
    try:
        assert len(encargos.listar(con)) == 1
        assert len(cliente.agentes_abiertos) == 1
    finally:
        con.close()


def test_marcar_al_dueno_no_le_abre_un_encargo(cliente):
    _escribe_al_bot(user_id=1, username="dueno", nombre="El Dueño")
    cliente.post("/encargos/persona",
                 data={"user_id": 1, "estado": "activo", "es_dueno": "on"})
    con = web.conexion()
    try:
        assert encargos.dueno(con)["user_id"] == 1
        assert encargos.listar(con) == [] and cliente.agentes_abiertos == []
    finally:
        con.close()


def test_si_no_se_puede_abrir_la_entrevista_el_alta_se_queda_y_se_dice(cliente, monkeypatch):
    def no_puede(con, encargo_id):
        raise RuntimeError("no hay servidor de tmux al que pedirle una ventana")

    monkeypatch.setattr(entrevistador, "abrir_agente", no_puede)
    _escribe_al_bot()
    r = cliente.post("/encargos/persona",
                     data={"user_id": 777, "alias": "tienda", "estado": "activo"})
    assert r.status_code == 200 and "no hay servidor de tmux" in r.text
    con = web.conexion()
    try:
        assert encargos.puede_hablar(con, 777) is True
    finally:
        con.close()


def test_bloquear_a_alguien_le_quita_el_alta(cliente):
    _escribe_al_bot()
    _de_alta(cliente)
    cliente.post("/encargos/persona", data={"user_id": 777, "estado": "bloqueado"})
    con = web.conexion()
    try:
        assert encargos.puede_hablar(con, 777) is False
    finally:
        con.close()


def test_un_estado_inventado_no_pasa_por_la_web(cliente):
    """La lista cerrada del dominio tiene que serlo también desde fuera."""
    _escribe_al_bot()
    r = cliente.post("/encargos/persona",
                     data={"user_id": 777, "estado": "jefe"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]

    con = web.conexion()
    try:
        assert encargos.ver_persona(con, 777)["estado"] == "pendiente"
    finally:
        con.close()


def test_solo_hay_un_dueno_a_la_vez(cliente):
    """Quien aprueba el gasto es uno. Dos dueños es no tener ninguno."""
    _escribe_al_bot(777, "tienda_t", "Tienda")
    _escribe_al_bot(888, "escuela_t", "Escuela")
    cliente.post("/encargos/persona", data={"user_id": 777, "estado": "activo",
                                            "es_dueno": "1"})
    cliente.post("/encargos/persona", data={"user_id": 888, "estado": "activo",
                                            "es_dueno": "1"})
    con = web.conexion()
    try:
        assert encargos.dueno(con)["user_id"] == 888
        assert [p["user_id"] for p in encargos.personas(con) if p["es_dueno"]] == [888]
    finally:
        con.close()


def test_guardar_a_otra_persona_no_desmarca_al_dueno(cliente):
    """🔴 El matiz de `/canal/usuario`: la casilla sin marcar de OTRA ficha no
    puede desmarcar al dueño. Cada tarjeta tiene su propio formulario, así que
    guardar un alias en la de al lado enviaría `es_dueno` vacío."""
    _escribe_al_bot(777, "tienda_t", "Tienda")
    _escribe_al_bot(888, "escuela_t", "Escuela")
    cliente.post("/encargos/persona", data={"user_id": 777, "estado": "activo",
                                            "es_dueno": "1"})
    cliente.post("/encargos/persona", data={"user_id": 888, "alias": "escuela"})

    con = web.conexion()
    try:
        assert encargos.dueno(con)["user_id"] == 777
    finally:
        con.close()


def test_desmarcarse_uno_mismo_deja_el_canal_sin_dueno(cliente):
    """Y eso se permite: quitar al dueño es una decisión suya, no un accidente."""
    _escribe_al_bot()
    cliente.post("/encargos/persona", data={"user_id": 777, "estado": "activo",
                                            "es_dueno": "1"})
    cliente.post("/encargos/persona", data={"user_id": 777, "estado": "activo"})
    con = web.conexion()
    try:
        assert encargos.dueno(con) is None
    finally:
        con.close()


# ── abrir encargos ────────────────────────────────────────────────────────────


def test_crear_un_encargo_a_nombre_de_alguien_sin_alta_se_rechaza(cliente):
    """🔴 `encargos.crear` es idempotente y no sabe de permisos —lo llama el relé
    al ver un mensaje—, así que la puerta la pone la vista. Sin ella, la pantalla
    abriría encargos a nombre de alguien bloqueado o que nunca se aprobó."""
    _escribe_al_bot()
    r = cliente.post("/encargos/crear",
                     data={"encargo_id": "la-tienda", "user_id": 777},
                     follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]

    con = web.conexion()
    try:
        assert encargos.listar(con) == []
    finally:
        con.close()


def test_crear_un_encargo_con_alguien_de_alta_lleva_a_su_ficha(cliente):
    _escribe_al_bot()
    _de_alta(cliente)
    r = cliente.post("/encargos/crear",
                     data={"encargo_id": "la-tienda", "user_id": 777})
    assert r.status_code == 200
    assert "la-tienda" in r.text

    con = web.conexion()
    try:
        # `encargo-1` lo abrió el alta (229); éste es el segundo, con nombre.
        assert {e["id"] for e in encargos.listar(con)} == {"encargo-1", "la-tienda"}
    finally:
        con.close()


def test_un_id_que_no_sirve_de_subdominio_se_dice_en_vez_de_reventar(cliente):
    """El id es carpeta **y** subdominio. Uno con mayúsculas da un subdominio que
    no resuelve, y eso se descubre cuando ya está publicado."""
    _escribe_al_bot()
    _de_alta(cliente)
    r = cliente.post("/encargos/crear",
                     data={"encargo_id": "La Tienda", "user_id": 777})
    assert r.status_code == 200
    assert "no sirve como id de encargo" in r.text


def test_la_pantalla_propone_un_id_provisional(cliente):
    """Feo y obviamente temporal a propósito: hay que ponerle nombre antes de
    enseñárselo a nadie."""
    _escribe_al_bot()
    _de_alta(cliente)
    assert 'value="encargo-1"' in cliente.get("/encargos").text


# ── renombrar ─────────────────────────────────────────────────────────────────


def _un_encargo(cliente, encargo_id="encargo-1"):
    _escribe_al_bot()
    _de_alta(cliente)
    cliente.post("/encargos/crear", data={"encargo_id": encargo_id, "user_id": 777})
    return encargo_id


def test_la_conversacion_se_lee_como_un_chat_y_las_muestras_van_juntas(cliente):
    """Lo de ella a un lado, lo del agente al otro, y las seis fotos en una sola
    burbuja: en lista vertical eran una pared que tapaba la pregunta."""
    _un_encargo(cliente)
    con = web.conexion()
    try:
        buzon.aparcar(con, "encargo-1", 777, "tengo una panadería")
        buzon.encolar_salida(con, "encargo-1", "Ahora algo distinto: te mando seis imágenes.")
        for n, nombre in enumerate(("Claro", "Cálido", "Oscuro"), start=1):
            buzon.encolar_salida(con, "encargo-1", f"{n} · {nombre}",
                                 clase="muestras", adjunto=f"/x/{n}.png")
        buzon.encolar_salida(con, "encargo-1", "¿Cuál se parece más?")
        con.commit()
    finally:
        con.close()

    r = cliente.get("/encargos/encargo-1")
    assert r.status_code == 200
    assert 'class="chat"' in r.text
    assert r.text.count('class="msg sale"') == 3, "presentación, tira de muestras, pregunta"
    assert r.text.count('class="muestra"') == 3
    assert "tengo una panadería" in r.text and "2 · Cálido" in r.text


def test_renombrar_antes_de_publicar_le_pone_su_nombre(cliente):
    _un_encargo(cliente)
    r = cliente.post("/encargos/encargo-1/renombrar", data={"nombre": "la-tienda"})
    assert r.status_code == 200

    con = web.conexion()
    try:
        assert encargos.ver(con, "la-tienda")
        assert encargos.ver(con, "encargo-1") is None
    finally:
        con.close()


def test_renombrar_uno_publicado_ENSEÑA_el_error(cliente):
    """🔴 El «no» tiene motivo —el id es la URL que la persona ya tiene— y hay
    que poder leerlo. Un formulario que no hace nada y tampoco lo explica se lee
    como una pantalla rota, y entonces se deja de usar."""
    _un_encargo(cliente)
    con = web.conexion()
    try:
        encargos.tocar(con, "encargo-1", url="https://encargo-1.ejemplo")
        con.commit()
    finally:
        con.close()

    r = cliente.post("/encargos/encargo-1/renombrar", data={"nombre": "la-tienda"})
    assert r.status_code == 200
    assert "rompería el enlace" in r.text

    con = web.conexion()
    try:
        assert encargos.ver(con, "encargo-1"), "se renombró igual"
    finally:
        con.close()


# ── la ficha ──────────────────────────────────────────────────────────────────


def test_la_ficha_enseña_lo_sabido_los_huecos_y_lo_que_falta(cliente):
    """La ficha ES el estado: si no se puede leer entera desde aquí, saber en qué
    punto va una entrevista obliga a abrir un archivo JSON a mano."""
    _un_encargo(cliente)
    con = web.conexion()
    try:
        ficha = encargos.cargar_ficha(con, "encargo-1")
        ficha.responde("dia", "Una panadería de barrio, abro a las seis.")
        ficha.rendirse("duele")
        encargos.guardar_ficha(con, ficha)
        con.commit()
    finally:
        con.close()

    cuerpo = cliente.get("/encargos/encargo-1").text
    assert "Una panadería de barrio" in cuerpo
    assert "No lo sabe" in cuerpo, "el hueco declarado no se ve"
    # La fase que sigue pidiendo turno, dicha por su título y no por su id.
    assert "Cómo quieres que se vea" in cuerpo


def test_la_ficha_enseña_la_conversacion_en_las_dos_direcciones(cliente):
    """Cuando algo de la ficha extraña, lo primero que se quiere ver es qué dijo
    ella exactamente — y qué se le contestó."""
    _un_encargo(cliente)
    con = web.conexion()
    try:
        buzon.aparcar(con, "encargo-1", 777, "Vendo pan y bollería")
        buzon.encolar_salida(con, "encargo-1", "¿Cómo es un día normal?")
        con.commit()
    finally:
        con.close()

    cuerpo = cliente.get("/encargos/encargo-1").text
    assert "Vendo pan y bollería" in cuerpo
    assert "¿Cómo es un día normal?" in cuerpo


def test_lo_que_espera_al_agente_se_cuenta_en_la_lista(cliente):
    """Un encargo con mensajes aparcados y sin agente abierto es el caso que el
    buzón existe para que no se pierda: tiene que verse sin entrar."""
    _un_encargo(cliente)
    con = web.conexion()
    try:
        buzon.aparcar(con, "encargo-1", 777, "Otra cosa que se me olvidó")
        con.commit()
    finally:
        con.close()

    assert "1 sin entregar" in cliente.get("/encargos").text


def test_el_indice_y_las_secciones_cuadran_en_las_dos_vistas(cliente):
    """El índice y las secciones se escriben en sitios distintos de la plantilla.
    Un `{% if %}` mal cerrado deja una entrada apuntando a una sección que no se
    renderizó: el enlace no hace nada y la página se queda en blanco."""
    import re

    def cuadran(cuerpo, esperadas):
        del_indice = set(re.findall(r'data-sec="([a-z]+)"', cuerpo))
        presentes = set(re.findall(
            r'<section class="seccion" id="sec-([a-z]+)"', cuerpo))
        assert del_indice == presentes == esperadas

    _un_encargo(cliente)
    cuadran(cliente.get("/encargos").text, {"encargos", "personas", "registro"})
    cuadran(cliente.get("/encargos/encargo-1").text,
            {"ficha", "conversacion", "registro"})


# ── el registro ───────────────────────────────────────────────────────────────


def test_el_registro_se_filtra_por_encargo_desde_la_url(cliente):
    """Por la URL y no por JavaScript: una vista filtrada se puede guardar,
    compartir y recargar, que es lo que hace falta mirándolo desde el móvil."""
    _un_encargo(cliente)
    con = web.conexion()
    try:
        encargos.registrar(con, "sale", "lo de este", encargo_id="encargo-1")
        encargos.registrar(con, "falla", "lo de ningún encargo")
        con.commit()
    finally:
        con.close()

    todo = cliente.get("/encargos").text
    solo = cliente.get("/encargos?enc=encargo-1").text
    assert "lo de ningún encargo" in todo
    assert "lo de ningún encargo" not in solo
    assert "lo de este" in solo
    assert "(filtrado)" in solo


# ── abrir el entrevistador ────────────────────────────────────────────────────


def test_abrir_el_agente_llama_al_entrevistador_y_lo_dice_en_pantalla(
    cliente, monkeypatch
):
    """La vista no abre ventanas: se lo pide al entrevistador y cuenta dónde
    quedó. Sin decir dónde, «se abrió» obliga a buscarlo por todas las sesiones."""
    llamadas = []

    def falso_abrir(con, encargo_id):
        llamadas.append(encargo_id)
        return {"slot_id": 3, "pane_id": "%9", "session": "encargos",
                "ventana": 2}

    monkeypatch.setattr(entrevistador, "abrir_agente", falso_abrir, raising=False)

    _un_encargo(cliente)
    r = cliente.post("/encargos/encargo-1/agente")
    assert r.status_code == 200
    # Dos veces: la primera la pidió el alta (229), la segunda este botón.
    assert llamadas == ["encargo-1", "encargo-1"]
    assert "encargos" in r.text and "slot 3" in r.text


def test_si_el_entrevistador_no_puede_abrir_se_dice_en_voz_alta(
    cliente, monkeypatch
):
    """🔴 Regla dura 21: lo que falla en tmux se dice. «No abrió nada» sin motivo
    es peor aquí que en ningún sitio — quien espera al otro lado es alguien de
    fuera que no tiene forma de saber que no le escucha nadie."""
    def no_puede(con, encargo_id):
        raise RuntimeError("no hay servidor de tmux al que pedirle una ventana")

    monkeypatch.setattr(entrevistador, "abrir_agente", no_puede, raising=False)

    _un_encargo(cliente)
    r = cliente.post("/encargos/encargo-1/agente")
    assert r.status_code == 200
    assert "no hay servidor de tmux" in r.text


# ── 🔴 la vista no habla con Telegram ─────────────────────────────────────────


def test_la_vista_no_manda_NADA_por_telegram(cliente, monkeypatch):
    """🔴 Regla dura 22, comprobada rompiendo la salida en vez de leyendo el código.

    `_llamar` es el único sitio por el que `Bot` y `BotDeEncargos` salen a la red,
    y `_multiparte` el único por el que suben un archivo. Si cualquier ruta de esta
    pantalla intentara hablar con Telegram, reventaría aquí y con nombre.

    Importa porque `hub-web` expone el puerto —y con él una shell, regla dura 8—:
    la única razón de que el relé sea un proceso aparte es que el token esté sólo
    en él.
    """
    def prohibido(*args, **kwargs):
        raise AssertionError("la vista de encargos ha intentado hablar con Telegram")

    monkeypatch.setattr(telegram.Bot, "_llamar", prohibido)
    monkeypatch.setattr(telegram.BotDeEncargos, "_multiparte", prohibido)
    monkeypatch.setattr(entrevistador, "abrir_agente",
                        lambda con, encargo_id: {"slot_id": 1, "pane_id": "%1",
                                                 "session": "s", "ventana": 0},
                        raising=False)

    _escribe_al_bot()
    for respuesta in (
        cliente.get("/encargos"),
        cliente.post("/encargos/persona",
                     data={"user_id": 777, "alias": "tienda", "estado": "activo",
                           "es_dueno": "1", "nota": "panadería"}),
        cliente.post("/encargos/crear",
                     data={"encargo_id": "encargo-1", "user_id": 777}),
        cliente.post("/encargos/encargo-1/renombrar", data={"nombre": "la-tienda"}),
        cliente.post("/encargos/la-tienda/agente"),
        cliente.get("/encargos/la-tienda"),
        cliente.get("/encargos?enc=la-tienda"),
    ):
        assert respuesta.status_code == 200


def test_la_confianza_se_marca_por_persona_y_se_guarda(cliente):
    """Decisión 236: para quien tiene criterio técnico y no hace falta revisar."""
    _escribe_al_bot()
    cliente.post("/encargos/persona",
                 data={"user_id": 777, "alias": "tienda", "estado": "activo", "de_confianza": "1"})
    con = web.conexion()
    try:
        assert encargos.de_confianza(con, 777) is True
    finally:
        con.close()
    cliente.post("/encargos/persona", data={"user_id": 777, "alias": "tienda", "estado": "activo"})
    con = web.conexion()
    try:
        assert encargos.de_confianza(con, 777) is False, "la casilla sin marcar la quita"
    finally:
        con.close()


def test_volver_a_guardar_a_quien_ya_tiene_su_pagina_no_le_abre_otro_encargo(cliente):
    _escribe_al_bot()
    _de_alta(cliente)
    con = web.conexion()
    try:
        encargos.tocar(con, "encargo-1", estado="publicado", url="https://x")
        encargos.editar_persona(con, 777, estado="bloqueado")
        con.commit()
    finally:
        con.close()

    _de_alta(cliente)          # bloqueado → activo otra vez

    con = web.conexion()
    try:
        assert [e["id"] for e in encargos.listar(con)] == ["encargo-1"]
    finally:
        con.close()


# ── Alta por el chat web (decisión 246) ─────────────────────────────────────


def test_dar_de_alta_por_el_chat_web_ensena_el_acceso_una_vez_y_abre_el_encargo(cliente, monkeypatch):
    from hub import chatweb, entrevistador, rele_encargos

    class ChatFalso:
        def crear_persona(self, usuario, nombre):
            assert usuario == "rosa-perez" and nombre == "Rosa Pérez"
            return 900000001, "clave-una-vez"

    abiertos = []
    monkeypatch.setattr(rele_encargos, "ajustes", lambda: {"chat_web": {"url": "https://chat.test/", "token_ref": "x"}})
    monkeypatch.setattr(chatweb, "bot", lambda ajustes: ChatFalso())
    monkeypatch.setattr(entrevistador, "empezar_con", lambda con, uid: abiertos.append(uid) or {})

    r = cliente.post("/encargos/persona-web", data={"nombre": "Rosa Pérez"})

    assert r.status_code == 200
    assert "clave-una-vez" in r.text and "rosa-perez" in r.text and "https://chat.test" in r.text
    con = web.conexion()
    try:
        p = encargos.ver_persona(con, 900000001)
        assert p["estado"] == "activo" and p["canal"] == "web" and p["alias"] == "Rosa Pérez"
        assert "clave-una-vez" not in json.dumps(dict(p))
    finally:
        con.close()
    assert abiertos == [900000001]


def test_sin_chat_web_configurado_el_alta_lo_dice(cliente, monkeypatch):
    from hub import rele_encargos

    monkeypatch.setattr(rele_encargos, "ajustes", lambda: {})
    r = cliente.post("/encargos/persona-web", data={"nombre": "Rosa"}, follow_redirects=False)
    assert r.status_code in (302, 303) and "chat_web" in r.headers["location"]
