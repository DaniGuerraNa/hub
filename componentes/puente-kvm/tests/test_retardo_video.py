"""Tras pulsar, esperar a VER el cambio, no a la primera pantalla quieta (C-0485).

Con el aparato real, el vídeo del JetKVM llegó 1–2 s tarde: dos capturas
iguales justo después de pulsar eran las de ANTES de la tecla, y la primera
página de una lectura salió vieja (faltaron las líneas 1–3). Aquí un Mac
simulado cuyo vídeo llega `retraso` segundos tarde, como aquél, y lo que con
él tiene que seguir saliendo bien.
"""

import asyncio
import time

import pytest
from PIL import Image

from puente_kvm import cambios, config, lecturas, muestras
from puente_kvm.control import Bitacora, Control
from puente_kvm.motor import IGUAL, Motor, PantallaInesperada, diferencia
from puente_kvm.simulador import Simulador

from .ayuda import PERSONA, puente_simulado

# Pequeño, para que la suite no se alargue; el del perfil, un poco más, como
# los 3 s frente a los 1–2 s medidos.
RETRASO = 0.4
PERFIL_MS = 600


class SimuladorConRetraso(Simulador):
    """Un Mac simulado cuyo vídeo enseña la pantalla de hace `retraso` segundos.

    Guarda (hora, imagen) cada vez que la pantalla cambia —tras cada informe de
    teclado, de ratón o de rueda— y la captura da la última que ya tiene
    `retraso` segundos. El retraso es el del perfil, como con el JetKVM.
    """

    retardo_video_s = None

    def __init__(self, *a, retraso: float = RETRASO, **k):
        super().__init__(*a, **k)
        self.retraso = retraso
        self._historia: list[tuple[float, Image.Image]] = []
        self._clave_vista = None
        self.apuntar_cambio(desde=0.0)  # lo de antes de empezar ya está a la vista

    def apuntar_cambio(self, desde: float | None = None) -> None:
        """Lo que hay ahora en el Mac, para enseñarlo dentro de `retraso`."""
        clave = (self.editor.version, self.puntero)
        if clave != self._clave_vista:
            self._clave_vista = clave
            self._historia.append((time.monotonic() if desde is None else desde, self._pintar()))

    async def informe_teclado(self, modificadores, teclas):
        await super().informe_teclado(modificadores, teclas)
        self.apuntar_cambio()

    async def raton(self, x, y, botones=0):
        await super().raton(x, y, botones)
        self.apuntar_cambio()

    async def rueda(self, pasos):
        await super().rueda(pasos)
        self.apuntar_cambio()

    async def captura(self):
        visible = time.monotonic() - self.retraso
        cual = 0
        for i, (t, _) in enumerate(self._historia):
            if t <= visible:
                cual = i
        del self._historia[:cual]  # lo de antes ya no se enseñará
        await asyncio.sleep(0)
        return self._historia[0][1].copy()


def motor_con(sim: Simulador, **perfil) -> Motor:
    m = Motor(sim, Control(), Bitacora(),
              {**config.PERFIL_POR_OMISION, "retardo_tecla_ms": 2, "retardo_video_ms": PERFIL_MS, **perfil})
    m.tope_estable = 1.0
    m.control.dar()
    return m


def en_medio(sim: Simulador, linea: int) -> None:
    """El documento abierto por la línea `linea`, ya a la vista (como lo dejó la persona)."""
    e = sim.editor
    e.arriba, e.cursor = linea, (linea, 0)
    e.version += 1
    if isinstance(sim, SimuladorConRetraso):
        sim.apuntar_cambio(desde=0.0)


def vista_de(lineas: list[str], arriba: int, cursor: tuple[int, int], motor: Motor) -> Image.Image:
    """La región del editor de un Mac sin retraso con el documento en esa posición."""
    ref = Simulador(lineas=list(lineas))
    ref.editor.arriba, ref.editor.cursor = arriba, cursor
    ref.puntero = tuple(motor.perfil["aparcar_raton"])
    return motor.recortar(ref._pintar())


def leer_con(motor: Motor) -> lecturas.Lectura:
    async def leer():
        async with motor.ocupar("leer"):
            return await lecturas.capturar(motor, lecturas.nueva("documento"))
    return asyncio.run(leer())


LINEAS = muestras.procedimiento(100)


def test_la_primera_pagina_trae_las_lineas_de_arriba_aunque_el_video_llegue_tarde():
    sim = SimuladorConRetraso(lineas=list(LINEAS))
    en_medio(sim, 70)
    m = motor_con(sim)
    l = leer_con(m)
    assert l.estado == "capturada", l.error
    primera = Image.open(l.png(1))
    # La de arriba del todo, con el cursor en la línea 1: no la de la línea 70,
    # que era lo que el vídeo aún enseñaba justo después de Cmd+↑.
    assert diferencia(primera, vista_de(LINEAS, 0, (0, 0), m)) < IGUAL
    assert diferencia(primera, vista_de(LINEAS, 70, (70, 0), m)) > IGUAL


def test_no_corta_la_lectura_antes_del_final_aunque_el_video_llegue_tarde():
    sin_retraso = leer_con(motor_con(Simulador(lineas=list(LINEAS))))
    sim = SimuladorConRetraso(lineas=list(LINEAS))
    m = motor_con(sim)
    l = leer_con(m)
    assert l.estado == "capturada", l.error
    assert len(l.paginas) == len(sin_retraso.paginas) > 2
    e = sim.editor
    ultima = Image.open(l.png(len(l.paginas)))
    assert diferencia(ultima, Image.open(sin_retraso.png(len(sin_retraso.paginas)))) < IGUAL
    assert e.arriba == len(e.lineas) - e.filas  # y el Mac quedó al final del documento


