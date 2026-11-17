"""Invariantes de ventanas y slots, contra un tmux de verdad (C-0328, HIS-05).

Las quejas que más ha repetido el dueño en tres meses son de esta familia:
«veo una en sin organizar que también está en trabajo» (10-sep), «abrí dos
sobre estudio y no se asociaron» (23-oct), «no importa qué nombre le dé, me
lleva siempre a la primera» (11-nov). Cada arreglo tocó una ruta y la
siguiente falló igual en otra, porque abrir, atar y leer una ventana pasa por
varias copias (C-0043, C-0083, C-0084, C-0105).

Aquí no se arregla nada: se fija **qué tiene que ser verdad siempre**, y se
ejercita por las puertas de producción —las rutas de la web y `slots`— con un
servidor de tmux propio, en el socket de pruebas de la pasada (nunca el de
quien la ejecuta). Lo que se mira es lo que pinta /trabajo:

- una ventana viva sale en UN solo sitio (bajo un slot, en «Sin organizar» o
  entre las ocultas), y ninguna se pierde;
- lo que sale en «Sin organizar» no tiene slot, y lo que la franja de pestañas
  dice de cada ventana (`pertenece`) cuadra con dónde sale;
- abrir una ventana desde un slot la deja bajo él; moverla, renombrarla o
  cerrar otra no rompe nada.

Lo que hoy no se cumple va marcado `xfail(strict=True)` con su porqué: el día
que se arregle, el test pasa, el `strict` lo pone en rojo y hay que quitar la
marca. Es el aviso de que el invariante ya se sostiene.
"""

from __future__ import annotations

import os
import shutil

import pytest
from fastapi.testclient import TestClient

import arnes_tmux
from hub import api, config, slots, snapshotter, terminal, tmux, web

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="tmux no disponible")

ORIGEN = {"origin": "http://127.0.0.1:8787"}


class Escena:
    """La base, el registro con dos proyectos y un tmux vacío, todo de verdad."""

    def __init__(self, con, raiz) -> None:
        self.con = con
        self.raiz = raiz
        self.web = TestClient(web.app)

    def muestrear(self) -> None:
        """Lo que hace el snapshotter cada 20 s; aquí no hay demonio."""
        snapshotter.un_ciclo(self.con)

    def slot(self, proyecto: str, nombre: str) -> int:
        # `cat`: un proceso que vive y no lee el perfil de nadie.
        return slots.crear(self.con, proyecto, nombre, comando="cat")

    def ventanas(self, session: str) -> list[dict]:
        return tmux.listar_ventanas(session)

    def sitios(self) -> dict[tuple[str, int | None], list[str]]:
        """Cada ventana → en qué sitios de /trabajo sale, como los lee la ruta."""
        ctx = api.contexto_trabajo(self.con)
        sueltas, tapadas = api.bandeja_de_ventanas(
            self.con, terminal.sesiones_disponibles(), ctx["paneles"])
        sitios: dict[tuple[str, int | None], list[str]] = {}
        for p in ctx["proyectos"]:
            for s in p["slots"]:
                for v in s["ventanas"]:
                    sitios.setdefault((v["session"], v["ventana"]), []).append(f"slot {s['id']}")
        for f in sueltas:
            sitios.setdefault((f["session"], f["ventana"]), []).append("sin organizar")
        for f in tapadas:
            sitios.setdefault((f["session"], f["ventana"]), []).append("oculta")
        return sitios

    def donde(self, session: str, indice: int) -> list[str]:
        return self.sitios().get((session, indice), [])

    def comprobar(self) -> dict[tuple[str, int | None], list[str]]:
        """Los invariantes de siempre, sobre una muestra recién tomada."""
        self.muestrear()
        sitios = self.sitios()
        vivas = {(p["session"], p["window_idx"]) for p in tmux.listar_paneles()}

        dobles = {v: s for v, s in sitios.items() if len(s) > 1}
        assert not dobles, f"ventanas en más de un sitio: {dobles}"
        assert set(sitios) == vivas, (
            f"perdidas: {sorted(vivas - set(sitios))}; inventadas: {sorted(set(sitios) - vivas, key=str)}")

        # La franja de pestañas de cada sesión dice lo mismo que la barra.
        for session in {s for s, _ in vivas}:
            for v in api.ventanas_de_sesion(self.con, session):
                lugar = sitios[(session, v["indice"])][0]
                if lugar.startswith("slot "):
                    assert v["pertenece"] == "este" and v["slot"]["id"] == int(lugar[5:]), (session, v)
                else:
                    assert v["pertenece"] == "ninguno", (session, v)

        # Y las ventanas de cada slot son las mismas que da `paneles_de_slot`,
        # que es por donde le escriben el secretario y el orquestador.
        for (session, indice), (lugar,) in sitios.items():
            if lugar.startswith("slot "):
                suyas = {(p["session"], p["window_idx"])
                         for p in api.paneles_de_slot(self.con, int(lugar[5:]))}
                assert (session, indice) in suyas
        return sitios


