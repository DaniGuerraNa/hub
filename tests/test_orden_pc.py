"""Una orden de PowerShell en el Windows del dueño (C-0240, decisión 404).

Lo que decide si una orden sólo mira es `veredicto`, sobre lo que devuelve el
analizador de PowerShell: aquí se prueba con esos hechos escritos a mano, sin
Windows. Contra el PowerShell de verdad, sólo con `HUB_WINDOWS_DE_VERDAD=1`:
la suite no toca el Windows de quien la corre en cada pasada.
"""

from __future__ import annotations

import base64
import json
import os
import re

import pytest

from hub import maquina, orden_pc

VETADAS = ["c:\\users\\yo\\proyectos\\tienda"]
BASE = {"temp": "C:\\Users\\yo\\AppData\\Local\\Temp", "perfil": "C:\\Users\\yo", "onedrive": ""}


def _c(nombre, *elementos, constante=True, posicion=0, previo=""):
    """Un comando como lo describe el guion: `-X` es parámetro, `{}` un bloque,
    `$…` una expresión y lo demás una cadena constante."""
    out = []
    for e in elementos:
        if isinstance(e, list):
            out.append({"tipo": "lista", "nombre": "", "texto": ",".join(e), "valores": e})
        elif e == "{}":
            out.append({"tipo": "bloque", "nombre": "", "texto": ""})
        elif e.startswith("-") and not e[1:2].isdigit():
            out.append({"tipo": "parametro", "nombre": e[1:].split(":")[0], "texto": e, "pegado": ":" in e})
        elif e.startswith(("$", "(", "@")):
            out.append({"tipo": "expresion", "nombre": "", "texto": e})
        elif e.lstrip("-").isdigit():
            out.append({"tipo": "numero", "nombre": "", "texto": e})
        else:
            out.append({"tipo": "constante", "nombre": "", "texto": e})
    return {"nombre": nombre, "constante": constante, "elementos": out, "posicion": posicion, "previo": previo}


def _h(*comandos, **otros):
    hechos = {"errores": [], "comandos": list(comandos), "metodos": [], "redirecciones": 0, "variables": [],
              "asignaciones": [], "cadenas": [], "usos": 0, "requisitos": False, "base": BASE}
    hechos.update(otros)
    return hechos


def _v(hechos, orden="x"):
    return orden_pc.veredicto(hechos, orden, VETADAS)


# ── qué es sólo mirar ────────────────────────────────────────────────────────

def test_los_modelos_de_los_monitores_se_miran_sin_preguntar():
    """El caso que lo motivó: «revisa cuáles son los modelos de mis monitores»."""
    v = _v(_h(_c("Get-CimInstance", "WmiMonitorID", "-Namespace", "root\\wmi"), _c("ForEach-Object", "{}"),
              _c("Where-Object", "{}"), _c("%", "{}"),
              variables=[{"nombre": "_", "unidad": "", "esparcida": False}]))
    assert v.lectura and not v.nunca and not v.motivos


