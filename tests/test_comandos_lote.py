"""Un comando preparado sobre una lista de valores (C-0507, decisión 464).

Lo pidió así: «pasarle una lista de repos y que él los clone; si ya tenemos el
comando, sólo es que ejecute, valide que se clonó y repita». Aquí se prueba la
puerta del hub (`comandos`): preparar la lista, dejarla escrita en una línea
sin Enter, y correrla de verdad —con un script de juguete que clona un repo
local por `file://`, sin red— sólo sobre lo que el dueño marcó ejecutable.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from hub import comandos, db, slots, tmux

RAIZ = Path(__file__).resolve().parents[1]


def _git(*args, cwd=None):
    subprocess.run(["git", "-c", "user.email=prueba@ejemplo", "-c", "user.name=prueba", *args], cwd=cwd,
                   check=True, capture_output=True)


@pytest.fixture
def mundo(tmp_path, monkeypatch, con):
    """Un proyecto indexado que ES un repo de git, con `interno/repos` dentro;
    un repo de origen local, y el script de clonar de juguete."""
    raiz = tmp_path / "trabajo"
    repos = raiz / "interno" / "repos"
    repos.mkdir(parents=True)
    _git("init", "-q", str(raiz))
    origen = tmp_path / "origen"
    _git("init", "-q", str(origen))
    _git("commit", "-q", "--allow-empty", "-m", "primero", cwd=origen)
    guion = tmp_path / "secretos" / "clonar.sh"
    guion.parent.mkdir()
    guion.write_text(
        "#!/bin/bash\n"
        '[ "$GIT_TERMINAL_PROMPT" = "0" ] || { echo "sin GIT_TERMINAL_PROMPT=0" >&2; exit 3; }\n'
        '[ -t 0 ] && { echo "con una terminal delante" >&2; exit 4; }\n'
        'case "$1" in\n'
        "  roto) echo \"fatal: repository 'https://usuario:clave-muy-secreta@git.ejemplo/roto.git' not found\" >&2;"
        " exit 128;;\n"
        '  plano) mkdir "$2/$1"; exit 0;;\n'
        "  lento) sleep 30;;\n"
        "esac\n"
        f'git clone -q "file://{origen}" "$2/$1"\n', encoding="utf-8")
    yml = tmp_path / "comandos.yml"
    yml.write_text(
        "comandos:\n"
        "  - id: clonar\n"
        "    nombre: Clonar repo\n"
        f"    plantilla: bash {guion} {{repo}} {{ruta}}\n"
        "    ejecutable: true\n"
        '    crea: "{repo}"\n'
        "  - id: escrito\n"
        "    nombre: Sólo escrito\n"
        f"    plantilla: bash {guion} {{repo}} {{ruta}}\n"
        "  - id: sin-crea\n"
        f"    plantilla: bash {guion} {{repo}} {{ruta}}\n"
        "    ejecutable: true\n"
        "  - id: dos-huecos\n"
        "    plantilla: bash x.sh {repo} {rama}\n", encoding="utf-8")
    monkeypatch.setenv("HUB_COMANDOS_YML", str(yml))
    con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES ('demo','Demo',?, 'ask')", (str(raiz),))
    con.execute("INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo',?,'asiento')", (str(raiz),))
    con.commit()
    return {"raiz": raiz, "repos": repos, "guion": guion, "yml": yml}


# ── preparar una lista ───────────────────────────────────────────────────────

def test_preparar_lote_da_una_orden_por_valor_escapada_y_sin_repetidos(mundo):
    ordenes = comandos.preparar_lote("clonar", None, ["api", "web; rm -rf ~", "api"], str(mundo["repos"]))
    assert ordenes == [f"bash {mundo['guion']} api {mundo['repos']}",
                       f"bash {mundo['guion']} 'web; rm -rf ~' {mundo['repos']}"]


@pytest.mark.parametrize("malo", ["--upload-pack=touch x", "../fuera", "a\x1b[201~b", "con\nsalto", " "])
def test_un_valor_con_control_guion_delante_o_dos_puntos_no_prepara_ninguno(mundo, malo):
    """Una lista a medias no se escribe ni se corre: falla entera."""
    with pytest.raises(comandos.ComandoInvalido):
        comandos.preparar_lote("clonar", None, ["bueno", malo], str(mundo["repos"]))


def test_mas_de_treinta_de_una_vez_no_se_preparan(mundo):
    with pytest.raises(comandos.ComandoInvalido, match="como mucho 30"):
        comandos.preparar_lote("clonar", None, [f"r{i}" for i in range(31)], str(mundo["repos"]))
    assert len(comandos.preparar_lote("clonar", None, [f"r{i}" for i in range(30)], str(mundo["repos"]))) == 30


def test_con_dos_huecos_hay_que_decir_cual_lleva_la_lista(mundo):
    with pytest.raises(comandos.ComandoInvalido, match="di cuál"):
        comandos.preparar_lote("dos-huecos", None, ["api"], "/srv")
    assert comandos.preparar_lote("dos-huecos", "repo", ["api"], "/srv", fijos={"rama": "main"}) == [
        "bash x.sh api main"]


def test_crea_dice_la_carpeta_y_sin_el_campo_no_dice_ninguna(mundo):
    assert comandos.crea("clonar", {"repo": "api"}, str(mundo["repos"])) == mundo["repos"] / "api"
    assert comandos.crea("escrito", {"repo": "api"}, str(mundo["repos"])) is None


def test_un_crea_que_sale_de_la_carpeta_no_vale(mundo):
    mundo["yml"].write_text(mundo["yml"].read_text() + "  - id: fuera\n    plantilla: bash x {repo}\n"
                            '    crea: "/tmp/{repo}"\n', encoding="utf-8")
    with pytest.raises(comandos.ComandoInvalido, match="sale de la carpeta"):
        comandos.crea("fuera", {"repo": "api"}, str(mundo["repos"]))


# ── dejarla escrita ──────────────────────────────────────────────────────────

@pytest.fixture
def ventanas(monkeypatch):
    abiertas = []
    monkeypatch.setattr(slots, "abrir_en", lambda ruta, nombre, session, texto="": abiertas.append(
        {"ruta": ruta, "session": session, "texto": texto}) or "%9")
    return abiertas


def test_una_lista_se_deja_en_una_sola_linea_y_salta_lo_que_ya_esta(mundo, ventanas, con):
    (mundo["repos"] / "ya-estaba").mkdir()
    r = comandos.dejar_escrito(con, "clonar", ["api", "ya-estaba", "web"], str(mundo["repos"]))
    [v] = ventanas
    assert v["texto"] == (f"bash {mundo['guion']} api {mundo['repos']} ; "
                          f"bash {mundo['guion']} web {mundo['repos']}")
    assert "\n" not in v["texto"]
    assert r["saltados"] == ["ya-estaba"] and not r["sin_crea"]
    assert r["session"] == "demo" and r["url"].startswith("/trabajo?session=demo")


def test_sin_crea_no_salta_ninguno_y_lo_dice(mundo, ventanas, con):
    (mundo["repos"] / "ya-estaba").mkdir()
    r = comandos.dejar_escrito(con, "escrito", ["ya-estaba"], str(mundo["repos"]))
    assert r["sin_crea"] and r["saltados"] == [] and "ya-estaba" in ventanas[0]["texto"]


def test_fuera_de_lo_indexado_no_se_abre_nada(mundo, ventanas, con, tmp_path):
    (tmp_path / "fuera").mkdir()
    with pytest.raises(comandos.CarpetaInvalida, match="no está bajo ninguna ruta"):
        comandos.dejar_escrito(con, "clonar", ["api"], str(tmp_path / "fuera"))
    assert ventanas == []


def test_con_guardrail_never_el_secretario_no_deja_nada_escrito(mundo, ventanas, con):
    con.execute("UPDATE proyecto SET guardrail = 'never'")
    with pytest.raises(comandos.CarpetaInvalida, match="never"):
        comandos.dejar_escrito(con, "clonar", ["api"], str(mundo["repos"]), respetar_never=True)
    assert ventanas == []


def test_la_lista_llega_a_un_panel_de_verdad_en_una_linea_y_sin_enter(mundo, con):
    """🔴 Con tmux de verdad (el servidor de pruebas, nunca el del dueño):
    `abrir_en` pega antes de que la shell pida el bracketed paste, así que un
    salto de línea sería un Enter. Unidas por ` ; ` quedan escritas y
    ninguna corre: pasado un rato, ningún repo existe."""
    if not shutil.which("tmux"):
        pytest.skip("tmux no disponible")
    try:
        r = comandos.dejar_escrito(con, "clonar", ["api", "web"], str(mundo["repos"]))
        time.sleep(1.5)
        pantalla = tmux.capturar_panel(r["pane_id"], unir_lineas=True)
        lineas = [linea for linea in pantalla.splitlines() if "clonar.sh" in linea]
        assert len(lineas) == 1 and r["texto"] in lineas[0], pantalla
        assert not (mundo["repos"] / "api").exists() and not (mundo["repos"] / "web").exists()
        assert r["ventana"] is not None and f"&ventana={r['ventana']}" in r["url"]
    finally:
        with contextlib.suppress(Exception):
            tmux._correr(["kill-session", "-t", "=demo"])


# ── correrla ─────────────────────────────────────────────────────────────────

def test_sin_ejecutable_o_sin_crea_no_corre_nada(mundo, con):
    for id_comando, motivo in (("escrito", "ejecutable: true"), ("sin-crea", "qué carpeta crea")):
        with pytest.raises(comandos.ComandoInvalido, match=motivo):
            comandos.ejecutar_lote(con, id_comando, ["api"], str(mundo["repos"]))
    assert list(mundo["repos"].iterdir()) == []


def test_clona_salta_lo_que_estaba_y_dice_el_error_sin_la_clave(mundo, con):
    (mundo["repos"] / "ya-estaba").mkdir()
    (mundo["repos"] / "ya-estaba" / "suyo.txt").write_text("no se toca")
    r = comandos.ejecutar_lote(con, "clonar", ["api", "ya-estaba", "roto"], str(mundo["repos"]))
    por = {x["valor"]: x for x in r["resultados"]}
    assert por["api"]["estado"] == "hecho" and (mundo["repos"] / "api" / ".git").is_dir()
    assert por["ya-estaba"]["estado"] == "ya_estaba"
    assert sorted(p.name for p in (mundo["repos"] / "ya-estaba").iterdir()) == ["suyo.txt"]
    assert por["roto"]["estado"] == "fallo" and "128" in por["roto"]["error"]
    assert "clave-muy-secreta" not in por["roto"]["salida"] and "[oculto]@" in por["roto"]["salida"]


def test_no_da_por_clonado_lo_que_no_es_un_repo_aunque_este_dentro_de_otro(mundo, con):
    """`interno/repos` vive dentro de un repo: `rev-parse --git-dir` contestaría
    el de arriba y daría por bueno un clon que no dejó nada."""
    r = comandos.ejecutar_lote(con, "clonar", ["plano"], str(mundo["repos"]))
    [x] = r["resultados"]
    assert x["estado"] == "fallo" and "no es un repo" in x["error"]


def test_una_orden_que_se_pasa_del_tope_se_corta_y_sigue_con_la_siguiente(mundo, con):
    t0 = time.monotonic()
    r = comandos.ejecutar_lote(con, "clonar", ["lento", "api"], str(mundo["repos"]), tope_s=1)
    assert time.monotonic() - t0 < 20
    por = {x["valor"]: x for x in r["resultados"]}
    assert por["lento"]["estado"] == "fallo" and "se cortó" in por["lento"]["error"]
    assert por["api"]["estado"] == "hecho"


def test_con_guardrail_never_no_se_corre_nada(mundo, con):
    con.execute("UPDATE proyecto SET guardrail = 'never'")
    with pytest.raises(comandos.CarpetaInvalida, match="never"):
        comandos.ejecutar_lote(con, "clonar", ["api"], str(mundo["repos"]))
    assert not (mundo["repos"] / "api").exists()


# ── quién puede ──────────────────────────────────────────────────────────────

def _codigo_de_src() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in (RAIZ / "src" / "hub").rglob("*.py")}


def test_solo_el_secretario_llama_a_ejecutar_lote():
    """🔴 Nunca `hub-web` ni un panel: lo corre `hub-secretario` desde su cola."""
    llaman = {p.relative_to(RAIZ).as_posix() for p, texto in _codigo_de_src().items()
              if re.search(r"\bejecutar_lote\(", texto)}
    assert llaman == {"src/hub/comandos.py", "src/hub/secretario/lotes.py"}


def test_el_hub_nunca_marca_un_comando_como_ejecutable():
    """`ejecutable: true` lo escribe el dueño en su `comandos.yml`: ningún
    código del hub escribe ese archivo, y lo que se publica no trae ninguno
    marcado (ni las semillas ni los ejemplos)."""
    for p, texto in _codigo_de_src().items():
        assert not re.search(r"comandos\.archivo\(\)\.(write|open)|ARCHIVO.*write_text", texto), p
    for carpeta in ("semillas", "producto"):
        for p in (RAIZ / carpeta).rglob("*"):
            if p.is_file() and p.suffix in (".yml", ".yaml"):
                assert "ejecutable: true" not in p.read_text(encoding="utf-8", errors="replace"), p
