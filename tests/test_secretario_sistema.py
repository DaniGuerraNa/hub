"""El prompt de la conversación (C-0408, SEC2-08).

Es texto que se paga en cada turno y que el modelo obedece al pie de la
letra: si nombra una herramienta que no se le sirve, la busca, falla y lo
cuenta como si fuera culpa de otro.
"""

from __future__ import annotations

import re

import pytest

from hub.secretario import agenda, conversacion, herramientas


def _nombrados(texto: str) -> set[str]:
    """Lo que el texto nombra entre comillas invertidas, sin el comodín `accion_*`."""
    return {n for n in re.findall(r"`([a-z_]+)`", texto)}


def _no_servidos(texto: str, *, con_el_dueno: bool) -> set[str]:
    servidas = herramientas.todas(con_el_dueno=con_el_dueno)
    parametros = {k for h in servidas.values() for k in (h.esquema.get("properties") or {})}
    return {n for n in _nombrados(texto) if n not in servidas and n not in parametros}


@pytest.fixture
def sin_agenda(monkeypatch):
    monkeypatch.setattr(agenda, "disponible", lambda: "google: falta entrar")


@pytest.fixture
def con_agenda(monkeypatch):
    monkeypatch.setattr(agenda, "disponible", lambda: None)


def test_el_sistema_no_nombra_ninguna_herramienta_que_no_se_le_sirva(sin_agenda):
    assert _nombrados(conversacion.sistema()), "sin nombres que mirar, esto pasaría sin mirar"
    assert not _no_servidos(conversacion.SISTEMA, con_el_dueno=True)
    assert not _no_servidos(conversacion.sistema(), con_el_dueno=True)


def test_el_prompt_del_pide_solo_nombra_lo_que_se_sirve_sin_el_dueno(sin_agenda):
    """Sin hilo no se sirven `tarjeta`, `investigar` ni `pedir_modelo_mayor` (404)."""
    assert _nombrados(conversacion.sistema_pide())
    assert not _no_servidos(conversacion.sistema_pide(), con_el_dueno=False)


def test_el_vigia_de_nombres_ve_una_herramienta_que_no_existe(sin_agenda):
    assert _no_servidos("usa `buscar` y luego `agenda` o `consultar_oraculo`", con_el_dueno=True) == {
        "agenda", "consultar_oraculo"}


def test_el_vigia_de_nombres_ve_una_accion_sin_configurar(sin_agenda, monkeypatch):
    """SEC-08: una acción sin configurar no se sirve, y el prompt que la
    nombrara la mandaría a buscarla igual."""
    from hub.secretario import piezas

    class SinConfigurar(piezas.Accion):
        id, como_configurar = "sin_configurar", "Se configura en su sitio."
        disponible = staticmethod(lambda: False)

    class Lista(piezas.Accion):
        id = "lista"

    monkeypatch.setattr(piezas, "acciones", lambda: {"sin_configurar": SinConfigurar(), "lista": Lista()})
    assert _no_servidos("usa `accion_lista` o `accion_sin_configurar`", con_el_dueno=True) == {
        "accion_sin_configurar"}


def test_sin_agenda_conectada_ni_se_le_ofrece_ni_se_le_nombra(sin_agenda):
    """SEC-07: la agenda sigue sin conectar y el prompt se la presentaba como
    fuente. «¿Qué tengo mañana?» acababa en una llamada que sólo podía fallar."""
    assert "agenda" not in herramientas.todas(con_el_dueno=True)
    assert "`agenda`" not in conversacion.sistema()
    assert "compromisos, agenda y proyectos" not in conversacion.sistema()


def test_con_la_agenda_conectada_vuelve_a_ser_una_fuente(con_agenda):
    assert "agenda" in herramientas.todas(con_el_dueno=True)
    assert "`agenda`" in conversacion.sistema() and "agenda y proyectos" in conversacion.sistema()
    assert not _no_servidos(conversacion.sistema(), con_el_dueno=True)


def test_tiene_un_como_decides_de_cinco_lineas():
    bloque = conversacion.SISTEMA.split("Cómo decides:\n", 1)[1].split("\n\n", 1)[0]
    lineas = [l for l in bloque.split("\n- ")]
    assert len(lineas) == 5
    for palabra in ("búscalo primero", "`investigar`", "encárgalo", "pregúntale en una frase", "`hub_buscar`",
                    "`accion_abrir_en_pc`"):
        assert palabra in bloque, palabra


def test_dice_que_aun_no_repite_recordatorios():
    """SEC-12: «cada lunes» acababa en un aviso único sin decirlo."""
    assert "Aún no repites recordatorios" in conversacion.SISTEMA


def test_por_voz_le_pide_escribir_para_el_oido():
    """VOZ-21 (C-0358): «dos o tres frases, sin listas» no decía nada de
    cifras, rutas ni símbolos, y 6 de 26 respuestas por voz traían «/». Lo
    que mejor suena es lo que no hay que limpiar (`paraOir` es la red)."""
    regla = conversacion.SISTEMA.split("«(por voz)»", 1)[1].split("\n- ", 1)[0]
    for pide in ("como mucho tres frases", "ofrécele contarlo", "sin rutas", "códigos de ficha",
                 "a las cuatro y media", "redondeadas", "emojis", "paréntesis"):
        assert pide in regla, pide
