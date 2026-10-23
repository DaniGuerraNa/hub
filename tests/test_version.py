"""Versiones, el aviso de versión nueva y `actualizar.sh` (decisión 286).

Lo que se prueba ejecutándolo de verdad —git contra un repo local, los scripts
de shell en carpetas temporales— y no con dobles: un doble prueba que el código
no revienta, no que el hub sepa decir qué versión tiene.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub import config, version

RAIZ = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"


def _git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
                            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def clon_con_remoto(tmp_path, monkeypatch):
    """Un clon cuyo `origin` es un repo local con etiquetas, y la consulta encendida."""
    publicado = tmp_path / "publicado"
    publicado.mkdir()
    _git("init", "-q", "-b", "main", cwd=publicado)
    (publicado / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.2.0"\n')
    _git("add", ".", cwd=publicado)
    _git("commit", "-q", "-m", "uno", cwd=publicado)
    for etiqueta in ("v0.2.0", "v0.9.0", "v0.10.0", "ensayo", "v1.0"):
        _git("tag", etiqueta, cwd=publicado)
    _git("tag", "-a", "v0.3.0", "-m", "anotada", cwd=publicado)
    clon = tmp_path / "clon"
    _git("clone", "-q", str(publicado), str(clon), cwd=tmp_path)
    monkeypatch.setenv("HUB_BUSCAR_VERSIONES", "1")
    return clon, publicado


# ── comparar versiones ───────────────────────────────────────────────────────

def test_las_versiones_se_comparan_por_numeros_y_no_como_texto():
    assert version.clave("0.10.0") > version.clave("0.9.3")
    assert version.clave("1.0.0") > version.clave("0.99.99")


def test_una_version_mal_escrita_se_rechaza_en_vez_de_compararse_mal():
    with pytest.raises(ValueError):
        version.clave("v0.2")


def test_de_la_salida_de_ls_remote_solo_cuentan_las_etiquetas_vXYZ():
    salida = ("a1\trefs/tags/v0.2.0\n"
              "b2\trefs/tags/v0.3.0\n"
              "c3\trefs/tags/v0.3.0^{}\n"
              "d4\trefs/tags/ensayo\n"
              "e5\trefs/tags/v1.0\n"
              "f6\trefs/tags/v0.10.0\n")
    assert version.etiquetas(salida) == ["0.2.0", "0.3.0", "0.10.0"]


# ── la versión publicada ─────────────────────────────────────────────────────

def test_la_version_publicada_es_la_etiqueta_mas_alta_del_remoto(clon_con_remoto):
    clon, _ = clon_con_remoto
    datos = version.buscar_remota(clon)
    assert datos["ultima"] == "0.10.0"
    assert "error" not in datos


def test_se_mira_como_mucho_una_vez_al_dia(clon_con_remoto):
    clon, publicado = clon_con_remoto
    ahora = datetime.now(timezone.utc)
    version.buscar_remota(clon, ahora=ahora)
    _git("tag", "v0.11.0", cwd=publicado)

    assert version.buscar_remota(clon, ahora=ahora + timedelta(hours=3))["ultima"] == "0.10.0"
    assert version.buscar_remota(clon, ahora=ahora + timedelta(hours=25))["ultima"] == "0.11.0"


def test_sin_red_se_conserva_lo_ultimo_que_se_supo_y_se_apunta_el_fallo(clon_con_remoto):
    clon, publicado = clon_con_remoto
    ahora = datetime.now(timezone.utc)
    version.buscar_remota(clon, ahora=ahora)
    shutil.rmtree(publicado)

    datos = version.buscar_remota(clon, ahora=ahora + timedelta(days=2))
    assert datos["ultima"] == "0.10.0"
    assert datos["error"]


def test_con_HUB_BUSCAR_VERSIONES_0_no_se_sale_a_internet(clon_con_remoto, monkeypatch):
    clon, _ = clon_con_remoto
    monkeypatch.setenv("HUB_BUSCAR_VERSIONES", "0")
    assert version.buscar_remota(clon) is None
    assert not (config.HUB_HOME / "version-remota.json").exists()


def test_un_clon_sin_origin_no_busca_ni_apunta_un_fallo(clon_con_remoto):
    clon, _ = clon_con_remoto
    _git("remote", "remove", "origin", cwd=clon)
    assert version.buscar_remota(clon) is None
    assert not (config.HUB_HOME / "version-remota.json").exists()


def test_la_suite_no_sale_a_internet_por_defecto():
    """El ciclo lento de cualquier test haría un `ls-remote` a GitHub."""
    assert os.environ["HUB_BUSCAR_VERSIONES"] == "0"


# ── el estado que pinta la UI ────────────────────────────────────────────────

def test_sin_version_apuntada_falta_terminar_de_actualizar():
    """Lo que ve quien hizo `git pull` y reinició con el procedimiento de antes."""
    estado = version.estado()
    assert estado["instalada"] is None
    assert estado["falta_terminar"] is True


def test_con_la_version_apuntada_no_falta_nada():
    version.registrar(version.del_codigo())
    assert version.estado()["falta_terminar"] is False


def test_una_version_apuntada_mas_vieja_que_el_codigo_falta_terminar():
    version.registrar("0.1.0")
    assert version.estado()["falta_terminar"] is True


def test_hay_nueva_solo_si_la_publicada_es_mayor_que_la_del_codigo():
    actual = version.del_codigo()
    mayor = actual.split(".")
    mayor[1] = str(int(mayor[1]) + 1)
    archivo = config.HUB_HOME / "version-remota.json"
    archivo.write_text(json.dumps({"ultima": ".".join(mayor), "mirado_en": "2026-01-01T00:00:00+00:00"}))
    assert version.estado()["hay_nueva"] is True
    archivo.write_text(json.dumps({"ultima": actual, "mirado_en": "2026-01-01T00:00:00+00:00"}))
    assert version.estado()["hay_nueva"] is False


# ── migraciones y novedades ──────────────────────────────────────────────────

def test_las_migraciones_son_las_de_las_versiones_cruzadas_y_en_orden(tmp_path):
    for nombre in ("0.2.0", "0.10.0", "0.3.0", "0.9.1", "README", "nota"):
        (tmp_path / f"{nombre}.sh").write_text("true\n")
    nombres = [p.stem for p in version.migraciones("0.2.0", "0.10.0", tmp_path)]
    assert nombres == ["0.3.0", "0.9.1", "0.10.0"]


def test_una_instalacion_anterior_al_protocolo_aplica_desde_la_020(tmp_path):
    (tmp_path / "0.2.0.sh").write_text("true\n")
    assert [p.stem for p in version.migraciones(None, "0.2.0", tmp_path)] == ["0.2.0"]


def test_las_novedades_son_solo_las_versiones_que_se_cruzan():
    texto = ("# Cambios\n\nintro\n\n## 0.4.0 — x\ncuatro\n\n## 0.3.0 — x\ntres\n\n"
             "## 0.2.0 — x\ndos\n")
    salida = version.novedades(texto, "0.2.0", "0.4.0")
    assert "cuatro" in salida and "tres" in salida
    assert "dos" not in salida and "intro" not in salida


def test_el_changelog_tiene_la_entrada_de_la_version_del_codigo():
    """Lo mismo que exige `publicar.sh`: ninguna versión sin decir qué cambia."""
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    actual = version.del_codigo()
    assert re.search(rf"^## \[?{re.escape(actual)}\]?( |$)", texto, re.M)
    for apartado in ("### Qué tienes que hacer", "### Nuevo", "### Qué cambia en lo que ya usabas"):
        assert apartado in version.novedades(texto, None, actual), apartado


def test_publicar_se_niega_sin_entrada_en_el_changelog():
    guion = RAIZ / "scripts" / "publicar.sh"
    if not guion.exists():
        pytest.skip("publicar.sh sólo existe en el repo de desarrollo")
    texto = guion.read_text(encoding="utf-8")
    revision = texto.split("# ── La versión")[1].split("# ── Qué viaja")[0]
    assert "CHANGELOG.md" in revision and "exit 1" in revision
    assert texto.index("# ── La versión") < texto.index("# ── Qué viaja")


# ── lo que se ve ─────────────────────────────────────────────────────────────

@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web

    ruta = tmp_path / "hub.db"
    db.inicializar(db.conectar(ruta))

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    return TestClient(web.app)


@pytest.mark.parametrize("pantalla", ["/", "/respaldo", "/guia"])
def test_falta_terminar_de_actualizar_se_dice_en_todas_las_pantallas(cliente, pantalla):
    html = cliente.get(pantalla).text
    assert "Falta terminar de actualizar" in html
    assert "bash scripts/actualizar.sh" in html


def test_con_la_actualizacion_terminada_no_hay_aviso(cliente):
    version.registrar(version.del_codigo())
    html = cliente.get("/").text
    assert "Falta terminar de actualizar" not in html
    assert "Hay una versión nueva" not in html


def test_una_version_publicada_mas_nueva_se_anuncia_con_sus_novedades(cliente):
    version.registrar(version.del_codigo())
    (config.HUB_HOME / "version-remota.json").write_text(
        json.dumps({"ultima": "99.0.0", "mirado_en": "2026-01-01T00:00:00+00:00"}))
    assert "Hay una versión nueva del hub, la 99.0.0" in cliente.get("/").text
    guia = cliente.get("/guia").text
    assert 'id="version"' in guia
    assert "la <strong>99.0.0</strong>" in guia


def test_la_guia_dice_que_version_tienes_y_que_trajo(cliente):
    guia = cliente.get("/guia").text
    assert f"tienes la {version.del_codigo()}" in guia
    assert "Qué trajo la" in guia


# ── los scripts ──────────────────────────────────────────────────────────────

def _correr(guion: Path, entorno: dict, *args: str, cwd: Path | None = None, timeout=300):
    return subprocess.run([BASH, str(guion), *args], capture_output=True, text=True,
                          timeout=timeout, cwd=cwd, env={**os.environ, **entorno})


def test_los_guiones_nuevos_son_bash_valido():
    for guion in ("actualizar.sh", "lib/unidades.sh", "instalar.sh", "sembrar-asistente.sh"):
        r = subprocess.run([BASH, "-n", str(RAIZ / "scripts" / guion)], capture_output=True, text=True)
        assert r.returncode == 0, f"{guion}: {r.stderr}"
    assert os.access(RAIZ / "scripts" / "actualizar.sh", os.X_OK)


def test_los_units_se_regeneran_con_lo_instalado_y_lo_retocado_queda_al_lado(tmp_path):
    unidades = tmp_path / "units"
    guion = tmp_path / "prueba.sh"
    guion.write_text(f"""set -euo pipefail
