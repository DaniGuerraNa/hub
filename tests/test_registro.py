"""projects.yml manda sobre el índice, y la atribución usa la ruta más específica."""

from __future__ import annotations

from pathlib import Path

import pytest

from hub import api, registry
from hub.registry import Atribuidor

YAML_DEMO = """
proyectos:
  - id: facturador
    nombre: Facturador
    asiento: /mnt/c/proyects/facturador-main
    rutas:
      - ruta: /home/ana/dev/facturador
      - ruta: /home/ana/dev/facturador-front
  - id: idle
    nombre: Idle
    dominio: personal
    asiento: /mnt/c/proyects/Idle
"""


@pytest.fixture
def yaml_demo(tmp_path) -> Path:
    ruta = tmp_path / "projects.yml"
    ruta.write_text(YAML_DEMO, encoding="utf-8")
    return ruta


def test_carga_asiento_y_repos(yaml_demo):
    proyectos = registry.cargar(yaml_demo)
    facturador = next(p for p in proyectos if p.id == "facturador")
    assert facturador.asiento == "/mnt/c/proyects/facturador-main"
    assert len(facturador.todas_las_rutas()) == 3


def test_sincronizar_refleja_altas_y_bajas(con, yaml_demo):
    registry.sincronizar(con, registry.cargar(yaml_demo))
    assert len(api.listar_proyectos(con)) == 2

    # El YAML manda: lo que desaparece de ahí, desaparece del índice.
    yaml_demo.write_text(
        "proyectos:\n  - id: idle\n    nombre: Idle\n", encoding="utf-8"
    )
    registry.sincronizar(con, registry.cargar(yaml_demo))
    assert [p["id"] for p in api.listar_proyectos(con)] == ["idle"]


def test_atribucion_prefiere_la_ruta_mas_larga(yaml_demo):
    """~/dev/facturador-front no debe caer en ~/dev/facturador."""
    atribuidor = Atribuidor(registry.cargar(yaml_demo))
    assert atribuidor.atribuir("/home/ana/dev/facturador-front/apps/web") == "facturador"
    assert atribuidor.atribuir("/home/ana/dev/facturador/apps") == "facturador"
    assert atribuidor.atribuir("/mnt/c/proyects/Idle") == "idle"


def test_atribucion_no_confunde_prefijos_parciales(yaml_demo):
    atribuidor = Atribuidor(registry.cargar(yaml_demo))
    assert atribuidor.atribuir("/home/ana/dev/facturador-otro-repo") is None
    assert atribuidor.atribuir("/home/ana/otra-cosa") is None


def test_un_patron_en_rutas_se_expande_a_los_repos_git_que_existen(tmp_path):
    """Un workspace que contiene repos los declara con `patron:`, no uno a uno."""
    ws = tmp_path / "workspace"
    for nombre in ("ext/repos/a", "ext/repos/b", "int/repos/c", "ext/repos/sin-git"):
        (ws / nombre).mkdir(parents=True)
    (ws / "ext/repos/a/.git").mkdir()
    (ws / "int/repos/c/.git").write_text("gitdir: /otro/sitio")   # un worktree
    (ws / "ext/repos/b/.git").mkdir()
    (ws / "ext/repos/archivo.txt").write_text("no soy un repo")
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    [p] = registry.cargar(yml)
    assert [Path(r.ruta).relative_to(ws).as_posix() for r in p.rutas] == [
        "ext/repos/a", "ext/repos/b", "int/repos/c",
    ]
    assert all(r.tipo == "repo" for r in p.rutas)
    assert p.todas_las_rutas()[-1] == str(ws)


def test_un_patron_sin_coincidencias_no_es_error(tmp_path):
    """Un workspace recién instalado está vacío a propósito: cero rutas, no un fallo."""
    ws = tmp_path / "vacio"
    ws.mkdir()
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    [p] = registry.cargar(yml)
    assert p.rutas == []