@pytest.mark.parametrize("hechos, dice", [
    (_h(_c("Remove-Item", "C:\\nada.txt")), "«Remove-Item» no es de sólo mirar"),
    (_h(_c("Get-Content", "C:\\Windows\\win.ini")), "«Get-Content» no es de sólo mirar"),
    (_h(_c("Get-Clipboard")), "«Get-Clipboard» no es de sólo mirar"),
    (_h(metodos=["ReadAllText"]), "llama a «ReadAllText»"),
    (_h(_c("Get-Service"), redirecciones=1), "escribe en un archivo"),
    (_h(_c("Get-Service"), _c("%", "Stop")), "ForEach-Object sólo con un bloque"),
    (_h(_c("Get-Service"), _c("ForEach-Object", "-MemberName", "Stop")), "llama a métodos"),
    (_h(_c("Get-CimInstance", "Win32_BIOS", "-ComputerName", "otra")), "a otra máquina"),
    (_h(_c("Get-Service", "-Comp", "otra")), "a otra máquina"),
    (_h(_c("Get-CimInstance", "Win32_BIOS", "-CimSession", "$s")), "a otra máquina"),
    (_h(_c("Select-String", "clave", "C:\\x.txt")), "«Select-String» no es de sólo mirar"),
    (_h(_c("Get-ChildItem", "-Path:C:\\Users")), "escribe el valor separado"),
    (_h(_c("Get-ItemProperty", "-LiteralPath:C:\\x")), "escribe el valor separado"),
    (_h(_c("Get-ChildItem", "('C:' + '\\Users')")), "se calcula al correr"),
    (_h(_c("Get-Service", "$nombres")), "se calcula al correr"),
    (_h(_c("Get-CimInstance", "CIM_Process")), "la clase «CIM_Process»"),
    (_h(_c("Get-CimInstance", "-ClassName", "Win32_Product")), "la clase «Win32_Product»"),
    (_h(_c("Get-WmiObject", "-Query", "SELECT * FROM Win32_Product")), "la clase «Win32_Product»"),
    (_h(_c("Get-CimInstance", "Win32_BIOS", "-CN", "otra")), "a otra máquina"),
    (_h(_c("Get-CimInstance", "Win32_BIOS", "-Namespace", "root\\securitycenter2")), "espacio de WMI"),
    (_h(_c("Get-HotFix", "-IPAddress", "10.0.0.2")), "a otra máquina"),
    (_h(_c("Get-HotFix", "-__Server", "otra")), "a otra máquina"),
    (_h(_c("Get-WinEvent", "-PSPath", "C:\\x.evtx")), "lee archivos"),
    (_h(_c("Get-Service"), _c("ForEach-Object", "-Args", "x")), "llama a métodos"),
    # Lo que entra por la tubería: una cadena o un objeto con `Path`.
    (_h(_c("Get-ChildItem", posicion=1, previo="")), "por la tubería"),
    (_h(_c("Get-Process"), _c("Get-ChildItem", posicion=1, previo="Get-Process")), "por la tubería"),
    (_h(_c("Get-Process"), _c("%", "{}", posicion=1, previo="Get-Process"),
        _c("Get-ItemProperty", posicion=2, previo="%")), "por la tubería"),
    (_h(_c("Get-ChildItem", "C:\\Users")), "sólo mira el registro"),
    (_h(_c("Get-ItemProperty", "Env:Path")), "sólo mira el registro"),
    (_h(_c("Get-ChildItem", "$ruta")), "se calcula al correr"),
    (_h(variables=[{"nombre": "PATH", "unidad": "env", "esparcida": False}]), "variables de entorno"),
    (_h(_c("Get-Service"), variables=[{"nombre": "p", "unidad": "", "esparcida": True}]), "parámetros escondidos"),
    (_h(asignaciones=["$x.Valor"]), "cambia «$x.Valor»"),
    (_h(_c("Get-CimInstance", "Win32_Process"), cadenas=["Win32_Process"]), "línea de órdenes"),
    (_h(_c("Get-Service"), cadenas=["\\\\servidor\\c$"]), "otra máquina por red"),
    (_h(_c("& $x", constante=False)), "no está escrito"),
    (_h(usos=1), "carga módulos"),
])
def test_lo_que_no_es_solo_mirar_se_dice_con_su_motivo(hechos, dice):
    v = _v(hechos)
    assert not v.lectura
    assert any(dice in m for m in v.motivos), v.motivos


