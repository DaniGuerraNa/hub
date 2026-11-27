"""La salud del equipo que se queda solo.

Lo que se protege aquí no son las cifras —esas salen del driver y del sistema—
sino **la forma de fallar**: que una medida que no se pudo tomar no pise la
anterior, y que una fuente rota no se lleve por delante a las demás. Las dos
cosas importan porque el mes que esto vale es el mes en que nadie las mira.
"""

from __future__ import annotations

import json

import pytest

from hub import maquina


@pytest.fixture
def sin_windows(monkeypatch):
    """Una máquina sin GPU y sin Windows: Linux pelado, como un CI."""
    for fuente in ("_gpu", "_windows", "_ups", "_tailscale", "_arranque", "_encendido"):
        monkeypatch.setattr(maquina, fuente, lambda: (_ for _ in ()).throw(FileNotFoundError()))


def test_sin_gpu_se_siguen_midiendo_los_discos(sin_windows):
    """🔴 Regla dura 14 dentro de la medición: que no haya GPU no puede dejar
    sin medir el disco, que es lo que de verdad se llena."""
    claves = {m.clave for m in maquina.medir()}

    assert "disco.wsl.libre" in claves
    assert "memoria.libre" in claves
    assert not any(c.startswith("gpu") for c in claves)


def test_si_no_se_puede_medir_nada_se_dice_y_no_se_devuelve_una_lista_vacia(monkeypatch):
    """Una lista vacía se escribiría como «cero de todo». El silencio se levanta."""
    for fuente in ("_gpu", "_discos", "_memoria_y_carga", "_windows", "_ups", "_tailscale",
                   "_arranque", "_encendido"):
        monkeypatch.setattr(maquina, fuente, lambda: (_ for _ in ()).throw(OSError("no")))

    with pytest.raises(maquina.MaquinaNoMedida):
        maquina.medir()


def test_una_medida_que_no_se_pudo_tomar_conserva_la_anterior(con, monkeypatch):
    """🔴 El modo de fallo caro: un cero que significa «no he mirado».

    Escribiría 0 GB libres en la pantalla y, peor, dispararía una alarma a un
    teléfono que está a 2 000 km.
    """
    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("gpu.temperatura", 62, unidad="°C")])
    maquina.escanear(con)

    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("carga", 0.5)])
    maquina.escanear(con)

    guardadas = maquina.ultimas(con)
    assert guardadas["gpu.temperatura"]["valor"] == 62
    assert guardadas["carga"]["valor"] == 0.5


def test_cada_magnitud_guarda_solo_su_ultima_lectura(con, monkeypatch):
    """No es un histórico: volver a medir lo reconstruye (regla dura 1)."""
    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("gpu.temperatura", 40)])
    maquina.escanear(con)
    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("gpu.temperatura", 75)])
    maquina.escanear(con)

    filas = con.execute("SELECT valor FROM maquina WHERE clave='gpu.temperatura'").fetchall()
    assert [f["valor"] for f in filas] == [75]


def test_el_texto_y_el_numero_conviven_en_la_misma_tabla(con, monkeypatch):
    """La pantalla y las alarmas leen de una sola costura, no de dos."""
    monkeypatch.setattr(maquina, "medir", lambda: [
        maquina.Medida("gpu.nombre", texto="NVIDIA GeForce RTX 4070 Ti"),
        maquina.Medida("gpu.temperatura", 61, unidad="°C"),
    ])
    maquina.escanear(con)

    assert maquina.valor(con, "gpu.temperatura") == 61
    assert maquina.valor(con, "gpu.nombre") is None
    assert maquina.ultimas(con)["gpu.nombre"]["texto"].startswith("NVIDIA")


