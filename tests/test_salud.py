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


# ── C-0309: el ciclo lento va en su hilo y su estado viaja en el latido ──────
#
# Sacarlo del latido tiene un precio: si se cuelga en un `stat` sobre el disco
# de Windows, el latido sigue tan tranquilo y el respaldo, el consumo y la
# salud del equipo se quedan con cifras viejas sin que nada lo diga. Por eso
# Salud lo juzga. Sólo en pantalla: no es una clase de `avisos.CLASES`.

def _latido_con_lento(visto_desde=AHORA, **lento):
    """Un latido reciente con el estado del ciclo lento; las fechas se dan en
    segundos hacia atrás desde `visto_desde`."""
    def hace(segundos):
        return (visto_desde - timedelta(seconds=segundos)).isoformat(timespec="seconds")

    estado = {"desde": hace(7200), "corriendo": False, "dentro": False, "empezo": None,
              "acabo": None, "duro": None, "paso": None, "paso_desde": None, "pasos": {},
              "fallo": None, "fallaron": {}}
    for clave, valor in lento.items():
        estado[clave] = hace(valor) if clave in ("desde", "empezo", "acabo", "paso_desde") else valor
    (config.HUB_HOME / salud.ARCHIVO_LATIDO).write_text(json.dumps(
        {"en": hace(5), "pid": 1, "lento": estado}))


def test_las_mediciones_lentas_estan_bien_si_la_ultima_vuelta_acabo_hace_poco():
    _latido_con_lento(acabo=240, duro=52.0)
    fila = salud.mediciones_lentas(AHORA)
    assert fila["clave"] == "lento" and fila["estado"] == "ok"
    assert "hace 4 min" in fila["detalle"] and "52 s" in fila["detalle"]
    assert not fila.get("arreglo")


def test_mas_de_media_hora_sin_acabar_una_vuelta_es_un_aviso_con_su_arreglo():
    _latido_con_lento(acabo=35 * 60, duro=52.0, corriendo=True, empezo=33 * 60)
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso" and "35 min" in fila["detalle"]
    assert "systemctl --user restart hub-snapshotter" in fila["arreglo"]
    assert "las cifras del respaldo" in fila["detalle"]


def test_al_despertar_de_una_suspension_no_manda_reiniciar_lo_que_se_arregla_solo():
    """El equipo estuvo ocho horas suspendido: el latido es de ahora y la
    última vuelta lenta, de anoche. No hay ninguna en marcha y ninguna falló:
    la siguiente se pide sola en menos de diez minutos, y «reinicia el
    muestreo» era un consejo que no hacía falta seguir."""
    _latido_con_lento(acabo=8 * 3600, duro=52.0)
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso" and "8 h" in fila["detalle"]
    assert "próxima vuelta" in fila["detalle"]
    assert not fila.get("arreglo") and "restart" not in fila["detalle"]

    # Y si nunca acabó ninguna, no dice que «acabó»: dice desde cuándo espera.
    _latido_con_lento(desde=45 * 60)
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso" and "arrancó hace 45 min" in fila["detalle"]
    assert "acabó hace" not in fila["detalle"] and not fila.get("arreglo")


def test_si_en_la_ultima_vuelta_fallaron_pasos_la_fila_dice_cuales_y_no_sale_bien():
    _latido_con_lento(acabo=120, duro=3.0,
                      fallaron={"repos": "OSError: [Errno 5] Input/output error",
                                "consumo": "OSError: [Errno 5] Input/output error",
                                "uno-nuevo": "ValueError: x"})
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso", "aviso, nunca «mal»: el muestreo de ventanas no depende de esto"
    assert "el respaldo de los repos, el consumo y «uno-nuevo»" in fila["detalle"]
    assert "journalctl --user -u hub-snapshotter" in fila["arreglo"]
    assert "restart" not in fila["arreglo"]

    _latido_con_lento(acabo=120, duro=3.0, fallaron="basura")
    assert salud.mediciones_lentas(AHORA)["estado"] == "ok"