def test_lo_que_tarda_cada_cambio_queda_en_las_tardanzas():
    m = motor_con(SimuladorConRetraso(lineas=list(LINEAS)))
    l = leer_con(m)
    # Una por página salvo la primera si ya estaba arriba (no cambia), y ninguna al final.
    assert len(m.tardanzas) >= len(l.paginas) - 1 > 1
    assert all(RETRASO * 0.9 <= t <= PERFIL_MS / 1000 + 1.0 for t in m.tardanzas), list(m.tardanzas)
    assert m.esperas_sin_cambio >= 1  # el Av Pág del final no movió nada
    assert not l.aviso  # 0,4 s frente a un tope de 1,6 s: lejos


def test_si_el_cambio_tarda_cerca_del_tope_la_bitacora_dice_que_se_suba_el_retraso():
    sim = SimuladorConRetraso(lineas=list(LINEAS), retraso=1.75)
    # Se avisa contra «Retraso del vídeo», no contra el tope (que lleva 1 s de
    # margen): `asentada` da por hecho que el vídeo no llega más tarde que eso.
    m = motor_con(sim, retardo_video_ms=2000)
    m.tope_estable = 0.6

    async def prueba():
        async with m.ocupar("probar"):
            return await m.tras(lambda: m.atajo("pagedown", apuntar=False))
    v = asyncio.run(prueba())
    assert v.cambio and v.tardo > 1.6
    avisos = [e for e in m.bitacora.ultimas() if e["tipo"] == "aviso"]
    assert len(avisos) == 1 and "Retraso del vídeo" in avisos[0]["detalle"]
    assert m.aviso_retraso


def test_comprobar_las_paginas_antes_de_escribir_no_falla_en_falso_con_el_video_tarde():
    sim = SimuladorConRetraso(lineas=list(LINEAS), retraso=0.0)
    m = motor_con(sim)
    l = leer_con(m)  # leída con el vídeo al día: aquí sólo se prueba la comprobación
    assert l.estado == "capturada" and len(l.paginas) > 2
    sim.retraso = RETRASO

    async def comprobar():
        async with m.ocupar("comprobar"):
            # Tras leer, el documento está al final: el vídeo, al pulsar Cmd+↑,
            # aún enseña la última página, que no es la primera leída.
            await cambios.comprobar_paginas(m, l, len(l.paginas))
    asyncio.run(comprobar())


def test_ir_a_la_linea_tras_teclear_un_tramo_no_teclea_el_numero_si_el_atajo_no_abre_nada():
    # Lo tecleado del tramo llega al vídeo tarde: comparado con una pantalla de
    # antes de teclearlo, parecía el diálogo abriéndose, y el número y el Enter
    # acababan en el documento.
    sim = SimuladorConRetraso(lineas=list(LINEAS))
    m = motor_con(sim, ir_a_linea="cmd+j")  # un atajo que este programa no tiene

    async def prueba():
        async with m.ocupar("escribir"):
            await m.teclear("-- una línea nueva del tramo\n-- y otra más, bastante larga\n")
            despues = list(sim.editor.lineas)
            with pytest.raises(PantallaInesperada, match="no se abrió"):
                await m.ir_a_linea(120)
            return despues
    despues = asyncio.run(prueba())
    assert sim.editor.lineas == despues  # ni el número ni el Enter acabaron en el documento


def test_ir_a_la_linea_no_teclea_el_numero_si_lo_de_antes_no_estaba_quieto():
    """Con el vídeo más tarde que «Retraso del vídeo», o un aviso de macOS
    entrando, lo que acaba de pintarse pasaba por el diálogo (lo encontró el
    revisor): sin un «antes» quieto no se teclea el número."""
    sim = SimuladorConRetraso(lineas=list(LINEAS))
    m = motor_con(sim)

    async def a_medio_pintar(zona=None, recortar=True):
        return await m.captura(), False
    m.asentada = a_medio_pintar

    async def prueba():
        async with m.ocupar("escribir"):
            antes = list(sim.editor.lineas)
            with pytest.raises(PantallaInesperada, match="no estaba quieta"):
                await m.ir_a_linea(120)
            return antes
    antes = asyncio.run(prueba())
    assert sim.editor.lineas == antes


def test_ir_a_la_linea_con_el_video_tarde_espera_a_ver_el_dialogo_y_llega():
    sim = SimuladorConRetraso(lineas=list(LINEAS))
    m = motor_con(sim)

    async def prueba():
        async with m.ocupar("ir"):
            await m.ir_a_linea(80)
    asyncio.run(prueba())
    assert sim.editor.cursor == (79, 0) and sim.editor.dialogo is None


def test_el_simulador_no_espera_el_retraso_del_perfil():
    m = motor_con(Simulador(lineas=["SELECT 1;"]), retardo_video_ms=3000)
    assert m.retardo_video() == 0.0


def test_el_retraso_del_video_se_guarda_acotado_en_el_perfil_sin_cambiar_de_aparato():
    with puente_simulado() as (c, _):
        assert c.get("/api/estado").json()["perfil"]["retardo_video_ms"] == 3000
        perfil = {**config.PERFIL_POR_OMISION, "retardo_video_ms": 99999}
        assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200
        assert config.leer_ajustes()["perfil"]["retardo_video_ms"] == 10000
        perfil["retardo_video_ms"] = -5
        assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200
        assert c.get("/api/estado").json()["perfil"]["retardo_video_ms"] == 0
        assert 'name="perfil.retardo_video_ms"' in c.get("/ajustes").text
