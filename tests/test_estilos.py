"""El catálogo de muestras: qué garantiza, y qué se rompería sin que se viera.

Ninguna prueba abre un navegador. Lo que se protege aquí no es cómo queda —eso
se mira, y se miró— sino las tres propiedades que hacen que enseñar las muestras
signifique algo, y que se pueden romper editando el CSS sin que nada falle.
"""

from __future__ import annotations

import re

import pytest

from hub import estilos


def test_hay_catalogo_de_sobra_para_elegir():
    """Pidió más de seis. Con tres, elegir es conformarse."""
    assert len(estilos.ESTILOS) >= 10
    ids = [e.id for e in estilos.ESTILOS]
    assert len(set(ids)) == len(ids), "hay ids repetidos"


@pytest.mark.parametrize("estilo", estilos.ESTILOS, ids=lambda e: e.id)
def test_el_catalogo_de_estilos_ensena_siempre_la_misma_pantalla(estilo):
    """🔴 El invariante del que depende todo.

    Si cada muestra de estilo enseñara otro contenido, ella estaría eligiendo
    CONTENIDO y no estilo — y su respuesta no diría nada sobre cómo quiere que
    se vea lo suyo. Es lo más fácil de romper: basta con que alguien «mejore»
    una muestra cambiándole los textos.
    """
    referencia = estilos.PANTALLA_POR_ID[estilos.PANTALLA_DE_REFERENCIA]
    assert referencia.html in estilos.pagina(estilo)


def test_el_catalogo_de_estilos_no_varia_la_pantalla():
    """🔴 El invariante donde de verdad vive: en el emparejamiento.

    Probarlo sobre `pagina()` no basta —ahí se le pasa lo que se quiera—, y
    probarlo sobre `generar()` exige un navegador. Por eso el emparejamiento es
    una función aparte: la regla se comprueba sin pintar nada.
    """
    pantallas = {p.id for _, p in estilos.catalogo()["estilos"]}
    assert pantallas == {estilos.PANTALLA_DE_REFERENCIA}


def test_el_catalogo_de_pantallas_no_varia_el_estilo():
    """Y al revés, que es lo que hace que sean dos catálogos y no uno mezclado."""
    usados = {e.id for e, _ in estilos.catalogo()["pantallas"]}
    assert usados == {estilos.ESTILO_DE_REFERENCIA}


def test_los_dos_catalogos_ensenan_todo_lo_que_hay():
    """Una muestra que existe y no se enseña es una opción de menos sin que
    nadie lo haya decidido."""
    cat = estilos.catalogo()
    assert {e.id for e, _ in cat["estilos"]} == {e.id for e in estilos.ESTILOS}
    assert {p.id for _, p in cat["pantallas"]} == {p.id for p in estilos.PANTALLAS}


@pytest.mark.parametrize("pantalla", estilos.PANTALLAS, ids=lambda p: p.id)
def test_cada_pantalla_se_pinta_con_el_estilo_que_se_le_pase(pantalla):
    """🔴 Y el invariante AL REVÉS, que es lo que hace que sean dos catálogos.

    Aquí lo que se pregunta es «¿cuál de éstas te serviría?». Si cada pantalla
    llevara su propio aspecto, compararía el aspecto en vez de para qué sirve —
    el mismo error que el otro catálogo evita, cometido por el otro lado.
    """
    neutro = estilos.POR_ID[estilos.ESTILO_DE_REFERENCIA]
    pagina = estilos.pagina(neutro, pantalla)
    assert neutro.css in pagina
    assert pantalla.html in pagina


@pytest.mark.parametrize("estilo", estilos.ESTILOS, ids=lambda e: e.id)
def test_una_pantalla_nueva_funciona_en_LOS_DOCE_sin_tocarlos(estilo):
    """🔴 Lo que permite que el catálogo crezca.

    Lo propio de cada pantalla —las casillas del calendario, las cifras del
    panel— está escrito una sola vez contra tokens. Si un estilo se deja uno sin
    declarar, esa pantalla se pinta rota **sólo en ese estilo**, y como las
    capturas se miran de una en una es de las cosas que se cuelan.
    """
    pedidos = set(re.findall(r"var\((--[a-z-]+)\)", estilos.COMUN))
    declarados = set(re.findall(r"(--[a-z-]+)\s*:", estilo.tokens))
    assert not (pedidos - declarados), f"«{estilo.id}» no declara {pedidos - declarados}"


