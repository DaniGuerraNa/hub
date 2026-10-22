"""Qué ventanas devuelve el botón de restaurar, y de qué muestra las saca.

🔴 Este archivo existe porque la primera versión **pasó sus tests y falló con
los datos de verdad**. La lógica estaba mezclada con la ejecución en tmux, así
que sólo se podía probar abriendo ventanas, y las dos reglas que elegían la
muestra —«la más reciente con paneles» y luego «la del PID anterior»— parecían
correctas y eran incorrectas las dos. Se vieron al ejecutarlas contra la base
real tras un apagón, no leyendo el código.

Todo lo de aquí es puro: ni tmux, ni disco salvo el que se inyecta.
"""

from __future__ import annotations

import os

import pytest

from hub import db, restauracion


@pytest.fixture
def con(tmp_path):
    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    con.execute(
        "INSERT INTO proyecto (id, nombre, asiento, estado_ref) VALUES ('demo','Demo','/p','E.md')"
    )
    con.execute(
        """INSERT INTO slot (id, proyecto_id, nombre, ruta, restaurar, creado_en)
           VALUES (1,'demo','Trabajo','/p/trabajo',1,'2026-09-01')"""
    )
    con.execute(
        """INSERT INTO slot (id, proyecto_id, nombre, ruta, restaurar, creado_en)
           VALUES (2,'demo','Sin marcar','/p/otro',0,'2026-09-01')"""
    )
    yield con
    con.close()


