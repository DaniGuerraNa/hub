"""El secretario le escribe a una sesión de trabajo ya abierta (C-0225, decisión 395).

El dueño le pidió pasarle un trabajo a su Claude Code del slot «Trabajo», para
seguir él en esa sesión con su contexto, y el secretario no tenía cómo. Aquí se
prueba lo que decide el secretario —qué ventana, si puede, qué escribe—; la
escritura en sí es `entrega.entregar`, que tiene sus pruebas con tmux de verdad
(`test_entrega`), y el recorrido entero se probó contra un Claude real.
"""
from __future__ import annotations

import json

import pytest

from hub import db, entrega, orquestador
from hub.secretario import herramientas, memoria, piezas
from hub.secretario.acciones import pc

QUIETA = "✳ Migración de video"


@pytest.fixture
def hub(con, tmp_path, monkeypatch):
    """Un slot «Trabajo» con un Claude y dos `bash` restaurados con su glifo."""
    con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES ('trabajo','Trabajo','/srv/t','ask')")
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, creado_en) VALUES (1, 'trabajo', 'Trabajo', 'x')")
    _muestra(con, {"pane_id": "%55", "comando": "claude", "titulo": QUIETA, "window_idx": 0},
             {"pane_id": "%24", "comando": "bash", "titulo": QUIETA, "window_idx": 5},
             {"pane_id": "%25", "comando": "bash", "titulo": "✳ Otra", "window_idx": 6})
    real = db.conectar
    monkeypatch.setattr(pc.db, "conectar", lambda *a, **k: real(tmp_path / "hub.db"))
    monkeypatch.setattr(herramientas, "_hub", lambda: real(tmp_path / "hub.db"))
    monkeypatch.setattr(orquestador, "viva", lambda: None)
    monkeypatch.setattr(pc.tmux, "servidor_pid", lambda: 1)   # el de la muestra
    return con


def _muestra(con, *paneles):
    con.execute("DELETE FROM snapshot")
    sid = con.execute("INSERT INTO snapshot (tomado_en, server_pid) VALUES ('2026-11-09T23:40:00+00:00', 1)").lastrowid
    for p in paneles:
        fila = {"snapshot_id": sid, "session": "trabajo", "pane_idx": 0, "cwd": "/srv/t", "slot_id": 1, **p}
        con.execute(f"INSERT INTO panel ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})",
                    tuple(fila.values()))


@pytest.fixture
def escrito(monkeypatch):
    hechos = []
    monkeypatch.setattr(entrega, "entregar", lambda pane_id, texto: hechos.append((pane_id, texto)))
    return hechos


def test_le_escribe_a_la_unica_ventana_con_agente_y_no_a_las_shells_restauradas(hub, escrito):
    """Las `bash` llevan el glifo de Claude en el título (tmux-resurrect, 261)."""
    r = pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "Crea el servicio de upload."})
    assert escrito == [("%55", f"{pc.MARCA_SESION}\nCrea el servicio de upload.")]
    assert "%55" in r


def test_la_primera_linea_dice_que_es_del_secretario_por_encargo_del_dueno(hub, escrito):
    pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})
    assert escrito[0][1].splitlines()[0] == "[Del secretario, por encargo del dueño]"


def test_con_dos_ventanas_con_agente_pide_cual_y_no_escribe(hub, escrito):
    _muestra(hub, {"pane_id": "%1", "comando": "claude", "titulo": QUIETA, "window_idx": 1},
             {"pane_id": "%2", "comando": "claude", "titulo": "✳ Otra cosa", "window_idx": 2})
    with pytest.raises(ValueError, match="2 ventanas con agente.*%1.*%2"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})
    assert escrito == []
    pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola", "ventana": "%2"})
    assert escrito[0][0] == "%2"


