"""Las nueve secciones de la interfaz nueva (C-0169).

Lo que se protege: que ninguna pantalla del raíl de siempre se quede sin
camino en el nuevo, que cada destino exista de verdad, y que las secciones
sólo recoloquen las cifras que el raíl ya daba —ni una señal nueva—.
"""

from __future__ import annotations

import re
from pathlib import Path

from hub import api, navegacion, web

PLANTILLAS = Path(web.__file__).parent / "templates"

# Las entradas del raíl de siempre: `('/ruta', 'clave', 'Nombre', 'icono')` en
# los grupos y `entrada_rail('/ruta', 'clave', …)` arriba.
_ENTRADA = re.compile(r"\('(/[a-z]*)', '([a-z]+)', ")


def _del_rail_de_siempre() -> set[tuple[str, str]]:
    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    return set(_ENTRADA.findall(base))


def _pantallas() -> list[dict]:
    return [p for s in navegacion.SECCIONES for p in s["pantallas"]]


def test_toda_pantalla_del_rail_de_siempre_tiene_seccion_en_el_nuevo():
    de_siempre = _del_rail_de_siempre()
    assert len(de_siempre) >= 20, f"sólo {len(de_siempre)}: ¿cambió cómo se escribe el raíl?"
    nuevas = {(p["ruta"], p["clave"]) for p in _pantallas()}
    assert not de_siempre - nuevas, (
        f"pantallas del raíl de siempre sin sitio en `navegacion.SECCIONES`: {sorted(de_siempre - nuevas)}")
    for _, clave in de_siempre:
        assert navegacion.de_pantalla(clave), clave


def test_son_nueve_secciones_y_ninguna_clave_se_repite():
    assert [s["clave"] for s in navegacion.SECCIONES] == [
        "hoy", "secretario", "trabajo", "proyectos", "ideas", "salud", "herramientas", "fuera", "ajustes"]
    claves = [p["clave"] for p in _pantallas()]
    assert len(claves) == len(set(claves)), "una clave en dos secciones: no se sabría dónde estás"
    rutas = [p["ruta"] for p in _pantallas()]
    assert len(rutas) == len(set(rutas))


def test_cada_destino_es_una_ruta_get_que_existe():
    rutas = {r.path for r in web.app.routes if "GET" in getattr(r, "methods", set())}
    for p in _pantallas():
        assert p["ruta"].split("?")[0] in rutas, p["ruta"]


def test_la_barra_del_telefono_son_cuatro_secciones_que_existen():
    claves = {s["clave"] for s in navegacion.SECCIONES}
    assert navegacion.BARRA == ("secretario", "trabajo", "hoy", "ideas")
    assert set(navegacion.BARRA) <= claves


def test_la_direccion_manda_sobre_la_clave_de_la_vista():
    # Su vista dice «orquestador», pero son permisos: Ajustes.
    assert navegacion.de_pantalla("orquestador", "/orquestador/permisos") == "ajustes"
    assert navegacion.de_pantalla("orquestador", "/orquestador") == "ideas"
    # La ficha de un proyecto se pinta con la sección de Panorama.
    assert navegacion.de_pantalla("panorama", "/proyecto/demo") == "proyectos"
    assert navegacion.de_pantalla("panorama", "/") == "hoy"
    # El detalle de una reunión no está en la lista: vale la clave.
    assert navegacion.de_pantalla("reuniones", "/reuniones/20261020-090000") == "herramientas"
    assert navegacion.de_pantalla("", "/no-existe") is None
    assert navegacion.de_pantalla(None) is None


def test_toda_seccion_que_dice_una_vista_existe_en_el_reparto():
    """Cada `"seccion": "…"` que una ruta pasa a su plantilla tiene sitio. El
    raíl de siempre no las lista todas (el banco de dictado no está en él)."""
    fuente = Path(web.__file__).read_text(encoding="utf-8")
    dichas = set(re.findall(r'"seccion": "([a-z_]+)"', fuente))
    assert {"panorama", "trabajo", "banco", "guia"} <= dichas
    sin_sitio = sorted(c for c in dichas if navegacion.de_pantalla(c) is None)
    assert not sin_sitio, f"vistas con una sección que `navegacion.SECCIONES` no conoce: {sin_sitio}"


def test_las_pestanas_de_ajuste_del_secretario_son_de_ajustes():
    """Las mismas que su vista llama «ajustes»: todo lo que no es suyo."""
    for pestana in ("avisos", "fuentes", "confianza", "disparadores", "personaje", "ajustes"):
        ruta = f"/secretario?p={pestana}"
        assert navegacion.de_pantalla("secretario", ruta) == "ajustes", pestana
        assert navegacion.pantalla_actual("secretario", ruta) == "secretario_ajustes", pestana
    for ruta in ("/secretario", "/secretario?p=conversacion", "/secretario?p=pendientes&aviso=Hecho",
                 "/secretario?p=memoria", "/secretario?aviso=Hecho"):
        assert navegacion.de_pantalla("secretario", ruta) == "secretario", ruta
        assert navegacion.pantalla_actual("secretario", ruta) == "secretario", ruta
    # La misma lista que usa la vista para decidir qué pestaña es de ajuste.
    fuente = Path(api.__file__).read_text(encoding="utf-8")
    assert f'pestana if pestana in {navegacion._PESTANAS_DEL_SECRETARIO!r}'.replace("'", '"') in fuente


