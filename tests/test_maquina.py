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
    for fuente in ("_gpu", "_windows", "_ups", "_tailscale", "_arranque"):
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
                   "_arranque"):
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
