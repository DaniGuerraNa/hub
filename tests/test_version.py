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


def test_se_mira_como_mucho_una_vez_cada_hora(clon_con_remoto):
    """Antes era una vez al día, y un usuario se quedó viendo la 0.3.0 con la
    0.3.1 ya publicada (decisión 296)."""
    clon, publicado = clon_con_remoto
    ahora = datetime.now(timezone.utc)
    version.buscar_remota(clon, ahora=ahora)
    _git("tag", "v0.11.0", cwd=publicado)

    assert version.buscar_remota(clon, ahora=ahora + timedelta(minutes=30))["ultima"] == "0.10.0"
    assert version.buscar_remota(clon, ahora=ahora + timedelta(minutes=61))["ultima"] == "0.11.0"


def test_al_entrar_en_actualizaciones_basta_con_cinco_minutos(clon_con_remoto):
    clon, publicado = clon_con_remoto
    ahora = datetime.now(timezone.utc)
    version.buscar_remota(clon, ahora=ahora)
    _git("tag", "v0.11.0", cwd=publicado)

    assert version.buscar_remota(clon, ahora=ahora + timedelta(minutes=6),
                                 cada=version.AL_ENTRAR)["ultima"] == "0.11.0"


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
    assert 'href="/actualizaciones">Terminar ahora' in html


def test_con_la_actualizacion_terminada_no_hay_aviso(cliente):
    version.registrar(version.del_codigo())
    html = cliente.get("/").text
    assert "Falta terminar de actualizar" not in html
    assert "Hay una versión nueva" not in html


def test_una_version_publicada_mas_nueva_se_anuncia_con_sus_novedades(cliente, monkeypatch):
    from hub import actualizacion
    # El clon de quien corre la suite puede tener cambios: no es lo que se prueba.
    monkeypatch.setattr(actualizacion, "cambios_locales", lambda raiz=None: [])
    version.registrar(version.del_codigo())
    (config.HUB_HOME / "version-remota.json").write_text(
        json.dumps({"ultima": "99.0.0", "mirado_en": "2026-01-01T00:00:00+00:00"}))
    assert "Hay una versión nueva del hub, la 99.0.0" in cliente.get("/").text
    pantalla = cliente.get("/actualizaciones").text
    assert "La 99.0.0 está publicada" in pantalla
    assert 'action="/actualizaciones/aplicar"' in pantalla


def test_actualizaciones_dice_que_version_tienes_y_que_trajo(cliente):
    """Vivía en /guia hasta la decisión 296: ahora tiene su pantalla."""
    pantalla = cliente.get("/actualizaciones").text
    assert f"<strong>{version.del_codigo()}</strong>" in pantalla
    assert "Qué trajo la" in pantalla
    assert 'id="version"' not in cliente.get("/guia").text


def test_con_cambios_locales_no_se_ofrece_el_boton_y_se_dice_que_hacer(cliente, monkeypatch):
    from hub import actualizacion
    monkeypatch.setattr(actualizacion, "cambios_locales", lambda raiz=None: [" M src/hub/api.py"])
    pantalla = cliente.get("/actualizaciones").text
    assert "cambios sin guardar" in pantalla and "git restore ." in pantalla
    assert 'action="/actualizaciones/aplicar"' not in pantalla
    r = cliente.post("/actualizaciones/aplicar", headers={"origin": "http://127.0.0.1:8787"},
                     follow_redirects=False)
    assert "No%20se%20actualiz" in r.headers["location"]


