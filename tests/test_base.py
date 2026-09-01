"""La capa base y el puntero al estado vigente.

El diagnóstico de §1 es que al usuario no le falta documentación —documenta
excepcionalmente bien— sino un puntero a cuál de sus quince documentos está
vigente. Esto lo resuelve leyendo el que el propio proyecto declaró.

Los formatos de los casos de prueba **no se inventan**: son los que aparecen en
sus checkpoints reales del 2026-08-21.
"""

from __future__ import annotations

import pytest

from hub import base
from hub.models import Proyecto, Ruta


def _escribir(ruta, texto):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


# ───────────────────────── extracción del mínimo ─────────────────────────


def test_lee_el_frontmatter_estructurado_cuando_existe():
    campos = base.extraer_minimo(
        "---\nestado: verde\nproxima_accion: revisar el PR\nbloqueado_por: nada\n---\n\n# Cuerpo\n"
    )
    assert campos["estado"] == "verde"
    assert campos["proxima_accion"] == "revisar el PR"


def test_reconoce_los_encabezados_numerados_de_sus_checkpoints():
    """Sus documentos van numerados: `## 0. Estado en una línea`.

    Sin quitar la numeración el extractor no reconocía NINGUNO de los suyos —
    exactamente el modo de falla que haría inútil la función.
    """
    campos = base.extraer_minimo(
        "# Punto de retoma\n\n"
        "## 0. Estado en una línea\n\nTodo commiteado y verificado.\n\n"
        "## 1. Qué hacer al volver, en orden\n\n1. Leer el resumen\n2. Abrir el exe\n"
    )
    assert campos["estado"] == "Todo commiteado y verificado."
    assert "Leer el resumen" in campos["proxima_accion"]


def test_encuentra_el_alias_aunque_el_titulo_lleve_adorno():
    """`## 2. 🔴 LO QUE ESPERA DECISIÓN DEL STAKEHOLDER` es un título real suyo."""
    campos = base.extraer_minimo(
        "## 2. 🔴 LO QUE ESPERA DECISIÓN DEL STAKEHOLDER\n\n¿Este canon es el de la V1?\n"
    )
    assert "canon" in campos["bloqueado_por"]


def test_una_seccion_que_solo_menciona_la_palabra_no_es_el_estado():
    """`## 5.1 El mínimo de estado` es diseño de este mismo repo, y se colaba
    como si fuera el estado del proyecto. Un estado falso es peor que ninguno:
    se actúa sobre él."""
    assert base.extraer_minimo("## 5.1 El mínimo de estado\n\nLos viejos no migran.\n") == {}
    assert base.extraer_minimo("## Historial de estado\n\nx\n") == {}


def test_una_subseccion_no_se_lleva_por_delante_a_su_padre():
    """Su sección de decisiones cuelga todo el contenido de 2.1, 2.2 y 2.3.

    Si una subsección cerrara la sección padre, el campo saldría vacío y se
    descartaría — el dato más importante del checkpoint, perdido en silencio.
    """
    campos = base.extraer_minimo(
        "## 2. Qué espera decisión\n"
        "### 2.1 La grande: ¿este canon es el de la V1?\n"
        "### 2.2 Las dos que se ven al abrir\n"
    )
    assert "canon" in campos["bloqueado_por"]


def test_un_encabezado_de_otra_casilla_si_cierra_la_seccion():
    campos = base.extraer_minimo(
        "## Estado\n\nverde\n\n### Próxima acción\n\ndesplegar\n"
    )
    assert campos["estado"] == "verde"
    assert campos["proxima_accion"] == "desplegar"


def test_el_frontmatter_gana_sobre_una_seccion_de_prosa():
    campos = base.extraer_minimo("---\nestado: lo declarado\n---\n\n## Estado\n\nprosa vieja\n")
    assert campos["estado"] == "lo declarado"


def test_un_documento_sin_el_bloque_minimo_no_inventa_campos():
    """`contexto-tecnico.md` es contexto, no estado. Decirlo es la respuesta correcta."""
    assert base.extraer_minimo("# Contexto técnico\n\n## Stack\n\nPython\n") == {}


def test_una_seccion_vacia_no_cuenta_como_encontrada():
    assert base.extraer_minimo("## Estado\n\n---\n\n## Otra cosa\n") == {}


def test_quita_la_tipografia_del_markdown():
    """La tarjeta muestra texto, no markdown renderizado: `> **x**` sería ruido."""
    campos = base.extraer_minimo("## Estado\n\n> **Todo commiteado** y `verificado`.\n")
    assert campos["estado"] == "Todo commiteado y verificado."


