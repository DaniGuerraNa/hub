"""El despliegue de un encargo: que se pare donde tiene que pararse.

🔴 Casi todo lo de aquí prueba que NO se despliega. Este script empuja archivos
a un servidor donde viven las betas de otros proyectos y recarga el Caddy que
las sirve a todas, así que lo que hay que fijar no es que suba bien: es que se
niegue en cuanto algo no cuadra, y antes de tocar nada.

Ninguna prueba sale a la red: `ssh`, `rsync`, `curl` y `docker` se sustituyen por
guiones de mentira que apuntan lo que se les pidió.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GUION = RAIZ / "scripts" / "desplegar-encargo.sh"


@pytest.fixture
def mvp(tmp_path):
    carpeta = tmp_path / "mvp"
    carpeta.mkdir()
    (carpeta / "index.html").write_text("<h1>Los fiados de hoy</h1>", encoding="utf-8")
    return carpeta


@pytest.fixture
def falsos(tmp_path):
    """`ssh`, `rsync`, `curl` y `docker` de mentira, con su bitácora.

    Cada uno apunta en `bitacora.txt` con qué se le llamó. Es lo que permite
    afirmar «no se subió nada» en vez de sólo «devolvió error», que es una
    garantía mucho más floja para un script que escribe en un servidor ajeno.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir()
    bitacora = tmp_path / "bitacora.txt"

    def guion(nombre: str, cuerpo: str) -> None:
        ruta = binarios / nombre
        ruta.write_text(
            f'#!/usr/bin/env bash\necho "{nombre} $*" >> "{bitacora}"\n{cuerpo}\n',
            encoding="utf-8",
        )
        ruta.chmod(0o755)

    # `ssh` contesta a las dos preguntas que le hace el guion: si se puede
    # entrar (sí) y si Caddy lee el directorio de sitios (por omisión, no).
    guion("ssh", f'''
case "$*" in
  *"import /opt/encargos/sites"*) [ -f "{tmp_path}/hay-import" ] && exit 0 || exit 1 ;;
  *) cat >/dev/null 2>&1 || true; exit 0 ;;
esac''')
    guion("rsync", "exit 0")
    guion("scp", "exit 0")
    guion("curl", 'printf 200')
    return {"bin": binarios, "bitacora": bitacora, "raiz": tmp_path}


def corre(falsos, *args):
    entorno = {**os.environ, "PATH": f"{falsos['bin']}:{os.environ['PATH']}", "HUB_DOMINIO_ENCARGOS": "ejemplo.com"}
    return subprocess.run(["bash", str(GUION), *args], capture_output=True,
                          text=True, timeout=60, env=entorno)


def bitacora(falsos) -> str:
    ruta = Path(falsos["bitacora"])
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else ""


# ── Lo que para el despliegue antes de tocar nada ───────────────────────────


def test_un_nombre_provisional_tambien_se_despliega(falsos, mvp):
    """Decisión 232: el nombre no bloquea. Si la ficha no sabe cómo se llama el
    negocio, sale como `encargo-3.ejemplo.com`, que es feo y funciona."""
    (Path(falsos["raiz"]) / "hay-import").write_text("", encoding="utf-8")
    r = corre(falsos, "encargo-3", str(mvp), "vps-test")
    assert r.returncode == 0 and "encargo-3.ejemplo.com" in r.stdout


def test_un_id_que_no_sirve_de_subdominio_se_rechaza(falsos, mvp):
    for malo in ("Abarrotes", "abarrotes_rosa", "-rosa", "../etc"):
        r = corre(falsos, malo, str(mvp), "vps-test", "--va")
        assert r.returncode != 0, malo


def test_sin_index_no_se_sube_nada(falsos, tmp_path):
    """La URL daría un listado de archivos o un 404, y quien la abra creerá que
    se rompió el servidor en vez de que falta la página."""
    vacia = tmp_path / "vacia"
    vacia.mkdir()

    r = corre(falsos, "abarrotes-rosa", str(vacia), "vps-test", "--va")

    assert r.returncode != 0 and "index.html" in r.stderr
    assert bitacora(falsos) == ""


def test_sin_la_linea_import_se_para_y_explica_quien_tiene_que_ponerla(falsos, mvp):
    """🔴 Y no la pone este script.

    El Caddyfile principal es de otro proyecto y su propio despliegue lo
    regenera entero: una línea añadida desde aquí desaparecería sola y sin
    aviso, y el encargo dejaría de responder sin que nada lo relacionara.
    """
    r = corre(falsos, "abarrotes-rosa", str(mvp), "vps-test", "--va")

    assert r.returncode != 0
    assert "import /opt/encargos/sites/*.caddy" in r.stderr + r.stdout
    assert "rsync" not in bitacora(falsos)


# ── El ensayo, que es lo que pasa por omisión ───────────────────────────────


def test_sin_pedirlo_es_un_ensayo_y_no_escribe_en_el_servidor(falsos, mvp):
    """Lo mismo que `publicar.sh`: lo que toca algo ajeno se mira antes."""
    (Path(falsos["raiz"]) / "hay-import").write_text("", encoding="utf-8")

    r = corre(falsos, "abarrotes-rosa", str(mvp), "vps-test")

    assert r.returncode == 0
    assert "ENSAYO" in r.stdout
    assert "-avzn" in bitacora(falsos)      # rsync en seco
    assert "mkdir" not in bitacora(falsos)


# ── Cuando sí va ────────────────────────────────────────────────────────────