def test_el_boton_lanza_actualizar_sh_fuera_del_proceso_del_hub(cliente, monkeypatch):
    """🔴 Fuera de su cgroup: `actualizar.sh` reinicia `hub-web`, y un hijo
    normal moriría con él a mitad de la actualización. La puerta es
    `procesos.desasir` (344); que de verdad saca del cgroup lo prueba
    `test_procesos`."""
    from hub import actualizacion, procesos
    monkeypatch.setattr(actualizacion, "cambios_locales", lambda raiz=None: [])
    monkeypatch.setattr(actualizacion, "_con_systemd", lambda: True)
    monkeypatch.setattr(procesos, "_puede", True)
    lanzadas = []

    def desasir(orden, **kw):
        lanzadas.append(orden)
        return subprocess.Popen(["sleep", "1"])
    monkeypatch.setattr(procesos, "desasir", desasir)
    r = cliente.post("/actualizaciones/aplicar", headers={"origin": "http://127.0.0.1:8787"},
                     follow_redirects=False)
    assert r.headers["location"].startswith("/actualizaciones")
    assert lanzadas[-1][:2] == ["bash", "-c"] and "scripts/actualizar.sh" in lanzadas[-1][-1]
    assert actualizacion.en_marcha()


def test_si_el_scope_no_se_monta_no_se_queda_en_marcha(monkeypatch):
    """Si `systemd-run` falla la orden ni arranca: sin esto, la pantalla diría
    «en marcha» media hora (arquitecto de C-0148)."""
    from hub import actualizacion, procesos
    monkeypatch.setattr(actualizacion, "_con_systemd", lambda: True)
    monkeypatch.setattr(procesos, "_puede", True)
    monkeypatch.setattr(procesos, "desasir", lambda orden, **kw: subprocess.Popen(["false"]))
    with pytest.raises(RuntimeError, match="no se pudo lanzar"):
        actualizacion.lanzar()
    assert not actualizacion.en_marcha()


def test_con_servicios_y_sin_scope_no_se_lanza_a_ciegas(monkeypatch):
    from hub import actualizacion, procesos
    monkeypatch.setattr(actualizacion, "_con_systemd", lambda: True)
    monkeypatch.setattr(procesos, "_puede", False)
    with pytest.raises(RuntimeError, match="en una terminal"):
        actualizacion.lanzar()
    assert not actualizacion.en_marcha()


def test_una_actualizacion_en_marcha_no_se_lanza_dos_veces(monkeypatch):
    from hub import actualizacion
    (actualizacion.carpeta() / "inicio.json").write_text(json.dumps({"t": int(__import__("time").time())}))
    with pytest.raises(RuntimeError, match="en marcha"):
        actualizacion.lanzar()


def test_el_resultado_se_lee_aunque_el_hub_se_haya_reiniciado():
    """El registro y el resultado viven en archivos, no en la memoria del
    proceso que se reinicia a mitad."""
    import time
    from hub import actualizacion
    t = int(time.time())
    (actualizacion.carpeta() / "inicio.json").write_text(json.dumps({"t": t}))
    (actualizacion.carpeta() / "registro.log").write_text("\x1b[1m7/7 · Comprobación\x1b[0m\n  ✓ instalada\n")
    (actualizacion.carpeta() / "resultado.json").write_text(json.dumps({"rc": 0, "t": t + 5}))
    e = actualizacion.estado()
    assert e["en_marcha"] is False and e["rc"] == 0
    assert "7/7 · Comprobación" in e["registro"] and "\x1b" not in e["registro"]


# ── los scripts ──────────────────────────────────────────────────────────────

def _correr(guion: Path, entorno: dict, *args: str, cwd: Path | None = None, timeout=300):
    return subprocess.run([BASH, str(guion), *args], capture_output=True, text=True,
                          timeout=timeout, cwd=cwd, env={**os.environ, **entorno})


def test_los_guiones_nuevos_son_bash_valido():
    for guion in ("actualizar.sh", "lib/unidades.sh", "lib/puente.sh", "instalar.sh", "sembrar-asistente.sh"):
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
    for servicio in ("hub-web", "hub-snapshotter", "hub-canal", "hub-encargos", "hub-secretario"):
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
    """El entorno que monta el `uv sync` de `actualizar.sh` (77 MB), compartido
    por el módulo y borrado al acabarlo: nadie lo mira después, ni cuando un
    test falla (C-0325)."""
    carpeta = tmp_path_factory.mktemp("venv-actualizar")
    yield carpeta / "venv"
    shutil.rmtree(carpeta, ignore_errors=True)


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


# ── C-0448: copia de antes, comprobación de verdad y cómo volver ─────────────

