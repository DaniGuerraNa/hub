"""Las rutas POST que ningún test llamaba, cada una con su caso de error (C-0103).

La auditoría del 3-nov encontró una veintena: funcionaban, pero nada lo
decía, y partir `web.py` (164) sin ellas es mover código que nadie vigila.
Aquí se llama a cada una por HTTP con el arnés de Starlette y los datos
aislados de `conftest.py`.

Lo externo —git, docker, tmux, la red— se finge en el módulo **dueño**, no en
`web.py`: así, si una ruta se salta su puerta, el test lo nota. Donde la puerta
lanzaría un agente (crear un proyecto, sembrar la capa base), se finge la
puerta misma y se comprueba lo que la ruta le pasa, que es lo único suyo.
"""

from __future__ import annotations

import inspect
import io
import re
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

from hub import (agentes, canal, config, db, ideas, orquestador, registry,
                 repos, servicios, slots, snapshotter, tmux, web)
from hub.registry import Atribuidor

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf000000030101001899f05e"
    "0000000049454e44ae426082")


@pytest.fixture
def cliente():
    return TestClient(web.app)


@pytest.fixture
def con():
    """La base del hub de esta prueba: la misma que abre la app (`config.DB_PATH`)."""
    c = db.abrir()
    yield c
    c.close()


@pytest.fixture
def demo(con, tmp_path):
    """Un proyecto con carpeta y un slot, dados de alta por sus puertas."""
    asiento = tmp_path / "demo"
    asiento.mkdir()
    registry.añadir_proyecto({"id": "demo", "nombre": "Demo", "asiento": str(asiento),
                              "guardrail": "ask"})
    registry.sincronizar(con, registry.cargar())
    slot = slots.crear(con, "demo", "Formulario", ruta=str(asiento))
    return {"asiento": asiento, "slot": slot}


def _post(cliente, url, **kw):
    return cliente.post(url, follow_redirects=False, **kw)


def _destino(r) -> tuple[str, str]:
    """A dónde vuelve una redirección, y el aviso que lleva."""
    assert r.status_code == 303, (r.status_code, r.text[:300])
    partes = urlsplit(r.headers["location"])
    aviso = parse_qs(partes.query).get("aviso", [""])[0]
    return partes.path, unquote(aviso)


# ── Tablero ──────────────────────────────────────────────────────────────────

def test_adjuntar_a_una_idea_la_guarda_y_vuelve_al_tablero(cliente, con):
    idea = ideas.apuntar(con, "Una idea con captura")
    r = _post(cliente, f"/tablero/idea/{idea}/adjuntar",
              files={"archivos": ("captura.png", io.BytesIO(_PNG), "image/png")})
    assert _destino(r) == ("/tablero", "Adjuntado")
    assert [a["nombre"] for a in ideas.adjuntos(idea)] == [f"_tablero/{idea}/captura.png"]


def test_adjuntar_a_una_idea_que_no_existe_dice_por_que_no_entro(cliente):
    r = _post(cliente, "/tablero/idea/999/adjuntar",
              files={"archivos": ("captura.png", io.BytesIO(_PNG), "image/png")})
    camino, aviso = _destino(r)
    assert camino == "/tablero" and "no hay ninguna idea 999" in aviso


# ── Respaldo, servicios e inventario: reescanear ─────────────────────────────

def test_reescanear_el_respaldo_mide_y_vuelve_a_su_pantalla_sin_aviso(cliente, demo, monkeypatch):
    medidos = []
    monkeypatch.setattr(repos, "escanear", lambda con, proyectos: medidos.append(
        [p.id for p in proyectos]))
    r = _post(cliente, "/respaldo/escanear")
    assert r.status_code == 303 and r.headers["location"] == "/respaldo"
    assert medidos == [["demo"]]


def test_si_git_no_deja_medir_el_respaldo_lo_dice_en_vez_de_enseñar_cero(cliente, monkeypatch):
    def falla(con, proyectos):
        raise repos.RespaldoNoMedido("git no responde")
    monkeypatch.setattr(repos, "escanear", falla)
    r = _post(cliente, "/respaldo/escanear")
    assert r.status_code == 303
    assert parse_qs(urlsplit(r.headers["location"]).query)["no_medido"] == ["git no responde"]


def test_reescanear_los_servicios_guarda_lo_que_dice_docker(cliente, con, demo, monkeypatch):
    monkeypatch.setattr(servicios, "listar", lambda: [
        {"nombre": "demo-postgres", "imagen": "postgres", "estado": "running", "detalle": "Up 2h"}])
    assert _destino(_post(cliente, "/servicios/escanear")) == ("/servicios", "")
    assert [f["contenedor"] for f in con.execute("SELECT contenedor FROM servicio")] == ["demo-postgres"]