def test_un_patron_relativo_sin_asiento_se_rechaza(tmp_path):
    yml = tmp_path / "projects.yml"
    yml.write_text("""
proyectos:
  - id: trabajo
    nombre: Trabajo
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    with pytest.raises(registry.YamlInvalido, match="asiento"):
        registry.cargar(yml)


# ── La sección escrita en línea (`conexiones: []`) ────────────────────────────
#
# 🔴 Este bloque cubre el fallo que dejó el hub entero sin registro, y era de
# PRIMER USO: la plantilla que se publica trae `conexiones: []` —vacía a
# propósito— y `_insertar_bajo_cerrojo` buscaba una línea **exactamente igual**
# a `conexiones:`. Como no casaba, se caía a «no existe la sección» y añadía
# otra al final: clave duplicada. A partir de ahí `projects.yml` no carga, y con
# él se caen el snapshotter, el asistente y todo lo que pida el registro.
#
# Lo que lo dejó pasar fue la comprobación previa: usaba `yaml.safe_load`, que
# admite claves duplicadas en silencio y se queda con la última. Un validador
# más laxo que el lector no valida nada.

PLANTILLA_CON_SECCION_EN_LINEA = """proyectos:
  - id: demo
    nombre: Demo
    asiento: /tmp/demo

# Vacío a propósito: las conexiones reales las declara quien usa el hub.
conexiones: []
"""


def _yml(tmp_path, texto):
    ruta = tmp_path / "projects.yml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_la_primera_conexion_sobre_la_plantilla_no_rompe_el_registro(tmp_path):
    """El caso exacto que lo rompió, y le pasaría a cualquiera recién instalado:
    dar de alta la PRIMERA conexión desde la UI."""
    ruta = _yml(tmp_path, PLANTILLA_CON_SECCION_EN_LINEA)
    registry.añadir_conexion({"alias": "VPS", "host": "h", "usuario": "u"}, ruta=ruta)

    assert [c.alias for c in registry.cargar_conexiones(ruta)] == ["VPS"]
    assert [p.id for p in registry.cargar(ruta)] == ["demo"]
    assert ruta.read_text(encoding="utf-8").count("\nconexiones:") == 1, \
        "se escribió una segunda clave `conexiones`"


def test_la_seccion_en_linea_se_abre_conservando_el_comentario(tmp_path):
    """`projects.yml` se edita a mano (decisión 7): su formato es parte de lo que
    lo hace editable, así que abrir la sección no puede llevarse el comentario
    que explica para qué es."""
    ruta = _yml(tmp_path, PLANTILLA_CON_SECCION_EN_LINEA)
    registry.añadir_conexion({"alias": "VPS"}, ruta=ruta)
    texto = ruta.read_text(encoding="utf-8")
    assert "# Vacío a propósito" in texto
    assert "conexiones: []" not in texto


def test_la_segunda_conexion_se_añade_a_la_misma_seccion(tmp_path):
    ruta = _yml(tmp_path, PLANTILLA_CON_SECCION_EN_LINEA)
    registry.añadir_conexion({"alias": "uno"}, ruta=ruta)
    registry.añadir_conexion({"alias": "dos"}, ruta=ruta)
    assert [c.alias for c in registry.cargar_conexiones(ruta)] == ["uno", "dos"]


def test_una_seccion_en_linea_CON_contenido_no_se_reescribe_a_ciegas(tmp_path):
    """Ahí no se puede insertar un bloque sin reescribir el valor, y reescribir
    a ciegas un archivo que alguien edita a mano es peor que decir que no."""
    ruta = _yml(tmp_path, "proyectos: []\nconexiones: [{alias: ya-estaba}]\n")
    with pytest.raises(registry.YamlInvalido) as exc:
        registry.añadir_conexion({"alias": "nueva"}, ruta=ruta)
    assert "una sola línea" in str(exc.value)
    assert "ya-estaba" in ruta.read_text(encoding="utf-8"), "se tocó el archivo"


def test_sobre_un_registro_ya_roto_el_alta_se_niega_en_vez_de_empeorarlo(tmp_path):
    """Con la clave ya duplicada —el estado en que quedó la máquina— añadir otra
    conexión tiene que fallar limpio y no tocar el archivo.

    🔴 Y una nota honesta sobre lo que este test NO prueba: la comprobación
    previa a escribir pasó de `yaml.safe_load` al lector estricto, y quitarla no
    pone ningún test en rojo. Es correcto que sea así —con `_abrir_seccion`
    arreglado ya no hay forma de generar la clave duplicada, así que esa
    comprobación es un segundo cinturón para el próximo que llame a `_insertar`—
    pero no se puede afirmar que esté cubierta: un validador más laxo que el
    lector no valida nada, y eso hoy sólo lo sostiene la lectura del código.
    """
    ruta = _yml(tmp_path, "proyectos: []\nconexiones:\n  - alias: a\n"
                          "conexiones:\n  - alias: b\n")
    antes = ruta.read_text(encoding="utf-8")
    with pytest.raises(registry.YamlInvalido):
        registry.añadir_conexion({"alias": "nueva"}, ruta=ruta)
    assert ruta.read_text(encoding="utf-8") == antes


def test_dar_de_alta_un_proyecto_sobre_una_seccion_en_linea_tampoco_rompe(tmp_path):
    """El mismo `_insertar` sirve a proyectos y a conexiones: si sólo se
    arreglara para una, la otra seguiría rompiendo el registro."""
    ruta = _yml(tmp_path, "proyectos: []\nconexiones: []\n")
    registry.añadir_proyecto({"id": "nuevo", "nombre": "Nuevo",
                              "asiento": "/tmp/nuevo"}, ruta=ruta)
    assert [p.id for p in registry.cargar(ruta)] == ["nuevo"]
