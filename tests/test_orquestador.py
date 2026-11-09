"""El orquestador: lo que puede hacer, lo que no, y cuándo se le despierta.

Lo que se protege aquí son tres promesas del plan (PLAN-ORQUESTADOR.md):

- **El alcance es una cerradura** (decisión 256): sin nivel, ni lee sesiones ni
  manda nada, y `never` gana siempre (regla dura 7).
- **Detener detiene de verdad**: después, cualquier orden suya se niega.
- **Nada sale por Telegram salvo el timbre** (regla dura 22), ni siquiera el
  pedido, que ya lleva nombres de clientes.

tmux no se toca: las sesiones se simulan en la frontera (`entrega`, `tui`). El
recorrido con una sesión de Claude real se hizo a mano y está en la bitácora
de la decisión 258.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub import db, modelos, orquestador as orq, orquestador_cli, rele, transcripts, tui, web


@pytest.fixture
def escena(con):
    # alfa en `auto` para probar la mecánica sin confirmaciones; las de `ask`
    # tienen sus propios tests (decisión 279).
    for pid, guardrail in (("alfa", "auto"), ("beta", "ask"), ("prohibido", "never")):
        con.execute(
            "INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES (?,?,?,?)",
            (pid, pid.title(), f"/tmp/{pid}", guardrail),
        )
    con.commit()
    return con


@pytest.fixture
def sesion_libre(monkeypatch):
    """Una sesión de Claude Code viva y libre en `%5`, del proyecto alfa."""
    escritos: list[tuple[str, str]] = []
    monkeypatch.setattr(orq, "sesiones", lambda con, p: [
        {"pane_id": "%5", "nombre": "trabajo", "cwd": "/tmp/alfa",
         "agente": "Claude Code", "trabajando": False}] if p == "alfa" else [])
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (True, ""))
    monkeypatch.setattr(orq.entrega, "quien_hay", lambda pane: (tui.CLAUDE, ""))
    monkeypatch.setattr(orq.entrega, "entregar", lambda pane, texto: escritos.append((pane, texto)))
    return escritos


def _activa(pedido="haz algo en alfa"):
    tarea_id = orq.crear(pedido)
    with orq.editar(tarea_id) as t:
        t["estado"] = orq.ACTIVA
    return tarea_id


def _hace(segundos: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=segundos)).isoformat(timespec="seconds")


# ─────────────────────────────── los permisos ───────────────────────────────


def test_un_proyecto_que_no_esta_en_permisos_es_nada(escena):
    assert orq.nivel_de(escena, "alfa") == "nada"


def test_never_en_projects_yml_gana_a_cualquier_nivel(escena):
    """Regla dura 7: `never` significa nunca, aunque alguien lo suba aquí."""
    orq.fijar_nivel("prohibido", "alto")

    assert orq.nivel_de(escena, "prohibido") == "nada"


def test_fijar_a_nada_quita_el_proyecto_del_archivo(escena):
    orq.fijar_nivel("alfa", "medio")
    assert orq.leer_permisos() == {"alfa": "medio"}

    orq.fijar_nivel("alfa", "nada")
    assert orq.leer_permisos() == {}


def test_un_nivel_inventado_no_se_guarda(escena):
    with pytest.raises(ValueError):
        orq.fijar_nivel("alfa", "total")


def test_el_archivo_de_permisos_vive_fuera_de_la_carpeta_del_orquestador():
    """Lo único que él no debe poder tocar no vive donde trabaja."""
    assert orq.carpeta() not in orq.permisos_yml().parents


# ────────────────────────────────── la cola ─────────────────────────────────


def test_una_tarea_nueva_espera_en_cola_y_no_arranca_sola():
    tarea_id = orq.crear("revisa alfa")

    assert orq.cargar(tarea_id)["estado"] == orq.EN_COLA
    assert orq.viva() is None
    assert orq.bitacora(tarea_id)[0]["tipo"] == "pedido"


def test_una_tarea_vacia_no_se_encola():
    with pytest.raises(ValueError):
        orq.crear("   ")


def test_la_bomba_arranca_la_primera_de_la_cola_con_un_orquestador_nuevo(escena, monkeypatch):
    abiertos: list[str] = []
    monkeypatch.setattr(orq, "localizar", lambda: None)
    monkeypatch.setattr(orq, "abrir_panel", lambda texto: abiertos.append(texto) or "%9")
    primera = orq.crear("la primera")
    segunda = orq.crear("la segunda")

    orq.bombear(escena)

    assert orq.cargar(primera)["estado"] == orq.ACTIVA
    assert orq.cargar(segunda)["estado"] == orq.EN_COLA
    assert len(abiertos) == 1 and primera in abiertos[0]
    assert orq.cargar(primera)["despertar"] == []


def test_con_una_en_curso_la_siguiente_espera_su_turno(escena, monkeypatch):
    monkeypatch.setattr(orq, "localizar", lambda: None)
    monkeypatch.setattr(orq, "abrir_panel", lambda texto: "%9")
    _activa()
    siguiente = orq.crear("otra")

    orq.bombear(escena)

    assert orq.cargar(siguiente)["estado"] == orq.EN_COLA


def test_si_el_orquestador_no_arranca_se_rinde_a_la_tercera(escena, monkeypatch):
    """Sin tope abriría una ventana nueva cada 20 s para siempre."""
    def no_arranca(texto):
        raise RuntimeError("claude murió al arrancar")
    monkeypatch.setattr(orq, "localizar", lambda: None)
    monkeypatch.setattr(orq, "abrir_panel", no_arranca)
    tarea_id = orq.crear("algo")

    for _ in range(orq.INTENTOS_DE_ARRANQUE):
        with orq.editar(tarea_id) as t:
            if t["estado"] == orq.DETENIDA:
                break
            t["despertar"] = t["despertar"] or ["Tarea nueva: x"]
        orq.bombear(escena)

    assert orq.cargar(tarea_id)["estado"] == orq.DETENIDA


# ─────────────────────────────── sus manos ──────────────────────────────────


def test_sin_tarea_en_curso_sus_manos_se_niegan(escena):
    with pytest.raises(orq.TareaCerrada):
        orq.preguntar("¿sigo?")


def test_sin_alcance_no_ve_ni_manda_nada(escena, sesion_libre):
    """🔴 La cerradura (256): se niega aquí, no en su prompt."""
    _activa()

    with pytest.raises(orq.SinPermiso):
        orq.mandar(escena, "alfa", "%5", "cambia el logo")

    assert sesion_libre == []


def test_no_manda_a_un_panel_que_no_es_de_ese_proyecto(escena, sesion_libre):
    """Un pane_id equivocado le mandaría el trabajo de un proyecto a otro."""
    orq.fijar_nivel("beta", "alto")
    _activa()

    with pytest.raises(ValueError, match="no es una sesión viva"):
        orq.mandar(escena, "beta", "%5", "haz algo")

    assert sesion_libre == []


def test_lo_que_manda_lleva_de_donde_viene_el_nivel_y_lo_que_nunca(escena, sesion_libre):
    orq.fijar_nivel("alfa", "medio")
    tarea_id = _activa()

    r = orq.mandar(escena, "alfa", "%5", "aplica el logo 4 a la landing")

    assert r["enviado"] is True
    pane, texto = sesion_libre[0]
    assert pane == "%5"
    assert texto.startswith(orq.marca(tarea_id, 1))
    assert "medio" in texto and orq.DESCRIPCION["medio"] in texto
    assert "desplegar a producción" in texto
    assert "aplica el logo 4 a la landing" in texto
    assert "RESUMEN" in texto
    tarea = orq.cargar(tarea_id)
    assert tarea["estado"] == orq.ESPERANDO_SESION
    assert tarea["esperas"][0]["pane_id"] == "%5"
    assert tarea["proyectos"] == ["alfa"]


def test_si_la_sesion_esta_trabajando_no_escribe_y_espera_a_que_quede_libre(
        escena, sesion_libre, monkeypatch):
    """No se encola en la cola de Claude: el hub creería saber un orden que no controla."""
    orq.fijar_nivel("alfa", "alto")
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (False, "está trabajando ahora mismo"))
    tarea_id = _activa()

    r = orq.mandar(escena, "alfa", "%5", "haz algo")

    assert r["enviado"] is False
    assert sesion_libre == []
    assert orq.cargar(tarea_id)["esperas"][0]["tipo"] == "libre"


def test_lo_escrito_sin_confirmar_no_se_vuelve_a_escribir(escena, sesion_libre, monkeypatch):
    """Reintentar duplicaría la orden, y en una sesión eso es trabajo de más."""
    orq.fijar_nivel("alfa", "alto")
    def a_medias(pane, texto):
        raise orq.entrega.EscritoSinConfirmar("no se vio salir")
    monkeypatch.setattr(orq.entrega, "entregar", a_medias)
    tarea_id = _activa()

    r = orq.mandar(escena, "alfa", "%5", "haz algo")

    assert r == {"enviado": True, "confirmado": False, "espera": 1}
    assert orq.cargar(tarea_id)["estado"] == orq.ESPERANDO_SESION


def test_abrir_se_niega_si_ya_hay_una_sesion(escena, sesion_libre):
    """Decisión suya: si hay una, ésa; si hay varias, se le pregunta."""
    orq.fijar_nivel("alfa", "alto")
    _activa()

    with pytest.raises(ValueError, match="Usa ésa"):
        orq.abrir_sesion(escena, "alfa")


def test_tres_sesiones_del_mismo_slot_se_distinguen_por_su_pestana(escena, monkeypatch):
    """Sólo con el slot salían las tres como «Hub - Dev» y nadie sabía a cuál
    mandar. Lo que las distingue es lo que dice la pestaña de /trabajo: el
    nombre puesto a mano o, si no, el título de Claude."""
    escena.execute("""INSERT INTO slot (id, proyecto_id, nombre, ruta, status, creado_en)
                      VALUES (1,'alfa','Hub - Dev','/tmp/alfa','activo','2026-09-23')""")
    escena.execute("INSERT INTO snapshot (id, tomado_en, server_pid) VALUES (1,'2026-09-23',99)")
    for pane, ventana in (("%2", 1), ("%3", 2), ("%32", 3)):
        escena.execute(
            """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                                  cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
               VALUES (1,?,'Personal',?,0,'/tmp/alfa','✳ x','claude','x','alfa',1)""",
            (pane, ventana))
    escena.commit()
    monkeypatch.setattr(orq.tmux, "listar_ventanas", lambda s: [
        {"indice": 1, "etiqueta": "Hub remoto"},
        {"indice": 2, "etiqueta": "Hub - Dev"},
        {"indice": 3, "etiqueta": "hub · orquestador"},
    ])
    monkeypatch.setattr(orq.entrega, "quien_hay",
                        lambda pane: (type("A", (), {"nombre": "Claude Code"})(), ""))
    monkeypatch.setattr(orq.tui, "ocupado", lambda agente, pane: False)

    nombres = {s["pane_id"]: s["nombre"] for s in orq.sesiones(escena, "alfa")}

    assert nombres == {"%2": "Hub - Dev › Hub remoto",
                       "%3": "Hub - Dev",          # la pestaña repite el slot: no se dobla
                       "%32": "Hub - Dev › hub · orquestador"}


# ────────────────────────────── despertarlo ─────────────────────────────────


@pytest.fixture
def mirando(monkeypatch):
    """El estado de `%5` lo decide el test: vivo, trabajando o desaparecido."""
    estado = {"vivo": True, "trabajando": False, "permiso": False}
    monkeypatch.setattr(orq.entrega, "quien_hay",
                        lambda pane: (tui.CLAUDE, "") if estado["vivo"] else (None, "el panel ya no existe"))
    monkeypatch.setattr(orq.tui, "ocupado", lambda agente, pane: estado["trabajando"])
    monkeypatch.setattr(orq, "_pide_permiso", lambda pane: estado["permiso"])
    return estado


def _con_espera(enviado_hace: int, visto_trabajando=False, tipo="respuesta"):
    tarea_id = _activa()
    with orq.editar(tarea_id) as t:
        e = orq._nueva_espera(t, "alfa", "%5", tipo=tipo)
        e["enviado"] = _hace(enviado_hace)
        e["visto_trabajando"] = visto_trabajando
        t["estado"] = orq.ESPERANDO_SESION
    return tarea_id


def _revisar(tarea_id):
    with orq.editar(tarea_id) as t:
        orq._revisar_esperas(t)
    return orq.cargar(tarea_id)


def test_cuando_la_sesion_acaba_se_le_despierta_para_leerla(mirando):
    tarea_id = _con_espera(enviado_hace=200, visto_trabajando=True)

    t = _revisar(tarea_id)

    assert t["esperas"][0]["estado"] == "terminada"
    assert "./orq respuesta %5" in t["despertar"][0]
    assert t["estado"] == orq.ACTIVA


def test_justo_despues_de_mandar_quieta_no_significa_acabada(mirando):
    """El spinner aún no arrancó: darla por acabada leería una respuesta vacía."""
    tarea_id = _con_espera(enviado_hace=5)

    t = _revisar(tarea_id)

    assert t["esperas"][0]["estado"] == "esperando"
    assert t["despertar"] == []


def test_una_orden_corta_acaba_entre_dos_latidos_y_se_da_por_hecha_igual(mirando):
    tarea_id = _con_espera(enviado_hace=orq.QUIETA_TRAS + 5)

    assert _revisar(tarea_id)["esperas"][0]["estado"] == "terminada"


def test_mientras_trabaja_no_se_le_molesta(mirando):
    mirando["trabajando"] = True
    tarea_id = _con_espera(enviado_hace=600)

    t = _revisar(tarea_id)

    assert t["esperas"][0]["visto_trabajando"] is True
    assert t["despertar"] == []


def test_si_la_sesion_desaparece_se_le_dice(mirando):
    mirando["vivo"] = False
    tarea_id = _con_espera(enviado_hace=60)

    t = _revisar(tarea_id)

    assert t["esperas"][0]["estado"] == "perdida"
    assert "ya no está" in t["despertar"][0]


def test_si_la_sesion_pide_un_permiso_se_le_dice_una_vez(mirando):
    """Él no puede darlo: sólo el dueño, en el hub."""
    mirando["permiso"] = True
    tarea_id = _con_espera(enviado_hace=120)

    _revisar(tarea_id)
    t = _revisar(tarea_id)

    assert len(t["despertar"]) == 1
    assert "permiso" in t["despertar"][0]


def test_pasado_el_tope_se_avisa_una_vez_y_se_sigue_esperando(mirando):
    """Una batería de tests larga es trabajo legítimo: no se cancela nada."""
    mirando["trabajando"] = True
    tarea_id = _con_espera(enviado_hace=orq.TOPE_MINUTOS * 60 + 30)

    _revisar(tarea_id)
    t = _revisar(tarea_id)

    assert len(t["despertar"]) == 1
    assert t["esperas"][0]["estado"] == "esperando"


def test_si_el_orquestador_esta_trabajando_el_aviso_espera_al_siguiente_latido(monkeypatch):
    tarea_id = _activa()
    with orq.editar(tarea_id) as t:
        t["despertar"] = ["la sesión terminó"]
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (False, "está trabajando ahora mismo"))

    r = orq._despertar(tarea_id)

    assert "pendiente" in r
    assert orq.cargar(tarea_id)["despertar"] == ["la sesión terminó"]


def test_varios_avisos_llegan_en_un_solo_mensaje(monkeypatch):
    """Cada entrega es un turno, y un turno relee el contexto entero."""
    entregados: list[str] = []
    tarea_id = _activa()
    with orq.editar(tarea_id) as t:
        t["despertar"] = ["una terminó", "otra terminó"]
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (True, ""))
    monkeypatch.setattr(orq.entrega, "entregar", lambda pane, texto: entregados.append(texto))

    orq._despertar(tarea_id)

    assert len(entregados) == 1 and "una terminó" in entregados[0] and "otra terminó" in entregados[0]
    assert orq.cargar(tarea_id)["despertar"] == []


def test_si_su_ventana_se_perdio_se_abre_otra_que_retoma(monkeypatch):
    abiertos: list[str] = []
    tarea_id = _activa()
    with orq.editar(tarea_id) as t:
        t["despertar"] = ["la sesión terminó"]
    monkeypatch.setattr(orq, "localizar", lambda: None)
    monkeypatch.setattr(orq, "abrir_panel", lambda texto: abiertos.append(texto) or "%9")

    orq._despertar(tarea_id)

    assert abiertos[0].startswith("Retomas la tarea " + tarea_id)
    assert "la sesión terminó" in abiertos[0]


# ─────────────────────────── El dueño: bandeja y detener ────────────────────────


def test_preguntar_deja_la_tarea_esperando_y_su_respuesta_la_despierta():
    tarea_id = _activa()

    orq.preguntar("¿A cuál de las dos sesiones?")
    assert orq.cargar(tarea_id)["estado"] == orq.ESPERANDO_DUENO

    orq.responder(tarea_id, "a la de la izquierda")
    t = orq.cargar(tarea_id)
    assert t["estado"] == orq.ACTIVA
    assert t["pregunta"] is None
    assert "a la de la izquierda" in t["despertar"][0]


def test_si_manda_trabajo_con_la_pregunta_abierta_se_le_puede_contestar_igual(
        escena, sesion_libre):
    """Pasó en el primer ensayo: preguntó, mandó sin esperar, y la respuesta del
    dueño se rechazaba porque `mandar` había cambiado el estado."""
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()
    orq.preguntar("¿minúsculas o mayúsculas?")

    orq.mandar(escena, "alfa", "%5", "mientras, cuenta las líneas")
    assert orq.cargar(tarea_id)["estado"] == orq.ESPERANDO_DUENO

    orq.responder(tarea_id, "minúsculas")
    assert orq.cargar(tarea_id)["pregunta"] is None


def test_responder_sin_pregunta_abierta_no_hace_nada():
    tarea_id = _activa()

    with pytest.raises(ValueError):
        orq.responder(tarea_id, "sí")


def test_detener_interrumpe_solo_a_quien_trabaja_y_cierra_sus_manos(monkeypatch):
    """🔴 Lo que hace real el botón: después, cualquier orden suya se niega."""
    teclas: list[tuple[str, str]] = []
    tarea_id = _con_espera(enviado_hace=60)
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq.tui, "detectar", lambda pane: tui.CLAUDE)
    monkeypatch.setattr(orq.tui, "ocupado", lambda agente, pane: pane == "%5")
    monkeypatch.setattr(orq.tmux, "tecla_en_panel", lambda pane, t: teclas.append((pane, t)))

    r = orq.detener(tarea_id)

    assert r["ok"] and teclas == [("%5", "Escape")]
    assert orq.cargar(tarea_id)["esperas"][0]["estado"] == "cancelada"
    with pytest.raises(orq.TareaCerrada, match="DETENIDA"):
        orq.avance("sigo")


def test_detener_interrumpe_tambien_una_sesion_que_ya_se_habia_dado_por_acabada(monkeypatch):
    """Pasó en el ensayo: la espera estaba «terminada» y la sesión seguía con
    un comando de cien segundos. Detener tiene que pararla igual."""
    teclas: list[tuple[str, str]] = []
    tarea_id = _con_espera(enviado_hace=60)
    with orq.editar(tarea_id) as t:
        t["esperas"][0]["estado"] = "terminada"
    monkeypatch.setattr(orq, "localizar", lambda: None)
    monkeypatch.setattr(orq.tui, "detectar", lambda pane: tui.CLAUDE)
    monkeypatch.setattr(orq.tui, "ocupado", lambda agente, pane: True)
    monkeypatch.setattr(orq.tmux, "tecla_en_panel", lambda pane, t: teclas.append((pane, t)))

    orq.detener(tarea_id)

    assert teclas == [("%5", "Escape")]


def test_quitar_de_la_cola_no_toca_ningun_panel(monkeypatch):
    monkeypatch.setattr(orq.tmux, "tecla_en_panel",
                        lambda *a: pytest.fail("no debía pulsar nada"))
    tarea_id = orq.crear("para luego")

    assert orq.detener(tarea_id)["ok"]
    assert orq.cargar(tarea_id)["estado"] == orq.DETENIDA


def test_terminar_exige_un_resumen_y_cancela_lo_pendiente():
    tarea_id = _con_espera(enviado_hace=10)

    with pytest.raises(ValueError):
        orq.terminar("  ")
    orq.terminar("Hecho: logo 4 en la landing.")

    t = orq.cargar(tarea_id)
    assert t["estado"] == orq.TERMINADA
    assert t["esperas"][0]["estado"] == "cancelada"


# ───────────────────────────────── el timbre ────────────────────────────────


def test_el_timbre_no_lleva_ni_el_pedido(con):
    """🔴 Regla dura 22: «en <cliente> dame logos» ya nombra a un cliente."""
    _activa("en el-cliente-secreto dame opciones de logos")
    orq.preguntar("¿Te valen tres opciones?")
    orq.terminar("hecho")

    textos = [json.loads(r.read_text())["texto"] for r in orq.timbres_pendientes()]
    assert len(textos) == 2
    assert not any("cliente-secreto" in t or "logos" in t or "opciones" in t for t in textos)


class _Bot:
    def __init__(self, falla=None):
        self.enviados: list[tuple[int, str]] = []
        self.falla = falla

    def enviar(self, chat_id, texto):
        if self.falla:
            raise self.falla
        self.enviados.append((chat_id, texto))
        return 1


def test_el_rele_toca_el_timbre_al_dueno_y_lo_borra(con):
    rele.canal.anotar_contacto(con, 777, "duena", "La dueña")
    rele.canal.marcar_dueno(con, 777)
    orq.timbre("Tarea t-1 terminada.")
    bot = _Bot()

    assert rele.enviar_timbres(con, bot) == 1

    assert bot.enviados[0][0] == 777 and "t-1" in bot.enviados[0][1]
    assert orq.timbres_pendientes() == []


def test_si_telegram_no_responde_el_timbre_se_queda_para_la_vuelta_siguiente(con):
    rele.canal.anotar_contacto(con, 777, "duena", "La dueña")
    rele.canal.marcar_dueno(con, 777)
    orq.timbre("Tarea t-1 terminada.")

    rele.enviar_timbres(con, _Bot(falla=rele.telegram.TelegramCaido("sin red")))

    assert len(orq.timbres_pendientes()) == 1


# ─────────────────────────── leer lo que contestó ───────────────────────────


def test_la_respuesta_se_lee_del_transcript_por_la_marca(tmp_path, monkeypatch):
    """En una misma carpeta puede haber tres sesiones: la marca es lo que casa."""
    tarea_id = _con_espera(enviado_hace=30)
    registro = tmp_path / "transcripts"
    directorio = registro / transcripts.slug_de("/tmp/alfa")
    directorio.mkdir(parents=True)
    lineas = [
        {"type": "user", "uuid": "u0", "timestamp": _hace(90),
         "message": {"role": "user", "content": "otra cosa de antes"}},
        {"type": "assistant", "uuid": "a0", "timestamp": _hace(80),
         "message": {"role": "assistant", "content": [{"type": "text", "text": "respuesta vieja"}]}},
        {"type": "user", "uuid": "u1", "timestamp": _hace(29),
         "message": {"role": "user", "content": orq.marca(tarea_id, 1) + " haz esto"}},
        {"type": "assistant", "uuid": "a1", "timestamp": _hace(10),
         "message": {"role": "assistant", "content": [{"type": "text",
                     "text": "Listo.\nRESUMEN\n- hecho: todo"}]}},
    ]
    (directorio / "sesion.jsonl").write_text("\n".join(json.dumps(l) for l in lineas))
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", registro)
    monkeypatch.setattr(orq.tmux, "listar_paneles",
                        lambda: [{"pane_id": "%5", "cwd": "/tmp/alfa"}])

    r = orq.respuesta("%5")

    assert r["origen"] == "transcript"
    assert "RESUMEN" in r["texto"]
    assert "respuesta vieja" not in r["texto"]


# ─────────────────────────── cómo se le arranca ─────────────────────────────


def test_su_sesion_no_se_confunde_con_un_espejo_de_la_terminal():
    """Con el prefijo de los espejos, `localizar()` no lo veía nunca y la bomba
    abría otro orquestador en cada latido. Pasó en el primer ensayo real."""
    from hub import tmux

    assert not orq.SESION.startswith(tmux.PREFIJO_ESPEJO)


def test_arranca_en_opus_y_sin_poder_preguntar_permisos():
    """`dontAsk`: lo no permitido se rechaza, no se queda esperando a nadie.
    Opus por decisión suya del 22-sep (257), con id exacto (91)."""
    comando = orq.comando_de_arranque("Tarea nueva: t-1").completa()

    assert "--permission-mode dontAsk" in comando
    assert f"--model {modelos.ORQUESTADOR}" in comando
    assert modelos.ORQUESTADOR == "claude-opus-5-5"


def test_su_carpeta_le_niega_escribir():
    """🔴 El hub no escribe en los proyectos, y su agente tampoco (254)."""
    carpeta = orq.preparar()

    ajustes = json.loads((carpeta / ".claude" / "settings.json").read_text())
    assert {"Edit", "Write", "NotebookEdit"} <= set(ajustes["permissions"]["deny"])
    assert not any(p.startswith(("Edit", "Write")) for p in ajustes["permissions"]["allow"])
    assert (carpeta / "orq").stat().st_mode & 0o111
    assert "Nunca sin el dueño" in (carpeta / "CLAUDE.md").read_text()


# ─────────────────────────────────── el CLI ─────────────────────────────────


def test_el_cli_dice_por_que_no_puede_y_sale_con_error(escena, capsys, monkeypatch):
    monkeypatch.setattr(orquestador_cli.db, "conectar", lambda ruta: escena)
    _activa()

    codigo = orquestador_cli.main(["sesiones", "alfa"])

    assert codigo == 1
    assert "no tienes alcance" in capsys.readouterr().err


def test_el_cli_ensena_la_tarea_con_su_alcance(escena, capsys, monkeypatch):
    monkeypatch.setattr(orquestador_cli.db, "conectar", lambda ruta: escena)
    orq.fijar_nivel("alfa", "bajo")
    _activa("revisa alfa")

    assert orquestador_cli.main(["tarea"]) == 0

    salida = capsys.readouterr().out
    assert "revisa alfa" in salida
    assert "alfa (Alfa): bajo" in salida
    assert "beta" not in salida


# ─────────────────── guardrail ask: el dueño confirma (279) ──────────────────


def _alfa_pide_confirmar(con):
    con.execute("UPDATE proyecto SET guardrail = 'ask' WHERE id = 'alfa'")
    con.commit()


def test_con_ask_mandar_crea_una_peticion_y_no_escribe_nada(escena, sesion_libre):
    _alfa_pide_confirmar(escena)
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()

    with pytest.raises(orq.PendienteDeConfirmar) as exc:
        orq.mandar(escena, "alfa", "%5", "cambia el logo")

    assert sesion_libre == []
    tarea = orq.cargar(tarea_id)
    assert tarea["estado"] == orq.ESPERANDO_DUENO
    [conf] = orq.pendientes_de_confirmar(tarea)
    assert conf["proyecto"] == "alfa" and "cambia el logo" in conf["detalle"]
    assert exc.value.conf_id == conf["id"]


def test_con_ask_repetir_la_orden_no_crea_otra_peticion(escena, sesion_libre):
    _alfa_pide_confirmar(escena)
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()
    for _ in range(3):
        with pytest.raises(orq.PendienteDeConfirmar):
            orq.mandar(escena, "alfa", "%5", "cambia el logo")

    assert len(orq.cargar(tarea_id)["confirmaciones"]) == 1


def test_con_auto_manda_sin_preguntar(escena, sesion_libre):
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()

    assert orq.mandar(escena, "alfa", "%5", "cambia el logo")["enviado"] is True
    assert not orq.cargar(tarea_id).get("confirmaciones")


def test_con_never_ni_siquiera_llega_a_pedir_confirmacion(escena, sesion_libre):
    orq.fijar_nivel("prohibido", "alto")
    tarea_id = _activa()

    with pytest.raises(orq.SinPermiso):
        orq.mandar(escena, "prohibido", "%5", "haz algo")

    assert not orq.cargar(tarea_id).get("confirmaciones")


def test_confirmada_despierta_al_orquestador_y_lo_siguiente_ya_se_manda(escena, sesion_libre):
    _alfa_pide_confirmar(escena)
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()
    with pytest.raises(orq.PendienteDeConfirmar):
        orq.mandar(escena, "alfa", "%5", "cambia el logo")

    orq.confirmar(tarea_id, 1, aprobar=True)

    tarea = orq.cargar(tarea_id)
    assert tarea["estado"] == orq.ACTIVA
    assert "CONFIRMÓ" in tarea["despertar"][-1]
    assert orq.mandar(escena, "alfa", "%5", "cambia el logo")["enviado"] is True
    assert orq.mandar(escena, "alfa", "%5", "y ahora el pie")["enviado"] is True
    assert len(sesion_libre) == 2


def test_negada_no_escribe_y_no_se_vuelve_a_preguntar(escena, sesion_libre):
    _alfa_pide_confirmar(escena)
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()
    with pytest.raises(orq.PendienteDeConfirmar):
        orq.mandar(escena, "alfa", "%5", "cambia el logo")

    orq.confirmar(tarea_id, 1, aprobar=False)

    with pytest.raises(orq.SinPermiso, match="NO confirmó"):
        orq.mandar(escena, "alfa", "%5", "cambia el logo")
    assert sesion_libre == []
    assert len(orq.cargar(tarea_id)["confirmaciones"]) == 1


def test_el_orquestador_no_tiene_orden_para_confirmar(escena):
    """🔴 Sólo el dueño confirma (256, 279): ni orden en `./orq` ni `curl`."""
    assert not any("confirm" in orden or "aprob" in orden for orden in orquestador_cli.ORDENES)
    ajustes = json.loads((orq.preparar() / ".claude" / "settings.json").read_text())
    assert "Bash(curl:*)" in ajustes["permissions"]["deny"]


def test_el_cli_dice_que_espera_al_dueno_sin_salir_con_error(escena, capsys, monkeypatch):
    monkeypatch.setattr(orquestador_cli.db, "conectar", lambda ruta: escena)
    monkeypatch.setattr(orq, "sesiones", lambda con, p: [
        {"pane_id": "%5", "nombre": "t", "cwd": "/tmp/beta", "agente": "Claude Code",
         "trabajando": False}])
    orq.fijar_nivel("beta", "alto")
    _activa()

    codigo = orquestador_cli.main(["mandar", "beta", "%5", "haz algo"])

    assert codigo == 0
    assert "confirme" in capsys.readouterr().out


# ───────────────────────────────── la pantalla ──────────────────────────────


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def test_la_pantalla_se_pinta_y_encola(cliente, escena):
    assert cliente.get("/orquestador").status_code == 200

    r = cliente.post("/orquestador/tarea", data={"pedido": "revisa alfa"}, follow_redirects=False)

    assert r.status_code == 303
    assert orq.en_cola()[0]["pedido"] == "revisa alfa"
    assert "revisa alfa" in cliente.get(r.headers["location"]).text


def test_la_pregunta_abierta_sale_arriba_con_su_formulario(cliente, escena):
    _activa()
    orq.preguntar("¿Sigo con la B?")

    pagina = cliente.get("/orquestador").text

    assert "¿Sigo con la B?" in pagina
    assert pagina.index("¿Sigo con la B?") < pagina.index("Nueva tarea")
    assert 'action="/orquestador/responder"' in pagina


def test_la_confirmacion_pendiente_sale_arriba_y_se_contesta_desde_la_pantalla(
        cliente, escena, sesion_libre):
    _alfa_pide_confirmar(escena)
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()
    with pytest.raises(orq.PendienteDeConfirmar):
        orq.mandar(escena, "alfa", "%5", "cambia el logo")

    pagina = cliente.get("/orquestador").text
    assert "Pide confirmar: alfa" in pagina and "cambia el logo" in pagina
    assert pagina.index("Pide confirmar") < pagina.index("Nueva tarea")

    r = cliente.post("/orquestador/confirmar",
                     data={"tarea_id": tarea_id, "conf_id": "1", "decision": "si"},
                     follow_redirects=False)

    assert r.status_code == 303
    assert orq.cargar(tarea_id)["confirmaciones"][0]["estado"] == "aprobada"


def test_los_permisos_se_conceden_desde_la_pantalla(cliente, escena):
    cliente.post("/orquestador/permiso", data={"proyecto_id": "alfa", "nivel": "medio"},
                 follow_redirects=False)

    assert orq.leer_permisos() == {"alfa": "medio"}


def test_sin_transcriptor_el_audio_lo_dice_y_no_manda_nada(cliente):
    r = cliente.post("/orquestador/audio",
                     files={"audio": ("audio.webm", b"RIFF....", "audio/webm")})

    assert r.json()["ok"] is False
    assert "transcriptor" in r.json()["error"]
    assert orq.listar() == []


# ──────────────────────────── los puntos del plan ───────────────────────────


def test_los_pasos_se_cuentan_de_un_plan_numerado():
    plan = "1. mirar el estado\n2) contar\n   1. sub-apartado del uno\n3. cerrar\nnota suelta"

    assert orq.contar_pasos(plan) == 3
    assert orq.contar_pasos("sin números") == 0


def test_los_puntos_dicen_hecho_ahora_y_falta():
    tarea_id = _activa()
    orq.fijar_plan("1. a\n2. b\n3. c\n4. d")
    orq.marcar_paso(3)

    assert orq.puntos(orq.cargar(tarea_id)) == ["hecho", "hecho", "ahora", "falta"]


def test_esperando_al_dueno_el_punto_de_ahora_lo_dice():
    tarea_id = _activa()
    orq.fijar_plan("1. a\n2. b")
    orq.preguntar("¿sigo?")

    assert orq.puntos(orq.cargar(tarea_id)) == ["pregunta", "falta"]


def test_una_terminada_tiene_todos_hechos_y_una_detenida_lo_que_falto_parado():
    uno = _activa()
    orq.fijar_plan("1. a\n2. b\n3. c")
    orq.terminar("hecho antes de lo previsto")
    assert orq.puntos(orq.cargar(uno)) == ["hecho"] * 3

    dos = _activa()
    orq.fijar_plan("1. a\n2. b\n3. c")
    orq.marcar_paso(2)
    orq.detener(dos)
    assert orq.puntos(orq.cargar(dos)) == ["hecho", "parado", "parado"]


def test_un_paso_fuera_del_plan_se_niega():
    _activa()
    orq.fijar_plan("1. a\n2. b")

    with pytest.raises(ValueError, match="de 1 a 2"):
        orq.marcar_paso(5)


def test_la_lista_se_filtra_por_proyecto(cliente, escena):
    for pedido, proyecto in (("en alfa", "alfa"), ("en beta", "beta")):
        tarea_id = _activa(pedido)
        with orq.editar(tarea_id) as t:
            t["proyectos"] = [proyecto]
        orq.terminar("hecho")

    pagina = cliente.get("/orquestador?proyecto=beta").text

    assert "en beta" in pagina and "en alfa" not in pagina


def test_los_permisos_viven_en_su_propia_pantalla(cliente, escena):
    principal = cliente.get("/orquestador").text
    permisos = cliente.get("/orquestador/permisos")

    assert 'action="/orquestador/permiso"' not in principal
    assert permisos.status_code == 200
    assert 'action="/orquestador/permiso"' in permisos.text
    assert "never en projects.yml" in permisos.text      # el de `prohibido`


# ─────────────────────── lo que dejó el 23-sep: nadie lo despertaba ──────────


def test_si_la_sesion_aun_arranca_se_espera_y_no_se_queda_colgado(escena, sesion_libre, monkeypatch):
    """Pasó el 23-sep: la sesión recién abierta aún arrancaba, `mandar` daba
    error, él anotó «se lo pido cuando acepte» y terminó el turno. No quedó
    ninguna espera, así que nadie lo despertó nunca."""
    orq.fijar_nivel("alfa", "alto")
    monkeypatch.setattr(orq.entrega, "panel_apto",
                        lambda pane: (False, "Claude Code está arrancando y todavía no acepta entrada"))
    tarea_id = _activa()

    r = orq.mandar(escena, "alfa", "%5", "haz algo")

    assert r["espera"] == "libre"
    assert orq.cargar(tarea_id)["esperas"][0]["tipo"] == "libre"


def test_una_espera_libre_acaba_solo_cuando_se_le_puede_escribir(mirando, monkeypatch):
    apto = {"v": False}
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (apto["v"], "arrancando"))
    tarea_id = _con_espera(enviado_hace=120, tipo="libre")

    assert _revisar(tarea_id)["despertar"] == []
    apto["v"] = True
    t = _revisar(tarea_id)
    assert "ya está libre" in t["despertar"][0]


def test_una_tarea_parada_sin_nada_pendiente_se_despierta_sin_repetir_en_el_mismo_latido(monkeypatch):
    """La red: ningún descuido suyo deja una tarea muerta en silencio."""
    tarea_id = _activa()
    viejo = _hace(orq.MINUTOS_SIN_NADA * 60 + 30)
    ruta = orq.dir_de(tarea_id) / "bitacora.jsonl"
    ruta.write_text(json.dumps({"cuando": viejo, "tipo": "avance", "texto": "espero"}) + "\n")
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq.tui, "ocupado", lambda agente, pane: False)

    with orq.editar(tarea_id) as t:
        orq._vigilar_quieta(t)
        orq._vigilar_quieta(t)

    t = orq.cargar(tarea_id)
    assert len(t["despertar"]) == 1 and "sin avanzar" in t["despertar"][0]


def test_si_esta_trabajando_la_red_no_lo_molesta(monkeypatch):
    tarea_id = _activa()
    (orq.dir_de(tarea_id) / "bitacora.jsonl").write_text(
        json.dumps({"cuando": _hace(3600), "tipo": "avance", "texto": "x"}) + "\n")
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq.tui, "ocupado", lambda agente, pane: True)

    with orq.editar(tarea_id) as t:
        orq._vigilar_quieta(t)

    assert orq.cargar(tarea_id)["despertar"] == []


def test_dar_nivel_a_un_proyecto_never_se_rechaza_y_no_dice_guardado(cliente):
    """La pantalla no ofrece selector para un `never`, pero una petición a mano
    sí llegaba: se guardaba «alto» y se contestaba «Guardado», aunque luego no
    rigiera. Visto en la instalación en limpio del 13-oct."""
    c = web.conexion()
    c.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES "
              "('prohibido','Prohibido','/tmp/p','never')")
    c.commit()
    c.close()

    r = cliente.post("/orquestador/permiso", data={"proyecto_id": "prohibido", "nivel": "alto"},
                     follow_redirects=False)

    assert "never" in r.headers["location"] and "Guardado" not in r.headers["location"]
    assert "prohibido" not in orq.leer_permisos()


def test_si_la_sesion_espera_en_un_menu_se_avisa_al_dueno_sin_fiarlo_al_modelo(
        escena, sesion_libre, monkeypatch):
    """Visto instalando en limpio: «¿confías en esta carpeta?» en la sesión del
    proyecto. La tarea esperaba con la razón bien escrita y al dueño no le
    llegaba nada. Un menú no se arregla esperando (decisión 265)."""
    orq.fijar_nivel("alfa", "alto")
    monkeypatch.setattr(orq.entrega, "panel_apto",
                        lambda pane: (False, "Claude Code está esperando que contestes algo"))
    monkeypatch.setattr(orq.tmux, "capturar_panel",
                        lambda p: " ❯ No, exit\n   Yes, I trust this folder\n Enter to confirm · Esc to cancel")
    tarea_id = _activa()

    r = orq.mandar(escena, "alfa", "%5", "haz algo")

    assert r["enviado"] is False and r["necesita_al_dueno"] is True
    assert sesion_libre == []                               # no se escribió encima del menú
    (aviso,) = [json.loads(t.read_text()) for t in orq.timbres_pendientes()]
    assert tarea_id in aviso["texto"] and "alfa" not in aviso["texto"]   # regla 22


def test_si_la_sesion_solo_trabaja_no_se_molesta_al_dueno(escena, sesion_libre, monkeypatch):
    orq.fijar_nivel("alfa", "alto")
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (False, "está trabajando ahora mismo"))
    monkeypatch.setattr(orq.tmux, "capturar_panel", lambda p: "❯ \n")
    _activa()

    r = orq.mandar(escena, "alfa", "%5", "haz algo")

    assert r["necesita_al_dueno"] is False
    assert orq.timbres_pendientes() == []


# ─────────────────────────────── reanudar ───────────────────────────────────


def _detenida(pedido="haz algo en alfa"):
    tarea_id = _activa(pedido)
    with orq.editar(tarea_id) as t:
        t["empezada"] = orq.ahora()
    orq.detener(tarea_id)
    return tarea_id


def test_una_tarea_detenida_se_reanuda_desde_donde_estaba_con_la_nota_del_dueno(monkeypatch):
    """Detener era de un solo sentido: había que dictarla otra vez (269)."""
    monkeypatch.setattr(orq, "localizar", lambda: None)
    tarea_id = _detenida()
    with orq.editar(tarea_id) as t:
        t["paso"], t["pasos"] = 4, 6

    r = orq.reanudar(tarea_id, "usa opus en la sesión de alfa")

    t = orq.cargar(tarea_id)
    assert r == {"ok": True, "en_cola": False}
    assert t["estado"] == orq.ACTIVA and t["paso"] == 4 and t["cerrada"] is None
    assert t["despertar"][0].startswith("El dueño REANUDA la tarea " + tarea_id)
    assert "«usa opus en la sesión de alfa»" in t["despertar"][0]
    assert orq.bitacora(tarea_id)[-1]["tipo"] == "reanudada"
    orq.avance("sigo")   # sus manos vuelven a funcionar


def test_reanudada_se_le_dice_a_su_mismo_orquestador_sin_cerrarlo(monkeypatch):
    """Su ventana aún tiene el contexto de esta tarea: tirarlo sería perderlo."""
    entregados: list[str] = []
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq, "cerrar_panel", lambda: pytest.fail("no debía cerrar su ventana"))
    monkeypatch.setattr(orq.entrega, "panel_apto", lambda pane: (True, ""))
    monkeypatch.setattr(orq.entrega, "entregar", lambda pane, texto: entregados.append(texto))
    monkeypatch.setattr(orq, "_interrumpir", lambda pane: False)
    tarea_id = _detenida()

    orq.reanudar(tarea_id)
    orq._despertar(tarea_id)

    assert len(entregados) == 1 and "REANUDA" in entregados[0]


def test_con_otra_en_curso_la_reanudada_vuelve_a_la_cola_y_arranca_con_contexto_limpio(
        escena, monkeypatch):
    abiertos: list[str] = []
    cerrados: list[bool] = []
    monkeypatch.setattr(orq, "localizar", lambda: None)
    monkeypatch.setattr(orq, "cerrar_panel", lambda: cerrados.append(True))
    monkeypatch.setattr(orq, "abrir_panel", lambda texto: abiertos.append(texto) or "%9")
    vieja = _detenida()
    otra = _activa("otra cosa")

    assert orq.reanudar(vieja, "sigue")["en_cola"] is True
    assert orq.cargar(vieja)["estado"] == orq.EN_COLA
    orq.bombear(escena)
    assert abiertos == []          # la otra sigue en curso

    with orq.editar(otra) as t:
        t["estado"] = orq.TERMINADA
    orq.bombear(escena)

    assert orq.cargar(vieja)["estado"] == orq.ACTIVA
    assert cerrados and "REANUDA" in abiertos[0] and "«sigue»" in abiertos[0]


def test_solo_se_reanuda_lo_detenido():
    tarea_id = _activa()

    with pytest.raises(ValueError, match="no está detenida"):
        orq.reanudar(tarea_id)


def test_reanudar_desde_la_pantalla(cliente, escena, monkeypatch):
    monkeypatch.setattr(orq, "localizar", lambda: None)
    tarea_id = _detenida()

    pagina = cliente.get(f"/orquestador?tarea={tarea_id}").text
    assert 'action="/orquestador/reanudar"' in pagina

    r = cliente.post("/orquestador/reanudar", data={"tarea_id": tarea_id, "nota": "ya vi lo que hacía"},
                     follow_redirects=False)

    assert r.status_code == 303
    assert orq.cargar(tarea_id)["estado"] == orq.ACTIVA


# ─────────────────── modelo, esfuerzo y contexto de las sesiones ────────────


def test_el_orquestador_y_sus_sesiones_compactan_al_70():
    """Una sesión llegó al 96 % sin compactar en siete horas (267)."""
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70" in orq.comando_de_arranque("Tarea nueva: t-1").completa()
    assert modelos.entorno_de_sesion() == {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "70"}


@pytest.fixture
def abriendo(escena, monkeypatch):
    from hub import agentes, entrevistador, slots
    creados: list[str] = []
    monkeypatch.setattr(orq, "sesiones", lambda con, p: [])
    monkeypatch.setattr(agentes, "confiar", lambda ruta: None)
    monkeypatch.setattr(slots, "crear", lambda con, p, n, **kw: creados.append(kw["comando"]) or 1)
    monkeypatch.setattr(slots, "abrir", lambda con, sid, **kw: "%7")
    monkeypatch.setattr(entrevistador, "comprobar_arranque", lambda pane: None)
    monkeypatch.setattr(orq.tui, "listo", lambda agente, pane: True)
    orq.fijar_nivel("alfa", "alto")
    _activa()
    return creados


def test_abrir_por_omision_es_opus_con_esfuerzo_alto_y_compactando_al_70(escena, abriendo):
    orq.abrir_sesion(escena, "alfa")

    assert abriendo[0].startswith("env CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70 claude ")
    assert "--model claude-opus-5-5" in abriendo[0] and "--effort high" in abriendo[0]


def test_abrir_acepta_el_alias_pero_lanza_el_id_exacto(escena, abriendo):
    """Decisión 91: el alias nunca llega a `claude`."""
    orq.abrir_sesion(escena, "alfa", modelo="sonnet", esfuerzo="low")

    assert "--model claude-sonnet-5 " in abriendo[0] and "--effort low" in abriendo[0]


def test_abrir_no_pasa_del_techo_de_modelos_ni_inventa_esfuerzos(escena, abriendo):
    with pytest.raises(ValueError, match="fuera de la política"):
        orq.abrir_sesion(escena, "alfa", modelo="fable")
    with pytest.raises(ValueError, match="esfuerzo"):
        orq.abrir_sesion(escena, "alfa", esfuerzo="ultra")
    assert abriendo == []


@pytest.fixture
def ajustando(escena, sesion_libre, monkeypatch):
    """`%5` con Claude como proceso raíz, en Sonnet y quieto."""
    fichas = [{"pid": 100, "session_id": "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0", "cwd": "/tmp/alfa", "estado": "idle",
               "modelo": "claude-sonnet-5", "esfuerzo": None,
               "permisos": "bypassPermissions", "compacta_al": None, "contexto": 900_000}]
    relanzados: list[tuple] = []
    monkeypatch.setattr(orq, "ficha", lambda pane: fichas[0] if len(relanzados) == 0
                        else {**fichas[0], "pid": 200, "modelo": "x"})
    monkeypatch.setattr(orq.tmux, "relanzar_panel",
                        lambda pane, ruta, comando, entorno: relanzados.append((pane, ruta, comando, entorno)))
    monkeypatch.setattr(orq.tui, "listo", lambda agente, pane: True)
    orq.fijar_nivel("alfa", "alto")
    _activa()
    return fichas, relanzados


def test_ajustar_relanza_la_misma_conversacion_en_el_mismo_panel(escena, sesion_libre, ajustando):
    """🔴 Sin `/model` ni `/effort`: los dos guardan el valor como predeterminado
    del dueño en su settings.json (medido el 16-oct, decisión 268)."""
    _, relanzados = ajustando

    r = orq.ajustar(escena, "alfa", "%5", modelo="opus", esfuerzo="xhigh")

    pane, ruta, comando, entorno = relanzados[0]
    assert (pane, ruta) == ("%5", "/tmp/alfa")
    # Orden de la puerta única (340): las banderas de `claude` no dependen del orden.
    assert comando == ("claude --model claude-opus-5-5 --effort xhigh "
                       "--permission-mode bypassPermissions --resume 0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0")
    assert entorno["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "70" and "PATH" in entorno
    assert sesion_libre == []      # no se escribió nada en su cuadro
    assert "claude-opus-5-5/xhigh" in r["cambio"]
    assert orq.bitacora(orq.viva()["id"])[-1]["tipo"] == "ajustada"


def test_ajustar_no_relanza_si_hay_trabajo_en_segundo_plano_sin_forzar(escena, sesion_libre, ajustando, monkeypatch):
    fichas, relanzados = ajustando
    fichas[0]["estado"] = "shell"
    monkeypatch.setattr(orq, "_procesos_hijos", lambda pid: ["bash -c entrenar.py"])

    with pytest.raises(ValueError, match="entrenar.py"):
        orq.ajustar(escena, "alfa", "%5", modelo="opus")
    assert relanzados == []

    orq.ajustar(escena, "alfa", "%5", modelo="opus", forzar=True)
    assert len(relanzados) == 1


def test_ajustar_no_toca_un_panel_que_no_arranco_claude_directamente(escena, sesion_libre, ajustando):
    """Debajo podría haber una shell del dueño, y relanzar se la llevaría."""
    fichas, relanzados = ajustando
    fichas[0]["pid"] = None

    with pytest.raises(ValueError, match="directamente"):
        orq.ajustar(escena, "alfa", "%5", modelo="opus")
    assert relanzados == []


def test_ajustar_solo_en_sesiones_del_proyecto(escena, sesion_libre, ajustando):
    with pytest.raises(ValueError, match="no es una sesión viva"):
        orq.ajustar(escena, "alfa", "%99", modelo="opus")


def test_compactar_escribe_compact_y_espera_a_que_quede_libre(escena, sesion_libre):
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()

    orq.compactar(escena, "alfa", "%5", "lo de la etapa 2")

    assert sesion_libre == [("%5", "/compact lo de la etapa 2")]
    espera = orq.cargar(tarea_id)["esperas"][-1]
    assert espera["tipo"] == "libre" and espera["pane_id"] == "%5"


def test_el_contexto_se_mide_del_ultimo_turno_del_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", tmp_path)
    d = tmp_path / transcripts.slug_de("/tmp/alfa")
    d.mkdir()
    lineas = [
        {"type": "assistant", "message": {"usage": {"input_tokens": 5, "cache_read_input_tokens": 100}}},
        {"type": "user", "message": {"content": "hola"}},
        {"type": "assistant", "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": 900_000,
                                                    "cache_creation_input_tokens": 56_000}}},
        {"type": "system", "subtype": "x"},
    ]
    (d / "s-1.jsonl").write_text("\n".join(json.dumps(l) for l in lineas))

    assert orq._contexto("/tmp/alfa", "s-1") == 956_002
    assert orq._contexto("/tmp/alfa", "otra") is None


def test_tras_compactar_el_contexto_es_lo_que_quedo_y_no_el_ultimo_turno(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", tmp_path)
    d = tmp_path / transcripts.slug_de("/tmp/alfa")
    d.mkdir()
    lineas = [
        {"type": "assistant", "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": 956_000}}},
        {"type": "system", "subtype": "compact_boundary",
         "compactMetadata": {"preTokens": 957_469, "postTokens": 18_897}},
        {"type": "user", "isCompactSummary": True, "message": {"content": "resumen"}},
    ]
    (d / "s-1.jsonl").write_text("\n".join(json.dumps(l) for l in lineas))

    assert orq._contexto("/tmp/alfa", "s-1") == 18_897


# ─────────── lo que Claude Code dice de sí mismo (decisión 270) ─────────────


def test_si_no_avanza_tras_el_aviso_se_le_vuelve_a_despertar_y_a_la_tercera_al_dueno(monkeypatch):
    """16-oct: contestó al aviso «esta vez sí me avisará» sin nada abierto, y
    como avisaba una vez por silencio, se quedó tres horas parada."""
    tarea_id = _activa()
    (orq.dir_de(tarea_id) / "bitacora.jsonl").write_text(
        json.dumps({"cuando": _hace(3 * 3600), "tipo": "respuesta", "texto": "x"}) + "\n")
    monkeypatch.setattr(orq, "localizar", lambda: "%1")
    monkeypatch.setattr(orq, "_ocupada", lambda agente, pane: (False, False))
    timbres: list[str] = []
    monkeypatch.setattr(orq, "timbre", timbres.append)

    for vez in range(3):
        with orq.editar(tarea_id) as t:
            orq._vigilar_quieta(t)
            assert len(t["despertar"]) == 1, vez
            t["despertar"] = []                    # se le entregó y no hizo nada
            t["vigia_en"] = _hace(orq.MINUTOS_SIN_NADA * 60 + 5)

    assert timbres == [f"La tarea {tarea_id} lleva 180 min sin avanzar."]


def test_con_trabajo_de_fondo_la_respuesta_no_se_da_por_acabada(mirando, monkeypatch):
    """Medido: el turno acabó, la pantalla dice libre y Claude dice `shell`
    mientras su `sleep 40` sigue. Leerla ahí es leer una respuesta a medias."""
    monkeypatch.setattr(orq, "estado_claude", lambda pane: "shell")
    tarea_id = _con_espera(enviado_hace=600)

    t = _revisar(tarea_id)

    assert t["esperas"][0]["estado"] == "esperando" and t["despertar"] == []
    monkeypatch.setattr(orq, "estado_claude", lambda pane: "idle")
    assert _revisar(tarea_id)["esperas"][0]["estado"] == "terminada"


def test_busy_cuenta_como_trabajando_aunque_aun_no_se_vea_el_spinner(mirando, monkeypatch):
    monkeypatch.setattr(orq, "estado_claude", lambda pane: "busy")
    tarea_id = _con_espera(enviado_hace=orq.QUIETA_TRAS + 5)

    t = _revisar(tarea_id)

    assert t["esperas"][0]["estado"] == "esperando" and t["esperas"][0]["visto_trabajando"]


def test_mandar_no_pega_encima_de_una_sesion_que_sigue_con_lo_suyo(escena, sesion_libre, monkeypatch):
    """Lo pegado quedaba «en cola» y salía cuando ella quisiera."""
    monkeypatch.setattr(orq, "estado_claude", lambda pane: "shell")
    monkeypatch.setattr(orq.tmux, "capturar_panel", lambda pane: "")
    orq.fijar_nivel("alfa", "alto")
    tarea_id = _activa()

    r = orq.mandar(escena, "alfa", "%5", "sigue")

    assert r["enviado"] is False and sesion_libre == []
    assert orq.cargar(tarea_id)["esperas"][-1]["tipo"] == "libre"


def test_el_estado_se_lee_del_archivo_de_su_panel_y_solo_si_esta_vivo(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(orq, "_sesiones_de_claude", lambda: tmp_path)
    monkeypatch.setattr(orq.tmux, "pid_del_panel", lambda pane: 1)   # una shell debajo
    vivo, muerto = os.getpid(), 999_999_999
    (tmp_path / f"{muerto}.json").write_text(json.dumps(
        {"pid": muerto, "status": "busy", "tmux": "s:@1.%5"}))
    assert orq.estado_claude("%5") is None          # de una sesión que ya murió

    (tmp_path / f"{vivo}.json").write_text(json.dumps(
        {"pid": vivo, "status": "shell", "tmux": "s:@1.%5"}))
    assert orq.estado_claude("%5") == "shell"
    assert orq.estado_claude("%55") is None         # no casa por prefijo


@pytest.mark.parametrize("cambio,motivo", [
    ({"permisos": "inventado"}, "modo de permisos que el hub no conoce"),
    ({"session_id": "no-es-uuid"}, "qué conversación retomar"),
])
def test_ajustar_no_relanza_lo_que_no_cabe_en_la_linea_y_lo_dice(escena, sesion_libre, ajustando, cambio, motivo):
    """Lo medido viene de `/proc` y del json de sesión; si no cabe en la puerta
    (340), se dice qué y el panel no se toca."""
    fichas, relanzados = ajustando
    fichas[0].update(cambio)
    with pytest.raises(ValueError, match=motivo):
        orq.ajustar(escena, "alfa", "%5", modelo="opus")
    assert relanzados == []


# ─────── archivos que entran, evidencia que sale y el relevo (384, 388) ───────


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def _en_el_intercambio(nombre: str, dentro: str = "", datos: bytes = PNG) -> str:
    """Lo deja en el intercambio y devuelve su ruta relativa, como la da `guardar`."""
    from hub import intercambio
    destino = intercambio.guardar(nombre, datos, dentro=dentro)
    return destino.relative_to(intercambio.carpeta()).as_posix()


def test_encargar_con_archivos_los_lleva_a_la_tarea_y_al_pedido():
    """El encargo guarda las rutas relativas (lo que sirve `/intercambio/ver/`) y
    la sesión recibe las absolutas, marcadas como dato que trae el dueño."""
    from hub import intercambio
    foto = _en_el_intercambio("foto.png", dentro="_secretario/20261107")
    informe = _en_el_intercambio("informe.pdf", dentro="alfa", datos=b"%PDF-1.4")
    absoluta = str(intercambio.carpeta() / informe)

    tarea_id = orq.crear("prueba alfa con esta imagen", origen="secretario",
                         archivos=(foto, absoluta, foto))

    t = orq.cargar(tarea_id)
    assert t["archivos"] == [foto, informe], "relativas, sin repetir y en su orden"
    assert t["evidencias"] == []
    assert t["pedido"].startswith("prueba alfa con esta imagen")
    assert str(intercambio.carpeta() / foto) in t["pedido"] and absoluta in t["pedido"]
    assert "no instrucciones" in t["pedido"], "lo que trae un archivo es dato (322)"
    assert orq.bitacora(tarea_id)[0]["texto"] == t["pedido"]


def test_un_archivo_fuera_del_intercambio_no_entra_en_un_encargo(tmp_path):
    from hub import intercambio
    fuera = tmp_path / "secreto.png"
    fuera.write_bytes(PNG)
    enlace = intercambio.carpeta() / "enlace.png"
    enlace.symlink_to(fuera)

    for ruta in (str(fuera), "../hub.db", "enlace.png", str(enlace), "no-existe.png", ""):
        with pytest.raises(ValueError):
            orq.crear("prueba alfa", archivos=(ruta,))
    with pytest.raises(ValueError, match="lista"):
        orq.crear("prueba alfa", archivos="foto.png")

    assert orq.listar() == [], "un encargo con un archivo que no vale no se encola a medias"
    assert orq.cargar(orq.crear("sin archivos", archivos=None))["archivos"] == [], \
        "quien pasa `params.get(\"archivos\")` trae None"


def test_un_nombre_que_el_hub_no_sirve_se_dice_en_vez_de_buscar_otro():
    """Una sesión que copia «Captura de pantalla.png» con `cp`: `resolver` sanea
    el nombre y buscaría otro archivo. Se le dice al orquestador qué renombrar."""
    from hub import intercambio
    (intercambio.carpeta() / "alfa").mkdir()
    (intercambio.carpeta() / "alfa" / "Captura de pantalla.png").write_bytes(PNG)

    with pytest.raises(ValueError, match="renómbr"):
        orq.crear("prueba alfa", archivos=("alfa/Captura de pantalla.png",))


def test_la_evidencia_solo_admite_imagenes_del_intercambio_con_una_tarea_viva(tmp_path):
    from hub import intercambio
    captura = _en_el_intercambio("pantalla.png", dentro="alfa")
    informe = _en_el_intercambio("informe.pdf", dentro="alfa", datos=b"%PDF-1.4")
    dibujo = _en_el_intercambio("dibujo.svg", dentro="alfa", datos=b"<svg/>")
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(PNG)

    with pytest.raises(orq.TareaCerrada):
        orq.evidencia(captura)

    tarea_id = _activa()
    for mala in (informe, dibujo, str(fuera), "../fuera.png"):
        with pytest.raises(ValueError):
            orq.evidencia(mala)

    assert orq.evidencia(str(intercambio.carpeta() / captura), "el render de la casa") == captura
    assert orq.evidencia(captura, "el render, otra vez") == captura

    t = orq.cargar(tarea_id)
    assert [(e["ruta"], e["nota"]) for e in t["evidencias"]] == [(captura, "el render, otra vez")]
    assert [b["ruta"] for b in orq.bitacora(tarea_id) if b["tipo"] == "evidencia"] == [captura, captura]

    orq.terminar("hecho")
    with pytest.raises(orq.TareaCerrada):
        orq.evidencia(captura)


def test_el_orquestador_apunta_evidencia_y_la_ve_en_su_tarea(escena, capsys, monkeypatch, tmp_path):
    # Una conexión por orden, como `./orq`: `main` cierra la suya al acabar.
    conectar = db.conectar
    monkeypatch.setattr(orquestador_cli.db, "conectar", lambda ruta: conectar(tmp_path / "hub.db"))
    captura = _en_el_intercambio("pantalla.png", dentro="alfa")
    _activa()

    assert orquestador_cli.main(["evidencia", captura, "se ve la casa"]) == 0
    assert captura in capsys.readouterr().out
    assert orquestador_cli.main(["evidencia", "alfa/nada.png"]) == 1
    assert "no hay" in capsys.readouterr().err

    assert orquestador_cli.main(["tarea"]) == 0
    salida = capsys.readouterr().out
    assert "## Evidencia apuntada" in salida and f"{captura}: se ve la casa" in salida


@pytest.mark.parametrize("texto", [
    "¿firmo el contrato del proveedor para seguir?",
    "hay que aceptar los términos y condiciones del servicio",
    "falta un trámite en el portal de la tienda",
    "¿pago la suscripción del dominio?",
    "¿gasto 20 en créditos de la API?",
    "¿lo publico en su nombre en sus redes?",
    "¿lo publico en sus redes?",
    "¿apuesto 20 a la cuota de 1,5?",
    "deposita 500 en la cuenta nueva",
    "¿retiro las ganancias ya?",
    "¿me suscribo al plan anual?",
    "¿lo despliego a producción?",
])
def test_lo_legal_va_al_dueno_aunque_el_motivo_diga_otra_cosa(texto):
    """La red sólo sube (348, 381): lo que le compromete legalmente o con dinero
    no lo contesta el secretario, aunque el orquestador diga que es una duda."""
    assert orq.toca_al_dueno(texto)
    assert orq.para_quien(texto, "duda") == "dueno"


def test_lo_operativo_no_lo_toma_por_legal():
    for texto in ("¿a cuál de las dos sesiones mando?", "¿lo apunto en el avance o espero al final?",
                  "los tests fallaron dos veces igual, ¿reintento con más contexto?",
                  "lo anotaría en el avance y sigo"):
        assert not orq.toca_al_dueno(texto), texto


def test_la_lista_de_nunca_sin_el_dueno_lleva_lo_legal():
    nunca = " · ".join(orq.SIEMPRE_DEL_DUENO)
    for palabra in ("firmar", "términos", "trámites", "contratos", "publicar en nombre del dueño", "dinero"):
        assert palabra in nunca
    assert all(orq.toca_al_dueno(x) for x in orq.SIEMPRE_DEL_DUENO), "la red reconoce su propia lista"


@pytest.fixture
def pc(monkeypatch):
    """El agente de Windows de Reuniones, simulado en su frontera."""
    estado = {"vivo": True, "falla": None, "abiertas": []}

    def pedir_abrir(ruta):
        if estado["falla"]:
            raise estado["falla"]
        estado["abiertas"].append(ruta)
        return "pid"

    monkeypatch.setattr(orq.reuniones, "agente", lambda: {"vivo": estado["vivo"]})
    monkeypatch.setattr(orq.reuniones, "pedir_abrir", pedir_abrir)
    return estado


def test_una_pregunta_de_relevo_es_del_dueno_y_abre_sus_asuntos_en_la_pc(pc):
    """388: lo que sólo él puede hacer en la PC se le abre en la PC, nunca en el teléfono."""
    tarea_id = _activa()

    assert orq.preguntar("hay un captcha en la pestaña del alta", "relevo") == "dueno"

    assert pc["abiertas"] == ["/secretario?p=pendientes"]
    assert orq.timbres_pendientes() == [], "el relevo no va al teléfono"
    t = orq.cargar(tarea_id)
    assert t["estado"] == orq.ESPERANDO_DUENO and t["pregunta"]["motivo"] == "relevo"
    assert any(b["tipo"] == "relevo" for b in orq.bitacora(tarea_id))


@pytest.mark.parametrize("vivo,falla", [(False, None), (True, OSError("disco lleno"))])
def test_sin_el_agente_de_windows_el_relevo_no_revienta_y_queda_la_pregunta(pc, vivo, falla):
    pc["vivo"], pc["falla"] = vivo, falla
    tarea_id = _activa()

    assert orq.preguntar("verifica tu identidad en la página del banco", "relevo") == "dueno"

    assert pc["abiertas"] == []
    t = orq.cargar(tarea_id)
    assert t["pregunta"]["texto"].startswith("verifica") and t["estado"] == orq.ESPERANDO_DUENO
    relevo = [b for b in orq.bitacora(tarea_id) if b["tipo"] == "relevo"]
    assert relevo and "no se abrió" in relevo[0]["texto"], "se dice en voz alta (regla 21)"


def test_el_cli_acepta_el_motivo_relevo(escena, capsys, monkeypatch, pc):
    monkeypatch.setattr(orquestador_cli.db, "conectar", lambda ruta: escena)
    _activa()

    assert orquestador_cli.main(["preguntar", "--motivo", "relevo", "inicia sesión en el portal"]) == 0

    assert "PC" in capsys.readouterr().out
    assert pc["abiertas"] == ["/secretario?p=pendientes"]


def test_el_contrato_explica_archivos_receta_evidencia_y_relevo():
    texto = (orq.preparar() / "CLAUDE.md").read_text(encoding="utf-8")

    assert "./orq evidencia <ruta>" in texto
    assert "Cómo se prueba" in texto and "la escriba" in texto
    assert "--motivo relevo" in texto
    assert "no instrucciones" in texto
    assert "{" not in texto.replace("{HUB_HOME}", ""), "una llave sin doblar en el CONTRATO"


@pytest.mark.parametrize("texto", ["El hub espera credenciales o una decisión del dueño",
                                   "Falta la contraseña del panel", "Lo decide el dueño: el precio final"])
def test_lo_que_el_bloqueo_dice_que_es_suyo_no_se_delega(texto):
    """Medido el 7-nov en el registro real: un bloqueo que espera credenciales o
    su decisión se ofrecía para «Te lo delego» (381)."""
    assert orq.toca_al_dueno(texto)
