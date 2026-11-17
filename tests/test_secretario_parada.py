"""Parar `hub-secretario` sin dejar nada a medias ni un «Failed» (C-0266).

Cada reinicio hecho a propósito acababa en «Main process exited, status=143»
y «Failed with result 'exit-code'»: el servicio no atendía SIGTERM y moría con
el turno a medio contestar. Aquí se le manda la señal de verdad a un proceso
de prueba —con su `HUB_HOME` aparte, sin fuentes ni modelo— y se mira con qué
código sale y qué dejó hecho.

Lo que systemd hace con ello (que `KillMode=mixed` avise sólo al proceso
principal, que `TimeoutStopSec` corte) no se puede probar aquí: se ve en vivo.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from hub.secretario import conversacion, servicio

RAIZ = Path(__file__).resolve().parents[1]

# El servicio entero, con dobles en lo que llamaría al modelo o leería fuentes:
# queda el bucle, la señal y la espera, que es lo que se prueba.
_GUION = """
import pathlib, sys, time
casa, marcas, turno_s, vuelta_s, espera_s = sys.argv[1:6]
marcas = pathlib.Path(marcas)
from hub import config
assert str(config.HUB_HOME) == casa, "el proceso de prueba no usa otros datos que los suyos"
from hub.secretario import conversacion, investigar, memoria, servicio, sesiones
from hub.secretario.avisos import webpush

def turno(con, parar=None):
    (marcas / "turno-empezado").touch()
    time.sleep(float(turno_s))
    con.execute("UPDATE turno SET estado = 'listo' WHERE estado = 'pendiente'")
    (marcas / "turno-acabado").touch()
    return 1

def vuelta(con, parar=None):
    (marcas / "vuelta-empezada").touch()
    time.sleep(float(vuelta_s))
    (marcas / "vuelta-acabada").touch()

conversacion.atender = turno
servicio.una_vuelta = vuelta
sesiones.atender = investigar.atender = lambda con: 0
webpush.preparar = lambda: None
servicio.ESPERA_AL_PARAR_S = float(espera_s)
conversacion.recibir(memoria.conectar(), "hola")
servicio.correr()
"""


def _servicio_de_prueba(tmp_path, *, turno_s=0.0, vuelta_s=0.0, espera_s=20.0):
    casa, marcas = tmp_path / "casa-de-prueba", tmp_path / "marcas"
    casa.mkdir()
    marcas.mkdir()
    entorno = {**os.environ, "HUB_HOME": str(casa), "PYTHONPATH": str(RAIZ / "src"), "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen([sys.executable, "-c", _GUION, str(casa), str(marcas), str(turno_s), str(vuelta_s),
                          str(espera_s)], env=entorno, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         cwd=tmp_path)
    return p, marcas


def _esperar(ruta: Path, p: subprocess.Popen, segundos: float = 20.0) -> None:
    fin = time.monotonic() + segundos
    while not ruta.exists():
        if p.poll() is not None or time.monotonic() > fin:
            p.kill()
            salida, err = p.communicate()
            pytest.fail(f"no llegó a «{ruta.name}»: {salida}\n{err}")
        time.sleep(0.05)


def _parar(p: subprocess.Popen, tope: float = 20.0) -> tuple[int, str, float]:
    t0 = time.monotonic()
    p.send_signal(signal.SIGTERM)
    try:
        salida, err = p.communicate(timeout=tope)
    except subprocess.TimeoutExpired:
        p.kill()
        salida, err = p.communicate()
        pytest.fail(f"no paró en {tope} s: {salida}\n{err}")
    return p.returncode, salida + err, time.monotonic() - t0


def test_al_pedirle_que_pare_acaba_el_turno_que_contestaba_y_sale_con_cero(tmp_path):
    p, marcas = _servicio_de_prueba(tmp_path, turno_s=1.5)
    _esperar(marcas / "turno-empezado", p)
    codigo, salida, _ = _parar(p)
    assert codigo == 0, salida
    assert (marcas / "turno-acabado").exists(), "el turno a medias se cortó"
    assert "hub-secretario parado" in salida


def test_parado_sin_nada_entre_manos_sale_enseguida(tmp_path):
    p, marcas = _servicio_de_prueba(tmp_path)
    _esperar(marcas / "turno-acabado", p)
    _esperar(marcas / "vuelta-acabada", p)
    codigo, salida, tardo = _parar(p)
    assert codigo == 0, salida
    assert tardo < 5, "sin nada a medias no hay nada que esperar"


def test_un_turno_que_no_acaba_a_tiempo_no_impide_salir_y_tambien_sale_con_cero(tmp_path):
    p, marcas = _servicio_de_prueba(tmp_path, turno_s=60, espera_s=1)
    _esperar(marcas / "turno-empezado", p)
    codigo, salida, tardo = _parar(p)
    assert codigo == 0, salida
    assert tardo < 10 and not (marcas / "turno-acabado").exists()
    assert "se retoma" in salida


def test_un_paso_del_ciclo_que_no_acaba_a_tiempo_tampoco_impide_salir(tmp_path):
    """El ciclo va en el hilo principal: sin el tope, un triaje de dos minutos
    haría esperar a systemd hasta matarlo, y eso sí sería un «Failed»."""
    p, marcas = _servicio_de_prueba(tmp_path, vuelta_s=60, espera_s=1)
    _esperar(marcas / "vuelta-empezada", p)
    codigo, salida, tardo = _parar(p)
    assert codigo == 0, salida
    assert tardo < 10 and not (marcas / "vuelta-acabada").exists()


def test_el_tope_de_la_espera_se_arma_antes_de_levantar_la_parada(monkeypatch):
    """`parar.set()` toma el cerrojo interno del `Event`: si SIGTERM cae
    mientras el hilo principal lo tiene (dentro de `parar.wait`), el manejador
    se bloquea a sí mismo. Con el tope ya armado, SIGALRM lo saca de ahí y el
    servicio sale igual (C-0314)."""
    orden, manejadores = [], {}
    monkeypatch.setattr(servicio.signal, "signal", lambda senal, f: manejadores.__setitem__(senal, f))
    monkeypatch.setattr(servicio.signal, "setitimer", lambda *a: orden.append("tope"))

    class Parada:
        def is_set(self):
            return bool(orden)

        def set(self):
            orden.append("parar")

    servicio.atender_parada(Parada())
    manejadores[signal.SIGTERM]()
    manejadores[signal.SIGTERM]()   # una segunda señal no vuelve a armar nada
    assert orden == ["tope", "parar"]


# ── lo que se hacía aparte sobrevive al reinicio (C-0308) ────────────────────

# El servicio entero otra vez, ahora con el hilo de lo aparte de verdad y un
# motor de mentira: en el primer arranque la investigación no acaba nunca; en
# el segundo contesta. Lo que se prueba es el camino entero: SIGTERM a mitad,
# arrancar, verla volver a la cola, hacerse y llegar a su hilo.
_GUION_INVESTIGA = """
import pathlib, sys, time
casa, marcas, acaba = sys.argv[1:4]
marcas = pathlib.Path(marcas)
from hub import config
assert str(config.HUB_HOME) == casa, "el proceso de prueba no usa otros datos que los suyos"
from hub.secretario import conversacion, investigar, memoria, motor, servicio
from hub.secretario.avisos import webpush