def _muestra(con, id_, pid, preservado=1, paneles=()):
    con.execute(
        "INSERT INTO snapshot (id, tomado_en, server_pid, preservado) VALUES (?,?,?,?)",
        (id_, f"2026-09-16T{id_ % 24:02d}:00:00+00:00", pid, preservado),
    )
    for session, vent, panel, cwd, comando, slot_id in paneles:
        con.execute(
            """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                                  cwd, comando, slot_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (id_, f"%{id_}{vent}{panel}", session, vent, panel, cwd, comando, slot_id),
        )


TODO_EXISTE = lambda r: bool(r)          # noqa: E731
NADA_EXISTE = lambda r: False            # noqa: E731


# ─────────────────────────── de qué muestra ───────────────────────────


def test_sin_slots_marcados_no_hay_plan(con):
    """Un botón que abre ventanas de slots que nadie marcó sería una sorpresa."""
    con.execute("UPDATE slot SET restaurar=0")
    _muestra(con, 10, 111, paneles=[("s", 0, 0, "/p/a", "claude", 1)])
    assert restauracion.plan_de_restauracion(con, existe=TODO_EXISTE) == []


def test_se_eligen_solo_las_muestras_de_antes_de_un_corte(con):
    """Las corrientes no valen: tras arrancar en frío, la última es tmux vacío."""
    _muestra(con, 10, 111, preservado=1, paneles=[("s", 0, 0, "/p/a", "claude", 1)])
    _muestra(con, 11, 222, preservado=0, paneles=[("s", 0, 0, "/p/z", "bash", 1)])
    assert [c["id"] for c in restauracion.candidatos_de_restauracion(con)] == [10]


def test_una_muestra_sin_slots_no_es_candidata(con):
    """No tendría de dónde sacar ninguna ventana: ofrecerla es ofrecer un vacío."""
    _muestra(con, 10, 111, paneles=[("s", 0, 0, "/p/a", "claude", None)])
    assert restauracion.candidatos_de_restauracion(con) == []


def test_las_candidatas_dicen_qué_procesos_había(con):
    """🔴 Es lo único que dejó distinguir las dos del 16-sep.

    Las dos tenían los mismos slots y casi los mismos paneles; una era el
    escritorio de trabajo y la otra un tmux de veinte segundos. Lo que las
    separaba era que en una corría algo.
    """
    _muestra(con, 10, 111, paneles=[("s", 0, 0, "/p/a", "claude", 1),
                                    ("s", 1, 0, "/p/b", "codex", 1)])
    _muestra(con, 20, 222, paneles=[("s", 0, 0, "/p/a", "bash", 1)])
    por_id = {c["id"]: c for c in restauracion.candidatos_de_restauracion(con)}
    assert por_id[10]["procesos"] == ["claude", "codex"]
    assert por_id[20]["procesos"] == ["bash"]


def test_se_puede_pedir_una_muestra_que_no_es_la_por_defecto(con):
    """Si no, mirar un plan y ejecutar otro sería posible."""
    _muestra(con, 10, 111, paneles=[("s", 0, 0, "/p/vieja", "claude", 1)])
    _muestra(con, 20, 222, paneles=[("s", 0, 0, "/p/nueva", "claude", 1)])
    plan = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE, muestra_id=10)
    assert [p["ruta"] for p in plan] == ["/p/vieja"]


# ─────────────────────────── qué ventanas ───────────────────────────


def test_devuelve_una_ventana_por_cada_una_que_había(con):
    """Lo que pidió: «toda terminal que ya estaba dentro de un slot»."""
    _muestra(con, 10, 111, paneles=[
        ("work", 0, 0, "/p/trabajo", "claude", 1),
        ("work", 1, 0, "/p/trabajo", "bash", 1),
        ("work", 2, 0, "/p/trabajo", "claude", 1),
    ])
    assert len(restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)) == 3


def test_dos_paneles_de_la_misma_ventana_son_una_ventana(con):
    """🔴 Una ventana partida en dos no son dos ventanas.

    Sin esto, cada apagón multiplicaría el escritorio: dos paneles hoy, cuatro
    ventanas mañana, ocho al siguiente. La división es geometría, no trabajo.
    """
    _muestra(con, 10, 111, paneles=[
        ("work", 0, 0, "/p/trabajo", "claude", 1),
        ("work", 0, 1, "/p/trabajo", "bash", 1),
    ])
    assert len(restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)) == 1


def test_un_slot_marcado_que_no_salía_en_la_muestra_recibe_su_ventana(con):
    """Es el contrato de la decisión 165, que esto amplía y no sustituye."""
    _muestra(con, 10, 111, paneles=[("work", 0, 0, "/p/trabajo", "claude", 1)])
    con.execute("UPDATE slot SET restaurar=1 WHERE id=2")
    plan = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert {p["nombre"]: p["origen"] for p in plan} == {
        "Trabajo": "muestra", "Sin marcar": "slot"}


def test_un_slot_sin_marcar_no_vuelve_aunque_estuviera_abierto(con):
    """La casilla es la que manda, no lo que hubiera abierto (regla dura 3)."""
    _muestra(con, 10, 111, paneles=[("otro", 0, 0, "/p/otro", "claude", 2)])
    plan = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert "Sin marcar" not in [p["nombre"] for p in plan]


# ─────────────────────────── qué comando ───────────────────────────


def test_a_claude_y_a_codex_se_les_deja_su_comando(con):
    _muestra(con, 10, 111, paneles=[("w", 0, 0, "/p/trabajo", "claude", 1),
                                    ("w", 1, 0, "/p/trabajo", "codex", 1)])
    assert [p["comando"] for p in restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)] == [
        restauracion.COMANDO_SUGERIDO, "codex"]


@pytest.mark.parametrize("proceso", ["node", "npm", "bash", "vim", "python3"])
def test_lo_que_no_está_en_la_lista_blanca_abre_la_ventana_y_no_escribe_nada(con, proceso):
    """🔴 Nunca se escribe el valor de la muestra tal cual.

    `panel.comando` es lo que tmux reportaba; de ahí a teclearlo en una terminal
    hay un salto que no se da. Y `npm run dev` no se reconstruye desde «npm»:
    adivinarlo sería peor que dejar la ventana lista.
    """
    _muestra(con, 10, 111, paneles=[("w", 0, 0, "/p/trabajo", proceso, 1)])
    plan = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert plan[0]["comando"] == ""
    assert plan[0]["ruta"] == "/p/trabajo"


# ─────────────────────────── qué ruta ───────────────────────────


@pytest.mark.parametrize("guardada, esperada", [
    ("/mnt/c_stale2/Users/d/proy", "/mnt/c/Users/d/proy"),
    ("/mnt/c_stale/Users/d/proy", "/mnt/c/Users/d/proy"),
    ("/mnt/d_stale7/cosas", "/mnt/d/cosas"),
    ("/Users/d/proy", "/mnt/c/Users/d/proy"),
    ("/mnt/c_stale", "/mnt/c"),
    ("/home/u/proy", "/home/u/proy"),
    ("/mnt/c/Users/d/proy", "/mnt/c/Users/d/proy"),
])
def test_las_rutas_de_montajes_rancios_se_traen_al_de_hoy(guardada, esperada):
    """🔴 10 de las 19 rutas de la muestra del 16-sep ya no existían por esto.

    Cuando WSL pierde el disco de Windows mueve el montaje roto a un lado y
    monta otro nuevo; el muestreo guarda la ruta tal cual la ve.
    """
    assert restauracion.normalizar_ruta(guardada) == esperada


def test_una_carpeta_que_solo_se_parece_no_se_toca():
    """`_stale` como parte de un nombre real no es un montaje rancio."""
    assert restauracion.normalizar_ruta("/mnt/carpeta_stale2/x") == "/mnt/carpeta_stale2/x"


def test_si_la_ruta_guardada_ya_no_existe_se_cae_a_la_del_slot(con):
    _muestra(con, 10, 111, paneles=[("w", 0, 0, "/p/se-borro", "claude", 1)])
    plan = restauracion.plan_de_restauracion(
        con, existe=lambda r: r == "/p/trabajo")
    assert plan[0]["ruta"] == "/p/trabajo"
    assert "ya no existe" in plan[0]["aviso"]


def test_si_no_existe_ninguna_no_se_abre_y_se_dice(con):
    """🔴 Abrirla en un sitio cualquiera sería peor que no abrirla."""
    _muestra(con, 10, 111, paneles=[("w", 0, 0, "/p/se-borro", "claude", 1)])
    plan = restauracion.plan_de_restauracion(con, existe=NADA_EXISTE)
    assert plan[0]["ruta"] == ""
    assert plan[0]["comando"] == ""
    assert "no existe" in plan[0]["aviso"]


# ──────────────── «~» no es un destino, es la falta de uno ────────────────
#
# Medido en su máquina el 2026-09-17. Tras el apagón, WSL renombró el montaje a
# `/mnt/c_stale2`, tmux-resurrect guardó esa ruta y al restaurar tmux cayó a
# `$HOME` porque ya no existía. De las cinco ventanas de `work`, las cuatro con
# la ruta rancia acabaron en `~` y la única con la ruta buena acabó bien.
#
# El hub no abrió ninguna de ellas. Lo que sí es suyo es que el plan lee el
# estado de AHORA: sin esto, «Restaurar» volvía a abrir en `~` —10 de 14
# ventanas ese día— y cada vuelta lo dejaba igual de mal.

CASA = os.path.expanduser("~")


def test_una_ventana_en_casa_vuelve_a_la_ruta_del_slot(con):
    """🔴 La tercera forma de ruta rota, y la única que EXISTE.

    Por eso las dos comprobaciones anteriores la daban por buena: `~` está ahí,
    se puede abrir, y una ventana abierta en el sitio equivocado no se distingue
    de una bien abierta hasta que uno teclea.
    """
    _muestra(con, 5, 100,
             paneles=[("work", 0, 0, CASA, "claude", 1)])
    (paso,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert paso["ruta"] == "/p/trabajo"
    assert "donde cae una shell sin ruta" in paso["aviso"]


def test_se_dice_que_no_se_abrio_donde_ponia(con):
    """Callarlo dejaría a alguien en una ruta que no es la suya creyendo que sí."""
    _muestra(con, 6, 100,
             paneles=[("work", 0, 0, "/", "claude", 1)])
    (paso,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert paso["ruta"] == "/p/trabajo"
    assert paso["ruta_pedida"] == "/"


def test_un_slot_que_vive_en_casa_se_queda_en_casa(con):
    """No todo `~` es un error: si la ruta del slot ES `~`, ahí es donde va.

    Sin esta línea, el arreglo convertía un slot legítimo en uno sin ruta.
    """
    con.execute("UPDATE slot SET ruta=? WHERE id=1", (CASA,))
    _muestra(con, 7, 100,
             paneles=[("work", 0, 0, CASA, "claude", 1)])
    (paso,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert paso["ruta"] == CASA
    assert paso["aviso"] == ""


def test_si_el_slot_no_tiene_otra_ruta_se_queda_donde_estaba(con):
    """Mandar a una ruta que tampoco existe no arregla nada: se abre donde
    estaba y se dice, que es mejor que no abrir."""
    con.execute("UPDATE slot SET ruta=NULL WHERE id=1")
    _muestra(con, 8, 100,
             paneles=[("work", 0, 0, CASA, "claude", 1)])
    (paso,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert paso["ruta"] == CASA


def test_una_ruta_buena_no_se_toca(con):
    """La quinta ventana de `work`, la que sí acabó donde debía."""
    _muestra(con, 9, 100,
             paneles=[("work", 0, 0, "/p/trabajo/sub", "claude", 1)])
    (paso,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert paso["ruta"] == "/p/trabajo/sub"
    assert paso["aviso"] == ""


# ─────────────── reanudar la conversación (decisión 289) ───────────────

SESION = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _con_conversacion(con, sesion, cwd="/p/a"):
    _muestra(con, 10, 111, paneles=[("s", 0, 0, cwd, "claude", 1)])
    con.execute("UPDATE panel SET claude_sesion=? WHERE snapshot_id=10", (sesion,))


def test_una_ventana_con_claude_deja_escrito_reanudar_su_conversacion(con, monkeypatch):
    monkeypatch.delenv("HUB_RESTAURAR_CLAUDE", raising=False)
    _con_conversacion(con, SESION)

    (v,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)

    assert v["comando"] == f"claude --resume {SESION}" and v["reanuda"]


@pytest.mark.parametrize("modo, esperado", [("nuevo", "claude"), ("nada", ""),
                                            ("cualquier-cosa", f"claude --resume {SESION}")])
def test_el_modo_se_elige_con_la_variable(con, monkeypatch, modo, esperado):
    monkeypatch.setenv("HUB_RESTAURAR_CLAUDE", modo)
    _con_conversacion(con, SESION)
    (v,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert v["comando"] == esperado


def test_sin_conversacion_conocida_o_con_un_id_raro_se_deja_claude_a_secas(con):
    _con_conversacion(con, "x; rm -rf ~")
    (v,) = restauracion.plan_de_restauracion(con, existe=TODO_EXISTE)
    assert v["comando"] == "claude" and not v["reanuda"]


def test_si_se_abre_en_otra_carpeta_no_se_reanuda(con):
    """Claude Code busca la conversación por la ruta: desde otra, `--resume` falla."""
    _con_conversacion(con, SESION, cwd="/p/ya-no-esta")
    (v,) = restauracion.plan_de_restauracion(con, existe=lambda r: r != "/p/ya-no-esta")
    assert v["ruta"] == "/p/trabajo" and v["comando"] == "claude"