@pytest.fixture
def escena(tmp_path, monkeypatch):
    # Un servidor propio colgado del de la pasada: que lo de otros tests no
    # cuente aquí, y que al acabar no quede ni el servidor ni su socket.
    zocalo = f"{os.environ['HUB_TMUX_SOCKET']}-inv"
    monkeypatch.setenv("HUB_TMUX_SOCKET", zocalo)
    monkeypatch.delenv("TMUX", raising=False)
    # Las ventanas sin comando abren la shell de `SHELL`: una sin perfil.
    monkeypatch.setenv("SHELL", "/bin/sh")

    proyectos = []
    for id_ in ("estudio", "tienda"):
        (tmp_path / id_).mkdir()
        proyectos.append(f"  - id: {id_}\n    nombre: {id_.title()}\n    asiento: {tmp_path / id_}\n")
    config.projects_yml().write_text("proyectos:\n" + "".join(proyectos), encoding="utf-8")

    con = web.conexion()
    # Sin tmux aún: sólo sincroniza el registro.
    snapshotter.un_ciclo(con)
    try:
        yield Escena(con, tmp_path)
    finally:
        con.close()
        arnes_tmux.apagar(zocalo)


# --------------------------------------------------------------------------- #
# Abrir
# --------------------------------------------------------------------------- #