def test_los_programas_de_windows_se_resuelven_aunque_el_PATH_no_los_traiga(monkeypatch):
    """🔴 La decisión 81 otra vez, en otro sitio.

    `hub-snapshotter` corre bajo systemd, cuyo PATH no trae los caminos de
    interoperabilidad de Windows. Se vio en la primera medición dentro del
    servicio: discos y memoria al día, y la GPU, el SAI y Windows congelados
    diez minutos atrás **sin un solo error a la vista**. Probar a mano no lo
    detecta, porque una shell interactiva sí los encuentra.
    """
    monkeypatch.setattr(maquina.shutil, "which", lambda nombre: None)

    assert maquina._programa("powershell.exe").startswith("/mnt/c/")
    assert maquina._programa("nvidia-smi.exe").startswith("/mnt/c/")
    assert maquina._programa("df") == "df"       # lo que no es de Windows, tal cual


def test_una_fuente_que_falla_lo_dice_en_voz_alta(monkeypatch, capsys):
    """Callarlo es lo que dejó al servicio midiendo la mitad (regla dura 21)."""
    def explota():
        raise FileNotFoundError("nvidia-smi.exe")

    explota.__name__ = "_gpu"
    monkeypatch.setattr(maquina, "_gpu", explota)

    maquina.medir()

    salida = capsys.readouterr().out
    assert "_gpu no midió" in salida and "nvidia-smi.exe" in salida


def test_sin_windows_debajo_se_dice_una_vez_y_no_cada_minuto(monkeypatch, capsys):
    """Instalando en limpio en un Linux sin Windows, el SAI escribía «no existe
    powershell.exe» en el registro cada minuto. No es un fallo: no aplica."""
    monkeypatch.setattr(maquina.shutil, "which", lambda nombre: None)
    monkeypatch.setattr(maquina, "RESPALDOS", {"powershell.exe": "/no/existe/powershell.exe"})
    monkeypatch.setattr(maquina, "_FALTAS_DICHAS", set())
    monkeypatch.setattr(maquina.subprocess, "run",
                        lambda *a, **k: pytest.fail("no debía intentar ejecutarlo"))

    for _ in range(3):
        assert maquina.escanear_ups(None) == 0

    assert capsys.readouterr().out.count("no hay powershell.exe") == 1


# ── Volver sola tras un apagón (C-0214) ─────────────────────────────────────

