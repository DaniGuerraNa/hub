"""Lo que de verdad tiene que aguantar: perder tmux sin previo aviso.

Un cierre abrupto no dispara ningún hook, así que la detección se basa en
comparar el PID del servidor entre muestras.
"""

from __future__ import annotations

import pytest

from hub import api, snapshotter, tmux
from hub.registry import Atribuidor
from hub.models import Proyecto


@pytest.fixture
def atribuidor(con):
    con.execute(
        "INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')"
    )
    return Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])


def _paneles(n=2, base="%"):
    return [
        {
            "session": "demo",
            "window_idx": i,
            "pane_idx": 0,
            "pane_id": f"{base}{i}",
            "cwd": "/tmp/demo",
            "titulo": f"⠂ Tarea {i}",
            "comando": "claude",
            "activo": i == 0,
        }
        for i in range(n)
    ]


def _falsear(monkeypatch, pid, paneles):
    monkeypatch.setattr(tmux, "servidor_pid", lambda: pid)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: paneles)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)


def test_captura_atribuye_y_limpia_la_etiqueta(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)

    paneles = api.paneles_abiertos(con)
    assert len(paneles) == 2
    assert paneles[0]["proyecto_id"] == "demo"
    assert paneles[0]["etiqueta"] == "Tarea 0"
    assert paneles[0]["comando"] == "claude"


def test_detecta_el_corte_y_preserva_la_ultima_muestra(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(3))
    snapshotter.capturar(con, atribuidor)
    snapshotter.capturar(con, atribuidor)

    # WSL se cae y tmux vuelve con otro PID y un solo panel.
    _falsear(monkeypatch, 200, _paneles(1, base="%n"))
    snapshotter.capturar(con, atribuidor)

    perdido = api.recuperacion_pendiente(con)
    assert perdido is not None
    assert len(perdido["paneles"]) == 3, "debe mostrar lo que había ANTES del corte"
    assert perdido["server_pid"] == 100


def test_sin_servidor_no_pisa_la_ultima_muestra_buena(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(3))
    snapshotter.capturar(con, atribuidor)

    # tmux muerto: ni PID ni paneles. No debe escribirse un snapshot vacío.
    _falsear(monkeypatch, None, [])
    assert snapshotter.capturar(con, atribuidor) is None

    perdido = api.recuperacion_pendiente(con)
    assert perdido is not None and len(perdido["paneles"]) == 3


def test_un_corte_sin_nada_abierto_no_se_anuncia(con, atribuidor, monkeypatch):
    """Reiniciar con la terminal cerrada no pierde nada: no hay nada que avisar."""
    _falsear(monkeypatch, 100, [])
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, 200, _paneles(1))
    snapshotter.capturar(con, atribuidor)

    assert api.recuperacion_pendiente(con) is None


def test_marcar_revisada_deja_de_anunciar(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, 200, _paneles(1))
    snapshotter.capturar(con, atribuidor)

    perdido = api.recuperacion_pendiente(con)
    api.marcar_recuperacion_revisada(con, perdido["id"])
    assert api.recuperacion_pendiente(con) is None


def test_la_poda_respeta_los_preservados(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, 200, _paneles(2))
    for _ in range(12):
        snapshotter.capturar(con, atribuidor)

    snapshotter.podar(con, retencion=3)
    filas = con.execute("SELECT preservado FROM snapshot").fetchall()
    assert sum(1 for f in filas if f["preservado"] == 1) == 1
    assert sum(1 for f in filas if f["preservado"] == 0) == 3


def test_el_binding_sobrevive_entre_muestras(con, atribuidor, monkeypatch):
    from hub import slots

    _falsear(monkeypatch, 100, _paneles(1))
    snapshotter.capturar(con, atribuidor)
    slot_id = slots.crear(con, "demo", "back", ruta="/tmp/demo")
    slots.vincular(con, "%0", slot_id)

    snapshotter.capturar(con, atribuidor)
    panel = api.paneles_abiertos(con)[0]
    assert panel["slot_id"] == slot_id
    assert panel["slot_nombre"] == "back"

    # Y registra actividad en el slot, que es dato para ordenar, no gestión.
    assert api.obtener_slot(con, slot_id)["ultima_actividad"] is not None