RAIZ={RAIZ}; UNIDADES={unidades}
HUB_HOME=/datos/mios; HUB_HOST=127.0.0.1; HUB_PORT=8799
. "$RAIZ/scripts/lib/unidades.sh"
generar_unidades
echo 'retoque a mano' >> "$UNIDADES/hub-canal.service"
HUB_HOME=x; HUB_HOST=y; HUB_PORT=z
leer_unidad_instalada
echo "$HUB_HOME $HUB_HOST $HUB_PORT"
generar_unidades
""")
    r = _correr(guion, {})
    assert r.returncode == 0, r.stderr
    assert "/datos/mios 127.0.0.1 8799" in r.stdout
    for servicio in ("hub-web", "hub-snapshotter", "hub-canal", "hub-encargos"):
        texto = (unidades / f"{servicio}.service").read_text()
        assert "Environment=HUB_PORT=8799" in texto
        assert not re.search(r"@[A-Z_]+@", texto), "queda un marcador sin sustituir"
        assert "Environment=HUB_HOME=/datos/mios" in texto
    assert "retoque a mano" in (unidades / "hub-canal.service.antes").read_text()
    assert "retoque a mano" not in (unidades / "hub-canal.service").read_text()
    assert not (unidades / "hub-web.service.antes").exists(), "lo que no cambió no deja copia"


def test_refrescar_el_asistente_pone_al_dia_lo_de_la_semilla_y_no_toca_lo_demas(tmp_path):
    casa = tmp_path / "casa"
    casa.mkdir()
    shutil.copy(RAIZ / "projects.ejemplo.yml", casa / "projects.yml")
    entorno = {"HUB_HOME": str(casa), "HUB_PROJECTS_YML": str(casa / "projects.yml"),
               "HUB_BIN": str(tmp_path / "bin")}
    destino = tmp_path / "asistente"
    guion = RAIZ / "scripts" / "sembrar-asistente.sh"
    assert _correr(guion, entorno, str(destino)).returncode == 0

    original = (destino / "CLAUDE.md").read_text()
    (destino / "CLAUDE.md").write_text("instrucciones viejas\n")
    (destino / "ESTADO.md").write_text("lo mío\n")
    sin_tocar = (destino / "bin" / "hub").stat().st_mtime_ns

    r = _correr(guion, entorno, "--refrescar", str(destino))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (destino / "CLAUDE.md").read_text() == original
    antes = list(destino.glob("CLAUDE.md.antes-*"))
    assert len(antes) == 1 and antes[0].read_text() == "instrucciones viejas\n"
    assert (destino / "ESTADO.md").read_text() == "lo mío\n"
    assert (destino / "bin" / "hub").stat().st_mtime_ns == sin_tocar
    assert "@ASIENTO@" not in (destino / ".claude" / "settings.json").read_text()

    r2 = _correr(guion, entorno, "--refrescar", str(destino))
    assert "ya estaba al día" in r2.stdout


@pytest.fixture(scope="module")
def _venv_compartido(tmp_path_factory):
    return tmp_path_factory.mktemp("venv-actualizar") / "venv"


@pytest.fixture
def clon_desechable(tmp_path, _venv_compartido):
    """Una copia del árbol de trabajo con su propio git, para correr
    `actualizar.sh` de verdad sin tocar este clon, sus servicios ni sus datos."""
    destino = tmp_path / "hub"
    shutil.copytree(RAIZ, destino, ignore=shutil.ignore_patterns(
        ".venv", ".git", "__pycache__", ".pytest_cache", "*.png"))
    _git("init", "-q", "-b", "main", cwd=destino)
    _git("add", "-A", cwd=destino)
    _git("commit", "-q", "-m", "copia", cwd=destino)
    casa = tmp_path / "casa"
    casa.mkdir()
    shutil.copy(RAIZ / "projects.ejemplo.yml", casa / "projects.yml")
    entorno = {
        "HUB_HOME": str(casa), "HUB_PROJECTS_YML": str(casa / "projects.yml"),
        # Sin units instalados: `actualizar.sh` no debe tocar systemd de nadie.
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        # 🔴 Su propio entorno. Con el de este clon, el `uv sync` de la copia
        # reinstalaba `hub` apuntando a la carpeta temporal, y el hub de verdad
        # quedaba importando código que pytest borra al terminar (pasó así).
        "UV_PROJECT_ENVIRONMENT": str(_venv_compartido),
    }
    return destino, casa, entorno


def test_actualizar_aplica_los_pasos_y_apunta_la_version_al_final(clon_desechable):
    destino, casa, entorno = clon_desechable
    paso = destino / "scripts" / "migraciones" / f"{version.del_codigo()}.sh"
    paso.write_text('echo "paso de versión en $HUB_HOME" > "$HUB_HOME/paso-hecho"\n')
    _git("add", "-A", cwd=destino)
    _git("commit", "-q", "-m", "paso", cwd=destino)

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode == 0, r.stdout + r.stderr
    assert (casa / "paso-hecho").read_text().strip() == f"paso de versión en {casa}"
    assert json.loads((casa / "version.json").read_text())["version"] == version.del_codigo()
    assert "Qué cambió" in r.stdout
    # Y el entorno del hub de verdad sigue apuntando a este clon.
    instalado = next((RAIZ / ".venv").glob("lib/python*/site-packages/hub-*.dist-info/direct_url.json"), None)
    if instalado:
        assert str(RAIZ) in instalado.read_text()


def test_si_un_paso_falla_la_version_no_se_apunta(clon_desechable):
    destino, casa, entorno = clon_desechable
    (destino / "scripts" / "migraciones" / f"{version.del_codigo()}.sh").write_text("exit 3\n")
    _git("add", "-A", cwd=destino)
    _git("commit", "-q", "-m", "paso roto", cwd=destino)

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode != 0
    assert "la versión NO se apunta" in r.stderr
    assert not (casa / "version.json").exists()


def test_actualizar_no_pisa_cambios_sin_guardar(clon_desechable):
    destino, casa, entorno = clon_desechable
    (destino / "README.md").write_text("tocado\n")

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode != 0
    assert "cambios sin guardar" in r.stderr
    assert "git diff > ~/cambios-hub-" in r.stderr
    assert "git restore ." in r.stderr
    assert "git switch -c mis-cambios-" in r.stderr
    assert not (casa / "version.json").exists()
