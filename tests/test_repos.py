"""Respaldo de repos.

El hub existe porque el 2026-08-27 se dieron por muertos dos worktrees con 473
commits sin respaldo. Si esta medición miente, el proyecto entero pierde sentido:
un número inflado hace que se ignore, y uno bajo hace que se pierda trabajo.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from hub import repos
from hub.models import Proyecto, Ruta


def _git(ruta, *args):
    subprocess.run(["git", "-C", str(ruta), *args], check=True, capture_output=True)


def _commit(ruta, nombre):
    (ruta / nombre).write_text(nombre, encoding="utf-8")
    _git(ruta, "add", "-A")
    _git(ruta, "commit", "-m", nombre)


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git no disponible")
    ruta = tmp_path / "repo"
    ruta.mkdir()
    _git(ruta, "init", "-b", "main")
    _git(ruta, "config", "user.email", "t@t")
    _git(ruta, "config", "user.name", "t")
    _commit(ruta, "uno")
    return ruta


@pytest.fixture
def con_remoto(repo, tmp_path):
    """Un repo con su remoto ya sincronizado, para medir lo que se añade después."""
    remoto = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "--bare", str(remoto)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(remoto))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def test_una_ruta_que_no_es_repo_no_inventa_estado(tmp_path):
    assert repos.estado_de(str(tmp_path)) is None
    assert repos.estado_de(str(tmp_path / "no-existe")) is None


def test_un_repo_sin_remoto_no_cuenta_commits_en_riesgo(repo):
    """No tener remoto es una decisión, no un descuido: no puede leerse como alarma."""
    estado = repos.estado_de(str(repo))
    assert estado["regimen"] == "sin-remoto"
    assert estado["sin_push"] is None
    assert estado["rama"] == "main"


def test_cuenta_lo_que_no_esta_en_el_remoto(con_remoto):
    _commit(con_remoto, "dos")
    _commit(con_remoto, "tres")
    estado = repos.estado_de(str(con_remoto))
    assert estado["sin_push"] == 2
    assert estado["regimen"] == "con-upstream"


def test_una_rama_sin_upstream_se_mide_contra_todos_los_remotos(con_remoto):
    """El caso real de `~/dev/app`: rama `dev`, `origin/dev` no existe.

    Comparar contra `origin/<rama>` contaba el historial entero —576 commits en
    vez de 250. Lo correcto es qué NO alcanza ningún remoto.
    """
    _git(con_remoto, "checkout", "-b", "dev")
    _commit(con_remoto, "dos")
    estado = repos.estado_de(str(con_remoto))

    assert estado["regimen"] == "sin-upstream"  # nadie sigue a `dev`
    assert estado["sin_push"] == 1  # y sólo un commit está de verdad sin respaldo


def test_detecta_los_cambios_sin_commitear(con_remoto):
    (con_remoto / "sucio.txt").write_text("x", encoding="utf-8")
    assert repos.estado_de(str(con_remoto))["sucios"] == 1


def test_cuenta_los_worktrees_extra_sin_contar_el_principal(con_remoto, tmp_path):
    assert repos.estado_de(str(con_remoto))["worktrees"] == 0
    _git(con_remoto, "worktree", "add", str(tmp_path / "wt"), "-b", "otra")
    assert repos.estado_de(str(con_remoto))["worktrees"] == 1


def test_dos_worktrees_del_mismo_commit_no_suman_dos_veces(con_remoto, tmp_path):
    """`~/dev/app` y `~/dev/app-int` son el mismo trabajo.

    Sumarlos daría 500 donde hay 250, y una cifra inflada se termina ignorando.
    """
    _commit(con_remoto, "dos")
    espejo = tmp_path / "espejo"
    _git(con_remoto, "worktree", "add", "--detach", str(espejo), "HEAD")

    medidos = [repos.estado_de(str(con_remoto)), repos.estado_de(str(espejo))]
    assert all(m["sin_push"] == 1 for m in medidos)

    unicos = repos.deduplicar(medidos)
    assert len(unicos) == 1
    assert sum(m["sin_push"] for m in unicos) == 1


def test_worktrees_en_commits_distintos_siguen_siendo_un_solo_repositorio(
    con_remoto, tmp_path
):
    """🔴 La TERCERA cifra inflada de este proyecto, y la que más costó ver.

    Medir sólo `HEAD` por worktree daba 250 + 223 = 473 el 2026-08-27, que
    coincidía con la medición a mano. **Coincidía porque los worktrees estaban
    en el mismo commit.** En cuanto una sesión semiautónoma commiteó
    en `-int` y no en la copia principal, el hub pasó a decir 1017 commits sin
    respaldo donde había 529: los mismos objetos, del mismo repositorio,
    contados hasta cuatro veces.

    Lo que se mide es el repositorio —`--all` más los HEAD de sus worktrees—, y
    por eso la cifra sale idéntica desde cualquiera de ellos.
    """
    otro = tmp_path / "otro"
    _git(con_remoto, "worktree", "add", str(otro), "-b", "rama-b")
    _commit(otro, "propio")
    _commit(con_remoto, "en-main")

    medidos = [repos.estado_de(str(con_remoto)), repos.estado_de(str(otro))]
    # Dos commits sin respaldo en el repo: uno en `main`, otro en `rama-b`.
    # Ambos worktrees dan el mismo total, no cada uno «el suyo».
    assert [m["sin_push"] for m in medidos] == [2, 2]

    unicos = repos.deduplicar(medidos)
    assert len(unicos) == 1
    assert sum(m["sin_push"] for m in unicos) == 2


def test_un_head_desatado_no_se_pierde_del_recuento(con_remoto, tmp_path):
    """`rev-list --all` NO incluye los HEAD desatados, y `~/dev/app` está
    justo así: detached, con commits que no cuelgan de ninguna rama. Sin sumar
    los HEAD de los worktrees, ese trabajo se contaría como respaldado."""
    _commit(con_remoto, "en-main")
    suelto = tmp_path / "suelto"
    _git(con_remoto, "worktree", "add", "--detach", str(suelto), "HEAD")
    _commit(suelto, "sólo-en-detached")

    assert repos.estado_de(str(con_remoto))["sin_push"] == 2


def test_escanear_guarda_una_fila_por_ruta_de_repo(con, con_remoto, tmp_path):
    proyecto = Proyecto(id="demo", nombre="Demo", asiento=str(con_remoto))
    # Una ruta que no es repo no debe generar fila ni romper el escaneo.
    proyecto.rutas.append(Ruta(ruta=str(tmp_path)))

    assert repos.escanear(con, [proyecto]) == 1
    fila = con.execute("SELECT * FROM repo").fetchone()
    assert fila["ruta"] == str(con_remoto)
    assert fila["rama"] == "main"
    assert fila["head"]


def test_un_escaneo_que_se_eterniza_se_corta_y_lo_dice(con, con_remoto, monkeypatch, capsys):
    """El escaneo corre dentro del bucle del snapshotter.

    Con `/mnt/c` colgado cada comando agota su tiempo, y un escaneo eterno
    dejaría al hub sin muestrear justo cuando el sistema va peor. Truncar en
    silencio sería peor todavía: se leería como «no hay nada sin respaldar».
    """
    monkeypatch.setattr(repos, "PRESUPUESTO_SEGUNDOS", -1)
    proyecto = Proyecto(id="demo", nombre="Demo", asiento=str(con_remoto))

    # Devolvía 0 y se daba por bueno. Un escaneo que no llegó a mirar NINGÚN
    # repo es indistinguible de «no tienes repos» viendo el resultado, así que
    # ahora se levanta y quien llama conserva la última medición. Es el mismo
    # criterio que con git ausente: cero medido y cero por no haber medido no se
    # pueden pintar igual.
    with pytest.raises(repos.RespaldoNoMedido):
        repos.escanear(con, [proyecto])
    assert "truncado" in capsys.readouterr().out


def test_un_escaneo_truncado_a_medias_conserva_lo_que_no_pudo_mirar(
    con, con_remoto, monkeypatch, tmp_path
):
    """La otra mitad: si midió algunos, los demás no pueden caer a cero.

    Con `DELETE FROM repo` los repos que no dio tiempo a mirar salían a cero
    —«nada sin respaldar»— en vez de conservar su última cifra buena.
    """
    medido = Proyecto(id="demo", nombre="Demo", asiento=str(con_remoto))
    repos.escanear(con, [medido])
    antes = con.execute("SELECT ruta, sin_push FROM repo").fetchall()
    assert antes, "el control positivo no midió nada"

    # Un segundo proyecto que no es repo: se declara, no aporta filas, y el
    # primero tiene que seguir donde estaba.
    otro = tmp_path / "no-es-repo"
    otro.mkdir()
    repos.escanear(con, [medido, Proyecto(id="otro", nombre="Otro", asiento=str(otro))])
    despues = con.execute("SELECT ruta, sin_push FROM repo").fetchall()
    assert [tuple(f) for f in despues] == [tuple(f) for f in antes]


def test_un_git_que_falla_no_tumba_la_medicion(monkeypatch, repo):
    """Un montaje caído o un repo roto no puede dejar sin medir a los demás."""
    repos._hay_git.cache_clear()
    monkeypatch.setattr(repos.shutil, "which", lambda x: None)
    try:
        assert repos.estado_de(str(repo)) is None
    finally:
        repos._hay_git.cache_clear()  # el caché no puede filtrarse a otros tests
