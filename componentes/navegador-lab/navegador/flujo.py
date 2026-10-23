"""Flujos: lo que el dueño enseñó una vez, convertido en algo que se puede repetir.

De la grabación (código Playwright que escupe `playwright-cli recording-stop`) se
sale a un YAML legible y editable a mano. No se guarda el código: un flujo lo va
a leer una persona para decidir si lo deja correr, y `marcar: {rol: checkbox,
nombre: "{{grupo}}"}` se entiende sin saber Playwright.

🔴 Lo tecleado en un campo que parece de secreto NUNCA se copia: se sustituye
por un parámetro `secreto_N` y se avisa. La grabación en crudo sí lo lleva, por
eso no se guarda (ver `grabar`).
"""
import re
from dataclasses import dataclass

import yaml

PARECE_SECRETO = re.compile(r"contrase|password|passw|secret|token|clave|mfa|otp|c[oó]digo", re.I)

ACCIONES = {"click": "pulsar", "dblclick": "doble_clic", "check": "marcar", "uncheck": "desmarcar",
            "fill": "rellenar", "press": "tecla", "selectOption": "elegir", "hover": "encima"}
LOCALIZADORES = {"getByRole": "rol", "getByLabel": "etiqueta", "getByText": "texto",
                 "getByPlaceholder": "marcador", "getByTestId": "testid", "locator": "css"}


class NoEntiendo(ValueError):
    pass


def _cadena(s: str, i: int) -> tuple[str, int]:
    q = s[i]
    out, i = [], i + 1
    while s[i] != q:
        if s[i] == "\\":
            i += 1
            out.append({"n": "\n", "t": "\t"}.get(s[i], s[i]))
        else:
            out.append(s[i])
        i += 1
    return "".join(out), i + 1