def _base_con_notas(ruta: Path, filas: int = 1) -> None:
    """Una base cualquiera en WAL, como las que deja el hub en `HUB_HOME`."""
    import sqlite3
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS nota (texto TEXT)")
    con.executemany("INSERT INTO nota VALUES (?)", [("lo que sólo vive aquí",)] * filas)
    con.commit()
    con.close()


def _notas(ruta: Path) -> int:
    import sqlite3
    con = sqlite3.connect(ruta)
    try:
        return con.execute("SELECT count(*) FROM nota").fetchone()[0]
    finally:
        con.close()


def test_actualizar_copia_las_bases_antes_de_tocarlas_y_otra_corrida_no_las_pisa(clon_desechable):
    destino, casa, entorno = clon_desechable
    _base_con_notas(casa / "hub.db")
    _base_con_notas(casa / "secretario" / "memoria.db")

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode == 0, r.stdout + r.stderr
    hoy = datetime.now().strftime("%Y%m%d")
    copias = casa / "respaldos"
    assert sorted(p.name for p in copias.glob("antes-*.db")) == [
        f"antes-hub-{hoy}.db", f"antes-secretario-{hoy}.db"]
    assert str(copias / f"antes-hub-{hoy}.db") in r.stdout

    # Lo que la versión nueva escribe después no entra en la copia de antes.
    _base_con_notas(casa / "hub.db")
    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode == 0, r.stdout + r.stderr
    assert _notas(casa / "hub.db") == 2
    assert _notas(copias / f"antes-hub-{hoy}.db") == 1


def test_si_un_paso_falla_dice_como_volver_y_donde_estan_las_copias(clon_desechable):
    destino, casa, entorno = clon_desechable
    primero = _git("rev-parse", "HEAD", cwd=destino).strip()
    (destino / "scripts" / "migraciones" / f"{version.del_codigo()}.sh").write_text("exit 3\n")
    _git("add", "-A", cwd=destino)
    _git("commit", "-q", "-m", "paso roto", cwd=destino)
    _base_con_notas(casa / "hub.db")

    # Lo que pasa el guion viejo al nuevo cuando lo que bajó trae otro actualizar.sh.
    r = _correr(destino / "scripts" / "actualizar.sh", {**entorno, "HUB_ACTUALIZA_DESDE": primero},
                "--sin-bajar", cwd=destino)

    assert r.returncode != 0
    assert not (casa / "version.json").exists()
    volver = r.stderr[r.stderr.index("Para volver a como estaba"):]
    assert f"git checkout {primero}\n" in volver
    assert "bash scripts/actualizar.sh --sin-bajar" in volver
    assert str(casa / "respaldos" / f"antes-hub-{datetime.now():%Y%m%d}.db") in volver
    assert "INSTALAR.md, «Volver a la versión anterior»" in volver
    assert "git switch main && bash scripts/actualizar.sh" in volver
    # 🔴 Restaurar pisa lo escrito desde la copia: eso se hace leyendo, no copiando lo impreso.
    assert "cp " not in volver


def test_si_el_commit_de_antes_tampoco_se_instalo_se_vuelve_a_la_etiqueta_de_la_version_apuntada(
        clon_desechable):
    """Un reintento que baja otro arreglo después de fallar: el commit de antes
    de bajar es el del intento fallido, no lo que estaba instalado, y volver
    ahí repetiría sus pasos. Manda la versión apuntada, que al fallar no
    cambia; sin su etiqueta no se inventa un commit: se dice cómo buscarlo."""
    destino, casa, entorno = clon_desechable
    intento = _git("rev-parse", "HEAD", cwd=destino).strip()
    _git("tag", "v0.4.0", intento, cwd=destino)
    (destino / "scripts" / "migraciones" / f"{version.del_codigo()}.sh").write_text("exit 3\n")
    _git("add", "-A", cwd=destino)
    _git("commit", "-q", "-m", "arreglo publicado después del fallo, con un paso roto", cwd=destino)
    (casa / "version.json").write_text(json.dumps({"version": "0.4.0", "en": "2026-11-01T10:00:00+00:00"}))
    entorno = {**entorno, "HUB_ACTUALIZA_DESDE": intento}

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode != 0
    assert "  git checkout v0.4.0\n" in r.stderr and intento not in r.stderr

    _git("tag", "-d", "v0.4.0", cwd=destino)
    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode != 0
    volver = r.stderr[r.stderr.index("Para volver a como estaba"):]
    assert "No encuentro el commit de la versión que tenías (la 0.4.0)" in volver
    assert "git reflog" in volver and "git checkout <ese commit>" in volver
    assert intento not in volver


