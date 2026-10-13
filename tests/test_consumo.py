"""Cuánto ha costado cada proyecto, leído del registro de Claude Code.

🔴 Lo que estos tests protegen no es que el módulo sume: es que **no sume dos
veces**. Una respuesta se escribe en el registro partida en varias líneas —una
por bloque de contenido— y todas repiten el mismo `usage`. Medido sobre el
registro real: 144 527 mensajes para 73 291 peticiones, o sea que sumar línea a
línea infla 1,86x, y de forma desigual por campo. Un contador inflado es
exactamente la clase de cifra que la regla dura 13 prohíbe enseñar: se aprende a
ignorarla, y entonces el día que importe tampoco se mirará.
"""

from __future__ import annotations

import json

import pytest

from hub import api, consumo
from hub.models import Proyecto, Ruta


# ── El arnés ─────────────────────────────────────────────────────────────────

def _linea(request_id, *, cwd, salida, lectura=0, escritura=0, entrada=2,
           modelo="claude-opus-5", cuando="2026-08-20T10:00:00.000Z",
           razonado=0, tipo="assistant"):
    """Una línea del registro, con la forma exacta que escribe Claude Code."""
    return json.dumps({
        "type": tipo,
        "cwd": cwd,
        "requestId": request_id,
        "timestamp": cuando,
        "uuid": f"{request_id}-{salida}",
        "message": {
            "model": modelo,
            "usage": {
                "input_tokens": entrada,
                "cache_creation_input_tokens": escritura,
                "cache_read_input_tokens": lectura,
                "output_tokens": salida,
                "output_tokens_details": {"thinking_tokens": razonado},
            },
        },
    })


@pytest.fixture
def registro(tmp_path, monkeypatch):
    """Un registro de mentira, y una función para escribir sesiones en él."""
    raiz = tmp_path / "transcripts"
    raiz.mkdir()
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(raiz))

    def escribir(nombre, lineas, carpeta="-tmp-demo"):
        destino = raiz / carpeta
        destino.mkdir(exist_ok=True)
        (destino / f"{nombre}.jsonl").write_text("\n".join(lineas) + "\n",
                                                 encoding="utf-8")
    return escribir


def _proyectos_de(con):
    """El proyecto `demo` de `conftest`, como lo vería `registry.cargar()`."""
    return [Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo",
                     rutas=[Ruta(ruta="/tmp/demo", tipo="asiento")])]


# ── Lo que no se puede contar dos veces ──────────────────────────────────────

def test_una_respuesta_partida_en_varias_lineas_cuenta_una_sola_peticion(
    con, proyecto_demo, registro
):
    """🔴 El defecto que este módulo existe para no tener.

    Tres líneas —pensar, texto, herramienta— del mismo `requestId`. Sumarlas
    daría tres peticiones y el triple de caché leída.
    """
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=10, lectura=1000, escritura=50),
        _linea("req_A", cwd="/tmp/demo", salida=10, lectura=1000, escritura=50),
        _linea("req_A", cwd="/tmp/demo", salida=387, lectura=1000, escritura=50),
    ])
    consumo.escanear(con, _proyectos_de(con))
    fila = con.execute("SELECT peticiones, lectura, escritura FROM consumo").fetchone()
    assert fila["peticiones"] == 1, "una respuesta partida se contó como varias"
    assert fila["lectura"] == 1000, "la caché leída se sumó entre líneas de la misma petición"
    assert fila["escritura"] == 50


def test_la_salida_es_el_maximo_de_los_parciales_y_no_su_suma(
    con, proyecto_demo, registro
):
    """`output_tokens` va creciendo línea a línea: es el recuento parcial según
    se emitía. Sumarlo daría 10+10+387 = 407 donde de verdad son 387."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=10),
        _linea("req_A", cwd="/tmp/demo", salida=10),
        _linea("req_A", cwd="/tmp/demo", salida=387),
    ])
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT salida FROM consumo").fetchone()["salida"] == 387


def test_una_peticion_repartida_entre_dos_archivos_no_se_cuenta_dos_veces(
    con, proyecto_demo, registro
):
    """Pasa cuando se reanuda una sesión: 52 peticiones del registro real están
    en dos archivos. Deduplicar por archivo en vez de globalmente las contaría
    dos veces, y ese error no se ve mirando ningún archivo por separado."""
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=387, lectura=1000)])
    registro("s2", [_linea("req_A", cwd="/tmp/demo", salida=387, lectura=1000)])
    consumo.escanear(con, _proyectos_de(con))
    fila = con.execute("SELECT peticiones, lectura FROM consumo").fetchone()
    assert fila["peticiones"] == 1
    assert fila["lectura"] == 1000


def test_peticiones_distintas_si_se_suman(con, proyecto_demo, registro):
    """La otra mitad, y la que se rompe si uno se pasa de listo deduplicando."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100, lectura=1000),
        _linea("req_B", cwd="/tmp/demo", salida=200, lectura=2000),
    ])
    consumo.escanear(con, _proyectos_de(con))
    fila = con.execute("SELECT peticiones, salida, lectura FROM consumo").fetchone()
    assert (fila["peticiones"], fila["salida"], fila["lectura"]) == (2, 300, 3000)


