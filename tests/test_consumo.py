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


# ── C-0326: sólo se relee el transcript que cambió ───────────────────────────
#
# El escaneo releía el registro entero —1,8 GB, 1 003 archivos— cada diez
# minutos para añadir lo de los últimos diez, en los que cambian ocho. Ahora
# lo leído de cada archivo se recuerda mientras el archivo no cambie
# (`hub.recordar.por_archivo`) y sólo se funde.
#
# 🔴 Lo que estos tests protegen es la regla dura 19: que recordando salga
# EXACTAMENTE lo mismo que leyéndolo todo, y que se sepa por qué. Por eso no
# basta comparar el escaneo en caliente con el mismo escaneo en frío —si los
# dos se equivocaran igual, coincidirían—: se comparan los dos con la pasada
# de antes, línea a línea sobre un único diccionario, copiada aquí abajo tal
# como era.

import os
import random
from pathlib import Path

from hub import recordar


def _leyendo_todo_linea_a_linea(raiz):
    """La pasada completa de antes de C-0326, sin tocar: el patrón de medida.

    No la «mejores»: vale precisamente porque no comparte ni una línea con lo
    que se prueba."""
    fuera = {}
    for archivo in sorted(raiz.rglob("*.jsonl")):
        try:
            manejador = archivo.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with manejador:
            for linea in manejador:
                if not linea.startswith("{"):
                    continue
                try:
                    dato = json.loads(linea)
                except ValueError:
                    continue
                if dato.get("type") != "assistant":
                    continue
                mensaje = dato.get("message") or {}
                uso = mensaje.get("usage")
                if not uso:
                    continue
                clave = dato.get("requestId") or f"uuid:{dato.get('uuid', '')}"
                marca = str(dato.get("timestamp") or "")
                fila = fuera.get(clave)
                if fila is None:
                    fila = fuera[clave] = {
                        "ruta": dato.get("cwd") or "",
                        "dia": marca[:10],
                        "modelo": str(mensaje.get("model") or "?"),
                        "cuando": marca,
                        "razonado": 0,
                        **{col: 0 for _, col in consumo.CAMPOS},
                    }
                for origen, col in consumo.CAMPOS:
                    fila[col] = max(fila[col], uso.get(origen) or 0)
                detalles = uso.get("output_tokens_details") or {}
                fila["razonado"] = max(fila["razonado"],
                                       detalles.get("thinking_tokens") or 0)
    return fuera


def _raiz():
    return Path(os.environ["HUB_TRANSCRIPTS"])


def _tabla(con):
    """La tabla entera salvo `medido_en`, que es la hora del escaneo."""
    return [tuple(f) for f in con.execute(
        """SELECT proyecto_id, ruta, dia, modelo, peticiones, entrada, escritura, lectura,
                  salida, razonado, razonadas, desde, hasta
           FROM consumo ORDER BY ruta, dia, modelo""")]