def test_el_ciclo_barre_espejos_huerfanos(con, atribuidor, monkeypatch):
    """Si el navegador muere sin avisar, el espejo queda: el latido lo limpia."""
    from hub import registry, terminal

    barridos = []
    monkeypatch.setattr(registry, "cargar", lambda *a, **k: [])
    monkeypatch.setattr(terminal, "limpiar_espejos_huerfanos",
                        lambda *a, **k: barridos.append(True) or [])
    _falsear(monkeypatch, 100, _paneles(1))

    snapshotter.un_ciclo(con)
    assert barridos == [True]


def test_un_barrido_fallido_no_tumba_el_ciclo(con, atribuidor, monkeypatch):
    """El snapshotter existe para funcionar el día que todo lo demás falla."""
    from hub import registry, terminal

    monkeypatch.setattr(registry, "cargar", lambda *a, **k: [])
    monkeypatch.setattr(terminal, "limpiar_espejos_huerfanos",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tmux caído")))
    _falsear(monkeypatch, 100, _paneles(2))

    assert snapshotter.un_ciclo(con) is not None


def test_un_barrido_fallido_se_dice_en_voz_alta(con, atribuidor, monkeypatch, capsys):
    """C-0085, regla dura 21: no tumba el ciclo, pero tampoco se calla."""
    from hub import registry, terminal

    monkeypatch.setattr(registry, "cargar", lambda *a, **k: [])
    monkeypatch.setattr(terminal, "limpiar_espejos_huerfanos",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tmux caído")))
    _falsear(monkeypatch, 100, _paneles(2))

    snapshotter.un_ciclo(con)
    assert "tmux caído" in capsys.readouterr().out


def test_tras_un_corte_las_ventanas_vuelven_a_su_slot(con, atribuidor, monkeypatch):
    """El caso real del 2026-09-04: tmux reinicia y todo queda «desacomodado».

    `resurrect` devuelve la sesión con su nombre y sus ventanas, pero con otros
    `pane_id`. Sin reconciliación, TODOS los slots se quedan vacíos y todas las
    terminales caen a la bandeja.
    """
    from hub import slots

    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)
    slot_id = slots.crear(con, "demo", "back", ruta="/tmp/demo")
    slots.vincular(con, "%0", slot_id)
    snapshotter.capturar(con, atribuidor)

    # Muere el servidor y resurrect restaura lo mismo con otros ids de panel.
    _falsear(monkeypatch, 200, _paneles(2, base="%n"))
    snapshotter.capturar(con, atribuidor)

    panel = next(p for p in api.paneles_abiertos(con) if p["pane_id"] == "%n0")
    assert panel["slot_id"] == slot_id, "el slot tiene que seguir ocupado tras el corte"
    assert panel["slot_nombre"] == "back"


def test_la_reconciliacion_no_revive_un_slot_archivado(con, atribuidor, monkeypatch):
    """Archivar es una decisión humana: un corte no puede deshacerla (principio 9)."""
    from hub import slots

    _falsear(monkeypatch, 100, _paneles(1))
    snapshotter.capturar(con, atribuidor)
    slot_id = slots.crear(con, "demo", "back", ruta="/tmp/demo")
    slots.vincular(con, "%0", slot_id)
    snapshotter.capturar(con, atribuidor)
    slots.archivar(con, slot_id)

    _falsear(monkeypatch, 200, _paneles(1, base="%n"))
    snapshotter.capturar(con, atribuidor)

    assert api.paneles_abiertos(con)[0]["slot_id"] is None


def test_la_reconciliacion_no_ata_una_ventana_que_no_estaba(con, atribuidor, monkeypatch):
    """Sólo se restaura lo que alguien ató; no se inventan vínculos nuevos."""
    from hub import slots

    _falsear(monkeypatch, 100, _paneles(1))
    snapshotter.capturar(con, atribuidor)
    slot_id = slots.crear(con, "demo", "back", ruta="/tmp/demo")
    slots.vincular(con, "%0", slot_id)
    snapshotter.capturar(con, atribuidor)

    # Tras el corte hay una ventana MÁS, que nunca tuvo slot.
    _falsear(monkeypatch, 200, _paneles(2, base="%n"))
    snapshotter.capturar(con, atribuidor)

    por_id = {p["pane_id"]: p for p in api.paneles_abiertos(con)}
    assert por_id["%n0"]["slot_id"] == slot_id
    assert por_id["%n1"]["slot_id"] is None


def test_apunta_que_conversacion_de_claude_corre_en_cada_panel_si_el_proceso_vive(
        tmp_path, monkeypatch):
    """Decisión 289: de ahí sale el `claude --resume` de «Restaurar». Un archivo
    de un proceso muerto apunta a un panel del tmux de ANTES y no cuenta."""
    import json
    import os
    from hub import orquestador, snapshotter

    carpeta = tmp_path / "sessions"
    carpeta.mkdir()
    vivo = {"pid": os.getpid(), "sessionId": "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
            "tmux": "work:@2.%7"}
    muerto = {"pid": 2 ** 22 + 7, "sessionId": "aaaaaaaa-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
              "tmux": "work:@3.%9"}
    raro = {"pid": os.getpid(), "sessionId": "no-es-un-uuid", "tmux": "work:@4.%11"}
    for i, d in enumerate((vivo, muerto, raro)):
        (carpeta / f"{i}.json").write_text(json.dumps(d))
    (carpeta / "roto.json").write_text("{")
    monkeypatch.setattr(orquestador, "_sesiones_de_claude", lambda: carpeta)

    assert snapshotter.claude_por_panel() == {"%7": vivo["sessionId"]}


def test_un_panel_que_ensena_un_trabajo_en_segundo_plano_apunta_a_la_conversacion_del_trabajo(
        tmp_path, monkeypatch):
    """C-0228: el Claude de la ventana sólo enseña el trabajo (`parkedJobId`);
    quien trabaja, y tiene los subagentes, es la conversación del trabajo.
    Medido el 9-nov en 2.1.280. Si el trabajo ya no vive, la de la ventana."""
    import json
    import os
    from hub import orquestador, snapshotter

    carpeta = tmp_path / "sessions"
    carpeta.mkdir()
    ventana = {"pid": os.getpid(), "sessionId": "11111111-2222-4333-8444-555555555555",
               "tmux": "trabajo:@1.%1", "kind": "interactive", "parkedJobId": "ab12cd34"}
    trabajo = {"pid": os.getpid(), "sessionId": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
               "kind": "bg", "jobId": "ab12cd34"}
    huerfana = {"pid": os.getpid(), "sessionId": "99999999-8888-4777-8666-555555555555",
                "tmux": "trabajo:@2.%2", "kind": "interactive", "parkedJobId": "deadbeef"}
    muerto = {"pid": 2 ** 22 + 7, "sessionId": "aaaaaaaa-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
              "kind": "bg", "jobId": "deadbeef"}
    # El trabajo se escribe DESPUÉS de la ventana: el orden de lectura no decide.
    for nombre, d in (("a", ventana), ("b", huerfana), ("c", muerto), ("d", trabajo)):
        (carpeta / f"{nombre}.json").write_text(json.dumps(d))
    monkeypatch.setattr(orquestador, "_sesiones_de_claude", lambda: carpeta)

    assert snapshotter.claude_por_panel() == {"%1": trabajo["sessionId"],
                                              "%2": huerfana["sessionId"]}


def test_sin_servidor_nada_sigue_contando_como_abierto(con, atribuidor, monkeypatch):
    """Con tmux muerto, lo de antes no puede seguir saliendo como abierto.

    `detectar_corte` preserva sólo la última muestra del servidor que murió, así
    que la penúltima —mismos paneles— pasaba a ser la «actual» y nadie la
    pisaba, porque sin servidor no se escribe nada. El slot salía en verde y su
    «Abrir» llevaba a una terminal sin nada detrás.
    """
    _falsear(monkeypatch, 100, _paneles(3))
    snapshotter.capturar(con, atribuidor)
    snapshotter.capturar(con, atribuidor)  # dos del mismo servidor: se preserva una

    _falsear(monkeypatch, None, [])
    snapshotter.capturar(con, atribuidor)

    assert api.snapshot_actual(con) is None
    assert api.paneles_abiertos(con) == []
    assert len(api.recuperacion_pendiente(con)["paneles"]) == 3


def test_al_volver_tmux_lo_abierto_vuelve_a_verse(con, atribuidor, monkeypatch):
    """Y la otra mitad: un corte no apaga la vista para siempre."""
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, None, [])
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, 200, _paneles(1, base="%n"))
    snapshotter.capturar(con, atribuidor)

    paneles = api.paneles_abiertos(con)
    assert len(paneles) == 1 and paneles[0]["pane_id"] == "%n0"


