"""El ciclo lento corre en su propio hilo y el latido no lo espera (C-0309).

Medido el 12-nov en la base de quien lo usa: de 49 intervalos entre muestras,
47 iban de 20 a 23 s y dos eran de 69 y 75 s, los dos donde tocó medir git,
docker y el registro de consumo. Los mensajes programados y el despertar del
orquestador esperaban detrás. Lo que se prueba aquí es que ya no esperan, y
sobre todo que el arreglo no rompe lo que el snapshotter promete (regla dura
2): un ciclo lento que lanza, que se cuelga o cuyo hilo no arranca no deja al
hub sin latido ni sin muestra.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time

import pytest

from hub import busqueda, config, consumo, db, maquina, repos, salud, servicios, snapshotter, tmux
from hub.registry import Atribuidor
from hub.models import Proyecto


def _hasta(condicion, segundos=5.0):
    """Espera a que algo de otro hilo ocurra, sin dormir un plazo a ciegas."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.005)
    return False


class _Trabajo:
    """Un ciclo lento de mentira que se queda trabajando hasta que se le suelta."""

    def __init__(self):
        self.entro = threading.Event()
        self.soltar = threading.Event()
        self.veces = 0
        self.conexiones = []
        self.hilos = []

    def __call__(self, con, al_paso):
        self.veces += 1
        self.conexiones.append(con)
        self.hilos.append(threading.current_thread())
        self.entro.set()
        self.soltar.wait(10)


@pytest.fixture
def lento_de_prueba(tmp_path):
    """Un `CicloLento` sobre la base temporal, y su trabajo; al acabar se suelta
    para que el hilo no se quede esperando entre tests."""
    trabajo = _Trabajo()
    lento = snapshotter.CicloLento(trabajo=trabajo,
                                   conectar=lambda: db.conectar(tmp_path / "hub.db"))
    yield lento, trabajo
    trabajo.soltar.set()


@pytest.fixture
def latido_quieto(monkeypatch):
    """Una vuelta sin tmux, programados, orquestador ni SAI de verdad: cuenta
    qué se hizo."""
    hechos: list[str] = []
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda c: hechos.append("muestra"))
    monkeypatch.setattr(snapshotter, "ciclo_mensajes", lambda c: hechos.append("programados") or 0)
    monkeypatch.setattr(snapshotter.orquestador, "bombear", lambda c: hechos.append("orquestador") or {})
    monkeypatch.setattr(snapshotter.maquina, "escanear_ups", lambda c: hechos.append("sai") or 0)
    return hechos


# ── El latido no espera ──────────────────────────────────────────────────────

def test_mientras_el_ciclo_lento_trabaja_el_latido_sigue_muestreando(
    con, lento_de_prueba, latido_quieto
):
    """🔴 El defecto: con el ciclo lento dentro de la vuelta, la muestra, los
    programados y el orquestador esperaban a git sobre 9p."""
    lento, trabajo = lento_de_prueba
    for ciclo in range(4):
        snapshotter.vuelta(con, ciclo, lento)
    assert trabajo.entro.wait(5), "el ciclo lento no llegó a arrancar"
    assert not trabajo.soltar.is_set(), "el ciclo lento sigue trabajando"
    assert latido_quieto.count("muestra") == 4
    assert latido_quieto.count("programados") == 4
    assert latido_quieto.count("orquestador") == 4


def test_el_ciclo_lento_corre_en_otro_hilo_y_con_su_propia_conexion(
    con, lento_de_prueba, latido_quieto
):
    """Una conexión de SQLite no se comparte entre hilos: la del latido tiene
    su transacción de la muestra, y dos hilos sobre ella se la pisarían."""
    lento, trabajo = lento_de_prueba
    snapshotter.vuelta(con, 0, lento)
    assert trabajo.entro.wait(5)
    assert trabajo.hilos[0] is not threading.current_thread()
    assert trabajo.hilos[0].daemon, "un hilo que no es daemon no dejaría parar el servicio"
    assert trabajo.conexiones[0] is not con