def _un_segundo_despues(archivo):
    """Como si el cambio hubiera llegado un segundo más tarde. En una prueba
    todo pasa en el mismo milisegundo, y con núcleos anteriores al 6.13 dos
    escrituras en el mismo tic del reloj llevan la misma fecha."""
    st = archivo.stat()
    os.utime(archivo, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def _anadir(archivo, *lineas):
    with archivo.open("a", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")


def _comprobar_que_coinciden(con):
    """En caliente, en frío y con la pasada de antes: las tres, lo mismo."""
    raiz = _raiz()
    lejos = consumo.time.monotonic() + 600
    patron = _leyendo_todo_linea_a_linea(raiz)
    en_caliente = consumo._peticiones(raiz, lejos)
    assert en_caliente == patron
    assert list(en_caliente) == list(patron), "cambió el orden en que salen las peticiones"

    consumo.escanear(con, _proyectos_de(con))
    tabla_en_caliente = _tabla(con)
    recordar.olvidar()
    assert consumo._peticiones(raiz, lejos) == patron
    consumo.escanear(con, _proyectos_de(con))
    assert _tabla(con) == tabla_en_caliente
    return tabla_en_caliente


# Para contar qué archivos se leen de verdad: `recordar` exige una función de
# módulo (por su nombre distingue a los lectores), así que el contador es una.
LEIDOS: list[str] = []
_de_archivo_de_verdad = consumo._de_archivo


def _de_archivo_contando(archivo):
    LEIDOS.append(archivo.name)
    return _de_archivo_de_verdad(archivo)


def test_la_tabla_es_la_misma_recordando_que_leyendo_todo(con, proyecto_demo, registro):
    """🔴 El corazón de C-0326 (reglas duras 13 y 19).

    **Por qué coinciden, y no sólo que coinciden.** La pasada completa pliega
    las líneas archivo a archivo, en orden `sorted`, sobre un diccionario por
    petición. De cada petición guarda dos clases de cosas:

    - los recuentos, que son un **máximo** sobre todas sus líneas; y el
      máximo de todas es el máximo de los máximos de cada archivo;
    - ruta, día, modelo y hora, que son de la **primera línea vista**; y la
      primera vista es la primera del primer archivo, en ese orden, que trae
      la petición.

    Leer cada archivo por separado (su máximo y su primera línea por
    petición) y fundir los resultados en el mismo orden da, pues, lo mismo
    por construcción; y recordar el resultado de un archivo no cambia nada
    mientras ese resultado sea el que daría leerlo otra vez. Ése es el único
    supuesto: **un archivo con la misma huella (fecha, tamaño e inodo) tiene
    el mismo contenido**. Aquí se le hace al registro todo lo que le pasa en
    la vida real y, tras cada cosa, se compara con la pasada de antes.
    """
    A, B = "/tmp/demo", "/tmp/otro"
    registro("s1", [_linea("req_A", cwd=A, salida=10, lectura=1000, cuando="2026-08-20T10:00:00.000Z"),
                    _linea("req_A", cwd=A, salida=387, lectura=1000, cuando="2026-08-20T10:00:01.000Z"),
                    _linea("req_B", cwd=A, salida=5, razonado=3, cuando="2026-08-20T11:00:00.000Z")])
    registro("s2", [_linea("req_C", cwd=B, salida=40, modelo="claude-haiku-5",
                           cuando="2026-08-21T09:00:00.000Z")], carpeta="-tmp-otro")
    registro("s3", ["esto no es json", "", "{roto"])
    antes = _comprobar_que_coinciden(con)
    assert sum(f[4] for f in antes) == 3

    # 1. Se añaden líneas a un transcript: una petición nueva y otra que crece.
    s1 = _raiz() / "-tmp-demo" / "s1.jsonl"
    _anadir(s1, _linea("req_B", cwd=A, salida=90, razonado=30, cuando="2026-08-20T11:00:05.000Z"),
            _linea("req_D", cwd=A, salida=7, cuando="2026-08-22T08:00:00.000Z"))
    tabla = _comprobar_que_coinciden(con)
    assert tabla != antes and sum(f[4] for f in tabla) == 4

    # 2. Un archivo nuevo, con una petición que ya estaba en otro (sesión
    #    reanudada) y que aquí lleva MÁS salida y otro cwd: suma el máximo,
    #    pero la ruta y el día siguen siendo los del primero en orden.
    registro("s0-reanudada", [_linea("req_C", cwd=A, salida=400, cuando="2026-08-25T09:00:00.000Z")],
             carpeta="-tmp-otro")
    registro("s9", [_linea("req_A", cwd=B, salida=999, lectura=1000, cuando="2026-09-01T10:00:00.000Z")],
             carpeta="-tmp-otro")
    tabla = _comprobar_que_coinciden(con)
    assert sum(f[4] for f in tabla) == 4, "una petición repartida se contó dos veces"

    # 3. Una última línea a medio escribir, que luego se completa.
    with s1.open("a", encoding="utf-8") as f:
        f.write(_linea("req_E", cwd=A, salida=11)[:40])
    _comprobar_que_coinciden(con)
    with s1.open("a", encoding="utf-8") as f:
        f.write(_linea("req_E", cwd=A, salida=11)[40:] + "\n")
    assert sum(f[4] for f in _comprobar_que_coinciden(con)) == 5

    # 4. Claude Code poda un transcript: lo suyo deja de contar.
    (_raiz() / "-tmp-otro" / "s2.jsonl").unlink()
    _comprobar_que_coinciden(con)

    # 5. Se reemplaza por renombrado (escribir aparte y mover encima).
    s9 = _raiz() / "-tmp-otro" / "s9.jsonl"
    aparte = s9.with_suffix(".tmp")
    aparte.write_text(_linea("req_F", cwd=B, salida=1, cuando="2026-09-02T10:00:00.000Z") + "\n",
                      encoding="utf-8")
    os.replace(aparte, s9)
    _comprobar_que_coinciden(con)

    # 6. Se reescribe en el sitio con el MISMO tamaño y otro contenido.
    tamano = s9.stat().st_size
    s9.write_text(_linea("req_G", cwd=B, salida=2, cuando="2026-09-02T10:00:00.000Z") + "\n",
                  encoding="utf-8")
    assert s9.stat().st_size == tamano
    _un_segundo_despues(s9)
    tabla = _comprobar_que_coinciden(con)
    assert any(f[1] == B and f[8] == 2 for f in tabla), "se quedó con lo de antes de reescribir"


def test_recordando_sale_lo_mismo_tras_doscientos_cambios_al_azar(con, proyecto_demo, registro):
    """Lo mismo que el anterior, sin elegir yo los casos: doscientos cambios
    al azar (con semilla fija, para que un fallo se pueda repetir) y, tras
    cada uno, lo recordado contra la pasada de antes."""
    azar = random.Random(326)
    raiz = _raiz()
    lejos = consumo.time.monotonic() + 600
    carpetas = ["-a", "-b", "-c"]
    cwds = ["/tmp/demo", "/tmp/otro", ""]
    modelos = ["claude-opus-5", "claude-haiku-5", None]
    serie = 0
    mayor = repartidas = 0

    def lineas(cuantas):
        salida = []
        for _ in range(cuantas):
            # Pocas peticiones distintas: así se repiten dentro de un archivo
            # y entre archivos, que es donde está el riesgo.
            peticion = azar.choice([f"req_{azar.randrange(25)}", f"req_{azar.randrange(25)}", None])
            dato = json.loads(_linea(peticion, cwd=azar.choice(cwds), salida=azar.randrange(500),
                                     lectura=azar.randrange(5000), escritura=azar.randrange(50),
                                     razonado=azar.choice([0, 0, azar.randrange(80)]),
                                     modelo=azar.choice(modelos),
                                     cuando=f"2026-08-{azar.randrange(10, 28)}T10:00:{azar.randrange(60):02d}.000Z",
                                     tipo=azar.choice(["assistant"] * 5 + ["user"])))
            if peticion is None:
                del dato["requestId"]
                dato["uuid"] = f"u{azar.randrange(40)}"
            salida.append(json.dumps(dato))
        return salida

    for paso in range(200):
        archivos = sorted(raiz.rglob("*.jsonl"))
        que = azar.choice(["nuevo"] * 3 + ["anadir"] * 5 + ["borrar", "renombrar", "reescribir"])
        if que == "nuevo" or not archivos:
            serie += 1
            registro(f"s{azar.randrange(1000):03d}-{serie}", lineas(azar.randrange(0, 6)),
                     carpeta=azar.choice(carpetas))
        elif que == "anadir":
            _anadir(azar.choice(archivos), *lineas(azar.randrange(1, 5)))
        elif que == "borrar":
            azar.choice(archivos).unlink()
        elif que == "renombrar":
            destino = azar.choice(archivos)
            aparte = destino.with_suffix(".tmp")
            aparte.write_text("\n".join(lineas(azar.randrange(0, 5))) + "\n", encoding="utf-8")
            os.replace(aparte, destino)
        else:
            destino = azar.choice(archivos)
            destino.write_text("\n".join(lineas(azar.randrange(0, 5))) + "\n", encoding="utf-8")
            _un_segundo_despues(destino)

        patron = _leyendo_todo_linea_a_linea(raiz)
        recordado = consumo._peticiones(raiz, lejos)
        assert recordado == patron, f"paso {paso} ({que})"
        assert list(recordado) == list(patron), f"paso {paso} ({que}): otro orden"
        assert consumo._agregar(recordado) == consumo._agregar(patron), f"paso {paso} ({que})"
        mayor = max(mayor, len(patron))
        sueltas = sum(len(_de_archivo_de_verdad(a) or {}) for a in raiz.rglob("*.jsonl"))
        repartidas += sueltas > len(patron)
    # Que el azar llegó a montar algo que pruebe: un registro con cuerpo y,
    # casi siempre, peticiones repartidas entre varios archivos.
    assert mayor > 40 and repartidas > 150, (mayor, repartidas)


@pytest.fixture
def leidos(monkeypatch):
    LEIDOS.clear()
    monkeypatch.setattr(consumo, "_de_archivo", _de_archivo_contando)
    return LEIDOS


def test_el_segundo_escaneo_no_vuelve_a_leer_lo_que_no_cambio(con, proyecto_demo, registro, leidos):
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=10)])
    registro("s2", [_linea("req_B", cwd="/tmp/demo", salida=20)])
    registro("s3", [])           # sin peticiones: también se recuerda, no se relee
    consumo.escanear(con, _proyectos_de(con))
    assert sorted(leidos) == ["s1.jsonl", "s2.jsonl", "s3.jsonl"]

    leidos.clear()
    consumo.escanear(con, _proyectos_de(con))
    assert leidos == []
    assert con.execute("SELECT SUM(peticiones), SUM(salida) FROM consumo").fetchone()[:] == (2, 30)

    _anadir(_raiz() / "-tmp-demo" / "s2.jsonl", _linea("req_C", cwd="/tmp/demo", salida=5))
    consumo.escanear(con, _proyectos_de(con))
    assert leidos == ["s2.jsonl"], "sólo se relee el que cambió, y entero"


