"""Qué lee una plantilla, sin renderizarla (C-0100).

Las pantallas que arman su vista en `api` se prueban afirmando que `api` da
todo lo que la plantilla lee. Hace falta porque el fallo no se ve: un nombre
que no llega no revienta en Jinja, sale vacío, y la pantalla se sirve en 200
diciendo «no hay nada» donde sí lo hay.

Se lee el árbol de la plantilla con el mismo entorno que usa la web, así que
los filtros y las globales son los de verdad.
"""

from __future__ import annotations

from jinja2 import meta, nodes

from hub import web


def _arbol(plantilla: str) -> nodes.Template:
    entorno = web.plantillas.env
    fuente = entorno.loader.get_source(entorno, plantilla)[0]
    return entorno.parse(fuente)


def nombres(plantilla: str) -> set[str]:
    """Las variables de contexto que lee la plantilla (sin las globales).

    Jinja cuenta como del contexto un `{% set %}` dentro de un bloque que se
    lee en otra rama; lo que la propia plantilla asigna fuera de un bucle no
    viene de la ruta. Lo asignado dentro de un `for` sí cuenta: sólo vive en
    esa vuelta, y fuera el mismo nombre es el del contexto."""
    arbol = _arbol(plantilla)
    propios = {i.target for i in arbol.find_all(nodes.Import)}
    pendientes = [arbol]
    while pendientes:
        n = pendientes.pop()
        if isinstance(n, nodes.For):
            continue
        if isinstance(n, (nodes.Assign, nodes.AssignBlock)):
            propios |= {t.name for t in n.target.find_all(nodes.Name)} | (
                {n.target.name} if isinstance(n.target, nodes.Name) else set())
        pendientes.extend(n.iter_child_nodes())
    return meta.find_undeclared_variables(arbol) - set(web.plantillas.env.globals) - propios


def _leidos(arbol: nodes.Node, nombre: str) -> set[str]:
    campos = set()
    for n in arbol.find_all((nodes.Getattr, nodes.Getitem)):
        if not (isinstance(n.node, nodes.Name) and n.node.name == nombre):
            continue
        if isinstance(n, nodes.Getattr):
            campos.add(n.attr)
        elif isinstance(n.arg, nodes.Const) and isinstance(n.arg.value, str):
            campos.add(n.arg.value)
    return campos


def campos(plantilla: str, nombre: str) -> set[str]:
    """Los campos que lee de `nombre`: `nombre.x` o `nombre['x']`."""
    return _leidos(_arbol(plantilla), nombre)


def _sin_envoltorio(n: nodes.Node) -> nodes.Node:
    # `lista|sort`, `lista[:30]`: lo que se recorre sigue siendo `lista`.
    while isinstance(n, (nodes.Filter, nodes.Getitem)) and n.node is not None:
        n = n.node
    return n


def campos_de_cada(plantilla: str, coleccion: str) -> set[str]:
    """Los campos que lee de cada elemento de `coleccion` en sus `for`."""
    leidos = set()
    for bucle in _arbol(plantilla).find_all(nodes.For):
        origen = _sin_envoltorio(bucle.iter)
        if not (isinstance(origen, nodes.Name) and origen.name == coleccion):
            continue
        if not isinstance(bucle.target, nodes.Name):
            continue
        for parte in (*bucle.body, *bucle.else_):
            leidos |= _leidos(parte, bucle.target.name)
    return leidos