def test_no_se_lanza_un_ciclo_lento_encima_de_otro_ni_se_encola(lento_de_prueba):
    """De uno en uno. Encolarlo haría que, tras un `/mnt/c` colgado media
    hora, salieran tres escaneos seguidos justo cuando el disco vuelve."""
    lento, trabajo = lento_de_prueba
    assert lento.pedir() is True
    assert trabajo.entro.wait(5)
    assert lento.pedir() is False
    assert lento.pedir() is False

    trabajo.soltar.set()
    assert _hasta(lambda: not lento.estado()["corriendo"])
    time.sleep(0.05)
    assert trabajo.veces == 1, "lo pedido mientras trabajaba se quedó en cola"

    assert lento.pedir() is True
    assert _hasta(lambda: trabajo.veces == 2)


def test_el_sai_se_mide_en_el_latido_tambien_cuando_toca_el_ciclo_lento(
    con, lento_de_prueba, latido_quieto
):
    """El SAI aguanta ~22 min (decisión 249): su medida no puede esperar a
    que el ciclo lento, que ahora va por su cuenta, llegue a ella."""
    lento, _ = lento_de_prueba
    snapshotter.vuelta(con, 0, lento)
    assert latido_quieto.count("sai") == 1


# ── Regla dura 2: ni muere ni se queda sordo ─────────────────────────────────

def test_un_ciclo_lento_que_lanza_no_mata_su_hilo_y_el_siguiente_corre(tmp_path, capsys):
    veces = []

    def trabajo(con, al_paso):
        veces.append(1)
        if len(veces) == 1:
            raise OSError(5, "Input/output error")

    lento = snapshotter.CicloLento(trabajo=trabajo,
                                   conectar=lambda: db.conectar(tmp_path / "hub.db"))
    assert lento.pedir() is True
    assert _hasta(lambda: not lento.estado()["corriendo"])
    estado = lento.estado()
    assert "Input/output error" in estado["fallo"]
    assert estado["acabo"] is None, "una vuelta que falló no cuenta como acabada"
    assert "Input/output error" in capsys.readouterr().out, "se dice en voz alta (regla 21)"

    assert lento.pedir() is True
    assert _hasta(lambda: lento.estado()["acabo"] is not None)
    assert lento.estado()["fallo"] is None
    assert len(veces) == 2


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_si_el_hilo_muere_el_siguiente_pedido_lo_levanta_otra_vez(tmp_path):
    """Un hilo no puede morir por una excepción normal, pero sí por lo que no
    se atrapa a propósito. Si pasa, el ciclo lento no se queda parado para
    siempre con el latido tan tranquilo."""
    veces = []

    def trabajo(con, al_paso):
        veces.append(threading.current_thread())
        if len(veces) == 1:
            raise SystemExit

    lento = snapshotter.CicloLento(trabajo=trabajo,
                                   conectar=lambda: db.conectar(tmp_path / "hub.db"))
    assert lento.pedir() is True
    assert _hasta(lambda: veces and not veces[0].is_alive())
    assert lento.estado()["corriendo"] is False

    assert lento.pedir() is True
    assert _hasta(lambda: lento.estado()["acabo"] is not None)
    assert len(veces) == 2 and veces[1] is not veces[0]


def test_si_la_base_no_abre_en_el_hilo_se_dice_y_se_reintenta_en_la_vuelta_siguiente(tmp_path, capsys):
    abre = {"si": False}
    veces = []

    def conectar():
        if not abre["si"]:
            raise db.BaseIlegible("la base está ocupada")
        return db.conectar(tmp_path / "hub.db")

    lento = snapshotter.CicloLento(trabajo=lambda con, al_paso: veces.append(con), conectar=conectar)
    lento.pedir()
    assert _hasta(lambda: not lento.estado()["corriendo"])
    assert veces == [] and "ocupada" in lento.estado()["fallo"]
    assert "ocupada" in capsys.readouterr().out

    abre["si"] = True
    lento.pedir()
    assert _hasta(lambda: len(veces) == 1)


