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
import sys
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
    assert "Environment=HUB_PORT=9999" in generado
    assert "@" not in re.sub(r"[\w.-]+@[\w.-]+", "", generado.replace("@RAIZ@", ""))


@pytest.mark.parametrize("nombre", ["hub-web", "hub-snapshotter", "hub-canal", "hub-encargos", "hub-secretario"])
def test_todos_los_servicios_saben_en_que_puerto_esta_la_web(nombre):
    """El pánico corre en `hub-canal` y comprobaba 8787 aunque el hub se
    hubiera instalado en otro puerto: `HUB_PORT` sólo llegaba al ExecStart."""
    texto = (RAIZ / "scripts" / f"{nombre}.service.plantilla").read_text(encoding="utf-8")
    assert "Environment=HUB_PORT=@PUERTO@" in texto


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


def test_la_guia_desaparece_en_cuanto_hay_un_proyecto(hub_vacio, tmp_path):
    """Se va sola al quedar superada por los hechos, sin tener que descartarla."""
    cliente, conectar = hub_vacio
    con = conectar()
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('mio','Mío',?)", (str(tmp_path),))
    con.commit()
    con.close()
    assert "primer-arranque" not in cliente.get("/").text


def test_los_proyectos_de_ejemplo_no_esconden_la_guia(hub_vacio):
    """🔴 El registro recién instalado trae dos de ejemplo con rutas inventadas.
    Contándolos, la guía de la portada no salía nunca en una instalación nueva,
    que es el único sitio donde existe (sala limpia, 16-oct)."""
    cliente, conectar = hub_vacio
    con = conectar()
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES "
                "('mi-proyecto','Mi proyecto','~/dev/no-existe-de-verdad')")
    con.commit()
    con.close()
    assert "primer-arranque" in cliente.get("/").text


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


# ── lo que salió en la segunda ronda de pruebas en limpio (14-oct) ───────────

