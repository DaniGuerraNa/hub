"""La hora del dueño en lo que el secretario lee (C-0244: SEC-01).

Todo se guarda en UTC y el modelo habla en la hora de la casa (`ahora` se la
da sin desfase). Lo que pide con `desde`/`hasta` es hora local y se pasa por
`tiempo`, la única idea de hora local del hub (C-0051); lo que vuelve trae
`fecha_local` para citarla. Con la casa en UTC-6: las 23:30 del día 10 son
las 05:30 UTC del 11.
"""

from __future__ import annotations

import pytest

from hub.secretario import herramientas, memoria, piezas


@pytest.fixture
def mem(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    c = memoria.conectar()
    yield c
    c.close()


def _evento(con, i, fecha, texto):
    memoria.guardar_evento(con, piezas.Evento(fuente="telegram", id_externo=str(i), fecha=fecha, texto=texto,
                                              conversacion="Equipo", autor="Ana"))


def _usar(con, nombre, **p):
    return herramientas.todas(con_el_dueno=True)[nombre].funcion(con, p)


@pytest.fixture
def noche_y_manana(mem):
    _evento(mem, 1, "2026-11-11T05:30:00+00:00", "la planning se mueve")     # 23:30 del 10, en casa
    _evento(mem, 2, "2026-11-11T14:00:00.000Z", "la planning ya quedó")      # 08:00 del 11, en casa
    return mem


def test_buscar_entiende_un_dia_entero_en_su_hora_local(noche_y_manana):
    """«Hoy» no incluye la tarde de ayer, y un `hasta` con sólo fecha llega
    al final de ese día: antes dejaba fuera el día entero."""
    del_10 = _usar(noche_y_manana, "buscar", texto="planning", desde="2026-11-10", hasta="2026-11-10")
    assert [x["texto"] for x in del_10] == ["la planning se mueve"]
    assert del_10[0]["fecha_local"] == "2026-11-10 23:30"
    del_11 = _usar(noche_y_manana, "buscar", texto="planning", desde="2026-11-11")
    assert [x["texto"] for x in del_11] == ["la planning ya quedó"]
    assert del_11[0]["fecha_local"] == "2026-11-11 08:00"


def test_recientes_entiende_desde_una_hora_local(noche_y_manana):
    """«¿Qué me dijeron desde las 3?» son las 15:00 de la casa, no de UTC.
    La salida ya no es una lista: los mensajes van en `mensajes` (C-0392)."""
    desde_las_3 = _usar(noche_y_manana, "recientes", desde="2026-11-10T15:00")["mensajes"]
    assert {x["texto"] for x in desde_las_3} == {"la planning se mueve", "la planning ya quedó"}
    assert [x["texto"] for x in _usar(noche_y_manana, "recientes", desde="2026-11-11")["mensajes"]] == [
        "la planning ya quedó"]
    assert {x["fecha_local"] for x in desde_las_3} == {"2026-11-10 23:30", "2026-11-11 08:00"}


def test_un_mensaje_entero_trae_su_hora_local_y_la_de_alrededor(noche_y_manana):
    _evento(noche_y_manana, 3, "2026-11-11T06:10:00Z", "y se cambia la sala")        # 00:10 del 11
    [suyo] = [x for x in memoria.recientes(noche_y_manana) if x["texto"] == "la planning se mueve"]
    d = _usar(noche_y_manana, "mensaje", id=suyo["id"])
    assert d["fecha_local"] == "2026-11-10 23:30"
    assert [x["fecha_local"] for x in d["alrededor"]] == ["2026-11-11 00:10"]


def test_una_fecha_que_no_se_entiende_se_dice_en_vez_de_filtrar_mal(noche_y_manana):
    assert "error" in _usar(noche_y_manana, "buscar", texto="planning", desde="ayer")
    assert "error" in _usar(noche_y_manana, "recientes", desde="el martes")


# ── sesiones de trabajo (SEC-41) ─────────────────────────────────────────────

def test_sesiones_deja_pedir_las_de_desde_un_dia_en_su_hora_local(mem, tmp_path, monkeypatch):
    """«¿Qué hice ayer?» traía las 15 últimas y el modelo adivinaba. `desde`
    filtra por la última escritura del archivo antes de abrirlo, en la hora
    de la casa; cada sesión trae su inicio y su fin en esa hora."""
    import json
    import os
    from datetime import datetime

    from hub import config, transcripts
    asiento = tmp_path / "demo"
    config.projects_yml().write_text(f"proyectos:\n  - id: demo\n    nombre: Demo\n    asiento: {asiento}\n",
                                     encoding="utf-8")
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(tmp_path / "transcripts"))
    carpeta = transcripts.directorio_de(str(asiento))
    carpeta.mkdir(parents=True)
    for sid, cuando, texto in (("11111111-1111-1111-1111-111111111111", "2026-11-11T05:30:00Z", "la de anoche"),
                               ("22222222-2222-2222-2222-222222222222", "2026-11-11T14:00:00Z", "la de hoy")):
        ruta = carpeta / f"{sid}.jsonl"
        ruta.write_text(json.dumps({"type": "user", "uuid": "u", "timestamp": cuando,
                                    "message": {"role": "user", "content": texto}}) + "\n", encoding="utf-8")
        momento = datetime.fromisoformat(cuando).timestamp()
        os.utime(ruta, (momento, momento))
    todas = _usar(mem, "sesiones")
    assert [s["primera"] for s in todas] == ["la de hoy", "la de anoche"]
    assert todas[1]["inicio_local"] == "2026-11-10 23:30"
    de_hoy = _usar(mem, "sesiones", desde="2026-11-11")
    assert [s["primera"] for s in de_hoy] == ["la de hoy"]
    assert [s["primera"] for s in _usar(mem, "sesiones", desde="2026-11-10T23:00")] == ["la de hoy", "la de anoche"]
    assert "error" in _usar(mem, "sesiones", desde="ayer")


