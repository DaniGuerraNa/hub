"""`hub preguntar`, ejecutado de verdad contra un hub levantado.

Mismo arnés que `test_lienzo_cli`: se levanta uvicorn y se corre el `bin/hub`
como lo correría un agente. Es la única forma de cubrir lo que de verdad falla
aquí —que el CLI y la API se hablen—, y de hecho el primer defecto que cazó fue
justo de ese tipo: `opcion()` CONSUME el argumento al leerlo, y `--vence` se
leía dos veces, así que el aviso de «sin --vence» salía cuando sí se había
puesto. Ningún test de módulo lo habría visto.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hub import canal, config, db

CLI = Path(__file__).resolve().parents[1] / "semillas" / "asistente" / "bin" / "hub"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def hub_vivo(tmp_path, monkeypatch):
    """Un hub de verdad, con su propio HUB_HOME y su propia base."""
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    puerto = _puerto_libre()
    entorno = {
        **os.environ,
        "HUB_HOME": str(tmp_path),
        "HUB_PROJECTS_YML": str(tmp_path / "p.yml"),
        "HUB_PORT": str(puerto),
    }

    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('demo','Demo')")
    canal.anotar_contacto(con, 777, "ana_t", "Ana")
    canal.editar_usuario(con, 777, alias="ana", estado="activo")
    for accion in canal.ACCIONES:
        canal.conceder(con, 777, "demo", accion)
    con.commit()
    con.close()

    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "hub.web:app",
         "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
        env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import urllib.request
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/preguntas", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proceso.terminate()
        pytest.skip("el hub de pruebas no llegó a levantar")

    yield entorno, tmp_path
    proceso.terminate()
    proceso.wait(timeout=10)


def _hub(entorno, *args, entrada: str | None = None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        env=entorno, input=entrada, capture_output=True, text=True, timeout=30,
    )


def _preguntas(raiz):
    con = db.conectar(raiz / "hub.db")
    filas = [dict(f) for f in con.execute("SELECT * FROM canal_pregunta ORDER BY id")]
    con.close()
    return filas


def test_varias_preguntas_separadas_por_guiones_van_en_un_lote(hub_vivo):
    entorno, raiz = hub_vivo
    r = _hub(entorno, "preguntar", "--proyecto", "demo", "--a", "ana",
             "--panel", "%7", "--texto", "-",
             entrada="¿la primera?\n---\n¿la segunda?\n---\n¿la tercera?\n")

    assert r.returncode == 0, r.stderr
    assert "VUELVEN JUNTAS" in r.stdout

    filas = _preguntas(raiz)
    assert [f["texto"] for f in filas] == ["¿la primera?", "¿la segunda?", "¿la tercera?"]
    lotes = {f["lote"] for f in filas}
    assert len(lotes) == 1 and lotes != {None}


def test_una_sola_pregunta_no_crea_lote(hub_vivo):
    """El lote es opcional: quien manda una duda suelta se comporta como antes."""
    entorno, raiz = hub_vivo
    r = _hub(entorno, "preguntar", "--proyecto", "demo", "--a", "ana",
             "--texto", "-", entrada="¿una sola?\n")

    assert r.returncode == 0, r.stderr
    assert "VUELVEN JUNTAS" not in r.stdout
    assert _preguntas(raiz)[0]["lote"] is None


def test_el_aviso_de_sin_vence_NO_sale_cuando_si_se_puso(hub_vivo):
    """🔴 El defecto que hizo nacer este archivo.

    `opcion()` borra el argumento de la lista al leerlo. Leerlo dos veces daba
    None la segunda, así que el CLI avisaba de que faltaba `--vence` mientras lo
    guardaba correctamente en la base. Un aviso que miente se aprende a ignorar,
    y éste protege de un lote que no vuelve nunca.
    """
    entorno, raiz = hub_vivo
    r = _hub(entorno, "preguntar", "--proyecto", "demo", "--a", "ana",
             "--panel", "%7", "--vence", "2030-01-01T00:00:00+00:00",
             "--texto", "-", entrada="¿A?\n---\n¿B?\n")

    assert r.returncode == 0, r.stderr
    assert "Sin `--vence`" not in r.stdout
    assert all(f["vence_en"] == "2030-01-01T00:00:00+00:00" for f in _preguntas(raiz))


def test_sin_vence_el_lote_avisa_de_que_puede_no_volver_nunca(hub_vivo):
    entorno, _ = hub_vivo
    r = _hub(entorno, "preguntar", "--proyecto", "demo", "--a", "ana",
             "--panel", "%7", "--texto", "-", entrada="¿A?\n---\n¿B?\n")

    assert "Sin `--vence`" in r.stdout
