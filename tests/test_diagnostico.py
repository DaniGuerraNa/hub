"""El diagnóstico de Windows y de la red, en sólo lectura (decisión 386, C-0194).

Se prueba con salidas grabadas, sin Windows: lo que se protege es que los
guiones no puedan cambiar nada, que lo de fuera no llegue a PowerShell sin
validar, que de un pantallazo salgan su código y su hora, que la traza se lea
en cualquier idioma y que todo quepa en el tiempo de una herramienta. Las
cifras de verdad se midieron contra el Windows real (ver la ficha).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from hub import diagnostico, maquina
from hub.secretario import herramientas, motor

# ── las salidas grabadas (anonimizadas: IP de documentación, equipo genérico) ──

_LARGO = "x" * 900
EVENTOS = [
    {"id": 1001, "fuente": "Microsoft-Windows-WER-SystemErrorReporting", "hora": "2026-11-06T22:50:50Z",
     "bugcheck": None,
     "texto": "El equipo se reinició después de una comprobación de errores. La comprobación de errores fue: "
              "0x00000133 (0x0000000000000000, 0x0000000000000501, 0x0000000000000500, 0xfffff8046f4fb320). "
              "Se guardó un volcado en: C:\\Windows\\MEMORY.DMP. Id. de informe: 0000. " + _LARGO},
    {"id": 41, "fuente": "Microsoft-Windows-Kernel-Power", "hora": "2026-11-06T22:50:30Z", "bugcheck": 307,
     "texto": "Se reinició el sistema sin apagarlo limpiamente primero."},
    {"id": 161, "fuente": "volmgr", "hora": "2026-11-06T22:50:25Z", "bugcheck": None,
     "texto": "No se pudo crear el archivo de volcado debido a un error durante la creación del volcado."},
    {"id": 6008, "fuente": "EventLog", "hora": "2026-11-06T22:50:42Z", "bugcheck": None,
     "texto": "El cierre anterior del sistema a las 04:13:25 p. m. del \u200e06/\u200e11/\u200e2026 resultó inesperado."},
    # En inglés: el código sale igual.
    {"id": 1001, "fuente": "Microsoft-Windows-WER-SystemErrorReporting", "hora": "2026-11-05T16:53:25Z",
     "bugcheck": None,
     "texto": "The computer has rebooted from a bugcheck.  The bugcheck was: 0x00000101 (0x0000000000000008, "
              "0x0000000000000000, 0xffffaf81c23c0180, 0x000000000000000a). A dump was saved in: "
              "C:\\Windows\\MEMORY.DMP. Report Id: 0000."},
    # Un 41 con código y sin su 1001: el volcado no se guardó, pero fue un pantallazo.
    {"id": 41, "fuente": "Microsoft-Windows-Kernel-Power", "hora": "2026-11-01T08:00:00Z", "bugcheck": 0x124,
     "texto": "Se reinició el sistema sin apagarlo limpiamente primero."},
    {"id": 6005, "fuente": "EventLog", "hora": "2026-11-06T22:50:40Z", "bugcheck": None,
     "texto": "Se inició el servicio de registro de eventos."},
]
WINDOWS = {
    "eventos": EVENTOS,
    "volcados": [{"nombre": "C:\\Windows\\MEMORY.DMP", "bytes": 5679219536, "fecha": "2026-11-06T22:50:38Z"}],
    "sin_permiso": ["C:\\Windows\\Minidump"],
    "equipo": {"bios": {"fabricante": "Fabricante BIOS", "version": "F6", "fecha": "2023-05-16"},
               "placa": {"fabricante": "Fabricante", "modelo": "Placa X"}, "cpu": "CPU de 12 núcleos",
               "windows": {"nombre": "Microsoft Windows 10 Pro", "version": "10.0.19045",
                           "arranque": "2026-11-06T22:50:20Z"}},
    "fallos": [],
}
RED = {
    "adaptadores": [{"nombre": "Ethernet", "descripcion": "Controlador 2.5GbE", "velocidad": "100 Mbps", "medio": "802.3"}],
    "rutas": [{"siguiente": "192.168.1.1", "interfaz": "Ethernet", "metrica": 35},
              {"siguiente": "26.0.0.1", "interfaz": "Otra VPN", "metrica": 9257}],
    "dns": [{"interfaz": "Ethernet", "servidores": ["8.8.8.8", "8.8.4.4"]}],
    "proceso": None,
    "fallos": [],
}

PING_ES = ("\r\nHaciendo ping a 1.1.1.1 con 32 bytes de datos:\r\n"
           "Respuesta desde 1.1.1.1: bytes=32 tiempo=41ms TTL=54\r\n"
           "Respuesta desde 1.1.1.1: bytes=32 tiempo<1m TTL=54\r\n"
           "Tiempo de espera agotado para esta solicitud.\r\n"
           "Respuesta desde 192.168.1.20: Host de destino inaccesible.\r\n"
           "Respuesta desde 1.1.1.1: bytes=32 tiempo=45ms TTL=54\r\n\r\n"
           "Estad\xa1sticas de ping para 1.1.1.1:\r\n").encode("cp850")
PING_EN = ("\r\nPinging 1.1.1.1 with 32 bytes of data:\r\n"
           "Reply from 1.1.1.1: bytes=32 time=41ms TTL=54\r\n"
           "Reply from 1.1.1.1: bytes=32 time<1ms TTL=54\r\n"
           "Request timed out.\r\n"
           "Reply from 192.168.1.20: Destination host unreachable.\r\n"
           "Reply from 1.1.1.1: bytes=32 time=45ms TTL=54\r\n\r\n"
           "Ping statistics for 1.1.1.1:\r\n").encode("ascii")

TRACERT_ES = ("\r\nTraza a 1.1.1.1 sobre caminos de 15 saltos como m\xa0ximo.\r\n\r\n"
              "  1    <1 ms    <1 ms    <1 ms  192.168.1.1 \r\n"
              "  2     1 ms    <1 ms    <1 ms  100.64.0.1 \r\n"
              "  3    24 ms    24 ms    24 ms  203.0.113.14 \r\n"
              "  4     *        *        *     Tiempo de espera agotado para esta solicitud.\r\n"
              "  5    38 ms     *       38 ms  198.51.100.9 \r\n"
              " 10   575 ms   567 ms   330 ms  1.1.1.1 \r\n\r\n"
              "Traza completa.\r\n").encode("cp850")
TRACERT_EN = ("\r\nTracing route to 1.1.1.1 over a maximum of 15 hops\r\n\r\n"
              "  1    <1 ms    <1 ms    <1 ms  192.168.1.1 \r\n"
              "  2     1 ms    <1 ms    <1 ms  100.64.0.1 \r\n"
              "  3    24 ms    24 ms    24 ms  203.0.113.14 \r\n"
              "  4     *        *        *     Request timed out.\r\n"
              "  5    38 ms     *       38 ms  198.51.100.9 \r\n"
              " 10   575 ms   567 ms   330 ms  1.1.1.1 \r\n\r\n"
              "Trace complete.\r\n").encode("ascii")


class Proceso:
    """Un `Popen` grabado. `cuelga`: no termina nunca, y cada espera adelanta
    el reloj falso lo que se le dejó esperar."""

    def __init__(self, salida: bytes = b"", rc: int = 0, *, cuelga: bool = False, reloj=None,
                 no_suelta: bool = False):
        self.salida, self.rc, self.cuelga, self.reloj, self.muerto = salida, rc, cuelga, reloj, False
        self.no_suelta, self.returncode = no_suelta, None

    def communicate(self, timeout=None):
        if self.cuelga and (not self.muerto or self.no_suelta):
            if self.reloj is not None and timeout:
                self.reloj.t += timeout
            raise subprocess.TimeoutExpired("x", timeout)
        self.returncode = None if self.cuelga else self.rc
        return (b"" if self.cuelga else self.salida), b""

    def kill(self):
        self.muerto = True


@pytest.fixture
def windows_falso(monkeypatch):
    """Una PC con Windows grabada: cada programa contesta lo de arriba. Devuelve
    la lista de lo que se lanzó, para ver qué llegó a cada uno."""
    lanzados: list[list[str]] = []
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")

    def lanzar(args):
        lanzados.append(list(args))
        programa = args[0].rsplit("/", 1)[-1]
        if programa == "powershell.exe":
            datos = WINDOWS if "Get-WinEvent" in args[-1] else RED
            return Proceso(json.dumps(datos, ensure_ascii=False).encode("utf-8"))
        if programa == "ping.exe":
            return Proceso(PING_ES)
        if programa == "tracert.exe":
            return Proceso(TRACERT_ES)
        raise AssertionError(f"no se esperaba lanzar {args}")

    monkeypatch.setattr(diagnostico, "_lanzar", lanzar)
    return lanzados


# ── sólo lectura ───────────────────────────────────────────────────────────────

def _sin_cadenas(guion: str) -> str:
    """Lo que hay entre comillas simples es dato («Microsoft-Windows-WHEA-Logger»), no código."""
    return re.sub(r"'[^']*'", "''", guion)


def test_el_diagnostico_solo_usa_verbos_de_lectura():
    """🔴 Un guion fijo que pudiera cambiar algo en la PC no es diagnóstico.
    Se lee cada guion: cada cmdlet tiene que empezar por un verbo de lectura,
    no hay operador de llamada ni `Invoke-Expression`, los métodos que se
    llaman son de formatear y no de actuar (nada de `.Kill()`), y lo único de
    .NET que se toca es la codificación de la salida."""
    assert len(diagnostico.GUIONES) == 4
    for guion in diagnostico.GUIONES:
        codigo = _sin_cadenas(guion)
        verbos = set(re.findall(r"\b([A-Z][A-Za-z]*)-[A-Z][A-Za-z]+\b", codigo))
        assert verbos and verbos <= set(diagnostico.VERBOS_DE_LECTURA), verbos - set(diagnostico.VERBOS_DE_LECTURA)
        assert "&" not in codigo and not re.search(r"\b(iex|icm|Invoke)\b", codigo, re.I)
        metodos = set(re.findall(r"\.(\w+)\(", codigo))
        assert metodos <= {"AddDays", "ToUniversalTime", "ToString", "Substring", "Trim"}, metodos
        estaticas = set(re.findall(r"\[[\w.]+\]::\w+", codigo))
        assert estaticas <= {"[Console]::OutputEncoding", "[Text.Encoding]::UTF8", "[Math]::Min"}, estaticas
        assert '"' not in guion  # viajan por la línea de órdenes de Windows, que interpreta las dobles
        # 🔴 Lo que está en posición de orden (inicio de línea, tras | ; { ( =)
        # es un cmdlet de lectura o una palabra del lenguaje: así no cuela un
        # ejecutable suelto (`shutdown.exe /r`, `netsh …`) ni un alias (`kill`,
        # `rm`, `spps`). Una clave de tabla (`id=…`) no es una orden.
        assert not _ordenes_que_no_leen(codigo), _ordenes_que_no_leen(codigo)
        assert ".exe" not in guion.lower()  # ni dentro de una cadena: `. 'C:\…\shutdown.exe'` la ejecuta


PALABRAS = {"foreach", "if", "elseif", "else", "try", "catch"}


def _ordenes_que_no_leen(codigo: str) -> set[str]:
    """Lo que en posición de orden no es un cmdlet de lectura ni una palabra
    del lenguaje; también `ForEach-Object Kill` (un método por su nombre, sin
    paréntesis) y el operador punto, que ejecuta lo que le sigue."""
    raras = set(re.findall(r"ForEach-Object\s+(-?[A-Za-z]\w*)", codigo))
    raras |= {"." for _ in re.finditer(r"(?:^|[|;{(=])\s*\.\s", codigo, re.M)}
    ordenes = set(re.findall(r"(?:^|[|;{(=])\s*([A-Za-z][\w.-]*)(?!\s*=)(?![\w.-])", codigo, re.M))
    verbos = "|".join(diagnostico.VERBOS_DE_LECTURA)
    return raras | {o for o in ordenes if o not in PALABRAS and not re.fullmatch(rf"(?:{verbos})-[A-Za-z]+", o)}


def test_el_test_de_solo_lectura_caza_una_orden_suelta():
    """El vigilante, vigilado: un guion con una orden que actúa no pasa."""
    for malo in ("$x = shutdown.exe /r", "Get-Process | spps", "try { kill 4 }", "if ($a) { Stop-Computer }",
                 "netsh interface set interface Ethernet disable", "Get-Process x | ForEach-Object Kill",
                 "Get-Service x | ForEach-Object -MemberName Stop", "$x = 1; . 'C:\\Windows\\x.ps1'"):
        assert _ordenes_que_no_leen(_sin_cadenas(malo)), malo


def test_los_programas_se_buscan_por_la_puerta_de_maquina():
    """Por `maquina.encontrar`, que sabe dónde están aunque el PATH de systemd
    no los traiga; `maquina._salida` es privado y no es un segundo camino."""
    fuente = (Path(diagnostico.__file__)).read_text(encoding="utf-8")
    assert "maquina.encontrar(" in fuente
    assert "_salida(" not in fuente and "shutil.which" not in fuente and "shell=True" not in fuente
    assert {"tracert.exe", "ping.exe", "powershell.exe"} <= set(maquina.RESPALDOS)


def test_tracert_y_ping_van_con_argumentos_sueltos_y_sin_shell(windows_falso):
    diagnostico.red(trazar="1.1.1.1")
    traza = next(a for a in windows_falso if a[0].endswith("tracert.exe"))
    assert traza[1:] == ["-d", "-h", "15", "-w", "500", "1.1.1.1"]
    pings = [a for a in windows_falso if a[0].endswith("ping.exe")]
    assert {a[-1] for a in pings} == {"192.168.1.1", "1.1.1.1", "8.8.8.8"}
    assert all(a[1:-1] == ["-n", "5", "-w", "1000"] for a in pings)


# ── lo que entra de fuera ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raro", [
    "1.1.1.1; Stop-Computer", "-t", "-n 99999 1.1.1.1", "x' ; Remove-Item C:\\ -Recurse ; '", "$(Get-Process)",
    "a b", "fe80::1%x; y", "uno..dos", "a" * 300, "`calc`", "host\nStop-Computer", "-",
])
def test_un_destino_raro_no_llega_a_ningun_programa(windows_falso, raro):
    with pytest.raises(ValueError):
        diagnostico.red([raro])
    with pytest.raises(ValueError):
        diagnostico.red(trazar=raro)
    assert windows_falso == []


def test_una_puerta_de_enlace_rara_tampoco_llega_a_ping(windows_falso, monkeypatch):
    """La puerta viene de Windows, pero va a `ping.exe` como un destino: pasa por el mismo patrón."""
    monkeypatch.setitem(RED, "rutas", [{"siguiente": "-t", "interfaz": "Rara", "metrica": 1},
                                       {"siguiente": "192.168.1.1", "interfaz": "Ethernet", "metrica": 35}])
    d = diagnostico.red()
    assert d["puerta"] == "192.168.1.1"
    assert not any("-t" == a[-1] for a in windows_falso)


def test_un_destino_o_un_proceso_raro_no_llega_a_powershell(windows_falso):
    """🔴 Lo único que entra en un guion es el nombre de un proceso, entre
    comillas simples; el patrón no admite comillas, `$`, comodines ni saltos."""
    for raro in ["juego'; Stop-Process -Name explorer; '", "juego*", "$env:USERNAME", "a|b", "x" * 65,
                 "juego\nStop-Computer", 'ju"ego', "", "(Get-Process)"]:
        with pytest.raises(ValueError):
            diagnostico.red(proceso=raro or " ")
    for raro in ["1.1.1.1'; Stop-Computer; '", "-t"]:
        with pytest.raises(ValueError):
            diagnostico.red([raro], proceso="juego")
    assert windows_falso == []

    diagnostico.red(proceso="Juego-Win64-Shipping.exe")
    (guion,) = [a[-1] for a in windows_falso if a[0].endswith("powershell.exe")]
    assert "$buscado = 'Juego-Win64-Shipping'" in guion
    assert "__PROCESO__" not in guion


def test_los_dias_se_acotan_antes_de_entrar_al_guion(windows_falso):
    for malo in (0, -3, 61, "1; Stop-Computer"):
        with pytest.raises(ValueError):
            diagnostico.windows(malo)
    assert windows_falso == []
    diagnostico.windows(7)
    assert "(Get-Date).AddDays(-7)" in windows_falso[0][-1]


# ── sin Windows ───────────────────────────────────────────────────────────────

def test_sin_windows_lo_dice_y_no_revienta(monkeypatch, capsys):
    """En un Linux sin Windows debajo: un mensaje claro, sin lanzar nada, y
    ni la herramienta del secretario ni la CLI se caen."""
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: None)
    monkeypatch.setattr(diagnostico, "_lanzar", lambda args: pytest.fail(f"lanzó {args}"))

    with pytest.raises(diagnostico.SinWindows, match="Windows"):
        diagnostico.windows()
    with pytest.raises(diagnostico.SinWindows, match="powershell.exe"):
        diagnostico.red(trazar="1.1.1.1")

    h = herramientas.todas()["diagnosticar_pc"]
    for que in ("windows", "red"):
        r = h.funcion(None, {"que": que})
        assert "Windows" in r["error"]
    assert diagnostico.main(["windows"]) == 2
    assert "WSL" in capsys.readouterr().err


def test_si_wsl_no_deja_lanzar_programas_de_windows_tambien_lo_dice(monkeypatch):
    """El archivo está pero no arranca (la interoperabilidad apagada, como se
    midió para la 313): no es un error raro, es «aquí no hay Windows»."""
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")

    def no_arranca(args):
        raise OSError(8, "Exec format error")

    monkeypatch.setattr(diagnostico, "_lanzar", no_arranca)
    with pytest.raises(diagnostico.SinWindows, match="interoperabilidad"):
        diagnostico.windows()
    with pytest.raises(diagnostico.SinWindows, match="interoperabilidad"):
        diagnostico.red(trazar="1.1.1.1")
    assert "interoperabilidad" in herramientas.todas()["diagnosticar_pc"].funcion(None, {"que": "red"})["error"]


# ── Windows ───────────────────────────────────────────────────────────────────

def test_de_un_pantallazo_saca_su_codigo_y_su_hora(windows_falso):
    """Las dos horas: la de volver a arrancar (el 1001) y la de la caída (el 6008)."""
    d = diagnostico.windows()

    assert d["pantallazos"] == [
        {"hora": "2026-11-06T22:50:50Z", "codigo": "0x00000133", "nombre": "DPC_WATCHDOG_VIOLATION",
         "cayo": "04:13:25 p. m. del 06/11/2026"},
        {"hora": "2026-11-05T16:53:25Z", "codigo": "0x00000101", "nombre": "CLOCK_WATCHDOG_TIMEOUT",
         "cayo": d["pantallazos"][1]["cayo"]},
        # El 41 que no tuvo su 1001; el que sí lo tuvo no se cuenta dos veces.
        {"hora": "2026-11-01T08:00:00Z", "codigo": "0x00000124", "nombre": "WHEA_UNCORRECTABLE_ERROR", "cayo": ""},
    ]
    assert all(len(e["texto"]) <= diagnostico.TEXTO for e in d["eventos"])
    assert [e["hora"] for e in d["eventos"]] == sorted((e["hora"] for e in d["eventos"]), reverse=True)
    assert {e["que"] for e in d["eventos"]} >= {"pantallazo", "no pudo guardar el volcado", "arranque"}
    assert d["volcados"] == WINDOWS["volcados"]
    assert d["sin_permiso"] == ["C:\\Windows\\Minidump"]

    texto = diagnostico.legible(d)
    assert "0x00000133 DPC_WATCHDOG_VIOLATION" in texto
    # La hora del 1001 es la de volver a arrancar; la caída, la del 6008, tal
    # cual la escribe Windows (revisión cruzada del 7-nov: 37 min de diferencia).
    assert "se cayó a las 04:13:25 p. m. del 06/11/2026 (según el 6008)" in texto
    assert "cuando volvió a arrancar, no la de la caída" in texto
    assert "BIOS F6 del 2023-05-16" in texto
    assert "Sin permiso para listar C:\\Windows\\Minidump" in texto
    assert "Sólo lectura" in texto


def test_las_marcas_de_direccion_de_windows_no_llegan_al_texto(windows_falso):
    d = diagnostico.windows()
    assert not any("\u200e" in e["texto"] for e in d["eventos"])
    assert any("06/11/2026" in e["texto"] for e in d["eventos"] if e["id"] == 6008)


def test_si_powershell_no_devuelve_json_se_dice(monkeypatch):
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    monkeypatch.setattr(diagnostico, "_lanzar", lambda args: Proceso(b"Acceso denegado", rc=1))
    d = diagnostico.windows()
    assert d["pantallazos"] == [] and "PowerShell no devolvió" in d["fallos"][0]
    assert "No se pudo: PowerShell" in diagnostico.legible(d)


# ── la red ─────────────────────────────────────────────────────────────────────

def test_tracert_se_lee_en_espanol_y_en_ingles():
    es = diagnostico.leer_tracert(diagnostico._texto(TRACERT_ES))
    en = diagnostico.leer_tracert(diagnostico._texto(TRACERT_EN))

    assert es == en
    assert [s["salto"] for s in es] == [1, 2, 3, 4, 5, 10]
    assert es[0] == {"salto": 1, "ms": [0, 0, 0], "ip": "192.168.1.1"}
    assert es[3] == {"salto": 4, "ms": [None, None, None], "ip": None}
    assert es[4] == {"salto": 5, "ms": [38, None, 38], "ip": "198.51.100.9"}
    assert es[5]["ms"] == [575, 567, 330]


def test_ping_se_lee_en_espanol_y_en_ingles_y_sin_contar_un_inaccesible():
    """«Host de destino inaccesible» empieza como una respuesta y no es un eco;
    en español, «<1 ms» se escribe «tiempo<1m», sin la «s»."""
    es = diagnostico.leer_ping(diagnostico._texto(PING_ES))
    en = diagnostico.leer_ping(diagnostico._texto(PING_EN))
    assert es == en == {"enviados": 5, "recibidos": 3, "perdidos_pct": 40, "min": 0, "media": 29, "max": 45}

    nada = diagnostico.leer_ping("La solicitud de ping no pudo encontrar el host x.invalid. Compruebe el nombre y\n"
                                 "vuelva a intentarlo.\n")
    assert nada["recibidos"] == 0 and nada["perdidos_pct"] == 100 and "no pudo encontrar" in nada["nota"]
    assert "vuelva a intentarlo" in nada["nota"]


def test_un_eco_por_ipv6_se_cuenta_aunque_no_lleve_ttl():
    """🔴 Medido el 7-nov contra el `ping.exe` real: en IPv6 la respuesta no
    trae TTL. Exigirlo daba un 100 % de pérdida inventado a todo lo que se
    resuelve por IPv6 (también «localhost»), y una cifra así no se enseña."""
    salida = ("\nHaciendo ping a ::1 con 32 bytes de datos:\nRespuesta desde ::1: tiempo<1m \n"
              "Respuesta desde ::1: tiempo=3ms \n\nEstadísticas de ping para ::1:\n"
              "    Paquetes: enviados = 2, recibidos = 2, perdidos = 0\n    (0% perdidos),\n"
              "Tiempos aproximados de ida y vuelta en milisegundos:\n    Mínimo = 0ms, Máximo = 3ms, Media = 1ms\n")
    assert diagnostico.leer_ping(salida, enviados=2) == {"enviados": 2, "recibidos": 2, "perdidos_pct": 0,
                                                          "min": 0, "media": 2, "max": 3}
    en = "Reply from 2606:4700:4700::1111: time=41ms \n    Minimum = 41ms, Maximum = 41ms, Average = 41ms\n"
    assert diagnostico.leer_ping(en, enviados=1)["recibidos"] == 1


def test_un_ping_cortado_en_el_tope_no_inventa_perdida(monkeypatch):
    """Los ecos que faltan de un ping que se cortó no se perdieron: no
    salieron. Se dan los tiempos que hubo y la pérdida queda sin medir."""
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    dos = (b"Respuesta desde 1.1.1.1: bytes=32 tiempo=40ms TTL=54\r\n"
           b"Respuesta desde 1.1.1.1: bytes=32 tiempo=41ms TTL=54\r\n")

    class Cortado(Proceso):
        def communicate(self, timeout=None):
            if not self.muerto:
                raise subprocess.TimeoutExpired("x", timeout)
            return dos, b""

    def lanzar(args):
        if args[0].endswith("powershell.exe"):
            return Proceso(json.dumps(RED).encode())
        return Cortado()

    monkeypatch.setattr(diagnostico, "_lanzar", lanzar)
    d = diagnostico.red()
    uno = next(x for x in d["latencias"] if x["destino"] == "1.1.1.1")
    assert uno["recibidos"] == 2 and uno["perdidos_pct"] is None and uno["min"] == 40
    assert "1.1.1.1 (referencia): mín 40 · media 40 · máx 41 ms · pérdida sin medir (no terminó a tiempo)" \
        in diagnostico.legible(d)


def test_de_una_ip_muerta_la_nota_es_el_motivo_y_no_el_saludo():
    salida = ("\nHaciendo ping a 192.0.2.1 con 32 bytes de datos:\n"
              "Tiempo de espera agotado para esta solicitud.\nTiempo de espera agotado para esta solicitud.\n\n"
              "Estadísticas de ping para 192.0.2.1:\n    Paquetes: enviados = 2, recibidos = 0, perdidos = 2\n"
              "    (100% perdidos),\n")
    r = diagnostico.leer_ping(salida, enviados=2)
    assert r["recibidos"] == 0 and r["nota"] == "Tiempo de espera agotado para esta solicitud."


def test_la_red_mide_la_puerta_de_enlace_las_referencias_y_lo_que_usa_un_proceso(windows_falso, monkeypatch):
    con_proceso = dict(RED, proceso={
        "buscado": "juego", "procesos": [{"nombre": "Juego-Win64", "pid": 10}],
        "tcp": [{"remota": "9.9.9.9", "puerto": 443, "local": 5000, "pid": 10},
                {"remota": "149.112.112.112", "puerto": 7777, "local": 5001, "pid": 10},
                {"remota": "192.168.1.5", "puerto": 80, "local": 5002, "pid": 10},
                {"remota": "::ffff:9.9.9.9", "puerto": 443, "local": 5003, "pid": 10}],
        "udp": [{"local": "0.0.0.0", "puerto": 6000, "pid": 10}]})
    monkeypatch.setitem(RED, "proceso", con_proceso["proceso"])

    d = diagnostico.red(["ejemplo.org"], proceso="juego", trazar="1.1.1.1")

    assert [(x["destino"], x["papel"]) for x in d["latencias"]] == [
        ("192.168.1.1", "puerta de enlace"), ("1.1.1.1", "referencia"), ("8.8.8.8", "referencia"),
        ("ejemplo.org", "pedido"), ("9.9.9.9", "lo usa juego"), ("149.112.112.112", "lo usa juego")]
    assert d["puerta"] == "192.168.1.1" and d["traza"]["completa"] and len(d["traza"]["saltos"]) == 6

    texto = diagnostico.legible(d)
    assert "Ethernet — Controlador 2.5GbE, 100 Mbps" in texto
    assert "1.1.1.1 (referencia): mín <1 · media 29 · máx 45 ms · 40 % perdidos" in texto
    assert "1 conexión TCP" not in texto and "4 conexiones TCP establecidas, 1 puerto UDP abierto" in texto
    assert "   1  <1 <1 <1 ms  192.168.1.1" in texto
    assert "De UDP Windows sólo da el puerto local" in texto
    assert "Sólo lectura" in texto


# ── el tiempo ─────────────────────────────────────────────────────────────────

class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_el_diagnostico_cabe_en_el_tiempo_de_una_herramienta(monkeypatch):
    """🔴 El secretario lo llama como herramienta, y una herramienta callada
    más de `SIN_NOTICIAS_S` se mata con el turno entero. Con TODO colgado
    —PowerShell, cada ping y la traza— y esperando cada uno lo máximo que se le
    deja, el diagnóstico termina dentro de `TOPE_S`, por debajo de 60 s, y dice
    qué no terminó en vez de reventar."""
    assert diagnostico.TOPE_S + 2.5 < 60 <= motor.SIN_NOTICIAS_S
    assert diagnostico.ESPERA_PS < diagnostico.TOPE_S
    reloj = Reloj()
    monkeypatch.setattr(diagnostico, "_reloj", reloj)
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    monkeypatch.setattr(diagnostico, "_lanzar", lambda args: Proceso(cuelga=True, reloj=reloj, no_suelta=True))

    inicio = reloj.t
    d = diagnostico.red([f"198.51.100.{i}" for i in range(diagnostico.DESTINOS_MAX)], proceso="juego",
                        trazar="1.1.1.1")
    # Lo de después del tope: un segundo para leer lo que dejaron los muertos
    # y un suspiro por proceso, nunca segundos por cada uno.
    assert reloj.t - inicio <= diagnostico.TOPE_S + 2.5 < 60
    assert any("PowerShell no terminó" in f for f in d["fallos"])
    assert any("traza" in f and "no terminó" in f for f in d["fallos"])
    assert all(x["recibidos"] == 0 and x["nota"] == "no terminó a tiempo" for x in d["latencias"])

    inicio = reloj.t
    w = diagnostico.windows()
    assert reloj.t - inicio <= diagnostico.ESPERA_PS + 1.5
    assert "PowerShell no terminó" in w["fallos"][0]


# ── el secretario ──────────────────────────────────────────────────────────────

def test_el_secretario_lo_recibe_resumido_y_sabe_que_es_solo_lectura(windows_falso):
    h = herramientas.todas()["diagnosticar_pc"]
    assert h.gesto == "maquina"
    assert "SÓLO LEYENDO" in h.descripcion and "pantallazo" in h.descripcion and "ping" in h.descripcion
    assert h.esquema["properties"]["que"]["enum"] == ["windows", "red", "programas"]

    r = h.funcion(None, {"que": "windows"})
    assert isinstance(r, str) and "0x00000133" in r and len(r) < 8000
    assert h.funcion(None, {"que": "red", "trazar": "1.1.1.1; rm"})["error"].startswith("argumento no válido")
    assert "error" in h.funcion(None, {"que": "borrar"})
    assert herramientas.actividad("diagnosticar_pc", {"que": "red"})["rotulo"] == "Revisando la red de la máquina del hub"

    nombres = [x.nombre for x in herramientas.LECTURAS]
    assert nombres.index("diagnosticar_pc") == nombres.index("hub_maquina") + 1


# ── los programas (C-0237, decisión 402) ───────────────────────────────────────

PROGRAMAS = {
    "windows": {"nombre": "Microsoft Windows 10 Pro", "version": "10.0.19045", "build": "19045"},
    "gpus": [{"nombre": "Gráfica Ejemplo 7000", "controlador": "31.0.22044.1", "fecha": "2024-01-01"}],
    "programas": [
        {"nombre": "AMD Software", "version": "23.4.3", "editor": "Advanced Micro Devices, Inc.", "instalado": ""},
        # La misma, en la clave de 32 bits: se cuenta una vez.
        {"nombre": "AMD Software", "version": "23.4.3", "editor": "Advanced Micro Devices, Inc.", "instalado": ""},
        {"nombre": "Ñandú Editor", "version": "2.1", "editor": "Taller Ejemplo", "instalado": "20250301"},
        {"nombre": "Navegador", "version": "120.0", "editor": "Ejemplo SA", "instalado": "20240115"},
        # Una actualización que Windows no enseña en «Aplicaciones»: no cuenta como programa.
        {"nombre": "Actualización KB5000001", "version": "", "editor": "Taller Ejemplo", "instalado": "", "oculto": True},
    ],
    "fallos": [],
}

# Dos muestras de procesos, con la hora antes y después de su consulta. La
# primera, en frío, tarda 4 s; la segunda, 1: entre sus mitades van 6,5 s, que
# no es ni lo de antes (8) ni lo de después (5).
ES = [
    {"antes": "2026-11-10T09:59:56.0000000Z", "despues": "2026-11-10T10:00:00.0000000Z", "fallos": [], "procesos": [
        {"nombre": "atieclxx.exe", "pid": 4368, "desde": "2026-11-06T22:50:43Z", "escrito": 0, "leido": 501830},
        {"nombre": "ruidoso.exe", "pid": 10, "desde": "2026-11-10T09:59:52Z", "escrito": 1000, "leido": 0},
        {"nombre": "reciclado.exe", "pid": 20, "desde": "2026-11-10T09:59:00Z", "escrito": 500, "leido": 0}]},
    {"antes": "2026-11-10T10:00:04.0000000Z", "despues": "2026-11-10T10:00:05.0000000Z", "fallos": [], "procesos": [
        {"nombre": "atieclxx.exe", "pid": 4368, "desde": "2026-11-06T22:50:43Z", "escrito": 0, "leido": 501830},
        {"nombre": "ruidoso.exe", "pid": 10, "desde": "2026-11-10T09:59:52Z", "escrito": 1000 + 13000,
         "leido": 0},
        # El PID 20 ya es otro proceso: no se mide como si fuera el mismo.
        {"nombre": "otro.exe", "pid": 20, "desde": "2026-11-10T10:00:02Z", "escrito": 90000, "leido": 0}]},
]


@pytest.fixture
def pc_falsa(monkeypatch):
    """Windows grabado para `programas`: el guion de programas y dos muestras
    de procesos, en orden. Devuelve lo que se lanzó."""
    lanzados: list[list[str]] = []
    muestras = iter(ES)
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    monkeypatch.setattr(diagnostico, "_dormir", lambda s: None)

    def lanzar(args):
        lanzados.append(list(args))
        assert args[0].endswith("powershell.exe"), args
        datos = PROGRAMAS if "Win32_VideoController" in args[-1] else next(muestras)
        return Proceso(json.dumps(datos, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(diagnostico, "_lanzar", lanzar)
    return lanzados


def test_a_powershell_no_llega_nada_de_fuera(pc_falsa):
    """🔴 Lo que se busca se filtra en Python: los guiones que salen son los
    fijos, tal cual, digan lo que digan `buscar` y `proceso`."""
    diagnostico.programas("'; Stop-Computer; '", proceso="x'; kill 4")
    assert len(pc_falsa) == 3
    assert all(any(a[-1] is g for g in (diagnostico._PS_PROGRAMAS, diagnostico._PS_ES)) for a in pc_falsa)
    assert not any("Stop-Computer" in x or "kill" in x for a in pc_falsa for x in a)


def test_de_un_proceso_o_un_programa_nunca_salen_su_linea_de_ordenes_ni_rutas():
    """La línea de órdenes puede llevar llaves (regla dura 5) y las rutas, la
    carpeta del usuario."""
    for guion in (diagnostico._PS_PROGRAMAS, diagnostico._PS_ES):
        for campo in ("CommandLine", "ExecutablePath", "InstallLocation", "UninstallString", "Path ="):
            assert campo not in guion, campo


@pytest.mark.parametrize("buscar, nombres", [
    ("amd", ["AMD Software"]),            # una vez, aunque esté en dos claves
    ("ñandu", ["Ñandú Editor"]),           # sin tildes ni mayúsculas
    ("ejemplo sa", ["Navegador"]),         # por el editor
    ("nada así", []),
])
def test_busca_por_nombre_o_editor_sin_mayusculas_ni_tildes(pc_falsa, buscar, nombres):
    d = diagnostico.programas(buscar)
    assert [x["nombre"] for x in d["programas"]] == nombres
    assert d["total_programas"] == 3 and d["total_entradas"] == 4


def test_sin_buscar_solo_dice_cuantos_programas_hay(pc_falsa):
    d = diagnostico.programas()
    assert d["programas"] == [] and d["total_programas"] == 3
    assert "Programas instalados: 3 en Aplicaciones de Windows (4 entradas" in diagnostico.legible(d)


def test_un_componente_escondido_se_encuentra_pero_se_dice_que_lo_es(pc_falsa):
    r = diagnostico.legible(diagnostico.programas("kb5000001"))
    assert "Actualización KB5000001 (sin versión) — Taller Ejemplo (componente que Windows no enseña en Aplicaciones)" in r


def test_lo_de_ahora_sale_de_dos_muestras_con_la_hora_de_windows(pc_falsa, monkeypatch):
    """El intervalo va de la mitad de una consulta a la de la otra (6,5 s), no
    lo que tardó PowerShell en arrancar según el reloj de aquí ni la hora de
    antes de una consulta lenta (reglas duras 13 y 19)."""
    d = diagnostico.programas(proceso="atieclxx.exe")
    assert d["muestra_s"] == 6.5
    (at,) = d["proceso"]["instancias"]
    assert at["escrito"] == 0 and at["leido"] == 501830 and at["ahora_bps"] == 0 and at["media_bps"] == 0
    assert [x["nombre"] for x in d["mas_escriben"]] == ["ruidoso.exe"]
    assert d["mas_escriben"][0]["ahora_bps"] == 2000   # 13 000 B en 6,5 s


def test_la_media_es_lo_escrito_entre_lo_que_lleva_en_marcha(pc_falsa):
    """14 000 B desde las 09:59:52 hasta la mitad de la segunda consulta
    (10:00:04,5): 12,5 s."""
    (r,) = diagnostico.programas(proceso="ruidoso")["proceso"]["instancias"]
    assert r["media_bps"] == 1120


def test_un_pid_reutilizado_no_se_mide_como_el_mismo(pc_falsa):
    d = diagnostico.programas(proceso="otro")
    (otro,) = d["proceso"]["instancias"]
    assert otro["ahora_bps"] is None and otro["nuevo"]
    assert "otro.exe" not in [x["nombre"] for x in d["mas_escriben"]]
    assert "ahora sin medir (arrancó entre las dos muestras)" in diagnostico.legible(d)


def test_con_muchos_del_mismo_nombre_dice_cuantos_hay_de_verdad(monkeypatch):
    """35 chrome.exe no son «20 en marcha» porque se enseñen 20 (regla dura 13)."""
    muchos = [{"nombre": "chrome.exe", "pid": 100 + i, "desde": "2026-11-10T09:00:00Z", "escrito": 0, "leido": 0}
              for i in range(35)]
    m = [{"antes": "2026-11-10T10:00:00Z", "despues": "2026-11-10T10:00:00Z", "procesos": muchos},
         {"antes": "2026-11-10T10:00:05Z", "despues": "2026-11-10T10:00:05Z", "procesos": muchos}]
    d = diagnostico.leer_programas(PROGRAMAS, m, proceso="chrome")
    assert d["proceso"]["en_marcha"] == 35 and len(d["proceso"]["instancias"]) == diagnostico.INSTANCIAS_MAX
    r = diagnostico.legible(d | {"que": "programas"})
    assert "Proceso «chrome» (35 en marcha)" in r and "… y 15 más con ese nombre" in r


def test_si_la_primera_muestra_no_vuelve_lo_de_ahora_sale_sin_medir(monkeypatch):
    reloj = Reloj()
    monkeypatch.setattr(diagnostico, "_reloj", reloj)
    monkeypatch.setattr(diagnostico, "_dormir", lambda s: pytest.fail("esperó sin primera muestra"))
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    lanzados = []

    def lanzar(args):
        lanzados.append(args)
        if "Win32_VideoController" in args[-1]:
            return Proceso(json.dumps(PROGRAMAS).encode("utf-8"))
        return Proceso(cuelga=True, reloj=reloj)

    monkeypatch.setattr(diagnostico, "_lanzar", lanzar)
    d = diagnostico.programas("amd", proceso="atieclxx")
    assert len(lanzados) == 2 and d["muestra_s"] is None and d["mas_escriben"] == []
    assert [x["nombre"] for x in d["programas"]] == ["AMD Software"]
    assert d["proceso"]["instancias"] == [] and any("PowerShell no terminó" in f for f in d["fallos"])


def test_los_programas_tambien_caben_en_el_tiempo_de_una_herramienta(monkeypatch):
    reloj = Reloj()
    monkeypatch.setattr(diagnostico, "_reloj", reloj)
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    monkeypatch.setattr(diagnostico, "_lanzar", lambda args: Proceso(cuelga=True, reloj=reloj, no_suelta=True))
    inicio = reloj.t
    d = diagnostico.programas("amd", proceso="x")
    assert reloj.t - inicio <= diagnostico.TOPE_S + 2.5 < 60
    assert d["programas"] == [] and d["muestra_s"] is None


def test_con_la_primera_muestra_lenta_y_la_segunda_colgada_tambien_cabe(monkeypatch):
    """El peor caso que sí llega a esperar: la primera muestra vuelve casi en
    su plazo, se espera `MUESTRA_S` y la segunda no vuelve nunca."""
    reloj = Reloj()
    monkeypatch.setattr(diagnostico, "_reloj", reloj)
    monkeypatch.setattr(diagnostico, "_dormir", lambda s: setattr(reloj, "t", reloj.t + s))
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: f"/mnt/c/falso/{nombre}")
    muestras = iter([ES[0]])

    class Lenta(Proceso):
        def communicate(self, timeout=None):
            reloj.t += diagnostico.ESPERA_PS - 1
            return super().communicate(timeout)

    def lanzar(args):
        if "Win32_VideoController" in args[-1]:
            return Proceso(json.dumps(PROGRAMAS).encode("utf-8"))
        siguiente = next(muestras, None)
        if siguiente is None:
            return Proceso(cuelga=True, reloj=reloj, no_suelta=True)
        return Lenta(json.dumps(siguiente).encode("utf-8"))

    monkeypatch.setattr(diagnostico, "_lanzar", lanzar)
    inicio = reloj.t
    d = diagnostico.programas("amd", proceso="atieclxx")
    assert reloj.t - inicio <= diagnostico.TOPE_S + 2.5 < 60
    assert d["muestra_s"] is None and [x["nombre"] for x in d["programas"]] == ["AMD Software"]
    assert any("segunda muestra" in f for f in d["fallos"])


def test_el_resumen_separa_el_controlador_del_programa_y_dice_que_es_un_techo(pc_falsa):
    r = diagnostico.legible(diagnostico.programas("amd", proceso="atieclxx"))
    assert "Microsoft Windows 10 Pro 10.0.19045 (build 19045)" in r
    assert "Gráfica Ejemplo 7000 — controlador 31.0.22044.1 del 2024-01-01" in r
    assert "no es la del programa del fabricante" in r
    assert "AMD Software 23.4.3 — Advanced Micro Devices, Inc." in r
    assert "0 B escritos" in r and "ahora 0 B/s (medido 6.5 s)" in r
    assert "ruidoso.exe (pid 10): 2.0 KB/s" in r
    assert "lo que el proceso pide leer y escribir" in r and "no lo que llega al SSD" in r


def test_el_secretario_pregunta_por_un_programa_y_lo_que_escribe(pc_falsa):
    """Lo que no pudo hacer: ver qué versión de Adrenalin hay y si su proceso
    escribe sin parar."""
    h = herramientas.todas()["diagnosticar_pc"]
    assert "AMD Software" in h.descripcion and "buscar" in h.esquema["properties"]
    r = h.funcion(None, {"que": "programas", "buscar": "amd", "proceso": "atieclxx"})
    assert isinstance(r, str) and "AMD Software 23.4.3" in r and "atieclxx.exe (pid 4368" in r
    assert h.funcion(None, {"que": "programas", "buscar": "x" * 200})["error"].startswith("argumento no válido")
    assert herramientas.actividad("diagnosticar_pc", {"que": "programas"})["rotulo"] == \
        "Revisando los programas de la máquina del hub"


def test_la_cli_tambien_mira_los_programas(pc_falsa, capsys):
    assert diagnostico.main(["programas", "--buscar", "amd"]) == 0
    assert "AMD Software 23.4.3" in capsys.readouterr().out