def test_un_python3_viejo_en_el_sistema_no_bloquea_si_uv_tiene_el_suyo(tmp_path):
    """🔴 Ubuntu 22.04 trae 3.10. El doctor miraba `python3`, decía FALTA y
    aconsejaba `uv python install 3.12` — que no cambia `python3`, así que
    seguía en FALTA después de hacerle caso. El hub corre con `uv run`."""
    falso = tmp_path / "bin"
    falso.mkdir()
    (falso / "python3").write_text("#!/bin/sh\necho 3.10\n")
    (falso / "python3").chmod(0o755)
    r = _correr(DOCTOR, {"PATH": f"{falso}:{os.environ['PATH']}"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "3.10" not in r.stdout
    assert "(el que usa uv)" in r.stdout


def test_el_repo_fija_python_3_12_para_que_uv_no_baje_el_mas_nuevo():
    """🔴 Sin `.python-version`, en una máquina sin 3.12 uv bajó 3.15 y no había
    ruedas de `httptools` para él: intentó compilar, no había `cc`, y la
    instalación falló en una WSL recién estrenada."""
    assert (RAIZ / ".python-version").read_text().strip() == "3.12"


def _puerto_ocupado():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


def test_con_el_puerto_ocupado_arrancar_lo_dice_y_no_finge(tmp_path):
    """El 14-oct: puerto ocupado, `hub-web` moría con Errno 98, y la
    comprobación hablaba con el otro programa y daba el visto bueno."""
    s, puerto = _puerto_ocupado()
    try:
        r = _correr(RAIZ / "scripts" / "arrancar.sh",
                    {"HUB_PORT": str(puerto), "HUB_HOME": str(tmp_path)})
    finally:
        s.close()
    assert r.returncode == 1
    assert "ya lo usa otro programa" in r.stderr


def test_el_doctor_ve_el_puerto_ocupado():
    s, puerto = _puerto_ocupado()
    try:
        r = _correr(DOCTOR, {"HUB_PORT": str(puerto)})
    finally:
        s.close()
    assert "ya hay algo escuchando" in r.stdout


def test_el_instalador_no_da_por_buena_una_pantalla_que_falla():
    """Decía «Listo» y salía con 0 con pantallas en 404."""
    texto = INSTALAR.read_text(encoding="utf-8")
    comprobacion = texto.split('paso "5/5')[1]
    assert 'apple-mobile-web-app-title" content="Hub"' in comprobacion   # es el hub quien contesta
    assert comprobacion.index("exit 1", comprobacion.index("fallos")) < comprobacion.index("Listo.")


def test_sembrar_el_asistente_lo_declara_dentro_de_proyectos_y_el_registro_sigue_leyendose(tmp_path):
    """🔴 Sala limpia, 16-oct: el script imprimía el bloque y un «Añade:», y
    pegarlo al final del archivo lo dejaba debajo de `conexiones: []`. El
    registro entero dejaba de leerse. Ahora se declara solo, en su sitio."""
    casa = tmp_path / "otra-casa"
    casa.mkdir()
    shutil.copy(RAIZ / "projects.ejemplo.yml", casa / "projects.yml")
    destino = tmp_path / "asistente"
    entorno = {"HUB_HOME": str(casa), "HUB_PROJECTS_YML": str(casa / "projects.yml"),
               "HUB_BIN": str(tmp_path / "bin")}

    r = _correr(RAIZ / "scripts" / "sembrar-asistente.sh", entorno, str(destino))

    assert r.returncode == 0, r.stdout + r.stderr
    assert "declarado en tu registro" in r.stdout
    leer = subprocess.run(
        ["uv", "run", "--quiet", "python", "-c",
         "from hub import registry; ps = registry.cargar();"
         "print(sorted(p.id for p in ps), [p.asiento for p in ps if p.tipo == 'asistente'])"],
        cwd=RAIZ, capture_output=True, text=True, env={**os.environ, **entorno}, timeout=120)
    assert leer.returncode == 0, leer.stderr
    assert "'asistente'" in leer.stdout and str(destino) in leer.stdout
    assert "conexiones: []" in (casa / "projects.yml").read_text(encoding="utf-8")

    otro = tmp_path / "asistente2"
    r2 = _correr(RAIZ / "scripts" / "sembrar-asistente.sh", entorno, str(otro))
    assert "ya había un asistente" in r2.stdout     # no se duplica ni se pisa


def _sembrar_en(tmp_path, bin_):
    casa = tmp_path / "casa"
    casa.mkdir(exist_ok=True)
    shutil.copy(RAIZ / "projects.ejemplo.yml", casa / "projects.yml")
    entorno = {"HUB_HOME": str(casa), "HUB_PROJECTS_YML": str(casa / "projects.yml"),
               "HUB_BIN": str(bin_)}
    destino = tmp_path / "asistente"
    return _correr(RAIZ / "scripts" / "sembrar-asistente.sh", entorno, str(destino)), destino


def test_sembrar_el_asistente_deja_el_comando_hub_en_el_path_del_usuario(tmp_path):
    """Decisión 278: las skills usan `hub` fuera del chat, y en una máquina
    nueva sólo existía dentro del asistente."""
    bin_ = tmp_path / "bin"
    r, destino = _sembrar_en(tmp_path, bin_)
    assert r.returncode == 0, r.stdout + r.stderr
    enlace = bin_ / "hub"
    assert enlace.is_symlink() and os.readlink(enlace) == str(destino / "bin" / "hub")
    assert "comando hub en" in r.stdout


def test_sembrar_no_pisa_un_hub_que_ya_existia_en_esa_ruta(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    suyo = bin_ / "hub"
    suyo.write_text("#!/bin/sh\necho otro\n")
    r, _ = _sembrar_en(tmp_path, bin_)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not suyo.is_symlink() and "echo otro" in suyo.read_text()
    assert "no se toca" in r.stdout


def _desinstalar_con_datos(tmp_path, entorno_hub_home: str, respuesta: str, respaldo: str = "",
                           respaldo_del_unit: str = ""):
    """`desinstalar.sh --datos` en una casa de mentira, con un `systemctl`
    falso delante: el de verdad pararía los servicios de quien corre la suite."""
    casa = tmp_path / "casa"
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    (bin_ / "systemctl").chmod(0o755)
    unidades = casa / ".config" / "systemd" / "user"
    unidades.mkdir(parents=True)
    datos = tmp_path / "datos-de-verdad"
    (datos / "respaldos").mkdir(parents=True)
    (datos / "respaldos" / "hub-20261105.db").write_bytes(b"x")
    (datos / "secretario").mkdir()
    (datos / "secretario" / "memoria.db").write_bytes(b"x")
    (datos / "hub.db").write_bytes(b"x")
    (unidades / "hub-web.service").write_text(
        f"[Service]\nEnvironment=HUB_HOME={datos}\n"
        "ExecStart=/x/uv run uvicorn hub.web:app --host 127.0.0.1 --port 8787\n")
    if respaldo_del_unit:
        (unidades / "hub-snapshotter.service").write_text(
            f"[Service]\nEnvironment=HUB_HOME={datos}\nEnvironment=HUB_RESPALDO={respaldo_del_unit}\n")
    r = subprocess.run(
        [BASH, str(RAIZ / "scripts" / "desinstalar.sh"), "--datos"], input=respuesta + "\n",
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": str(casa), "XDG_CONFIG_HOME": str(casa / ".config"),
             "PATH": f"{bin_}:{os.environ['PATH']}", "HUB_HOME": entorno_hub_home,
             "HUB_RESPALDO": respaldo},
    )
    return r, datos


def test_desinstalar_datos_borra_el_hub_home_del_servicio_y_no_uno_supuesto(tmp_path):
    """C-0114: usaba el `HUB_HOME` del entorno (o el de por omisión), no el
    del servicio instalado: borraba una carpeta que no era y dejaba los datos."""
    supuesto = tmp_path / "supuesto"
    supuesto.mkdir()
    (supuesto / "algo").write_text("no es del hub")
    r, datos = _desinstalar_con_datos(tmp_path, str(supuesto), "borrar")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not datos.exists()
    assert (supuesto / "algo").exists()


def test_desinstalar_datos_dice_todo_lo_que_se_va_antes_de_pedir_borrar(tmp_path):
    """El aviso sólo nombraba «tus notas de slots»; con la carpeta se van
    también las copias de cada día y la memoria del secretario."""
    r, datos = _desinstalar_con_datos(tmp_path, "", "no")
    salida = r.stdout + r.stderr
    assert str(datos) in salida
    assert "respaldos" in salida and "secretario" in salida
    assert datos.exists()


def test_desinstalar_datos_dice_que_las_copias_fuera_de_la_carpeta_no_se_tocan(tmp_path):
    """C-0186: con `HUB_RESPALDO` fuera de `HUB_HOME`, las copias diarias no se
    borran —están en otra carpeta— y el aviso no lo decía: quien quería
    llevárselo todo creía que ya no quedaba nada."""
    fuera = tmp_path / "copias-en-otro-disco"
    fuera.mkdir()
    (fuera / "hub-20261105.db").write_bytes(b"x")

    r, datos = _desinstalar_con_datos(tmp_path, "", "borrar", respaldo=str(fuera))

    assert r.returncode == 0, r.stdout + r.stderr
    assert not datos.exists() and (fuera / "hub-20261105.db").exists()
    assert str(fuera) in r.stdout and "no se toca" in r.stdout


def test_desinstalar_las_copias_de_fuera_las_dice_el_servicio_instalado_y_no_el_entorno(tmp_path):
    """Como `HUB_HOME` (C-0114): manda lo que usa el servicio, no lo que diga
    la shell desde la que se desinstala."""
    del_servicio, de_la_shell = tmp_path / "copias-del-servicio", tmp_path / "copias-de-la-shell"
    r, _ = _desinstalar_con_datos(tmp_path, "", "no", respaldo=str(de_la_shell),
                                  respaldo_del_unit=str(del_servicio))
    assert r.returncode == 0, r.stdout + r.stderr
    assert str(del_servicio) in r.stdout and str(de_la_shell) not in r.stdout


def test_desinstalar_datos_sin_servicios_instalados_tambien_avisa_de_las_copias(tmp_path):
    """Sin units que leer, buscar `HUB_RESPALDO` en ellos no puede tumbar el
    guion (`set -e` con `pipefail`): se dice la frase general y se sigue."""
    casa, bin_, datos = tmp_path / "casa", tmp_path / "bin", tmp_path / "datos"
    for d in (casa, bin_, datos):
        d.mkdir()
    (bin_ / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    (bin_ / "systemctl").chmod(0o755)
    (datos / "hub.db").write_bytes(b"x")
    r = subprocess.run(
        [BASH, str(RAIZ / "scripts" / "desinstalar.sh"), "--datos"], input="no\n",
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": str(casa), "XDG_CONFIG_HOME": str(casa / ".config"),
             "PATH": f"{bin_}:{os.environ['PATH']}", "HUB_HOME": str(datos), "HUB_RESPALDO": ""},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HUB_RESPALDO" in r.stdout and datos.exists()


def test_desinstalar_solo_quita_el_enlace_si_lleva_al_asistente():
    texto = (RAIZ / "scripts" / "desinstalar.sh").read_text(encoding="utf-8")
    bloque = texto.split("ENLACE=")[1].split("\nfi\n")[0]
    assert "el asistente" in bloque and 'rm -f "$ENLACE"' in bloque


# ── C-0112: el hub sólo escucha en esta máquina (regla dura 8) ───────────────

@pytest.mark.parametrize("guion", ["instalar.sh", "arrancar.sh"])
@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::", "mi-pc.local"])
def test_los_guiones_se_niegan_a_escuchar_fuera_de_esta_maquina(tmp_path, guion, host):
    r = _correr(RAIZ / "scripts" / guion, {"HUB_HOST": host, "HUB_HOME": str(tmp_path / "home"),
                                            "HUB_PORT": "1"}, "--sin-servicios")
    assert r.returncode != 0
    assert "sólo escucha en esta máquina" in r.stderr
    assert not (tmp_path / "home").exists(), "paró después de empezar a instalar"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_la_guarda_de_loopback_deja_pasar_lo_de_esta_maquina(host):
    r = subprocess.run([BASH, "-c", f'. "{RAIZ}/scripts/lib/loopback.sh"; exigir_loopback "{host}"; echo sigue'],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "sigue"


def test_actualizar_no_conserva_un_unit_que_escucha_fuera():
    texto = (RAIZ / "scripts" / "actualizar.sh").read_text(encoding="utf-8")
    assert texto.index('exigir_loopback "$HUB_HOST"') < texto.index('paso "1/7')


# 🔴 Direcciones de documentación, que no se pueden abrir: si la guarda dejara
# de funcionar, el test fallaría sin dejar el hub escuchando en la red ni un
# segundo (regla 8: «ni temporalmente»). Con 0.0.0.0 sí lo dejaba.
@pytest.mark.parametrize("host", ["192.0.2.1", "2001:db8::1"])
def test_la_web_no_arranca_escuchando_fuera(host, tmp_path):
    """Con uvicorn de verdad, como lo lanza el unit: `--host` no pasa por
    `main()`, así que lo para el arranque de la app."""
    r = subprocess.run(
        [sys.executable, "-m", "uvicorn", "hub.web:app", "--host", host, "--port", "0"],
        capture_output=True, text=True, timeout=60, cwd=RAIZ,
        env={**os.environ, "HUB_HOME": str(tmp_path)},
    )
    assert r.returncode != 0
    assert "sólo escucha en esta máquina" in r.stderr
    assert "Uvicorn running" not in r.stderr


def test_la_web_lee_el_host_de_la_orden_en_sus_dos_formas():
    from hub import web

    assert web._host_de_la_orden(["uvicorn", "hub.web:app", "--host", "0.0.0.0"]) == "0.0.0.0"
    assert web._host_de_la_orden(["uvicorn", "--host=::", "hub.web:app"]) == "::"
    assert web._host_de_la_orden(["uvicorn", "hub.web:app"], {}) == "127.0.0.1"
    # uvicorn también lo toma del entorno (revisor de C-0112).
    assert web._host_de_la_orden(["uvicorn", "hub.web:app"], {"UVICORN_HOST": "0.0.0.0"}) == "0.0.0.0"
