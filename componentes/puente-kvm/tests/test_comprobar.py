"""`puente-kvm comprobar` dice qué falta y cómo arreglarlo; `diagnostico` no lleva secretos.

Todo contra carpetas, archivos y puertos de la prueba: nunca el puente ni la
contraseña de verdad de este equipo.
"""

import asyncio
import contextlib
import json
import os
import socket
import subprocess
from pathlib import Path
import threading
import time

import httpx
import pytest
import uvicorn

from puente_kvm import comprobar, config, lecturas, simulador, terminal
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

from .jetkvm_falso import JetKVMFalso


@pytest.fixture
def programas(tmp_path, monkeypatch):
    """Un PATH de mentira: sólo lo que la prueba pone en él."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()

    def poner(*nombres):
        for n in nombres:
            f = bin_ / n
            # claude dice su versión como el de verdad; los demás, cualquier cosa.
            texto = "2.1.322 (Claude Code)" if n == "claude" else f"{n} 1.0"
            f.write_text(f"#!/bin/sh\necho '{texto}'\n")
            f.chmod(0o755)
    # El PATH del puente y las carpetas del sistema, de mentira: en este equipo
    # hay más de un claude de verdad, y la prueba no puede depender de ellos.
    monkeypatch.setattr(terminal, "_path_de_usuario", lambda: str(bin_))
    monkeypatch.setattr(comprobar, "SISTEMA", ())
    return poner


def entorno(texto: str, modo: int = 0o600):
    ruta = config.entorno()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto)
    ruta.chmod(modo)
    return ruta


def por_que(lista, que):
    return [p for p in lista if p.que == que]


def test_dice_que_programas_faltan_y_como_instalarlos(programas, capsys):
    programas("uv", "curl")
    assert comprobar.comprobar(["--sin-entrar"]) == 1
    salida = capsys.readouterr().out
    assert "✔ uv: uv 1.0" in salida
    assert "✘ tmux: no está en el PATH" in salida and "apt install tmux" in salida
    assert "✘ claude: el puente no encuentra Claude Code" in salida


def test_con_todo_instalado_y_el_simulador_no_falta_nada_imprescindible(programas, capsys):
    programas("uv", "tmux", "claude", "curl")
    entorno("JETKVM_CLAVE=\n")
    assert comprobar.comprobar(["--sin-entrar"]) == 0, capsys.readouterr().out


def test_el_archivo_de_la_clave_legible_por_otros_es_un_fallo_y_la_clave_no_se_ensena(programas, capsys):
    programas("uv", "tmux", "claude", "curl")
    entorno("JETKVM_CLAVE=superclave-123\n", 0o644)
    assert comprobar.comprobar(["--sin-entrar"]) == 1
    salida = capsys.readouterr().out
    assert "permisos 644" in salida and "chmod 600" in salida
    assert "superclave" not in salida


def test_un_puerto_ocupado_por_otro_programa_se_dice():
    with socket.socket() as s:
        s.bind(("127.0.0.1", config.PUERTO))
        s.listen()
        p = comprobar._servicio(comprobar._preguntar_al_puente(timeout=0.5))
    assert p[0].estado == comprobar.FALTA and "otro programa" in p[0].detalle


@contextlib.contextmanager
def puente_en_marcha():
    servidor = uvicorn.Server(uvicorn.Config(
        crear_app(Simulador(lineas=["x"]), hosts={f"127.0.0.1:{config.PUERTO}"}),
        host="127.0.0.1", port=config.PUERTO, log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        with contextlib.suppress(httpx.HTTPError):
            httpx.get(f"http://127.0.0.1:{config.PUERTO}/api/estado", timeout=1)
            break
        time.sleep(0.1)
    try:
        yield
    finally:
        servidor.should_exit = True
        hilo.join(5)


def test_con_el_puente_en_marcha_dice_su_version():
    with puente_en_marcha():
        p = comprobar._servicio(comprobar._preguntar_al_puente())
    assert p[0].estado == comprobar.BIEN and config.VERSION in p[0].detalle


@pytest.mark.parametrize("version, estado", [("0.5.11", comprobar.BIEN), ("0.6.0", comprobar.OJO)])
def test_el_jetkvm_dice_su_firmware_y_se_avisa_si_no_esta_contrastado(version, estado, monkeypatch):
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]), version=version)
        url = await falso.arrancar()
        try:
            return await comprobar._sondear_jetkvm(url, "secreta", entrar=True)
        finally:
            await falso.parar()
    puntos, firmware = asyncio.run(prueba())
    assert firmware == version
    assert por_que(puntos, "firmware")[0].estado == estado


def test_un_jetkvm_que_no_responde_dice_que_mirar():
    puntos, _ = asyncio.run(comprobar._sondear_jetkvm("http://127.0.0.1:1", "", entrar=True))
    assert puntos[0].estado == comprobar.FALTA and "misma red" in puntos[0].arreglo


def test_el_simulador_arranca_aunque_falte_su_fuente(monkeypatch):
    monkeypatch.setattr(simulador, "FUENTE_MONO", None)
    monkeypatch.setattr(simulador, "FUENTE_UI", None)
    sim = Simulador(lineas=["SELECT 1;"])
    assert asyncio.run(sim.captura()).size == (1920, 1080)
    # El metapaquete: `fonts-dejavu-mono` no existe en Ubuntu 22.04 y apt no instalaría nada.
    assert "sudo apt install fonts-dejavu)" in sim.estado()["nota"]


def test_el_diagnostico_no_lleva_secretos_ni_contenido_del_trabajo(programas, monkeypatch):
    programas("uv", "tmux", "claude", "curl")
    entorno("JETKVM_CLAVE=superclave-123\n")
    monkeypatch.setenv("JETKVM_CLAVE", "superclave-123")
    l = lecturas.nueva("usp_Confidencial")
    hogar = config.hogar()
    entradas = [
        {"n": 1, "t": 1, "tipo": "lectura", "detalle": "empiezo a capturar «usp_Confidencial»", "quien": "claude",
         "lectura": l.id},
        {"n": 2, "t": 31, "tipo": "lectura", "detalle": "«usp_Confidencial»: 12 páginas", "quien": "claude",
         "lectura": l.id},
        {"n": 3, "t": 40, "tipo": "teclear", "detalle": "16 caracteres: 'SELECT secretito'", "quien": "claude"},
        {"n": 4, "t": 41, "tipo": "error", "detalle": "TextoIntraducible: no sé teclear estos caracteres: '✓'",
         "quien": "claude"},
        {"n": 5, "t": 42, "tipo": "comprobacion", "detalle": "cambio-confidencial-a1b2c3: las páginas 1–3 son "
         "las leídas (0.6 s)", "quien": "claude"},
    ]
    (hogar / "bitacora.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entradas))
    texto = comprobar.informe()
    for prohibido in ("superclave", "secretito", "Confidencial", "confidencial", "✓"):
        assert prohibido not in texto, prohibido
    if str(os.path.expanduser("~")) != "/":
        assert os.path.expanduser("~") + "/" not in texto
    assert config.VERSION in texto
    assert "12 páginas en 30.0 s" in texto
    assert "las páginas 1–3 son las leídas (0.6 s)" in texto
    assert "TextoIntraducible" in texto


def repo(ruta):
    ruta.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(ruta)], check=True)
    return ruta


@pytest.mark.parametrize("systemd, dentro, esperada", [
    (True, False, "bash scripts/servicio.sh instalar"),
    (False, False, "bash scripts/arrancar.sh"),
    (True, True, 'PUENTE_TRABAJO="$HOME/puente-trabajo" bash scripts/servicio.sh instalar'),
    (False, True, 'PUENTE_TRABAJO="$HOME/puente-trabajo" bash scripts/arrancar.sh'),
])
def test_la_orden_que_se_sugiere_depende_de_systemd_y_de_si_el_codigo_esta_en_otro_repositorio(
        monkeypatch, systemd, dentro, esperada):
    monkeypatch.delenv("PUENTE_TRABAJO", raising=False)
    monkeypatch.setattr(comprobar, "hay_systemd", lambda: systemd)
    monkeypatch.setattr(comprobar, "otro_repositorio", lambda r: Path("/repo") if dentro else None)
    assert comprobar.orden_arrancar() == esperada
    assert esperada in comprobar._servicio(None)[0].arreglo


def test_con_puente_trabajo_puesto_no_se_sugiere_otro(monkeypatch, tmp_path):
    monkeypatch.setenv("PUENTE_TRABAJO", str(tmp_path / "fuera"))
    monkeypatch.setattr(comprobar, "hay_systemd", lambda: True)
    monkeypatch.setattr(comprobar, "otro_repositorio", lambda r: Path("/repo"))
    assert comprobar.orden_arrancar() == "bash scripts/servicio.sh instalar"


def test_otro_repositorio_se_ve_desde_dentro_y_no_desde_fuera(tmp_path):
    de_fuera = repo(tmp_path / "proyecto")
    (de_fuera / "componentes" / "puente-kvm").mkdir(parents=True)
    assert comprobar.otro_repositorio(de_fuera / "componentes" / "puente-kvm") == de_fuera.resolve()
    (tmp_path / "suelto").mkdir()
    assert comprobar.otro_repositorio(tmp_path / "suelto") is None


def test_el_espacio_de_trabajo_es_el_del_puente_en_marcha_no_el_de_la_shell(tmp_path):
    esp = tmp_path / "puente-trabajo"
    (esp / "trabajo").mkdir(parents=True)
    (esp / "trabajo" / "entorno.md").write_text("medido")
    p = por_que(comprobar._espacio({"espacio": str(esp)}), "espacio de trabajo de Claude")[0]
    assert p.estado == comprobar.BIEN and str(esp) in p.detalle and "en marcha" in p.detalle
    assert "entorno.md" in p.detalle


def test_un_espacio_de_trabajo_dentro_de_otro_repositorio_es_un_aviso(tmp_path):
    esp = repo(tmp_path / "otro") / "componentes" / "puente-kvm"
    (esp / "trabajo").mkdir(parents=True)
    p = por_que(comprobar._espacio({"espacio": str(esp)}), "espacio de trabajo de Claude")[0]
    assert p.estado == comprobar.OJO and "otro repositorio" in p.detalle and "PUENTE_TRABAJO" in p.arreglo


def test_el_estado_del_puente_dice_su_espacio_de_trabajo():
    with puente_en_marcha():
        e = comprobar._preguntar_al_puente()
    assert e["espacio"] == str(config.espacio()) and e["codigo"] == str(config.CODIGO)


def claude_en(carpeta, version):
    carpeta.mkdir(parents=True, exist_ok=True)
    f = carpeta / "claude"
    f.write_text(f"#!/bin/sh\necho '{version} (Claude Code)'\n")
    f.chmod(0o755)
    return f


def test_comprobar_dice_que_claude_abre_el_puente_y_avisa_si_hay_varios_distintos(monkeypatch, tmp_path):
    # Lo que pasó: un /usr/bin/claude viejo y el de la persona, al día.
    propio = claude_en(tmp_path / "casa" / ".npm-global" / "bin", "2.1.322")
    viejo = claude_en(tmp_path / "usr-bin", "2.1.112")
    monkeypatch.setattr(terminal, "_path_de_usuario", lambda: f"{propio.parent}:{viejo.parent}")
    monkeypatch.setattr(comprobar, "SISTEMA", ())
    puntos = comprobar._claude(None, "claude-fable-5-2")
    usado = por_que(puntos, "claude")[0]
    assert usado.estado == comprobar.BIEN and "2.1.322" in usado.detalle and str(propio) in usado.detalle
    varios = por_que(puntos, "varios Claude Code")[0]
    assert varios.estado == comprobar.OJO and "2.1.112" in varios.detalle and str(viejo) in varios.detalle
    assert por_que(puntos, "modelo de Claude")[0].estado == comprobar.BIEN


def test_con_el_puente_en_marcha_cuenta_el_claude_que_abre_el_servicio(monkeypatch, tmp_path):
    viejo = claude_en(tmp_path / "usr-bin", "2.1.112")
    monkeypatch.setattr(terminal, "_path_de_usuario", lambda: str(viejo.parent))
    monkeypatch.setattr(comprobar, "SISTEMA", ())
    estado = {"claude_code": {"ruta": str(viejo), "version": "2.1.112"}}
    puntos = comprobar._claude(estado, "claude-fable-5-2")
    assert "en marcha" in por_que(puntos, "claude")[0].detalle
    modelo = por_que(puntos, "modelo de Claude")[0]
    assert modelo.estado == comprobar.OJO and "2.1.112" in modelo.detalle