# Un systemd de usuario de mentira: apunta cada orden y contesta según los
# archivos de su carpeta. `late` hace que el muestreo reiniciado dé su latido
# unos segundos después, como el de verdad.
_SYSTEMCTL_FALSO = r"""#!/bin/sh
d="$SYSTEMCTL_FALSO"
echo "$*" >> "$d/ordenes"
[ "$1" = "--user" ] && shift
orden=$1; shift
case "$orden" in
  show-environment|daemon-reload) exit 0 ;;
  is-active)
    callado=""; if [ "$1" = "--quiet" ]; then callado=1; shift; fi
    estado=$(cat "$d/activo-$1" 2>/dev/null || echo inactive)
    [ -n "$callado" ] || echo "$estado"
    [ "$estado" = active ] ;;
  is-enabled) echo enabled ;;
  restart)
    if [ "$1" = hub-snapshotter ] && [ -e "$d/late" ]; then
      printf '{"en": "%s", "pid": 2}' "$(date -u -d '+3 seconds' +%Y-%m-%dT%H:%M:%S+00:00)" \
        > "$HUB_HOME/latido-snapshotter.json"
    fi ;;
  *) exit 0 ;;
esac
"""


@pytest.fixture
def systemd_falso(clon_desechable, tmp_path):
    """`actualizar.sh` con servicios sin tocar los de nadie: `systemctl` y
    `curl` de mentira delante en el PATH, y el unit de la web en la carpeta
    temporal. Están en marcha la web, el muestreo y el canal."""
    destino, casa, entorno = clon_desechable
    d = tmp_path / "systemd-falso"
    (d / "bin").mkdir(parents=True)
    for nombre, texto in (("systemctl", _SYSTEMCTL_FALSO), ("curl", "#!/bin/sh\nprintf 200\n")):
        (d / "bin" / nombre).write_text(texto)
        (d / "bin" / nombre).chmod(0o755)
    for servicio in ("hub-web", "hub-snapshotter", "hub-canal"):
        (d / f"activo-{servicio}").write_text("active\n")
    unidades = Path(entorno["XDG_CONFIG_HOME"]) / "systemd" / "user"
    unidades.mkdir(parents=True)
    (unidades / "hub-web.service").write_text(
        f"[Service]\nEnvironment=HUB_HOME={casa}\n"
        "ExecStart=/x/.venv/bin/python -m uvicorn hub.web:app --host 127.0.0.1 --port 8799\n")
    path = f"{d / 'bin'}:{os.environ['PATH']}"
    # 🔴 Sólo si el de mentira es el primero que se encuentra: si no se pudiera
    # ejecutar, el siguiente sería el de verdad y la prueba reiniciaría los
    # servicios de quien corre la suite.
    if shutil.which("systemctl", path=path) != str(d / "bin" / "systemctl"):
        pytest.skip("el systemctl de mentira no se puede ejecutar aquí")
    entorno = {**entorno, "PATH": path, "SYSTEMCTL_FALSO": str(d), "HUB_ESPERA_SENAL": "2",
               "GIT_CONFIG_GLOBAL": "/dev/null"}
    return destino, casa, entorno, d


def _ordenes(d: Path) -> list[str]:
    archivo = d / "ordenes"
    return archivo.read_text().splitlines() if archivo.exists() else []