def test_la_consulta_de_una_direccion_no_la_saca_de_su_seccion():
    assert navegacion.de_pantalla("trabajo", "/trabajo?slot=3") == "trabajo"
    assert navegacion.pantalla_actual("orquestador", "/orquestador?tarea=t-1") == "orquestador"
    assert navegacion.de_pantalla("banco", "/voz/banco?aparato=pc") == "ajustes"


def test_la_pantalla_en_la_que_estas_se_marca_por_su_direccion():
    assert navegacion.pantalla_actual("orquestador", "/orquestador/permisos") == "orquestador_permisos"
    assert navegacion.pantalla_actual("respaldo", "/respaldo") == "respaldo"
    # En la ficha de un proyecto no se está en ninguna de las de la tira.
    assert navegacion.pantalla_actual("panorama", "/proyecto/demo") is None
    assert navegacion.pantalla_actual("", "/no-existe") is None


_RAIL = {"navegante_pendientes": 2, "sin_respaldo": 7, "secretario_pendientes": 3, "servicios": 4,
         "paneles": 5, "version": {"hay_nueva": True, "falta_terminar": False},
         "secretario_nombre": "Ada"}


def _por_clave(secciones):
    return {s["clave"]: s for s in secciones}


def test_cada_seccion_suma_lo_que_urge_dentro_y_no_inventa_cifras():
    s = _por_clave(navegacion.con_cifras(_RAIL))
    assert s["secretario"]["urge"] == 3
    assert s["salud"]["urge"] == 7           # los commits sin respaldo
    assert s["herramientas"]["urge"] == 2    # lo que espera en el navegante
    assert s["ajustes"]["urge"] == 1         # hay versión nueva
    assert s["trabajo"]["cuenta"] == 5 and s["trabajo"]["urge"] == 0
    # Los servicios en marcha informan, no urgen: se quedan en su pantalla.
    assert s["salud"]["cuenta"] == 0
    servicios = next(p for p in s["salud"]["pantallas"] if p["clave"] == "servicios")
    assert servicios["cuenta"] == 4 and servicios["urge"] == 0
    for clave in ("hoy", "proyectos", "ideas", "fuera"):
        assert s[clave]["urge"] == 0 and s[clave]["cuenta"] == 0, clave


def test_sin_nada_pendiente_ninguna_seccion_lleva_cifra():
    for s in navegacion.con_cifras({}):
        assert s["urge"] == 0 and s["cuenta"] == 0, s["clave"]
        assert all(p["urge"] == 0 and p["cuenta"] == 0 for p in s["pantallas"])


def test_las_cifras_salen_solo_de_lo_que_el_rail_de_siempre_ya_ensenaba():
    """Ni «te esperan N» ni puntos nuevos (roza la decisión 379): las mismas
    claves de `api.rail` que lee `entrada_rail` en la base de siempre."""
    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    macro = base.split("{% macro entrada_rail")[1].split("{% endmacro %}")[0]
    de_siempre = set(re.findall(r"rail\.(\w+)", macro)) - {"version"}
    assert {origen for _, origen in navegacion._CIFRAS.values()} == de_siempre


def test_el_secretario_lleva_el_nombre_que_le_puso_el_dueno():
    s = _por_clave(navegacion.con_cifras(_RAIL))
    assert s["secretario"]["nombre"] == "Ada" and s["secretario"]["corto"] == "Ada"
    assert s["secretario"]["pantallas"][0]["nombre"] == "Ada"
    assert _por_clave(navegacion.con_cifras({}))["secretario"]["nombre"] == "Secretario"
    # Y nunca el de la maqueta, escrito.
    for archivo in (Path(navegacion.__file__), *(PLANTILLAS / "nueva").rglob("*.html")):
        assert "Lía" not in archivo.read_text(encoding="utf-8"), archivo.name


def test_la_tira_solo_sale_donde_hay_mas_de_una_pantalla_y_no_trae_su_barra():
    s = _por_clave(navegacion.con_cifras({}))
    assert not s["hoy"]["tira"] and not s["trabajo"]["tira"]
    assert not s["secretario"]["tira"]      # su pantalla ya trae su barra
    assert s["salud"]["tira"] and s["ajustes"]["tira"] and s["ideas"]["tira"]
    assert [x["clave"] for x in navegacion.con_cifras({}) if x["en_barra"]] == ["hoy", "secretario", "trabajo", "ideas"]
    assert s["ideas"]["corto"] == "Ideas" and s["ideas"]["nombre"] == "Ideas y tareas"


def test_el_rail_trae_las_secciones_con_sus_cifras(con):
    rail = api.rail(con)
    assert [s["clave"] for s in rail["secciones"]] == [s["clave"] for s in navegacion.SECCIONES]
    assert _por_clave(rail["secciones"])["secretario"]["urge"] == rail["secretario_pendientes"]
    assert _por_clave(rail["secciones"])["trabajo"]["cuenta"] == rail["paneles"]
