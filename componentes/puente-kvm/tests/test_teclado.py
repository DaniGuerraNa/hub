"""Lo que se teclea por HID llega al Mac como el mismo texto.

El simulador interpreta los informes como macOS con «U.S.», así que esto
prueba la tabla de `hid` de verdad: si `{` saliera con la tecla equivocada,
el editor tendría otra cosa.
"""

import asyncio

import pytest

from puente_kvm import hid
from puente_kvm.simulador import Simulador


def teclear_en(sim: Simulador, texto: str) -> None:
    async def correr():
        for p in hid.secuencia(texto):
            await sim.informe_teclado(p.modificadores, [p.tecla])
            await sim.informe_teclado(0, [])

    asyncio.run(correr())


def test_todo_el_ascii_imprimible_llega_igual_al_editor():
    sim = Simulador(lineas=[""])
    texto = "".join(chr(i) for i in range(32, 127))
    teclear_en(sim, texto)
    assert sim.editor.lineas == [texto]


def test_los_acentos_la_enie_y_los_signos_de_apertura_llegan_por_teclas_muertas():
    sim = Simulador(lineas=[""])
    texto = "¿Año fiscal? ¡Sí! Conciliación de pingüinos: Ñandú, «O» y 10 €"
    teclear_en(sim, texto)
    assert sim.editor.lineas == [texto]


def test_los_saltos_de_linea_son_enter_y_parten_la_linea():
    sim = Simulador(lineas=[""])
    teclear_en(sim, "BEGIN\n    SELECT 1;\nEND;")
    assert sim.editor.lineas == ["BEGIN", "    SELECT 1;", "END;"]


def test_un_caracter_sin_tecla_impide_teclear_el_texto_entero():
    with pytest.raises(hid.TextoIntraducible) as e:
        hid.secuencia("SELECT 1 -- ✓ revisado")
    assert e.value.caracteres == ["✓"]


def test_los_atajos_se_leen_con_sus_modificadores():
    p = hid.combinacion("cmd+shift+down")
    assert p.modificadores == hid.GUI | hid.SHIFT
    assert p.tecla == hid.TECLAS["down"]
    with pytest.raises(ValueError):
        hid.combinacion("cmd+")
    with pytest.raises(ValueError):
        hid.combinacion("hiper+a")