def _publicada_un_commit_por_delante(destino: Path, tmp_path: Path) -> str:
    """El clon, un commit por detrás de su `origin`, y ese commit trae otro
    `actualizar.sh`: el guion viejo baja y se relanza con el nuevo. Devuelve
    el commit en el que estaba el clon."""
    antes = _git("rev-parse", "HEAD", cwd=destino).strip()
    guion = destino / "scripts" / "actualizar.sh"
    guion.write_text(guion.read_text() + "# lo que trae la versión publicada\n")
    _git("commit", "-q", "-am", "publicada", cwd=destino)
    publicado = tmp_path / "publicado.git"
    _git("clone", "-q", "--bare", str(destino), str(publicado), cwd=tmp_path)
    _git("remote", "add", "origin", str(publicado), cwd=destino)
    _git("fetch", "-q", "origin", cwd=destino)
    _git("branch", "-q", "--set-upstream-to=origin/main", cwd=destino)
    _git("reset", "-q", "--hard", antes, cwd=destino)
    return antes


def test_si_el_muestreo_no_late_tras_reiniciarlo_la_actualizacion_falla_y_dice_como_volver(
        systemd_falso, tmp_path):
    """Hasta C-0448 bastaba con que la web contestara: una versión que dejaba
    el muestreo muerto se daba por instalada (decisión 151, arrancado no es
    funcionar)."""
    destino, casa, entorno, d = systemd_falso
    antes = _publicada_un_commit_por_delante(destino, tmp_path)

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, cwd=destino)

    assert r.returncode != 0, r.stdout + r.stderr
    assert "el actualizador también cambió" in r.stdout
    assert "--user restart hub-snapshotter" in _ordenes(d)
    assert "hub-snapshotter está en marcha pero no ha latido" in r.stderr
    assert "journalctl --user -u hub-snapshotter -n 40 --no-pager" in r.stderr
    assert "la versión NO se apunta" in r.stderr
    assert not (casa / "version.json").exists()
    # El commit de antes de bajar, aunque el guion que falla sea el nuevo.
    assert f"git checkout {antes}\n" in r.stderr
    assert "Volver a la versión anterior" in r.stderr


def test_con_el_muestreo_latiendo_se_apunta_la_version_y_cada_servicio_dice_como_quedo(systemd_falso):
    """El secretario que arranca pero aún no late sólo avisa: su primer
    latido puede tardar un minuto."""
    destino, casa, entorno, d = systemd_falso
    (d / "late").touch()
    (d / "activo-hub-secretario").write_text("active\n")

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((casa / "version.json").read_text())["version"] == version.del_codigo()
    reiniciados = [o.split()[-1] for o in _ordenes(d) if o.startswith("--user restart ")]
    assert reiniciados == ["hub-web", "hub-snapshotter", "hub-canal", "hub-secretario"]
    assert "hub-snapshotter da señales de vida" in r.stdout
    assert "hub-canal en marcha (no tiene señal propia" in r.stdout
    assert "hub-secretario está en marcha pero aún no late" in r.stdout
    assert "Para volver" not in r.stderr


def test_un_servicio_reiniciado_que_no_queda_en_marcha_hace_fallar_la_actualizacion(systemd_falso):
    destino, casa, entorno, d = systemd_falso
    (d / "late").touch()
    # El canal estaba en marcha, se reinicia y se cae al arrancar.
    guion = d / "bin" / "systemctl"
    guion.write_text(guion.read_text().replace(
        "  restart)\n", '  restart)\n    [ "$1" = hub-canal ] && echo activating > "$d/activo-hub-canal"\n'))

    r = _correr(destino / "scripts" / "actualizar.sh", entorno, "--sin-bajar", cwd=destino)

    assert r.returncode != 0, r.stdout + r.stderr
    assert "hub-canal no quedó en marcha" in r.stderr
    assert "journalctl --user -u hub-canal -n 40 --no-pager" in r.stderr
    assert not (casa / "version.json").exists()


# ── C-0121: sin git no hay 500, y lo apuntado no se queda a medias ────────────