def test_con_docker_apagado_los_servicios_conservan_lo_ultimo_medido(cliente, con, monkeypatch):
    def apagado():
        raise servicios.NoRespondio("docker no responde")
    monkeypatch.setattr(servicios, "listar", apagado)
    r = _post(cliente, "/servicios/escanear")
    assert r.status_code == 303 and r.headers["location"] == "/servicios?docker=no"


def test_reescanear_el_inventario_recoge_las_capacidades_del_proyecto(cliente, con, demo):
    agentes_ = demo["asiento"] / ".claude" / "agents"
    agentes_.mkdir(parents=True)
    (agentes_ / "revisor.md").write_text("---\nname: revisor\ndescription: Revisa.\n---\n",
                                         encoding="utf-8")
    assert _destino(_post(cliente, "/inventario/escanear", data={"medir": ""})) == ("/inventario", "")
    assert [f["nombre"] for f in con.execute("SELECT nombre FROM capacidad")] == ["revisor"]


def test_medir_el_uso_sin_transcripts_deja_las_capacidades_sin_uso(cliente, con, demo):
    # Sin transcripts: `conftest.py` apunta `HUB_TRANSCRIPTS` a una carpeta que
    # no existe, y `catalogo` la lee (C-0179).
    agentes_ = demo["asiento"] / ".claude" / "agents"
    agentes_.mkdir(parents=True)
    (agentes_ / "revisor.md").write_text("---\nname: revisor\ndescription: Revisa.\n---\n",
                                         encoding="utf-8")
    assert _destino(_post(cliente, "/inventario/escanear", data={"medir": "1"})) == ("/inventario", "")
    assert con.execute("SELECT usado FROM capacidad").fetchone()["usado"] is None


def test_con_el_registro_roto_el_inventario_dice_donde_en_vez_de_un_500(cliente):
    config.projects_yml().write_text("proyectos: [esto no cierra\n", encoding="utf-8")
    r = _post(cliente, "/inventario/escanear", data={"medir": ""})
    assert r.status_code == 422 and "El registro no se puede leer" in r.text


# ── Conexiones ───────────────────────────────────────────────────────────────

def test_una_conexion_nueva_va_al_registro_y_al_indice(cliente, con, demo):
    r = _post(cliente, "/conexiones/nueva", data={
        "alias": "vps-pruebas", "host": "203.0.113.7", "usuario": "deploy",
        "proposito": "pruebas", "referencia_secreto": "~/.ssh/config#vps-pruebas",
        "proyectos": ["demo"]})
    assert _destino(r) == ("/conexiones", "")
    assert [c.alias for c in registry.cargar_conexiones()] == ["vps-pruebas"]
    assert con.execute("SELECT alias FROM conexion").fetchone()["alias"] == "vps-pruebas"


def test_una_conexion_sin_alias_vuelve_con_el_motivo(cliente):
    r = _post(cliente, "/conexiones/nueva", data={"alias": "", "host": "h"})
    assert r.status_code == 303
    partes = urlsplit(r.headers["location"])
    assert partes.path == "/conexiones" and parse_qs(partes.query)["error"][0]
    assert registry.cargar_conexiones() == []


# ── Orquestador ──────────────────────────────────────────────────────────────

def test_detener_una_tarea_en_cola_la_detiene_sin_tocar_ningun_panel(cliente, monkeypatch):
    monkeypatch.setattr(tmux, "tecla_en_panel", lambda *a: pytest.fail("no debía pulsar nada"))
    tarea = orquestador.crear("para luego")
    r = _post(cliente, "/orquestador/detener", data={"tarea_id": tarea})
    camino, aviso = _destino(r)
    assert camino == "/orquestador" and aviso == "Detenida."
    assert orquestador.cargar(tarea)["estado"] == orquestador.DETENIDA


def test_detener_dos_veces_dice_que_ya_estaba_detenida(cliente):
    tarea = orquestador.crear("para luego")
    orquestador.detener(tarea)
    _, aviso = _destino(_post(cliente, "/orquestador/detener", data={"tarea_id": tarea}))
    assert aviso.startswith("No se detuvo: ya estaba")


def test_detener_una_tarea_que_no_existe_no_rompe(cliente):
    _, aviso = _destino(_post(cliente, "/orquestador/detener", data={"tarea_id": "t-no-existe"}))
    assert aviso.startswith("No se detuvo")


# ── Componentes ──────────────────────────────────────────────────────────────