@pytest.mark.parametrize("hechos", [
    _h(_c("Get-CimInstance", "Win32_VideoController"), _c("Select-Object", ["Name", "DriverVersion"])),
    _h(_c("Get-CimInstance", "-ClassName", "WmiMonitorID", "-Namespace", "root/wmi")),
    _h(_c("gcim", "-Namespace", "root\\cimv2", "-Query", "SELECT Name FROM Win32_BIOS")),
    _h(_c("Get-WmiObject", "Win32_DiskDrive", "Model,Size")),
    _h(_c("Get-PnpDevice", "-Class", "Monitor", "-PresentOnly"), _c("Select-Object", "-First", "5")),
    _h(_c("Get-Process"), _c("Select-Object", "@{n='MB';e={$_.WS / 1MB}}")),
    _h(_c("Get-CimInstance", "Win32_LogicalDisk"), _c("Where-Object", "DeviceID", "-eq", "C:")),
    _h(_c("Get-PnpDevice", "-Class", "Monitor"), _c("Get-PnpDeviceProperty", posicion=1, previo="Get-PnpDevice")),
    _h(_c("Where-Object", "{}", posicion=1, previo="")),
])
def test_lo_que_si_es_solo_mirar(hechos):
    v = _v(hechos)
    assert v.lectura and not v.nunca, (v.motivos, v.nunca)


def test_el_registro_si_se_mira():
    v = _v(_h(_c("Get-ItemProperty", "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"),
              _c("Select-Object", "ProductName")))
    assert v.lectura


@pytest.mark.parametrize("nombre, args, lee", [
    ("ipconfig", (), True), ("ipconfig", ("/all",), True), ("ipconfig.exe", ("/ALL",), True),
    ("nvidia-smi", ("-L",), True), ("nvidia-smi", ("-l",), False), ("pnputil", ("/enum-devices", "/connected"), True),
    ("ipconfig", ("/release",), False), ("nvidia-smi", ("-pl", "100"), False),
    ("netsh", ("wlan", "show", "profile", "key=clear"), False), ("powercfg", ("/batteryreport",), False),
])
def test_los_programas_solo_miran_solos_y_con_sus_argumentos_fijos(nombre, args, lee):
    v = _v(_h(_c(nombre, *args)))
    assert v.lectura is lee
    if lee:
        assert v.nativo == (nombre.lower().removesuffix(".exe"), args)


def test_un_programa_de_lectura_dentro_de_una_tuberia_ya_no_es_solo_mirar():
    assert not _v(_h(_c("ipconfig", "/all"), _c("Select-String", "IPv4"))).lectura


# ── lo que no se acepta nunca ────────────────────────────────────────────────