def test_lo_anadido_a_un_transcript_entra_y_sube_la_salida_al_maximo(con, proyecto_demo, registro):
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=10, lectura=1000)])
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT peticiones, salida FROM consumo").fetchone()[:] == (1, 10)

    _anadir(_raiz() / "-tmp-demo" / "s1.jsonl",
            _linea("req_A", cwd="/tmp/demo", salida=387, lectura=1000),
            _linea("req_B", cwd="/tmp/demo", salida=3))
    consumo.escanear(con, _proyectos_de(con))
    fila = con.execute("SELECT peticiones, salida, lectura FROM consumo").fetchone()
    assert fila[:] == (2, 390, 1000), "la misma petición creció: es su máximo, no una segunda"


def test_un_transcript_podado_deja_de_contar_en_el_siguiente_escaneo(con, proyecto_demo, registro):
    """Sin pasada diaria: un archivo que ya no está no sale en el recorrido,
    así que no se funde. Lo recordado de él se suelta en ese mismo escaneo."""
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=10)])
    registro("s2", [_linea("req_B", cwd="/tmp/demo", salida=20, cuando="2026-08-01T10:00:00.000Z")])
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 2

    (_raiz() / "-tmp-demo" / "s2.jsonl").unlink()
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT SUM(peticiones), SUM(salida) FROM consumo").fetchone()[:] == (1, 10)
    assert not con.execute("SELECT 1 FROM consumo WHERE dia='2026-08-01'").fetchone()