def test_si_el_hilo_no_arranca_el_ciclo_lento_corre_dentro_del_latido(
    con, latido_quieto, monkeypatch, capsys
):
    """La salida de emergencia: sin hilo se mide como siempre, dentro de la
    vuelta. Más lento, pero el respaldo y la copia de la base se siguen
    haciendo."""
    hechos = []

    class NoArranca(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(snapshotter.threading, "Thread", NoArranca)
    lento = snapshotter.CicloLento(
        trabajo=lambda c, al_paso: hechos.append((c, threading.current_thread())),
        conectar=lambda: pytest.fail("sin hilo no se abre otra conexión"))

    snapshotter.vuelta(con, 0, lento)

    assert hechos == [(con, threading.current_thread())]
    estado = lento.estado()
    assert estado["dentro"] is True and estado["acabo"] is not None
    assert "se mide dentro del latido" in capsys.readouterr().out
    # Y la vuelta siguió entera: el muestreo no depende de esto.
    assert latido_quieto[:3] == ["muestra", "programados", "orquestador"]
    # El SAI lo mide el latido también aquí: el ciclo lento de un
    # `CicloLento` no lo mide nunca, corra en su hilo o dentro.
    assert latido_quieto == ["muestra", "programados", "orquestador", "sai"]


def test_sin_hilo_la_vuelta_mide_dentro_como_siempre(con, latido_quieto, monkeypatch):
    """`lento=None` es lo de antes: quien llama a `vuelta` sin más no cambia."""
    monkeypatch.setattr(snapshotter, "ciclo_lento", lambda c: latido_quieto.append("lento"))
    snapshotter.vuelta(con, 0)
    assert latido_quieto == ["muestra", "programados", "orquestador", "lento"]


# ── Qué paso corre y cuánto duró cada uno ────────────────────────────────────

@pytest.fixture
def pasos_de_mentira(monkeypatch):
    """Los nueve pasos del ciclo lento, sin git, docker ni PowerShell."""
    from hub import copia_base, intercambio, transcribir
    from hub import version as _version
    snapshotter._RACHAS_LENTO.clear()
    monkeypatch.setattr(snapshotter.registry, "cargar", lambda: [])
    for modulo, nombre in ((repos, "escanear"), (servicios, "escanear"), (busqueda, "reindexar"),
                           (consumo, "escanear"), (maquina, "escanear"), (copia_base, "hacer")):
        monkeypatch.setattr(modulo, nombre, lambda *a, **k: 0)
    monkeypatch.setattr(_version, "buscar_remota", lambda: None)
    monkeypatch.setattr(intercambio, "podar_de_paso", lambda: [])
    monkeypatch.setattr(transcribir, "podar_dictados", lambda: 0)


def test_el_ciclo_lento_dice_que_paso_empieza_y_cuanto_duro(con, pasos_de_mentira):
    visto = []
    resultado = snapshotter.ciclo_lento(
        con, al_paso=lambda clave, duro=None, fallo=None: visto.append((clave, duro)))

    empezados = [clave for clave, duro in visto if duro is None]
    acabados = [clave for clave, duro in visto if duro is not None]
    assert empezados == acabados, "cada paso que empieza, acaba; y en orden"
    # El registro va primero y también se dice: es un `stat` sobre el disco
    # de Windows, justo lo que se cuelga.
    assert empezados[0] == "registro"
    assert set(resultado) <= set(empezados)
    assert all(isinstance(duro, float) and duro >= 0 for _, duro in visto if duro is not None)


def test_un_paso_que_falla_tambien_dice_cuanto_duro(con, pasos_de_mentira, monkeypatch):
    def revienta(*a, **k):
        raise RuntimeError("git se quedó sin disco")

    monkeypatch.setattr(repos, "escanear", revienta)
    visto = []
    fallos = {}

    def apuntar(clave, duro=None, fallo=None):
        visto.append((clave, duro))
        if fallo:
            fallos[clave] = fallo

    snapshotter.ciclo_lento(con, al_paso=apuntar)
    assert [duro is not None for clave, duro in visto if clave == "repos"] == [False, True]
    assert ("servicios", None) in visto, "los demás pasos siguen (regla dura 14)"
    assert fallos == {"repos": "RuntimeError: git se quedó sin disco"}


def test_un_aviso_de_paso_que_lanza_no_deja_sin_medir(con, pasos_de_mentira, capsys):
    def revienta(clave, duro=None, fallo=None):
        raise ValueError("no se pudo apuntar")

    resultado = snapshotter.ciclo_lento(con, al_paso=revienta)
    assert resultado["repos"] == 0 and resultado["dictados"] == 0
    assert "no se pudo apuntar" in capsys.readouterr().out


def test_el_estado_dice_en_que_paso_va_y_al_acabar_cuanto_duro_cada_uno(tmp_path):
    en_el_paso = threading.Event()
    soltar = threading.Event()

    def trabajo(con, al_paso):
        al_paso("registro")
        al_paso("registro", 0.3)
        al_paso("repos")
        en_el_paso.set()
        soltar.wait(10)
        al_paso("repos", 1.5)

    lento = snapshotter.CicloLento(trabajo=trabajo,
                                   conectar=lambda: db.conectar(tmp_path / "hub.db"))
    try:
        lento.pedir()
        assert en_el_paso.wait(5)
        estado = lento.estado()
        assert estado["corriendo"] is True and estado["paso"] == "repos"
        assert estado["paso_desde"] and estado["empezo"]
        assert estado["pasos"] == {"registro": 0.3}
    finally:
        soltar.set()
    assert _hasta(lambda: not lento.estado()["corriendo"])
    estado = lento.estado()
    assert estado["paso"] is None and estado["paso_desde"] is None
    assert estado["pasos"]["repos"] == 1.5
    assert estado["acabo"] and isinstance(estado["duro"], float)
    json.dumps(estado)   # viaja en el latido: tiene que poder escribirse


def test_el_estado_devuelto_no_es_el_de_dentro(lento_de_prueba):
    lento, _ = lento_de_prueba
    estado = lento.estado()
    estado["pasos"]["inventado"] = 1.0
    estado["corriendo"] = True
    assert lento.estado()["pasos"] == {} and lento.estado()["corriendo"] is False


# ── El estado viaja en el latido ─────────────────────────────────────────────

def test_el_latido_lleva_el_estado_del_ciclo_lento(con, lento_de_prueba, latido_quieto):
    lento, trabajo = lento_de_prueba
    snapshotter.vuelta(con, 0, lento)
    assert trabajo.entro.wait(5)
    snapshotter.vuelta(con, 1, lento)

    latido = json.loads((config.HUB_HOME / salud.ARCHIVO_LATIDO).read_text())
    assert latido["lento"]["corriendo"] is True
    assert latido["lento"]["dentro"] is False
    assert latido["en"] and latido["pid"]


def test_un_estado_que_no_se_puede_leer_no_deja_al_hub_sin_latido(con, latido_quieto, capsys):
    """El latido es lo que dice «estoy vivo» (decisión 289): no se pierde por
    un dato de más."""
    class Roto:
        def estado(self):
            raise RuntimeError("estado ilegible")

        def pedir(self):
            return True

    snapshotter.vuelta(con, 1, Roto())
    assert salud.muestreo()["estado"] == "ok"
    assert "estado ilegible" in capsys.readouterr().out
    assert latido_quieto.count("muestra") == 1


# ── El plazo del latido ──────────────────────────────────────────────────────

def test_el_latido_va_a_plazo_fijo_y_no_duerme_veinte_segundos_despues_de_cada_vuelta():
    """Dormir el intervalo entero DESPUÉS de la vuelta hacía que el periodo
    fuera 20 s más lo que durase: 22,9 s de media, medido."""
    intervalo = config.INTERVALO_SEGUNDOS
    assert snapshotter.espera_hasta_la_siguiente(0) == intervalo
    assert snapshotter.espera_hasta_la_siguiente(2.9) == pytest.approx(intervalo - 2.9)
    # Una vuelta más larga que el intervalo no deja el bucle girando sin pausa.
    assert snapshotter.espera_hasta_la_siguiente(intervalo + 55) == 1


# ── Dos conexiones de verdad sobre la misma base ─────────────────────────────

def test_cincuenta_muestras_mientras_el_ciclo_lento_reescribe_no_chocan(
    con, tmp_path, monkeypatch, capsys
):
    """Lo que cambia de verdad con el hilo: dos conexiones del mismo proceso
    escribiendo a la vez. Aquí el ciclo lento es el de verdad —repos con git,
    servicios, índice, consumo, máquina y la copia de la base, cada uno
    escribiendo sus tablas— y sólo se sustituye lo que saldría de la máquina
    (docker y PowerShell). Ni una muestra ni un paso pueden toparse con
    «database is locked»."""
    if not shutil.which("git"):
        pytest.skip("git no disponible")
    repo = tmp_path / "repo"
    repo.mkdir()
    for orden in (["init", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                  ["commit", "--allow-empty", "-m", "uno"]):
        subprocess.run(["git", "-C", str(repo), *orden], check=True, capture_output=True)
    yml = tmp_path / "projects.yml"
    yml.write_text(f"proyectos:\n  - id: demo\n    nombre: Demo\n    asiento: {repo}\n", encoding="utf-8")
    monkeypatch.setenv("HUB_PROJECTS_YML", str(yml))

    registro = tmp_path / "transcripts" / "-tmp-demo"
    registro.mkdir(parents=True)
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(registro.parent))
    (registro / "s1.jsonl").write_text("\n".join(json.dumps({
        "type": "assistant", "cwd": str(repo), "requestId": f"req_{n}",
        "timestamp": "2026-08-20T10:00:00.000Z", "uuid": f"u{n}",
        "message": {"model": "claude-opus-5", "usage": {"input_tokens": 2, "output_tokens": 10 + n}},
    }) for n in range(40)) + "\n", encoding="utf-8")

    monkeypatch.setattr(servicios, "listar", lambda: [
        {"nombre": f"demo-{n}", "imagen": "pg", "estado": "running", "detalle": "Up", "creado": ""}
        for n in range(5)])
    monkeypatch.setattr(maquina, "medir", lambda: [
        maquina.Medida(f"disco.prueba{n}", float(n), "", "%") for n in range(8)])
    snapshotter._RACHAS_LENTO.clear()

    parar = threading.Event()
    vueltas = []

    def reescribir(con_lenta, al_paso):
        while not parar.is_set():
            vueltas.append(snapshotter.ciclo_lento(con_lenta, al_paso))

    lento = snapshotter.CicloLento(trabajo=reescribir,
                                   conectar=lambda: db.conectar(tmp_path / "hub.db"))
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [
        {"session": "demo", "window_idx": i, "pane_idx": 0, "pane_id": f"%{i}", "cwd": str(repo),
         "titulo": f"Tarea {i}", "comando": "bash", "activo": i == 0} for i in range(6)])
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo',?)", (str(repo),))
    atribuidor = Atribuidor([Proyecto(id="demo", nombre="Demo", asiento=str(repo))])

    assert lento.pedir() is True
    muestras = []
    limite = time.monotonic() + 60
    try:
        # Al menos cincuenta, y sin parar hasta que el ciclo lento haya dado
        # tres vueltas enteras con muestras cayéndole encima: cincuenta
        # muestras solas acaban antes de que git conteste la primera vez.
        while len(muestras) < 50 or len(vueltas) < 3:
            assert time.monotonic() < limite, f"{len(vueltas)} vueltas lentas en un minuto"
            muestras.append(snapshotter.capturar(con, atribuidor))
    finally:
        parar.set()
    assert _hasta(lambda: not lento.estado()["corriendo"], 30)

    assert all(muestras) and len(set(muestras)) == len(muestras)
    dicho = capsys.readouterr().out
    assert "locked" not in dicho and "falló" not in dicho, dicho
    assert lento.estado()["fallo"] is None
    for vuelta in vueltas:
        assert vuelta["repos"] == 1 and vuelta["servicios"] == 5 and vuelta["maquina"] == 8, vuelta
        assert vuelta["consumo"] == 1 and vuelta["indice"], vuelta
    # Y lo que dejó cada uno está entero.
    assert con.execute("SELECT COUNT(*) FROM servicio").fetchone()[0] == 5
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 40
    assert con.execute("SELECT COUNT(*) FROM panel WHERE snapshot_id=?", (muestras[-1],)).fetchone()[0] == 6