def test_preparar_un_componente_abre_su_ventana_con_el_encargo_sin_enter(cliente, tmp_path, monkeypatch):
    (tmp_path / "laboratorio-que-no-existe").mkdir()
    abiertas = []

    def abrir_en(ruta, nombre, sesion, comando):
        abiertas.append((ruta, nombre, sesion))
        return "%9"
    monkeypatch.setattr(slots, "abrir_en", abrir_en)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [{"pane_id": "%9", "window_idx": 4}])
    r = _post(cliente, "/api/componentes/preparar", json={"nombre": "navegante"}).json()
    assert r == {"ok": True, "session": "hub", "ventana": 4}
    assert abiertas == [(str(tmp_path / "laboratorio-que-no-existe"), "preparar-navegador-lab", "hub")]


def test_preparar_un_componente_que_no_existe_lo_dice(cliente):
    r = _post(cliente, "/api/componentes/preparar", json={"nombre": "otro"}).json()
    assert r["ok"] is False and "no hay ningún componente" in r["error"]


def test_preparar_un_componente_que_no_esta_en_el_clon_lo_dice(cliente):
    r = _post(cliente, "/api/componentes/preparar", json={"nombre": "navegante"}).json()
    assert r["ok"] is False and "no está en" in r["error"]


# ── Canal de consulta ────────────────────────────────────────────────────────

def test_el_tutorial_se_encola_para_alguien_activo(cliente, con):
    canal.anotar_contacto(con, 77, "alguien", "Alguien")
    canal.editar_usuario(con, 77, estado="activo")
    assert _destino(_post(cliente, "/canal/tutorial", data={"user_id": "77"})) == ("/canal", "")
    assert canal.ver_usuario(con, 77)["tutorial"] == "pedido"


def test_el_tutorial_no_se_encola_para_quien_no_esta_aprobado(cliente, con):
    canal.anotar_contacto(con, 78, "otro", "Otro")
    r = _post(cliente, "/canal/tutorial", data={"user_id": "78"})
    assert r.status_code == 303 and "apru%C3%A9balo" in r.headers["location"]
    assert canal.ver_usuario(con, 78)["tutorial"] != "pedido"


@pytest.mark.parametrize("ruta", ["/canal/tutorial", "/canal/usuario", "/canal/permiso",
                                  "/encargos/persona", "/encargos/crear"])
def test_un_user_id_que_no_es_un_numero_se_dice_en_castellano(cliente, ruta):
    """C-0176: la pantalla enseñaba «invalid literal for int() with base 10»."""
    r = _post(cliente, ruta, data={"user_id": "ana", "encargo_id": "x", "proyecto_id": "x",
                                   "accion": "x"})
    assert r.status_code == 303
    error = parse_qs(urlsplit(r.headers["location"]).query)["error"][0]
    assert "invalid literal" not in error
    assert "número" in error and "«ana»" in error


# ── Lanzar agentes: la capa base, proyectos y kits nuevos, preparar kits ────

def test_sembrar_la_capa_base_sin_prompt_usa_el_que_propone_el_hub(cliente, con, demo, monkeypatch):
    lanzados = []

    def lanzar(con_, proyecto_id, prompt, nombre_ventana="agente", **kw):
        lanzados.append((proyecto_id, prompt, nombre_ventana))
        return {"session": "demo", "ventana": 2}
    monkeypatch.setattr(agentes, "lanzar", lanzar)
    r = _post(cliente, "/api/base/sembrar", json={"proyecto_id": "demo"}).json()
    assert r == {"ok": True, "session": "demo", "ventana": 2}
    ((proyecto, prompt, ventana),) = lanzados
    assert proyecto == "demo" and ventana == "capa-base" and prompt.strip()


def test_sembrar_la_capa_base_con_guardrail_never_se_niega(cliente, con, demo):
    con.execute("UPDATE proyecto SET guardrail='never' WHERE id='demo'")
    r = _post(cliente, "/api/base/sembrar", json={"proyecto_id": "demo", "prompt": "x"}).json()
    assert r["ok"] is False and r["bloqueado"] is True


def test_sembrar_la_capa_base_de_un_proyecto_que_no_existe_lo_dice(cliente):
    r = _post(cliente, "/api/base/sembrar", json={"proyecto_id": "nadie", "prompt": "x"}).json()
    assert r == {"ok": False, "error": "proyecto desconocido: nadie"}