def test_una_peticion_en_dos_archivos_toma_ruta_y_dia_del_primero_en_orden_aunque_solo_cambie_el_segundo(
    con, proyecto_demo, registro, leidos
):
    """Lo que un conjunto global de `requestId` ya vistos haría mal: la fila
    heredaría la ruta y el día del archivo que se leyó primero EN EL TIEMPO.
    Aquí el primero en orden (`a`) se lee una vez y no vuelve a tocarse; el
    que cambia es el segundo (`b`), y la petición sigue siendo de `a`."""
    registro("a", [_linea("req_A", cwd="/tmp/demo", salida=10, cuando="2026-08-20T10:00:00.000Z")])
    registro("b", [_linea("req_A", cwd="/tmp/otro", salida=50, cuando="2026-08-25T10:00:00.000Z")])
    consumo.escanear(con, _proyectos_de(con))
    leidos.clear()

    _anadir(_raiz() / "-tmp-demo" / "b.jsonl",
            _linea("req_A", cwd="/tmp/otro", salida=700, cuando="2026-08-26T10:00:00.000Z"))
    consumo.escanear(con, _proyectos_de(con))
    assert leidos == ["b.jsonl"]
    (fila,) = con.execute("SELECT ruta, dia, peticiones, salida FROM consumo").fetchall()
    assert fila[:] == ("/tmp/demo", "2026-08-20", 1, 700)

    # Y si el que desaparece es el primero, pasa a ser del que queda.
    (_raiz() / "-tmp-demo" / "a.jsonl").unlink()
    consumo.escanear(con, _proyectos_de(con))
    (fila,) = con.execute("SELECT ruta, dia, peticiones, salida FROM consumo").fetchall()
    assert fila[:] == ("/tmp/otro", "2026-08-25", 1, 700)


