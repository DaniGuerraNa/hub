from __future__ import annotations

import os

import pytest

import arnes_tmux
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

    🔴 Y es de esta pasada: al nombre que se pida (o `hub-tests`) se le añade
    el pid, y al acabar se apaga y se borra su socket (C-0325). Con un nombre
    compartido no se podía limpiar —dos pasadas a la vez con el mismo
    `HUB_TMUX_SOCKET` se habrían tumbado las sesiones la una a la otra— y cada
    nombre dejaba su socket muerto en `/tmp/tmux-<uid>`.
    """
    zocalo = f"{os.environ.get('HUB_TMUX_SOCKET') or 'hub-tests'}-{os.getpid()}"
    os.environ["HUB_TMUX_SOCKET"] = zocalo
    yield
    arnes_tmux.apagar(zocalo)


@pytest.fixture(autouse=True)
def _arranque_sin_espera(request, monkeypatch):
    """Una ventana de agente abierta en un test no espera su arranque (C-0325).

    `entrevistador.comprobar_arranque` duerme 1,5 s para ver si el agente
    murió al arrancar, y en la suite el agente es `cat`, que no muere: esa
    espera costaba 1,5 s por ventana abierta de verdad. El test que sí
    necesita verla —el de la ventana que muere al arrancar— lleva la marca
    `espera_de_arranque_real` y la tiene entera.
    """
    if request.node.get_closest_marker("espera_de_arranque_real"):
        return
    from hub import entrevistador
    monkeypatch.setattr(entrevistador, "ESPERA_ARRANQUE", 0)


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
def _secretario_apagado(monkeypatch):
    """El aviso de «secretario caído» mira `systemctl` de quien corre la suite:
    en la máquina del dueño está habilitado y en la de otro no. Por omisión,
    apagado; sus pruebas ponen el latido que quieren (decisión 329)."""
    from hub import avisos
    monkeypatch.setattr(avisos, "latido_secretario", lambda: (False, None))


@pytest.fixture(autouse=True)
def _systemd_quieto(monkeypatch):
    """🔴 La suite no acciona los servicios de quien la corre.

    `salud.encender` hace `systemctl --user enable --now` (decisión 400): un
    test que pasara por `/secretario/encender` le encendería el secretario de
    verdad, con su suscripción. Y lo que pinta `/secretario` depende de si hay
    systemd y de cómo está su servicio, que en cada máquina es distinto. Por
    omisión, sin systemd y sin poder ordenar nada; las pruebas de `salud`
    traen de vuelta lo real con un `systemctl` de mentira en el PATH."""
    from hub import salud
    monkeypatch.setattr(salud, "_orden", lambda *a, **k: (1, "en los tests no se acciona systemd"))
    monkeypatch.setattr(salud, "estado_servicio", lambda nombre: None)


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
    # `transcripts.raiz()` cae por omisión a `~/.claude/projects`, o sea 1,5 GB
    # de transcripts REALES de quien ejecuta la suite: un test que se olvidara de
    # apuntarlo a otro sitio no fallaría, tardaría diez segundos y daría cifras
    # distintas en cada máquina. Apuntando a una carpeta que no existe, el que se
    # olvide se lleva un `ConsumoNoMedido` (o ninguna conversación) y se entera.
    # Desde C-0049 vale para todo lo que lee transcripts, no sólo para Consumo.
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
    # Y el Puente KVM (decisión 438): su clon y su puerto. En la máquina de
    # quien ejecuta puede haber un puente de verdad escuchando, y /puente le
    # preguntaría. El puerto 1 no lo escucha nadie: «no contesta» al momento.
    monkeypatch.setenv("PUENTE_KVM", str(tmp_path / "puente-que-no-existe"))
    monkeypatch.setenv("PUENTE_PUERTO", "1")
    # Y sus datos: ahí deja las reuniones del Mac (decisión 443), y con la
    # herramienta encendida Reuniones las leería y el ciclo lento las procesaría.
    monkeypatch.setenv("PUENTE_HOME", str(tmp_path / "puente-datos-que-no-existen"))
    # Y el estudio (decisión 461), por lo mismo: el de verdad puede estar en su 8795.
    monkeypatch.setenv("ESTUDIO_PUERTO", "1")
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
    # Y las copias de la base (decisión 277, C-0417): con `HUB_RESPALDO_EXTRA`
    # en el entorno de quien ejecuta, cada test que copia una base dejaría la
    # suya en su otro disco de verdad, y podaría las suyas por el nombre.
    monkeypatch.delenv("HUB_RESPALDO", raising=False)
    monkeypatch.delenv("HUB_RESPALDO_EXTRA", raising=False)
    # Y las llaves del secretario (decisiones 304 y 311): por omisión viven en
    # `~/.secretos/` de quien ejecuta, y la de Web Push existe en cuanto el
    # servicio arrancó una vez. Un test no lee ni crea llaves reales.
    monkeypatch.setenv("HUB_SECRETARIO_WEBPUSH", str(tmp_path / "secretos" / "webpush"))
    monkeypatch.setenv("HUB_SECRETARIO_GOOGLE", str(tmp_path / "secretos" / "google"))
    monkeypatch.setenv("HUB_SECRETARIO_CORREO", str(tmp_path / "secretos" / "correo"))
    # Telegram fija su carpeta al importarse: se mueve el atributo, no sólo la variable.
    from hub.secretario.fuentes import telegram as _telegram
    monkeypatch.setattr(_telegram, "POR_OMISION", tmp_path / "secretos" / "telegram")


@pytest.fixture(autouse=True)
def _sin_recuerdos():
    """Cada test empieza sin nada recordado (`hub.recordar`, C-0310).

    Lo recordado vive en la memoria del proceso, y la suite es un solo
    proceso: un test que cambia `HOME` o reescribe un archivo con el mismo
    tamaño en el mismo instante heredaría lo que leyó el anterior."""
    from hub import recordar
    recordar.olvidar()
    yield
    recordar.olvidar()


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


@pytest.fixture
def canal_telegram():
    """El Canal de Telegram configurado: el respaldo de los avisos del
    secretario (decisión 310) sólo cuenta como listo si existe, si `hub-canal`
    leyó su token y si hay dueño en /canal (C-0060)."""
    from hub import canal, rele_base

    config.canal_yml().parent.mkdir(parents=True, exist_ok=True)
    config.canal_yml().write_text("token_ref: env:TOKEN_DE_PRUEBA\n", encoding="utf-8")
    rele_base.anotar_token("canal", "env:TOKEN_DE_PRUEBA", None)
    h = db.conectar()
    db.inicializar(h)
    canal.anotar_contacto(h, 1, "dueno", "Dueño")
    canal.marcar_dueno(h, 1)
    h.close()
    yield config.canal_yml()
