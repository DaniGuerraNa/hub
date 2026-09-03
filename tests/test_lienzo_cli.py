"""`hub lienzo`, ejecutado de verdad contra un hub levantado.

No se importa el script ni se simula la red: se levanta uvicorn en un puerto
libre y se corre el `bin/hub` como lo correría un agente. Es la única forma de
que el test cubra lo que de verdad falla aquí — que el CLI y la API se hablen.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hub import config, lienzos

CLI = Path(__file__).resolve().parents[1] / "semillas" / "asistente" / "bin" / "hub"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def hub_vivo(tmp_path):
    """Un hub de verdad, en su propio puerto y con su propio HUB_HOME."""
    puerto = _puerto_libre()
    entorno = {
        **os.environ,
        "HUB_HOME": str(config.HUB_HOME),
        "HUB_PROJECTS_YML": os.environ.get("HUB_PROJECTS_YML", str(tmp_path / "p.yml")),
        "HUB_PORT": str(puerto),
    }
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "hub.web:app",
         "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
        env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Esperar a que conteste, no a que el proceso exista: arrancar tarda, y un
    # `sleep` fijo o sobra o se queda corto en la máquina de otro.
    import urllib.request
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/lienzos", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proceso.terminate()
        pytest.skip("el hub de pruebas no llegó a levantar")

    yield entorno
    proceso.terminate()
    proceso.wait(timeout=10)


def _hub(entorno, *args, entrada: str | None = None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        env=entorno, input=entrada, capture_output=True, text=True, timeout=30,
    )


def test_publicar_y_volver_a_leerlo_de_punta_a_punta(hub_vivo):
    r = _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "pedidos",
             "--titulo", "Flujo de pedidos", "--plantilla", "arquitectura",
             "--slot", "diseño", "--cuerpo", "-", entrada="piezas: []\n")

    assert r.returncode == 0, r.stderr
    assert "flujo-de-pedidos" in r.stdout

    leido = _hub(hub_vivo, "lienzo", "ver", "pedidos", "flujo-de-pedidos")
    assert leido.returncode == 0, leido.stderr
    assert "piezas: []" in leido.stdout
    assert "Flujo de pedidos" in leido.stdout


def test_el_cuerpo_multilinea_llega_entero_por_la_entrada(hub_vivo):
    """`--cuerpo -` existe porque un diagrama son varias líneas: meterlas en un
    argumento de shell obliga a escapar comillas y saltos, y ahí se rompe."""
    cuerpo = 'piezas:\n  - {id: a, nombre: "λ uno"}\n  - {id: b, nombre: "dos"}\nflujo:\n  - a -> b\n'
    _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "pedidos", "--titulo", "Multi",
         "--cuerpo", "-", entrada=cuerpo)

    assert lienzos.leer("pedidos", "multi").cuerpo == cuerpo


def test_publicar_encima_de_su_edicion_falla_y_dice_como_seguir(hub_vivo):
    """🔴 El CLI no reintenta con --forzar por su cuenta: pisar la edición del
    usuario es decisión suya."""
    _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "pedidos", "--titulo", "Flujo")

    # Como lo editaría de verdad: por la web, que conserva el frontmatter.
    lienzo = lienzos.leer("pedidos", "flujo")
    lienzos.guardar_edicion(lienzo, "lo que escribió él\n")
    marca = os.stat(lienzo.ruta).st_mtime + 600
    os.utime(lienzo.ruta, (marca, marca))

    r = _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "pedidos", "--titulo", "Flujo")

    assert r.returncode != 0
    assert "--revisar" in r.stderr
    assert lienzos.leer("pedidos", "flujo").cuerpo == "lo que escribió él\n"


def test_un_lienzo_sin_marca_de_publicacion_tampoco_se_pisa(hub_vivo):
    """🔴 Ante la duda, no se destruye.

    Un archivo traído a mano —o uno cuyo frontmatter se rompió al editarlo fuera
    de la web— no tiene `publicado_en`. Si eso se leyera como «no consta que sea
    suyo, luego puedo pisarlo», serían los DOS únicos casos donde republicar
    borra sin avisar. Se descubrió porque un test escribió el archivo entero a
    mano y la guarda dejó de saltar.
    """
    carpeta = lienzos.carpeta_de("pedidos")
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "traido.md").write_text("lo puse yo a mano\n", encoding="utf-8")

    r = _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "pedidos", "--titulo", "traido")

    assert r.returncode != 0
    assert (carpeta / "traido.md").read_text(encoding="utf-8") == "lo puse yo a mano\n"


def test_listar_y_buscar_desde_la_linea_de_comandos(hub_vivo):
    _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "pedidos", "--titulo", "Flujo de pedidos")
    _hub(hub_vivo, "lienzo", "nuevo", "--proyecto", "estudio", "--titulo", "Orden SQL",
         "--plantilla", "pasos")

    listado = _hub(hub_vivo, "lienzo", "listar", "pedidos")
    assert "flujo-de-pedidos" in listado.stdout
    assert "orden-sql" not in listado.stdout      # otro proyecto: no sale al listar

    hallado = _hub(hub_vivo, "lienzo", "buscar", "orden")
    assert "orden-sql" in hallado.stdout          # pero sí al buscar


def test_un_error_de_la_api_llega_con_su_mensaje_y_no_como_hub_caido(hub_vivo):
    """CONTROL NEGATIVO del arreglo de `HTTPError`.

    `HTTPError` hereda de `URLError`, así que sin una rama propia todo 4xx salía
    como «el hub no responde» + «mira systemctl». Se perdía el único mensaje que
    decía qué hacer, y quien lo lee concluye que el servicio está caído.
    """
    r = _hub(hub_vivo, "lienzo", "ver", "pedidos", "no-existe")
    assert r.returncode != 0
    assert "no responde" not in r.stderr
    assert "systemctl" not in r.stderr
    assert "no existe" in r.stderr


def test_con_el_hub_apagado_si_dice_que_no_responde(hub_vivo):
    """La otra mitad: el diagnóstico de «caído» tiene que seguir funcionando.

    Si el arreglo de arriba se hubiera hecho atrapando todo, este caso —el único
    donde `systemctl` es el consejo correcto— habría dejado de distinguirse.
    """
    apagado = {**hub_vivo, "HUB_PORT": "1"}     # puerto donde no escucha nadie
    r = _hub(apagado, "lienzo", "listar", "pedidos")
    assert r.returncode != 0
    assert "no responde" in r.stderr


def test_sin_argumentos_ensena_la_forma_que_funciona(hub_vivo):
    """Es lo que lee un agente para saber usarlo: si no enseña la forma correcta,
    el comando no existe para él."""
    r = _hub(hub_vivo, "lienzo")
    assert r.returncode == 0
    for pieza in ("nuevo", "--proyecto", "--titulo", "ver", "listar", "buscar"):
        assert pieza in r.stdout