def test_descarta_las_tablas_que_sin_renderizar_son_ilegibles():
    campos = base.extraer_minimo(
        "## Estado\n\nVa bien.\n\n| Repo | Commit |\n|---|---|\n| idle | 055115f |\n"
    )
    assert campos["estado"] == "Va bien."


# ───────────────────────── resolución del puntero ─────────────────────────


@pytest.fixture
def proyecto(tmp_path):
    asiento = tmp_path / "asiento"
    repo = tmp_path / "repo"
    _escribir(repo / "docs" / "ESTADO.md", "## Estado\n\nen marcha\n")
    asiento.mkdir(parents=True, exist_ok=True)
    return Proyecto(
        id="demo", nombre="Demo", asiento=str(asiento),
        rutas=[Ruta(ruta=str(repo))], estado_ref="docs/ESTADO.md",
    )


def test_resuelve_el_puntero_contra_todas_las_rutas_no_solo_el_asiento(proyecto):
    """El proyecto se orquesta desde /mnt/c mientras su código vive en ~/dev."""
    estado = base.estado_de(proyecto)
    assert estado["existe"]
    assert estado["campos"]["estado"] == "en marcha"


def test_un_puntero_roto_se_reporta_como_roto_no_como_ausente(proyecto):
    proyecto.estado_ref = "docs/NO-EXISTE.md"
    estado = base.estado_de(proyecto)
    assert estado["existe"] is False
    assert estado["declarado"] == "docs/NO-EXISTE.md"


def test_sin_estado_ref_se_dice_que_nadie_declaro_cual_esta_vigente(proyecto):
    proyecto.estado_ref = None
    estado = base.estado_de(proyecto)
    assert estado["declarado"] is None
    assert estado["campos"] == {}


# ───────────────────────── la capa base ─────────────────────────


def test_detecta_la_capa_base_y_su_version(proyecto, tmp_path):
    _escribir(
        tmp_path / "asiento" / ".claude" / "hub" / "project.yml",
        f'id: demo\nbase_version: "{base.VERSION_BASE}"\n',
    )
    capa = base.capa_de(proyecto)
    assert capa["presente"] and capa["al_dia"]
    assert capa["tiene_capabilities"] is False


def test_un_proyecto_sin_capa_base_lo_dice_sin_romper(proyecto):
    assert base.capa_de(proyecto)["presente"] is False


def test_el_prompt_de_siembra_prohibe_crear_otro_documento_de_estado(proyecto):
    """Sobran documentos y falta el puntero: sembrar uno nuevo sería el error."""
    prompt = base.prompt_sembrar(proyecto)
    assert "no crees un documento de estado" in prompt.lower()
    assert proyecto.id in prompt and base.VERSION_BASE in prompt


# ── el título del documento no es su estado ──────────────────────────────────

def test_el_titulo_del_documento_no_tapa_a_la_seccion_de_estado():
    """Caso real: un checkpoint que empieza por «# Resumen y checkpoint — X».

    «resumen» es alias de estado, así que el H1 encajaba y se llevaba el
    preámbulo entero —una cita explicando cómo leer el archivo— dejando fuera el
    «## Estado en una línea» que venía justo debajo. El estado que enseñaba el
    hub era la instrucción de uso del documento, no el estado del proyecto.
    """
    texto = (
        "# Resumen y checkpoint — proyecto\n\n"
        "> El primer fichero que se lee al retomar. Estado arriba, actas abajo.\n\n"
        "## Estado en una línea\n\n"
        "12 frentes evaluados, ranking vigente.\n"
    )
    assert base.extraer_minimo(texto)["estado"] == "12 frentes evaluados, ranking vigente."


def test_si_el_titulo_es_lo_unico_que_encaja_sigue_valiendo():
    """La penalización al título es para desempatar, no para ignorarlo."""
    texto = "# Estado del proyecto\n\nParado desde marzo.\n"
    assert base.extraer_minimo(texto)["estado"] == "Parado desde marzo."


def test_el_frontmatter_gana_a_cualquier_seccion():
    """Una declaración explícita no la pisa una sección de prosa que se llame igual."""
    texto = (
        "---\nestado: Lo declarado manda.\n---\n\n"
        "# Resumen\n\nprosa\n\n## Estado en una línea\n\nesto tampoco gana\n"
    )
    assert base.extraer_minimo(texto)["estado"] == "Lo declarado manda."