@pytest.mark.parametrize("hechos, orden, dice", [
    (_h(_c("wsl", "-e", "cat", "/etc/passwd")), "wsl -e cat /etc/passwd", "WSL"),
    (_h(_c("ubuntu2204.exe")), "ubuntu2204.exe", "WSL"),
    (_h(_c("Get-ChildItem", "\\\\wsl$\\Ubuntu\\home")), "Get-ChildItem \\\\wsl$\\Ubuntu\\home", "WSL"),
    (_h(_c("Get-ChildItem", "//wsl.localhost/Ubuntu")), "Get-ChildItem //wsl.localhost/Ubuntu", "WSL"),
    (_h(_c("docker", "ps")), "docker ps", "de uno en uno"),
    (_h(_c("Stop-Service", "com.docker.service")), "Stop-Service com.docker.service", "de uno en uno"),
    (_h(_c("tailscale", "serve")), "tailscale serve", "red privada"),
    (_h(_c("New-NetFirewallRule")), "New-NetFirewallRule -LocalPort 22", "cortafuegos"),
    (_h(_c("netsh", "interface", "portproxy", "add")), "netsh interface portproxy add v4tov4", "puerto"),
    (_h(_c("Start-Process", "notepad", "-Verb", "RunAs")), "Start-Process notepad -Verb RunAs", "administrador"),
    (_h(_c("iex", "$x")), "iex $x", "lo que corre no es lo que aprobaste"),
    (_h(_c("powershell", "-c", "x")), "powershell -c x", "esconde lo que corre"),
    (_h(metodos=["FromBase64String"]), "[Convert]::FromBase64String('aGk=')", "codificado"),
    (_h(_c("Remove-Item", "C:\\Users\\yo\\proyectos\\tienda\\x")), "Remove-Item C:\\Users\\yo\\proyectos\\tienda\\x",
     "un proyecto tuyo"),
    (_h(_c("Get-ChildItem", "C:/Users/yo", "-Recurse"), _c("Remove-Item")), "Get-ChildItem C:/Users/yo -Recurse | Remove-Item",
     "un proyecto tuyo"),
    (_h(_c("Copy-Item", "C:\\Users\\yo\\.ssh\\id_ed25519", "D:\\")), "Copy-Item C:\\Users\\yo\\.ssh\\id_ed25519 D:\\",
     "llaves"),
    (_h(errores=["Falta la llave de cierre"]), "Get-Service | % {", "no se entiende"),
    # Lo que el revisor esquivó: rutas relativas, ~, $env:, comodines, \\?\.
    (_h(_c("Remove-Item", "..\\..\\..\\proyectos", "-Recurse")), "Remove-Item ..\\..\\..\\proyectos -Recurse",
     "un proyecto tuyo"),
    (_h(_c("Remove-Item", "~\\proyectos\\tienda\\x")), "Remove-Item ~\\proyectos\\tienda\\x", "un proyecto tuyo"),
    (_h(_c("Remove-Item", "$env:USERPROFILE\\proyectos"), cadenas=["$env:USERPROFILE\\proyectos"]),
     'Remove-Item "$env:USERPROFILE\\proyectos"', "un proyecto tuyo"),
    (_h(_c("Remove-Item", "C:\\Users\\*\\proyectos")), "Remove-Item C:\\Users\\*\\proyectos", "un proyecto tuyo"),
    (_h(_c("Remove-Item", "\\\\?\\C:\\Users\\yo\\proyectos\\tienda")), "Remove-Item \\\\?\\C:\\Users\\yo\\proyectos\\tienda",
     "un proyecto tuyo"),
    (_h(_c("Get-ChildItem", "\\\\?\\UNC\\wsl$\\Ubuntu")), "Get-ChildItem \\\\?\\UNC\\wsl$\\Ubuntu", "WSL"),
    (_h(_c("cmd", "/c", "wsl ls")), 'cmd /c "wsl ls"', "WSL"),
    (_h(_c("Start-Process", "C:\\Windows\\System32\\wsl.exe")), "Start-Process C:\\Windows\\System32\\wsl.exe", "WSL"),
    (_h(_c("& $x", constante=False)), "& $x", "se calcula al correr"),
    (_h(_c("Set-Location", "C:\\")), "Set-Location C:\\; Remove-Item x", "cambia de carpeta"),
    (_h(_c("Start-Process", "notepad", "-Verb", "RunAs"), cadenas=["RunAs"]), "Start-Process notepad -Verb Run`As",
     "administrador"),
])
def test_lo_que_no_se_acepta_ni_con_su_si(hechos, orden, dice):
    v = _v(hechos, orden)
    assert v.nunca and dice in v.nunca, v.nunca
    assert not v.lectura


def test_un_disco_en_un_filtro_no_es_tocar_carpetas():
    """Mirar no llega a los archivos: la regla de las carpetas es para cambiar."""
    v = _v(_h(_c("Get-CimInstance", "Win32_LogicalDisk"), _c("Where-Object", "DeviceID", "-eq", "C:")),
           "Get-CimInstance Win32_LogicalDisk | Where-Object DeviceID -eq 'C:'")
    assert v.lectura and not v.nunca


def test_mirar_el_servicio_de_docker_si_se_puede():
    """Cambiarlo es de la pantalla de docker (12); ver si está en marcha, no."""
    v = _v(_h(_c("Get-Service", "*docker*")), "Get-Service *docker*")
    assert v.lectura and not v.nunca