def test_un_archivo_que_no_se_pudo_abrir_se_reintenta(con, proyecto_demo, registro, monkeypatch):
    """Un «no pude abrirlo» no se recuerda: recordado, ese transcript no
    volvería a contar hasta que cambiase o se reiniciara el muestreo."""
    registro("s1", [_linea("req_A", cwd="/tmp/demo", salida=10)])
    registro("s2", [_linea("req_B", cwd="/tmp/demo", salida=20)])
    abrir = Path.open
    falla = {"si": True}

    def abrir_o_no(self, *a, **k):
        if falla["si"] and self.name == "s2.jsonl":
            raise PermissionError(13, "Permission denied")
        return abrir(self, *a, **k)

    monkeypatch.setattr(Path, "open", abrir_o_no)
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 1

    falla["si"] = False            # el archivo no ha cambiado: misma huella
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 2


def test_fundir_no_modifica_lo_recordado(con, proyecto_demo, registro):
    """Lo recordado se devuelve sin copia: si fundir escribiera en ello, la
    salida de una petición repartida subiría en lo recordado del primer
    archivo y ya no bajaría aunque el segundo se podara."""
    registro("a", [_linea("req_A", cwd="/tmp/demo", salida=10)])
    registro("b", [_linea("req_A", cwd="/tmp/demo", salida=900)])
    raiz = _raiz()
    lejos = consumo.time.monotonic() + 600
    de_a = consumo._de_archivo(raiz / "-tmp-demo" / "a.jsonl")

    primera = consumo._peticiones(raiz, lejos)
    assert primera["req_A"]["salida"] == 900
    primera["req_A"]["salida"] = 123456         # quien recibe puede tocar lo suyo
    assert recordar.por_archivo(raiz / "-tmp-demo" / "a.jsonl", consumo._de_archivo) == de_a

    (raiz / "-tmp-demo" / "b.jsonl").unlink()
    assert consumo._peticiones(raiz, lejos)["req_A"]["salida"] == 10


def test_pasarse_del_presupuesto_no_escribe_y_el_siguiente_ciclo_sigue_donde_iba(
    con, proyecto_demo, registro, leidos, monkeypatch
):
    """El corte sigue entre archivos y sin recuento a medias; pero lo leído
    hasta el corte queda recordado, así que un registro demasiado grande para
    una vuelta se acaba de leer en la siguiente en vez de no medirse nunca."""
    registro("s0", [_linea("req_0", cwd="/tmp/demo", salida=1)])
    consumo.escanear(con, _proyectos_de(con))
    for n in range(1, 5):
        registro(f"s{n}", [_linea(f"req_{n}", cwd="/tmp/demo", salida=1)])
    leidos.clear()

    reloj = {"ahora": 1000.0}

    def cada_archivo_tarda_25_s():
        reloj["ahora"] += 25
        return reloj["ahora"]

    with monkeypatch.context() as m:
        m.setattr(consumo.time, "monotonic", cada_archivo_tarda_25_s)
        with pytest.raises(consumo.ConsumoNoMedido):
            consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 1, "escribió a medias"
    ya = list(leidos)
    assert ya and len(ya) < 4

    leidos.clear()
    consumo.escanear(con, _proyectos_de(con))
    assert sorted(leidos + ya) == ["s1.jsonl", "s2.jsonl", "s3.jsonl", "s4.jsonl"], \
        "volvió a leer lo que ya tenía, o se dejó alguno"
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 5