def test_el_razonamiento_no_se_suma_al_total(con, proyecto_demo, registro):
    """Está DENTRO de la salida, no al lado. Contarlo aparte lo cuenta dos veces."""
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=400, razonado=250)])
    consumo.escanear(con, _proyectos_de(con))
    datos = api.consumo(con)
    assert datos["totales"]["razonado"] == 250
    assert datos["totales"]["total"] == 400 + 2  # salida + la entrada de 2


# ── A qué proyecto va cada cosa ──────────────────────────────────────────────

def test_cada_cwd_va_al_proyecto_que_lo_contiene(con, proyecto_demo, registro):
    registro("s1", [_linea("req_A", cwd="/tmp/demo/src/hub", salida=100)])
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT proyecto_id FROM consumo").fetchone()["proyecto_id"] == "demo"


def test_lo_que_no_cae_en_ningun_proyecto_se_enseña_aparte_y_no_se_descarta(
    con, proyecto_demo, registro
):
    """🔴 No es un hueco: es la lista de carpetas donde se ha trabajado sin darlas
    de alta en el hub. En el registro real son 4 751 peticiones en una sola ruta.
    Descartarlas dejaría un total que no cuadra con nada y sin decir por qué."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100),
        _linea("req_B", cwd="/tmp/otra-cosa", salida=700),
    ])
    consumo.escanear(con, _proyectos_de(con))
    datos = api.consumo(con)
    sin_proyecto = [e for e in datos["proyectos"] if e["proyecto_id"] is None]
    assert len(sin_proyecto) == 1
    assert sin_proyecto[0]["salida"] == 700
    assert "/tmp/otra-cosa" in dict(sin_proyecto[0]["rutas"])
    assert datos["totales"]["salida"] == 800, "lo no atribuido se cayó del total"


def test_dar_de_alta_un_proyecto_reclasifica_su_historia_sin_rescatar_nada(
    con, proyecto_demo, registro
):
    """La atribución se recalcula en cada escaneo en vez de congelarse. Por eso
    la clave de la tabla es la RUTA y no el proyecto: declarar una carpeta nueva
    en `projects.yml` reordena lo ya medido en el siguiente ciclo lento."""
    registro("s1", [_linea("req_A", cwd="/tmp/nuevo", salida=100)])

    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT proyecto_id FROM consumo").fetchone()["proyecto_id"] is None

    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('nuevo','Nuevo','/tmp/nuevo')")
    ampliados = _proyectos_de(con) + [
        Proyecto(id="nuevo", nombre="Nuevo", asiento="/tmp/nuevo",
                 rutas=[Ruta(ruta="/tmp/nuevo", tipo="asiento")])]
    consumo.escanear(con, ampliados)
    assert con.execute("SELECT proyecto_id FROM consumo").fetchone()["proyecto_id"] == "nuevo"


# ── Lo que NO se puede hacer al no poder medir ───────────────────────────────

def test_sin_registro_no_se_borra_lo_ya_medido(con, proyecto_demo, registro, monkeypatch):
    """Regla dura 13 en su forma más cara: un cero que significa «no he mirado»
    es indistinguible de un cero que significa «no has gastado nada»."""
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=100)])
    consumo.escanear(con, _proyectos_de(con))

    monkeypatch.setenv("HUB_TRANSCRIPTS", "/no/existe/en/ningun/sitio")
    with pytest.raises(consumo.ConsumoNoMedido):
        consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT salida FROM consumo").fetchone()["salida"] == 100


def test_un_registro_vacio_tampoco_pisa_la_ultima_medicion(
    con, proyecto_demo, registro, tmp_path, monkeypatch
):
    """La carpeta existe pero no tiene nada legible dentro. Es lo que pasa si
    Claude Code acaba de podar o si la ruta apunta al sitio equivocado."""
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=100)])
    consumo.escanear(con, _proyectos_de(con))

    vacia = tmp_path / "vacia"
    vacia.mkdir()
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(vacia))
    with pytest.raises(consumo.ConsumoNoMedido):
        consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT salida FROM consumo").fetchone()["salida"] == 100


def test_una_linea_corrupta_no_se_lleva_por_delante_el_resto(
    con, proyecto_demo, registro
):
    """Un `.jsonl` puede acabar a medias: es un archivo que se escribe mientras
    se lee. Que la última línea esté partida no puede dejar sin contar la sesión."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100),
        '{"type":"assistant","message":{"usage":',   # cortada por la mitad
        "no es json en absoluto",
        _linea("req_B", cwd="/tmp/demo", salida=200),
    ])
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT salida FROM consumo").fetchone()["salida"] == 300


