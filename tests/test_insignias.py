"""Que ningún estado se quede mudo.

Las insignias existen para no tener que LEER cada estado. Eso sólo funciona si
están todos: un valor sin glifo cae al texto pelado, y en una rejilla donde los
demás llevan símbolo, el que no lo lleva no se lee como «desconocido» sino que
pasa desapercibido — justo lo contrario de lo que se busca.

Por eso el mapa vive en Python y no en un macro de Jinja: aquí se puede afirmar
contra los valores que el sistema realmente produce.
"""

from __future__ import annotations

import pytest

from hub import insignias
from hub.insignias import ESPERA, NEUTRO, OK, RIESGO

# Los valores que el sistema puede generar hoy. Si se añade uno —un `status`
# nuevo en projects.yml, un estado de Docker que no se había visto— este test
# es el que avisa de que le falta su insignia.
VALORES = {
    "status": ["activo", "pausado", "archivado"],
    "guardrail": ["auto", "ask", "never"],
    "dominio": ["personal", "laboral"],
    "tipo": ["proyecto", "kit", "asistente"],
    "regimen": ["con-upstream", "sin-upstream", "sin-remoto"],
    # Los seis estados que devuelve `docker ps`, no sólo los dos que hay hoy en
    # la máquina: el día que un contenedor muera, la UI tiene que saber decirlo.
    "servicio": ["running", "exited", "created", "paused", "restarting", "dead"],
}


@pytest.mark.parametrize(
    "dimension,valor",
    [(d, v) for d, vs in VALORES.items() for v in vs],
)
def test_todo_valor_conocido_tiene_insignia(dimension, valor):
    i = insignias.de(dimension, valor)
    assert i is not None, f"{dimension}={valor} saldría sin glifo"
    assert i.glifo and i.texto and i.porque


def test_el_tono_siempre_es_uno_de_los_cuatro_de_la_escala():
    """La escala es el contrato: un tono nuevo rompe que el color signifique
    lo mismo en toda la interfaz."""
    permitidos = {OK, ESPERA, RIESGO, NEUTRO}
    for dimension, valores in insignias.MAPA.items():
        for valor, i in valores.items():
            assert i.tono in permitidos, f"{dimension}={valor} usa el tono {i.tono!r}"


def test_un_valor_desconocido_no_se_inventa_un_glifo():
    """Devolver None deja que la plantilla caiga al texto pelado, que es
    correcto. Un glifo inventado afirmaría algo que no sabemos."""
    assert insignias.de("status", "flotando") is None
    assert insignias.de("dimension-que-no-existe", "activo") is None
    assert insignias.de("status", None) is None


def test_el_valor_se_normaliza_antes_de_buscarlo():
    """`projects.yml` lo edita un humano: 'Activo' y 'activo ' son lo mismo."""
    assert insignias.de("status", " Activo ") == insignias.de("status", "activo")


def test_los_glifos_de_una_dimension_no_se_repiten():
    """Si dos valores comparten glifo, el símbolo deja de distinguirlos y todo
    el peso vuelve a caer en el color — que es lo que no queremos."""
    for dimension, valores in insignias.MAPA.items():
        # `status` y `servicio` sí comparten familia de formas entre sí a
        # propósito (● en marcha, ○ parado): la comprobación es DENTRO de cada
        # dimensión, que es donde hay que distinguir.
        glifos = [i.glifo for i in valores.values()]
        assert len(glifos) == len(set(glifos)), f"{dimension} repite glifo"


def test_ningun_estado_de_reposo_pide_atencion():
    """«archivado» y «sin remoto» son decisiones, no problemas. Pintarlos de
    alerta enseña a ignorar la alerta."""
    assert insignias.de("status", "archivado").tono == NEUTRO
    assert insignias.de("regimen", "sin-remoto").tono == NEUTRO
    assert insignias.de("guardrail", "never").tono == NEUTRO