def test_una_ventana_que_no_es_del_slot_no_se_elige(hub, escrito):
    with pytest.raises(ValueError, match="no es de ese slot"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola", "ventana": "%24"})
    assert escrito == []


def test_con_guardrail_never_no_toca_el_panel(hub, escrito):
    hub.execute("UPDATE proyecto SET guardrail='never' WHERE id='trabajo'")
    with pytest.raises(PermissionError, match="never"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})
    assert escrito == []


def test_si_el_orquestador_espera_a_esa_ventana_no_le_escribe_encima(hub, escrito, monkeypatch):
    monkeypatch.setattr(orquestador, "viva", lambda: {
        "id": "t-1", "esperas": [{"pane_id": "%55", "estado": "esperando"}]})
    with pytest.raises(RuntimeError, match="orquestador espera"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})
    assert escrito == []


def test_con_tmux_reiniciado_desde_el_muestreo_no_escribe(hub, escrito, monkeypatch):
    """Los `%N` se reutilizan: el de la muestra podría ser ya otra sesión."""
    monkeypatch.setattr(pc.tmux, "servidor_pid", lambda: 999)
    with pytest.raises(RuntimeError, match="tmux se reinició"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})
    assert escrito == []


def test_panel_no_apto_dice_el_motivo(hub, monkeypatch):
    def ocupado(pane_id, texto):
        raise entrega.PanelNoApto("está trabajando")
    monkeypatch.setattr(entrega, "entregar", ocupado)
    with pytest.raises(RuntimeError, match="no le escribí a %55: está trabajando"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})


def test_escrito_sin_confirmar_no_se_da_por_hecho(hub, monkeypatch):
    def a_medias(pane_id, texto):
        raise entrega.EscritoSinConfirmar("no salió")
    monkeypatch.setattr(entrega, "entregar", a_medias)
    with pytest.raises(RuntimeError, match="no vi que saliera"):
        pc.EscribirEnSesion().ejecutar(None, {"slot": 1, "texto": "hola"})


def test_pregunta_siempre_aunque_la_pongan_en_auto(monkeypatch, tmp_path):
    """Techo de la 303: un mensaje en un agente es una instrucción y no se deshace."""
    (memoria.carpeta()).mkdir(parents=True, exist_ok=True)
    (memoria.carpeta() / "permisos.yml").write_text("escribir_en_sesion: auto\n", encoding="utf-8")
    assert piezas.nivel(pc.EscribirEnSesion()) == "ask"


def test_la_respuesta_es_lo_que_dijo_la_sesion_tras_el_ultimo_mensaje_suyo(hub, tmp_path, monkeypatch):
    from hub import transcripts
    ruta = tmp_path / "sesion.jsonl"
    lineas = [
        {"type": "user", "uuid": "1", "message": {"content": f"{pc.MARCA_SESION}\nprimero"}},
        {"type": "assistant", "uuid": "2", "message": {"content": [{"type": "text", "text": "vieja"}]}},
        {"type": "user", "uuid": "3", "message": {"content": f"{pc.MARCA_SESION}\nsegundo"}},
        {"type": "assistant", "uuid": "4", "message": {"content": [{"type": "text", "text": "Hecho: el servicio "
                                                                     "usa la clave sk-ant-abc123def456ghi789"}]}},
    ]
    ruta.write_text("\n".join(json.dumps(x) for x in lineas), encoding="utf-8")
    assert transcripts.respuesta_tras(ruta, pc.MARCA_SESION).startswith("Hecho")
    assert transcripts.respuesta_tras(ruta, "otra marca") is None

    hub.execute("UPDATE panel SET claude_sesion='s-1' WHERE pane_id='%55'")
    monkeypatch.setattr(transcripts, "ruta_de_sesion", lambda sid, *a: ruta if sid == "s-1" else None)
    monkeypatch.setattr(herramientas_tui(), "ocupado", lambda agente, pane_id: False)
    r = herramientas._respuesta_de_sesion(None, {"slot": 1})
    assert r["ventana"] == "%55" and r["terminada"] is True
    assert r["respuesta"].startswith("Hecho") and "sk-ant-abc123" not in r["respuesta"]

    # En vivo: si sigue trabajando, no está terminada aunque el muestreo diga quieta.
    monkeypatch.setattr(herramientas_tui(), "ocupado", lambda agente, pane_id: True)
    assert herramientas._respuesta_de_sesion(None, {"slot": 1})["terminada"] is False