def test_si_nunca_acabo_una_vuelta_se_cuenta_desde_que_arranco():
    _latido_con_lento(desde=600)
    assert salud.mediciones_lentas(AHORA)["estado"] == "ok"
    _latido_con_lento(desde=45 * 60, fallo="OperationalError: disk I/O error")
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso" and "45 min" in fila["detalle"]
    assert "disk I/O error" in fila["detalle"], "si la última falló, se dice con qué"


def test_mas_de_diez_minutos_en_un_paso_es_un_aviso_que_dice_cual():
    """El hilo colgado en un `stat` sobre 9p: sin esto sería un silencio."""
    _latido_con_lento(acabo=14 * 60, duro=52.0, corriendo=True, empezo=11 * 60 + 5,
                      paso="repos", paso_desde=11 * 60)
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso"
    assert "11 min" in fila["detalle"] and "respaldo de los repos" in fila["detalle"]
    assert "restart hub-snapshotter" in fila["arreglo"]

    _latido_con_lento(acabo=11 * 60, duro=52.0, corriendo=True, empezo=65,
                      paso="repos", paso_desde=60)
    assert salud.mediciones_lentas(AHORA)["estado"] == "ok"


def test_un_paso_que_salud_no_conoce_sale_con_su_clave():
    _latido_con_lento(acabo=60, corriendo=True, empezo=700, paso="uno-nuevo", paso_desde=700)
    assert "«uno-nuevo»" in salud.mediciones_lentas(AHORA)["detalle"]


def test_si_se_mide_dentro_del_latido_porque_el_hilo_no_arranca_se_dice():
    _latido_con_lento(acabo=120, duro=52.0, dentro=True)
    fila = salud.mediciones_lentas(AHORA)
    assert fila["estado"] == "aviso" and "dentro del muestreo" in fila["detalle"]


def test_sin_estado_del_ciclo_lento_no_hay_fila_ni_un_bien_por_omision():
    """Regla dura 13: un snapshotter de antes de esto, o uno parado, no ha
    dicho nada del ciclo lento; lo que no se sabe no sale."""
    assert salud.mediciones_lentas(AHORA) is None           # sin latido
    _latido(15)
    assert salud.mediciones_lentas(AHORA) is None           # latido sin `lento`
    _latido_con_lento(acabo=60, duro=52.0)
    (config.HUB_HOME / salud.ARCHIVO_LATIDO).write_text(json.dumps(
        {"en": (AHORA - timedelta(hours=2)).isoformat(), "pid": 1,
         "lento": {"acabo": (AHORA - timedelta(hours=2)).isoformat()}}))
    assert salud.mediciones_lentas(AHORA) is None           # parado: lo dice «Muestreo»


def test_un_estado_a_medias_o_con_basura_no_tumba_la_pantalla():
    (config.HUB_HOME / salud.ARCHIVO_LATIDO).write_text(json.dumps(
        {"en": (AHORA - timedelta(seconds=5)).isoformat(), "pid": 1,
         "lento": {"acabo": "ayer por la tarde", "paso": 7, "duro": "mucho"}}))
    assert salud.mediciones_lentas(AHORA) is None
    (config.HUB_HOME / salud.ARCHIVO_LATIDO).write_text(json.dumps(
        {"en": (AHORA - timedelta(seconds=5)).isoformat(), "pid": 1, "lento": "sí"}))
    assert salud.mediciones_lentas(AHORA) is None


def test_latir_escribe_el_estado_del_ciclo_lento_y_sin_el_el_latido_de_siempre():
    salud.latir()
    assert "lento" not in json.loads((config.HUB_HOME / salud.ARCHIVO_LATIDO).read_text())
    salud.latir(lento={"corriendo": True, "pasos": {"repos": 1.5}})
    assert json.loads((config.HUB_HOME / salud.ARCHIVO_LATIDO).read_text())["lento"]["pasos"] == {"repos": 1.5}


def test_un_estado_que_no_se_puede_escribir_no_deja_al_hub_sin_latido(capsys):
    """El latido dice «estoy vivo» (decisión 289): no se pierde por un dato
    de más que no cabe en JSON."""
    salud.latir(lento={"corriendo": object()})
    assert salud.muestreo()["estado"] == "ok"
    assert "lento" not in json.loads((config.HUB_HOME / salud.ARCHIVO_LATIDO).read_text())
    assert "ciclo lento" in capsys.readouterr().out