def test_un_proyecto_nuevo_entra_por_su_puerta_con_las_rutas_partidas(cliente, monkeypatch):
    llamadas = []

    def crear(con_, id_, nombre, ruta, dominio, guardrail, estado_ref, rutas=None):
        llamadas.append((id_, nombre, ruta, dominio, guardrail, estado_ref, rutas))
        return {"proyecto": id_, "session": id_, "ventana": 0}
    monkeypatch.setattr(agentes, "crear_proyecto", crear)
    r = _post(cliente, "/api/proyecto/nuevo", json={
        "id": "tienda", "nombre": "Tienda", "ruta": "/srv/tienda",
        "rutas": "/srv/tienda-api\n\n/srv/tienda-web\n"}).json()
    assert r["ok"] is True and r["proyecto"] == "tienda"
    assert llamadas == [("tienda", "Tienda", "/srv/tienda", "personal", "ask", "ESTADO.md",
                         ["/srv/tienda-api", "/srv/tienda-web"])]


@pytest.mark.parametrize("error,esperado", [
    (agentes.CarpetaOcupada("ya hay algo"), {"ok": False, "ocupada": True, "error": "ya hay algo"}),
    (ValueError("id no válido"), {"ok": False, "error": "id no válido"}),
])
def test_un_proyecto_nuevo_que_no_se_puede_crear_dice_por_que(cliente, monkeypatch, error, esperado):
    def crear(*a, **kw):
        raise error
    monkeypatch.setattr(agentes, "crear_proyecto", crear)
    assert _post(cliente, "/api/proyecto/nuevo", json={"id": "x"}).json() == esperado


def test_un_proyecto_nuevo_con_guardrail_never_se_crea_vacio_y_sin_agente(cliente, tmp_path, monkeypatch):
    """Por la puerta de verdad: con `never`, `lanzar` se niega antes de tocar tmux."""
    monkeypatch.setattr(tmux, "_correr", lambda *a, **kw: pytest.fail("no debía llegar a tmux"))
    r = _post(cliente, "/api/proyecto/nuevo", json={
        "id": "cerrado", "nombre": "Cerrado", "ruta": str(tmp_path / "cerrado"),
        "guardrail": "never"}).json()
    assert r["ok"] is True and r["agente"] is False and "never" in r["aviso"]
    assert [p.id for p in registry.cargar()] == ["cerrado"]
    assert (tmp_path / "cerrado").is_dir()


def test_un_proyecto_nuevo_sin_datos_lo_rechaza_la_puerta_de_verdad(cliente):
    r = _post(cliente, "/api/proyecto/nuevo", json={}).json()
    assert r["ok"] is False and r["error"]


def test_un_kit_nuevo_entra_por_su_puerta(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setattr(agentes, "crear_kit", lambda con_, *a: (llamadas.append(a), {"kit": a[0]})[1])
    r = _post(cliente, "/api/kit/nuevo", json={"id": "avisos", "nombre": "Avisos",
                                                "ruta": "/srv/kit-avisos"}).json()
    assert r == {"ok": True, "kit": "avisos"}
    assert llamadas == [("avisos", "Avisos", "/srv/kit-avisos", "ask")]


def test_un_kit_nuevo_sin_datos_lo_rechaza_la_puerta_de_verdad(cliente):
    r = _post(cliente, "/api/kit/nuevo", json={}).json()
    assert r["ok"] is False and r["error"]


def test_preparar_kits_abre_la_ventana_del_proyecto_con_el_encargo(cliente, con, demo, monkeypatch):
    from hub import kits
    abiertas = []

    def abrir_en(ruta, nombre, sesion, comando):
        abiertas.append((ruta, nombre, sesion, comando))
        return "%7"
    monkeypatch.setattr(slots, "abrir_en", abrir_en)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [{"pane_id": "%7", "window_idx": 2}])
    kit = sorted(kits.catalogo())[0]
    r = _post(cliente, "/api/kits/preparar", json={"proyecto": "demo", "kits": [kit, kit]}).json()
    assert r["ok"] is True and r["kits"] == [kit] and r["ventana"] == 2
    ((ruta, nombre, _sesion, comando),) = abiertas
    assert (ruta, nombre) == (str(demo["asiento"]), "kits") and kit in comando


def test_preparar_kits_que_no_estan_en_el_catalogo_lo_dice(cliente, demo, monkeypatch):
    monkeypatch.setattr(slots, "abrir_en", lambda *a: pytest.fail("no debía abrir nada"))
    r = _post(cliente, "/api/kits/preparar", json={"proyecto": "demo", "kits": ["no-existe"]}).json()
    assert r["ok"] is False and "no están en el catálogo: no-existe" in r["error"]


def test_preparar_kits_en_un_proyecto_que_no_existe_lo_dice(cliente):
    r = _post(cliente, "/api/kits/preparar", json={"proyecto": "nadie", "kits": ["k"]}).json()
    assert r["ok"] is False and "nadie" in r["error"]