def herramientas_tui():
    from hub import tui
    return tui


def test_lo_que_la_sesion_le_contesta_despues_al_dueno_no_es_la_respuesta(tmp_path):
    """Él sigue escribiendo en esa sesión: la respuesta al secretario acaba ahí (revisor)."""
    from hub import transcripts
    ruta = tmp_path / "s.jsonl"
    lineas = [
        {"type": "user", "uuid": "1", "message": {"content": f"{pc.MARCA_SESION}\nhaz el servicio"}},
        {"type": "assistant", "uuid": "2", "message": {"content": [{"type": "text", "text": "Hecho el servicio."}]}},
        {"type": "user", "uuid": "3", "message": {"content": "ahora cambia el nombre de la tabla"}},
        {"type": "assistant", "uuid": "4", "message": {"content": [{"type": "text", "text": "Tabla renombrada."}]}},
    ]
    ruta.write_text("\n".join(json.dumps(x) for x in lineas), encoding="utf-8")
    assert transcripts.respuesta_tras(ruta, pc.MARCA_SESION, hasta_el_siguiente=True) == "Hecho el servicio."
    assert "Tabla renombrada." in transcripts.respuesta_tras(ruta, pc.MARCA_SESION)   # el orquestador, como antes


def test_sin_respuesta_todavia_no_esta_terminada(hub, tmp_path, monkeypatch):
    """Justo después de escribirle, sin texto aún: no se cuenta como «no contestó nada»."""
    from hub import transcripts
    ruta = tmp_path / "v.jsonl"
    ruta.write_text(json.dumps({"type": "user", "uuid": "1", "message": {"content": f"{pc.MARCA_SESION}\nhola"}}),
                    encoding="utf-8")
    hub.execute("UPDATE panel SET claude_sesion='s-2' WHERE pane_id='%55'")
    monkeypatch.setattr(transcripts, "ruta_de_sesion", lambda sid, *a: ruta)
    monkeypatch.setattr(herramientas_tui(), "ocupado", lambda agente, pane_id: False)
    r = herramientas._respuesta_de_sesion(None, {"slot": 1})
    assert r["respuesta"] == "" and r["terminada"] is False


def test_los_slots_dicen_que_una_sesion_quieta_esta_viva_y_esperando(hub):
    """El secretario leyó «detenido» como «no hay terminal viva» (9-nov)."""
    (slot,) = herramientas._hub_slots(None, {})
    assert slot["sesion"] == "abierta y esperando un mensaje"
    assert slot["agentes"] == [{"ventana": "%55", "agente": "Claude Code",
                                "estado": "abierta y esperando un mensaje"}]


# ── en qué está una sesión (C-0419, SEC-16) ──────────────────────────────────

SESION = "0b5c7d2e-1f3a-4b6c-8d9e-0a1b2c3d4e5f"


def _transcript(tmp_path, monkeypatch, lineas) -> None:
    """Un transcript de verdad donde lo busca el hub: `HUB_TRANSCRIPTS`, carpeta de su cwd."""
    from hub import transcripts
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(tmp_path / "transcripts"))
    carpeta = transcripts.directorio_de("/srv/t")
    carpeta.mkdir(parents=True)
    (carpeta / f"{SESION}.jsonl").write_text("\n".join(json.dumps(x) for x in lineas), encoding="utf-8")


def _herramienta(nombre, **entrada):
    return {"type": "tool_use", "name": nombre, "input": entrada}


