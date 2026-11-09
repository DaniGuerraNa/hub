"""El llavero: dónde vive cada llave y si está en Bitwarden, sin abrir nunca una (decisión 346, C-0143)."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import llavero, web

SECRETO = "VALOR-QUE-NUNCA-SE-LEE"
ORIGEN = {"origin": "http://127.0.0.1:8787"}


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Un HOME con llaves de mentira: declaradas, sueltas, ssh y una sesión."""
    monkeypatch.setenv("HOME", str(tmp_path))
    s = tmp_path / ".secretos"
    s.mkdir()
    (s / "telegram.env").write_text(f"TELEGRAM_BOT_TOKEN={SECRETO}\n")
    (s / "telegram.env").chmod(0o600)
    (s / "suelta.txt").write_text(SECRETO)
    (s / "suelta.txt").chmod(0o644)
    tg = s / "secretario-telegram"
    tg.mkdir()
    (tg / "api.env").write_text(f"TG_API_HASH={SECRETO}\n")
    (tg / "dueno.session").write_text(SECRETO)
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "id_prueba").write_text(SECRETO)
    (ssh / "id_prueba.pub").write_text("ssh-ed25519 AAAA")
    (ssh / "config").write_text("Host x")
    yml = tmp_path / "canal.yml"
    yml.write_text(f"token_ref: '{s / 'telegram.env'}#TELEGRAM_BOT_TOKEN'\n")
    monkeypatch.setenv("HUB_CANAL_YML", str(yml))
    from hub.secretario.fuentes import telegram as tg_mod
    monkeypatch.setattr(tg_mod, "POR_OMISION", tg)
    return tmp_path


def _por_nombre():
    return {f["nombre"]: f for f in llavero.inventario()}