def test_sin_git_comprobar_dice_que_no_pudo_mirar_en_vez_de_dar_500(cliente, tmp_path, monkeypatch):
    """`git remote get-url` iba sin `try`: sin git en el PATH (o colgado),
    «Comprobar ahora» daba un 500 en vez de decir qué pasó."""
    vacio = tmp_path / "sin-git"
    vacio.mkdir()
    monkeypatch.setenv("HUB_BUSCAR_VERSIONES", "1")
    monkeypatch.setenv("PATH", str(vacio))

    datos = version.buscar_remota(forzar=True)
    assert "git" in datos["error"]
    r = cliente.post("/actualizaciones/comprobar", headers={"origin": "http://127.0.0.1:8787"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert "No%20se%20pudo%20mirar" in r.headers["location"]


def test_lo_ultimo_que_se_supo_no_se_pierde_si_apuntar_lo_nuevo_falla(clon_con_remoto, monkeypatch):
    """Se escribe aparte y se cambia de un golpe, como `registrar`: un corte a
    mitad dejaba `version-remota.json` truncado y el hub olvidaba la publicada."""
    clon, publicado = clon_con_remoto
    ahora = datetime.now(timezone.utc)
    version.buscar_remota(clon, ahora=ahora)
    _git("tag", "v0.11.0", cwd=publicado)

    def corte(*_a, **_k):
        raise OSError("disco lleno")
    monkeypatch.setattr(os, "replace", corte)
    monkeypatch.setattr(Path, "replace", corte)
    datos = version.buscar_remota(clon, ahora=ahora + timedelta(hours=2))

    assert datos["ultima"] == "0.11.0"
    assert version.remota()["ultima"] == "0.10.0"





# ── C-0294: lo que se enseña de la consulta, y cómo se dice ──────────────────
#
# Un clon sin `origin` enseñaba un error apuntado tres semanas antes («La
# última vez que se miró falló: and the repository exists.») y prometía «Se
# mira cada hora» al lado de una fecha de hacía 21 días.


def _apuntado_viejo(error="and the repository exists."):
    (config.HUB_HOME / "version-remota.json").write_text(json.dumps({
        "ultima": None, "error": error, "mirado_en": "2026-10-21T06:25:00+00:00"}))


def test_un_clon_sin_origin_no_ensena_lo_apuntado_y_dice_que_no_busca(clon_con_remoto):
    clon, _ = clon_con_remoto
    _git("remote", "remove", "origin", cwd=clon)
    _apuntado_viejo()
    datos = version.para_la_guia(clon)
    assert datos["sin_remoto"] is True
    assert datos["buscar"] is False
    assert datos["error"] is None and datos["mirado_en"] is None


def test_lo_mirado_hace_mas_de_dos_horas_se_marca_atrasado(clon_con_remoto):
    clon, _ = clon_con_remoto
    _apuntado_viejo(error=None)
    datos = version.para_la_guia(clon)
    assert datos["atrasado"] is True
    assert datos["mirado_local"].startswith("21/10")


def test_del_error_de_git_se_guarda_la_linea_que_explica_no_la_ultima(clon_con_remoto):
    clon, publicado = clon_con_remoto
    shutil.rmtree(publicado)
    datos = version.buscar_remota(clon, forzar=True)
    assert datos["error"] != "and the repository exists."
    assert datos["error"].startswith("fatal:")


def test_actualizaciones_en_un_clon_sin_origin_no_promete_mirar_cada_hora(cliente, clon_con_remoto, monkeypatch):
    clon, _ = clon_con_remoto
    _git("remote", "remove", "origin", cwd=clon)
    monkeypatch.setattr(config, "RAIZ_REPO", clon)
    _apuntado_viejo()
    html = cliente.get("/actualizaciones").text
    assert "Este clon no tiene remoto" in html
    assert "and the repository exists" not in html
    assert "Se mira cada hora" not in html


def test_actualizaciones_dice_el_fallo_en_espanol_y_el_de_git_dentro_de_un_detalle(cliente, clon_con_remoto, monkeypatch):
    clon, publicado = clon_con_remoto
    shutil.rmtree(publicado)
    monkeypatch.setattr(config, "RAIZ_REPO", clon)
    html = cliente.get("/actualizaciones").text
    assert "No se pudo consultar el repositorio publicado" in html
    visible, _, detalle = html.partition("<details")
    assert "fatal:" not in visible and "fatal:" in detalle