def test_en_que_esta_una_sesion_es_su_ultimo_mensaje_y_sus_ultimas_herramientas(hub, tmp_path, monkeypatch):
    """«¿Cómo va lo de la tienda?» se quedaba en «está trabajando» (SEC-16)."""
    _transcript(tmp_path, monkeypatch, [
        {"type": "user", "uuid": "1", "timestamp": "2026-11-13T15:00:00Z", "message": {"content": "migra los videos"}},
        {"type": "assistant", "uuid": "2", "message": {"content": [{"type": "text", "text": "Empiezo por el esquema."}]}},
        {"type": "assistant", "uuid": "3", "message": {"content": [_herramienta("Read", file_path="/srv/t/a.py")]}},
        {"type": "assistant", "uuid": "4", "isSidechain": True,
         "message": {"content": [{"type": "text", "text": "soy un subagente"}]}},
        {"type": "assistant", "uuid": "5", "timestamp": "2026-11-13T15:20:00Z", "message": {"content": [
            {"type": "text", "text": "Migración lista; la clave quedó en sk-ant-abc123def456ghi789jkl. Falta el CDN."},
            _herramienta("Edit", file_path="/srv/t/videos.py")]}},
        {"type": "assistant", "uuid": "6", "message": {"content": [
            _herramienta("Bash", command="TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789 uv run pytest"),
            # La etiqueta corta en 60: sin tapar antes, quedaba «ghp_abcdefgh…», que ya no casa.
            _herramienta("Bash", command="echo uno dos tres cuatro cinco seis siete ocho "
                                         "ghp_abcdefghijklmnopqrstuvwxyz0123456789")]}},
    ])
    hub.execute("UPDATE panel SET claude_sesion = ? WHERE pane_id = '%55'", (SESION,))
    r = herramientas._ultimo_de_sesion(None, {"slot": 1})
    assert r["ventana"] == "%55" and r["sesion"] == "abierta y esperando un mensaje"
    assert r["ultimo_mensaje"].startswith("Migración lista") and "Falta el CDN" in r["ultimo_mensaje"]
    assert r["ultimo_mensaje_local"]
    assert r["herramientas"] == ("[Read /srv/t/a.py] · [Edit /srv/t/videos.py] · "
                                 "[Bash: TOKEN=[secreto oculto] uv run pytest] · "
                                 "[Bash: echo uno dos tres cuatro cinco seis siete ocho [secreto ocu…]")
    todo = json.dumps(r, ensure_ascii=False)
    assert "sk-ant-abc123" not in todo and "ghp_" not in todo, "las llaves se tapan, también las que la etiqueta corta"
    assert "subagente" not in todo


def test_un_ultimo_mensaje_largo_se_recorta_por_el_principio(hub, tmp_path, monkeypatch):
    largo = "relleno " * 2000 + "Y al final: falta el CDN."
    _transcript(tmp_path, monkeypatch, [
        {"type": "assistant", "uuid": "1", "message": {"content": [{"type": "text", "text": largo}]}}])
    hub.execute("UPDATE panel SET claude_sesion = ? WHERE pane_id = '%55'", (SESION,))
    r = herramientas._ultimo_de_sesion(None, {"slot": 1})
    assert r["recortado"] is True and len(r["ultimo_mensaje"]) <= herramientas.ULTIMO_MAXIMO
    assert r["ultimo_mensaje"].endswith("falta el CDN.")


def test_sin_conversacion_conocida_lo_dice(hub, tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(tmp_path / "vacio"))
    assert "no sé qué conversación" in herramientas._ultimo_de_sesion(None, {"slot": 1})["error"]
    hub.execute("UPDATE panel SET claude_sesion = ? WHERE pane_id = '%55'", (SESION,))
    assert "no sé qué conversación" in herramientas._ultimo_de_sesion(None, {"slot": 1})["error"]
    assert "slot" in herramientas._ultimo_de_sesion(None, {})["error"]


def test_en_que_esta_una_sesion_solo_se_ofrece_con_el_dueno_delante():
    """En un `pide` con el mensaje de un tercero delante no se sirve (404, C-0241)."""
    assert "ultimo_de_sesion" in herramientas.todas(con_el_dueno=True)
    assert "ultimo_de_sesion" not in herramientas.todas(con_el_dueno=False)