def test_preparar_kits_con_guardrail_never_se_niega(cliente, con, demo):
    con.execute("UPDATE proyecto SET guardrail='never' WHERE id='demo'")
    r = _post(cliente, "/api/kits/preparar", json={"proyecto": "demo", "kits": ["k"]}).json()
    assert r["ok"] is False and r["bloqueado"] is True


# ── Actualizaciones ──────────────────────────────────────────────────────────

def test_comprobar_versiones_apagado_lo_dice(cliente):
    """`HUB_BUSCAR_VERSIONES=0` en la suite: no se sale a internet."""
    _, aviso = _destino(_post(cliente, "/actualizaciones/comprobar"))
    assert aviso.startswith("No se buscan versiones")


@pytest.mark.parametrize("respuesta,empieza", [
    ({"ultima": "0.5.0"}, "Comprobado: la última publicada es la 0.5.0"),
    ({"error": "sin red"}, "No se pudo mirar: sin red"),
])
def test_comprobar_versiones_dice_lo_que_encontro(cliente, monkeypatch, respuesta, empieza):
    from hub import version
    monkeypatch.setattr(version, "buscar_remota", lambda **kw: respuesta)
    _, aviso = _destino(_post(cliente, "/actualizaciones/comprobar"))
    assert aviso.startswith(empieza)


# ── Ventanas de tmux desde la barra de trabajo ───────────────────────────────

def test_renombrar_va_a_tmux_por_su_nombre_y_cerrar_por_su_panel(cliente, monkeypatch):
    """Cerrar, por el panel y el servidor que trajo la lista de pestañas (396),
    y luego una muestra para que el raíl no la siga enseñando (C-0227)."""
    from hub import snapshotter
    hecho, muestras = [], []
    monkeypatch.setattr(tmux, "_correr", lambda args, **kw: hecho.append(args) or "")
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 42)
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda con: muestras.append(1))
    assert _post(cliente, "/api/sesion/demo/ventana/2", json={"nombre": "logs"}).json() == {"ok": True}
    r = _post(cliente, "/api/sesion/demo/ventana/2",
              json={"accion": "cerrar", "pane_id": "%9", "servidor": 42}).json()
    assert r == {"ok": True, "aviso": ""}
    assert hecho == [["rename-window", "-t", "=demo:2", "logs"], ["kill-window", "-t", "%9"]]
    assert muestras == [1]


def test_cerrar_una_pestana_con_el_servidor_de_antes_lo_dice(cliente, monkeypatch):
    monkeypatch.setattr(tmux, "_correr", lambda *a, **kw: pytest.fail("no debía llegar a tmux"))
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 43)
    r = _post(cliente, "/api/sesion/demo/ventana/2",
              json={"accion": "cerrar", "pane_id": "%9", "servidor": 42}).json()
    assert r["ok"] is False and "recárgala" in r["error"]


def test_un_nombre_de_sesion_que_no_es_valido_no_llega_a_tmux(cliente, monkeypatch):
    monkeypatch.setattr(tmux, "_correr", lambda *a, **kw: pytest.fail("no debía llegar a tmux"))
    r = _post(cliente, "/api/sesion/a;b/ventana/0", json={"accion": "cerrar"}).json()
    assert r["ok"] is False
    r = _post(cliente, "/api/sesion/demo/ventana/0",
              json={"accion": "cerrar", "pane_id": "%1; kill-server", "servidor": 1}).json()
    assert r["ok"] is False


# ── Encargos ─────────────────────────────────────────────────────────────────

def test_implementar_un_encargo_que_no_es_una_maqueta_publicada_lo_dice(cliente, con):
    from hub import encargos
    encargos.crear(con, "panaderia", user_id=1, titulo="Panadería")
    r = _post(cliente, "/encargos/panaderia/implementar")
    partes = urlsplit(r.headers["location"])
    assert r.status_code == 303 and partes.path == "/encargos/panaderia"
    assert "no es una maqueta publicada" in parse_qs(partes.query)["error"][0]


def test_implementar_pasa_el_encargo_a_su_puerta_y_vuelve_a_su_ficha(cliente, con, monkeypatch):
    from hub import implementador
    empezados = []
    monkeypatch.setattr(implementador, "empezar", lambda con_, id_: empezados.append(id_) or {})
    assert _destino(_post(cliente, "/encargos/panaderia/implementar")) == ("/encargos/panaderia", "")
    assert empezados == ["panaderia"]


# ── Slots: editar y cambiar de estado ────────────────────────────────────────

def test_editar_un_slot_guarda_y_vuelve_a_su_proyecto(cliente, con, demo):
    r = _post(cliente, f"/slot/{demo['slot']}/editar", data={
        "proyecto_id": "demo", "nombre": "  Formulario nuevo ", "nota": "sigue", "restaurar": "1"})
    assert _destino(r) == ("/proyecto/demo", "")
    s = con.execute("SELECT nombre, nota, restaurar FROM slot WHERE id=?", (demo["slot"],)).fetchone()
    assert (s["nombre"], s["nota"], s["restaurar"]) == ("Formulario nuevo", "sigue", 1)