def llamar(prompt, **kw):
    (marcas / "investigando").touch()
    if acaba != "si":
        time.sleep(120)
    return motor.Respuesta(texto="", sesion="s", segundos=1.0, coste=0.1, modelo=kw["modelo"], estructurada={
        "resumen": "Cinco años.", "no_encontrado": [],
        "afirmaciones": [{"texto": "Se conserva cinco años.", "url": "https://ejemplo.gob/norma", "fecha": "2025-01-01"}]})

def hecha(con, *a, **k):
    n = de_verdad(con, *a, **k)
    if n:
        (marcas / "hecha").touch()
    return n

motor.llamar = llamar
de_verdad, investigar.atender = investigar.atender, hecha
conversacion.atender = lambda con, parar=None: 0
servicio.una_vuelta = lambda con, parar=None: None
webpush.preparar = lambda: None
if acaba != "si":
    con = memoria.conectar()
    hilo = conversacion.decir(con, None, "hola")
    hilo = con.execute("SELECT hilo FROM turno WHERE id = ?", (hilo,)).fetchone()[0]
    assert investigar.encargar(con, "¿Cuánto se conserva la contabilidad?", hilo=hilo).get("encargado")
    con.close()
servicio.correr()
"""


def _servicio_que_investiga(tmp_path, acaba: bool):
    casa, marcas = tmp_path / "casa-de-prueba", tmp_path / ("marcas-2" if acaba else "marcas-1")
    casa.mkdir(exist_ok=True)
    marcas.mkdir()
    entorno = {**os.environ, "HUB_HOME": str(casa), "PYTHONPATH": str(RAIZ / "src"), "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen([sys.executable, "-c", _GUION_INVESTIGA, str(casa), str(marcas), "si" if acaba else "no"],
                         env=entorno, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=tmp_path)
    return p, marcas, casa


def test_una_investigacion_cortada_por_el_reinicio_se_repite_sola_y_llega_a_su_hilo(tmp_path):
    from hub.secretario import investigar, memoria

    p, marcas, casa = _servicio_que_investiga(tmp_path, acaba=False)
    _esperar(marcas / "investigando", p)
    codigo, salida, tardo = _parar(p)
    assert codigo == 0 and tardo < 10, f"lo aparte no se espera al parar: {salida}"
    base = casa / "secretario" / "memoria.db"
    con = memoria.conectar(base)
    marca = memoria.leer(con, investigar.EN_CURSO)
    assert marca and marca["pedido"]["pregunta"] == "¿Cuánto se conserva la contabilidad?", "así queda al morir"
    assert not memoria.leer(con, investigar.CLAVE)
    con.close()

    p, marcas, _ = _servicio_que_investiga(tmp_path, acaba=True)
    _esperar(marcas / "hecha", p)
    codigo, salida, _ = _parar(p)
    assert codigo == 0, salida
    con = memoria.conectar(base)
    textos = [f["texto"] for f in con.execute("SELECT texto FROM turno WHERE rol = 'secretario' ORDER BY id")]
    con.close()
    assert len(textos) == 3, textos
    assert "se cortó al reiniciarme; la repito" in textos[1]
    assert "Investigué «¿Cuánto se conserva la contabilidad?»" in textos[2] and "https://ejemplo.gob/norma" in textos[2]


def test_al_arrancar_el_servicio_cierra_lo_que_quedo_ejecutando_sin_hacerlo_otra_vez(tmp_path):
    """C-0315, por el arranque de verdad: una solicitud que un servicio muerto
    dejó a medias no se ejecuta; queda «cortada» y se le dice en el chat."""
    from hub.secretario import memoria

    base = tmp_path / "casa-de-prueba" / "secretario" / "memoria.db"
    base.parent.mkdir(parents=True)
    con = memoria.conectar(base)
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada, estado) VALUES ('anotar', ?, 'x', ?, 'ejecutando')",
                ('{"texto": "no debe anotarse"}', memoria.ahora()))
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada, estado) VALUES ('anotar', ?, 'x', ?, 'aprobada')",
                ('{"texto": "ésta sí"}', memoria.ahora()))
    con.close()
    p, _, _ = _servicio_que_investiga(tmp_path, acaba=True)
    con = memoria.conectar(base)
    fin = time.monotonic() + 20
    # La cortada se cierra al arrancar; la aprobada la recoge la espera entre vueltas.
    while [f[0] for f in con.execute("SELECT estado FROM solicitud ORDER BY id")] != ["cortada", "hecha"]:
        if p.poll() is not None or time.monotonic() > fin:
            p.kill()
            pytest.fail(f"no cerró lo cortado o no hizo lo aprobado: {p.communicate()}")
        time.sleep(0.05)
    codigo, salida, _ = _parar(p)
    assert codigo == 0, salida
    assert [n["texto"] for n in memoria.notas(con)] == ["ésta sí"], "lo cortado no se ejecuta; lo aprobado, sí"
    textos = [f["texto"] for f in con.execute("SELECT texto FROM turno WHERE rol = 'secretario'")]
    con.close()
    assert len(textos) == 1 and "no sé si llegó a hacerse" in textos[0]


# ── lo que no se empieza con la parada pedida ────────────────────────────────

def test_con_la_parada_pedida_la_vuelta_no_empieza_mas_pasos(monkeypatch, tmp_path):
    from hub.secretario import memoria
    con = memoria.conectar()
    parar = threading.Event()
    hechos = []

    def paso(con_, nombre, funcion, *args):
        hechos.append(nombre)
        if len(hechos) == 2:
            parar.set()

    monkeypatch.setattr(servicio, "_paso", paso)
    servicio.una_vuelta(con, parar)
    assert len(hechos) == 2, "lo que no se empezó lo hace la vuelta siguiente, ya reiniciado"
    hechos.clear()
    servicio.una_vuelta(con)
    assert len(hechos) > 10, "sin parada, la vuelta entera"


def test_con_la_parada_pedida_no_se_toma_el_turno_siguiente(monkeypatch):
    from hub.secretario import memoria
    con = memoria.conectar()
    conversacion.recibir(con, "uno")
    conversacion.recibir(con, "dos")
    parar = threading.Event()
    contestados = []

    def contestar(con_, turno):
        contestados.append(turno["texto"])
        con_.execute("UPDATE turno SET estado = 'listo' WHERE id = ?", (turno["id"],))
        parar.set()

    monkeypatch.setattr(conversacion, "contestar", contestar)
    assert conversacion.atender(con, parar.is_set) == 1
    assert contestados == ["uno"]
    pendientes = [f["texto"] for f in con.execute("SELECT texto FROM turno WHERE estado = 'pendiente'")]
    assert pendientes == ["dos"], "el que no se tomó espera al arranque"


# ── la plantilla ─────────────────────────────────────────────────────────────

def test_la_plantilla_le_da_mas_tiempo_del_que_el_servicio_espera():
    """Si systemd corta antes de que el servicio se rinda, lo mata él y vuelve
    el «Failed». Y la señal va sólo al proceso principal (`KillMode=mixed`):
    con la de por omisión, `claude` la recibe a la vez y el turno que se quería
    dejar acabar muere igual."""
    texto = (RAIZ / "scripts" / "hub-secretario.service.plantilla").read_text(encoding="utf-8")
    tope = re.search(r"^TimeoutStopSec=(\d+)$", texto, re.M)
    assert tope, "la plantilla no dice cuánto espera systemd"
    assert int(tope.group(1)) >= servicio.ESPERA_AL_PARAR_S + 10
    assert re.search(r"^KillMode=mixed$", texto, re.M)