@pytest.mark.parametrize("estilo", estilos.ESTILOS, ids=lambda e: e.id)
def test_la_muestra_no_pide_nada_por_la_red(estilo):
    """Se generan sin conexión y tienen que salir siempre iguales. Una fuente o
    una imagen de un CDN convierte la muestra en algo que depende de que un
    tercero siga sirviéndola — y es además la regla del proyecto: nunca un CDN."""
    pagina = estilos.pagina(estilo)
    assert "http://" not in pagina and "https://" not in pagina
    assert "@import" not in pagina


@pytest.mark.parametrize("estilo", estilos.ESTILOS, ids=lambda e: e.id)
def test_el_nombre_lo_puede_leer_quien_no_sabe_de_esto(estilo):
    """Lo lee ella, no un diseñador. Nadie elige «alto contraste, palo seco»."""
    tecnicas = ("css", "sans", "serif", "flex", "grid", "hex", "rgb",
                "tipograf", "contraste", "px")
    bajo = estilo.nombre.lower()
    assert not any(p in bajo for p in tecnicas), f"«{estilo.nombre}» suena a taller"
    assert len(estilo.nombre) <= 42


@pytest.mark.parametrize("estilo", estilos.ESTILOS, ids=lambda e: e.id)
def test_cada_muestra_pinta_de_verdad_algo_distinto(estilo):
    """Dos estilos con el mismo CSS son una opción de menos disfrazada de dos.

    No compara cómo se ven —eso se mira— sino que el CSS no esté duplicado, que
    es el descuido real al añadir una muestra copiando la anterior.
    """
    otros = [e.css for e in estilos.ESTILOS if e.id != estilo.id]
    assert estilo.css not in otros
    assert "background" in estilo.css, "una muestra sin fondo propio no es un estilo"


def test_hay_varias_clases_de_pantalla_y_no_solo_una_lista():
    """Petición suya: no todo es una lista de cobros. Un calendario y una lista
    de personas son cosas distintas y quien mira tiene que poder distinguirlas."""
    assert len(estilos.PANTALLAS) >= 5
    ids = [p.id for p in estilos.PANTALLAS]
    assert len(set(ids)) == len(ids)
    assert {"calendario", "clientes"} <= set(ids)


@pytest.mark.parametrize("pantalla", estilos.PANTALLAS, ids=lambda p: p.id)
def test_ninguna_pantalla_nombra_un_negocio_concreto(pantalla):
    """Textos genéricos, decisión suya para la v1: si la muestra dijera «tienda
    de abarrotes», ella juzgaría el contenido en vez del aspecto."""
    for palabra in ("abarrotes", "escuela", "curso"):
        assert palabra.lower() not in pantalla.html.lower()


@pytest.mark.parametrize("pantalla", estilos.PANTALLAS, ids=lambda p: p.id)
def test_toda_pantalla_trae_su_pie(pantalla):
    """El total y los dos botones son lo que hace que se lea como un producto y
    no como una maqueta suelta. Y son la parte que se sale del marco cuando algo
    de arriba crece de más, así que conviene que estén siempre."""
    assert "acciones" in pantalla.html and "total" in pantalla.html


def _clases(html: str) -> set[str]:
    """Las clases que un HTML de muestra usa de verdad."""
    return {c for attr in re.findall(r'class="([^"]+)"', html) for c in attr.split()}


def _cuerpos_que_ceden() -> set[str]:
    """Los contenedores declarados en `COMUN` como «el que absorbe y cede»."""
    regla = re.search(r"([^\n{}]*)\{\s*flex: 1; min-height: 0; overflow: hidden;",
                      estilos.COMUN)
    assert regla, "ningún cuerpo cede sitio: el pie se saldrá del marco"
    return {s.strip().lstrip(".") for s in regla.group(1).split(",")}