def test_una_carpeta_que_no_es_de_un_proyecto_se_puede_pedir():
    v = _v(_h(_c("Remove-Item", "C:\\Users\\Public\\x.txt")), "Remove-Item C:\\Users\\Public\\x.txt")
    assert not v.nunca and not v.lectura


def test_las_carpetas_de_los_proyectos_salen_del_registro_en_su_forma_de_windows(monkeypatch):
    from hub import registry

    class P:
        def todas_las_rutas(self):
            return ["/mnt/c/Users/Yo/Proyectos/Tienda", "/home/yo/projects/hub"]
    monkeypatch.setattr(registry, "cargar", lambda **k: [P()])
    assert orden_pc.rutas_vetadas() == ["c:\\users\\yo\\proyectos\\tienda"]


@pytest.fixture
def guion_sin_vetadas_fingidas(monkeypatch):
    """Como `guion_falso`, pero las carpetas vetadas salen del registro de verdad."""
    estado = {"hechos": _h(), "corridos": []}

    def lanzar(datos, fin):
        if datos["modo"] == "analizar":
            return {"hechos": estado["hechos"]}
        estado["corridos"].append(datos["modo"])
        return {"salida": "ok\n", "errores": []}
    monkeypatch.setattr(orden_pc, "_lanzar_guion", lanzar)
    return estado


def test_sin_registro_legible_cambiar_se_niega_y_leer_sigue(guion_sin_vetadas_fingidas, monkeypatch):
    """EJE-26: el registro roto no puede abrir la red justo cuando falla. Si no
    se sabe qué carpetas proteger, no se cambia nada; mirar no llega a los
    archivos y sigue."""
    from hub import registry

    def roto(**k):
        raise registry.YamlInvalido("roto")
    monkeypatch.setattr(registry, "cargar", roto)
    guion_sin_vetadas_fingidas["hechos"] = _h(_c("Remove-Item", "C:\\Users\\Public\\x.txt"))
    with pytest.raises(orden_pc.Prohibida, match="qué carpetas proteger"):
        orden_pc.cambiar("Remove-Item C:\\Users\\Public\\x.txt")
    guion_sin_vetadas_fingidas["hechos"] = _h(_c("Get-Service"))
    assert orden_pc.leer("Get-Service").salida == "ok\n"
    assert guion_sin_vetadas_fingidas["corridos"] == ["leer"]


def test_un_patron_ilegible_no_deja_sus_repos_sin_proteger(guion_sin_vetadas_fingidas, monkeypatch, tmp_path):
    """Con OneDrive en EIO (7-nov) el patrón se quedaba sin repos y éstos sin
    veto. Para el resto del hub sigue cargando sin ellos; para quien protege,
    no saber es no cambiar."""
    from pathlib import Path

    from hub import registry
    raiz = tmp_path / "onedrive"
    raiz.mkdir()
    yml = tmp_path / "projects.yml"
    yml.write_text(f"proyectos:\n  - id: trabajo\n    rutas:\n      - patron: \"{raiz}/*/repos/*\"\n",
                   encoding="utf-8")
    monkeypatch.setenv("HUB_PROJECTS_YML", str(yml))
    original = Path.glob

    def glob_que_falla(self, *a, **k):
        if str(self).startswith(str(raiz)):
            raise OSError(5, "Input/output error", str(self))
        return original(self, *a, **k)
    monkeypatch.setattr(Path, "glob", glob_que_falla)
    assert [p.rutas for p in registry.cargar()] == [[]]
    guion_sin_vetadas_fingidas["hechos"] = _h(_c("Remove-Item", "C:\\Users\\Public\\x.txt"))
    with pytest.raises(orden_pc.Prohibida, match="qué carpetas proteger"):
        orden_pc.cambiar("Remove-Item C:\\Users\\Public\\x.txt")
    assert guion_sin_vetadas_fingidas["corridos"] == []


