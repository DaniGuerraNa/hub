"""El secretario usa los comandos preparados del dueño (C-0507, decisión 464).

Le pidió unos repos de interno «que ya tenemos un script para eso», y contestó
que no existía ningún script: los comandos de `comandos.yml` sólo eran un
botón de Archivos. Ahora los ve (`comandos_preparados`), los deja escritos sin
Enter (`dejar_comando_escrito`) y, sólo con su sí en Pendientes a las órdenes
exactas, los corre él sobre una lista (`clonar_lista`) y le dice cuáles
salieron. Aquí, con un script de juguete que clona un repo local: nada de red,
nada de sus credenciales.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import config, db, slots, web
from hub.secretario import conversacion, herramientas, lotes, memoria, piezas, servicio

RAIZ = Path(__file__).resolve().parents[1]


def _git(*args, cwd=None):
    subprocess.run(["git", "-c", "user.email=prueba@ejemplo", "-c", "user.name=prueba", *args], cwd=cwd,
                   check=True, capture_output=True)


@pytest.fixture(autouse=True)
def _sin_telefono(monkeypatch):
    avisados = []
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda texto, **k: avisados.append(texto))
    return avisados


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    """Su hub de prueba: un proyecto con `interno/repos`, un repo de origen
    local, el script de juguete y su `comandos.yml` con uno ejecutable."""
    raiz = tmp_path / "trabajo"
    repos = raiz / "interno" / "repos"
    repos.mkdir(parents=True)
    origen = tmp_path / "origen"
    _git("init", "-q", str(origen))
    _git("commit", "-q", "--allow-empty", "-m", "primero", cwd=origen)
    guion = tmp_path / "secretos" / "clonar-interno.sh"
    guion.parent.mkdir()
    guion.write_text('#!/bin/bash\n[ "$1" = roto ] && { echo "fatal: no existe" >&2; exit 128; }\n'
                     f'git clone -q "file://{origen}" "$2/$1"\n', encoding="utf-8")
    yml = tmp_path / "comandos.yml"
    yml.write_text("comandos:\n"
                   "  - id: clonar-interno\n    nombre: Clonar repo — interno\n"
                   f"    plantilla: bash {guion} {{repo}} {{ruta}}\n    ejecutable: true\n    crea: \"{{repo}}\"\n"
                   "  - id: clonar-externo\n    nombre: Clonar repo — externo\n"
                   f"    plantilla: bash {guion} {{repo}} {{ruta}}\n", encoding="utf-8")
    monkeypatch.setenv("HUB_COMANDOS_YML", str(yml))
    h = db.conectar()
    db.inicializar(h)
    h.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo',?)", (str(raiz),))
    h.execute("INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo',?,'asiento')", (str(raiz),))
    h.commit()
    h.close()
    return {"raiz": raiz, "repos": repos, "guion": guion, "yml": yml}


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def hilo(con):
    return con.execute("INSERT INTO hilo (abierto, ultimo) VALUES (?, ?)",
                       (memoria.ahora(), memoria.ahora())).lastrowid


def _pedir(con, hilo, valores, preparado="clonar-interno", ruta=None, mundo=None, accion="clonar_lista"):
    params = {"preparado": preparado, "ruta": str(ruta or mundo["repos"]), "valores": valores}
    return herramientas.usar_accion(con, piezas.acciones()[accion], params, "me lo pidió", hilo)


def _dicho(con, hilo) -> str:
    return "\n".join(t["texto"] for t in con.execute("SELECT texto FROM turno WHERE hilo = ? ORDER BY id", (hilo,)))


# ── lo que sabe que existe ───────────────────────────────────────────────────

def test_ve_sus_comandos_y_que_carpetas_hay_ya(mundo, con):
    (mundo["repos"] / "ya-estaba").mkdir()
    r = herramientas.catalogo()["comandos_preparados"].funcion(con, {"ruta": str(mundo["repos"])})
    por = {c["id"]: c for c in r["comandos"]}
    assert por["clonar-interno"]["ejecutable"] and por["clonar-interno"]["huecos"] == ["repo", "ruta"]
    assert not por["clonar-externo"]["ejecutable"]
    assert r["carpeta"]["carpetas"] == ["ya-estaba"] and r["carpeta"]["proyecto"] == "demo"


def test_una_carpeta_fuera_de_lo_indexado_se_dice_en_vez_de_listarla(mundo, con, tmp_path):
    r = herramientas.catalogo()["comandos_preparados"].funcion(con, {"ruta": str(tmp_path)})
    assert "no está bajo ninguna ruta" in r["carpeta"]["error"]


def test_el_prompt_le_dice_que_mire_antes_de_decir_que_no_hay_script():
    assert "`comandos_preparados` antes de decir que no" in conversacion.sistema()


def test_sin_ningun_ejecutable_no_se_le_ofrece_correrlos(mundo, monkeypatch):
    monkeypatch.setenv("SECRETARIO_HILO", "1")
    assert {"accion_clonar_lista", "accion_dejar_comando_escrito"} <= set(herramientas.todas())
    mundo["yml"].write_text(mundo["yml"].read_text().replace("    ejecutable: true\n", ""), encoding="utf-8")
    assert "accion_clonar_lista" not in herramientas.todas()
    assert "accion_dejar_comando_escrito" in herramientas.todas()


# ── dejarlo escrito: sin preguntar, sin Enter ────────────────────────────────

def test_dejarlo_escrito_no_pregunta_y_devuelve_el_enlace_a_la_ventana(mundo, con, hilo, monkeypatch):
    escritas = []
    monkeypatch.setattr(slots, "abrir_en", lambda ruta, nombre, session, texto="": escritas.append(texto) or "%7")
    (mundo["repos"] / "ya-estaba").mkdir()
    r = _pedir(con, hilo, ["api", "ya-estaba", "web"], preparado="clonar-externo", mundo=mundo,
               accion="dejar_comando_escrito")
    assert r["hecho"], r
    assert "/trabajo?session=demo" in r["resultado"] and "no salté ninguno" in r["resultado"]
    assert escritas == [" ; ".join(f"bash {mundo['guion']} {v} {mundo['repos']}" for v in ("api", "ya-estaba", "web"))]
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_sin_el_dueno_delante_no_deja_ni_corre_nada(mundo, con, monkeypatch):
    monkeypatch.setattr(slots, "abrir_en", lambda *a, **k: pytest.fail("abrió una ventana"))
    for accion in ("dejar_comando_escrito", "clonar_lista"):
        r = _pedir(con, None, ["api"], mundo=mundo, accion=accion)
        assert not r["hecho"] and "cuando el dueño te lo pide" in r["nota"]
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


# ── correrlo: con su sí en Pendientes ────────────────────────────────────────

def test_pide_su_si_y_pendientes_ensena_cada_orden_rellenada(mundo, con, hilo, _sin_telefono):
    from hub import api
    (mundo["repos"] / "ya-estaba").mkdir()
    r = _pedir(con, hilo, ["prometeo-api", "ya-estaba"], mundo=mundo)
    assert not r["hecho"] and r["solicitud"]
    [s] = api.secretario_solicitudes(con, pendientes=True)
    datos = dict(map(tuple, s["datos"]))
    assert datos["orden 1"] == f"bash {mundo['guion']} prometeo-api {mundo['repos']}"
    assert datos["orden 2"].endswith("ya está: se salta")
    assert s["con_techo"] and s["riesgo_rotulo"] == "No tiene vuelta atrás"
    # El aviso al teléfono dice cuántos y con qué, no los nombres (regla dura 22).
    assert "2 órdenes" in _sin_telefono[0]
    assert "prometeo" not in _sin_telefono[0] and "interno" not in _sin_telefono[0]
    assert not (mundo["repos"] / "prometeo-api").exists()


def test_lo_que_no_es_ejecutable_no_se_puede_ni_pedir(mundo, con, hilo):
    r = _pedir(con, hilo, ["api"], preparado="clonar-externo", mundo=mundo)
    assert not r["hecho"] and "ejecutable: true" in r["error"]
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_no_pasa_a_auto_aunque_se_lo_pongan(mundo, monkeypatch):
    monkeypatch.setattr(piezas, "niveles", lambda: {"clonar_lista": "auto"})
    assert piezas.nivel(piezas.acciones()["clonar_lista"]) == "ask"


def test_sin_aprobar_no_corre_aunque_la_llamen_directo(mundo, con):
    with pytest.raises(RuntimeError, match="sí del dueño"):
        piezas.acciones()["clonar_lista"].ejecutar(con, {"preparado": "clonar-interno",
                                                         "ruta": str(mundo["repos"]), "valores": ["api"]})
    assert memoria.leer(con, lotes.CLAVE) in (None, [])


def test_un_si_que_llega_tarde_no_la_corre(mundo, con, hilo):
    r = _pedir(con, hilo, ["api"], mundo=mundo)
    con.execute("UPDATE solicitud SET creada = '2020-01-01T00:00:00+00:00'")
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    assert con.execute("SELECT estado FROM solicitud").fetchone()["estado"] == "caducada"
    assert lotes.atender(con) == 0 and not (mundo["repos"] / "api").exists()


def test_con_su_boton_se_encarga_se_corre_aparte_y_el_informe_llega_a_su_chat(mundo, con, hilo):
    r = _pedir(con, hilo, ["api", "web", "roto"], mundo=mundo)
    respuesta = TestClient(web.app).post(f"/secretario/solicitud/{r['solicitud']}", data={"decision": "aprobar"},
                                         follow_redirects=False)
    assert respuesta.status_code in (302, 303)
    assert servicio.ejecutar_aprobadas(con) == 1
    s = con.execute("SELECT estado, resultado FROM solicitud").fetchone()
    assert s["estado"] == "hecha" and "encargadas 3" in s["resultado"]
    assert not (mundo["repos"] / "api").exists(), "el sí sólo lo encarga: lo corre el hilo de lo aparte"

    assert lotes.atender(con) == 1
    assert (mundo["repos"] / "api" / ".git").is_dir() and (mundo["repos"] / "web" / ".git").is_dir()
    dicho = _dicho(con, hilo)
    assert lotes.MARCO in dicho and "Hechos y comprobados (2): api, web" in dicho
    assert "Falló roto" in dicho and "128" in dicho
    assert memoria.leer(con, lotes.EN_CURSO) is None


def test_si_su_comandos_yml_cambia_mientras_espera_no_corre_lo_que_no_aprobo(mundo, con, hilo):
    r = _pedir(con, hilo, ["api"], mundo=mundo)
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    mundo["yml"].write_text(mundo["yml"].read_text().replace("bash ", "bash -x "), encoding="utf-8")
    assert lotes.atender(con) == 1
    assert "ya no son las que aprobó" in _dicho(con, hilo)
    assert not (mundo["repos"] / "api").exists()


def test_una_carpeta_a_medias_no_se_toca_pero_tampoco_se_da_por_clonada(mundo, con, hilo):
    (mundo["repos"] / "a-medias").mkdir()
    r = _pedir(con, hilo, ["a-medias"], mundo=mundo)
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    lotes.atender(con)
    assert "no es un repo de git, no la toqué (1): a-medias" in _dicho(con, hilo)
    assert list((mundo["repos"] / "a-medias").iterdir()) == []


def test_la_lista_cortada_por_un_reinicio_no_se_repite_y_se_dice(mundo, con, hilo):
    memoria.poner(con, lotes.EN_CURSO, {"desde": memoria.ahora(), "pedido": {
        "preparado": "clonar-interno", "ruta": str(mundo["repos"]), "valores": ["api"], "hilo": hilo}})
    assert lotes.retomar(con) == 1
    assert "no sé hasta dónde llegó" in _dicho(con, hilo)
    assert memoria.leer(con, lotes.EN_CURSO) is None and memoria.leer(con, lotes.CLAVE) in (None, [])
    assert not (mundo["repos"] / "api").exists()


# ── el servicio de verdad ────────────────────────────────────────────────────

_GUION = """
import pathlib, sys
from hub import config
assert str(config.HUB_HOME) == sys.argv[1], "el proceso de prueba no usa otros datos que los suyos"
from hub.secretario import conversacion, investigar, servicio, sesiones
from hub.secretario.avisos import webpush
# Sin fuentes ni modelo: queda el ciclo que ejecuta lo aprobado y el hilo de lo aparte.
servicio.una_vuelta = lambda con, parar=None: None
conversacion.atender = lambda con, parar=None: 0
sesiones.atender = investigar.atender = lambda con: 0
webpush.preparar = lambda: None
servicio.correr()
"""


def test_el_servicio_de_verdad_lo_corre_tras_su_boton(mundo, con, hilo):
    """`hub-secretario` en un proceso aparte, con su `HUB_HOME` de prueba: el
    botón marca, el ciclo lo encarga y el hilo de lo aparte clona."""
    r = _pedir(con, hilo, ["api"], mundo=mundo)
    entorno = {**os.environ, "HUB_HOME": str(config.HUB_HOME), "PYTHONPATH": str(RAIZ / "src"),
               "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen([sys.executable, "-c", _GUION, str(config.HUB_HOME)], env=entorno,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        TestClient(web.app).post(f"/secretario/solicitud/{r['solicitud']}", data={"decision": "aprobar"})
        fin = time.monotonic() + 60
        while "Hechos y comprobados" not in _dicho(con, hilo):
            if p.poll() is not None or time.monotonic() > fin:
                break
            time.sleep(0.3)
    finally:
        p.send_signal(signal.SIGTERM)
        salida, _ = p.communicate(timeout=30)
    assert "Hechos y comprobados (1): api" in _dicho(con, hilo), salida
    assert (mundo["repos"] / "api" / ".git").is_dir()
    bitacora = [json.loads(f["params"]) for f in con.execute("SELECT params FROM bitacora WHERE accion = ?",
                                                              (lotes.ACCION,))]
    assert {"preparado": "clonar-interno", "valores": 1} in bitacora