# ── Revisión de C-0309 ───────────────────────────────────────────────────────

def test_el_ciclo_lento_de_un_hilo_no_mide_el_sai(tmp_path, pasos_de_mentira, monkeypatch):
    """El SAI se queda en el latido (decisión 249), y sólo ahí: leído también
    por el hilo lento, su lectura vieja pisaba la fresca del latido."""
    pedido = []
    monkeypatch.setattr(maquina, "escanear", lambda con, **k: pedido.append(k) or 0)
    lento = snapshotter.CicloLento(conectar=lambda: db.conectar(tmp_path / "hub.db"))
    lento.pedir()
    assert _hasta(lambda: lento.estado()["acabo"] is not None)
    assert pedido == [{"sai": False}]


def test_dentro_del_latido_y_sin_hilo_el_ciclo_lento_mide_el_sai_como_siempre(con, pasos_de_mentira, monkeypatch):
    pedido = []
    monkeypatch.setattr(maquina, "escanear", lambda con, **k: pedido.append(k) or 0)
    snapshotter.ciclo_lento(con)
    assert pedido == [{"sai": True}]


def test_si_los_pasos_lanzan_la_vuelta_acaba_pero_dice_cuales_fallaron(tmp_path, pasos_de_mentira, monkeypatch):
    """🔴 Lo que la primera versión dejaba pasar: con las mediciones lanzando
    una tras otra, la vuelta «acababa bien» (cada paso va en su `try`) y la
    fila de Salud salía en verde sobre cifras que nadie refrescaba."""
    def revienta(*a, **k):
        raise OSError(5, "Input/output error")

    for modulo in (repos, consumo, busqueda):
        monkeypatch.setattr(modulo, "reindexar" if modulo is busqueda else "escanear", revienta)
    lento = snapshotter.CicloLento(conectar=lambda: db.conectar(tmp_path / "hub.db"))
    lento.pedir()
    assert _hasta(lambda: lento.estado()["acabo"] is not None)
    estado = lento.estado()
    assert estado["fallo"] is None, "la vuelta acabó: lo que falló fueron pasos"
    assert set(estado["fallaron"]) == {"repos", "consumo", "indice"}
    assert "Input/output error" in estado["fallaron"]["repos"]
    json.dumps(estado)