def test_solo_cuentan_los_mensajes_del_asistente(con, proyecto_demo, registro):
    """Las líneas de usuario y los adjuntos no traen `usage`, pero las de tipo
    `system` sí pueden traer otras cosas. Se cuenta lo que la API cobró."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100),
        _linea("req_B", cwd="/tmp/demo", salida=999, tipo="user"),
    ])
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT salida FROM consumo").fetchone()["salida"] == 100


# ── La ventana ───────────────────────────────────────────────────────────────

def test_la_ventana_sale_del_registro_y_no_de_un_ajuste(con, proyecto_demo, registro):
    """🔴 Claude Code poda a los 30 días, así que esto NUNCA es un histórico. Si
    algún día cambia su poda, la pantalla lo dice sola porque las fechas salen
    del propio registro."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100, cuando="2026-08-10T09:00:00.000Z"),
        _linea("req_B", cwd="/tmp/demo", salida=100, cuando="2026-09-10T21:00:00.000Z"),
    ])
    consumo.escanear(con, _proyectos_de(con))
    datos = api.consumo(con)
    assert datos["desde"][:10] == "2026-08-10"
    assert datos["hasta"][:10] == "2026-09-10"


def test_el_modelo_se_conserva_porque_no_todos_pesan_igual(con, proyecto_demo, registro):
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100, modelo="claude-opus-5"),
        _linea("req_B", cwd="/tmp/demo", salida=100, modelo="claude-haiku-4-5-20251001"),
    ])
    consumo.escanear(con, _proyectos_de(con))
    modelos = dict(api.consumo(con)["proyectos"][0]["modelos"])
    assert modelos == {"claude-opus-5": 1, "claude-haiku-4-5-20251001": 1}


# ── Cómo se escriben las cifras ──────────────────────────────────────────────

def test_las_cifras_se_escriben_en_castellano():
    """Se mezclaban las dos convenciones en la misma tabla: `73,353` peticiones
    al lado de `13,3 G` de caché, con la coma queriendo decir una cosa distinta
    a dos columnas de distancia."""
    from hub.consumo import millones, numero
    assert numero(73353) == "73.353"
    assert numero(63.3, 1) == "63,3"
    assert millones(13_655_752_110) == "13,7 G"
    assert millones(262_494_112) == "262 M"
    assert millones(999) == "999"
    assert millones(None) == "—"


def test_el_redondeo_no_cambia_de_escala_a_mitad_de_columna():
    """Con `>= corte` a secas, 999 999 salía como «999.999» entre cifras en M."""
    from hub.consumo import millones
    assert millones(999_999) == "1,0 M"
    assert millones(999_499) == "999 k"


def test_el_cli_mide_y_deja_la_medicion_en_la_base(proyecto_demo, con, registro,
                                                   monkeypatch, capsys):
    """🔴 El CLI llevaba un `--guardar` y sin él decía «medido y NO guardado».
    Era falso: `db.conectar` abre con `isolation_level=None`, así que cada
    `INSERT` se confirma solo y la medición se escribía igual. Un flag que no
    hace nada y un mensaje que dice lo contrario de lo que pasa es peor que no
    tener ninguno de los dos; el test fija lo que de verdad ocurre.
    """
    from hub import config, db, registry

    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=100)])
    monkeypatch.setattr(registry, "cargar", lambda: _proyectos_de(None))

    assert consumo._cli([]) == 0
    salida = capsys.readouterr().out
    assert "NO guardado" not in salida
    assert "TOTAL" in salida

    # La base que abre el CLI es la de `config.DB_PATH`, que `conftest` ya tiene
    # apuntada a un temporal: se comprueba ahí, no en la conexión del test.
    otra = db.conectar(config.DB_PATH)
    try:
        assert otra.execute("SELECT salida FROM consumo").fetchone()[0] == 100
    finally:
        otra.close()