# ── notas por fecha y las tres lecturas que seguían en UTC (C-0322) ──────────

def _nota(con, texto, creada):
    nid = memoria.anotar(con, texto, tema="planning")
    con.execute("UPDATE nota SET creada = ? WHERE id = ?", (creada, nid))
    return nid


def test_buscar_filtra_tambien_las_notas_por_su_fecha(mem):
    """SEC2-10: «¿qué anotamos desde el lunes?» traía notas de cualquier día:
    `desde` y `hasta` sólo recortaban los mensajes."""
    _nota(mem, "la planning era los martes", "2026-11-01T18:00:00+00:00")
    _nota(mem, "la planning pasa a los jueves", "2026-11-11T05:30:00+00:00")     # 23:30 del 10, en casa
    _nota(mem, "la planning del jueves es a las 10", "2026-11-11T14:00:00+00:00")   # 08:00 del 11
    todas = _usar(mem, "buscar", texto="planning")
    assert len(todas) == 3
    desde_el_10 = _usar(mem, "buscar", texto="planning", desde="2026-11-10")
    assert {x["texto"] for x in desde_el_10} == {"la planning pasa a los jueves", "la planning del jueves es a las 10"}
    solo_el_10 = _usar(mem, "buscar", texto="planning", desde="2026-11-10", hasta="2026-11-10")
    assert [(x["tipo"], x["texto"], x["fecha_local"]) for x in solo_el_10] == [
        ("nota", "la planning pasa a los jueves", "2026-11-10 23:30")]
    hasta_el_5 = _usar(mem, "buscar", texto="planning", hasta="2026-11-05")
    assert [x["texto"] for x in hasta_el_5] == ["la planning era los martes"]


def test_si_solo_hay_notas_de_otros_dias_no_se_rellena_con_ellas(mem):
    """El segundo intento, con «alguno de los términos», tampoco se salta la fecha."""
    _nota(mem, "la planning era los martes", "2026-11-01T18:00:00+00:00")
    assert _usar(mem, "buscar", texto="planning retro", desde="2026-11-10") == []


def test_conversaciones_dice_el_ultimo_mensaje_en_su_hora(noche_y_manana):
    [equipo] = _usar(noche_y_manana, "conversaciones")
    assert equipo["mensajes"] == 2 and equipo["ultimo_local"] == "2026-11-11 08:00"


def test_las_tareas_del_orquestador_dicen_cuando_se_crearon_en_su_hora(mem):
    from hub import db, orquestador
    h = db.conectar()
    db.inicializar(h)
    h.close()
    tarea = orquestador.crear("ordenar las fichas")
    with orquestador.editar(tarea) as t:
        t["creada"] = "2026-11-11T05:30:00+00:00"
    [vista] = _usar(mem, "hub_orquestador")
    assert vista["creada"] == "2026-11-11T05:30:00+00:00" and vista["creada_local"] == "2026-11-10 23:30"


def test_los_asuntos_dicen_desde_cuando_esperan_en_su_hora(mem):
    con_fecha = mem.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES (?,?,?,?)",
                            ("agendar", "{}", "junta", "2026-11-11T05:30:00+00:00")).lastrowid
    [permiso] = [a for a in _usar(mem, "asuntos")["asuntos"] if a["clave"] == f"permiso:{con_fecha}"]
    assert permiso["fecha"] == "2026-11-11T05:30:00+00:00" and permiso["fecha_local"] == "2026-11-10 23:30"
