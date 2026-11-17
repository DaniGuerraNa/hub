"""El enrutador del secretario: la tabla decide, y si el dueño nombra uno, manda él (decisiones 301 y 405)."""

from __future__ import annotations

import pytest

from hub.secretario import enrutador, memoria


def test_sin_pedido_va_la_tabla_y_modelos_yml_la_cambia_dentro_del_techo():
    assert enrutador.modelo("investigar") == "claude-haiku-4-5"
    assert enrutador.modelo("conversacion") == "claude-sonnet-5"
    (memoria.carpeta() / "modelos.yml").write_text("investigar: sonnet\nno_existe: opus\n")
    assert enrutador.modelo("investigar") == "claude-sonnet-5"
    assert "no_existe" not in enrutador.tabla()


def test_con_pedido_va_ese_y_fable_solo_a_peticion():
    assert enrutador.modelo("investigar", "opus") == "claude-opus-5-5"
    assert enrutador.modelo("investigar", "  ") == "claude-haiku-4-5"          # vacío es no pedir
    with pytest.raises(ValueError):
        enrutador.modelo("investigar", "fable")
    assert enrutador.modelo("mayor", "fable", a_peticion=True) == "claude-fable-5-2"
    # Ni por la tabla: `modelos.yml` es suyo, pero lo lee el servicio solo.
    (memoria.carpeta() / "modelos.yml").write_text("investigar: fable\n")
    with pytest.raises(ValueError):
        enrutador.modelo("investigar")