def test_un_proyecto_que_ya_no_esta_declarado_no_se_confunde_con_lo_no_atribuido(
    con, proyecto_demo, registro
):
    """Se sabe de quién era ese gasto: decirlo es la diferencia entre «esta
    carpeta no la has dado de alta» y «esto lo gastó algo que quitaste del
    registro». Con la misma etiqueta salían dos filas indistinguibles."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100),
        _linea("req_B", cwd="/tmp/ni-idea", salida=50),
    ])
    consumo.escanear(con, _proyectos_de(con))
    con.execute("DELETE FROM proyecto WHERE id='demo'")

    etiquetas = {e["proyecto_id"]: e["nombre"] for e in api.consumo(con)["proyectos"]}
    assert etiquetas[None] == "Sin proyecto"
    assert etiquetas["demo"] == "demo — ya no está en projects.yml"


def test_se_cuenta_cuantas_peticiones_razonaron_y_no_solo_cuanto(
    con, proyecto_demo, registro
):
    """🔴 Sin este segundo número el primero engaña. En el registro real son
    4,5 M de razonamiento sobre 64,7 M de salida —un 7 %—, que se lee como
    «razona poco en cada turno»; lo que pasa de verdad es que sólo el 13 % de las
    peticiones razonó, y las que lo hicieron razonaron mucho."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=1000, razonado=650),
        _linea("req_B", cwd="/tmp/demo", salida=1000, razonado=0),
        _linea("req_C", cwd="/tmp/demo", salida=1000, razonado=0),
    ])
    consumo.escanear(con, _proyectos_de(con))
    t = api.consumo(con)["totales"]
    assert t["razonado"] == 650
    assert t["razonadas"] == 1, "no se distingue «razonó poco» de «casi nunca razonó»"
    assert t["peticiones"] == 3


# ── Por categoría ────────────────────────────────────────────────────────────

def _proyecto(con, pid, nombre, dominio="personal", tipo="proyecto", status="activo"):
    con.execute("INSERT INTO proyecto (id, nombre, dominio, tipo, status, asiento) "
                "VALUES (?,?,?,?,?,?)", (pid, nombre, dominio, tipo, status, f"/tmp/{pid}"))
    return Proyecto(id=pid, nombre=nombre, asiento=f"/tmp/{pid}",
                    rutas=[Ruta(ruta=f"/tmp/{pid}", tipo="asiento")])


def test_el_consumo_se_agrupa_por_las_categorias_del_hub(con, registro):
    """Las categorías salen de `projects.yml`, no del registro de Claude Code:
    cambiar el dominio de un proyecto reordena la vista sin volver a medir."""
    trabajo = _proyecto(con, "curro", "Curro", dominio="laboral")
    juego = _proyecto(con, "juego", "Juego", dominio="personal", status="pausado")
    registro("s1", [
        _linea("req_A", cwd="/tmp/curro", salida=300),
        _linea("req_B", cwd="/tmp/juego", salida=100),
    ])
    consumo.escanear(con, [trabajo, juego])

    cats = {c["campo"]: dict((t["valor"], t["total"]) for t in c["tajadas"])
            for c in api.consumo(con)["categorias"]}
    assert cats["dominio"] == {"laboral": 302, "personal": 102}
    assert cats["status"]["pausado"] == 102, "no se ve lo que gasta un proyecto pausado"
    assert cats["status"]["activo"] == 302