# Lo que devolvía `tailscale.exe serve status --json` en la PC del dueño el
# 9-nov, con el nombre de la máquina cambiado.
SERVE_MEDIDO = {
    "TCP": {"443": {"HTTPS": True}},
    "Web": {"maquina.red.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}}},
}


def test_serve_publica_el_hub_si_algun_sitio_lleva_a_su_puerto():
    assert maquina.sitio_del_hub(SERVE_MEDIDO) == "maquina.red.ts.net"
    assert maquina.sitio_del_hub({}) == ""
    otro = {"Web": {"m.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}}}
    assert maquina.sitio_del_hub(otro) == ""


def test_un_serve_dejado_en_una_terminal_no_cuenta_porque_no_vuelve_tras_un_apagon():
    """`serve` sin `--bg` va a `Foreground` y muere con su terminal."""
    assert maquina.sitio_del_hub({"Foreground": {"sesion": SERVE_MEDIDO}}) == ""


def _salidas(monkeypatch, **por_subcomando):
    def falsa(comando):
        return por_subcomando[comando[1]]
    monkeypatch.setattr(maquina, "_salida", falsa)


def test_tailscale_de_windows_sin_unattended_se_mide_como_no(monkeypatch):
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: "/x/tailscale.exe")
    _salidas(monkeypatch, debug='{"ForceDaemon": false, "WantRunning": true}',
             serve=json.dumps(SERVE_MEDIDO))

    medidas = {m.clave: m for m in maquina._tailscale()}

    assert medidas["desatendido.tailscale"].valor == 0
    assert medidas["desatendido.serve"].valor == 1
    assert medidas["desatendido.serve"].texto == "maquina.red.ts.net"


def test_en_un_linux_sin_windows_solo_se_mira_serve(monkeypatch):
    """Ahí tailscaled es un servicio del sistema: no tiene la pega de la sesión."""
    monkeypatch.setattr(maquina, "encontrar",
                        lambda nombre: "/usr/bin/tailscale" if nombre == "tailscale" else None)
    _salidas(monkeypatch, serve="")

    medidas = {m.clave: m for m in maquina._tailscale()}

    assert set(medidas) == {"desatendido.serve"} and medidas["desatendido.serve"].valor == 0


def test_sin_tailscale_no_aplica_y_no_es_un_fallo(monkeypatch):
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: None)
    with pytest.raises(maquina.NoHay):
        maquina._tailscale()


def test_la_tarea_de_arranque_y_la_suspension_salen_de_un_solo_powershell(monkeypatch):
    llamadas = []

    def falsa(comando):
        llamadas.append(comando[0])
        return "suspender=1200\r\ntarea=Levantar WSL\r\n"

    monkeypatch.setattr(maquina, "_salida", falsa)
    medidas = {m.clave: m for m in maquina._arranque()}

    assert llamadas == ["powershell.exe"]
    assert medidas["desatendido.suspender"].valor == 1200
    assert (medidas["desatendido.tarea"].valor, medidas["desatendido.tarea"].texto) == (1, "Levantar WSL")


def test_sin_tarea_de_arranque_se_guarda_como_no_y_no_como_sin_medir(monkeypatch):
    """«No hay tarea» es una respuesta; que falte la clave es «no se pudo mirar»."""
    monkeypatch.setattr(maquina, "_salida", lambda comando: "suspender=0\ntarea=\n")
    medidas = {m.clave: m for m in maquina._arranque()}
    assert medidas["desatendido.tarea"].valor == 0 and medidas["desatendido.suspender"].valor == 0


@pytest.mark.parametrize("accion, script", [
    # La del dueño: el script entre comillas dobladas.
    (r'C:\Windows\System32\cmd.exe /c ""C:\Users\x\hub\mantener-wsl-arriba.cmd""',
     r"C:\Users\x\hub\mantener-wsl-arriba.cmd"),
    # La que deja «Examinar»: el programa con su ruta y el script sin comillas.
    (r"C:\Windows\System32\cmd.exe /c C:\Users\x\levantar.cmd", r"C:\Users\x\levantar.cmd"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -File C:\scripts\a.ps1",
     r"C:\scripts\a.ps1"),
])
def test_la_ruta_del_script_de_la_tarea_se_saca_entera_y_sola(accion, script):
    """La regex se prueba en PowerShell, que es donde corre (regla dura 11)."""
    import re
    import subprocess

    ps = maquina.encontrar("powershell.exe")
    if not ps:
        pytest.skip("sin Windows debajo")
    patron = re.search(r"Matches\(\$texto, '([^']+)'\)", maquina._PS_ARRANQUE).group(1)
    orden = (f"[regex]::Matches('{accion.replace(chr(39), chr(39) * 2)}', '{patron}') "
             "| ForEach-Object { $_.Value }")
    salida = subprocess.run([ps, "-NoProfile", "-Command", orden], capture_output=True,
                            text=True, timeout=30).stdout
    assert salida.replace("\r", "").split("\n")[:-1] == [script]


# ── Revisión de C-0309: el SAI lo mide sólo el latido ────────────────────────

def test_el_ciclo_lento_no_pisa_la_lectura_del_sai_que_hizo_el_latido(con, monkeypatch):
    """🔴 Con el ciclo lento en su hilo, `medir()` leía el SAI al principio y
    lo guardaba al final, segundos después, con la fecha del guardado: si en
    medio el latido había leído «sobre batería», la lectura vieja lo pisaba
    hasta un minuto, y los avisos de luz veían un «volvió» y un «se fue»
    que no pasaron (decisión 249)."""
    lecturas = iter([[maquina.Medida("ups.estado", maquina.CON_CORRIENTE, "con corriente")],
                     [maquina.Medida("ups.estado", maquina.SOBRE_BATERIA, "sobre batería")]])
    leido = []

    def ups():
        leido.append(1)
        return next(lecturas)

    for fuente in ("_gpu", "_windows", "_tailscale", "_arranque", "_encendido"):
        monkeypatch.setattr(maquina, fuente, lambda: [])
    monkeypatch.setattr(maquina, "_ups", ups)

    # El hilo lento empieza su medida (leería «con corriente»)…
    lentas = maquina.medir(sai=False)
    # …el latido lee el SAI entre medias, dos veces: la última, sobre batería…
    maquina.escanear_ups(con)
    maquina.escanear_ups(con)
    # …y el hilo lento guarda lo suyo al acabar.
    maquina._guardar(con, lentas)

    assert len(leido) == 2, "el ciclo lento no tiene que leer el SAI"
    assert not [m for m in lentas if m.clave.startswith("ups.")]
    assert maquina.ultimas(con)["ups.estado"]["texto"] == "sobre batería"


def test_escanear_sin_sai_mide_lo_demas_y_con_el_todo_como_siempre(con, monkeypatch):
    for fuente in ("_gpu", "_windows", "_tailscale", "_arranque", "_encendido"):
        monkeypatch.setattr(maquina, fuente, lambda: [])
    monkeypatch.setattr(maquina, "_ups", lambda: [maquina.Medida("ups.carga", 80.0, unidad="%")])

    assert maquina.escanear(con, sai=False) > 0
    assert "ups.carga" not in maquina.ultimas(con) and "memoria.libre" in maquina.ultimas(con)
    maquina.escanear(con)
    assert maquina.ultimas(con)["ups.carga"]["valor"] == 80.0


# ── C-0381: el último arranque, cruzado ──────────────────────────────────────

def _systemctl(monkeypatch, sistema="@1794005473", usuario="@1794005509"):
    """`systemctl show … --timestamp=unix`, grabado del arranque del 6-nov:
    Linux a las 22:51:13Z y los servicios del usuario a las 22:51:49Z."""
    pedidos = []

    def salida(comando):
        pedidos.append(comando)
        return usuario if "--user" in comando else sistema

    monkeypatch.setattr(maquina, "_hay_systemd", lambda: True)
    monkeypatch.setattr(maquina, "_salida", salida)
    return pedidos


def test_el_arranque_de_wsl_y_del_hub_salen_de_systemd_en_hora_de_pared(monkeypatch):
    """🔴 De `systemctl`, no de `/proc/stat`: medido el 13-nov, el `btime` de
    WSL salía cinco horas tarde porque no cuenta la VM en pausa (regla 19)."""
    pedidos = _systemctl(monkeypatch)
    medidas = {m.clave: m.texto for m in maquina._encendido()}
    assert medidas == {"encendido.wsl": "2026-11-06T22:51:13Z", "encendido.hub": "2026-11-06T22:51:49Z"}
    # El de los servicios del usuario, no el de `hub-web`: ése cambia en cada
    # reinicio del servicio y dejaría de ser el del arranque.
    assert all("hub-web" not in " ".join(c) for c in pedidos)
    assert all("--timestamp=unix" in c for c in pedidos)


@pytest.mark.parametrize("crudo", ["", "n/a", "@0", "Fri 2026-11-06 16:51:13 CST"])
def test_un_instante_vacio_o_raro_no_se_guarda(monkeypatch, crudo):
    _systemctl(monkeypatch, sistema=crudo, usuario=crudo)
    assert maquina._encendido() == []


def test_sin_systemd_no_se_mide_y_no_es_un_fallo(monkeypatch):
    monkeypatch.setattr(maquina, "_hay_systemd", lambda: False)
    monkeypatch.setattr(maquina, "_salida", lambda c: pytest.fail(f"lanzó {c}"))
    with pytest.raises(maquina.NoHay):
        maquina._encendido()


def test_el_encendido_va_en_la_medida_del_ciclo_lento(monkeypatch):
    for fuente in ("_gpu", "_windows", "_ups", "_tailscale", "_arranque"):
        monkeypatch.setattr(maquina, fuente, lambda: [])
    _systemctl(monkeypatch)
    assert {"encendido.wsl", "encendido.hub"} <= {m.clave for m in maquina.medir(sai=False)}


def _guardadas(con, medido_en="2026-11-07T00:00:00+00:00", **textos):
    for clave, texto in textos.items():
        con.execute("INSERT INTO maquina (clave, valor, texto, unidad, medido_en) VALUES (?,?,?,?,?)",
                    (clave.replace("_", "."), None, texto, "", medido_en))


def test_maquina_cruza_cuanto_tardaron_wsl_y_el_hub_tras_encender_windows(con):
    """Lo del 6-nov: Windows 22:50:24Z, WSL 49 s después, el hub a los 85 s."""
    from hub import api
    _guardadas(con, windows_arranque="2026-11-06T22:50:24Z", encendido_wsl="2026-11-06T22:51:13Z",
               encendido_hub="2026-11-06T22:51:49Z")
    a = api.maquina(con)["arranque"]
    assert (a["wsl_s"], a["hub_s"], a["wsl"], a["hub"]) == (49, 85, "49 s", "85 s")


def test_lo_de_vueltas_distintas_o_que_no_cuadra_no_se_cruza(con):
    """Regla dura 13: un arranque de Windows de otra vuelta (PowerShell falló
    en la última) o un WSL anterior a Windows darían una cifra falsa."""
    from hub import api
    _guardadas(con, medido_en="2026-11-01T00:00:00+00:00", windows_arranque="2026-11-01T08:00:00Z")
    _guardadas(con, encendido_wsl="2026-11-06T22:51:13Z", encendido_hub="2026-11-06T22:51:49Z")
    assert api.maquina(con)["arranque"] is None
    con.execute("DELETE FROM maquina")
    _guardadas(con, windows_arranque="2026-11-06T22:52:00Z", encendido_wsl="2026-11-06T22:51:13Z")
    assert api.maquina(con)["arranque"] is None


def test_sin_los_servicios_del_hub_se_cruza_solo_wsl_y_una_espera_larga_se_dice_en_horas(con):
    from hub import api
    _guardadas(con, windows_arranque="2026-11-06T22:50:24Z", encendido_wsl="2026-11-07T01:20:24Z")
    a = api.maquina(con)["arranque"]
    assert (a["wsl"], a["hub"]) == ("2 h 30 min", "")


def test_la_pantalla_dice_el_ultimo_arranque(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web
    ruta = tmp_path / "hub.db"

    def conexion():
        c = db.conectar(ruta)
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    c = conexion()
    _guardadas(c, windows_arranque="2026-11-06T22:50:24Z", encendido_wsl="2026-11-06T22:51:13Z",
               encendido_hub="2026-11-06T22:51:49Z")
    c.close()
    html = TestClient(web.app).get("/maquina").text
    assert "Tras el último arranque" in html
    assert "WSL a los <strong>49 s</strong>" in html and "el hub a los <strong>85 s</strong>" in html


def test_el_encendido_y_los_apagones_de_windows_salen_en_la_hora_de_la_casa(con, tmp_path, monkeypatch):
    """C-0396, tras la revisión: «Windows arrancó», «Último apagón» y «Último
    reinicio» pintaban el texto crudo (`2026-11-06T22:51:13Z`), en UTC y a seis
    horas de la «Última lectura» de al lado."""
    import re

    from fastapi.testclient import TestClient
    from hub import db, web
    monkeypatch.setenv("TZ", "America/Mexico_City")
    _guardadas(con, windows_arranque="2026-11-06T22:50:24Z", windows_apagon="2026-11-05T03:10:00Z",
               windows_reinicio="2026-11-04T12:00:00Z")
    con.commit()
    monkeypatch.setattr(web, "conexion", lambda: db.conectar(tmp_path / "hub.db"))

    html = TestClient(web.app).get("/maquina").text

    assert not re.search(r"\d{4}-\d\d-\d\dT", re.sub(r'datetime="[^"]*"', "", html))
    for local in ("06/11(/2026)? 16:50", "04/11(/2026)? 21:10", "04/11(/2026)? 06:00"):
        assert re.search(r"<time [^>]*>" + local + r" \(hace ", html), local


def test_sin_apagones_registrados_se_dice_y_no_sale_una_raya(con, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from hub import db, web
    _guardadas(con, windows_arranque="2026-11-06T22:50:24Z")
    con.commit()
    monkeypatch.setattr(web, "conexion", lambda: db.conectar(tmp_path / "hub.db"))

    assert "ninguno registrado" in TestClient(web.app).get("/maquina").text


# ── El nombre en la red privada, al pintar /acceso (C-0504) ─────────────────

def _tailscale_falso(tmp_path, monkeypatch, status, serve, dormir=0):
    """Un `tailscale` de verdad (un programa), que contesta lo que se le diga."""
    import sys
    programa = tmp_path / "tailscale"
    programa.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        f"time.sleep({dormir})\n"
        f"print(json.dumps({serve!r} if sys.argv[1] == 'serve' else {status!r}))\n")
    programa.chmod(0o755)
    monkeypatch.setattr(maquina, "_programa_tailscale", lambda: str(programa))


def test_la_red_privada_da_el_nombre_de_la_maquina_y_si_serve_lleva_al_hub(tmp_path, monkeypatch):
    estado = {"BackendState": "Running", "Self": {"DNSName": "Maquina.red.ts.net."}}
    _tailscale_falso(tmp_path, monkeypatch, estado, SERVE_MEDIDO)
    red = maquina.red_privada()
    assert red == {"hay": True, "conectado": True, "nombre": "maquina.red.ts.net",
                   "lleva_al_hub": True, "puerto": 443, "error": ""}


def test_sin_serve_hacia_el_hub_se_sabe_el_nombre_igual(tmp_path, monkeypatch):
    estado = {"BackendState": "Running", "Self": {"DNSName": "maquina.red.ts.net."}}
    _tailscale_falso(tmp_path, monkeypatch, estado, {})
    red = maquina.red_privada()
    assert red["nombre"] == "maquina.red.ts.net" and red["lleva_al_hub"] is False


def test_un_tailscale_que_no_contesta_a_tiempo_no_es_un_no(tmp_path, monkeypatch):
    """Lo que no se pudo medir no se pinta ni hecho ni por hacer (regla 13)."""
    _tailscale_falso(tmp_path, monkeypatch, {}, {}, dormir=5)
    red = maquina.red_privada(tope=0.5)
    assert red["hay"] is True and red["lleva_al_hub"] is None and red["error"]


def test_sin_tailscale_se_dice_y_no_lanza(monkeypatch):
    monkeypatch.setattr(maquina, "_programa_tailscale", lambda: None)
    red = maquina.red_privada()
    assert red["hay"] is False and red["error"]


def test_el_tope_de_la_red_privada_es_para_las_dos_preguntas_juntas(tmp_path, monkeypatch):
    """Son dos llamadas (`status` y `serve status`): con un tope por llamada,
    /acceso esperaba el doble de lo dicho."""
    import time
    _tailscale_falso(tmp_path, monkeypatch, {"BackendState": "Running"}, {}, dormir=0.6)
    inicio = time.monotonic()
    red = maquina.red_privada(tope=1.0)
    assert time.monotonic() - inicio < 1.5
    assert red["lleva_al_hub"] is None and red["error"]