def test_mover_un_slot_a_otro_proyecto_lleva_a_ese_proyecto(cliente, con, demo, tmp_path):
    otro = tmp_path / "otro"
    otro.mkdir()
    registry.añadir_proyecto({"id": "otro", "nombre": "Otro", "asiento": str(otro)})
    registry.sincronizar(con, registry.cargar())
    r = _post(cliente, f"/slot/{demo['slot']}/editar", data={
        "proyecto_id": "demo", "nombre": "Formulario", "mover_a": "otro"})
    assert _destino(r) == ("/proyecto/otro", "")
    assert con.execute("SELECT proyecto_id FROM slot WHERE id=?", (demo["slot"],)).fetchone()[0] == "otro"


def test_mover_un_slot_a_un_proyecto_que_no_existe_vuelve_con_el_motivo_y_no_lo_toca(cliente, con, demo):
    """Daba 503 «el índice del hub no se puede leer»: la clave ajena saltaba
    como `IntegrityError` y caía en el manejador de base ilegible."""
    r = _post(cliente, f"/slot/{demo['slot']}/editar", data={
        "proyecto_id": "demo", "nombre": "Otro nombre", "mover_a": "no-existe"})
    assert _destino(r) == ("/proyecto/demo", "No se guardó: no hay ningún proyecto «no-existe»")
    s = con.execute("SELECT proyecto_id, nombre FROM slot WHERE id=?", (demo["slot"],)).fetchone()
    assert tuple(s) == ("demo", "Formulario")


def test_editar_sin_nombre_lo_rechaza_el_formulario(cliente, demo):
    assert _post(cliente, f"/slot/{demo['slot']}/editar", data={"proyecto_id": "demo"}).status_code == 422


@pytest.mark.parametrize("accion,estado", [("archivar", "archivado"), ("desarchivar", "activo")])
def test_archivar_y_desarchivar_cambian_el_estado_y_vuelven_al_destino(cliente, con, demo, accion, estado):
    r = _post(cliente, f"/slot/{demo['slot']}/estado",
              data={"accion": accion, "proyecto_id": "demo", "destino": "/trabajo"})
    assert _destino(r) == ("/trabajo", "")
    assert con.execute("SELECT status FROM slot WHERE id=?", (demo["slot"],)).fetchone()[0] == estado


def test_borrar_un_slot_lo_quita_y_vuelve_a_la_ficha(cliente, con, demo):
    r = _post(cliente, f"/slot/{demo['slot']}/estado", data={"accion": "borrar", "proyecto_id": "demo"})
    assert _destino(r) == ("/proyecto/demo", "")
    assert con.execute("SELECT 1 FROM slot WHERE id=?", (demo["slot"],)).fetchone() is None


def test_una_accion_de_estado_desconocida_no_toca_el_slot(cliente, con, demo):
    _post(cliente, f"/slot/{demo['slot']}/estado", data={"accion": "volar", "proyecto_id": "demo"})
    assert con.execute("SELECT status FROM slot WHERE id=?", (demo["slot"],)).fetchone()[0] == "activo"


# ── Bandeja: lo oculto, y el aviso de sesión perdida ─────────────────────────

def test_mostrar_devuelve_a_la_bandeja_solo_la_ventana_pedida(cliente, con):
    slots.ocultar(con, "logs", 3)
    slots.ocultar(con, "logs")
    r = _post(cliente, "/oculto/mostrar", data={"session": "logs", "ventana": "3", "destino": "/trabajo"})
    assert _destino(r) == ("/trabajo", "")
    assert [tuple(f) for f in con.execute("SELECT session, window_idx FROM oculto")] == [("logs", None)]


def test_mostrar_sin_sesion_lo_rechaza_el_formulario(cliente):
    assert _post(cliente, "/oculto/mostrar", data={"ventana": "1"}).status_code == 422


_DE_FUERA = ["https://otro.example/x", "//otro.example/x", "/\\otro.example/x", "javascript:alert(1)",
             "trabajo"]


@pytest.mark.parametrize("destino", _DE_FUERA)
def test_volver_nunca_saca_del_hub_aunque_el_destino_venga_de_fuera(cliente, demo, destino):
    """C-0177: `destino` viaja en el formulario, y `//otro.example` es una
    dirección de otro sitio para el navegador aunque empiece por `/`."""
    for r in (_post(cliente, "/oculto/mostrar", data={"session": "logs", "destino": destino}),
              _post(cliente, f"/slot/{demo['slot']}/estado",
                    data={"accion": "archivar", "proyecto_id": "demo", "destino": destino})):
        assert r.status_code == 303 and r.headers["location"] == "/"


