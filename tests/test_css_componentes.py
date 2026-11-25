"""Que nadie vuelva a pisar los componentes compartidos con un selector suelto.

`.placa` y `.insignia` son `<span>`. Cualquier regla de la forma `X span { … }`
los alcanza con más especificidad (0,1,1) que su propia clase (0,1,0) y les
cambia por debajo el `display`, el color o el tamaño de letra.

Pasó de verdad el 2026-08-29: `.cifra span { display:block; color:var(--texto-3) }`
convertía la placa en un bloque —con lo que `place-items:center` dejaba de
aplicar y el icono se pegaba a la esquina superior izquierda— y además le
imponía el gris encima de su tinte, así que el escudo de «commits sin respaldo»
salía apagado dentro de un cuadro rojo. No se ve leyendo el CSS; se vio
midiendo. Este test lo caza sin navegador.

La regla que impone: escribe `X > span:not(.placa)`, nunca `X span`. Acotar al
hijo directo y excluir el componente cuesta once caracteres y hace explícito a
quién apunta la regla.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hub import interfaz, web

PLANTILLAS = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates"


def _nombre(archivo: Path) -> str:
    """`nueva/base.html` y `base.html` son dos archivos: el id lleva la carpeta."""
    return str(archivo.relative_to(PLANTILLAS)) if archivo.is_relative_to(PLANTILLAS) else archivo.name


def _css_servido(cual: str) -> str:
    """Los `<style>` de la base tal como se sirve con cada interfaz (C-0169).

    La base nueva no trae `<style>` propio: escribe dentro de los bloques de
    la de siempre, así que su CSS sólo existe una vez pintada. Mirar lo
    servido cubre las dos sin que ninguna se escape por cómo está escrita."""
    html = web._PLANTILLAS[cual].get_template("base.html").render(titulo="x")
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))


INTERFACES = sorted(web._PLANTILLAS)

# Un selector de span descendiente: algo, un espacio, `span`, y a continuación
# el inicio del bloque o una coma. Lo que lleva `>` o `:not(` queda fuera.
SPAN_SUELTO = re.compile(r"^[^@{}\n]*[^>\s][ ]span\s*(?:,|\{)", re.MULTILINE)


@pytest.mark.parametrize("archivo", sorted(PLANTILLAS.rglob("*.html")), ids=_nombre)
def test_sin_selectores_que_pisen_las_placas(archivo: Path) -> None:
    css = "\n".join(re.findall(r"<style>(.*?)</style>", archivo.read_text(), re.S))
    # Sin comentarios: ahí se escribe *sobre* los selectores, y el lint se
    # denunciaba a sí mismo al leer la nota que explica esta misma regla.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    culpables = [m.group(0).strip() for m in SPAN_SUELTO.finditer(css)]
    assert not culpables, (
        f"{_nombre(archivo)}: selector de span descendiente sin acotar: {culpables}. "
        "`.placa` y `.insignia` son spans y quedan dentro del alcance. "
        "Usa `> span:not(.placa)`."
    )


@pytest.mark.parametrize("cual", INTERFACES)
def test_el_marco_servido_tampoco_pisa_las_placas(cual: str) -> None:
    """La base de la interfaz nueva escribe su CSS en bloques, sin `<style>`:
    el test de arriba no lo vería. Aquí se mira lo que llega al navegador."""
    css = re.sub(r"/\*.*?\*/", "", _css_servido(cual), flags=re.S)
    assert ".rail-global" in css, "no se ha pintado la base"
    culpables = [m.group(0).strip() for m in SPAN_SUELTO.finditer(css)]
    assert not culpables, f"interfaz {cual}: selector de span descendiente sin acotar: {culpables}"


# ── los tokens del sistema visual (C-0110) ────────────────────────────────────
#
# CLAUDE.md: «usa los tokens y sus radios, nunca valores literales». Un radio
# de 9, 10 o 16 px escrito a mano es uno de `--r-boton`, `--r-input`/`--r-nav`
# o `--r-tarjeta` que no se enterará si el token cambia: la interfaz se
# descose sin que nadie toque esa línea. Desde C-0403 también 11 (`--r-pop`),
# 12 (`--r-cifra`) y la píldora (`--r-pildora`, escrita 999 o 9999 px). Lo
# que no es de ningún token (3, 5, 7, 8 px) no se mira aquí.

ESTATICOS = PLANTILLAS.parent / "static"
VENDORIZADOS = {"xterm.css"}   # no son nuestros: se copian tal cual
RADIO = re.compile(r"radius\s*:\s*([^;}\"]*)")
VALOR_DE_TOKEN = re.compile(r"(?<![\d.])(9|10|11|12|16|999|9999)px")


def _sin_comentarios(texto: str) -> str:
    return re.sub(r"\{#.*?#\}|/\*.*?\*/", "", texto, flags=re.S)


@pytest.mark.parametrize(
    "archivo",
    sorted([*PLANTILLAS.rglob("*.html"),
            *(c for c in ESTATICOS.glob("*.css") if c.name not in VENDORIZADOS)]),
    ids=_nombre)
def test_un_radio_que_ya_es_token_se_escribe_con_su_token(archivo: Path) -> None:
    texto = _sin_comentarios(archivo.read_text(encoding="utf-8"))
    culpables = [m.group(0).strip() for m in RADIO.finditer(texto) if VALOR_DE_TOKEN.search(m.group(1))]
    assert not culpables, (
        f"{_nombre(archivo)}: radio literal con el valor de un token: {culpables}. "
        "9px es `--r-boton`, 10px `--r-input` (o `--r-nav` en la navegación), 11px `--r-pop`, "
        "12px `--r-cifra`, 16px `--r-tarjeta` y 999/9999px `--r-pildora`.")


#: Los `<input>` que no son un campo de texto: o tienen su propio dibujo
#: (casilla, botón, archivo, deslizador) o no se ven.
NO_SON_CAMPO = {"hidden", "checkbox", "radio", "submit", "button", "reset", "image", "file", "range", "color"}


def _selectores_de_campo() -> set[str]:
    """Los selectores de la regla de campo de `base.html`: la que acaba en `textarea, select`."""
    css = _sin_comentarios((PLANTILLAS / "base.html").read_text(encoding="utf-8"))
    regla = re.search(r"\}\s*([^{}]*\btextarea,\s*select)\s*\{", css)
    assert regla, "base.html ya no tiene la regla de campo"
    return {" ".join(s.split()) for s in regla.group(1).split(",")}


def test_todo_campo_de_las_plantillas_casa_con_el_estilo_de_campo_de_base() -> None:
    """Un `<input>` sin `type`, o de un tipo que la regla no nombra, sale con
    el gris del navegador junto a los del sistema: parecía de otra aplicación
    (C-0339, medido en /acceso, /reuniones, /navegante y el nombre del
    secretario). Escribir `type="text"` en cada uno no basta: el siguiente que
    falte vuelve a salir gris; por eso la regla cubre los tipos, no las plantillas."""
    cubiertos = _selectores_de_campo()
    culpables = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        texto = archivo.read_text(encoding="utf-8")
        for m in re.finditer(r"<input\b[^>]*>", texto, re.S):
            tipo = re.search(r"\btype=[\"']?([\w-]+)", m.group(0))
            tipo = tipo.group(1).lower() if tipo else None
            if tipo in NO_SON_CAMPO:
                continue
            selector = f"input[type={tipo}]" if tipo else "input:not([type])"
            if selector not in cubiertos:
                culpables.append(f"{_nombre(archivo)}:{texto.count(chr(10), 0, m.start()) + 1} {selector}")
    assert not culpables, f"campos sin el estilo del sistema: {culpables}"


def _bloques_media(css: str, consulta: str) -> list[str]:
    """El cuerpo de cada `@media <consulta> { … }`, contando llaves."""
    cuerpos = []
    for m in re.finditer(r"@media\s*" + re.escape(consulta) + r"\s*\{", css):
        nivel, i = 1, m.end()
        while nivel:
            nivel += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        cuerpos.append(css[m.end():i - 1])
    return cuerpos


@pytest.mark.parametrize("cual", INTERFACES)
def test_en_un_telefono_ningun_campo_tiene_menos_de_16_px(cual: str) -> None:
    """Safari en iOS amplía la página al tocar un campo de menos de 16 px y no
    la devuelve sola (C-0340: el 100 % de los campos de cada pantalla, también
    el cuadro del secretario). Con el dedo, todos a 16 px y con `!important`:
    es un mínimo de accesibilidad, como `prefers-reduced-motion`, y tiene que
    ganar a cada plantilla que afina su campo a 12 o 13 px."""
    css = _sin_comentarios(_css_servido(cual))
    campos = _selectores_de_campo()
    reglas = [r for cuerpo in _bloques_media(css, "(pointer: coarse)")
              for r in re.finditer(r"([^{}]+)\{([^}]*)\}", cuerpo)]
    cubren = [r for r in reglas
              if campos <= {" ".join(s.split()) for s in r.group(1).split(",")}
              and re.search(r"font-size\s*:\s*16px\s*!important", r.group(2))]
    assert cubren, f"interfaz {cual}: ninguna regla con el dedo lleva los campos a 16 px"


@pytest.mark.parametrize("cual", INTERFACES)
def test_el_texto_de_ejemplo_se_pinta_con_el_tono_que_desaparece(cual: str) -> None:
    """Con `--texto-3`, el del texto secundario de verdad, «Trabajo, Familia»
    parecía un filtro ya puesto (C-0342). `--texto-4` es el que el propio
    `:root` reserva para los placeholders."""
    css = _sin_comentarios(_css_servido(cual))
    regla = re.search(r"input::placeholder\s*,\s*textarea::placeholder\s*\{([^}]*)\}", css)
    assert regla, "falta la regla del texto de ejemplo"
    assert re.search(r"color\s*:\s*var\(--texto-4\)", regla.group(1)), regla.group(1)


def test_un_ejemplo_que_parece_un_valor_lleva_p_ej_delante() -> None:
    """En Fuentes y Disparadores el ejemplo es justo lo que se escribiría:
    sin «p. ej.» se confunde con lo guardado (C-0342)."""
    texto = (PLANTILLAS / "secretario.html").read_text(encoding="utf-8")
    for nombre in ("incluir", "conversacion", "menciona", "pide"):
        campo = re.search(r"<(?:input|textarea)\b[^>]*\bname=\"" + nombre + r"\"[^>]*>", texto, re.S)
        assert campo, nombre
        ejemplo = re.search(r"placeholder=\"([^\"]*)\"", campo.group(0))
        assert ejemplo and ejemplo.group(1).startswith("p. ej. "), (nombre, ejemplo and ejemplo.group(1))


def _contraste(a: str, b: str) -> float:
    """Contraste WCAG 2.x entre dos colores `#rrggbb`."""
    def luz(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    claro, oscuro = sorted((luz(a), luz(b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def _tokens_de_siempre() -> dict[str, str]:
    raiz = re.search(r":root\s*\{(.*?)\n\}", (PLANTILLAS / "base.html").read_text(encoding="utf-8"), re.S)
    return dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\b", raiz.group(1)))


def test_el_cuarto_tono_de_texto_se_lee_sobre_el_lienzo_y_la_superficie() -> None:
    """`--texto-4` viste cifras que hay que leer: la cuenta del raíl (11 px
    sobre la superficie), los ejes de las gráficas, las horas de Encargos y
    Reuniones. Daba 4,34:1 sobre el lienzo y 4,02 sobre la superficie, por
    debajo del 4,5 de WCAG AA para texto pequeño (C-0343). Y tiene que seguir
    un escalón por debajo de `--texto-3`, o un ejemplo volvería a parecer un
    valor escrito (C-0342). La interfaz nueva lleva sus propios tonos."""
    t = _tokens_de_siempre()
    assert _contraste(t["texto-4"], t["lienzo"]) >= 4.5
    assert _contraste(t["texto-4"], t["superficie"]) >= 4.5
    assert _contraste(t["texto-3"], t["texto-4"]) >= 1.3


def test_lo_que_se_lee_sobre_superficie2_no_usa_el_cuarto_tono() -> None:
    """Sobre `--superficie2` ni el `--texto-4` nuevo llega a 4,5:1 (da 4,12):
    el pie del modelo bajo cada respuesta del secretario y el «nada coincide»
    del selector van con `--texto-3` (C-0343)."""
    sitios = {
        ESTATICOS / "chat-secretario.css": r"\.burbuja \.pie\s*\{([^}]*)\}",
        PLANTILLAS / "base.html": r"\.combo-vacio\s*\{([^}]*)\}",
    }
    for ruta, patron in sitios.items():
        regla = re.search(patron, _sin_comentarios(ruta.read_text(encoding="utf-8")))
        assert regla, f"{ruta.name}: {patron}"
        assert "var(--texto-3)" in regla.group(1), f"{ruta.name}: {regla.group(1).strip()}"


def _px(cuerpo: str, propiedad: str) -> list[float]:
    m = re.search(r"(?<![\w-])" + propiedad + r"\s*:\s*([^;]+)", cuerpo)
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)px", m.group(1))] if m else []


def test_en_trabajo_con_el_telefono_cada_entrada_del_rail_mide_44_px() -> None:
    """En /trabajo el raíl se queda en iconos con `padding: 9px 0`, y el
    teléfono no le devolvía el lado: medido, 16×37 px por entrada, diez
    objetivos pegados en la pantalla que más se usa (C-0344)."""
    css = _sin_comentarios(_css_servido(interfaz.CLASICA))
    reglas = [r.group(2) for cuerpo in _bloques_media(css, "(max-width: 860px)")
              for r in re.finditer(r"([^{}]+)\{([^}]*)\}", cuerpo)
              if "body.completo .rail-global .enlace" in [" ".join(s.split()) for s in r.group(1).split(",")]]
    assert reglas, "el teléfono no tiene regla para el raíl de /trabajo"
    cuerpo = reglas[-1]
    assert _px(cuerpo, "min-width") == [44] and _px(cuerpo, "min-height") == [44], cuerpo
    relleno = _px(cuerpo, "padding")
    assert len(relleno) == 2 and relleno[1] > 0, f"sin relleno a los lados: {cuerpo}"


def _reglas_en(css: str, consulta: str) -> dict[str, str]:
    """Selector → cuerpo de cada regla dentro de los `@media <consulta>`."""
    return {" ".join(r.group(1).split()): r.group(2)
            for cuerpo in _bloques_media(css, consulta)
            for r in re.finditer(r"([^{}]+)\{([^}]*)\}", cuerpo)}


@pytest.mark.parametrize("cual", INTERFACES)
def test_en_el_telefono_la_paleta_pone_cada_resultado_en_tres_lineas(cual: str) -> None:
    """En fila, la clase de 74 px fijos y el detalle en una línea le dejaban al
    título una columna de una palabra: «Kit de / consulta / por / Telegram»
    (C-0346). Por debajo de 600 px: la clase encima, el título en una línea y
    el detalle debajo, los dos con elipsis."""
    reglas = _reglas_en(_sin_comentarios(_css_servido(cual)), "(max-width: 600px)")
    fila = reglas.get("dialog.paleta li", "")
    assert re.search(r"display\s*:\s*grid", fila), fila
    titulo = reglas.get("dialog.paleta li .titulo", "")
    assert "nowrap" in titulo and "ellipsis" in titulo, titulo
    assert re.search(r"min-width\s*:\s*0", reglas.get("dialog.paleta li .clase", "")), "la clase sigue fijando 74 px"


@pytest.mark.parametrize("cual", INTERFACES)
def test_con_el_dedo_botones_y_plegables_miden_44_px_fuera_del_chat(cual: str) -> None:
    """Medido a 390 px: 170 controles de menos de 24 px en Intercambio, 131 en
    Respaldo, 36 en Navegante (C-0348). Con el dedo, un suelo de 44 px para lo
    que se pulsa. Con peso cero (`:where`): una pantalla que ya eligió su alto
    —la barra de teclas de /trabajo, 36 px— lo conserva. El chat tiene su
    propio arreglo (UI-47) y el raíl lo miden C-0344 y C-0345."""
    reglas = _reglas_en(_sin_comentarios(_css_servido(cual)), "(pointer: coarse)")
    alto = [(s, c) for s, c in reglas.items() if _px(c, "min-height") == [44]]
    assert alto, f"interfaz {cual}: sin suelo de 44 px con el dedo"
    selector, cuerpo = alto[0]
    assert selector.startswith(":where(") and ":not(:where(" in selector, selector
    for objetivo in ("button", "a.boton", "summary", ".chip-filtro", ".panel a.fila"):
        assert objetivo in selector.split(":not(")[0], (objetivo, selector)
    for fuera in (".conv-chat", "#secretario-panel", ".rail-global"):
        assert fuera in selector.split(":not(")[1], (fuera, selector)
    ancho = [s for s, c in reglas.items() if _px(c, "min-width") == [44]]
    assert any("icono-solo" in s and ".menu > summary" in s for s in ancho), ancho


@pytest.mark.parametrize("cual", INTERFACES)
def test_en_el_telefono_las_cifras_van_de_dos_en_dos(cual: str) -> None:
    """Una por fila, cuatro cifras llenaban la primera pantalla de Respaldo,
    Servicios, Inventario y Consumo (C-0348)."""
    reglas = _reglas_en(_sin_comentarios(_css_servido(cual)), "(max-width: 600px)")
    cifras = reglas.get(".cifras", "")
    assert re.search(r"display\s*:\s*grid", cifras) and "repeat(2, minmax(0, 1fr))" in cifras, cifras
    assert re.search(r"flex-wrap\s*:\s*wrap", reglas.get(".cifra", "")), "una cifra larga se saldría de su celda"


#: La regla de la casilla con su texto (C-0341). `:where` deja el peso en el
#: de `label` (0,0,1): gana a la versalita de rótulo por ir detrás y cualquier
#: clase de una plantilla le sigue ganando a ella.
CASILLA = "label:where(:has(> input[type=checkbox], > input[type=radio]))"


@pytest.mark.parametrize("cual", INTERFACES)
def test_una_casilla_se_lee_como_opcion_y_no_como_rotulo(cual: str) -> None:
    """Todo `label` era versalita de 10 px, también el de una casilla:
    «RECIBE LOS AVISOS» o «LUN MAR MIÉ» se leían como el título de una
    sección, y cada plantilla lo deshacía a mano con `text-transform:none`."""
    css = _sin_comentarios(_css_servido(cual))
    rotulo = re.search(r"(?:^|\})\s*label\s*\{[^}]*text-transform\s*:\s*uppercase", css)
    casilla = re.search(r"(?:^|\})\s*" + re.escape(CASILLA) + r"\s*\{([^}]*)\}", css)
    assert rotulo and casilla, f"interfaz {cual}: falta la regla de rótulo o la de casilla"
    assert casilla.start() > rotulo.start(), "la de casilla tiene que ir detrás del rótulo para ganarle"
    cuerpo = casilla.group(1)
    assert re.search(r"text-transform\s*:\s*none", cuerpo) and re.search(r"display\s*:\s*flex", cuerpo)


def test_las_casillas_ya_no_deshacen_la_versalita_a_mano() -> None:
    """Lo que la regla de base hace ya no se repite en cada sitio (C-0341)."""
    sitios = {
        "chat-secretario.css": r"\.opciones-pop label\s*\{[^}]*",
        "encargos.html": r"\.marca-dueno\s*\{[^}]*",
        "conexiones.html": r"<label style=\"[^\"]*",
    }
    culpables = []
    for nombre, patron in sitios.items():
        ruta = ESTATICOS / nombre if nombre.endswith(".css") else PLANTILLAS / nombre
        for m in re.finditer(patron, _sin_comentarios(ruta.read_text(encoding="utf-8"))):
            if "text-transform" in m.group(0):
                culpables.append(f"{nombre}: {' '.join(m.group(0).split())[:80]}")
    assert not culpables, culpables


def test_ninguna_plantilla_vuelve_a_copiar_el_estilo_de_campo() -> None:
    """`secretario.html` declaraba otra vez, a mano, el pozo de los campos de
    hora, número y fecha: tres copias que se separan en cuanto cambie una."""
    copia = re.compile(r"[^{}]*input\[type=(?:time|number|datetime-local|date|url|search)\][^{}]*\{[^}]*"
                       r"background\s*:\s*var\(--lienzo\)", re.S)
    culpables = [_nombre(a) for a in sorted(PLANTILLAS.rglob("*.html"))
                 if a.name != "base.html" and copia.search(_sin_comentarios(a.read_text(encoding="utf-8")))]
    assert not culpables, f"copian el estilo de campo de base.html: {culpables}"


@pytest.mark.parametrize("cual", INTERFACES)
def test_en_base_los_colores_salen_de_root(cual: str) -> None:
    """Fuera de `:root`, la base no escribe colores: los toma de sus tokens.
    La única excepción es la sombra de lo que flota (`.menu-pop`,
    `.combo-pop`), que CLAUDE.md declara a propósito. El hover de `.cta` y el
    velo de los diálogos eran literales (C-0110).

    Se mira lo servido con cada interfaz (C-0169): la nueva añade detrás del
    `:root` de siempre sus juegos de colores, uno por entrada del catálogo
    (`interfaz.COLORES`), y su marco, que no puede traer ni un color escrito.
    Un juego es un bloque cuyo selector es EXACTAMENTE `[data-colores="x"]`
    (el de fábrica, con `:root,` delante): `[data-colores="x"] .cta { … }`
    con un color dentro sigue siendo un color fuera de sitio."""
    css = _sin_comentarios(_css_servido(cual))
    raices = re.findall(r"(?:^|(?<=\}))\s*:root\s*\{.*?\n\}", css, re.S)
    assert len(raices) == 1, f"{len(raices)} bloques :root"
    if cual == interfaz.NUEVA:
        juegos = {}
        for bloque in re.finditer(
                r'(?:^|(?<=\}))\s*(?::root\s*,\s*)?\[data-colores="([\w-]+)"\]\s*\{.*?\n\}', css, re.S):
            assert bloque.group(1) not in juegos, f"dos bloques para «{bloque.group(1)}»"
            juegos[bloque.group(1)] = bloque.group(0)
        assert set(juegos) == set(interfaz.COLORES), (
            f"bloques {sorted(juegos)} contra el catálogo {sorted(interfaz.COLORES)}")
        de_fabrica = juegos[interfaz.DE_FABRICA]
        assert de_fabrica.lstrip().startswith(":root"), "el de fábrica es también el `:root` de la nueva"
        # A igual peso gana el orden: el de fábrica va el primero, o pisaría a los demás.
        assert all(css.index(de_fabrica) < css.index(b) for c, b in juegos.items() if c != interfaz.DE_FABRICA)
        raices += list(juegos.values())
    fuera = css
    for raiz in raices:
        fuera = fuera.replace(raiz, "")
    culpables = [
        decl.strip() for decl in re.split(r"[;{}]", fuera)
        if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", decl) and not decl.strip().startswith("box-shadow")
    ]
    assert not culpables, f"colores literales fuera de :root: {culpables}"


# ── Lo de teclado, sólo donde hay teclado (C-0400, UI-12) ─────────────────────

@pytest.mark.parametrize("cual", INTERFACES)
def test_con_el_dedo_lo_que_es_solo_de_teclado_no_se_ve(cual: str) -> None:
    """«Ctrl K» en la cabecera de cada pantalla y «↑↓ Enter Esc» al pie de
    la paleta eran instrucciones imposibles de seguir en el teléfono."""
    reglas = _reglas_en(_sin_comentarios(_css_servido(cual)), "(hover: none)")
    assert any(".solo-teclado" in s and re.search(r"display\s*:\s*none", c) for s, c in reglas.items()), reglas


def _visible(texto: str) -> str:
    """El marcado sin comentarios ni guiones: lo que acaba leyéndose."""
    return re.sub(r"\{#.*?#\}|<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>", "", texto, flags=re.S)


def test_toda_tecla_y_todo_atajo_escrito_va_marcado_como_solo_de_teclado() -> None:
    culpables = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        texto = _visible(archivo.read_text(encoding="utf-8"))
        for m in re.finditer(r'<(\w+)\b[^>]*class="([^"]*)"[^>]*>', texto):
            clases = m.group(2).split()
            if ("tecla" in clases or "paleta-pie" in clases) and "solo-teclado" not in clases:
                culpables.append(f"{_nombre(archivo)}: {m.group(0)[:70]}")
        # Un atajo escrito en el texto: «(Ctrl+V)», «(Ctrl K)». En un `title` no
        # cuenta: sin ratón no se ve.
        sin_title = re.sub(r'\stitle="[^"]*"', "", texto)
        for m in re.finditer(r"\(Ctrl[ +]\w\)", sin_title):
            antes = sin_title[max(0, m.start() - 40):m.start()]
            if 'class="solo-teclado"' not in antes:
                culpables.append(f"{_nombre(archivo)}: {m.group(0)}")
    assert not culpables, culpables


def test_ningun_texto_manda_a_la_izquierda_ni_abajo_a_la_derecha() -> None:
    """En el teléfono no hay izquierda (el raíl y la lista van arriba) y la
    pestaña del secretario es una barra a todo lo ancho: «abajo a la derecha»
    mandaba a un sitio que no existe."""
    culpables = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        texto = _visible(archivo.read_text(encoding="utf-8"))
        texto = re.sub(r"<[^>]+>", " ", texto)
        for m in re.finditer(r"\b(?:en|a) la (?:izquierda|derecha)\b", texto):
            culpables.append(f"{_nombre(archivo)}: …{texto[max(0, m.start() - 30):m.end()]}")
    assert not culpables, culpables


# ── El trinquete: lo escrito a mano no crece (C-0403) ─────────────────────────
#
# Cada pantalla nueva elegía su tamaño de letra (había 19 distintos) y se
# escribían 444 `style=""`. No se migran de golpe —fundir 12, 13 y 14 px cambia
# la densidad de cada pantalla, y eso se decide mirándola—, pero tampoco
# crecen. Por archivo y no un total: con un total, uno sube mientras otro baja.
# Un archivo que no está en la lista nace con tope 0. 🔴 El tope sólo baja: si
# limpias un archivo, baja aquí su número; nunca lo subas para que pase.

LETRA_A_MANO = re.compile(r"font-size\s*:\s*[\d.]+px")
STYLE_A_MANO = re.compile(r"\sstyle=\"")

#: archivo → (tamaños de letra en px escritos a mano, atributos `style=""`).
#: Medido al cerrar C-0403 (13-nov).
TOPES: dict[str, tuple[int, int]] = {
    "_preparar.html": (4, 0),
    "acceso.html": (0, 21),
    "actualizaciones.html": (2, 2),
    "archivos.html": (4, 13),
    "banco_dictado.html": (7, 1),
    "base.html": (47, 1),
    "canal.html": (8, 30),
    "conexiones.html": (1, 18),
    "consumo.html": (2, 26),
    "contexto.html": (0, 1),
    "encargos.html": (6, 37),
    "encargos_acceso.html": (0, 4),
    "guia.html": (6, 4),
    "index.html": (4, 39),
    "intercambio.html": (7, 12),
    "inventario.html": (11, 27),
    "maquina.html": (2, 24),
    "navegante.html": (9, 26),
    "navegante_corrida.html": (4, 3),
    "no_existe.html": (0, 4),
    "nueva/base.html": (6, 0),
    "orquestador.html": (11, 17),
    "orquestador_permisos.html": (1, 5),
    "proyecto.html": (5, 17),
    "respaldo.html": (2, 7),
    "reunion.html": (7, 21),
    "reuniones.html": (7, 11),
    "secretario.html": (22, 23),
    "secretario_monitor.html": (0, 1),
    "servicios.html": (1, 6),
    "static/avatar-secretario.css": (1, 0),
    "static/chat-secretario.css": (20, 0),
    "static/escenario-secretario.css": (8, 0),
    "static/talleres.css": (5, 0),
    "tablero.html": (5, 5),
    "trabajo.html": (35, 2),
}

ARCHIVOS_CON_TOPE = sorted([*(a for a in PLANTILLAS.rglob("*.html") if a.name != "_personaje.html"),
                            *(c for c in ESTATICOS.glob("*.css") if c.name not in VENDORIZADOS)])


def _a_mano(archivo: Path) -> tuple[int, int]:
    texto = _sin_comentarios(archivo.read_text(encoding="utf-8"))
    return len(LETRA_A_MANO.findall(texto)), len(STYLE_A_MANO.findall(texto))


def _clave(archivo: Path) -> str:
    return _nombre(archivo) if archivo.is_relative_to(PLANTILLAS) else f"static/{archivo.name}"


@pytest.mark.parametrize("archivo", ARCHIVOS_CON_TOPE, ids=_clave)
def test_los_tamanos_de_letra_y_los_style_escritos_a_mano_no_crecen(archivo: Path) -> None:
    letra, estilo = _a_mano(archivo)
    tope_letra, tope_estilo = TOPES.get(_clave(archivo), (0, 0))
    assert letra <= tope_letra, (
        f"{_clave(archivo)}: {letra} tamaños de letra escritos a mano (tope {tope_letra}). "
        "Usa `--letra-1…6` de `:root`, o una clase que ya lo tenga.")
    assert estilo <= tope_estilo, (
        f"{_clave(archivo)}: {estilo} `style=\"\"` (tope {tope_estilo}). Una clase en el `<style>` de la pantalla.")


def test_el_trinquete_no_guarda_topes_de_archivos_que_ya_no_existen() -> None:
    existen = {_clave(a) for a in ARCHIVOS_CON_TOPE}
    # La interfaz nueva no viaja con el producto (C-0169): allí su tope no es
    # de un archivo que se borró, sino de uno que no vino, y la suite de quien
    # clona salía en rojo.
    no_vinieron = set() if interfaz.disponible() else {t for t in TOPES if t.startswith("nueva/")}
    sobran = set(TOPES) - existen - no_vinieron
    assert not sobran, sorted(sobran)


def test_la_escala_de_letra_y_los_radios_nuevos_estan_en_root() -> None:
    raiz = re.search(r":root\s*\{(.*?)\n\}", (PLANTILLAS / "base.html").read_text(encoding="utf-8"), re.S)
    tokens = dict(re.findall(r"(--(?:letra|r)-[\w-]+)\s*:\s*([\d.]+px)", raiz.group(1)))
    assert {k: v for k, v in tokens.items() if k.startswith("--letra-")} == {
        "--letra-1": "11px", "--letra-2": "12.5px", "--letra-3": "13.5px",
        "--letra-4": "15px", "--letra-5": "17px", "--letra-6": "24px"}
    assert (tokens["--r-pop"], tokens["--r-cifra"], tokens["--r-pildora"]) == ("11px", "12px", "999px")


def test_no_queda_un_style_suelto_entre_la_cabeza_y_el_cuerpo() -> None:
    """El de `.aviso-accion` vivía entre `</head>` y `<body>`: HTML inválido, y
    fuera del orden de cascada que se lee en la hoja."""
    texto = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    assert not re.search(r"</head>\s*<style", texto)
    hoja = texto[texto.index("<style>"):texto.index("{% block estilo_marco %}")]
    assert ".aviso-accion {" in hoja.replace(".aviso-accion{", ".aviso-accion {")