def test_las_rutas_vetadas_incluyen_un_repo_recien_clonado(monkeypatch, tmp_path):
    """La expansión de un patrón se recuerda un minuto (C-0415), pero lo que
    protege no se fía de lo recordado (decisión 410): un repo clonado hace un
    segundo queda vetado ya, aunque el resto del hub aún no lo vea."""
    from hub import registry
    ws = tmp_path / "ws"
    (ws / "ext" / "repos" / "a" / ".git").mkdir(parents=True)
    yml = tmp_path / "projects.yml"
    yml.write_text(f"proyectos:\n  - id: trabajo\n    asiento: {ws}\n    rutas:\n"
                   "      - patron: \"*/repos/*\"\n", encoding="utf-8")
    monkeypatch.setenv("HUB_PROJECTS_YML", str(yml))
    # Fuera de un disco de Windows no hay forma de Windows: aquí, la ruta tal cual.
    monkeypatch.setattr(orden_pc, "_windows", lambda r: r)
    registry.cargar()
    (ws / "ext" / "repos" / "b" / ".git").mkdir(parents=True)
    assert str(ws / "ext" / "repos" / "b") in orden_pc.rutas_vetadas()
    assert str(ws / "ext" / "repos" / "b") not in [r.ruta for r in registry.cargar()[0].rutas]


def test_un_registro_que_no_esta_tampoco_deja_las_carpetas_sin_proteger(guion_sin_vetadas_fingidas, monkeypatch,
                                                                          tmp_path):
    """Fallaba cerrado si el registro no se leía, pero abierto si no estaba (la
    ruta mal puesta, el disco sin montar): sin registro salía la lista vacía y
    se cambiaba cualquier carpeta (C-0314). Para el resto del hub, un registro
    que no está sigue siendo un registro vacío."""
    from hub import registry
    monkeypatch.setenv("HUB_PROJECTS_YML", str(tmp_path / "no-esta" / "projects.yml"))
    assert registry.cargar() == []
    with pytest.raises(orden_pc.SinVetadas, match="qué carpetas proteger"):
        orden_pc.rutas_vetadas()
    guion_sin_vetadas_fingidas["hechos"] = _h(_c("Remove-Item", "C:\\Users\\Public\\x.txt"))
    with pytest.raises(orden_pc.Prohibida, match="qué carpetas proteger"):
        orden_pc.cambiar("Remove-Item C:\\Users\\Public\\x.txt")
    assert guion_sin_vetadas_fingidas["corridos"] == []


# ── el guion: la orden entra como dato ───────────────────────────────────────

def test_la_orden_llega_por_la_entrada_y_nunca_al_texto_del_guion():
    """Por la entrada, además, no ocupa la línea de órdenes de Windows: con
    `-EncodedCommand` una orden de unos 2 800 caracteres ya no cabía."""
    orden = "Get-Service | Where-Object { $_.Name -eq 'x' }\n'; Remove-Item C:\\ #" + "á" * 3000
    entrada = orden_pc._entrada(orden_pc._datos("leer", orden))
    assert re.fullmatch(rb"[A-Za-z0-9+/=]+", entrada)
    datos = json.loads(base64.b64decode(entrada))
    assert base64.b64decode(datos["orden"]).decode() == orden
    assert "Remove-Item" not in orden_pc.GUION and len(orden_pc._GUION_CODIFICADO) < 32_000


def test_el_guion_es_fijo_y_no_ejecuta_texto():
    assert "__DATOS__" not in orden_pc.GUION and "[Console]::In.ReadToEnd()" in orden_pc.GUION
    assert not re.search(r"Invoke-Expression|\biex\b|\[ScriptBlock\]::Create", orden_pc.GUION, re.I)


