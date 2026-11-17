"""El secretario mira y cambia en el Windows del dueño (C-0240, decisión 404).

Le pidió «abre una terminal y revisa cuáles son los modelos de mis monitores»
y contestó que no tenía cómo. Ahora: `mirar_en_pc` corre sin preguntar lo que
`orden_pc` admite como lectura; `cambiar_en_pc`, lo demás, con su sí a esa
orden exacta. Aquí se prueba lo que el secretario decide alrededor —sólo con
el dueño delante, lo que no se puede ni pedir, que el sí caduque, cómo se le
enseña la orden—; qué es lectura se prueba en `test_orden_pc`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub import db, orden_pc, web
from hub.secretario import disparadores, herramientas, memoria, piezas, servicio

MONITORES = "Get-CimInstance WmiMonitorID -Namespace root\\wmi"


@pytest.fixture
def con():
    h = db.conectar()
    db.inicializar(h)
    h.close()
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _sin_telefono(monkeypatch):
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda *a, **k: None)


@pytest.fixture
def pc(monkeypatch):
    """`orden_pc` fingido: apunta lo que se corrió y clasifica por palabras."""
    corrido = []

    def leer(c):
        corrido.append(("leer", c))
        return orden_pc.Resultado(0, "PHL 242E1GJ\nVG279QM\ntoken=ghp_abcdefghijklmnopqrstuvwxyz0123456789", [],
                                  False, 0.4)

    def cambiar(c):
        corrido.append(("cambiar", c))
        return orden_pc.Resultado(0, "hecho\n", [], False, 1.0)

    def clasificar(c):
        if "docker" in c:
            return orden_pc.Veredicto(False, nunca="docker se acciona de uno en uno, desde su pantalla del hub")
        return orden_pc.Veredicto(False, motivos=["«Restart-Service» no es de sólo mirar"])
    monkeypatch.setattr(orden_pc, "leer", leer)
    monkeypatch.setattr(orden_pc, "cambiar", cambiar)
    monkeypatch.setattr(orden_pc, "clasificar", clasificar)
    return corrido


def _usar(con, accion_id, comando, hilo=1, motivo=""):
    return herramientas.usar_accion(con, piezas.acciones()[accion_id], {"comando": comando}, motivo, hilo)


# ── mirar: sin preguntar, y sólo con él delante ──────────────────────────────

def test_mirar_los_monitores_lo_hace_sin_preguntar_y_tapa_las_llaves(con, pc):
    r = _usar(con, "mirar_en_pc", MONITORES)
    assert r["hecho"] and "VG279QM" in r["resultado"]
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in r["resultado"]
    assert pc == [("leer", MONITORES)]


def test_sin_el_dueno_delante_no_mira_ni_cambia(con, pc):
    """Sin hilo es un disparador o un `pide`, con el texto de un tercero delante."""
    for accion in ("mirar_en_pc", "cambiar_en_pc"):
        r = _usar(con, accion, MONITORES, hilo=None)
        assert not r["hecho"] and "cuando el dueño te lo pide" in r["nota"]
    assert pc == []
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_sin_hilo_ni_se_le_ofrecen(monkeypatch):
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    assert not {"accion_mirar_en_pc", "accion_cambiar_en_pc"} & set(herramientas.todas())
    monkeypatch.setenv("SECRETARIO_HILO", "3")
    assert {"accion_mirar_en_pc", "accion_cambiar_en_pc"} <= set(herramientas.todas())


def test_un_disparador_no_puede_usarlas(con, pc):
    with pytest.raises(ValueError, match="sólo se hace cuando tú se lo pides"):
        disparadores.guardar_crudo("- nombre: x\n  cuando: {mensaje: {}}\n  haz: mirar_en_pc\n"
                                   "  comando: '{texto}'\n")
    base = {"clase": "mensaje", "que": "haz", "menciona": "monitor"}
    assert disparadores.de_formulario({**base, "haz": "anotar"})["haz"] == "anotar"
    with pytest.raises(ValueError, match="elige una acción"):
        disparadores.de_formulario({**base, "haz": "cambiar_en_pc"})
    # Uno escrito a mano antes de esta regla tampoco llega a correr.
    disparadores._hacer(con, {"nombre": "viejo", "haz": "mirar_en_pc", "comando": "{texto}"},
                        {"texto": "Remove-Item C:\\"})
    assert pc == []


# ── cambiar: con su sí a la orden exacta ─────────────────────────────────────

def test_cambiar_pide_su_si_con_el_motivo_que_saca_el_analizador(con, pc):
    r = _usar(con, "cambiar_en_pc", "Restart-Service Spooler", motivo="la impresora no responde")
    assert not r["hecho"] and r["solicitud"]
    s = con.execute("SELECT * FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert "la impresora no responde" in s["motivo"] and "Restart-Service" in s["motivo"]
    assert pc == []


def test_lo_que_no_se_puede_ni_pedir_no_le_llega_como_solicitud(con, pc):
    r = _usar(con, "cambiar_en_pc", "docker rm web")
    assert not r["hecho"] and "de uno en uno" in r["error"]
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_con_su_si_la_corre_y_lo_dice_en_el_hilo(con, pc):
    r = _usar(con, "cambiar_en_pc", "Restart-Service Spooler")
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    assert servicio.ejecutar_aprobadas(con) == 1
    assert pc == [("cambiar", "Restart-Service Spooler")]
    assert con.execute("SELECT estado FROM solicitud").fetchone()["estado"] == "hecha"


def test_un_si_que_llega_tarde_no_la_corre(con, pc):
    r = _usar(con, "cambiar_en_pc", "Restart-Service Spooler")
    con.execute("UPDATE solicitud SET creada = '2020-01-01T00:00:00+00:00'")
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    s = con.execute("SELECT estado, resultado FROM solicitud").fetchone()
    assert s["estado"] == "caducada" and "pídemelo otra vez" in s["resultado"]
    assert pc == []


def test_sin_aprobar_no_corre_aunque_la_llamen_directo(pc):
    with pytest.raises(RuntimeError, match="sí del dueño"):
        piezas.acciones()["cambiar_en_pc"].ejecutar(None, {"comando": "Restart-Service Spooler"})
    assert pc == []


def test_cambiar_no_puede_pasar_a_automatico():
    a = piezas.acciones()["cambiar_en_pc"]
    assert a.riesgo in piezas.CON_TECHO and piezas.nivel(a) == "ask"


# ── cómo se le enseña ────────────────────────────────────────────────────────

def test_la_solicitud_ensena_la_orden_entera_y_aparte(con, pc):
    orden = "Restart-Service -Name Spooler -Force"
    _usar(con, "cambiar_en_pc", orden, motivo="la impresora")
    html = TestClient(web.app).get("/secretario?p=pendientes").text
    assert f'<code class="mono orden-pc">{orden}</code>' in html
    assert "orden: " not in html


def test_en_el_formulario_de_disparadores_no_se_ofrecen():
    html = TestClient(web.app).get("/secretario?p=disparadores").text
    assert 'value="avisar"' in html
    assert 'value="mirar_en_pc"' not in html and 'value="cambiar_en_pc"' not in html


def test_si_no_es_solo_mirar_le_dice_al_modelo_por_donde_se_pide(con, monkeypatch):
    def leer(c):
        raise orden_pc.NoEsLectura(orden_pc.Veredicto(False, motivos=["«Remove-Item» no es de sólo mirar"]))
    monkeypatch.setattr(orden_pc, "leer", leer)
    r = _usar(con, "mirar_en_pc", "Remove-Item C:\\x")
    assert not r["hecho"] and "Remove-Item" in r["error"] and "cambiar_en_pc" in r["error"]