def test_valores_raros_en_el_registro_no_rompen_el_escaneo(con, proyecto_demo, registro):
    """`cwd` o el modelo pueden no ser texto en una línea estropeada. Antes
    se guardaba lo que viniera; internar cadenas no puede convertirlo en un
    error que deje sin medir todo lo demás."""
    rara = json.loads(_linea("req_R", cwd="/tmp/demo", salida=4))
    rara["cwd"] = None
    rara["message"]["model"] = 7
    registro("s1", [json.dumps(rara), _linea("req_A", cwd="/tmp/demo", salida=10)])
    raiz = _raiz()
    assert consumo._peticiones(raiz, consumo.time.monotonic() + 600) == _leyendo_todo_linea_a_linea(raiz)
    consumo.escanear(con, _proyectos_de(con))
    assert con.execute("SELECT SUM(peticiones) FROM consumo").fetchone()[0] == 2


def test_lo_recordado_de_un_transcript_podado_se_suelta_en_el_escaneo_siguiente(
    con, proyecto_demo, registro
):
    for n in range(4):
        registro(f"s{n}", [_linea(f"req_{n}", cwd="/tmp/demo", salida=1)])
    consumo.escanear(con, _proyectos_de(con))
    recordados = recordar._por_archivo["hub.consumo._de_archivo"]
    assert len(recordados) == 4

    (_raiz() / "-tmp-demo" / "s1.jsonl").unlink()
    (_raiz() / "-tmp-demo" / "s3.jsonl").unlink()
    consumo.escanear(con, _proyectos_de(con))
    assert sorted(Path(r).name for r in recordados) == ["s0.jsonl", "s2.jsonl"]


def test_un_escaneo_cortado_por_el_presupuesto_no_suelta_nada(con, proyecto_demo, registro, monkeypatch):
    """Cortado a medias no ha visto la lista entera: soltar ahí tiraría lo
    que el escaneo siguiente iba a aprovechar."""
    for n in range(4):
        registro(f"s{n}", [_linea(f"req_{n}", cwd="/tmp/demo", salida=1)])
    consumo.escanear(con, _proyectos_de(con))
    (_raiz() / "-tmp-demo" / "s0.jsonl").unlink()
    with pytest.raises(consumo.ConsumoNoMedido):
        consumo._peticiones(_raiz(), consumo.time.monotonic() - 1)
    assert len(recordar._por_archivo["hub.consumo._de_archivo"]) == 4


def test_el_rango_y_las_columnas_cuentan_los_mismos_dias(con, proyecto_demo, registro, tmp_path, monkeypatch):
    """Regla 19, tras la revisión de C-0396: las columnas se agrupan por día
    UTC (`marca[:10]`) y el rótulo «Del… al…» salía en día de la casa. A las
    20:00 de aquí ya es mañana en UTC: en los bordes discrepaban un día."""
    import re

    from fastapi.testclient import TestClient
    from hub import db, web
    monkeypatch.setenv("TZ", "America/Mexico_City")
    registro("s1", [
        _linea("req_A", cwd="/tmp/demo", salida=100, cuando="2026-08-10T09:00:00.000Z"),
        _linea("req_B", cwd="/tmp/demo", salida=100, cuando="2026-09-11T02:00:00.000Z"),
    ])
    consumo.escanear(con, _proyectos_de(con))
    con.commit()
    monkeypatch.setattr(web, "conexion", lambda: db.conectar(tmp_path / "hub.db"))

    datos = api.consumo(con)
    assert (datos["primer_dia"], datos["ultimo_dia"]) == ("2026-08-10", "2026-09-11")
    assert [c["dia"] for c in datos["grafica"]["columnas"]][-1] == "2026-09-11"
    for ruta in ("/consumo", "/proyecto/demo"):
        texto = re.sub(r"<[^>]+>", "", TestClient(web.app).get(ruta).text)
        texto = " ".join(texto.split())
        assert re.search(r"[Dd]el 10/08(/2026)? al 11/09(/2026)? \(días en UTC", texto), ruta