def test_un_muestreo_que_falla_no_deja_sin_programados_ni_orquestador(con, monkeypatch, capsys):
    """El 7-nov una carpeta de OneDrive ilegible tumbó el muestreo durante
    minutos, y con él lo que iba detrás en el mismo `try`: los programados y el
    despertar del orquestador (regla dura 2, decisión 376)."""
    hechos = []

    def revienta(c):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(snapshotter, "un_ciclo", revienta)
    monkeypatch.setattr(snapshotter, "ciclo_mensajes", lambda c: hechos.append("programados") or 0)
    monkeypatch.setattr(snapshotter.orquestador, "bombear", lambda c: hechos.append("orquestador") or {})
    monkeypatch.setattr(snapshotter, "ciclo_lento", lambda c: hechos.append("lento"))
    monkeypatch.setattr(snapshotter.salud, "latir", lambda: hechos.append("latido"))

    snapshotter.vuelta(con, 0)

    assert hechos == ["latido", "programados", "orquestador", "lento"]
    assert "muestreo fallido" in capsys.readouterr().out


def test_un_programa_de_windows_ilegible_es_que_no_esta(monkeypatch, capsys):
    """El 7-nov todo `/mnt/c` dio EIO: `encontrar` lanzaba en vez de decir que
    no hay, y con él el diagnóstico y las lecturas de la máquina."""
    from hub import maquina

    monkeypatch.setattr(maquina.shutil, "which", lambda n: None)

    def revienta(self):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(maquina.Path, "is_file", revienta)
    assert maquina.encontrar("powershell.exe") is None
    assert "no se puede leer" in capsys.readouterr().out