def test_la_fila_de_las_mediciones_lentas_sale_en_salud_y_no_es_un_aviso_al_telefono(cliente):  # noqa: F811
    from hub import avisos
    _latido_con_lento(datetime.now(timezone.utc), acabo=35 * 60, duro=52.0, fallo="OSError: roto")
    fila = next(r for r in cliente.get("/api/salud").json()["revisiones"] if r["clave"] == "lento")
    assert fila["estado"] == "aviso"
    assert "Mediciones lentas" in cliente.get("/maquina").text
    assert not [c for c in avisos.CLASES if "lento" in c], "sólo en pantalla (regla dura 3)"


# ── C-0378: lo que falla, arriba; lo que está bien, plegado y con su glifo ───


def _revisiones(*estados):
    return [{"clave": f"c{i}", "nombre": f"Comprobación {i}", "estado": e,
             "detalle": f"detalle {i}", **({"arreglo": f"arreglo {i}"} if e != "ok" else {})}
            for i, e in enumerate(estados)]


def _pliegue(html: str) -> tuple[str, str]:
    """Lo que hay en la tarjeta de salud antes del pliegue y lo de dentro."""
    tarjeta = html.split('id="salud"', 1)[1].split("</div>\n<style>", 1)[0]
    antes, _, dentro = tarjeta.partition('<details class="salud-pie"')
    return antes, dentro


def test_lo_que_no_esta_bien_sale_fuera_del_pliegue_y_lo_que_si_dentro(cliente, monkeypatch):  # noqa: F811
    """Diez «bien» seguidos empujaban debajo justo lo que fallaba (UI-43)."""
    monkeypatch.setattr(salud, "revisar", lambda slots, medidas=None: _revisiones("mal", *["ok"] * 9))
    antes, dentro = _pliegue(cliente.get("/maquina").text)
    assert "Comprobación 0" in antes and "arreglo 0" in antes
    assert "Comprobación 1" not in antes
    assert "Lo demás en pie · 9 comprobaciones" in dentro
    assert all(f"Comprobación {i}" in dentro for i in range(1, 10))


def test_con_todo_bien_queda_una_sola_linea_plegada(cliente, monkeypatch):  # noqa: F811
    monkeypatch.setattr(salud, "revisar", lambda slots, medidas=None: _revisiones(*["ok"] * 10))
    antes, dentro = _pliegue(cliente.get("/maquina").text)
    assert "Comprobación" not in antes
    assert "Todo en pie · 10 comprobaciones" in dentro and "<details" not in dentro.split("</summary>")[0][1:]


def test_cada_estado_de_salud_lleva_glifo_color_y_palabra(cliente, monkeypatch):  # noqa: F811
    """`base.html` pide los tres: «bien» iba sólo con color y palabra."""
    from hub import insignias
    monkeypatch.setattr(salud, "revisar", lambda slots, medidas=None: _revisiones("mal", "aviso", "ok"))
    html = cliente.get("/maquina").text
    for estado in ("mal", "aviso", "ok"):
        i = insignias.de("salud", estado)
        assert i is not None, f"«{estado}» saldría sin glifo"
        assert f'<span class="insignia {i.tono}" title="{i.porque}">' in html
        assert f'<span class="glifo" aria-hidden="true">{i.glifo}</span><span>{i.texto}</span>' in html


# ── C-0448: esperar la señal de un servicio, suelta ──────────────────────────
#
# Estaba dentro de `encender`, después de un `enable --now`. `actualizar.sh`
# necesita lo mismo tras reiniciar: que el servicio dé señales de vida
# posteriores al reinicio, no que `systemctl` devolviera 0 (decisión 151).

class _RelojFalso:
    """El `time` de `salud`: cada `sleep` avanza el reloj sin esperar."""

    def __init__(self):
        self.t = 1000.0
        self.dormido = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, segundos):
        self.t += segundos
        self.dormido += segundos


DESDE = "2026-11-13T10:00:00+00:00"


@pytest.fixture
def reloj_falso(monkeypatch):
    r = _RelojFalso()
    monkeypatch.setattr(salud, "time", r)
    return r


