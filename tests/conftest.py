from __future__ import annotations

import os

import pytest

from hub import config, db, tmux


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
def _hostname_fijo(monkeypatch):
    """La máquina de los tests se llama `DESKTOP`, se ejecuten donde se ejecuten.

    🔴 Cuatro archivos usan `"DESKTOP"` como el título que tmux pone a una
    shell, y `tmux._titulo_por_defecto()` lo comparaba con el hostname REAL.
    Coincidía sólo porque la máquina donde nació la suite se llama así: la
    primera persona que clonó el repo (3-sep) tuvo una prueba en rojo sin haber
    tocado nada. Una medición que coincide puede estar mal igual (regla 19).
    """
    monkeypatch.setattr(tmux, "_titulo_por_defecto", lambda: {"desktop"})


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
    # 🔴 Y el registro de Claude Code, por lo mismo y en la dirección segura.
    # `consumo.carpeta()` cae por omisión a `~/.claude/projects`, o sea 1,5 GB
    # de transcripts REALES de quien ejecuta la suite: un test que se olvidara de
    # apuntarlo a otro sitio no fallaría, tardaría diez segundos y daría cifras
    # distintas en cada máquina. Apuntando a una carpeta que no existe, el que se
    # olvide se lleva un `ConsumoNoMedido` y se entera.
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(tmp_path / "registro-que-no-existe"))
    # Y el laboratorio del navegador: en la máquina de quien ejecuta puede haber
    # preguntas pendientes de verdad, y el raíl las contaría en cada pantalla.
    monkeypatch.setenv("NAV_DATOS", str(tmp_path / "navegador-lab-que-no-existe"))
    # Y Reuniones: por omisión lee las grabaciones de verdad en `D:` y la llave
    # del agente se escribiría en su carpeta real (decisión 280).
    monkeypatch.setenv("REUNIONES_RAIZ", str(tmp_path / "reuniones-que-no-existen" / "grabaciones"))
    monkeypatch.setenv("REUNIONES_AGENTE", str(tmp_path / "agente-que-no-existe"))
    # Y los componentes mismos (decisión 293): sin esto, la suite medía el
    # laboratorio y el procesado de verdad de quien la ejecuta, y «preparado»
    # dependía de su máquina.
    monkeypatch.setenv("NAV_LAB", str(tmp_path / "laboratorio-que-no-existe"))
    monkeypatch.setenv("REUNIONES_PROYECTO", str(tmp_path / "procesado-que-no-existe"))
    # Y el estado que Claude Code escribe de cada sesión viva (decisión 270): el
    # orquestador lo consulta en cada espera, y en la máquina de quien ejecuta
    # la suite hay sesiones reales en paneles `%5` de verdad.
    from hub import orquestador
    monkeypatch.setattr(orquestador, "_sesiones_de_claude",
                        lambda: tmp_path / "sesiones-que-no-existen")
    # 🔴 Y la consulta de versión nueva (decisión 286): el ciclo lento hace un
    # `git ls-remote` al repo publicado. La suite no sale a internet; los tests
    # de `version` la encienden a propósito contra un repo local.
    monkeypatch.setenv("HUB_BUSCAR_VERSIONES", "0")


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
