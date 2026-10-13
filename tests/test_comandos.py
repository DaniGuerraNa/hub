"""Comandos preparados: plantillas con huecos, y lo que NO se guarda en ellas.

Lo que se protege aquí es la regla dura 5 en su forma menos obvia —una
plantilla que llevara credenciales dentro las guardaría en `comandos.yml`, que
es texto plano y se lee entero desde la web— y la regla dura 10: lo que se
interpola va escapado, porque el valor lo escribe una persona en un móvil.
"""

from __future__ import annotations

import pytest

from hub import comandos


@pytest.fixture
def declarados(tmp_path, monkeypatch):
    ruta = tmp_path / "comandos.yml"
    monkeypatch.setenv("HUB_COMANDOS_YML", str(ruta))
    ruta.write_text(
        "comandos:\n"
        "  - id: clonar\n"
        "    nombre: Clonar un repo\n"
        "    plantilla: bash ~/.secretos/clonar.sh {repo} {ruta}\n"
        "  - id: sin-plantilla\n"
        "    nombre: Roto\n",
        encoding="utf-8",
    )
    return ruta


def test_sin_archivo_no_hay_comandos_y_no_es_un_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_COMANDOS_YML", str(tmp_path / "no-existe.yml"))

    assert comandos.leer() == []


def test_una_entrada_sin_plantilla_se_ignora(declarados):
    """Media declaración no se enseña como un botón que luego no hace nada."""
    assert [c["id"] for c in comandos.leer()] == ["clonar"]


def test_los_huecos_salen_en_orden_y_sin_repetirse(declarados):
    plantilla = comandos.por_id("clonar")["plantilla"]

    assert comandos.huecos(plantilla + " {repo}") == ["repo", "ruta"]


def test_lo_que_se_interpola_va_escapado(declarados):
    """🔴 Regla dura 10. El valor lo escribe una persona en un móvil, y este
    texto acaba escrito en una shell esperando un Enter."""
    orden = comandos.expandir("bash x.sh {repo}", {"repo": "algo; rm -rf ~"})

    assert orden == "bash x.sh 'algo; rm -rf ~'"
    assert "; rm -rf ~'" in orden      # dentro de las comillas, no suelto


def test_si_falta_un_hueco_no_se_escribe_nada(declarados):
    """Una orden a medias pegada en un panel es peor que ninguna: se queda a la
    vista esperando un Enter que la ejecutaría mal (decisión 164)."""
    with pytest.raises(comandos.ComandoInvalido) as exc:
        comandos.expandir("bash x.sh {repo} {ruta}", {"ruta": "/tmp"})

    assert "repo" in str(exc.value)


def test_un_hueco_en_blanco_cuenta_como_ausente(declarados):
    """Un campo que se deja vacío en el formulario no es un valor."""
    with pytest.raises(comandos.ComandoInvalido):
        comandos.expandir("bash x.sh {repo}", {"repo": "   "})