def test_marcar_revisada_una_sesion_perdida_quita_el_aviso(cliente, con, demo, monkeypatch):
    from hub import api
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 4242)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [{
        "session": "demo", "window_idx": 0, "pane_idx": 0, "pane_id": "%1",
        "cwd": str(demo["asiento"]), "titulo": "Tarea", "comando": "bash", "activo": True}])
    atribuidor = Atribuidor(registry.cargar())
    snapshotter.capturar(con, atribuidor)
    monkeypatch.setattr(tmux, "servidor_pid", lambda: None)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [])
    snapshotter.capturar(con, atribuidor)
    perdida = api.recuperacion_pendiente(con)
    assert perdida
    assert _destino(_post(cliente, f"/recuperacion/{perdida['id']}/revisada")) == ("/", "")
    assert api.recuperacion_pendiente(con) is None


def test_marcar_revisada_una_muestra_que_no_existe_no_rompe(cliente):
    assert _destino(_post(cliente, "/recuperacion/999/revisada")) == ("/", "")


# ── El asistente: retirado donde el secretario es la voz, y sus errores ─────

def _secretario_en_todo_el_hub():
    from hub.secretario import memoria
    memoria.conectar().close()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n", encoding="utf-8")


@pytest.mark.parametrize("ruta,cuerpo", [
    ("/api/asistente/abrir", None),
    ("/api/asistente/retomar", {"sesion": "x"}),
    ("/api/asistente/responder", {"respuesta": "si"}),
])
def test_donde_el_secretario_es_la_voz_el_asistente_no_se_arranca_ni_se_le_contesta(cliente, ruta, cuerpo):
    _secretario_en_todo_el_hub()
    r = _post(cliente, ruta, json=cuerpo) if cuerpo else _post(cliente, ruta)
    assert r.status_code == 410 and "secretario" in r.json()["error"]


def test_abrir_el_asistente_sin_su_proyecto_dice_que_no_esta(cliente):
    r = _post(cliente, "/api/asistente/abrir").json()
    assert r["ok"] is False and r["error"]


def test_retomar_una_conversacion_que_no_es_del_asistente_lo_dice(cliente):
    r = _post(cliente, "/api/asistente/retomar", json={"sesion": "no-existe"}).json()
    assert r["ok"] is False and r["error"]


def test_responder_al_asistente_algo_fuera_de_la_lista_se_niega(cliente):
    r = _post(cliente, "/api/asistente/responder", json={"respuesta": "siempre"}).json()
    assert r["ok"] is False and r["error"]


# ── Secretario: notas y aparatos ─────────────────────────────────────────────

@pytest.fixture
def memoria():
    from hub.secretario import memoria as m
    c = m.conectar()
    yield m, c
    c.close()


def test_editar_una_nota_la_cambia_y_borrarla_la_quita(cliente, memoria):
    m, c = memoria
    nid = m.anotar(c, "El dentista es el jueves")
    assert _destino(_post(cliente, f"/secretario/nota/{nid}", data={"texto": "Es el viernes"})) == \
        ("/secretario", "Nota guardada.")
    assert m.notas(c)[0]["texto"] == "Es el viernes"
    assert _destino(_post(cliente, f"/secretario/nota/{nid}", data={"borrar": "1"})) == \
        ("/secretario", "Nota borrada.")
    assert m.notas(c) == []


def test_una_nota_vacia_no_borra_el_texto_que_habia(cliente, memoria):
    m, c = memoria
    nid = m.anotar(c, "No tocar")
    _post(cliente, f"/secretario/nota/{nid}", data={"texto": "   "})
    assert m.notas(c)[0]["texto"] == "No tocar"


def test_una_nota_que_ya_no_existe_no_sale_como_guardada_ni_borrada(cliente, memoria):
    """C-0175: decía «Nota guardada.» sin haber tocado nada (borrada en otra
    pestaña, o por el secretario mientras tanto)."""
    m, c = memoria
    m.anotar(c, "Sigue aquí")
    assert _destino(_post(cliente, "/secretario/nota/999", data={"texto": "Otra"})) == \
        ("/secretario", "Esa nota ya no existe.")
    assert _destino(_post(cliente, "/secretario/nota/999", data={"borrar": "1"})) == \
        ("/secretario", "Esa nota ya no existe.")
    assert [n["texto"] for n in m.notas(c)] == ["Sigue aquí"]