def _senal(monkeypatch, nombre, valores):
    """La señal de `nombre` devuelve `valores` uno tras otro y se queda en el último."""
    pendientes = list(valores)
    monkeypatch.setitem(salud.SENALES, nombre,
                        lambda: pendientes.pop(0) if len(pendientes) > 1 else pendientes[0])


def _activo(monkeypatch, como):
    monkeypatch.setattr(salud, "_systemctl", lambda *a: como if a[0] == "is-active" else "")


def test_una_senal_posterior_al_reinicio_es_ok_sin_agotar_la_espera(monkeypatch, reloj_falso):
    _senal(monkeypatch, "hub-snapshotter",
           [None, "2026-11-13T09:59:40+00:00", "2026-11-13T10:00:03+00:00"])
    _activo(monkeypatch, "active")
    assert salud.esperar_senal("hub-snapshotter", DESDE, espera=60) == "ok"
    assert reloj_falso.dormido == 2


def test_un_latido_de_antes_del_reinicio_no_cuenta_y_en_marcha_es_sin_senal(monkeypatch, reloj_falso):
    """El de antes lo dio el proceso viejo: no dice nada del nuevo."""
    _senal(monkeypatch, "hub-snapshotter", ["2026-11-13T09:59:59+00:00"])
    _activo(monkeypatch, "active")
    assert salud.esperar_senal("hub-snapshotter", DESDE, espera=60) == "sin-senal"
    assert reloj_falso.dormido >= 60


def test_sin_senal_y_sin_quedar_en_marcha_es_caido(monkeypatch, reloj_falso):
    """Con `Restart=always`, uno que revienta al arrancar pasa la espera entre
    intentos en `activating`: no está en marcha."""
    _senal(monkeypatch, "hub-secretario", [None])
    _activo(monkeypatch, "activating")
    assert salud.esperar_senal("hub-secretario", DESDE, espera=5) == "caido"


def test_una_senal_ilegible_no_cuenta_ni_revienta(monkeypatch, reloj_falso):
    _senal(monkeypatch, "hub-snapshotter", ["no es una fecha"])
    _activo(monkeypatch, "active")
    assert salud.esperar_senal("hub-snapshotter", DESDE, espera=3) == "sin-senal"


@pytest.mark.parametrize("como, esperado", [("active", "sin-medir"), ("failed", "caido")])
def test_lo_que_no_tiene_senal_propia_solo_se_mira_si_sigue_en_marcha(monkeypatch, reloj_falso,
                                                                      como, esperado):
    """Canal y encargos no laten: se dice «sin medir» y no se espera por nada."""
    _activo(monkeypatch, como)
    assert "hub-canal" not in salud.SENALES
    assert salud.esperar_senal("hub-canal", DESDE, espera=60) == esperado
    assert reloj_falso.dormido == 0


def test_la_senal_del_muestreo_es_su_latido(monkeypatch):
    _activo(monkeypatch, "active")
    salud.latir()
    assert salud.esperar_senal("hub-snapshotter", "2026-01-01T00:00:00+00:00", espera=0) == "ok"
    assert salud.esperar_senal("hub-snapshotter", "2999-01-01T00:00:00+00:00", espera=0) == "sin-senal"


def test_cada_servicio_que_se_enciende_tiene_su_senal():
    """`encender` da por encendido al ver la señal: uno sin ella saldría siempre «sin medir»."""
    assert set(salud.ENCENDIBLES) <= set(salud.SENALES)
    assert set(salud.SENALES) <= set(salud.SERVICIOS)


def test_la_orden_senal_dice_como_quedo_y_rechaza_nombres_y_fechas_raros(monkeypatch, capsys):
    """Lo que corre `actualizar.sh`: una palabra por salida, y el nombre del
    servicio tiene que ser uno del hub."""
    _activo(monkeypatch, "active")
    assert salud.main(["senal", "hub-canal", "--desde", DESDE, "--espera", "0"]) == 0
    assert capsys.readouterr().out.strip() == "sin-medir"
    for argumentos in (["senal", "hub-canal; reboot", "--desde", DESDE],
                       ["senal", "hub-canal", "--desde", "ayer"]):
        with pytest.raises(SystemExit) as salida:
            salud.main(argumentos)
        assert salida.value.code == 2