@pytest.mark.parametrize("mala", ["Get-Date\u202e", "Get-Date\u200b; Remove-Item x", "Get-Date\x1b[2K",
                                  "Get-Date\u2028Remove-Item x", "Get-Date\u00a0-Format x"])
def test_lo_que_no_se_ve_no_entra(mala):
    """El sí es a lo que se ve en Pendientes: un carácter invisible o de
    control haría que lo que se ve no fuera lo que corre."""
    with pytest.raises(ValueError, match="invisibles"):
        orden_pc._validar(mala)


def test_el_candado_del_guion_lleva_la_misma_lista_que_la_politica():
    datos = orden_pc._datos("leer", "Get-Date")
    assert set(datos["permitidos"]) == set(orden_pc.CMDLETS_LECTURA) | set(orden_pc.ALIAS_LECTURA)
    assert set(datos["modulos"]) == set(orden_pc.CMDLETS_LECTURA.values())


# ── leer y cambiar, con el guion fingido ─────────────────────────────────────

@pytest.fixture
def guion_falso(monkeypatch):
    """`_lanzar_guion` fingido: devuelve `hechos` al analizar y apunta qué modo se corrió."""
    estado = {"hechos": _h(), "corridos": [], "respuesta": {"salida": "ok\n", "errores": []}}

    def lanzar(datos, fin):
        if datos["modo"] == "analizar":
            return {"hechos": estado["hechos"]}
        estado["corridos"].append(datos["modo"])
        return estado["respuesta"]
    monkeypatch.setattr(orden_pc, "_lanzar_guion", lanzar)
    monkeypatch.setattr(orden_pc, "rutas_vetadas", lambda: VETADAS)
    return estado


def test_leer_no_corre_lo_que_no_es_solo_mirar(guion_falso):
    guion_falso["hechos"] = _h(_c("Remove-Item", "C:\\x"))
    with pytest.raises(orden_pc.NoEsLectura, match="Remove-Item"):
        orden_pc.leer("Remove-Item C:\\x")
    assert guion_falso["corridos"] == []


def test_leer_corre_en_el_powershell_recortado_y_devuelve_lo_que_sale(guion_falso):
    guion_falso["hechos"] = _h(_c("Get-Service"))
    r = orden_pc.leer("Get-Service")
    assert guion_falso["corridos"] == ["leer"] and r.salida == "ok\n" and not r.errores


def test_si_el_candado_la_para_no_se_da_por_leida(guion_falso):
    guion_falso["hechos"] = _h(_c("Get-Service"))
    guion_falso["respuesta"] = {"cerradura": ["comando cmd.exe"]}
    with pytest.raises(orden_pc.NoEsLectura, match="candado"):
        orden_pc.leer("Get-Service")


def test_cambiar_no_corre_lo_prohibido_aunque_lo_llamen(guion_falso):
    guion_falso["hechos"] = _h(_c("docker", "rm", "web"))
    with pytest.raises(orden_pc.Prohibida, match="de uno en uno"):
        orden_pc.cambiar("docker rm web")
    assert guion_falso["corridos"] == []


def test_cambiar_corre_en_un_powershell_normal(guion_falso):
    guion_falso["hechos"] = _h(_c("Restart-Service", "Spooler"))
    orden_pc.cambiar("Restart-Service Spooler")
    assert guion_falso["corridos"] == ["cambiar"]


def test_una_orden_vacia_o_enorme_no_llega_a_powershell(guion_falso):
    for mala in ("", "   ", "Get-Date;" * 1000):
        with pytest.raises(ValueError):
            orden_pc.leer(mala)
    assert guion_falso["corridos"] == []


# ── contra el PowerShell de verdad (opcional) ────────────────────────────────

de_verdad = pytest.mark.skipif(
    os.environ.get("HUB_WINDOWS_DE_VERDAD") != "1" or not maquina.encontrar("powershell.exe"),
    reason="sólo con HUB_WINDOWS_DE_VERDAD=1 y Windows debajo")


