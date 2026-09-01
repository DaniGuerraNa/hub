"""Los endpoints del asistente, servidos de verdad por FastAPI.

🔴 El test que más importa aquí es el que comprueba que **no existe ninguna ruta
de borrado** (regla dura 16). No es una comprobación de cortesía: el trato con
el usuario es que el asistente escribe notas y crea slots dentro del hub, y nada más.
Que aparezca un `DELETE` algún día tiene que romper este archivo.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub import asistente, db, tmux, web
from hub.models import Proyecto


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    ruta = tmp_path / "hub.db"

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)

    asiento = tmp_path / "asistente"
    asiento.mkdir()
    proyectos = [
        Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo"),
        Proyecto(id="asistente", nombre="Asistente", tipo="asistente",
                 asiento=str(asiento)),
    ]
    monkeypatch.setattr(web.registry, "cargar", lambda *a, **k: proyectos)

    con = conexion_de_pruebas()
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    con.execute(
        "INSERT INTO slot (proyecto_id, nombre, ruta, nota, status, creado_en) "
        "VALUES ('demo','facturador','/tmp/demo','', 'activo','2026-08-28')"
    )
    con.execute(
        "INSERT INTO snapshot (tomado_en, server_pid, preservado) VALUES ('2026-08-28', 1, 0)"
    )
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
           VALUES (1,'%7','work',0,0,'/tmp/demo','t','claude','facturador','demo',1)"""
    )
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
           VALUES (1,'%8','work',1,0,'/tmp/demo','t','bash','suelto','demo',NULL)"""
    )
    con.commit()
    con.close()
    return TestClient(web.app)


@pytest.fixture
def tmux_falso(monkeypatch):
    estado = {
        "paneles": [{"session": "asistente", "pane_id": "%9", "comando": "claude",
                     "window_idx": 0, "pane_idx": 0, "cwd": "/tmp", "titulo": "✳",
                     "activo": True}],
        "titulos": {"%9": "✳ listo"},
        "pegado": [],
        "enfocado": "%7",
        "cuadro": {"%9": ""},
    }
    regla = "─" * 40
    monkeypatch.setattr(tmux, "listar_paneles", lambda incluir_espejos=False: estado["paneles"])
    monkeypatch.setattr(tmux, "titulo_panel", lambda p: estado["titulos"].get(p))
    monkeypatch.setattr(tmux, "panel_enfocado", lambda excluir=None: estado["enfocado"])
    monkeypatch.setattr(tmux, "capturar_panel",
                        lambda p: f"x\n{regla}\n❯ {estado['cuadro'].get(p, '')}\n{regla}\ny")

    def pegar(pane_id, texto, enter=True):
        estado["pegado"].append((pane_id, texto))
        estado["cuadro"][pane_id] = texto

    monkeypatch.setattr(tmux, "pegar_en_panel", pegar)
    monkeypatch.setattr(tmux, "enter_en_panel", lambda p: estado["cuadro"].update({p: ""}))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)
    return estado


# --------------------------------------------------------------------------- #
# 🔴 El trato: qué puede escribir
# --------------------------------------------------------------------------- #


def test_no_existe_ninguna_ruta_de_borrado_para_el_asistente(cliente):
    # Regla dura 16. Borrar sigue siendo del usuario (principio 9). Si algún día
    # alguien añade un DELETE aquí, que sea rompiendo este test a propósito.
    rutas = [
        (r.path, sorted(r.methods))
        for r in web.app.routes
        if getattr(r, "path", "").startswith(("/api/asistente", "/api/nota", "/api/slot"))
    ]
    assert rutas, "los endpoints del asistente deberían existir"
    for camino, metodos in rutas:
        assert "DELETE" not in metodos, f"{camino} expone borrado"
    assert not any("borrar" in c or "eliminar" in c for c, _ in rutas)


def test_la_nota_cae_en_el_slot_del_panel_enfocado(cliente, tmux_falso):
    r = cliente.post("/api/nota", json={"texto": "473 commits sin respaldar"}).json()
    assert r["ok"] is True
    # Dice SIEMPRE dónde escribió: el panel enfocado es una inferencia, y una
    # nota que cae en otro sitio sin avisar es una nota perdida.
    assert r["slot"] == "facturador" and r["slot_id"] == 1

    guardada = cliente.get("/api/proyecto/demo").json()
    assert "473 commits" in guardada["slots"][0]["nota"]


def test_una_segunda_nota_se_anexa_en_vez_de_pisar_la_primera(cliente, tmux_falso):
    cliente.post("/api/nota", json={"texto": "primera"})
    r = cliente.post("/api/nota", json={"texto": "segunda"}).json()
    assert r["anexada"] is True

    nota = cliente.get("/api/proyecto/demo").json()["slots"][0]["nota"]
    assert "primera" in nota and "segunda" in nota


def test_sin_slot_se_sugiere_crearlo_en_vez_de_devolver_un_error(cliente, tmux_falso):
    tmux_falso["enfocado"] = "%8"  # el panel suelto, sin slot
    r = cliente.post("/api/nota", json={"texto": "algo"}).json()

    assert r["ok"] is False and r["motivo"] == "sin-slot"
    assert r["sugerencia"]["crear_slot"] == {
        "proyecto_id": "demo", "nombre": "suelto", "ruta": "/tmp/demo",
    }


def test_una_nota_vacia_no_se_guarda(cliente, tmux_falso):
    assert cliente.post("/api/nota", json={"texto": "  "}).json()["ok"] is False


def test_crear_un_slot_en_un_proyecto_que_no_existe_se_rechaza(cliente):
    r = cliente.post("/api/slot", json={"proyecto_id": "fantasma", "nombre": "x"}).json()
    assert r["ok"] is False and "desconocido" in r["error"]


def test_el_asistente_crea_slots_con_nombre(cliente):
    r = cliente.post("/api/slot", json={"proyecto_id": "demo", "nombre": "respaldo",
                                        "ruta": "/tmp/demo"}).json()
    assert r["ok"] is True
    nombres = [s["nombre"] for s in cliente.get("/api/proyecto/demo").json()["slots"]]
    assert "respaldo" in nombres


def test_un_slot_sin_nombre_no_se_crea(cliente):
    # El nombre ES la línea de trabajo: un slot sin él es un panel más.
    assert cliente.post("/api/slot", json={"proyecto_id": "demo", "nombre": " "}).json()["ok"] is False


# --------------------------------------------------------------------------- #
# El chat
# --------------------------------------------------------------------------- #


def test_la_conversacion_se_sirve_aunque_el_asistente_no_este_abierto(cliente, monkeypatch):
    monkeypatch.setattr(tmux, "listar_paneles", lambda incluir_espejos=False: [])
    r = cliente.get("/api/asistente").json()
    assert r["abierto"] is False and r["mensajes"] == []
    assert r["ocupado"] is None


def test_enviar_sin_asistente_abierto_contesta_el_porque(cliente, monkeypatch):
    monkeypatch.setattr(tmux, "listar_paneles", lambda incluir_espejos=False: [])
    r = cliente.post("/api/asistente/enviar", json={"texto": "hola"}).json()
    assert r["ok"] is False and "no está abierto" in r["error"]


def test_enviar_llega_al_panel_del_asistente(cliente, tmux_falso):
    assert cliente.post("/api/asistente/enviar", json={"texto": "hola"}).json()["ok"] is True
    assert tmux_falso["pegado"] == [("%9", "hola")]


def test_limpiar_manda_la_barra_clear(cliente, tmux_falso):
    assert cliente.post("/api/asistente/limpiar").json()["ok"] is True
    assert tmux_falso["pegado"] == [("%9", "/clear")]


# --------------------------------------------------------------------------- #
# El compactado en dos tiempos
# --------------------------------------------------------------------------- #


def test_compactar_primero_pide_las_instrucciones_al_propio_asistente(cliente, tmux_falso):
    r = cliente.post("/api/asistente/compactar", json={}).json()
    assert r == {"ok": True, "paso": "preparar"}
    assert tmux_falso["pegado"][0][1].startswith(asistente.PREFIJO_INTERNO)


def test_compactar_espera_si_el_asistente_aun_no_ha_contestado(cliente, tmux_falso,
                                                               monkeypatch):
    monkeypatch.setattr(asistente, "transcript_vivo", lambda p: None)
    r = cliente.post("/api/asistente/compactar", json={"paso": "ejecutar"}).json()
    assert r == {"ok": False, "esperando": True}
    assert tmux_falso["pegado"] == []


def test_compactar_ejecuta_con_lo_que_el_asistente_escribio(cliente, tmux_falso,
                                                            tmp_path, monkeypatch):
    transcript = tmp_path / "aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    transcript.write_text("\n".join(json.dumps(l) for l in [
        {"type": "user", "uuid": "u1", "timestamp": "2026-08-28T10:00:00Z",
         "message": {"content": asistente.PETICION_DE_COMPACTADO}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-08-28T10:01:00Z",
         "message": {"content": [{"type": "text", "text": "Conserva las decisiones."}]}},
    ]), encoding="utf-8")
    monkeypatch.setattr(asistente, "transcript_vivo", lambda p: transcript)

    r = cliente.post("/api/asistente/compactar", json={"paso": "ejecutar"}).json()
    assert r == {"ok": True, "paso": "ejecutar"}
    assert tmux_falso["pegado"] == [("%9", "/compact Conserva las decisiones.")]
    # El prompt generado es para uso interno: no vuelve al chat.
    assert "Conserva las decisiones" not in json.dumps(r)


def test_el_mensaje_interno_no_aparece_en_la_conversacion(cliente, tmux_falso,
                                                          tmp_path, monkeypatch):
    transcript = tmp_path / "bbbbbbbb-1111-2222-3333-444444444444.jsonl"
    transcript.write_text("\n".join(json.dumps(l) for l in [
        {"type": "user", "uuid": "u0", "timestamp": "2026-08-28T09:00:00Z",
         "message": {"content": "qué se hizo ayer"}},
        {"type": "user", "uuid": "u1", "timestamp": "2026-08-28T10:00:00Z",
         "message": {"content": asistente.PETICION_DE_COMPACTADO}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-08-28T10:01:00Z",
         "message": {"content": [{"type": "text", "text": "instrucciones internas"}]}},
    ]), encoding="utf-8")
    monkeypatch.setattr(asistente, "transcript_vivo", lambda p: transcript)

    r = cliente.get("/api/asistente").json()
    assert [m["uuid"] for m in r["mensajes"]] == ["u0"]


# --------------------------------------------------------------------------- #
# Sesiones
# --------------------------------------------------------------------------- #


def test_un_id_de_sesion_que_no_es_un_id_no_llega_a_leer_ningun_archivo(cliente):
    # El id sale de la URL y se convierte en un nombre de archivo. Sin validarlo,
    # este endpoint de lectura pasa a ser lectura libre del disco.
    for veneno in ["..", "....", "-etc-passwd", "sesion.jsonl", "a" * 200]:
        respuesta = cliente.get(f"/api/sesion/{veneno}")
        assert respuesta.status_code in (200, 404)
        if respuesta.status_code == 200:
            assert respuesta.json()["ok"] is False


def test_el_indice_de_sesiones_responde_aunque_no_haya_ninguna(cliente):
    assert cliente.get("/api/sesiones").json() == {"sesiones": []}