@pytest.mark.parametrize("pantalla", estilos.PANTALLAS, ids=lambda p: p.id)
def test_toda_pantalla_se_apoya_en_un_cuerpo_que_cede_sitio(pantalla):
    """🔴 La generalización del fallo de «papel», para la pantalla que venga.

    El total y los botones caben porque encima de ellos hay un contenedor que
    absorbe lo que sobra y cede lo que falta. Una pantalla nueva cuyo cuerpo no
    esté en esa regla se pinta perfecta en el estilo de referencia y se sale del
    marco en los de letra grande — y como las capturas se miran de una en una,
    eso no se ve hasta que alguien enseña justo ésa.
    """
    cuerpos = _cuerpos_que_ceden() & _clases(pantalla.html)
    assert cuerpos, (
        f"«{pantalla.id}» no usa ninguno de {sorted(_cuerpos_que_ceden())}: "
        "su pie se saldrá del marco en cuanto el estilo agrande la letra"
    )


@pytest.mark.parametrize("pantalla", estilos.PANTALLAS, ids=lambda p: p.id)
def test_ninguna_pantalla_usa_una_clase_que_nadie_pinta(pantalla):
    """Una clase que no existe en la hoja no falla: pinta el contenido suelto.

    Es el descuido típico al añadir una pantalla —renombrar una clase en el CSS
    y no en el HTML, o al revés— y el resultado es una captura fea que nadie
    atribuye a un error, porque la página se sirve perfectamente.
    """
    neutro = estilos.POR_ID[estilos.ESTILO_DE_REFERENCIA]
    hoja = estilos.COMUN + neutro.css
    huerfanas = sorted(c for c in _clases(pantalla.html)
                       if not re.search(rf"\.{re.escape(c)}\b", hoja))
    assert not huerfanas, f"«{pantalla.id}» usa clases que nadie pinta: {huerfanas}"


def test_lo_propio_de_cada_pantalla_se_pinta_solo_con_tokens():
    """🔴 Lo que hace que una pantalla nueva funcione en los doce sin tocarlos.

    Basta un color literal en `COMUN` para que esa pantalla lleve el mismo gris
    sobre el fondo blanco de «claro» y sobre el negro de «nocturno» — invisible
    en uno de los dos, y sólo en la captura que nadie estaba mirando.
    """
    literales = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|\b(?:black|white)\b",
                           estilos.COMUN)
    assert not literales, f"COMUN lleva colores literales: {literales}"


def test_ninguna_pantalla_es_una_variacion_de_otra():
    """Dos muestras que se confunden entre sí valen menos que una sola.

    No se pide que cada pantalla tenga una forma propia —cuatro de ellas son
    listas a propósito, porque un negocio pequeño vive en listas— sino que el
    catálogo enseñe de verdad varias formas: si todas acabaran siendo `.lista`
    con otros textos, la pregunta «¿cuál de éstas te serviría?» dejaría de
    tener respuesta.
    """
    cuerpos = _cuerpos_que_ceden()
    formas = {frozenset(cuerpos & _clases(p.html)) for p in estilos.PANTALLAS}
    assert len(formas) >= 6, f"sólo hay {len(formas)} formas distintas de pantalla"
    htmls = [p.html for p in estilos.PANTALLAS]
    assert len(set(htmls)) == len(htmls), "hay dos pantallas con el mismo contenido"


def test_la_lista_cede_sitio_para_que_el_pie_siempre_quepa():
    """🔴 Se vio mirando la captura, no leyendo: en «papel» la letra grande
    empujaba el total y los botones fuera del marco, y un botón cortado se lee
    como algo roto, no como un estilo. La lista absorbe lo que sobra y cede lo
    que falta."""
    regla = re.search(r"([^\n{}]*)\{\s*flex: 1; min-height: 0; overflow: hidden;", estilos.COMUN)
    assert regla, "ningún cuerpo cede sitio: el pie se saldrá del marco"
    # Los tres cuerpos posibles. Uno que falte se sale del marco sólo en las
    # pantallas que lo usen, o sea en un tercio de las capturas.
    cubiertos = {s.strip() for s in regla.group(1).split(",")}
    assert {".lista", ".calendario", ".barras"} <= cubiertos