def test_con_tmux_apagado_lo_ya_revisado_no_vuelve_a_salir_como_perdido(con):
    """C-0227: `detectar_corte` corre en cada ciclo mientras tmux está apagado, y
    volvía a poner `preservado=1` sobre el `2` de «revisada»: el «Ya lo revisé»
    (o cerrar la última ventana a propósito) volvía a avisar a los 20 s."""
    from hub import api, snapshotter

    sid = con.execute("INSERT INTO snapshot (tomado_en, server_pid) VALUES ('2026-11-09', 4242)").lastrowid
    con.execute("INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx, cwd) "
                "VALUES (?, '%1', 'w', 0, 0, '/tmp')", (sid,))
    assert snapshotter.detectar_corte(con, None) is True
    assert api.recuperacion_pendiente(con)["id"] == sid
    api.marcar_recuperacion_revisada(con, sid)

    snapshotter.detectar_corte(con, None)
    assert api.recuperacion_pendiente(con) is None
    # Un servidor nuevo sigue contando como corte: es lo que devuelve los slots.
    assert snapshotter.detectar_corte(con, 5151) is True


def test_quien_lee_mientras_se_escribe_la_muestra_ve_la_anterior_entera(con, atribuidor, monkeypatch, tmp_path):
    """C-0234 (revisor): con las filas `panel` escritas una a una, el latido de
    Trabajo llegó a leer `[]` a mitad de la muestra y soltaba ventanas vivas.
    Ahora la muestra entra de una vez: quien lee en medio ve la anterior."""
    from hub import db

    _falsear(monkeypatch, 100, _paneles(3))
    snapshotter.capturar(con, atribuidor)
    otra = db.conectar(tmp_path / "hub.db")
    vistos = []

    def al_escribir(sql):
        if sql.lstrip().startswith("INSERT INTO panel"):
            vistos.append(sorted(api.pulso_trabajo(otra)["paneles"] or []))

    con.set_trace_callback(al_escribir)
    snapshotter.capturar(con, atribuidor)
    con.set_trace_callback(None)
    otra.close()
    assert vistos and all(v == ["%0", "%1", "%2"] for v in vistos)