def test_lo_que_no_tiene_ficha_no_se_cuela_en_una_categoria_por_omision(
    con, registro, proyecto_demo
):
    """🔴 Un cwd sin proyecto no tiene dominio. Meterlo en «personal» porque es el
    valor por defecto del modelo falsearía justo la cifra que se está mirando:
    son 5 261 peticiones del registro real, el 10 %."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100),
        _linea("req_B", cwd="/tmp/ni-idea", salida=900),
    ])
    consumo.escanear(con, _proyectos_de(con))
    dominio = {t["valor"]: t["total"]
               for t in api.consumo(con)["categorias"][0]["tajadas"]}
    assert dominio["sin proyecto"] == 902
    assert "personal" not in dominio or dominio["personal"] == 102


def test_el_modelo_es_la_categoria_que_NO_sale_del_hub(con, proyecto_demo, registro):
    """Es la excepción: el hub no sabe con qué modelo se pidió, lo dice el
    registro. Y hace falta, porque un token de Opus y uno de Haiku no pesan
    igual y ésa es la única pista de peso que hay sin tabla de precios."""
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100, modelo="claude-opus-5"),
        _linea("req_B", cwd="/tmp/demo", salida=100, modelo="claude-haiku-4-5-20251001"),
    ])
    consumo.escanear(con, _proyectos_de(con))
    cats = {c["campo"]: c for c in api.consumo(con)["categorias"]}
    assert {t["valor"] for t in cats["modelo"]["tajadas"]} == {
        "claude-opus-5", "claude-haiku-4-5-20251001"}


# ── La gráfica ───────────────────────────────────────────────────────────────

def test_las_columnas_se_apoyan_en_la_base_y_la_serie_mayor_va_abajo(con, registro):
    """🔴 El apilado se dibuja desde el techo hacia abajo, así que el orden del
    reparto ES el orden visual. La serie mayor va la última para quedar apoyada
    en la base: sobre una línea recta su altura se compara entre días de un
    vistazo, y flotando sobre las pequeñas no."""
    grande = _proyecto(con, "grande", "Grande")
    chico = _proyecto(con, "chico", "Chico")
    registro("s1", [
        _linea("req_A", cwd="/tmp/grande", salida=900),
        _linea("req_B", cwd="/tmp/chico", salida=100),
    ])
    consumo.escanear(con, [grande, chico])
    g = api.consumo(con)["grafica"]

    col = g["columnas"][0]
    assert round(col["trozos"][-1]["y"] + col["trozos"][-1]["alto"], 1) == g["alto"], \
        "la columna no se apoya en la base"
    assert col["trozos"][-1]["tono"] == 1, "la serie mayor no quedó abajo"
    assert col["trozos"][0]["tono"] > 1


def test_el_dia_mas_alto_llena_el_lienzo_y_los_demas_se_escalan_contra_el(con, registro):
    grande = _proyecto(con, "grande", "Grande")
    registro("s1", [
        _linea("req_A", cwd="/tmp/grande", salida=1000, cuando="2026-08-20T10:00:00.000Z"),
        _linea("req_B", cwd="/tmp/grande", salida=500, cuando="2026-08-21T10:00:00.000Z"),
    ])
    consumo.escanear(con, [grande])
    g = api.consumo(con)["grafica"]
    altos = [sum(t["alto"] for t in c["trozos"]) for c in g["columnas"]]
    assert round(altos[0], 1) == g["alto"]
    assert 0.45 < altos[1] / altos[0] < 0.55


def test_mas_de_seis_proyectos_juntan_el_resto_en_otros(con, registro):
    """La rampa de tono tiene seis escalones: con más, dos series contiguas
    dejan de distinguirse y el color pasa a ser decoración."""
    proyectos, lineas = [], []
    for i in range(9):
        proyectos.append(_proyecto(con, f"p{i}", f"P{i}"))
        lineas.append(_linea(f"req_{i}", cwd=f"/tmp/p{i}", salida=(9 - i) * 100))
    registro("s1", lineas)
    consumo.escanear(con, proyectos)
    series = api.consumo(con)["grafica"]["series"]
    assert [s["tono"] for s in series] == [1, 2, 3, 4, 5, 6, 0]
    assert series[-1]["nombre"] == "otros (3)"


def test_sin_datos_la_grafica_no_revienta_ni_inventa_columnas(con, proyecto_demo):
    """Se pide `/consumo` antes del primer ciclo lento. Sin esto la vista daba un
    500 en vez de decir que todavía no hay medición."""
    g = api.consumo(con)["grafica"]
    assert g["columnas"] == [] and g["series"] == [] and g["tope"] == 0


# ── La parte, cuando se mira un solo proyecto ────────────────────────────────

def test_filtrar_por_proyecto_conserva_su_parte_del_total_global(con, registro):
    """🔴 En la ficha de un proyecto la pregunta es «cuánto de todo lo mío es
    esto». Calculando la parte sobre lo filtrado saldría siempre 100 %, que no
    contesta nada."""
    grande = _proyecto(con, "grande", "Grande")
    chico = _proyecto(con, "chico", "Chico")
    registro("s1", [
        _linea("req_A", cwd="/tmp/grande", salida=750, entrada=0),
        _linea("req_B", cwd="/tmp/chico", salida=250, entrada=0),
    ])
    consumo.escanear(con, [grande, chico])

    solo = api.consumo(con, "chico")
    assert solo["totales"]["total"] == 250
    assert solo["totales"]["parte"] == pytest.approx(25.0)
    assert [e["proyecto_id"] for e in solo["proyectos"]] == ["chico"]
