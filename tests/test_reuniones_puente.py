"""Reuniones del Mac grabadas por el Puente KVM (decisión 443, C-0461).

El puente las deja en su carpeta (`PUENTE_HOME/reuniones/<id>-kvm/`) con el
contrato de siempre, y el hub las enseña junto a las del agente de Windows y
lanza su procesado desde el ciclo lento, sin preguntarle nada al puente (438).
Apagada la herramienta, para el hub no existen."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import db, opcionales, procesos, reuniones, web

KVM = "20261120-093000-kvm"


@pytest.fixture
def carpetas(tmp_path, monkeypatch):
    """La del agente y la del puente, las dos en el temporal."""
    agente = tmp_path / "grabaciones"
    agente.mkdir()
    monkeypatch.setenv("REUNIONES_RAIZ", str(agente))
    monkeypatch.setenv("PUENTE_HOME", str(tmp_path / "puente"))
    puente = tmp_path / "puente" / "reuniones"
    puente.mkdir(parents=True)
    return agente, puente


@pytest.fixture
def encendida():
    opcionales.poner("puente-kvm", True)


@pytest.fixture
def lanzados(monkeypatch):
    """`procesos.desasir` de mentira: apunta la orden y su `REUNIONES_RAIZ`,
    y devuelve un proceso vivo de verdad para que su huella exista."""
    vistos = []
    vivos = []

    def desasir(orden, **kw):
        vistos.append({"orden": orden[orden.index("reuniones") + 1:], "raiz": kw["env"]["REUNIONES_RAIZ"]})
        p = subprocess.Popen(["sleep", "30"])
        vivos.append(p)
        return p

    monkeypatch.setattr(procesos, "desasir", desasir)
    yield vistos
    for p in vivos:
        p.kill()
        p.wait()


def _reunion(raiz, id_, fin=600, **meta):
    d = raiz / id_
    (d / "fotos").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": id_, "inicio": 0, **({"fin": fin} if fin else {}), **meta}))
    (d / "reunion.wav").write_bytes(b"\0" * 1000)
    return d


# ── de qué carpeta es cada id ──


def test_un_id_kvm_vive_en_la_carpeta_del_puente_solo_con_la_herramienta_encendida(carpetas):
    agente, puente = carpetas
    _reunion(puente, KVM)
    _reunion(agente, "20261120-090000")
    with pytest.raises(ValueError, match="no existe"):
        reuniones.carpeta_de(KVM)
    assert reuniones.raices() == [agente]
    opcionales.poner("puente-kvm", True)
    assert reuniones.carpeta_de(KVM) == puente / KVM
    assert reuniones.carpeta_de("20261120-090000") == agente / "20261120-090000"
    assert reuniones.raices() == [agente, puente]


def test_un_id_con_otro_sufijo_o_una_kvm_en_la_carpeta_del_agente_no_valen(carpetas, encendida):
    agente, _ = carpetas
    _reunion(agente, "20261120-110000-kvm")
    for malo in ("20261120-093000-mac", "20261120-093000-kvm/..", "../" + KVM):
        with pytest.raises(ValueError, match="no válida"):
            reuniones.carpeta_de(malo)
    with pytest.raises(ValueError, match="no existe"):
        reuniones.carpeta_de("20261120-110000-kvm")
    assert reuniones.lista() == [], "una -kvm donde no le toca no se enseña: luego no se podría abrir"


def test_sin_la_carpeta_del_puente_la_raiz_es_solo_la_del_agente(tmp_path, carpetas, encendida, monkeypatch):
    agente, _ = carpetas
    monkeypatch.setenv("PUENTE_HOME", str(tmp_path / "otro-que-no-existe"))
    assert reuniones.raices() == [agente]
    assert reuniones.raiz_puente() == tmp_path / "otro-que-no-existe" / "reuniones"
    assert not reuniones.raiz_puente().exists(), "el hub no crea la carpeta del puente"


def test_la_lista_mezcla_las_dos_carpetas_de_la_mas_nueva_a_la_mas_vieja(carpetas, encendida):
    agente, puente = carpetas
    _reunion(agente, "20261119-180000")
    _reunion(puente, KVM, proceso={"nombre": "Mac (JetKVM)"})
    _reunion(agente, "20261120-120000")
    _reunion(puente, "20261118-100000-kvm", fin=None)
    lista = reuniones.lista()
    assert [x["id"] for x in lista] == ["20261120-120000", KVM, "20261119-180000", "20261118-100000-kvm"]
    por_id = {x["id"]: x for x in lista}
    assert por_id[KVM]["app"] == "Mac (JetKVM)" and por_id[KVM]["estado"] == "sin procesar"
    assert por_id["20261118-100000-kvm"]["estado"] == "grabando"


def test_apagada_la_herramienta_la_lista_no_ensena_las_del_puente(carpetas):
    agente, puente = carpetas
    _reunion(agente, "20261119-180000")
    _reunion(puente, KVM)
    assert [x["id"] for x in reuniones.lista()] == ["20261119-180000"]


# ── el procesado solo, desde el ciclo lento ──


def test_procesar_pendientes_lanza_la_terminada_sin_procesar_mas_antigua(carpetas, encendida, lanzados):
    _, puente = carpetas
    _reunion(puente, "20261120-150000-kvm")
    _reunion(puente, KVM)
    hecha = _reunion(puente, "20261120-080000-kvm")
    (hecha / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    assert reuniones.procesar_pendientes() == KVM
    assert lanzados == [{"orden": ["procesar", KVM], "raiz": str(puente)}]


def test_procesar_pendientes_no_lanza_la_que_aun_no_tiene_fin(carpetas, encendida, lanzados):
    _, puente = carpetas
    _reunion(puente, KVM, fin=None)
    assert reuniones.procesar_pendientes() is None
    assert lanzados == []


def test_procesar_pendientes_no_lanza_con_otro_procesado_en_marcha(carpetas, encendida, lanzados):
    agente, puente = carpetas
    otra = _reunion(agente, "20261120-090000")
    (otra / "procesado.json").write_text(json.dumps({"estado": "procesando"}))
    _reunion(puente, KVM)
    assert reuniones.procesar_pendientes() is None, "un solo Whisper en la GPU"
    assert lanzados == []
    (otra / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    assert reuniones.procesar_pendientes() == KVM


def test_procesar_pendientes_no_lanza_dos_veces_ni_otra_mientras_arranca_la_primera(carpetas, encendida, lanzados):
    """Entre lanzar y que `reuniones procesar` escriba su «procesando» pasa un
    rato (`uv run` arrancando): ni se relanza la misma ni entra otra encima."""
    _, puente = carpetas
    _reunion(puente, KVM)
    assert reuniones.procesar_pendientes() == KVM
    assert reuniones.procesar_pendientes() is None
    _reunion(puente, "20261120-170000-kvm")
    assert reuniones.procesar_pendientes() is None, "la primera sigue viva"
    assert [v["orden"] for v in lanzados] == [["procesar", KVM]]


def test_procesar_pendientes_apagada_la_herramienta_no_hace_nada(carpetas, lanzados):
    _, puente = carpetas
    _reunion(puente, KVM)
    assert reuniones.procesar_pendientes() is None
    assert lanzados == []


def test_el_ciclo_lento_procesa_las_del_puente_en_su_propio_paso(con, carpetas, encendida, lanzados, monkeypatch):
    from hub import busqueda, consumo, copia_base, intercambio, maquina, repos, servicios, snapshotter, transcribir
    from hub import version as _version
    monkeypatch.setattr(snapshotter.registry, "cargar", lambda: [])
    for modulo, nombre in ((repos, "escanear"), (servicios, "escanear"), (busqueda, "reindexar"),
                           (consumo, "escanear"), (maquina, "escanear"), (copia_base, "hacer")):
        monkeypatch.setattr(modulo, nombre, lambda *a, **k: 0)
    monkeypatch.setattr(_version, "buscar_remota", lambda: None)
    monkeypatch.setattr(intercambio, "podar_de_paso", lambda: [])
    monkeypatch.setattr(transcribir, "podar_dictados", lambda: 0)
    _, puente = carpetas
    _reunion(puente, KVM)
    fallos = {}
    resultado = snapshotter.ciclo_lento(
        con, al_paso=lambda clave, duro=None, fallo=None: fallos.update({clave: fallo}) if fallo else None)
    assert resultado["reuniones"] == KVM and fallos == {}
    monkeypatch.setattr(reuniones, "procesar_pendientes", lambda: 1 / 0)
    resultado = snapshotter.ciclo_lento(
        con, al_paso=lambda clave, duro=None, fallo=None: fallos.update({clave: fallo}) if fallo else None)
    assert "ZeroDivisionError" in fallos["reuniones"] and resultado["dictados"] == 0, "en su propio try"


# ── cada orden, con la carpeta de su reunión ──


def test_lanzar_pasa_la_raiz_de_cada_reunion(carpetas, encendida, lanzados):
    agente, puente = carpetas
    for d in (_reunion(agente, "20261120-090000"), _reunion(puente, KVM)):
        (d / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    reuniones.lanzar_procesado("20261120-090000")
    reuniones.lanzar_voces(KVM)
    reuniones.lanzar_nombres(KVM, {"Persona 1": "Ana"}, resumen=False)
    assert [(v["orden"][0], v["raiz"]) for v in lanzados] == [
        ("procesar", str(agente)), ("voces", str(puente)), ("nombres", str(puente))]


def test_comprimir_de_las_dos_carpetas_lanza_una_orden_por_carpeta(carpetas, encendida, lanzados):
    agente, puente = carpetas
    _reunion(agente, "20261120-090000")
    _reunion(agente, "20261120-100000")
    _reunion(puente, KVM)
    reuniones.lanzar_compresion(reuniones.sin_comprimir())
    ordenes = sorted((v["raiz"], v["orden"][0], tuple(sorted(v["orden"][1:]))) for v in lanzados)
    assert ordenes == sorted([(str(agente), "comprimir", ("20261120-090000", "20261120-100000")),
                              (str(puente), "comprimir", (KVM,))])


def test_un_id_kvm_con_la_herramienta_apagada_no_se_lanza(carpetas, lanzados):
    _, puente = carpetas
    _reunion(puente, KVM)
    with pytest.raises(ValueError, match="no existe"):
        reuniones.lanzar_procesado(KVM)
    assert lanzados == []


# ── la pantalla ──


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def test_una_del_puente_sin_procesar_dice_que_se_procesa_sola_y_conserva_el_boton(carpetas, encendida, cliente):
    _, puente = carpetas
    _reunion(puente, KVM, proceso={"nombre": "Mac (JetKVM)"})
    html = cliente.get(f"/reuniones/{KVM}").text
    assert "se procesa sola en unos minutos" in html and 'value="procesar"' in html
    assert "Mac (JetKVM)" in html
    assert KVM in cliente.get("/reuniones").text


def test_una_del_agente_sin_procesar_no_promete_que_se_procese_sola(carpetas, cliente):
    agente, _ = carpetas
    _reunion(agente, "20261120-090000")
    html = cliente.get("/reuniones/20261120-090000").text
    assert "se procesa sola" not in html and 'value="procesar"' in html


def test_con_la_herramienta_apagada_la_pagina_de_una_del_puente_no_existe(carpetas, cliente):
    _, puente = carpetas
    _reunion(puente, KVM)
    r = cliente.get(f"/reuniones/{KVM}", follow_redirects=False)
    assert r.status_code in (303, 404)
    assert cliente.get(f"/reuniones/{KVM}/foto/0").status_code == 404


def test_el_secretario_sabe_que_grabar_reunion_es_solo_el_agente_de_windows():
    from hub.secretario.acciones.pc import GrabarReunion
    d = GrabarReunion.descripcion
    assert "sólo en el PC con Windows" in d and "botón del Puente KVM" in d


def test_las_fotos_del_puente_se_sirven_por_su_segundo_con_seis_cifras(carpetas, encendida, cliente):
    _, puente = carpetas
    d = _reunion(puente, KVM)
    (d / "fotos" / "000042.jpg").write_bytes(b"\xff\xd8")
    assert reuniones.detalle(KVM)["fotos"] == [42]
    assert cliente.get(f"/reuniones/{KVM}/foto/42").status_code == 200


def test_el_hub_lee_la_misma_carpeta_que_escribe_el_puente_por_omision(monkeypatch):
    monkeypatch.delenv("PUENTE_HOME", raising=False)
    assert reuniones.raiz_puente() == Path.home() / ".local/share/puente-kvm" / "reuniones"
    monkeypatch.setenv("PUENTE_HOME", "")
    assert reuniones.raiz_puente() == Path.home() / ".local/share/puente-kvm" / "reuniones", \
        "vacía cuenta como no puesta"