def test_cada_llave_con_su_sitio_las_sueltas_y_las_ssh_sin_abrir_ninguna(casa, monkeypatch):
    leidos = []
    real = Path.read_text

    def espia(self, *a, **k):
        leidos.append(str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", espia)
    filas = _por_nombre()
    assert filas["telegram-canal"]["estado"] == "en disco" and filas["telegram-canal"]["clave"] == "TELEGRAM_BOT_TOKEN"
    assert filas["secretario-telegram"]["estado"] == "carpeta"
    assert filas["suelta:suelta.txt"]["estado"].startswith("⚠"), "644 en .secretos se dice"
    assert "ssh:id_prueba" in filas and not any(n.startswith("ssh:config") for n in filas)
    assert filas["secretario-whatsapp"]["sesion"] is True
    assert "suelta:telegram.env" not in filas, "la declarada no sale también como suelta"
    assert not [r for r in leidos if ".secretos" in r or ".ssh" in r], f"abrió: {leidos}"


def test_la_pantalla_las_ensena_sin_el_valor_y_marcar_es_la_unica_escritura(casa):
    cliente = TestClient(web.app)
    html = cliente.get("/conexiones").text
    assert "Llaves de esta máquina" in html and "telegram-canal" in html and SECRETO not in html
    assert "sólo en esta máquina" in html
    r = cliente.post("/conexiones/llave", data={"nombre": "telegram-canal"}, headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303
    assert _por_nombre()["telegram-canal"]["bitwarden"] == "bw://hub/telegram-canal"
    assert "marcada en Bitwarden" in cliente.get("/conexiones").text
    cliente.post("/conexiones/llave", data={"nombre": "telegram-canal", "que": "desmarcar"}, headers=ORIGEN)
    assert not _por_nombre()["telegram-canal"]["bitwarden"]
    r = cliente.post("/conexiones/llave", data={"nombre": "inventada"}, headers=ORIGEN, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert SECRETO not in (llavero._marcas_yml().read_text())


def test_encolar_deja_la_llave_en_600_y_el_inventario_no_lee_su_valor(casa, monkeypatch):
    destino = llavero.encolar("encargo-tienda", "la contraseña del sistema de la tienda", valor=SECRETO)
    assert stat.S_IMODE(destino.stat().st_mode) == 0o600
    assert stat.S_IMODE(destino.parent.stat().st_mode) == 0o700
    leidos = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: leidos.append(self.name) or real(self, *a, **k))
    fila = _por_nombre()["cola:encargo-tienda"]
    assert fila["para"] == "la contraseña del sistema de la tienda" and fila["en_cola"]
    assert "encargo-tienda.json" not in leidos
    with pytest.raises(ValueError):
        llavero.encolar("Nombre Raro", "x", valor="v")
    with pytest.raises(ValueError):
        llavero.encolar("doble", "x", valor="v", ruta=str(destino))


def test_subir_no_corre_sin_terminal_ni_sin_la_caja_abierta(casa, monkeypatch):
    with pytest.raises(llavero.NoDesdeAqui, match="terminal"):
        llavero.subir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("BW_SESSION", raising=False)
    with pytest.raises(llavero.NoDesdeAqui, match="BW_SESSION"):
        llavero.subir()


def test_subir_pasa_el_valor_por_la_entrada_estandar_salta_sesiones_y_vacia_la_cola(casa, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("BW_SESSION", "sesion-de-prueba")
    llavero.encolar("encargo-tienda", "contraseña de la tienda", valor="nueva-clave")
    llamadas = []

    def bw(args, entrada=""):
        llamadas.append((args, entrada))
        if args[:2] == ["list", "folders"]:
            return json.dumps([{"id": "f1", "name": "hub"}])
        if args[:2] == ["list", "items"]:
            return json.dumps([{"name": "hub/ssh:id_prueba"}])   # ya estaba: no se pisa
        return json.dumps({"id": "nuevo"})

    monkeypatch.setattr(llavero, "_bw", bw)
    dicho = []
    assert llavero.subir(salida=dicho.append, confirmar=lambda: False) == 0
    assert not any(a[:2] == ["create", "item"] for a, _ in llamadas), "sin su sí no sube nada"
    assert any("hub/telegram-canal" in d for d in dicho), "enseña lo que va a subir antes de preguntar"
    llavero.subir(salida=dicho.append, confirmar=lambda: True)
    assert not any(SECRETO in d or "nueva-clave" in d for d in dicho), "por pantalla sólo títulos"
    creados = {}
    for args, entrada in llamadas:
        assert SECRETO not in " ".join(args) and "nueva-clave" not in " ".join(args), "nunca en argumentos"
        if args[:2] == ["create", "item"]:
            item = json.loads(base64.b64decode(entrada))
            creados[item["name"]] = item["notes"]
    assert creados["hub/telegram-canal"].startswith("TELEGRAM_BOT_TOKEN=")
    assert "hub/secretario-telegram/api.env" in creados
    assert not any("session" in n for n in creados), "las sesiones no se suben"
    assert "hub/ssh:id_prueba" not in creados
    assert creados["hub/encargo-tienda"] == "nueva-clave"
    filas = _por_nombre()
    assert "cola:encargo-tienda" not in filas, "la cola se vacía al subir"
    assert filas["telegram-canal"]["bitwarden"] == "bw://hub/telegram-canal"
    assert not filas["secretario-whatsapp"]["bitwarden"]


def test_solo_se_encola_lo_que_ya_es_una_llave_y_no_dos_veces(casa, tmp_path):
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    with pytest.raises(ValueError, match="sólo se encolan"):
        llavero.encolar("todo", "x", ruta=str(proyecto))
    with pytest.raises(ValueError, match="sólo se encolan"):
        llavero.encolar("casa", "x", ruta=str(tmp_path))
    with pytest.raises(ValueError, match="ya está en el inventario"):
        llavero.encolar("otra-vez", "x", ruta=str(tmp_path / ".secretos" / "telegram.env"))


def test_un_archivo_que_no_es_texto_no_se_sube_estropeado_ni_se_marca(casa, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("BW_SESSION", "s")
    (tmp := casa / ".secretos" / "binaria.p12").write_bytes(b"\xff\xfe\x00\x81")
    monkeypatch.setattr(llavero, "_bw", lambda args, entrada="": json.dumps(
        [{"id": "f1", "name": "hub"}] if args[:2] == ["list", "folders"] else [] if args[0] == "list" else {"id": "n"}))
    dicho = []
    llavero.subir(["suelta:binaria.p12"], salida=dicho.append, confirmar=lambda: True)
    assert any("no es texto" in d for d in dicho)
    assert not _por_nombre()["suelta:binaria.p12"]["bitwarden"]
