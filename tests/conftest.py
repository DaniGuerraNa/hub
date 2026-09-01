from __future__ import annotations

import os

import pytest

from hub import config, db


@pytest.fixture(autouse=True, scope="session")
def _tmux_aparte():
    """Los tests nunca tocan el tmux de quien los ejecuta.

    🔴 `HUB_HOME` aísla el disco y **no aísla tmux**. Hasta que existió esto,
    correr la suite en una máquina con trabajo abierto creaba —y mataba—
    sesiones en el servidor de tmux real: durante la auditoría del 1 de
    septiembre una prueba dejó una sesión suelta que hubo que borrar a mano.

    Un proyecto que se publica no puede pedirle a nadie que ejecute sus tests
    a ciegas con sus sesiones de trabajo abiertas.

    `-L` levanta un servidor de tmux distinto, con socket propio: lo que pase
    dentro no ve ni toca lo de fuera.
    """
    os.environ.setdefault("HUB_TMUX_SOCKET", "hub-tests")
    yield


@pytest.fixture(autouse=True)
def _datos_aparte(tmp_path, monkeypatch):
    """Ningún test toca los datos reales de quien los ejecuta.

    Tres cosas, y las tres se descubrieron una detrás de otra:

    - **El registro.** Sin esto `config.projects_yml()` cae al `projects.yml`
      del usuario y el resultado de la suite depende de qué proyectos tenga
      declarados ese día.

    - **`HUB_HOME`.** Se aisló después, al ver que dos ficheros de tests nuevos
      —los que usan `TestClient(web.app)`— llegaban a `web.conexion()` y
      **creaban, inicializaban y migraban con `ALTER TABLE` el `hub.db` vivo**,
      con el servicio y el snapshotter abiertos encima. No llegó a perderse
      nada, pero correr los tests no puede tocar el índice de nadie.

    - Se ponen la variable de entorno **y** el atributo del módulo: `config`
      resuelve `HUB_HOME` al importarse, así que `setenv` a solas no mueve lo
      que ya está cargado. Ésa es la mitad que se olvida.
    """
    casa = tmp_path / "hub-home"
    casa.mkdir()
    monkeypatch.setenv("HUB_HOME", str(casa))
    monkeypatch.setenv("HUB_PROJECTS_YML", str(tmp_path / "projects-vacio.yml"))
    monkeypatch.setattr(config, "HUB_HOME", casa)
    monkeypatch.setattr(config, "DB_PATH", casa / "hub.db")
    monkeypatch.setattr(config, "HUB_KITS", casa / "kits")


@pytest.fixture
def con(tmp_path):
    conexion = db.conectar(tmp_path / "hub.db")
    db.inicializar(conexion)
    yield conexion
    conexion.close()


@pytest.fixture
def proyecto_demo(con):
    con.execute(
        "INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')"
    )
    con.execute(
        "INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo','/tmp/demo','asiento')"
    )
    return "demo"