def test_lo_que_se_conserva_porque_no_se_pudo_preguntar_no_cuenta_como_fallo(tmp_path, pasos_de_mentira, monkeypatch):
    """Docker apagado o sin instalar es lo normal en muchas máquinas: si
    contase, la fila estaría siempre en aviso y se aprendería a no mirarla."""
    def docker_apagado(*a, **k):
        raise servicios.NoRespondio("docker no está instalado")

    monkeypatch.setattr(servicios, "escanear", docker_apagado)
    lento = snapshotter.CicloLento(conectar=lambda: db.conectar(tmp_path / "hub.db"))
    lento.pedir()
    assert _hasta(lambda: lento.estado()["acabo"] is not None)
    assert lento.estado()["fallaron"] == {}


def test_lo_que_fallo_en_la_ultima_vuelta_se_sigue_viendo_mientras_corre_la_siguiente(tmp_path):
    soltar = threading.Event()
    veces = []

    def trabajo(con, al_paso):
        veces.append(1)
        if len(veces) == 1:
            al_paso("repos")
            al_paso("repos", 0.1, "OSError: roto")
        else:
            soltar.wait(10)

    lento = snapshotter.CicloLento(trabajo=trabajo,
                                   conectar=lambda: db.conectar(tmp_path / "hub.db"))
    try:
        lento.pedir()
        assert _hasta(lambda: lento.estado()["acabo"] is not None)
        lento.pedir()
        assert _hasta(lambda: len(veces) == 2)
        assert lento.estado()["fallaron"] == {"repos": "OSError: roto"}
    finally:
        soltar.set()
    assert _hasta(lambda: not lento.estado()["corriendo"])
    assert lento.estado()["fallaron"] == {}, "la vuelta que acaba de terminar no tuvo fallos"
