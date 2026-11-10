"""La salud del hub: lo que tiene que estar en pie para que un apagón tenga
vuelta (decisión 289). Un usuario apagó, encendió al día siguiente y no le
volvió nada; ninguna pantalla lo había advertido antes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from hub import acceso, api, config, salud, web

from test_vistas_web import cliente  # noqa: F401  — el cliente con base de pruebas


AHORA = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _latido(hace_segundos, desde=AHORA):
    (config.HUB_HOME / salud.ARCHIVO_LATIDO).write_text(json.dumps(
        {"en": (desde - timedelta(seconds=hace_segundos)).isoformat(), "pid": 1}))


@pytest.mark.parametrize("hace, estado", [(15, "ok"), (150, "aviso"), (3600, "mal")])
def test_el_muestreo_se_juzga_por_su_latido(hace, estado):
    _latido(hace)
    assert salud.muestreo(AHORA)["estado"] == estado


def test_sin_latido_nunca_el_muestreo_esta_mal_y_dice_que_no_habra_restauracion():
    m = salud.muestreo(AHORA)
    assert m["estado"] == "mal" and "reabrir" in m["detalle"]
    assert "systemctl --user restart hub-snapshotter" in m["arreglo"]


def test_latir_deja_un_latido_de_ahora():
    salud.latir()
    assert salud.muestreo()["estado"] == "ok"


def test_avisa_si_ningun_slot_vuelve_tras_un_apagon(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('p','P')")
    con.execute("INSERT INTO slot (proyecto_id, nombre, creado_en) VALUES ('p','a','x'), ('p','b','x')")
    r = salud._restauracion(api.slots_activos(con))
    assert r["estado"] == "aviso" and "Ninguno de tus 2 slots es persistente" in r["detalle"]

    con.execute("UPDATE slot SET restaurar=1 WHERE nombre='a'")
    assert salud._restauracion(api.slots_activos(con))["detalle"].startswith("1 de 2 slots")


def test_con_el_muestreo_parado_todas_las_pantallas_lo_dicen(cliente):  # noqa: F811
    _latido(3600, datetime.now(timezone.utc))
    assert "no late desde hace 60 min" in cliente.get("/guia").text
    _latido(5, datetime.now(timezone.utc))
    assert "no late desde hace" not in cliente.get("/guia").text


def test_la_salud_sale_en_maquina_con_su_arreglo(cliente):  # noqa: F811
    html = cliente.get("/maquina").text
    assert 'id="salud"' in html and "Muestreo" in html and "Arreglo:" in html
    assert cliente.get("/api/salud").json()["revisiones"][0]["estado"] == "mal"


# ── C-0115: una sola lista de servicios y una sola pregunta por systemd ──────


def test_la_lista_de_servicios_es_la_que_instala_unidades_sh_y_tiene_sus_plantillas():
    """Estaba en tres sitios y ya había divergido una vez: desinstalar dejaba
    atrás los dos relés. Ahora salud la lee de `lib/unidades.sh`."""
    import re
    texto = (config.RAIZ_REPO / "scripts" / "lib" / "unidades.sh").read_text(encoding="utf-8")
    instalados = re.search(r'^SERVICIOS_HUB="([^"]*)"', texto, re.M).group(1).split()
    assert list(salud.SERVICIOS) == instalados
    plantillas = {p.name.removesuffix(".service.plantilla")
                  for p in (config.RAIZ_REPO / "scripts").glob("*.service.plantilla")}
    assert set(salud.SERVICIOS) == plantillas
    desinstalar = (config.RAIZ_REPO / "scripts" / "desinstalar.sh").read_text(encoding="utf-8")
    assert "hub-web hub-snapshotter" not in desinstalar and "$SERVICIOS_HUB" in desinstalar


def test_sin_systemd_de_usuario_lo_dice_en_vez_de_dar_los_servicios_por_parados(tmp_path, monkeypatch):
    """`systemctl` instalado pero sin sesión de usuario (un contenedor, WSL sin
    systemd): `show-environment` falla, y salud lo tomaba por «hay systemd» y
    pintaba web y muestreo como parados. La misma pregunta que actualizar."""
    from hub import actualizacion
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for nombre in ("systemctl", "systemd-run"):
        (bin_ / nombre).write_text("#!/bin/sh\necho 'Failed to connect to bus' >&2\nexit 1\n")
        (bin_ / nombre).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    assert salud.hay_systemd_de_usuario() is False
    assert actualizacion._con_systemd() is False
    (servicios,) = salud._servicios()
    assert servicios["clave"] == "servicios" and "No hay systemd de usuario" in servicios["detalle"]


# ── C-0214: volver sola tras un apagón, con el hub en una máquina aparte ─────

def _medidas(**valores):
    return {f"desatendido.{k}": {"valor": v[0], "texto": v[1]} for k, v in valores.items()}


MAL = _medidas(serve=(0, ""), tailscale=(0, ""), tarea=(0, ""), suspender=(1200, ""))


def _con_nombre_remoto():
    ruta = acceso.archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump({"hosts": ["maquina.red.ts.net"]}), encoding="utf-8")


def test_sin_entrar_desde_fuera_no_se_juzga_lo_de_volver_sola():
    """Quien usa el hub delante de la máquina inicia sesión él."""
    assert salud._desatendido(MAL) == []


def test_con_entrada_remota_cada_pieza_que_falta_dice_su_arreglo():
    _con_nombre_remoto()
    revisiones = {r["clave"]: r for r in salud._desatendido(MAL)}

    assert revisiones["desatendido:serve"]["estado"] == "mal"
    assert f"serve --bg {config.WEB_PORT}" in revisiones["desatendido:serve"]["arreglo"]
    assert "--unattended=true" in revisiones["desatendido:tailscale"]["arreglo"]
    assert "arrancar-sin-sesion.ps1" in revisiones["desatendido:tarea"]["arreglo"]
    assert "20 min" in revisiones["desatendido:suspender"]["detalle"]
    assert "standby-timeout-ac 0" in revisiones["desatendido:suspender"]["arreglo"]


def test_lo_que_no_se_pudo_medir_no_sale_como_bien():
    """Regla dura 13: sin medida no hay fila, ni «ok» por defecto."""
    _con_nombre_remoto()
    assert salud._desatendido({}) == []
    bien = salud._desatendido(_medidas(tarea=(1, "Levantar WSL"), suspender=(0, "")))
    assert [r["estado"] for r in bien] == ["ok", "ok"]
    assert "«Levantar WSL»" in bien[0]["detalle"]


def test_lo_medido_por_el_ciclo_lento_llega_a_la_salud_de_maquina(con):
    _con_nombre_remoto()
    con.execute("INSERT INTO maquina (clave, valor, texto, unidad, medido_en) "
                "VALUES ('desatendido.tailscale', 0, '', '', '2026-11-09T10:00:00')")
    claves = {r["clave"] for r in api.salud(con)}
    assert "desatendido:tailscale" in claves


def test_lo_que_dejo_de_poderse_medir_no_sale_como_bien_y_se_dice():
    """Con Tailscale parado, `maquina` conserva su último «bien»: enseñarlo
    como de ahora sería mentir justo cuando no se puede entrar (revisor)."""
    _con_nombre_remoto()
    medidas = {
        "disco.wsl.libre": {"valor": 50, "texto": "", "medido_en": "2026-11-09T12:10:00"},
        "ups.estado": {"valor": 2, "texto": "", "medido_en": "2026-11-09T12:19:00"},
        "desatendido.serve": {"valor": 1, "texto": "m.ts.net", "medido_en": "2026-11-09T11:00:00"},
        "desatendido.tarea": {"valor": 1, "texto": "T", "medido_en": "2026-11-09T12:10:00"},
    }
    revisiones = {r["clave"]: r for r in salud._desatendido(medidas)}

    assert "desatendido:serve" not in revisiones
    assert revisiones["desatendido:sin-medir"]["estado"] == "aviso"
    assert revisiones["desatendido:tarea"]["estado"] == "ok"   # el SAI no marca la vuelta


# ── C-0235: encender el secretario con un botón (decisión 400) ───────────────

# Los de verdad: `conftest` los sustituye en cada prueba para que la suite no
# accione nunca los servicios de quien la corre.
_ORDEN_REAL = salud._orden
_ESTADO_REAL = salud.estado_servicio

_SYSTEMCTL = """#!/bin/sh
PATH=/usr/bin:/bin
d="$SYSTEMCTL_FALSO"
echo "$*" >> "$d/ordenes"
case "$2" in
  show-environment) [ -e "$d/sin-systemd" ] && exit 1; exit 0 ;;
  is-active) cat "$d/activo" 2>/dev/null || echo inactive ;;
  is-enabled) if [ -e "$d/habilitado" ]; then echo enabled; else echo disabled; fi ;;
  enable)
    if [ -e "$d/no-enciende" ]; then cat "$d/no-enciende" >&2; exit 1; fi
    touch "$d/habilitado"
    cat "$d/al-encender" > "$d/activo"
    if [ -e "$d/late" ]; then "$PYTHON_FALSO" "$d/latir.py" "$d/memoria"; fi ;;