def test_guardar_una_nota_vaciada_dice_que_no_se_guardo(cliente, memoria):
    m, c = memoria
    nid = m.anotar(c, "No tocar")
    camino, aviso = _destino(_post(cliente, f"/secretario/nota/{nid}", data={"texto": "   "}))
    assert camino == "/secretario" and "bórrala" in aviso


def test_darse_de_baja_de_los_avisos_quita_ese_aparato_y_no_otro(cliente, memoria):
    m, c = memoria
    m.suscribir(c, "https://push.example/uno", "p", "a", aparato="móvil")
    m.suscribir(c, "https://push.example/dos", "p", "a", aparato="pc")
    r = _post(cliente, "/api/secretario/push/baja", json={"endpoint": "https://push.example/uno"})
    assert r.json() == {"ok": True}
    assert [s["aparato"] for s in m.suscripciones(c)] == ["pc"]


def test_darse_de_baja_de_un_aparato_que_no_esta_no_rompe(cliente, memoria):
    assert _post(cliente, "/api/secretario/push/baja", json={}).json() == {"ok": True}


def test_quitar_un_aparato_desde_la_pantalla_deja_de_avisarle(cliente, memoria):
    m, c = memoria
    sid = m.suscribir(c, "https://push.example/uno", "p", "a", aparato="móvil")
    assert _destino(_post(cliente, f"/secretario/aparato/{sid}/quitar")) == \
        ("/secretario", "Ese aparato ya no recibe avisos, aunque vuelva a abrir la app, hasta que pulses "
                        "«Activar avisos aquí» en él.")
    assert m.suscripciones(c) == []


def test_quitar_un_aparato_que_no_existe_no_toca_los_demas(cliente, memoria):
    m, c = memoria
    m.suscribir(c, "https://push.example/uno", "p", "a", aparato="móvil")
    assert _post(cliente, "/secretario/aparato/999/quitar").status_code == 303
    assert _post(cliente, "/secretario/aparato/abc/quitar").status_code == 422
    assert [s["aparato"] for s in m.suscripciones(c)] == ["móvil"]


# ── Un cuerpo que no es un objeto JSON (C-0174) ──────────────────────────────

def _rutas_que_leen_json() -> list[str]:
    """Las POST que leen el cuerpo como JSON, sacadas de la app y no de una
    lista a mano: una ruta nueva entra sola en la prueba."""
    rutas = []
    for r in web.app.routes:
        if "POST" not in (getattr(r, "methods", None) or set()):
            continue
        fuente = inspect.getsource(r.endpoint)
        if "request.json()" in fuente or "_objeto_json(" in fuente:
            rutas.append(re.sub(r"\{[^}]+\}", "1", r.path))
    return rutas


def test_hay_rutas_que_leen_json_para_probar():
    assert {"/api/slot", "/api/componentes/preparar", "/api/lienzo"} <= set(_rutas_que_leen_json())


@pytest.mark.parametrize("ruta", _rutas_que_leen_json())
@pytest.mark.parametrize("cuerpo", ["[]", '"texto"', "3", "no es json"])
def test_un_cuerpo_que_no_es_un_objeto_json_es_un_error_de_quien_llama_no_un_500(ruta, cuerpo):
    """`[]` llegaba a `cuerpo.get(…)` y el hub contestaba 500, que dice «me he
    roto» cuando quien se equivocó fue la llamada."""
    r = TestClient(web.app, raise_server_exceptions=False).post(
        ruta, content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code < 500, (ruta, r.status_code, r.text[:200])


def test_el_rechazo_dice_que_se_esperaba_un_objeto(cliente):
    r = _post(cliente, "/api/componentes/preparar", json=["navegante"])
    assert r.status_code == 400
    assert r.json()["ok"] is False and "objeto JSON" in r.json()["error"]


# ── Refrescar (C-0230) ───────────────────────────────────────────────────────

def test_refrescar_vuelve_a_la_pantalla_desde_la_que_se_pidio(cliente, monkeypatch):
    """Llevaba siempre a Panorama: desde cualquier pantalla, el botón de la
    cabecera te sacaba de donde estabas."""
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda con: None)
    r = _post(cliente, "/refrescar", data={"destino": "/trabajo?slot=7"})
    assert r.headers["location"] == "/trabajo?slot=7"
    r = _post(cliente, "/refrescar", data={"destino": "//malo.example"})
    assert r.headers["location"] == "/"


def test_el_boton_refrescar_lleva_su_pantalla_sin_el_aviso_de_antes(cliente):
    html = cliente.get("/servicios?aviso=Hecho&fugaz=1").text
    i = html.index('action="/refrescar"')
    assert 'name="destino" value="/servicios"' in html[i:i + 300]