def test_la_ruta_se_traduce_solo_para_el_chrome_de_windows():
    """🔴 El Chrome de Windows no entiende una ruta de Linux: la acepta,
    sale con código 0 y no escribe nada. El fallo no se ve — el síntoma es una
    captura que no existe."""
    assert estilos._para_el_navegador("/usr/bin/chromium", __import__("pathlib").Path("/tmp/x.png")) == "/tmp/x.png"


def test_sin_navegador_se_dice_que_solo_hace_falta_para_generar(monkeypatch):
    """Quien instale esto en limpio no tiene por qué tener Chrome: las capturas
    ya están hechas. El mensaje tiene que decirlo o parecerá un requisito."""
    monkeypatch.setattr(estilos, "_navegador", lambda: None)
    with pytest.raises(RuntimeError, match="Sólo hace"):
        estilos.capturar(estilos.ESTILOS[0])


# ── Qué eligió, dicho como lo diría una persona ─────────────────────────────


@pytest.mark.parametrize("respuesta, esperado", [
    ("calido", "calido"),
    ("Cálido, como una tienda de barrio", "calido"),   # el NOMBRE, que es lo que vio
    ("CÁLIDO", "calido"),
    ("la segunda", "calido"),
    # Con la coma pegada: así contesta quien acaba de ver seis fotos, y partir
    # por espacios dejaba el token «segunda,» sin casar con ningún ordinal.
    ("la segunda, la de la tienda de barrio", "calido"),
    ("me gusta la tercera", "nocturno"),
    ("opción 2", "calido"),
    ("2", "calido"),
    ("me gusta el claro", "claro"),
    ("el nocturno", "nocturno"),
])
def test_a_cual_se_parece_mas_se_contesta_de_muchas_formas(respuesta, esperado):
    """🔴 Lo destapó el primer ensayo con un agente de verdad.

    La ficha guardó «Cálido, como una tienda de barrio» —el nombre de la
    muestra, que es lo que se le enseñó— y quien construye busca un id. Sin
    resolverlo, el estilo elegido se perdía en silencio y se construía con el de
    referencia: la única decisión que ella pudo tomar viendo, descartada sin que
    nada lo dijera.
    """
    assert estilos.identificar(respuesta) == esperado


@pytest.mark.parametrize("respuesta", ["", "no lo sé", "que sea bonito", "el 99"])
def test_lo_que_no_se_sabe_no_se_adivina(respuesta):
    """Construir con el estilo equivocado es peor que volver a preguntar."""
    assert estilos.identificar(respuesta) is None


def test_el_otro_catalogo_se_identifica_aparte(catalogo_de_pantallas=None):
    """Los dos catálogos no comparten numeración: «la segunda» es otra en cada uno."""
    assert estilos.identificar("el calendario", "pantallas") == "calendario"
    assert estilos.identificar("la segunda", "pantallas") != \
        estilos.identificar("la segunda", "estilos")


def test_el_boceto_a_390_gana_la_cascada_al_estilo():
    """🔴 Se vio pintando el primer boceto de horas, no leyendo: la columna
    de 44 px que le sobra a un «2» no le cabe a un «10:00», y con siete filas
    la hoja crecía hasta dejar el total y los botones fuera de la foto. Lo que
    corrige eso va DESPUÉS del CSS del estilo, o el estilo lo pisa."""
    html = estilos.envolver_bosquejo("calido", "<main><h1>x</h1></main>")
    del_estilo = html.index(estilos.POR_ID["calido"].css.strip()[:40])
    del_boceto = html.index("minmax(44px, max-content)")
    assert del_estilo < del_boceto
    assert "height: 100vh; min-height: 0" in html
