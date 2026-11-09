"""Lo que espera del dueño: sus asuntos (C-0201, decisiones 379 y 380).

Se leen en vivo de cada dueño —las solicitudes, el orquestador, los avisos
del hub, el canal, las fichas, el estado de cada proyecto, sus compromisos—
y la tabla `asunto` sólo guarda lo que nace aquí y lo que él hizo con cada
uno. Ninguno sale al teléfono: esperan en su pantalla.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

from hub import avisos as avisos_hub, base, config, db, orquestador as orq, timbre
from hub.secretario import (__main__ as cli, asuntos, avisos, herramientas, memoria, piezas, resumen,
                            servicio, tiempo)


@pytest.fixture
def con(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    h = db.conectar()   # la del hub ya existe donde corre el secretario: aquí se crea
    db.inicializar(h)
    h.close()
    c = memoria.conectar()
    yield c
    c.close()


def _solicitud(con) -> int:
    return con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', ?, ?)",
                       ("para el informe", memoria.ahora())).lastrowid


def _pregunta_del_orquestador(texto: str = "¿Borro los temporales o los dejo?") -> str:
    tarea = orq.crear("revisa los logs de anoche")
    with orq.editar(tarea) as t:
        t["estado"] = orq.ACTIVA
    orq.preguntar(texto)
    return tarea


def _proyecto_con_estado(tmp_path, bloqueos: list[str], pid: str = "tienda") -> "os.PathLike":
    carpeta = tmp_path / pid
    carpeta.mkdir(exist_ok=True)
    estado = carpeta / "ESTADO.md"
    estado.write_text("# Estado\n\n## Estado actual\nEn marcha.\n\n## Bloqueado por\n"
                      + "".join(f"- {b}\n" for b in bloqueos), encoding="utf-8")
    config.projects_yml().write_text(
        f"proyectos:\n  - id: {pid}\n    nombre: La tienda\n    asiento: {carpeta}\n    estado_ref: ESTADO.md\n",
        encoding="utf-8")
    return estado


def _reescribir(ruta, texto: str) -> None:
    """Con otra fecha: dos escrituras en el mismo instante no se distinguen."""
    antes = ruta.stat().st_mtime_ns
    ruta.write_text(texto, encoding="utf-8")
    os.utime(ruta, ns=(antes + 2_000_000_000, antes + 2_000_000_000))


def _de(r: asuntos.Reunidos, clase: str) -> list[asuntos.Asunto]:
    return [a for a in r.asuntos if a.clase == clase]


# ── los mínimos del diseño ───────────────────────────────────────────────────

def test_los_asuntos_juntan_lo_que_espera_de_el_sin_copiarlo(con, tmp_path):
    sid = _solicitud(con)
    tarea = _pregunta_del_orquestador()
    h = db.conectar()
    try:
        avisos_hub.anotar(h, "%5", "preguntando", memoria.ahora())
        avisos_hub.marcar_avisado(h, "%5")
        h.execute("INSERT INTO proyecto (id, nombre) VALUES ('web', 'Web')")
        h.execute("INSERT INTO canal_pregunta (proyecto_id, texto, estado, creada_en) VALUES"
                  " ('web', '¿Subo hoy la versión?', 'pendiente', ?)", (memoria.ahora(),))
        h.commit()
    finally:
        h.close()
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    memoria.comprometer(con, "Lo de Luis", quien="Luis", vence="2020-01-01T15:00:00+00:00")
    _proyecto_con_estado(tmp_path, ["Falta que elijas el dominio"])
    propio = asuntos.preguntar(con, "¿Publico el catálogo nuevo?", clase="proyecto", origen="tienda")

    r = asuntos.reunir(con)

    assert not r.fallos
    assert [a.clase for a in r.asuntos] == ["permiso", "orquestador", "sesion", "canal", "bloqueo", "vence",
                                            "proyecto"]
    permiso, pregunta, sesion, canal, bloqueo, vence, del_proyecto = r.asuntos
    assert permiso.clave == f"permiso:{sid}" and permiso.enlace.endswith(f"#solicitud-{sid}")
    assert pregunta.texto == "El orquestador te pregunta: «¿Borro los temporales o los dejo?»"
    assert pregunta.origen == tarea and pregunta.enlace == "/orquestador" and pregunta.solo_el
    assert sesion.origen == "%5" and sesion.enlace == "/trabajo"
    assert "¿Subo hoy la versión?" in canal.texto
    assert bloqueo.texto == "La tienda está bloqueado por: Falta que elijas el dominio"
    assert bloqueo.enlace == "/proyecto/tienda" and not bloqueo.solo_el
    assert vence.texto == "Venció: Mandar el reporte", "el de Luis no es suyo"
    assert del_proyecto.id == propio and del_proyecto.texto == "¿Publico el catálogo nuevo?"
    assert {a.estado for a in r.asuntos} == {"nueva"}
    # 🔴 Lo que se lee en vivo no se copia (380): en la tabla sólo está lo propio.
    assert [tuple(f) for f in con.execute("SELECT clase, propio FROM asunto")] == [("proyecto", 1)]


def test_un_asunto_callado_no_vuelve_aunque_se_recalcule(con):
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    [vence] = asuntos.reunir(con).asuntos
    assert asuntos.marcar(con, vence.clave, "callada") == "callada"
    propio = asuntos.preguntar(con, "¿Renuevo el dominio?", clase="proyecto", clave="dominio")
    asuntos.marcar(con, "proyecto:dominio", "callada")

    for _ in range(3):
        cuenta = asuntos.recalcular(con)
    asuntos.marcar(con, vence.clave, "vista")              # ver la lista no lo descalla
    asuntos.preguntar(con, "¿Renuevo el dominio? (otra vez)", clase="proyecto", clave="dominio")

    assert asuntos.reunir(con).asuntos == []
    assert cuenta["total"] == 0 and cuenta["nuevas"] == 0
    assert asuntos.recalcular(con)["total"] == 0, "preguntarlo otra vez tampoco lo descalla"
    callados = asuntos.reunir(con, todos=True).asuntos
    assert {a.clave: a.estado for a in callados} == {vence.clave: "callada", "proyecto:dominio": "callada"}
    assert [a.id for a in callados if a.clase == "proyecto"] == [propio]
    # Callar es reversible, pero sólo por él, y vuelve como vista: ya lo vio.
    assert asuntos.reabrir(con, vence.clave) == "vista"
    assert [(a.clave, a.estado) for a in asuntos.reunir(con).asuntos] == [(vence.clave, "vista")]


def test_lo_que_solo_el_contesta_no_se_calla_ni_se_da_por_resuelto(con):
    """Un permiso callado seguiría esperando su sí sin que nada lo dijera, y
    el parte diría una cifra distinta de la de Pendientes (regla dura 13)."""
    _solicitud(con)
    _pregunta_del_orquestador()
    i = asuntos.preguntar(con, "Resuelve el captcha en la PC", clase="relevo")
    for a in asuntos.reunir(con).asuntos:
        with pytest.raises(ValueError):
            asuntos.marcar(con, a.clave, "callada")
    permiso, pregunta, relevo = asuntos.reunir(con).asuntos
    for a in (permiso, pregunta):
        with pytest.raises(ValueError):
            asuntos.marcar(con, a.clave, "resuelta")
    assert asuntos.marcar(con, relevo.clave, "resuelta") == "resuelta", "un relevo propio sí: lo hizo"
    assert con.execute("SELECT COUNT(*) FROM asunto WHERE propio = 0").fetchone()[0] == 0
    assert [a.id for a in asuntos.reunir(con, todos=True).asuntos if a.clase == "relevo"] == [i]

def test_cada_asunto_cuenta_como_nuevo_una_sola_vez(con):
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    assert asuntos.recalcular(con)["nuevas"] == 1
    [vence] = asuntos.reunir(con).asuntos
    asuntos.marcar(con, vence.clave, "vista")
    assert asuntos.recalcular(con)["nuevas"] == 0
    assert asuntos.recalcular(con)["total"] == 1, "visto sigue esperando; ya no es nuevo"

    # Si deja de esperar y vuelve, sigue siendo el mismo: no vuelve a ser nuevo.
    [c] = memoria.compromisos(con)
    memoria.cerrar_compromiso(con, c["id"])
    assert asuntos.recalcular(con)["total"] == 0
    memoria.cerrar_compromiso(con, c["id"], "abierto")
    assert asuntos.recalcular(con)["nuevas"] == 0

    # Lo que él decidió no lo deshace ver la lista, y a «nueva» no se vuelve.
    # (La marca de lo decidido la ponen `anotar` y `delegar`; aquí, a mano en la tabla.)
    con.execute("UPDATE asunto SET estado = 'anotada', ref = 'compromiso:9' WHERE clave = ?", (vence.clave,))
    assert asuntos.marcar(con, vence.clave, "vista") == "anotada"
    with pytest.raises(ValueError):
        asuntos.marcar(con, vence.clave, "nueva")

    memoria.comprometer(con, "Llamar al banco", vence="2020-01-02T15:00:00+00:00")
    cuenta = asuntos.recalcular(con)
    assert (cuenta["nuevas"], cuenta["total"], cuenta["por_clase"]) == (1, 2, {"vence": 2})
    assert memoria.leer(con, asuntos.CLAVE_ESTADO)["nuevas"] == 1, "la cuenta queda para la pantalla"


def test_un_bloqueo_que_el_proyecto_quita_desaparece(con, tmp_path):
    estado = _proyecto_con_estado(tmp_path, ["Falta el dominio", "Falta el logo", "nada"])
    r = asuntos.reunir(con)
    assert [a.detalle for a in _de(r, "bloqueo")] == ["Falta el dominio", "Falta el logo"], \
        "«nada» no bloquea"
    dominio = _de(r, "bloqueo")[0].clave
    con.execute("INSERT INTO asunto (clave, clase, estado, ref, creada) VALUES (?, 'bloqueo', 'delegada',"
                " 't-261107-010101', ?)", (dominio, memoria.ahora()))

    _reescribir(estado, "# Estado\n\n## Bloqueado por\n- Falta el dominio\n")
    r = asuntos.reunir(con)
    assert [(a.detalle, a.estado, a.ref) for a in _de(r, "bloqueo")] == \
        [("Falta el dominio", "delegada", "t-261107-010101")], "el que sigue conserva lo que él decidió"

    _reescribir(estado, "# Estado\n\n## Bloqueado por\nNinguno.\n")
    assert _de(asuntos.reunir(con), "bloqueo") == []


def test_un_punto_cortado_en_varias_lineas_es_un_asunto_y_lo_resuelto_no_cuenta(con, tmp_path):
    """Medido con los proyectos de verdad (7-nov): los documentos van cortados
    a ~80 columnas, y partir por línea daba 20 asuntos de 5 proyectos, la
    mitad trozos de frase."""
    estado = _proyecto_con_estado(tmp_path, [])
    estado.write_text(
        "# Estado\n\n## Bloqueado por\n"
        "¿Vale el diseño nuevo del menú? Los botones miden 30 px y la guía\n"
        "de estilo pide 44.\n"
        "- ✅ Resuelto — el color del pie: queda el de siempre.\n"
        "- 🔴 Faltan las fotos de los productos: tres por producto,\n  con fondo blanco.\n",
        encoding="utf-8")
    assert [a.detalle for a in _de(asuntos.reunir(con), "bloqueo")] == [
        "¿Vale el diseño nuevo del menú? Los botones miden 30 px y la guía de estilo pide 44.",
        "🔴 Faltan las fotos de los productos: tres por producto, con fondo blanco."]


def test_lo_callado_de_un_proyecto_no_vuelve_si_cambia_la_cola_de_su_punto(con, tmp_path):
    """El campo llega cortado a 600 caracteres: la cola del último punto se
    mueve sola cuando cambia algo de antes."""
    punto = "Faltan las fotos de los productos para la tienda, tres por producto y con el fondo blanco"
    estado = _proyecto_con_estado(tmp_path, [punto + ". Las pedirá"])
    [b] = _de(asuntos.reunir(con), "bloqueo")
    asuntos.marcar(con, b.clave, "callada")
    _reescribir(estado, f"# Estado\n\n## Bloqueado por\n- {punto}. Las pedirá el orquestador. Pedido también\n")
    assert _de(asuntos.reunir(con), "bloqueo") == []


def test_si_el_estado_dice_mas_de_lo_que_cabe_el_ultimo_bloqueo_lo_avisa(con, tmp_path):
    """`base` da seis líneas del campo: contar seis donde hay ocho sería una
    cifra indefendible (regla dura 13)."""
    _proyecto_con_estado(tmp_path, [f"Falta la pieza {n}" for n in range(1, 9)])
    bloqueos = _de(asuntos.reunir(con), "bloqueo")
    assert len(bloqueos) == 6
    assert bloqueos[-1].texto.endswith("(y puede que más)") and "puede haber más" in bloqueos[-1].detalle
    assert not any("más" in b.texto for b in bloqueos[:-1])
    _proyecto_con_estado(tmp_path, ["Falta la pieza 1", "Falta la pieza 2"])
    assert not any("más" in b.texto for b in _de(asuntos.reunir(con), "bloqueo"))


def test_una_fuente_que_no_se_puede_leer_se_dice_y_el_resto_sale(con, monkeypatch, capsys):
    def roto():
        raise OSError("disco lleno")
    monkeypatch.setattr(orq, "listar", roto)
    config.projects_yml().write_text("proyectos: [esto no es\n", encoding="utf-8")
    _solicitud(con)

    r = asuntos.reunir(con)
    assert [a.clase for a in r.asuntos] == ["permiso"]
    assert r.fallos[0] == "No pude leer el orquestador: disco lleno"
    assert r.fallos[1].startswith("No pude leer tus proyectos:")

    cuenta = asuntos.recalcular(con)
    assert cuenta["total"] == 1 and cuenta["fallos"] == r.fallos
    assert "No pude leer el orquestador: disco lleno" in capsys.readouterr().err, "se dice en voz alta"
    asuntos.recalcular(con)
    assert capsys.readouterr().err == "", "y una vez, no en cada vuelta"


def test_las_sugerencias_nunca_salen_al_telefono(con, monkeypatch, tmp_path):
    _solicitud(con)
    _pregunta_del_orquestador()
    _proyecto_con_estado(tmp_path, ["Falta el dominio"])
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")

    def al_telefono(*a, **k):
        raise AssertionError("una sugerencia salió al teléfono (379)")
    monkeypatch.setattr(avisos, "mandar", al_telefono)
    monkeypatch.setattr(avisos, "intentar", al_telefono)
    monkeypatch.setattr(timbre, "tocar", al_telefono)

    i = asuntos.preguntar(con, "Resuelve el captcha en la PC", clase="relevo", origen="orquestador")
    asuntos.preguntar(con, "¿Precio del envío?", clase="proyecto", origen="tienda")
    asuntos.recalcular(con)
    r = asuntos.reunir(con)
    for a in r.asuntos[:2]:
        asuntos.marcar(con, a.clave, "vista")
    # Un relevo se da por hecho con su botón: quien lo pidió no lee respuestas.
    asuntos.marcar(con, con.execute("SELECT clave FROM asunto WHERE id = ?", (i,)).fetchone()[0], "resuelta")
    acciones = piezas.acciones()
    assert herramientas.usar_accion(con, acciones["callar_asunto"], {"clave": _de(r, "vence")[0].clave})["hecho"]
    assert herramientas.usar_accion(con, acciones["comprometer"],
                                    {"que": "Elegir el dominio", "asunto": _de(r, "bloqueo")[0].clave})["hecho"]
    herramientas.todas()["asuntos"].funcion(con, {})
    assert asuntos.recalcular(con)["total"] == len(r.asuntos) - 2


def test_un_estado_que_no_cambio_no_se_relee(con, tmp_path, monkeypatch):
    estado = _proyecto_con_estado(tmp_path, ["Falta el dominio"])
    leidos = []
    real = base.estado_de

    def contando(p):
        leidos.append(p.id)
        return real(p)
    monkeypatch.setattr(base, "estado_de", contando)

    for _ in range(3):
        asuntos.recalcular(con)
    assert leidos == ["tienda"]
    _reescribir(estado, "# Estado\n\n## Bloqueado por\n- Falta el logo\n")
    assert [a.detalle for a in _de(asuntos.reunir(con), "bloqueo")] == ["Falta el logo"]
    assert leidos == ["tienda", "tienda"]


# ── el parte sale de aquí y no cambia ────────────────────────────────────────

def test_el_parte_cuenta_lo_que_espera_desde_los_asuntos_y_sin_las_sugerencias(con, tmp_path, monkeypatch):
    from hub import api, transcripts
    monkeypatch.setattr(api, "salud", lambda h: [])
    monkeypatch.setattr(transcripts, "listar_sesiones", lambda *a, **k: [])
    _solicitud(con)
    _solicitud(con)
    _proyecto_con_estado(tmp_path, ["Falta el dominio"])
    asuntos.preguntar(con, "Resuelve el captcha en la PC", clase="relevo")
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    asuntos.marcar(con, asuntos.reunir(con, clases=("vence",)).asuntos[0].clave, "callada")

    t = resumen.del_dia(con, noche=True)
    assert t.split("\n")[0] == "Te esperan 2 permisos · 1 vencido", \
        "bloqueos y relevos no van al teléfono; lo vencido sale del día, como antes, aunque se callara"
    assert "dominio" not in t and "captcha" not in t
    assert resumen.del_dia(con).endswith("Esperan tu sí: 2."), "la misma cifra que Pendientes"


def test_si_los_permisos_no_se_pueden_leer_el_resumen_lo_dice(con, monkeypatch):
    def rota(*a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr(piezas, "acciones", rota)
    assert resumen.del_dia(con) == "No pude leer los permisos: disco lleno."

def test_si_la_misma_fuente_falla_en_los_dos_lados_del_parte_es_un_fallo(con, monkeypatch):
    from hub import api, transcripts
    monkeypatch.setattr(api, "salud", lambda h: [])
    monkeypatch.setattr(transcripts, "listar_sesiones", lambda *a, **k: [])

    def roto():
        raise OSError("disco lleno")
    monkeypatch.setattr(orq, "listar", roto)
    t = resumen.del_dia(con, noche=True)
    assert t.split("\n")[0] == "1 fallo"
    assert t.count("No pude leer el orquestador: disco lleno") == 1


# ── las puertas de lo propio ─────────────────────────────────────────────────

def test_solo_nacen_aqui_las_clases_propias_y_con_enlace_del_hub(con):
    with pytest.raises(ValueError):
        asuntos.preguntar(con, "¿Apruebas?", clase="permiso")
    with pytest.raises(ValueError):
        asuntos.preguntar(con, "Mira esto", clase="proyecto", enlace="https://otro.sitio/x")
    with pytest.raises(ValueError):
        asuntos.preguntar(con, "   ", clase="proyecto")
    with pytest.raises(ValueError):
        asuntos.marcar(con, "proyecto:no-existe", "vista")
    with pytest.raises(ValueError):
        asuntos.marcar(con, "inventada:1", "vista")
    assert con.execute("SELECT COUNT(*) FROM asunto").fetchone()[0] == 0


def test_lo_que_dice_un_proyecto_se_contesta_aqui_y_lo_que_se_lee_en_vivo_no(con):
    i = asuntos.preguntar(con, "¿Envío gratis desde 500?", clase="proyecto", origen="tienda",
                          opciones=("sí", "no"), detalle="La clave es token=supersecreto123")
    [a] = asuntos.reunir(con).asuntos
    assert a.opciones == ("sí", "no") and "supersecreto123" not in a.detalle
    f = asuntos.responder(con, i, "sí, desde 500")
    assert (f["estado"], f["respuesta"]) == ("resuelta", "sí, desde 500")
    assert asuntos.reunir(con).asuntos == []
    # La misma pregunta otra vez es otra vez la pregunta: vuelve a esperar.
    assert asuntos.preguntar(con, "¿Envío gratis desde 500?", clase="proyecto", origen="tienda") == i
    assert [(x.estado, x.id) for x in asuntos.reunir(con).asuntos] == [("nueva", i)]

    asuntos.marcar(con, "permiso:7", "vista")
    vivo = con.execute("SELECT id FROM asunto WHERE clave = 'permiso:7'").fetchone()[0]
    with pytest.raises(ValueError):
        asuntos.responder(con, vivo, "sí")


# ── quien la usa: el ciclo, el chat y la terminal ────────────────────────────

def test_la_vuelta_del_ciclo_deja_la_cuenta_al_dia(con, monkeypatch):
    llamadas = []
    monkeypatch.setattr(asuntos, "recalcular", lambda c: llamadas.append(c))
    for paso in ("leer_fuentes", "ejecutar_aprobadas"):
        monkeypatch.setattr(servicio, paso, lambda c: 0)
    from hub import copia_base
    from hub.secretario import consultas, conversacion, disparadores, recordatorios, triaje
    for modulo, nombre in ((triaje, "triar"), (recordatorios, "revisar"), (disparadores, "por_horario"),
                           (disparadores, "por_estado"), (disparadores, "parar_si_acabo"),
                           (disparadores, "por_agenda"), (consultas, "atender"),
                           (conversacion, "cerrar_inactivos"), (copia_base, "hacer")):
        monkeypatch.setattr(modulo, nombre, lambda *a, **k: 0)
    servicio.una_vuelta(con)
    assert llamadas == [con]


def test_la_lectura_asuntos_va_despues_del_orquestador_y_no_marca_nada(con):
    _solicitud(con)
    nombres = [h.nombre for h in herramientas.LECTURAS]
    assert nombres.index("asuntos") == nombres.index("hub_orquestador") + 1
    h = herramientas.todas()["asuntos"]
    assert h.gesto == "compromisos"
    salida = h.funcion(con, {})
    assert [a["clase"] for a in salida["asuntos"]] == ["permiso"] and salida["no_pude_leer"] == []
    json.dumps(salida, ensure_ascii=False)
    assert asuntos.recalcular(con)["nuevas"] == 1, "leerla el modelo no es que él la viera"


def test_anotalo_deja_el_asunto_anotado_y_apuntando_a_su_compromiso(con, tmp_path):
    _proyecto_con_estado(tmp_path, ["Falta el trámite del permiso sanitario"])
    [b] = asuntos.reunir(con).asuntos
    r = herramientas.usar_accion(con, piezas.acciones()["comprometer"],
                                 {"que": "Hacer el trámite del permiso sanitario", "asunto": b.clave})
    assert r["hecho"] and "anotado" in r["resultado"]
    [c] = memoria.compromisos(con)
    assert c["origen"] == f"asunto:{b.clave}"
    [a] = asuntos.reunir(con).asuntos
    assert (a.estado, a.ref) == ("anotada", f"compromiso:{c['id']}")

    for clave in ("nada", "proyecto:no-existe", "bloqueo:tienda:000000000000"):
        malo = herramientas.usar_accion(con, piezas.acciones()["comprometer"], {"que": "Otra", "asunto": clave})
        assert not malo["hecho"], clave
    assert len(memoria.compromisos(con)) == 1, "una clave mala no deja un compromiso suelto"
    # Ya anotado, no se anota otra vez: dos «anótalo» no dejan dos compromisos.
    otra = herramientas.usar_accion(con, piezas.acciones()["comprometer"],
                                    {"que": "Y otra", "asunto": b.clave, "origen": "lo que diga el modelo"})
    assert not otra["hecho"] and "ya está anotado" in otra["error"], otra
    assert len(memoria.compromisos(con)) == 1


def test_callar_un_asunto_es_auto_y_reversible_y_solo_sobre_uno_que_existe(con):
    a = piezas.acciones()["callar_asunto"]
    assert (a.nivel_inicial, a.riesgo) == ("auto", "reversible") and a.gesto in herramientas.GESTOS
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    sid = _solicitud(con)
    # Los ids de solicitudes son correlativos: con el número equivocado, la
    # siguiente nacería callada. Y lo que sólo él contesta no se calla.
    for clave in (f"permiso:{sid + 1}", f"permiso:{sid}", "vence:999:2020-01-01T15:00:00+00:00"):
        assert not herramientas.usar_accion(con, a, {"clave": clave})["hecho"], clave
    assert con.execute("SELECT COUNT(*) FROM asunto").fetchone()[0] == 0
    [vence] = asuntos.reunir(con, clases=("vence",)).asuntos
    r = herramientas.usar_accion(con, a, {"clave": vence.clave})
    assert r["hecho"] and [x.clase for x in asuntos.reunir(con).asuntos] == ["permiso"]

def test_la_orden_asuntos_los_lista_sin_marcarlos(con, capsys, monkeypatch):
    _solicitud(con)
    monkeypatch.setattr(sys, "argv", ["hub.secretario", "asuntos"])
    with pytest.raises(SystemExit) as fin:
        cli.main()
    assert fin.value.code == 0
    salida = capsys.readouterr().out
    assert "[nueva] permiso" in salida and "Pide tu permiso" in salida
    assert asuntos.recalcular(con)["nuevas"] == 1


def test_la_orden_reabrir_devuelve_lo_que_callo(con, capsys, monkeypatch):
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    [vence] = asuntos.reunir(con).asuntos
    asuntos.marcar(con, vence.clave, "callada")
    monkeypatch.setattr(sys, "argv", ["hub.secretario", "asuntos", "reabrir", vence.clave])
    with pytest.raises(SystemExit) as fin:
        cli.main()
    assert fin.value.code == 0
    assert [a.estado for a in asuntos.reunir(con).asuntos] == ["vista"]


def test_lo_que_vence_hoy_es_un_asunto_y_lo_de_pasado_manana_no(con):
    mediodia = datetime(2026, 11, 9, 12, 0, tzinfo=tiempo.ahora_local().tzinfo)
    a_las = lambda d: d.astimezone(timezone.utc).isoformat(timespec="seconds")  # noqa: E731
    memoria.comprometer(con, "Hoy a las tres", vence=a_las(mediodia + timedelta(hours=3)))
    memoria.comprometer(con, "Pasado mañana", vence=a_las(mediodia + timedelta(days=2)))
    [hoy] = asuntos.reunir(con, momento=mediodia).asuntos
    assert hoy.texto == "Para hoy (15:00): Hoy a las tres"