def test_el_bloque_de_caddy_sirve_archivos_y_no_levanta_nada(falsos, mvp):
    """🔴 Un MVP de encargo es estático, y eso es la decisión, no una carencia.

    Sin base de datos que respaldar, sin proceso que se caiga un sábado y sin
    secreto que guardar: es lo que hace verdad por construcción que la v1 sea
    para mirar y no para depender.
    """
    (Path(falsos["raiz"]) / "hay-import").write_text("", encoding="utf-8")

    r = corre(falsos, "abarrotes-rosa", str(mvp), "vps-test")

    assert "file_server" in r.stdout
    assert "reverse_proxy" not in r.stdout


def test_caddy_se_recarga_por_nombre_exacto_y_no_se_reinicia(falsos, mvp):
    """Regla dura 12, y un motivo concreto: detrás de ese Caddy hay betas de
    otros proyectos, y reiniciarlo les cortaría las conexiones a todas."""
    # Sólo lo ejecutable: el comentario que explica por qué NO se hace nombra
    # `docker restart $(docker ps -q)` a propósito, y buscarlo en el texto
    # entero haría fallar al script por documentar bien su propio peligro.
    ordenes = "\n".join(l for l in GUION.read_text(encoding="utf-8").splitlines()
                        if not l.lstrip().startswith("#"))

    assert "caddy reload" in ordenes
    assert "docker restart" not in ordenes
    assert "$(docker ps" not in ordenes


def test_desplegar_no_es_funcionar_y_se_comprueba_la_url(falsos, mvp):
    """Un rsync que devuelve 0 y un reload que no se queja conviven con un 502."""
    fuente = GUION.read_text(encoding="utf-8")

    assert "curl" in fuente and "http_code" in fuente


def test_sin_decir_que_caddy_es_no_se_recarga_ninguno(falsos, mvp):
    """🔴 Adivinar cuál es recargaría el proxy que sirve lo de otros proyectos.

    No hay valor por omisión a propósito: el nombre depende de la máquina, y
    cablear el de una la convierte en la suposición de todas.
    """
    (Path(falsos["raiz"]) / "hay-import").write_text("", encoding="utf-8")

    r = corre(falsos, "abarrotes-rosa", str(mvp), "vps-test", "--va")

    assert r.returncode != 0 and "HUB_CADDY" in r.stderr
    assert "rsync" not in bitacora(falsos)


# ── Una app, no un sitio: contenedor propio y acceso (decisión 244) ─────────


@pytest.fixture
def app_(tmp_path):
    carpeta = tmp_path / "encargo" / "app"
    (carpeta / "static").mkdir(parents=True)
    (carpeta / "main.py").write_text("app = None", encoding="utf-8")
    (carpeta / "static" / "index.html").write_text("<h1>Citas</h1>", encoding="utf-8")
    (carpeta.parent / "acceso.bcrypt").write_text("$2b$12$hashdeprueba\n", encoding="utf-8")
    return carpeta


def test_una_app_sin_acceso_no_se_publica(falsos, app_):
    (app_.parent / "acceso.bcrypt").unlink()
    r = corre(falsos, "citas", str(app_))
    assert r.returncode == 1 and "acceso" in r.stderr
    assert "rsync" not in bitacora(falsos)


def test_el_bloque_de_una_app_pone_el_acceso_delante_y_no_sirve_archivos(falsos, app_):
    (falsos["raiz"] / "hay-import").touch()
    r = corre(falsos, "citas", str(app_))
    assert r.returncode == 0, r.stderr
    assert "basic_auth" in r.stdout and "$2b$12$hashdeprueba" in r.stdout
    assert "reverse_proxy encargo-citas:8000" in r.stdout
    assert "file_server" not in r.stdout
    assert "encargo-citas" in r.stdout      # dice que levantaría el contenedor
    # Ensayo: ni docker ni rsync de verdad.
    assert "docker" not in bitacora(falsos)


def test_al_publicar_una_app_el_contenedor_va_por_su_nombre_exacto(falsos, app_):
    """Regla dura 12: se toca UN contenedor, el de este encargo, por nombre."""
    (falsos["raiz"] / "hay-import").touch()
    entorno = {**os.environ, "PATH": f"{falsos['bin']}:{os.environ['PATH']}", "HUB_DOMINIO_ENCARGOS": "ejemplo.com", "HUB_CADDY": "caddy"}
    # `docker exec … /salud` y `docker build/run` pasan por el ssh falso, que
    # contesta 0 a todo; `curl` devuelve 200.
    r = subprocess.run(["bash", str(GUION), "citas", str(app_), "vps", "--va"],
                       capture_output=True, text=True, timeout=60, env=entorno)
    assert r.returncode == 0, r.stderr + r.stdout
    registro = bitacora(falsos)
    assert "docker rm -f encargo-citas" in registro
    assert "docker run -d --name encargo-citas" in registro
    assert "docker build -q -t encargo-citas" in registro
    assert "respaldo-encargos" in registro
    assert "docker ps -q" not in registro and "docker stop $(" not in registro


def test_sin_dominio_no_publica_bajo_ninguno_por_omision(falsos, app_):
    """Tenía el dominio del autor como valor por omisión: otra persona que lo
    lanzara a mano publicaba bajo él sin enterarse. Visto revisando a ojo la
    versión del 13-oct antes de publicarla."""
    entorno = {k: v for k, v in os.environ.items() if k != "HUB_DOMINIO_ENCARGOS"}
    entorno["PATH"] = f"{falsos['bin']}:{os.environ['PATH']}"

    r = subprocess.run(["bash", str(GUION), "citas", str(app_), "vps"],
                       capture_output=True, text=True, timeout=60, env=entorno)

    assert r.returncode != 0 and "HUB_DOMINIO_ENCARGOS" in r.stderr
    assert "ssh" not in bitacora(falsos)