def _args(s: str) -> list:
    """Argumentos de una llamada JS de grabación: cadenas, números, true/false y
    objetos planos `{ name: '…', exact: true }`. Lo justo para lo que graba Playwright."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c in "'\"`":
            v, i = _cadena(s, i)
            out.append(v)
        elif c == "{":
            obj, i = {}, i + 1
            while s[i] != "}":
                m = re.match(r"\s*(\w+)\s*:\s*", s[i:])
                if not m:
                    i += 1
                    continue
                i += m.end()
                if s[i] in "'\"`":
                    v, i = _cadena(s, i)
                else:
                    m2 = re.match(r"[\w.]+", s[i:])
                    v = {"true": True, "false": False}.get(m2.group(), m2.group())
                    i += m2.end()
                obj[m.group(1)] = v
                while s[i] in " ,\n":
                    i += 1
            out.append(obj)
            i += 1
        elif c.isdigit():
            m = re.match(r"\d+", s[i:])
            out.append(int(m.group()))
            i += m.end()
        else:
            i += 1
    return out


def _llamadas(expr: str) -> list[tuple[str, list]]:
    """`page.getByRole('x', {..}).first().click()` → [(getByRole, args), (first, []), (click, [])]."""
    out, i = [], 0
    expr = expr.strip()
    if not expr.startswith("page."):
        raise NoEntiendo(expr)
    i = 5
    while i < len(expr):
        m = re.match(r"(\w+)\(", expr[i:])
        if not m:
            raise NoEntiendo(expr)
        nombre, i = m.group(1), i + m.end()
        prof, ini, cad = 1, i, None
        while prof:
            c = expr[i]
            if cad:
                if c == "\\":
                    i += 1
                elif c == cad:
                    cad = None
            elif c in "'\"`":
                cad = c
            elif c == "(":
                prof += 1
            elif c == ")":
                prof -= 1
            i += 1
        out.append((nombre, _args(expr[ini:i - 1])))
        if i < len(expr) and expr[i] == ".":
            i += 1
    return out


def paso_de_linea(linea: str) -> dict:
    linea = linea.strip().removeprefix("await ").rstrip(";")
    llamadas = _llamadas(linea)
    if llamadas[0][0] == "goto":
        return {"ir": llamadas[0][1][0]}
    loc, accion = {}, None
    for nombre, args in llamadas:
        if nombre in LOCALIZADORES:
            clave = LOCALIZADORES[nombre]
            loc[clave] = args[0]
            if nombre == "getByRole" and len(args) > 1:
                if "name" in args[1]:
                    loc["nombre"] = args[1]["name"]
                if args[1].get("exact"):
                    loc["exacto"] = True
        elif nombre == "first":
            loc["n"] = 0
        elif nombre == "nth":
            loc["n"] = args[0]
        elif nombre in ACCIONES:
            accion = (ACCIONES[nombre], args)
        else:
            raise NoEntiendo(linea)
    if not loc or not accion:
        raise NoEntiendo(linea)
    verbo, args = accion
    if verbo in ("rellenar", "tecla", "elegir"):
        clave = {"rellenar": "valor", "tecla": "tecla", "elegir": "valor"}[verbo]
        return {verbo: {**loc, clave: args[0]}}
    return {verbo: loc}


@dataclass
class Conversion:
    flujo: dict
    avisos: list[str]


def convertir(codigo: str, nombre: str, descripcion: str = "",
              parametros: dict[str, str] | None = None) -> Conversion:
    """Grabación → flujo. `parametros` = {nombre: valor literal}: cada aparición
    del valor en los pasos pasa a `{{nombre}}`, que es lo que hace el flujo
    reutilizable (otra región, otro grupo de logs, otra consulta)."""
    pasos, avisos, secretos = [], [], 0
    for linea in codigo.splitlines():
        l = linea.strip()
        if not l.startswith("await page."):
            continue
        try:
            paso = paso_de_linea(l)
        except NoEntiendo:
            avisos.append(f"No entiendo esta línea y la dejo fuera: {l[:120]}")
            continue
        verbo, cuerpo = next(iter(paso.items()))
        if verbo == "rellenar":
            pista = " ".join(str(cuerpo.get(k, "")) for k in ("nombre", "etiqueta", "marcador", "css"))
            if PARECE_SECRETO.search(pista):
                secretos += 1
                cuerpo["valor"] = f"{{{{secreto_{secretos}}}}}"
                avisos.append(f"Campo «{pista.strip()}» parece un secreto: su valor NO se guardó "
                              f"(queda como secreto_{secretos}; lo teclea el dueño o va en la bóveda).")
        # Pulsar el campo y seleccionar todo antes de rellenarlo es cómo lo hace
        # una persona; `rellenar` ya vacía el campo, así que al repetir sobra.
        if verbo == "rellenar":
            mismo = {k: v for k, v in cuerpo.items() if k != "valor"}
            while pasos and (pasos[-1].get("pulsar") == mismo or
                             {k: v for k, v in (pasos[-1].get("tecla") or {}).items() if k != "tecla"} == mismo):
                pasos.pop()
        pasos.append(paso)
    def reemplazar(v, valor, marca):
        if isinstance(v, str):
            return v.replace(valor, marca)
        if isinstance(v, dict):
            return {k: reemplazar(x, valor, marca) for k, x in v.items()}
        if isinstance(v, list):
            return [reemplazar(x, valor, marca) for x in v]
        return v
    declarados = {}
    # Los valores más largos primero: si uno contiene a otro, el corto no debe
    # partir al largo por la mitad.
    for p, valor in sorted((parametros or {}).items(), key=lambda kv: -len(kv[1])):
        if valor not in yaml.safe_dump(pasos, allow_unicode=True):
            avisos.append(f"El parámetro {p} = {valor!r} no aparece en la grabación.")
            continue
        pasos = reemplazar(pasos, valor, f"{{{{{p}}}}}")
        declarados[p] = {"ejemplo": valor}
    for i in range(1, secretos + 1):
        declarados[f"secreto_{i}"] = {"secreto": True}
    flujo = {"nombre": nombre, "descripcion": descripcion, "modo": "lectura",
             "parametros": declarados, "pasos": pasos}
    return Conversion(flujo, avisos)


def sustituir(valor, params: dict):
    """`{{x}}` → params[x]. `{{api.ID}}` (con punto) es la variable de un
    `para_cada` y se deja para cuando el bucle la conozca, salvo que ya esté."""
    if isinstance(valor, str):
        def rep(m):
            k = m.group(1)
            if k in params:
                return str(params[k])
            if "." in k:
                return m.group(0)
            raise KeyError(f"falta el parámetro {k}")
        return re.sub(r"\{\{([\w.]+)\}\}", rep, valor)
    if isinstance(valor, dict):
        return {k: sustituir(v, params) for k, v in valor.items()}
    if isinstance(valor, list):
        return [sustituir(v, params) for v in valor]
    return valor


def componer(nombre: str, fragmentos: list[dict], descripcion: str = "") -> Conversion:
    """Varios fragmentos en orden → un flujo que los usa uno tras otro.

    `fragmentos` son los flujos tal cual (con su `nombre`, `parametros` y
    `pantallas`). Los parámetros del compuesto son la unión: un mismo nombre
    (`region`, `base`) es el mismo valor en todos, que es lo que se quiere casi
    siempre; si no, se renombra en el YAML. Avisa cuando un fragmento no
    termina en la pantalla donde empieza el siguiente: puede ser a propósito
    (un `ir` explícito), pero suele ser un hueco.
    """
    avisos, params, pasos = [], {}, []
    for i, f in enumerate(fragmentos):
        propios = {k: d for k, d in (f.get("parametros") or {}).items() if not (d or {}).get("secreto")}
        for k, d in propios.items():
            params.setdefault(k, d or {})
        pasos.append({"usar": {"flujo": f["coleccion"] + "/" + f["nombre"] if f.get("coleccion") else f["nombre"],
                               "con": {k: "{{" + k + "}}" for k in propios}}})
        if i:
            antes = (fragmentos[i - 1].get("pantallas") or {}).get("hasta")
            ahora = (f.get("pantallas") or {}).get("desde")
            if antes and ahora and antes != ahora:
                avisos.append(f"«{fragmentos[i - 1]['nombre']}» termina en {antes} y «{f['nombre']}» "
                              f"empieza en {ahora}: falta algo que lleve de una a otra.")
    pant = {}
    if fragmentos:
        d = (fragmentos[0].get("pantallas") or {}).get("desde")
        h = (fragmentos[-1].get("pantallas") or {}).get("hasta")
        pant = {k: v for k, v in (("desde", d), ("hasta", h)) if v}
    flujo = {"nombre": nombre, "descripcion": descripcion, "modo": "lectura",
             **({"pantallas": pant} if pant else {}), "parametros": params, "pasos": pasos}
    return Conversion(flujo, avisos)