def test_lanzar_un_slot_deja_su_ventana_bajo_el_slot_y_en_ningun_otro_sitio(escena):
    """«Lanzar» con tmux sin servidor: crea la sesión, y la ventana es del slot."""
    slot = escena.slot("estudio", "notas")
    r = escena.web.post(f"/slot/{slot}/abrir", data={"proyecto_id": "estudio"},
                        headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303 and "aviso" not in r.headers["location"]

    sitios = escena.comprobar()
    assert list(sitios.values()) == [[f"slot {slot}"]]


def test_dos_ventanas_mas_sobre_el_mismo_slot_quedan_las_dos_asociadas(escena):
    """23-oct: «abrí dos sobre estudio y no se asociaron». El «+» de la franja
    de pestañas con slot, dos veces."""
    slot = escena.slot("estudio", "notas")
    slots.abrir(escena.con, slot)
    escena.muestrear()
    for _ in range(2):
        r = escena.web.post("/api/sesion/estudio/ventanas", json={"slot": slot}, headers=ORIGEN)
        assert r.json() == {"ok": True}

    sitios = escena.comprobar()
    assert sorted(sitios) == [("estudio", i) for i in sorted(v["indice"] for v in escena.ventanas("estudio"))]
    assert all(s == [f"slot {slot}"] for s in sitios.values())
    assert len(sitios) == 3


def test_una_ventana_abierta_sin_slot_sale_solo_en_sin_organizar(escena):
    """El «+» sin slot (`tmux.nueva_ventana`) y la terminal del navegador de
    archivos (`slots.abrir_en`) no son de nadie: salen abajo, y sólo ahí."""
    slot = escena.slot("estudio", "notas")
    slots.abrir(escena.con, slot)
    escena.muestrear()
    r = escena.web.post("/api/sesion/estudio/ventanas", json={"nombre": "suelta"}, headers=ORIGEN)
    assert r.json() == {"ok": True}
    slots.abrir_en(str(escena.raiz / "tienda"), "archivos", "estudio")

    sitios = escena.comprobar()
    por_nombre = {v["nombre"]: v["indice"] for v in escena.ventanas("estudio")}
    assert sitios[("estudio", por_nombre["suelta"])] == ["sin organizar"]
    assert sitios[("estudio", por_nombre["archivos"])] == ["sin organizar"]
    assert sitios[("estudio", por_nombre["notas"])] == [f"slot {slot}"]


# --------------------------------------------------------------------------- #
# Mover
# --------------------------------------------------------------------------- #


def test_mover_una_ventana_a_un_slot_de_otro_proyecto_la_quita_del_primero(escena):
    notas = escena.slot("estudio", "notas")
    caja = escena.slot("tienda", "caja")
    pane = slots.abrir(escena.con, notas)
    escena.muestrear()

    r = escena.web.post("/panel/accion", data={"pane_id": pane, "accion": "vincular",
                                               "slot_id": str(caja), "destino": "/trabajo"},
                        headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303
    # Antes de la muestra siguiente ya está en su sitio: `vincular` toca la vigente.
    indice = api.panel_por_id(escena.con, pane)["window_idx"]
    assert escena.donde("estudio", indice) == [f"slot {caja}"]

    assert escena.comprobar()[("estudio", indice)] == [f"slot {caja}"]
    assert api.paneles_de_slot(escena.con, notas) == []


def test_soltar_una_ventana_la_baja_a_sin_organizar_y_darle_slot_la_sube(escena):
    notas = escena.slot("estudio", "notas")
    pane = slots.abrir(escena.con, notas)
    escena.muestrear()
    indice = api.panel_por_id(escena.con, pane)["window_idx"]

    escena.web.post("/panel/accion", data={"pane_id": pane, "accion": "desvincular"},
                    headers=ORIGEN, follow_redirects=False)
    assert escena.comprobar()[("estudio", indice)] == ["sin organizar"]

    escena.web.post("/panel/accion", data={"pane_id": pane, "accion": "promover", "nombre": "otra cosa"},
                    headers=ORIGEN, follow_redirects=False)
    nuevo = api.panel_por_id(escena.con, pane)["slot_id"]
    assert nuevo and nuevo != notas
    assert escena.comprobar()[("estudio", indice)] == [f"slot {nuevo}"]


# --------------------------------------------------------------------------- #
# Renombrar
# --------------------------------------------------------------------------- #


def test_renombrar_una_ventana_no_rompe_su_vinculo(escena):
    """Por las dos puertas: el doble clic de la pestaña (JSON) y la edición en
    línea de la portada (formulario)."""
    notas = escena.slot("estudio", "notas")
    pane = slots.abrir(escena.con, notas)
    escena.muestrear()
    indice = api.panel_por_id(escena.con, pane)["window_idx"]

    r = escena.web.post(f"/api/sesion/estudio/ventana/{indice}", json={"nombre": "repaso"}, headers=ORIGEN)
    assert r.json() == {"ok": True}
    assert escena.comprobar()[("estudio", indice)] == [f"slot {notas}"]

    escena.web.post("/panel/accion", data={"pane_id": pane, "accion": "renombrar_ventana",
                                           "nombre": "repaso final"},
                    headers=ORIGEN, follow_redirects=False)
    assert escena.comprobar()[("estudio", indice)] == [f"slot {notas}"]
    assert [v["nombre"] for v in escena.ventanas("estudio")] == ["repaso final"]


def test_pulsar_cada_ventana_de_un_slot_abre_esa_y_no_la_primera(escena):
    """11-nov: «no importa qué nombre le dé, me lleva siempre a la primera».
    Con nombres puestos a mano y en el orden en que se pulsan."""
    notas = escena.slot("estudio", "notas")
    slots.abrir(escena.con, notas)
    escena.muestrear()
    for _ in range(2):
        escena.web.post("/api/sesion/estudio/ventanas", json={"slot": notas}, headers=ORIGEN)
    indices = [v["indice"] for v in escena.ventanas("estudio")]
    for i, nombre in zip(indices, ("uno", "dos", "tres")):
        escena.web.post(f"/api/sesion/estudio/ventana/{i}", json={"nombre": nombre}, headers=ORIGEN)
    escena.comprobar()

    for indice in reversed(indices):
        ctx = api.contexto_trabajo(escena.con, None, "estudio", indice)
        assert (ctx["session"], ctx["ventana"]) == ("estudio", indice)
        assert ctx["slot"]["id"] == notas
        # Y entrando por el slot con la ventana pedida (C-0242).
        ctx = api.contexto_trabajo(escena.con, notas, "estudio", indice)
        assert ctx["ventana"] == indice


# --------------------------------------------------------------------------- #
# Cerrar
# --------------------------------------------------------------------------- #


def test_cerrar_una_ventana_quita_solo_la_suya_y_el_slot_sigue(escena):
    notas = escena.slot("estudio", "notas")
    slots.abrir(escena.con, notas)
    escena.muestrear()
    escena.web.post("/api/sesion/estudio/ventanas", json={"slot": notas}, headers=ORIGEN)
    escena.web.post("/api/sesion/estudio/ventanas", json={"nombre": "suelta"}, headers=ORIGEN)
    antes = escena.comprobar()
    segunda = sorted(i for (_, i), s in antes.items() if s == [f"slot {notas}"])[1]
    panel = next(p for p in api.paneles_abiertos(escena.con) if p["window_idx"] == segunda)

    r = escena.web.post(f"/api/sesion/estudio/ventana/{segunda}",
                        json={"accion": "cerrar", "pane_id": panel["pane_id"],
                              "servidor": api.snapshot_actual(escena.con)["server_pid"]},
                        headers=ORIGEN)
    assert r.json() == {"ok": True, "aviso": ""}

    despues = escena.comprobar()
    assert despues == {k: v for k, v in antes.items() if k != ("estudio", segunda)}
    assert api.obtener_slot(escena.con, notas)["status"] == "activo"


# --------------------------------------------------------------------------- #
# Lo que no se cumplía (C-0425, C-0426)
# --------------------------------------------------------------------------- #


def test_una_ventana_partida_con_un_panel_atado_no_sale_tambien_en_la_bandeja_de_la_portada(escena):
    """C-0425: la portada contaba paneles sin slot y «Sin organizar» ventanas
    sin ninguno; ahora las dos leen la misma regla (`api._ventanas_atadas`)."""
    notas = escena.slot("estudio", "notas")
    pane = slots.abrir(escena.con, notas)
    # Quien la usa la parte con el atajo de tmux: el hub no tiene puerta para esto.
    tmux._correr(["split-window", "-d", "-t", pane, "cat"])
    sitios = escena.comprobar()
    indice = api.panel_por_id(escena.con, pane)["window_idx"]
    assert sitios[("estudio", indice)] == [f"slot {notas}"]

    en_la_portada = {(p["session"], p["window_idx"]) for p in api.bandeja(escena.con)}
    assert ("estudio", indice) not in en_la_portada


def test_abrir_un_slot_en_una_sesion_nueva_no_la_pone_en_sin_organizar_antes_de_muestrear(escena):
    """C-0426: las rutas de la web muestreaban tras abrir; el secretario
    (`abrir_slot`), el orquestador y los agentes de encargos, que abren por
    `slots.abrir` a secas, no, y una sesión nueva salía hasta 20 s en «Sin
    organizar» (fila `desconocida`). Ahora muestrea la puerta."""
    notas = escena.slot("estudio", "notas")
    slots.abrir(escena.con, notas)
    escena.muestrear()

    caja = escena.slot("tienda", "caja")
    slots.abrir(escena.con, caja)   # sesión nueva, «tienda», sin muestrear a mano

    assert "sin organizar" not in escena.sitios().get(("tienda", None), [])
    [indice] = [v["indice"] for v in escena.ventanas("tienda")]
    assert escena.donde("tienda", indice) == [f"slot {caja}"]


def test_lanzar_desde_la_web_muestrea_una_vez_y_no_dos(escena, monkeypatch):
    """La muestra la toma `slots.abrir` (C-0426); la ruta ya no repite la
    suya: dos muestras seguidas en cada «Lanzar» son trabajo de más en el
    latido rápido (regla 14)."""
    vueltas = []
    original = snapshotter.capturar
    monkeypatch.setattr(snapshotter, "capturar", lambda con, a: vueltas.append(1) or original(con, a))
    slot = escena.slot("estudio", "notas")
    r = escena.web.post(f"/slot/{slot}/abrir", data={"proyecto_id": "estudio"},
                        headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303 and "aviso" not in r.headers["location"]
    assert len(vueltas) == 1
    escena.web.post("/api/sesion/estudio/ventanas", json={"slot": slot}, headers=ORIGEN)
    assert len(vueltas) == 2


# --------------------------------------------------------------------------- #
# Cerrar las shells sin usar (C-0352)
# --------------------------------------------------------------------------- #


def test_las_shells_recien_nacidas_se_ofrecen_y_cerrar_las_marcadas_quita_solo_esas(escena, monkeypatch):
    """Con tmux de verdad: cada ventana nace con el servidor y, sin tocar,
    se ofrece. La del slot se da por usada (su actividad, después del
    margen): no se ofrece y, aunque llegue marcada, no se cierra. Cerrar las
    marcadas va por la puerta de siempre, una muestra al final, y no toca las
    demás ni el slot.

    (Aquí la del slot es «sh» para tmux —con `/bin/sh` de `SHELL`, ve la
    shell que envuelve a `cat`—, pero no está en reposo: lleva `-c` y un
    hijo. Se da además por usada, para probar la actividad.)"""
    notas = escena.slot("estudio", "notas")
    slots.abrir(escena.con, notas)
    for nombre in ("una", "dos"):
        escena.web.post("/api/sesion/estudio/ventanas", json={"nombre": nombre}, headers=ORIGEN)
    escena.muestrear()
    por_nombre = {v["nombre"]: v["indice"] for v in escena.ventanas("estudio")}
    leer = tmux.actividad_de_ventanas
    arranque, en_vivo = leer()
    assert arranque and set(en_vivo) == {("estudio", i) for i in por_nombre.values()}
    assert all(arranque <= v["actividad"] <= arranque + api.MARGEN_DEL_ARRANQUE for v in en_vivo.values())
    assert all(p["pid"] > 0 and p["pane_id"].startswith("%") for v in en_vivo.values() for p in v["paneles"])
    usada = ("estudio", por_nombre["notas"])

    def con_la_del_slot_usada():
        arranque, en_vivo = leer()
        en_vivo[usada]["actividad"] = arranque + api.MARGEN_DEL_ARRANQUE + 1
        return arranque, en_vivo
    monkeypatch.setattr(tmux, "actividad_de_ventanas", con_la_del_slot_usada)
    quietas = api.shells_quietas(escena.con, api.paneles_abiertos(escena.con))["ventanas"]
    assert sorted(v["ventana"] for v in quietas) == sorted([por_nombre["una"], por_nombre["dos"]])
    una = next(v["pane_id"] for v in quietas if v["ventana"] == por_nombre["una"])
    del_slot = api.paneles_de_slot(escena.con, notas)[0]["pane_id"]

    vueltas = []
    original = snapshotter.un_ciclo
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda con: vueltas.append(1) or original(con))
    r = escena.web.post("/trabajo/cerrar-quietas", headers=ORIGEN, follow_redirects=False,
                        data={"pane_id": [una, del_slot],
                              "servidor": str(api.snapshot_actual(escena.con)["server_pid"])})
    assert r.status_code == 303
    from urllib.parse import unquote
    aviso = unquote(r.headers["location"])
    assert "1 ventana cerrada." in aviso and "1 ya no estaba sin usar" in aviso and "no se tocó" in aviso
    assert len(vueltas) == 1

    restantes = {v["nombre"] for v in escena.ventanas("estudio")}
    assert restantes == {"notas", "dos"}
    escena.comprobar()
    assert api.obtener_slot(escena.con, notas)["status"] == "activo"


def test_cerrar_las_quietas_sin_marcar_ninguna_lo_dice_y_no_cierra_nada(escena):
    slots.abrir(escena.con, escena.slot("estudio", "notas"))
    escena.web.post("/api/sesion/estudio/ventanas", json={"nombre": "una"}, headers=ORIGEN)
    r = escena.web.post("/trabajo/cerrar-quietas", headers=ORIGEN, follow_redirects=False,
                        data={"servidor": "1"})
    assert r.status_code == 303 and "aviso=" in r.headers["location"]
    assert len(escena.ventanas("estudio")) == 2


# --------------------------------------------------------------------------- #
# Lo que deja una tarea del orquestador (C-0351)
# --------------------------------------------------------------------------- #


def _tarea_que_abrio(escena, estado: str, *slots_abiertos: int, fija: dict | None = None) -> str:
    """Una tarea del orquestador con los slots que «abrió», como los apunta
    `abrir_sesion` en `abiertas`. Sin orquestador ni Claude: sólo su ficha."""
    from hub import orquestador as orq
    tarea_id = orq.crear("revisa estudio")
    with orq.editar(tarea_id) as t:
        t["estado"] = estado
        t["abiertas"] = [{"proyecto": "estudio", "pane_id": "%0", "ruta": str(escena.raiz),
                          "nombre": api.obtener_slot(escena.con, s)["nombre"], "slot_id": s,
                          "cuando": "2026-11-05T10:00:00+00:00"} for s in slots_abiertos]
        if fija:
            t["sesion_fija"] = fija
    return tarea_id


def test_una_tarea_cerrada_enseña_lo_que_dejo_abierto_y_ofrece_recogerlo(escena):
    """HER-04: cada tarea dejaba su slot y sus ventanas para siempre. Se
    enseña en la tarea, con un botón suyo y su confirmación; nada solo."""
    from hub import orquestador as orq
    orq_slot = escena.slot("estudio", "orq-1")
    slots.abrir(escena.con, orq_slot)
    escena.web.post("/api/sesion/estudio/ventanas", json={"slot": orq_slot}, headers=ORIGEN)
    tarea = _tarea_que_abrio(escena, "terminada", orq_slot)

    restos = api.restos_de_tarea(escena.con, orq.cargar(tarea))
    assert [r["id"] for r in restos["slots"]] == [orq_slot]
    assert restos["ventanas"] == 2 and restos["activos"] == 1

    html = escena.web.get(f"/orquestador?tarea={tarea}").text
    bloque = html[html.index('id="restos"'):]
    bloque = bloque[:bloque.index("</form>")]
    assert "orq-1" in bloque and "2 ventanas" in bloque
    assert 'action="/orquestador/cerrar-restos"' in bloque and "data-confirmar=" in bloque
    assert bloque.count('name="pane_id"') == 2
    assert f'name="servidor" value="{restos["servidor"]}"' in bloque


def test_recoger_lo_de_una_tarea_cierra_sus_ventanas_archiva_su_slot_y_no_toca_lo_demas(escena):
    from hub import orquestador as orq
    suyo = escena.slot("estudio", "notas")
    slots.abrir(escena.con, suyo)
    orq_slot = escena.slot("estudio", "orq-1")
    slots.abrir(escena.con, orq_slot)
    escena.web.post("/api/sesion/estudio/ventanas", json={"slot": orq_slot}, headers=ORIGEN)
    tarea = _tarea_que_abrio(escena, "detenida", orq_slot)
    restos = api.restos_de_tarea(escena.con, orq.cargar(tarea))

    r = escena.web.post("/orquestador/cerrar-restos", headers=ORIGEN, follow_redirects=False, data={
        "tarea_id": tarea, "servidor": str(restos["servidor"]),
        "pane_id": [v["pane_id"] for s in restos["slots"] for v in s["ventanas"]]})
    assert r.status_code == 303

    assert api.paneles_de_slot(escena.con, orq_slot) == []
    assert api.obtener_slot(escena.con, orq_slot)["status"] == "archivado"
    assert api.obtener_slot(escena.con, suyo)["status"] == "activo"
    assert list(escena.comprobar().values()) == [[f"slot {suyo}"]]
    assert api.restos_de_tarea(escena.con, orq.cargar(tarea))["slots"] == []


def test_con_la_tarea_viva_no_se_recoge_nada(escena):
    from hub import orquestador as orq
    orq_slot = escena.slot("estudio", "orq-1")
    slots.abrir(escena.con, orq_slot)
    tarea = _tarea_que_abrio(escena, "activa", orq_slot)
    escena.muestrear()
    [panel] = api.paneles_de_slot(escena.con, orq_slot)

    assert api.orquestador(escena.con, tarea)["detalle"]["restos"] is None
    r = escena.web.post("/orquestador/cerrar-restos", headers=ORIGEN, follow_redirects=False, data={
        "tarea_id": tarea, "servidor": str(api.snapshot_actual(escena.con)["server_pid"]),
        "pane_id": [panel["pane_id"]]})
    assert r.status_code == 303 and "aviso=" in r.headers["location"]
    assert api.paneles_de_slot(escena.con, orq_slot) != []
    assert api.obtener_slot(escena.con, orq_slot)["status"] == "activo"
    assert orq.cargar(tarea)["estado"] == "activa"


def test_ni_la_sesion_fija_del_tablero_ni_una_ventana_ajena_se_recogen(escena):
    """La fija se reutiliza en la tarea siguiente: no es de ésta. Y un
    `pane_id` que no es de sus slots no se cierra aunque llegue en el
    formulario."""
    from hub import orquestador as orq
    fija = escena.slot("estudio", "Tablero")
    slots.abrir(escena.con, fija)
    suyo = escena.slot("estudio", "notas")
    pane_suyo = slots.abrir(escena.con, suyo)
    tarea = _tarea_que_abrio(escena, "terminada", fija,
                             fija={"proyecto": "estudio", "nombre": "Tablero", "ruta": str(escena.raiz)})
    assert api.restos_de_tarea(escena.con, orq.cargar(tarea))["slots"] == []

    escena.web.post("/orquestador/cerrar-restos", headers=ORIGEN, follow_redirects=False, data={
        "tarea_id": tarea, "servidor": str(api.snapshot_actual(escena.con)["server_pid"]),
        "pane_id": [pane_suyo]})
    assert api.paneles_de_slot(escena.con, suyo) != []
    assert api.obtener_slot(escena.con, fija)["status"] == "activo"


def _viva_que_espera_a(pane_id: str, *slots_abiertos: int) -> str:
    """La tarea en curso, esperando la respuesta de ese panel: lo que deja
    `orquestador.mandar` cuando reutiliza la sesión que ya hay en el proyecto."""
    from hub import orquestador as orq
    viva = orq.crear("sigue en estudio")
    with orq.editar(viva) as t:
        t["estado"] = orq.ESPERANDO_SESION
        t["esperas"] = [{"id": 1, "tipo": "respuesta", "proyecto": "estudio", "pane_id": pane_id,
                         "enviado": "2026-11-13T10:00:00+00:00", "visto_trabajando": True,
                         "avisado_tope": False, "estado": "esperando"}]
        t["abiertas"] = [{"proyecto": "estudio", "pane_id": pane_id, "ruta": "/", "nombre": "x",
                          "slot_id": s, "cuando": "2026-11-13T10:00:00+00:00"} for s in slots_abiertos]
    assert orq.viva()["id"] == viva
    return viva


def test_lo_que_usa_la_tarea_en_curso_no_es_resto_de_la_cerrada_ni_se_recoge(escena):
    """Revisión cruzada de C-0351: `abrir_sesion` hace que la tarea siguiente
    reutilice la sesión que ya hay en el proyecto, así que el slot `orq-…` de
    la cerrada suele ser el panel donde trabaja la viva. Recoger los restos de
    la cerrada lo mataba y archivaba su slot. Se enseña como «lo usa la tarea
    en curso», sin botón, y la ruta lo vuelve a mirar al cerrar."""
    from urllib.parse import unquote

    from hub import orquestador as orq
    orq_slot = escena.slot("estudio", "orq-1")
    slots.abrir(escena.con, orq_slot)
    otro = escena.slot("estudio", "orq-2")
    slots.abrir(escena.con, otro)
    cerrada = _tarea_que_abrio(escena, "terminada", orq_slot, otro)
    [panel] = api.paneles_de_slot(escena.con, orq_slot)
    pintado = api.restos_de_tarea(escena.con, orq.cargar(cerrada))
    _viva_que_espera_a(panel["pane_id"])

    restos = api.restos_de_tarea(escena.con, orq.cargar(cerrada))
    en_uso = {s["id"]: s["en_uso"] for s in restos["slots"]}
    assert en_uso == {orq_slot: True, otro: False}
    assert restos["ventanas"] == 1 and restos["activos"] == 1
    html = escena.web.get(f"/orquestador?tarea={cerrada}").text
    bloque = html[html.index('id="restos"'):html.index("</form>", html.index('id="restos"'))]
    assert "lo usa la tarea en curso" in bloque
    assert f'value="{panel["pane_id"]}"' not in bloque

    # Con la página pintada ANTES de que la viva lo tomara: el formulario lo lleva.
    r = escena.web.post("/orquestador/cerrar-restos", headers=ORIGEN, follow_redirects=False, data={
        "tarea_id": cerrada, "servidor": str(pintado["servidor"]),
        "pane_id": [v["pane_id"] for s in pintado["slots"] for v in s["ventanas"]]})
    aviso = unquote(r.headers["location"])
    assert api.paneles_de_slot(escena.con, orq_slot) != []
    assert api.obtener_slot(escena.con, orq_slot)["status"] == "activo"
    assert "«orq-1»" in aviso and "tarea en curso" in aviso
    assert api.paneles_de_slot(escena.con, otro) == []
    assert api.obtener_slot(escena.con, otro)["status"] == "archivado"


def test_una_shell_en_la_que_se_acaba_de_lanzar_algo_no_se_cierra_aunque_llegue_marcada(escena):
    """Revisión cruzada de C-0352: al cerrar, «es una shell» salía de la
    muestra (hasta 20 s vieja) y, dentro del margen del arranque, el eco de
    teclear no saca la ventana de la lista. Es justo el momento de uso:
    reiniciar, Restaurar, Enter en cada ventana y limpiar. Lo que corre en
    cada panel se lee de tmux en el instante de cerrar."""
    import time
    from urllib.parse import unquote

    slots.abrir(escena.con, escena.slot("estudio", "notas"))
    escena.web.post("/api/sesion/estudio/ventanas", json={"nombre": "una"}, headers=ORIGEN)
    escena.muestrear()
    una = {v["nombre"]: v["indice"] for v in escena.ventanas("estudio")}["una"]
    [quieta] = [v for v in api.shells_quietas(escena.con, api.paneles_abiertos(escena.con))["ventanas"]
                if v["ventana"] == una]
    servidor = str(api.snapshot_actual(escena.con)["server_pid"])

    # Quien la usa lanza algo DESPUÉS de la muestra y antes de pulsar.
    tmux._correr(["send-keys", "-t", quieta["pane_id"], "sleep 300", "Enter"])
    limite = time.monotonic() + 3
    while time.monotonic() < limite and tmux.comando_de_panel(quieta["pane_id"]) != "sleep":
        time.sleep(0.05)
    assert tmux.comando_de_panel(quieta["pane_id"]) == "sleep"

    r = escena.web.post("/trabajo/cerrar-quietas", headers=ORIGEN, follow_redirects=False,
                        data={"pane_id": [quieta["pane_id"]], "servidor": servidor})
    assert "0 ventanas cerradas" in unquote(r.headers["location"])
    assert una in {v["indice"] for v in escena.ventanas("estudio")}


def test_una_ventana_que_corre_un_guion_no_cuenta_como_shell_sin_usar(escena):
    """Revisión cruzada de C-0352: con `sh x.sh` (o un comando compuesto)
    tmux dice `sh`, y dentro del margen la ventana salía como «sin usar»,
    aunque el guion esté esperando algo: la cifra se inflaba (regla 13). Sólo
    cuenta la shell a secas y sin nada debajo; la que sí lo es, se sigue
    ofreciendo."""
    guion = escena.raiz / "espera.sh"
    guion.write_text("read x\n", encoding="utf-8")
    slots.abrir(escena.con, escena.slot("estudio", "notas"))
    tmux.nueva_ventana("estudio", str(escena.raiz), "guion", f"sh {guion}")
    escena.web.post("/api/sesion/estudio/ventanas", json={"nombre": "a secas"}, headers=ORIGEN)
    escena.muestrear()
    por_nombre = {v["nombre"]: v["indice"] for v in escena.ventanas("estudio")}
    assert tmux.comando_de_panel(api.paneles_abiertos(escena.con)[0]["pane_id"]) in tmux.SHELLS

    quietas = {v["ventana"] for v in api.shells_quietas(escena.con, api.paneles_abiertos(escena.con))["ventanas"]}
    assert por_nombre["guion"] not in quietas and por_nombre["notas"] not in quietas
    assert quietas == {por_nombre["a secas"]}


def test_abrir_toma_solo_la_muestra_sin_barrer_espejos_ni_releer_el_registro(escena, monkeypatch):
    """Revisión cruzada de C-0426: con el `un_ciclo` entero, abrir un slot
    llevaba a `hub-secretario`, `hub-encargos` y `./orq` el barrido de
    espejos y la relectura del registro, cuyo `stat` sobre el disco de Windows
    es justo lo que se cuelga (regla dura 2). Sólo la muestra: de quién es
    cada ruta sale del índice."""
    from hub import conexiones, registry, terminal
    llamadas = []
    monkeypatch.setattr(registry, "cargar", lambda *a, **k: llamadas.append("registro") or [])
    monkeypatch.setattr(registry, "sincronizar", lambda *a, **k: llamadas.append("sincronizar"))
    monkeypatch.setattr(conexiones, "sincronizar", lambda *a, **k: llamadas.append("conexiones"))
    monkeypatch.setattr(terminal, "limpiar_espejos_huerfanos", lambda *a, **k: llamadas.append("espejos") or [])

    caja = escena.slot("tienda", "caja")
    slots.abrir(escena.con, caja)   # sesión nueva, sin muestrear a mano

    assert llamadas == []
    [indice] = [v["indice"] for v in escena.ventanas("tienda")]
    assert escena.donde("tienda", indice) == [f"slot {caja}"]
    assert api.panel_por_id(escena.con, api.paneles_de_slot(escena.con, caja)[0]["pane_id"])["proyecto_id"] == "tienda"
