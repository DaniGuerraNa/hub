"""Que el hub se pueda instalar en una máquina que no es ésta.

Aquí ya está todo instalado, y eso es justo lo que oculta lo que falta: probar el
instalador en la máquina donde se escribió no demuestra nada. Estos tests atacan
las tres formas concretas en que la instalación se rompía en otro sitio:

1. el diagnóstico no distinguía «falta» de «está» — no existía;
2. los units cableaban `%h/projects/hub` y `%h/.local/bin/uv`, así que un clon
   en otra carpeta, o un `uv` en otro sitio, no arrancaba;
3. el registro estaba dentro del repo, y actualizar pisaba los datos.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DOCTOR = RAIZ / "scripts" / "doctor.sh"
INSTALAR = RAIZ / "scripts" / "instalar.sh"


# Ruta absoluta a propósito: uno de los tests vacía el PATH, y con `"bash"` a
# secas ni siquiera se llegaría a lanzar el script.
BASH = shutil.which("bash") or "/bin/bash"


def _correr(guion: Path, entorno: dict | None = None, *args: str):
    return subprocess.run(
        [BASH, str(guion), *args],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, **(entorno or {})},
    )


# ── el diagnóstico ───────────────────────────────────────────────────────────

def test_el_doctor_pasa_en_una_maquina_preparada():
    r = _correr(DOCTOR)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Todo lo imprescindible está" in r.stdout


def test_el_doctor_se_ha_visto_fallar(tmp_path):
    """Un verde que nadie ha visto en rojo no es evidencia.

    Se le da un PATH donde no hay nada, que es lo más parecido a una máquina
    recién instalada. Tiene que salir != 0 y **nombrar** lo que falta: un
    diagnóstico que sólo dice «error» no ayuda a nadie.
    """
    vacio = tmp_path / "bin"
    vacio.mkdir()
    r = _correr(DOCTOR, {"PATH": str(vacio)})
    assert r.returncode == 1
    assert "FALTA" in r.stdout or "falta" in r.stdout.lower()
    for imprescindible in ("git", "tmux", "uv"):
        assert imprescindible in r.stdout


def test_el_doctor_dice_la_consecuencia_y_no_solo_el_nombre():
    """«Falta docker» no le dice nada a quien acaba de clonar."""
    texto = DOCTOR.read_text(encoding="utf-8")
    assert "queda vacía" in texto      # docker
    assert "cae a grep" in texto       # ripgrep
    assert "no hay asistente" in texto  # claude


# ── los servicios ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre", ["hub-web", "hub-snapshotter"])
def test_los_units_son_plantillas_sin_rutas_cableadas(nombre):
    plantilla = RAIZ / "scripts" / f"{nombre}.service.plantilla"
    texto = plantilla.read_text(encoding="utf-8")
    assert "@RAIZ@" in texto and "@UV@" in texto
    # `%h/projects/hub` era la suposición que rompía cualquier clon en otra
    # carpeta, y no fallaba aquí porque aquí esa carpeta existe.
    assert "%h/projects/hub" not in texto
    assert "%h/.local/bin/uv" not in texto


def test_el_unit_generado_lleva_las_rutas_reales(tmp_path):
    """La sustitución del instalador, sin instalar nada: se aplica y se mira."""
    plantilla = (RAIZ / "scripts" / "hub-web.service.plantilla").read_text(encoding="utf-8")
    generado = (
        plantilla.replace("@RAIZ@", "/opt/hub-de-otro")
        .replace("@HUB_HOME@", "/opt/datos")
        .replace("@UV@", "/usr/local/bin/uv")
        .replace("@PATH@", "/usr/bin")
        .replace("@HOST@", "127.0.0.1")
        .replace("@PUERTO@", "9999")
    )
    assert "WorkingDirectory=/opt/hub-de-otro" in generado
    assert "/usr/local/bin/uv run uvicorn" in generado
    assert "--port 9999" in generado
    assert "@" not in re.sub(r"[\w.-]+@[\w.-]+", "", generado.replace("@RAIZ@", ""))


# ── el registro ──────────────────────────────────────────────────────────────

def test_el_instalador_no_pisa_un_registro_existente():
    """Lo dice el código, y es la línea que protege los datos de quien actualiza."""
    texto = INSTALAR.read_text(encoding="utf-8")
    assert 'if [ -f "$HUB_HOME/projects.yml" ]' in texto
    assert "no se toca" in texto


def test_el_instalador_verifica_que_el_hub_contesta():
    """Arrancar no es funcionar: el instalador espera un 200, no un exit 0."""
    texto = INSTALAR.read_text(encoding="utf-8")
    assert "%{http_code}" in texto
    assert "/inventario" in texto and "/respaldo" in texto


def test_la_semilla_del_asistente_esta_completa():
    """Sin esto, el asistente sólo existía en un disco y no en ningún repo."""
    semilla = RAIZ / "semillas" / "asistente"
    for relativa in ("CLAUDE.md", "bin/hub", "bin/contexto-statusline.sh",
                     ".claude/settings.json"):
        assert (semilla / relativa).is_file(), relativa
    ajustes = (semilla / ".claude" / "settings.json").read_text(encoding="utf-8")
    # La ruta de la statusline se resuelve al sembrar: Claude Code no expande
    # `~` ni variables en ese campo.
    assert "@ASIENTO@" in ajustes
    assert '"deny"' in ajustes and '"Write"' in ajustes


def test_el_instalador_y_el_doctor_son_ejecutables():
    for guion in (DOCTOR, INSTALAR, RAIZ / "scripts" / "desinstalar.sh",
                  RAIZ / "scripts" / "sembrar-asistente.sh"):
        assert guion.is_file(), guion
        assert shutil.which("bash")
        r = subprocess.run(["bash", "-n", str(guion)], capture_output=True, text=True)
        assert r.returncode == 0, f"{guion.name}: {r.stderr}"


# ── lo que ve un hub recién instalado ────────────────────────────────────────

@pytest.fixture
def hub_vacio(tmp_path, monkeypatch):
    """Un hub sin un solo proyecto: exactamente lo que encuentra quien instala.

    Devuelve el cliente y una función para escribir en su misma base, porque dos
    de estos tests necesitan declarar algo y volver a mirar la página.
    """
    from fastapi.testclient import TestClient

    from hub import db, web

    ruta = tmp_path / "hub.db"
    db.inicializar(db.conectar(ruta))  # existe desde ya: el cliente no la crea hasta la 1ª petición

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    return TestClient(web.app), conexion_de_pruebas


def test_el_hub_vacio_guia_en_vez_de_ensenar_pantallas_en_blanco(hub_vacio):
    cliente, _ = hub_vacio
    html = cliente.get("/").text
    assert "primer-arranque" in html
    assert "todavía no sabe nada tuyo" in html


def test_sin_asistente_declarado_no_se_pinta_su_pestana(hub_vacio):
    """La pestaña salía siempre, y el error aparecía al pulsarla."""
    cliente, _ = hub_vacio
    assert 'id="asistente-pestana"' not in cliente.get("/").text


def test_con_asistente_declarado_si_se_pinta(hub_vacio):
    cliente, conectar = hub_vacio
    con = conectar()
    con.execute(
        "INSERT INTO proyecto (id, nombre, tipo, asiento)"
        " VALUES ('asistente','Asistente','asistente','/tmp/asistente')"
    )
    con.commit()
    con.close()
    assert 'id="asistente-pestana"' in cliente.get("/").text


def test_la_guia_desaparece_en_cuanto_hay_un_proyecto(hub_vacio):
    """Se va sola al quedar superada por los hechos, sin tener que descartarla."""
    cliente, conectar = hub_vacio
    con = conectar()
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('mio','Mío')")
    con.commit()
    con.close()
    assert "primer-arranque" not in cliente.get("/").text


def test_sin_systemd_el_doctor_no_bloquea_y_ofrece_arrancar_a_mano(tmp_path):
    """🔴 Lo que vio la primera instalación en limpio (3-sep): sin systemd de
    usuario el doctor decía FALTA, el instalador no seguía, y el único consejo
    era editar /etc/wsl.conf y reiniciar Windows — dentro de un Ubuntu que no
    era WSL. systemd sólo decide si el hub arranca solo; sin él se arranca a mano."""
    falso = tmp_path / "bin"
    falso.mkdir()
    (falso / "systemctl").write_text("#!/bin/sh\nexit 1\n")
    (falso / "systemctl").chmod(0o755)
    r = _correr(DOCTOR, {"PATH": f"{falso}:{os.environ['PATH']}"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "a mano" in r.stdout
    assert "--sin-servicios" in r.stdout
    assert "Todo lo imprescindible está" in r.stdout


def test_sin_systemd_el_instalador_cae_al_arranque_a_mano():
    texto = (RAIZ / "scripts" / "instalar.sh").read_text(encoding="utf-8")
    assert "systemctl --user show-environment" in texto
    assert "CON_SERVICIOS=0" in texto.split('paso "4/5')[1]


def test_el_arranque_a_mano_levanta_la_web_y_el_snapshotter():
    """Sin systemd, arrancar sólo la web deja un hub que no relee el registro."""
    guion = RAIZ / "scripts" / "arrancar.sh"
    assert os.access(guion, os.X_OK)
    texto = guion.read_text(encoding="utf-8")
    assert "uvicorn hub.web:app" in texto
    assert "python -m hub.snapshotter" in texto
    instalador = (RAIZ / "scripts" / "instalar.sh").read_text(encoding="utf-8")
    assert "scripts/arrancar.sh" in instalador.split('paso "4/5')[1]


# ── la sala limpia ───────────────────────────────────────────────────────────

def test_la_sala_limpia_esta_completa_y_sin_rastros_personales():
    """Los tres archivos existen, los dos guiones son ejecutables, y la imagen no
    hornea nada de esta máquina: las credenciales entran en `arrancar`, no aquí."""
    sala = RAIZ / "scripts" / "sala-limpia"
    for nombre in ("Dockerfile", "sala.sh", "persona.sh"):
        assert (sala / nombre).is_file(), nombre
    for guion in ("sala.sh", "persona.sh"):
        assert os.access(sala / guion, os.X_OK), guion
    dockerfile = (sala / "Dockerfile").read_text(encoding="utf-8")
    assert "credentials" not in dockerfile
    # Ningún home que no sea el de la persona, ni rutas de la máquina de nadie.
    assert re.findall(r"/home/(?!persona\b)\w+", dockerfile) == []
    assert "/mnt/" not in dockerfile
    assert "USER persona" in dockerfile          # nunca root: claude se niega
    sala_sh = (sala / "sala.sh").read_text(encoding="utf-8")
    assert "-p " not in sala_sh.split("docker run -d")[1].split("\n")[0]  # sin puertos mapeados
    # En el repo de desarrollo el índice está en producto/; en el publicado, en conocimiento/.
    indice = next(r for r in (RAIZ / "producto/conocimiento/INDICE.md", RAIZ / "conocimiento/INDICE.md") if r.is_file())
    assert "08-sala-limpia.md" in indice.read_text(encoding="utf-8")
