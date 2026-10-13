"""Los huecos del comando preparado, ejecutando el JavaScript (regla dura 11)."""

from __future__ import annotations

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("comandos.js")


def test_arranca_sin_reventar(tmp_path):
    assert ejecutar(GUION, tmp_path)["errores"] == []


def test_solo_se_enseñan_los_huecos_de_la_plantilla_elegida(tmp_path):
    """Enseñar todos a la vez obliga a adivinar cuál hay que rellenar."""
    resultado = ejecutar(
        GUION, tmp_path,
        previo="""
          const sel = document.getElementById('comando-preparado');
          sel.options = [{ dataset: { huecos: 'repo' } }];
          sel.selectedIndex = 0;
          document.querySelectorAll('[data-hueco]').forEach((c, i) => {
            c.dataset.hueco = i === 0 ? 'repo' : 'otro';
          });
        """,
        accion="""
          registro.visibles = [...document.querySelectorAll('[data-hueco]')]
            .map(c => [c.dataset.hueco, c.hidden]);
        """,
    )

    assert resultado["errores"] == []
    assert ["repo", False] in resultado["visibles"]
    assert ["otro", True] in resultado["visibles"]
