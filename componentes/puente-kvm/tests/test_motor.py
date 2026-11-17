"""Lo que el puente comprueba en la pantalla antes de fiarse de ella.

Una espera fija no sabe si el diálogo se abrió ni si la pantalla dejó de
moverse: aquí cada espera mira la pantalla y, si no ve lo que esperaba, lo
dice y no teclea.
"""

import asyncio

import pytest
from PIL import ImageDraw

from puente_kvm import config, muestras
from puente_kvm.control import Bitacora, Control
from puente_kvm.motor import Motor, PantallaInesperada
from puente_kvm.simulador import Simulador


class SimuladorInquieto(Simulador):
    """Un Mac en el que algo se mueve dentro del editor: cada captura es distinta.

    Lo que se mueve es pequeño (un 0,05 % de la pantalla) para que no parezca
    otra página, pero en su cuadro cambia de sobra: es una pantalla a medio pintar.
    """

    inquieto = True
    _vuelta = 0

    async def captura(self):
        img = await super().captura()
        if self.inquieto:
            self._vuelta += 1
            d = ImageDraw.Draw(img)
            d.rectangle([1500, 600, 1540, 620], fill=(0, 0, 0) if self._vuelta % 2 else (255, 255, 255))
        return img


def motor_con(sim: Simulador, **perfil) -> Motor:
    m = Motor(sim, Control(), Bitacora(), {**config.PERFIL_POR_OMISION, "retardo_tecla_ms": 2, **perfil})
    m.tope_estable = 0.6
    m.control.dar()
    return m


def correr(coro):
    return asyncio.run(coro)


def test_esperar_estable_dice_si_la_pantalla_nunca_se_quedo_quieta():
    async def prueba():
        quieto = motor_con(Simulador(lineas=["SELECT 1;"]))
        _, estable = await quieto.esperar_estable()
        assert estable
        inquieto = motor_con(SimuladorInquieto(lineas=["SELECT 1;"]))
        img, estable = await inquieto.esperar_estable()
        assert not estable and img is not None
    correr(prueba())


def test_ir_a_la_linea_no_teclea_el_numero_si_el_dialogo_no_se_abre():
    async def prueba():
        sim = Simulador(lineas=muestras.procedimiento(160))
        antes = list(sim.editor.lineas)
        m = motor_con(sim, ir_a_linea="cmd+j")  # un atajo que este programa no tiene
        with pytest.raises(PantallaInesperada, match="no se abrió"):
            await m.ir_a_linea(120)
        assert sim.editor.lineas == antes  # ni el número ni el Enter acabaron en el documento
    correr(prueba())


def test_ir_a_la_linea_espera_a_ver_el_dialogo_y_deja_el_cursor_en_ella():
    async def prueba():
        sim = Simulador(lineas=muestras.procedimiento(160))
        m = motor_con(sim)
        await m.ir_a_linea(120)
        assert sim.editor.cursor == (119, 0)
        assert sim.editor.dialogo is None
    correr(prueba())


def test_un_cambio_pequeno_en_la_barra_de_menus_no_cuenta_como_dialogo_abierto():
    # El reloj del Mac cambia cada minuto: eso no es el diálogo de ir a la línea.
    async def prueba():
        sim = Simulador(lineas=muestras.procedimiento(160))
        m = motor_con(sim, ir_a_linea="cmd+j")
        original = sim._pintar

        def con_reloj():
            img = original()
            ImageDraw.Draw(img).rectangle([1880, 6, 1900, 22], fill=(0, 0, 0))
            return img

        async def pulsar_y_cambiar_el_reloj(*a, **k):
            sim._pintar = con_reloj
            sim.editor.version += 1
        m.atajo = pulsar_y_cambiar_el_reloj
        with pytest.raises(PantallaInesperada):
            await m.ir_a_linea(5)
    correr(prueba())