esac
"""

# Lo que hace el servicio al arrancar (`servicio.una_vuelta`): su latido, en su base.
_LATIR = """import datetime, json, sqlite3, sys
c = sqlite3.connect(open(sys.argv[1]).read())
c.execute("INSERT INTO estado (clave, valor) VALUES ('latido', ?) ON CONFLICT(clave) DO UPDATE SET"
          " valor = excluded.valor",
          (json.dumps(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")),))
c.commit()
"""


@pytest.fixture
def systemd(tmp_path, monkeypatch):
    """Un systemd de usuario de mentira, con un `systemctl` de verdad en el
    PATH: `salud` lo ejecuta como ejecutaría el bueno. `al-encender` es cómo
    queda la unidad tras `enable --now`, y `late`, si el servicio llega a dar
    su latido."""
    import sys
    from hub.secretario import memoria
    d = tmp_path / "systemd"
    (d / "bin").mkdir(parents=True)
    (d / "bin" / "systemctl").write_text(_SYSTEMCTL)
    (d / "bin" / "systemctl").chmod(0o755)
    (d / "latir.py").write_text(_LATIR)
    (d / "al-encender").write_text("active\n")
    con = memoria.conectar()
    con.close()
    (d / "memoria").write_text(str(memoria.ruta()))
    # 🔴 Sólo el de mentira en el PATH: si no se pudiera ejecutar (un `/tmp`
    # con `noexec`), el siguiente sería el de verdad y la prueba encendería el
    # secretario de quien corre la suite (revisor). Y se comprueba antes de
    # devolver la orden real.
    monkeypatch.setenv("PATH", str(d / "bin"))
    monkeypatch.setenv("SYSTEMCTL_FALSO", str(d))
    monkeypatch.setenv("PYTHON_FALSO", sys.executable)
    import shutil
    if shutil.which("systemctl") != str(d / "bin" / "systemctl"):
        pytest.skip("el systemctl de mentira no se puede ejecutar aquí")
    monkeypatch.setattr(salud, "_orden", _ORDEN_REAL)
    monkeypatch.setattr(salud, "estado_servicio", _ESTADO_REAL)
    return d


def _ordenes(d) -> list[str]:
    archivo = d / "ordenes"
    return archivo.read_text().splitlines() if archivo.exists() else []


def test_encender_lo_habilita_y_lo_da_por_bueno_al_ver_su_latido(systemd):
    (systemd / "late").touch()
    estado, texto = salud.encender("hub-secretario", espera=5)
    assert estado == "encendido" and "en marcha" in texto and "reinicies" in texto
    assert "--user enable --now hub-secretario" in _ordenes(systemd)
    assert salud.estado_servicio("hub-secretario") == {"activo": "active", "habilitado": True}


def test_un_latido_de_antes_del_clic_no_cuenta_como_encendido(systemd):
    """Arrancado no es funcionar (151): la base guarda el último latido de
    cuando estuvo encendido, y ése no dice nada de ahora."""
    from hub.secretario import memoria
    con = memoria.conectar()
    memoria.poner(con, "latido", "2026-11-01T10:00:00+00:00")
    con.close()
    estado, texto = salud.encender("hub-secretario", espera=0)
    assert estado == "sin-senal"
    assert "aún no da señales" in texto and "systemctl --user status hub-secretario" in texto


def test_si_se_cae_al_arrancar_lo_dice_con_su_registro(systemd):
    """Con `Restart=always`, uno que revienta pasa la espera entre intentos en
    `activating`: «encendido» sería mentira y «arrancando», también."""
    (systemd / "al-encender").write_text("activating\n")
    estado, texto = salud.encender("hub-secretario", espera=0)
    assert estado == "no" and "se cae al arrancar" in texto
    assert "journalctl --user -u hub-secretario -n 40" in texto


def test_si_systemd_no_lo_enciende_dice_por_que(systemd):
    (systemd / "no-enciende").write_text("Failed to enable unit: Unit file hub-secretario.service does not exist.\n")
    estado, texto = salud.encender("hub-secretario", espera=0)
    assert estado == "no" and "does not exist." in texto and ".." not in texto


def test_sin_systemd_no_lanza_nada_y_dice_el_comando(systemd):
    """Lanzado desde `hub-web` colgaría de su cgroup y nadie lo levantaría al
    caerse (153, 344): sin systemd, sólo el comando."""
    (systemd / "sin-systemd").touch()
    estado, texto = salud.encender("hub-secretario", espera=0)
    assert estado == "no" and "uv run python -m hub.secretario" in texto
    assert not any(o.startswith("--user enable") for o in _ordenes(systemd))
    assert salud.estado_servicio("hub-secretario") is None


@pytest.mark.parametrize("nombre", ["hub-canal", "hub-web", "hub-secretario; reboot"])
def test_solo_enciende_los_de_su_lista(systemd, nombre):
    """Canal y encargos sin su token sólo apuntarían fallos, y los demás ya
    corren siempre: la lista es cerrada y el nombre no viene de la petición."""
    with pytest.raises(ValueError):
        salud.encender(nombre, espera=0)
    assert _ordenes(systemd) == []


def test_la_suite_no_acciona_systemd_por_omision():
    """El seguro de `conftest`: aunque una ruta llegue a `salud.encender`, la
    orden no sale de la suite."""
    assert salud._orden("enable", "--now", "hub-secretario")[0] != 0