@de_verdad
@pytest.mark.parametrize("orden, lee", [
    ("Get-CimInstance WmiMonitorID -Namespace root\\wmi | ForEach-Object { ($_.UserFriendlyName | "
     "Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join '' }", True),
    ("Get-PnpDevice -Class Monitor -PresentOnly | Select-Object FriendlyName", True),
    ("[IO.File]::ReadAllText('C:\\Windows\\win.ini')", False),
    ("Get-Service | Select-Object -First 1 > C:\\Users\\Public\\hub-prueba.txt", False),
    ("Get-Service | % Stop", False),
])
def test_de_verdad_el_analizador_de_powershell_da_lo_mismo(orden, lee):
    assert orden_pc.clasificar(orden).lectura is lee


@de_verdad
@pytest.mark.parametrize("orden", ["C:\\Windows\\System32\\cmd.exe /c echo x", "Remove-Item C:\\nada-de-hub.txt"])
def test_de_verdad_el_candado_del_guion_para_lo_que_no_esta_en_la_lista(orden):
    """Medido el 10-nov: el PowerShell recortado no impide un programa por su
    ruta. El candado del guion, en el mismo proceso, sí."""
    import time
    r = orden_pc._lanzar_guion(orden_pc._datos("leer", orden), time.monotonic() + orden_pc.TOPE_S)
    assert r.get("cerradura") and "salida" not in r


@de_verdad
def test_de_verdad_lee_y_devuelve_lo_que_escribe():
    r = orden_pc.leer("Get-Date -Format yyyy")
    assert re.search(r"\b20\d\d\b", r.salida) and not r.errores


@de_verdad
@pytest.mark.parametrize("orden, lee", [
    ("Get-ChildItem -Path:C:\\Users", False),
    ("Select-String clave C:\\Windows\\win.ini", False),
    ("Get-CimInstance -ClassName Win32_Product", False),
    ("Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion", True),
    ("Get-Process | Select-Object -First 3 Name, @{n='MB';e={[int]($_.WS / 1MB)}}", True),
])
def test_de_verdad_los_huecos_que_encontro_el_revisor(orden, lee):
    assert orden_pc.clasificar(orden).lectura is lee


@de_verdad
def test_de_verdad_una_ruta_relativa_se_resuelve_como_la_veria_windows():
    hechos = orden_pc.analizar("Remove-Item ..\\..\\..\\proyecto-falso-del-hub -Recurse")
    perfil = hechos["base"]["perfil"].lower()
    v = orden_pc.veredicto(hechos, "x", [perfil + "\\proyecto-falso-del-hub"])
    assert v.nunca and "un proyecto tuyo" in v.nunca


@de_verdad
def test_de_verdad_una_orden_larga_con_acentos_cabe():
    orden = "Get-Date | Select-Object " + ", ".join(f"@{{n='campo_á{i}';e={{$_.Year}}}}" for i in range(110))
    assert len(orden) > 2_800
    assert orden_pc.clasificar(orden).lectura


@de_verdad
@pytest.mark.parametrize("orden, lee", [
    ("'C:\\Users' | Get-ChildItem", False),
    ("Get-Process | Select-Object -First 1 | Get-ChildItem", False),
    ("Get-PnpDevice -Class Monitor -PresentOnly | Get-PnpDeviceProperty -KeyName DEVPKEY_Device_FriendlyName", True),
])
def test_de_verdad_lo_que_entra_por_la_tuberia(orden, lee):
    assert orden_pc.clasificar(orden).lectura is lee


@de_verdad
def test_de_verdad_el_candado_para_lo_que_entra_por_la_tuberia():
    import time
    r = orden_pc._lanzar_guion(orden_pc._datos("leer", "'C:\\Users' | Get-ChildItem"),
                               time.monotonic() + orden_pc.TOPE_S)
    assert any("tubería" in m for m in r.get("cerradura") or []) and "salida" not in r
