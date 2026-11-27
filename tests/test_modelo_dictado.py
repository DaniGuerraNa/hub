"""El modelo del dictado lo elige el dueño, junto al micrófono (C-0313, decisión 452).

Medido el 24-nov con su voz (banco de dictado, 40 frases): `small` 11,6 % de
WER y turbo 5,6 % por ~25 ms más en la GPU. La condición suya del 11-nov:
poder apagarlo si otra cosa necesita la memoria, y que nada lo cambie solo.

Las pruebas de extremo a extremo lanzan el servidor de verdad con un
`faster_whisper` falso: lo que se prueba es que el proceso viejo muere y el
nuevo carga, no un doble que diga que sí.
"""

from __future__ import annotations

import json
import sys
import time

import pytest

from hub import procesos, transcribir

FALSO = '''
import os
class _T:
    def __init__(s, t): s.text = t
class WhisperModel:
    def __init__(s, nombre, device="cpu", compute_type=None):
        if device == "cuda" and os.environ.get("FALSO_SIN_GPU"):
            raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")
    def transcribe(s, ruta, **k):
        if not isinstance(ruta, str):
            return [], None
        return [_T(" oído: " + open(ruta).read() + " ")], None
'''

# Un `download_model` de mentira con una caché de verdad: la carpeta de cada
# modelo, con su `model.bin`, en `FALSO_CACHE`. Bajar (sin `local_files_only`)
# no sale a internet: espera `FALSO_BAJA_S`, falla si `FALSO_BAJA` es «falla»,
# o deja la carpeta sin `model.bin` si es «a-medias» (C-0505).
UTILS = '''
import os, pathlib, time
_MODELS = {"large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo"}
def download_model(nombre, local_files_only=False):
    cache = pathlib.Path(os.environ["FALSO_CACHE"])
    carpeta = cache / nombre
    if not local_files_only:
        time.sleep(float(os.environ.get("FALSO_BAJA_S", "0")))
        if os.environ.get("FALSO_BAJA") == "falla":
            raise OSError("Connection reset by peer\\nmás detalle que no se enseña")
        carpeta.mkdir(parents=True, exist_ok=True)
        if os.environ.get("FALSO_BAJA") != "a-medias":
            (carpeta / "model.bin").write_bytes(b"pesos")
        return str(carpeta)
    hay = os.environ.get("FALSO_HAY", "small,large-v3-turbo").split(",")
    if nombre not in hay and not carpeta.is_dir():
        raise RuntimeError("not found locally")
    if nombre in hay:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "model.bin").write_bytes(b"pesos")
    return str(carpeta)
'''


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Un HUB_HOME aparte y un Whisper falso que arranca de verdad."""
    from hub import config

    falso = tmp_path / "falso" / "faster_whisper"
    falso.mkdir(parents=True)
    (falso / "__init__.py").write_text(FALSO)
    (falso / "utils.py").write_text(UTILS)
    monkeypatch.setenv("PYTHONPATH", str(falso.parent))
    monkeypatch.setenv("FALSO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "HUB_HOME", tmp_path / "hub")
    monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj: "")
    monkeypatch.setattr(transcribir, "por_omision", lambda: [sys.executable, "guion", "{audio}"])
    monkeypatch.setattr(procesos, "puede_desasir", lambda: False)
    yield tmp_path / "hub" / "voz"
    try:
        transcribir.apagar_servidor(tmp_path / "hub" / "voz" / "whisper.sock", 3)
    except RuntimeError:
        pass


def cargado(voz) -> dict | None:
    return transcribir.estado_servidor(voz / "whisper.sock")


def test_quien_nunca_eligio_sigue_con_small_como_antes(casa, monkeypatch):
    llamadas = []
    monkeypatch.setattr(transcribir, "arrancar_servidor", lambda e, **k: llamadas.append(k))
    assert transcribir.eleccion() == "small"
    transcribir._arrancar_servidor(casa / "whisper.sock")
    assert llamadas == [{"python": ""}]   # la línea de siempre, sin modelo ni dispositivo


def test_turbo_pide_la_gpu_y_nunca_cae_a_la_cpu_a_escondidas(casa, monkeypatch):
    llamadas = []
    monkeypatch.setattr(transcribir, "arrancar_servidor", lambda e, **k: llamadas.append(k))
    transcribir._guardar_eleccion("large-v3-turbo")
    transcribir._arrancar_servidor(casa / "whisper.sock")
    assert llamadas == [{"python": "", "modelo": "large-v3-turbo", "dispositivo": "cuda"}]


def test_una_eleccion_rota_o_desconocida_vuelve_a_small(casa):
    casa.mkdir(parents=True)
    (casa / "eleccion.json").write_text('{"modelo": "--borrar-todo"}')
    assert transcribir.eleccion() == "small"
    (casa / "eleccion.json").write_text("no es json")
    assert transcribir.eleccion() == "small"


def test_con_apagado_nada_carga_el_modelo_ni_al_calentar_ni_al_dictar(casa, monkeypatch):
    lanzados = []
    monkeypatch.setattr(transcribir, "arrancar_servidor", lambda e, **k: lanzados.append(k))
    monkeypatch.setattr(transcribir, "_servidor", lambda *a, **k: pytest.fail("con apagado no se pregunta al servidor"))
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, aj: "por la cpu")
    transcribir._guardar_eleccion("apagado")
    assert transcribir.calentar() == "apagado"
    medidas: dict = {}
    assert transcribir.dictado(b"x", "frase.webm", medidas=medidas) == "por la cpu"
    assert medidas["camino"] == "frio"
    assert transcribir._arrancar_servidor(casa / "whisper.sock") is None
    assert lanzados == []


def test_elegir_turbo_mata_el_anterior_y_contesta_con_turbo_ya_cargado(casa):
    transcribir.elegir("small")
    antes = cargado(casa)
    assert antes["modelo"] == "small"
    huella = procesos.huella(antes["pid"])
    estado = transcribir.elegir("large-v3-turbo")
    assert estado["eleccion"] == "large-v3-turbo"
    assert estado["cargado"]["modelo"] == "large-v3-turbo" and estado["cargado"]["dispositivo"] == "cuda"
    assert not procesos.vivo(huella)   # un zombi cuenta como muerto: ya no tiene memoria
    # Y lo dictado va por él.
    audio = casa / "frase.webm"
    audio.write_text("hola")
    assert transcribir._servidor(audio) == "oído: hola"


def test_apagar_suelta_la_memoria_antes_de_contestar(casa):
    transcribir.elegir("large-v3-turbo")
    huella = procesos.huella(cargado(casa)["pid"])
    estado = transcribir.elegir("apagado")
    assert estado["eleccion"] == "apagado" and estado["cargado"] is None
    assert not procesos.vivo(huella)   # el proceso ya no existe: la VRAM está libre
    assert not (casa / "whisper.sock").exists()


def test_si_la_gpu_falla_se_dice_y_la_eleccion_vuelve_a_la_de_antes(casa, monkeypatch):
    monkeypatch.setenv("FALSO_SIN_GPU", "1")
    with pytest.raises(RuntimeError, match="no se pudo cargar"):
        transcribir.elegir("large-v3-turbo")
    assert transcribir.eleccion() == "small"
    assert cargado(casa) is None


def test_no_se_ofrece_ni_se_deja_elegir_un_modelo_sin_descargar(casa, monkeypatch):
    monkeypatch.setenv("FALSO_HAY", "small")
    estado = transcribir.estado_dictado()
    assert {m["modelo"]: m["disponible"] for m in estado["modelos"]} == \
        {"small": True, "large-v3-turbo": False, "apagado": True}
    with pytest.raises(ValueError, match="no está descargado"):
        transcribir.elegir("large-v3-turbo")
    assert transcribir.eleccion() == "small"


def test_con_otro_transcriptor_declarado_no_hay_selector_y_se_dice_por_que(casa, monkeypatch):
    monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj: None)
    estado = transcribir.estado_dictado()
    assert estado["selector"] is False and "encargos.yml" in estado["motivo"]
    with pytest.raises(ValueError, match="encargos.yml"):
        transcribir.elegir("large-v3-turbo")


def test_un_servidor_vivo_con_otro_modelo_que_el_elegido_se_sustituye_al_calentar(casa):
    transcribir.elegir("small")
    viejo = procesos.huella(cargado(casa)["pid"])
    transcribir._guardar_eleccion("large-v3-turbo")   # lo eligió en otra pestaña, por ejemplo
    assert transcribir.calentar() == "arrancando"
    limite = time.monotonic() + 20
    while time.monotonic() < limite and not (cargado(casa) or {}).get("modelo") == "large-v3-turbo":
        time.sleep(0.1)
    assert cargado(casa)["modelo"] == "large-v3-turbo"
    assert not procesos.vivo(viejo)


def test_el_estado_solo_mira_la_gpu_si_se_pide(casa, monkeypatch):
    from hub import maquina

    monkeypatch.setattr(maquina, "gpu_memoria", lambda: pytest.fail("nvidia-smi sin pedirlo"))
    assert "gpu" not in transcribir.estado_dictado()
    monkeypatch.setattr(maquina, "gpu_memoria", lambda: (3947, 12282))
    assert transcribir.estado_dictado(gpu=True)["gpu"] == {"usada_mb": 3947, "total_mb": 12282}


def test_la_eleccion_se_guarda_solo_para_el_dueno(casa):
    transcribir._guardar_eleccion("large-v3-turbo")
    archivo = casa / "eleccion.json"
    assert json.loads(archivo.read_text()) == {"modelo": "large-v3-turbo"}
    assert oct(archivo.stat().st_mode & 0o777) == "0o600"


def test_las_rutas_del_modelo_piden_mismo_origen_y_dicen_el_error(monkeypatch):
    from fastapi.testclient import TestClient

    from hub import web

    def elegir(modelo):
        raise ValueError("Preciso (turbo, en la GPU) no está descargado en esta máquina")
    monkeypatch.setattr(transcribir, "elegir", elegir)
    monkeypatch.setattr(transcribir, "estado_dictado", lambda gpu=False: {"eleccion": "small", "gpu": gpu})
    cliente = TestClient(web.app, base_url="http://127.0.0.1:8787")
    origen = {"Origin": "http://127.0.0.1:8787"}
    r = cliente.post("/api/voz/modelo", data={"modelo": "large-v3-turbo"}, headers=origen)
    assert r.json() == {"ok": False, "error": "Preciso (turbo, en la GPU) no está descargado en esta máquina"}
    assert cliente.post("/api/voz/modelo", data={"modelo": "small"},
                        headers={"Origin": "https://malo.example"}).status_code == 403
    assert cliente.get("/api/voz/estado?gpu=1").json() == {"eleccion": "small", "gpu": True}


def _servidores_vivos(voz) -> list[int]:
    """Los servidores de Whisper de esta casa que siguen vivos, por /proc."""
    from pathlib import Path
    vivos = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            linea = (d / "cmdline").read_bytes().split(b"\0")
            estado = (d / "stat").read_text().split()[2]
        except OSError:
            continue
        if any(p.endswith(b"transcribir-servidor.py") for p in linea) and str(voz).encode() in b" ".join(linea) \
                and estado not in ("Z", "X"):
            vivos.append(int(d.name))
    return vivos


def test_una_frase_que_llega_mientras_se_cambia_no_deja_un_whisper_huerfano(casa, monkeypatch):
    """El revisor lo reprodujo: la frase que entra cuando el viejo ya murió
    arrancaba otro servidor, y `elegir` un segundo; el primero quedaba vivo
    en la GPU sin socket, y «apagado» no lo encontraba."""
    import os
    transcribir.elegir("small")
    enchufe = casa / "whisper.sock"
    marca = casa / "whisper.arrancando"
    os.utime(marca, (time.time() - 120, time.time() - 120))   # el viejo lleva minutos sirviendo
    original = transcribir._esperar_que_muera
    hecho = []

    def esperar(huella, s):
        r = original(huella, s)
        if r and not hecho:
            hecho.append(transcribir._arrancar_si_toca(enchufe, ""))   # la frase, justo en el hueco
        return r

    monkeypatch.setattr(transcribir, "_esperar_que_muera", esperar)
    estado = transcribir.elegir("large-v3-turbo")
    monkeypatch.setattr(transcribir, "_esperar_que_muera", original)
    assert hecho == [True]
    assert estado["cargado"]["modelo"] == "large-v3-turbo"   # la frase ya arrancó el nuevo
    assert len(_servidores_vivos(casa)) == 1
    transcribir.elegir("apagado")
    time.sleep(0.5)
    assert _servidores_vivos(casa) == []


def test_si_otro_ya_esta_cargando_el_elegido_elegir_le_espera_y_no_dice_que_fallo(casa, monkeypatch):
    transcribir.elegir("small")
    enchufe = casa / "whisper.sock"
    original = transcribir._arrancar_servidor

    def ya_lo_arranco_otro(e, python=""):
        original(e, python)   # lo lanza «la frase»…
        return None           # …y a `elegir` no le toca lanzar nada

    monkeypatch.setattr(transcribir, "_arrancar_servidor", ya_lo_arranco_otro)
    estado = transcribir.elegir("large-v3-turbo")
    assert estado["eleccion"] == "large-v3-turbo" and estado["cargado"]["modelo"] == "large-v3-turbo"
    assert len(_servidores_vivos(casa)) == 1 and enchufe.exists()


def test_elegir_lo_que_ya_esta_cargado_no_lo_recarga(casa):
    transcribir.elegir("large-v3-turbo")
    pid = cargado(casa)["pid"]
    transcribir.elegir("large-v3-turbo")
    assert cargado(casa)["pid"] == pid


def test_con_turbo_elegido_el_camino_frio_sigue_siendo_el_ligero_en_la_cpu(casa, monkeypatch):
    """Si turbo no está cargado, la frase no espera a la GPU: va por nuestro
    guion tal cual, que es `small` int8 en la CPU (invariante 4)."""
    transcribir._guardar_eleccion("large-v3-turbo")
    monkeypatch.setattr(transcribir, "_servidor", lambda *a, **k: None)
    usados = []
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, aj: usados.append(transcribir.comando(aj)) or "x")
    transcribir.dictado(b"x", "frase.webm")
    assert not any("--modelo" in parte or "large" in parte for parte in usados[0])


def test_ocupado_con_una_frase_no_se_dice_que_no_hay_ninguno(casa, monkeypatch):
    monkeypatch.setattr(transcribir, "estado_servidor", lambda e: None)
    monkeypatch.setattr(transcribir, "_escucha", lambda e: True)
    estado = transcribir.estado_dictado()
    assert estado["cargado"] is None and estado["ocupado"] is True


def test_el_rotulo_solo_lee_la_eleccion_sin_lanzar_nada(casa, monkeypatch):
    from hub import api
    monkeypatch.setattr(transcribir, "disponibles", lambda: pytest.fail("no debe mirar los modelos"))
    monkeypatch.setattr(transcribir, "estado_servidor", lambda e: pytest.fail("no debe preguntar al servidor"))
    transcribir._guardar_eleccion("apagado")
    assert api.voz_estado(solo_eleccion=True) == {"eleccion": "apagado", "selector": True}


def test_lo_descargado_se_recuerda_con_recordar_y_un_fallo_no_se_recuerda(casa, monkeypatch):
    """C-0496: qué modelos hay se recuerda por `recordar.por_tiempo`, no por una
    caché propia; si mirar falla, la vez siguiente vuelve a mirar."""
    import subprocess as sp

    from hub import recordar

    real = sp.run
    miradas = []

    def run(cmd, *a, **k):
        if "--disponibles" not in cmd:
            return real(cmd, *a, **k)
        miradas.append(cmd)
        if len(miradas) == 1:
            raise sp.CalledProcessError(1, cmd)
        return sp.CompletedProcess(cmd, 0, stdout='{"small": true, "large-v3-turbo": false}\n')

    monkeypatch.setattr(transcribir.subprocess, "run", run)
    assert transcribir.disponibles() == {}
    assert transcribir.disponibles() == {"small": True, "large-v3-turbo": False}
    transcribir.disponibles()["small"] = False   # lo devuelto es una copia
    assert transcribir.disponibles() == {"small": True, "large-v3-turbo": False}
    assert len(miradas) == 2
    recordar.olvidar()
    transcribir.disponibles()
    assert len(miradas) == 3


# ── Bajar un modelo sin descargar, desde el menú (C-0505) ────────────────────
#
# El guion de verdad con el `download_model` de mentira de arriba: nada sale a
# internet, pero el proceso se lanza, se le espera y deja su final escrito.

@pytest.fixture
def sin_turbo(casa, monkeypatch):
    from hub import maquina
    monkeypatch.setenv("FALSO_HAY", "small")
    monkeypatch.setattr(maquina, "gpu_memoria", lambda: (1000, 12282))
    return casa


def _esperar_descarga(espera: float = 20) -> dict:
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        d = transcribir.descarga()
        if d and d["estado"] != "bajando":
            return d
        time.sleep(0.05)
    raise AssertionError(f"la descarga no acabó: {transcribir.descarga()}")


def test_un_modelo_sin_descargar_dice_cuanto_pesa_para_su_boton(sin_turbo):
    estado = transcribir.estado_dictado()
    turbo = next(m for m in estado["modelos"] if m["modelo"] == "large-v3-turbo")
    assert turbo["disponible"] is False and estado["mirado"] is True
    assert turbo["tamano"] == 1_621_665_983 and turbo["solo_gpu"] is True
    assert estado["descarga"] is None


def test_descargar_lo_deja_elegible_sin_elegirlo_y_sin_esperar_cinco_minutos(sin_turbo):
    """`disponibles` recuerda cinco minutos: sin olvidarlo al acabar, el gris
    seguiría ahí. Y nada se elige solo."""
    assert transcribir.disponibles()["large-v3-turbo"] is False   # recordado
    d = transcribir.descargar("large-v3-turbo")
    assert d["modelo"] == "large-v3-turbo" and d["estado"] in ("bajando", "hecha")
    assert _esperar_descarga()["estado"] == "hecha"
    assert transcribir.disponibles()["large-v3-turbo"] is True
    assert transcribir.eleccion() == "small"
    assert transcribir.elegir("large-v3-turbo")["eleccion"] == "large-v3-turbo"


def test_una_descarga_que_falla_lo_dice_en_una_frase_y_el_modelo_sigue_sin_estar(sin_turbo, monkeypatch):
    monkeypatch.setenv("FALSO_BAJA", "falla")
    transcribir.descargar("large-v3-turbo")
    d = _esperar_descarga()
    assert d["estado"] == "fallo" and d["error"] == "Connection reset by peer"
    assert transcribir.disponibles()["large-v3-turbo"] is False


def test_reintentar_tras_un_fallo_baja_de_verdad_y_sigue_siendo_de_una_en_una(sin_turbo, monkeypatch):
    """El final del intento anterior quedaba en `descarga.avance`: el reintento
    salía «fallo» con el error viejo nada más pulsar, y el cerrojo dejaba
    lanzar otra encima (C-0505, revisor)."""
    monkeypatch.setenv("FALSO_BAJA", "falla")
    transcribir.descargar("large-v3-turbo")
    assert _esperar_descarga()["estado"] == "fallo"
    monkeypatch.delenv("FALSO_BAJA")
    monkeypatch.setenv("FALSO_BAJA_S", "2")
    d = transcribir.descargar("large-v3-turbo")
    assert d["estado"] == "bajando" and d["error"] == ""
    with pytest.raises(ValueError, match="de uno en uno"):
        transcribir.descargar("large-v3-turbo")
    assert len(_procesos_de_descarga()) == 1
    assert _esperar_descarga()["estado"] == "hecha"
    assert transcribir.disponibles()["large-v3-turbo"] is True


def test_el_final_de_la_descarga_no_lo_lee_nadie_mas(sin_turbo, monkeypatch):
    """Su error puede llevar rutas de la máquina: 600, como `descarga.json`."""
    monkeypatch.setenv("FALSO_BAJA", "falla")
    transcribir.descargar("large-v3-turbo")
    _esperar_descarga()
    assert (sin_turbo / "descarga.avance").stat().st_mode & 0o777 == 0o600
    assert (sin_turbo / "descarga.json").stat().st_mode & 0o777 == 0o600


def test_una_descarga_a_medias_no_sale_elegible(sin_turbo, monkeypatch):
    """Algunas `huggingface_hub` devuelven el snapshot a medias con
    `local_files_only`: sin `model.bin`, no está."""
    monkeypatch.setenv("FALSO_BAJA", "a-medias")
    transcribir.descargar("large-v3-turbo")
    assert _esperar_descarga()["estado"] == "fallo"
    assert transcribir.disponibles()["large-v3-turbo"] is False


def test_solo_una_descarga_a_la_vez(sin_turbo, monkeypatch):
    monkeypatch.setenv("FALSO_BAJA_S", "3")
    primera = transcribir.descargar("large-v3-turbo")
    assert primera["estado"] == "bajando"
    with pytest.raises(ValueError, match="de uno en uno"):
        transcribir.descargar("large-v3-turbo")
    assert len([p for p in _procesos_de_descarga()]) == 1
    assert _esperar_descarga()["estado"] == "hecha"


def _procesos_de_descarga() -> list[int]:
    from pathlib import Path
    vivos = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            linea = (d / "cmdline").read_bytes().split(b"\0")
            estado = (d / "stat").read_text().split()[2]
        except OSError:
            continue
        if b"--descargar" in linea and estado not in ("Z", "X"):
            vivos.append(int(d.name))
    return vivos


def test_una_descarga_cortada_sin_final_es_un_fallo_que_se_puede_repetir(sin_turbo, monkeypatch):
    import os
    import signal
    monkeypatch.setenv("FALSO_BAJA_S", "30")
    d = transcribir.descargar("large-v3-turbo")
    huella = json.loads((sin_turbo / "descarga.json").read_text())["huella"]
    os.kill(huella["pid"], signal.SIGKILL)
    limite = time.monotonic() + 5
    while procesos.vivo(huella) and time.monotonic() < limite:
        time.sleep(0.05)
    d = transcribir.descarga()
    assert d["estado"] == "fallo" and "vuelve a pulsar" in d["error"]
    monkeypatch.setenv("FALSO_BAJA_S", "0")
    transcribir.descargar("large-v3-turbo")
    assert _esperar_descarga()["estado"] == "hecha"


def test_no_se_baja_lo_que_ya_esta_ni_a_ciegas_ni_turbo_sin_gpu(casa, monkeypatch):
    from hub import maquina
    with pytest.raises(ValueError, match="ya está descargado"):
        transcribir.descargar("large-v3-turbo")
    with pytest.raises(ValueError, match="desconocido"):
        transcribir.descargar("--borrar-todo")
    monkeypatch.setenv("FALSO_HAY", "small")
    monkeypatch.setattr(maquina, "gpu_memoria", lambda: None)
    with pytest.raises(ValueError, match="GPU"):
        transcribir.descargar("large-v3-turbo")
    monkeypatch.setattr(transcribir, "_mirar_disponibles", lambda python: (_ for _ in ()).throw(OSError("x")))
    from hub import recordar
    recordar.olvidar()
    with pytest.raises(ValueError, match="no pude comprobar"):
        transcribir.descargar("large-v3-turbo")
    estado = transcribir.estado_dictado()
    assert estado["mirado"] is False
    assert not (casa / "descarga.json").exists()


def test_la_ruta_de_descargar_pide_mismo_origen_y_dice_el_error(monkeypatch):
    from fastapi.testclient import TestClient

    from hub import web

    def descargar(modelo):
        raise ValueError("ya se está bajando Preciso (turbo, en la GPU): de uno en uno")
    monkeypatch.setattr(transcribir, "descargar", descargar)
    monkeypatch.setattr(transcribir, "descarga", lambda: {"estado": "bajando"})
    cliente = TestClient(web.app, base_url="http://127.0.0.1:8787")
    origen = {"Origin": "http://127.0.0.1:8787"}
    r = cliente.post("/api/voz/descargar", data={"modelo": "large-v3-turbo"}, headers=origen)
    assert r.json() == {"ok": False, "error": "ya se está bajando Preciso (turbo, en la GPU): de uno en uno"}
    assert cliente.post("/api/voz/descargar", data={"modelo": "large-v3-turbo"},
                        headers={"Origin": "https://malo.example"}).status_code == 403
    assert cliente.get("/api/voz/estado?solo=descarga").json() == {"descarga": {"estado": "bajando"}}
