"""Sin `git`, el hub calla en vez de mentir.

El proyecto nació de encontrar 473 commits sin respaldar (§1). La cifra de
respaldo es, por tanto, la única del hub que no se puede equivocar en la
dirección tranquilizadora.

Y se equivocaba. Medido en la auditoría del 1 de septiembre, sobre una base que
YA tenía una medición buena: con git, 2 commits sin respaldo y 1 repo en riesgo;
quitando git del PATH y reescaneando, `repos.escanear` hacía su `DELETE FROM
repo` incondicional, insertaba cero filas, y la pantalla afirmaba «0 commits sin
respaldo». No era un cero inicial: **borraba la medición buena**.

Docker ya lo hacía bien —`NoRespondio` conserva la última lectura— y esto es lo
mismo para git.
"""

from __future__ import annotations

import shutil

import pytest

from hub import api, db, registry, repos
from hub.models import Proyecto


@pytest.fixture
def repo_con_trabajo_sin_respaldar(tmp_path, monkeypatch):
    """Un repo de verdad: dos commits que no están en su remoto."""
    import subprocess

    remoto = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remoto)], check=True)
    trabajo = tmp_path / "trabajo"
    trabajo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(trabajo), *args], check=True,
                       capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", "main", str(trabajo)], check=True)
    git("config", "user.email", "t@t")
    git("config", "user.name", "T")
    (trabajo / "a.txt").write_text("uno")
    git("add", ".")
    git("commit", "-qm", "uno")
    git("remote", "add", "origin", str(remoto))
    git("push", "-q", "origin", "main")
    for n in ("dos", "tres"):
        (trabajo / f"{n}.txt").write_text(n)
        git("add", ".")
        git("commit", "-qm", n)

    monkeypatch.setenv("HUB_HOME", str(tmp_path / "home"))
    return Proyecto(id="p", nombre="P", dominio="personal", asiento=str(trabajo))


@pytest.fixture(autouse=True)
def _cache_limpia():
    """`_hay_git` lleva `lru_cache`: sin vaciarla, el test mide la respuesta de antes.

    Se vacía también al SALIR, o el siguiente test hereda un «no hay git» que
    nadie puso — la contaminación entre tests es un falso rojo tan caro como un
    falso verde.
    """
    repos._hay_git.cache_clear()
    yield
    repos._hay_git.cache_clear()


def _sin_git(monkeypatch):
    monkeypatch.setattr(
        shutil, "which", lambda nombre: None if nombre == "git" else "/usr/bin/" + nombre
    )
    repos._hay_git.cache_clear()


def test_con_git_se_mide(repo_con_trabajo_sin_respaldar, tmp_path):
    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    registry.sincronizar(con, [repo_con_trabajo_sin_respaldar])
    repos.escanear(con, [repo_con_trabajo_sin_respaldar])
    r = api.respaldo(con)
    assert r["commits_sin_respaldo"] == 2
    assert r["repos_en_riesgo"] == 1
    assert r["hay_git"] is True


def test_sin_git_no_borra_la_medicion_buena(
    repo_con_trabajo_sin_respaldar, tmp_path, monkeypatch
):
    """El corazón del asunto: reescanear sin git no puede destruir lo medido."""
    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    registry.sincronizar(con, [repo_con_trabajo_sin_respaldar])
    repos.escanear(con, [repo_con_trabajo_sin_respaldar])

    _sin_git(monkeypatch)
    with pytest.raises(repos.RespaldoNoMedido):
        repos.escanear(con, [repo_con_trabajo_sin_respaldar])

    r = api.respaldo(con)
    assert r["commits_sin_respaldo"] == 2, "se perdió la medición buena"
    assert r["repos_en_riesgo"] == 1


def test_sin_git_la_pantalla_puede_decirlo(tmp_path, monkeypatch):
    """`hay_git` es lo que separa «no hay nada» de «no he mirado»."""
    _sin_git(monkeypatch)
    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    assert api.respaldo(con)["hay_git"] is False


def test_el_aviso_se_pinta_de_verdad_y_antes_de_las_cifras(tmp_path, monkeypatch):
    """Debajo de las cifras no sirve: para entonces ya se han leído.

    🔴 La primera versión de este test comparaba índices de subcadena sobre el
    TEXTO CRUDO de la plantilla y no renderizaba nada: habría pasado igual con
    el bloque dentro de un `{% if false %}`. Comprobaba que el aviso estuviera
    escrito, no que llegara a verse — que es justo la distinción que este
    proyecto lleva toda la auditoría persiguiendo.
    """
    from fastapi.testclient import TestClient

    from hub import web

    _sin_git(monkeypatch)
    html = TestClient(web.app).get("/respaldo").text

    assert "no está en el PATH" in html, "el aviso no llegó a pintarse"
    assert html.index("no está en el PATH") < html.index('class="cifras"')


def test_con_git_el_aviso_no_aparece(tmp_path):
    """El control negativo: un aviso que sale siempre deja de leerse."""
    from fastapi.testclient import TestClient

    from hub import web

    assert "no está en el PATH" not in TestClient(web.app).get("/respaldo").text
