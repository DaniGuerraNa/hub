"""Contar un fallo o una idea a quien mantiene el hub (C-0468, decisión 445).

Lo que se protege: que los datos del equipo salgan de la lista blanca y no
lleven rutas, usuario ni el nombre del equipo; que el enlace vaya al
formulario de la plantilla y nunca lleve la URL del remoto (puede llevar un
token), ni `labels=` ni `body=`; que las plantillas de GitHub y el código
hablen de los mismos campos; y que la pantalla no mande nada por su cuenta.

Lo que se prueba ejecutándolo de verdad (git contra un clon temporal, la
pantalla servida por la app) y no con dobles, salvo lo que haría falta
estropear la máquina para provocar: un usuario y un equipo inventados.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from hub import api, config, db, incidencias, tmux, version, web

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLAS_GITHUB = RAIZ / ".github" / "ISSUE_TEMPLATE"

USUARIO = "persona-inventada"
EQUIPO = "equipo-inventado-7"


def _git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
                            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def clon(tmp_path):
    """Un clon de verdad, con un commit y sin `origin`, como el de quien desarrolla."""
    carpeta = tmp_path / "clon"
    carpeta.mkdir()
    _git("init", "-q", "-b", "main", cwd=carpeta)
    (carpeta / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.8.0"\n')
    _git("add", ".", cwd=carpeta)
    _git("commit", "-q", "-m", "uno", cwd=carpeta)
    return carpeta


@pytest.fixture
def persona_inventada(tmp_path, monkeypatch):
    """Un usuario, una carpeta personal y un equipo que no son de nadie: si
    alguno aparece en lo que sale, se ha filtrado algo de la máquina."""
    casa = tmp_path / "home" / USUARIO
    casa.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("USER", USUARIO)
    monkeypatch.setenv("LOGNAME", USUARIO)
    monkeypatch.setattr(socket, "gethostname", lambda: EQUIPO)
    monkeypatch.setattr(platform, "node", lambda: EQUIPO)
    return casa


def _salud_con_texto_propio(casa: Path) -> list[dict]:
    """Lo que devuelve `salud.revisar`, con lo peor que puede traer: el
    arreglo de seguir vivo sin terminal lleva el usuario (decisión 289)."""
    return [
        {"clave": "linger", "nombre": "Seguir vivo sin terminal", "estado": "aviso",
         "detalle": f"Al cerrar la última terminal en {casa}…",
         "arreglo": f"loginctl enable-linger {USUARIO}"},
        {"clave": "muestreo", "nombre": "Muestreo", "estado": "ok", "detalle": "Late."},
        {"clave": "servicio:hub-web", "nombre": "hub-web", "estado": "ok", "detalle": "En marcha."},
        # Una clave con forma de ruta o un estado que no existe no salen.
        {"clave": f"{casa}/raro", "estado": "mal"},
        {"clave": "copia", "estado": f"de {USUARIO}"},
    ]


def _datos(casa: Path, **cambios) -> list[tuple[str, str]]:
    argumentos = dict(
        version={"codigo": "0.8.0", "instalada": "0.7.2", "falta_terminar": True},
        commit="33c6d93", con_cambios=True, salud=_salud_con_texto_propio(casa),
        encendidas=frozenset({"puente-kvm"}), interfaz="nueva",
        navegador="Mozilla/5.0 (X11; Linux x86_64) Chrome/131.0 Safari/537.36",
        agente_reuniones="0.3.0", de="puente-kvm")
    argumentos.update(cambios)
    return incidencias.datos_del_equipo(**argumentos)


# ── la lista blanca ──────────────────────────────────────────────────────────


def test_los_datos_del_equipo_no_llevan_ni_rutas_ni_usuario_ni_el_nombre_del_equipo(persona_inventada):
    texto = incidencias.como_texto(_datos(persona_inventada))

    for no_puede in (USUARIO, EQUIPO, str(persona_inventada), "/home/", str(config.HUB_HOME)):
        assert no_puede not in texto, no_puede
    # Y lo que sí tiene que decir, para que el aviso sirva.
    assert "Versión del hub: 0.8.0 (instalada del todo: 0.7.2; falta terminar de actualizar)" in texto
    assert "Commit: 33c6d93, con cambios locales" in texto
    assert "Desde: Puente KVM" in texto
    assert "Herramientas opcionales: puente-kvm" in texto
    assert "Agente de Reuniones: 0.3.0" in texto
    assert f"Python: {platform.python_version()}" in texto


def test_de_la_salud_solo_salen_la_clave_y_el_estado():
    filas = dict(_datos(Path("/home/alguien")))

    assert filas["Salud del hub"] == "linger aviso · 2 más ok"
    assert "loginctl" not in incidencias.como_texto(_datos(Path("/home/alguien")))


def test_lo_que_no_tiene_la_forma_esperada_no_sale():
    """Lista blanca de verdad: un valor que no casa con su forma se cae, no
    se copia tal cual con la esperanza de que sea inofensivo."""
    filas = dict(_datos(Path("/x"), commit="no es un commit; rm -rf", agente_reuniones="/home/x/agente",
                        de="otro-sitio", interfaz="de-otro", encendidas=frozenset({"puente-kvm", "a b/c"}),
                        version={"codigo": "../../etc", "falta_terminar": False}))

    assert filas["Commit"] == "no se pudo leer"
    assert filas["Versión del hub"] == "no se pudo leer"
    assert filas["Herramientas opcionales"] == "puente-kvm"
    assert "Agente de Reuniones" not in filas
    assert "Desde" not in filas
    assert "Interfaz" not in filas


def test_el_navegador_va_en_una_linea_y_recortado():
    filas = dict(_datos(Path("/x"), navegador="Mozilla\n\x07" + "x" * 400))

    assert "\n" not in filas["Navegador"] and "\x07" not in filas["Navegador"]
    assert len(filas["Navegador"]) <= 160


def test_el_sistema_nunca_lleva_el_nombre_del_equipo(persona_inventada):
    filas = dict(_datos(persona_inventada))
    assert EQUIPO not in filas["Sistema"]
    assert platform.release() in filas["Sistema"]


def test_sin_claude_en_el_path_de_usuario_lo_dice(monkeypatch, tmp_path):
    monkeypatch.setattr(tmux, "path_de_usuario", lambda extra=None: str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert dict(_datos(tmp_path))["Claude Code"] == "no se encontró"


def test_claude_en_la_carpeta_de_usuario_se_encuentra_con_el_path_de_systemd(monkeypatch, tmp_path):
    """El PATH de `hub-web` bajo systemd no trae `~/.local/bin` (decisión 81):
    sin mirar ahí, la incidencia diría «no se encontró» con Claude instalado."""
    casa = tmp_path / "casa"
    propio = casa / ".local" / "bin" / "claude"
    propio.parent.mkdir(parents=True)
    propio.write_text("#!/bin/sh\necho '2.1.322 (Claude Code)'\n")
    propio.chmod(0o755)
    sistema = tmp_path / "bin-del-sistema"   # el de systemd, sin nada propio de la persona
    sistema.mkdir()
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("PATH", str(sistema))

    from hub import maquina
    assert maquina.encontrar("claude") is None
    assert maquina.encontrar("claude", de_usuario=True) == str(propio)
    assert dict(_datos(tmp_path))["Claude Code"] == "2.1.322"


def test_un_claude_que_no_contesta_no_cuelga_la_pantalla(monkeypatch, tmp_path):
    colgado = tmp_path / "claude"
    colgado.write_text(f"#!/bin/sh\nexec {shutil.which('sleep')} 30\n")
    colgado.chmod(0o755)
    monkeypatch.setattr(tmux, "path_de_usuario", lambda extra=None: str(tmp_path))
    monkeypatch.setattr(incidencias, "ESPERA_CLAUDE", 0.3)

    assert dict(_datos(tmp_path))["Claude Code"] == "no contestó en 0.3 s"


def test_de_claude_code_solo_pasa_su_numero_de_version(monkeypatch, tmp_path):
    falso = tmp_path / "claude"
    falso.write_text(f"#!/bin/sh\necho '2.1.322 (Claude Code) {tmp_path}'\n")
    falso.chmod(0o755)
    monkeypatch.setattr(tmux, "path_de_usuario", lambda extra=None: str(tmp_path))

    assert dict(_datos(tmp_path))["Claude Code"] == "2.1.322"


def test_la_version_de_tmux_va_por_el_adaptador_y_solo_si_tiene_forma_de_version(monkeypatch):
    real = tmux.version()
    assert real is None or len(real) <= 20

    monkeypatch.setattr(tmux, "_correr", lambda args: "tmux 3.4\n")
    assert tmux.version() == "3.4"
    monkeypatch.setattr(tmux, "_correr", lambda args: "tmux 3.4 en /home/alguien\n")
    assert tmux.version() == ""  # está, pero lo que dijo no sale
    assert dict(_datos(Path("/x")))["tmux"] == "no se pudo leer"

    def sin_tmux(args):
        raise tmux.TmuxNoDisponible("tmux no está en el PATH")
    monkeypatch.setattr(tmux, "_correr", sin_tmux)
    assert tmux.version() is None
    assert dict(_datos(Path("/x")))["tmux"] == "no está"


# ── a dónde se abre ──────────────────────────────────────────────────────────


def test_el_destino_es_el_formulario_nuevo_del_repo_y_nada_mas():
    assert incidencias.destino("alguien/hub") == "https://github.com/alguien/hub/issues/new"
    assert incidencias.destino(None) is None
    for malo in ("https://github.com/alguien/hub", "alguien/hub?labels=x", "alguien", "a/b/c", "a/b&body=x"):
        assert incidencias.destino(malo) is None, malo


def test_sin_origin_de_github_no_hay_destino(clon):
    assert version.repo_github(clon) is None
    _git("remote", "add", "origin", "https://gitlab.com/alguien/hub.git", cwd=clon)
    assert version.repo_github(clon) is None


def test_un_origin_con_token_da_el_repo_y_nunca_la_llave(clon, monkeypatch):
    _git("remote", "add", "origin", "https://x-access-token:LLAVE123@github.com/alguien/hub.git", cwd=clon)
    monkeypatch.setattr(config, "RAIZ_REPO", clon)

    assert version.repo_github() == "alguien/hub"
    datos = api.incidencia(_con(), interfaz="clasica", navegador=None)
    assert datos["destino"] == "https://github.com/alguien/hub/issues/new"
    assert "LLAVE123" not in json.dumps(datos)


def test_el_commit_es_el_corto_del_clon(clon):
    corto = version.commit(clon)
    assert corto and corto == _git("rev-parse", "--short", "HEAD", cwd=clon).strip()


def test_fuera_de_un_clon_no_hay_commit(tmp_path):
    assert version.commit(tmp_path) is None


# ── las plantillas de GitHub ─────────────────────────────────────────────────


@pytest.mark.parametrize("tipo", sorted(incidencias.TIPOS))
def test_cada_plantilla_tiene_los_campos_que_rellena_el_hub(tipo):
    """El hub rellena por `id`: un campo renombrado en la plantilla deja el
    enlace abriendo un formulario vacío, sin ningún error que lo diga."""
    plantilla = yaml.safe_load((PLANTILLAS_GITHUB / incidencias.TIPOS[tipo]).read_text(encoding="utf-8"))
    campos = {c["id"]: c for c in plantilla["body"] if "id" in c}

    assert tuple(campos) == incidencias.CAMPOS
    assert campos["que_paso"]["attributes"]["label"] == incidencias.ROTULOS[tipo]["campo"]
    # Las etiquetas van en la plantilla: en la URL darían 404 a quien no
    # tiene permiso en el repositorio.
    assert plantilla["labels"] == [tipo]


def test_las_plantillas_son_las_que_nombra_el_codigo_y_ninguna_mas():
    en_disco = {p.name for p in PLANTILLAS_GITHUB.glob("*.yml")} - {"config.yml"}
    assert en_disco == set(incidencias.TIPOS.values())


def test_la_configuracion_de_github_no_lleva_ningun_correo():
    texto = (PLANTILLAS_GITHUB / "config.yml").read_text(encoding="utf-8")
    config_ = yaml.safe_load(texto)
    assert config_["blank_issues_enabled"] is True
    assert "@" not in texto and "mailto" not in texto


# ── la pantalla ──────────────────────────────────────────────────────────────


def _con():
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    return con


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setattr(web, "conexion", _con)
    return TestClient(web.app)


def test_sin_github_detras_solo_se_ofrece_copiar_y_se_dice_por_que(http, monkeypatch):
    monkeypatch.setattr(version, "repo_github", lambda raiz=None: None)
    html = http.get("/incidencia").text

    assert 'id="inc-abrir"' not in html
    assert '<button type="button" class="cta" id="inc-copiar">Copiar el texto</button>' in html
    assert "No hay a dónde abrirlo" in html
    assert "Lo que mandes a GitHub es público" in html


def test_con_github_detras_el_enlace_abre_la_plantilla_sin_etiquetas_ni_cuerpo(http, monkeypatch):
    monkeypatch.setattr(version, "repo_github", lambda raiz=None: "alguien/hub")
    html = http.get("/incidencia", params={"tipo": "mejora", "titulo": "Ordenar los slots"}).text

    assert ('href="https://github.com/alguien/hub/issues/new?template=mejora.yml'
            '&amp;title=Ordenar%20los%20slots"') in html
    assert 'rel="noopener noreferrer"' in html
    assert "labels=" not in html and "body=" not in html and "assignees=" not in html
    assert 'id="tipo-mejora" value="mejora"' in html
    assert ">Qué te gustaría</label>" in html


def test_un_tipo_que_no_existe_cae_en_fallo(http):
    html = http.get("/incidencia", params={"tipo": "otro"}).text
    assert ">Qué pasó</label>" in html
    assert 'id="tipo-fallo" value="fallo"' in html.split("checked>")[0].rsplit("<input", 1)[1]


def test_desde_el_puente_lo_dice_y_lo_lleva_en_los_datos(http):
    html = http.get("/incidencia", params={"de": "puente-kvm"}).text
    assert "Vienes del Puente KVM" in html
    assert "Desde: Puente KVM" in html
    assert 'value="Puente KVM: "' in html

    otro = http.get("/incidencia", params={"de": "otro-sitio"}).text
    assert "Vienes del" not in otro and "Desde:" not in otro


def test_la_pantalla_no_tiene_por_donde_recibir_nada():
    """El hub no envía nada (445): ni una ruta que no sea GET."""
    metodos = {m for r in web.app.routes if getattr(r, "path", "") == "/incidencia" for m in r.methods}
    assert metodos <= {"GET", "HEAD"}


def test_la_pantalla_no_lleva_lo_que_no_sale_aunque_la_salud_lo_traiga(http, monkeypatch, persona_inventada):
    """De `api.salud` sólo pasan la clave y el estado, también por la ruta de verdad."""
    monkeypatch.setattr(api, "salud", lambda con: _salud_con_texto_propio(persona_inventada))
    html = http.get("/incidencia", headers={"user-agent": "Navegador/1.0"}).text
    equipo = html.split('id="inc-equipo">')[1].split("</pre>")[0]

    assert "Salud del hub: linger aviso" in equipo
    assert "Navegador: Navegador/1.0" in equipo
    for no_puede in (USUARIO, EQUIPO, "loginctl", "/home/"):
        assert no_puede not in equipo, no_puede


def test_se_llega_desde_actualizaciones_la_guia_y_el_mapa(http):
    assert 'href="/incidencia"' in http.get("/actualizaciones").text
    from hub import guia, navegacion
    assert any(p["ruta"] == "/incidencia" for p in guia.PANTALLAS)
    assert navegacion.de_pantalla("incidencia", "/incidencia") == "ajustes"
