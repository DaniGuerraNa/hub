"""Lo último que llegó, entero o diciendo que no (C-0392).

«Resúmeme el grupo de hoy» con 266 mensajes: `recientes` cortaba en 100 sin
decirlo y el modelo resumía 100 como si fueran todos. Ahora la herramienta
dice cuántos hay (`total`), si queda algo (`hay_mas`) y por dónde seguir
(`siguiente`, que se pasa en `antes_de`), en el orden `(fecha, id)`, y ajusta
la página a lo que cabe en lo que el MCP le manda al modelo.
"""

from __future__ import annotations

import json

import pytest

from hub.secretario import herramientas, memoria, piezas


@pytest.fixture
def con(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    c = memoria.conectar()
    yield c
    c.close()


def _evento(con, i, fecha, texto="", conversacion="Equipo", autor="Ana", para_mi="otros") -> int:
    memoria.guardar_evento(con, piezas.Evento(fuente="telegram", id_externo=str(i), fecha=fecha,
                                              texto=texto or f"mensaje {i}", conversacion=conversacion,
                                              autor=autor, para_mi=para_mi))
    return con.execute("SELECT id FROM evento WHERE id_externo = ?", (str(i),)).fetchone()[0]


def _fecha(minuto: int) -> str:
    return f"2026-11-13T{14 + minuto // 60:02d}:{minuto % 60:02d}:00+00:00"


def _usar(con, **p):
    return herramientas.todas(con_el_dueno=True)["recientes"].funcion(con, p)


def _recorrer(con, **p) -> tuple[list[int], list[dict]]:
    vistos, paginas, antes_de = [], [], None
    while True:
        d = _usar(con, **p, **({"antes_de": antes_de} if antes_de else {}))
        paginas.append(d)
        vistos += [m["id"] for m in d["mensajes"]]
        if not d["hay_mas"]:
            return vistos, paginas
        antes_de = d["siguiente"]
        assert len(paginas) < 50, "no termina"


def test_con_266_mensajes_de_un_chat_recientes_dice_el_total_y_que_hay_mas(con):
    for i in range(266):
        _evento(con, i, _fecha(i))
    _evento(con, 999, _fecha(10), conversacion="Otro chat")

    d = _usar(con, conversacion="Equipo", n=100)

    assert len(d["mensajes"]) == 100 and d["total"] == 266 and d["hay_mas"] is True
    assert d["siguiente"] == d["mensajes"][-1]["id"]
    assert d["mensajes"][0]["texto"] == "mensaje 265", "lo más nuevo primero"


def test_pidiendo_antes_de_se_recorren_todos_sin_repetir_ni_saltar_ninguno(con):
    ids = [_evento(con, i, _fecha(i)) for i in range(266)]

    vistos, paginas = _recorrer(con, n=100)

    assert vistos == ids[::-1]
    assert [len(p["mensajes"]) for p in paginas] == [100, 100, 66]
    assert paginas[-1]["siguiente"] is None and {p["total"] for p in paginas} == {266}


def test_la_paginacion_sigue_la_fecha_aunque_los_ids_vayan_en_otro_orden(con):
    """Un chat exportado entra con ids nuevos y fechas viejas."""
    nuevos = [_evento(con, i, _fecha(100 + i)) for i in range(5)]
    exportados = [_evento(con, 50 + i, _fecha(i)) for i in range(5)]

    vistos, _ = _recorrer(con, n=3)

    assert vistos == nuevos[::-1] + exportados[::-1]


def test_dos_mensajes_con_la_misma_fecha_no_se_repiten_entre_paginas(con):
    ids = [_evento(con, i, _fecha(7)) for i in range(7)]

    vistos, paginas = _recorrer(con, n=2)

    assert sorted(vistos) == sorted(ids) and len(vistos) == len(set(vistos))
    assert vistos == sorted(ids, reverse=True), "a igual fecha, el id decide"
    assert len(paginas) == 4


def test_una_pagina_de_mensajes_largos_trae_menos_y_su_siguiente_es_el_ultimo_que_va(con):
    ids = [_evento(con, i, _fecha(i), texto=f"{i} " + "palabra larga " * 200) for i in range(100)]

    d = _usar(con, n=100)

    assert len(herramientas._json(d)) <= herramientas.TOPE_SALIDA
    assert 0 < len(d["mensajes"]) < 100 and d["hay_mas"] is True and d["total"] == 100
    assert d["siguiente"] == d["mensajes"][-1]["id"], "el último que de verdad va"
    vistos, paginas = _recorrer(con, n=100)
    assert vistos == ids[::-1], "nada se salta por el corte"
    assert all(len(herramientas._json(p)) <= herramientas.TOPE_SALIDA for p in paginas)


def test_recientes_filtra_por_autor_como_palabra_entera_y_sin_tildes(con):
    _evento(con, 1, _fecha(1), autor="Ana")
    _evento(con, 2, _fecha(2), autor="Anabel")
    _evento(con, 3, _fecha(3), autor="Ana María")
    _evento(con, 4, _fecha(4), autor="ÁNA López")

    d = _usar(con, autor="ana")

    assert sorted(m["autor"] for m in d["mensajes"]) == ["Ana", "Ana María", "ÁNA López"] and d["total"] == 3
    assert memoria.autores_llamados(con, "ana") == memoria.sobre_persona(con, "ana")["autores"], "la misma regla"
    assert _usar(con, autor="Nadie") == {"mensajes": [], "total": 0, "hay_mas": False, "siguiente": None}


def test_recientes_con_hasta_un_dia_incluye_la_tarde_de_ese_dia(con):
    _evento(con, 1, "2026-11-10T23:00:00+00:00", "la tarde del 10")      # 17:00 del 10, en casa
    _evento(con, 2, "2026-11-11T05:30:00+00:00", "la noche del 10")      # 23:30 del 10
    _evento(con, 3, "2026-11-11T14:00:00+00:00", "la mañana del 11")

    d = _usar(con, desde="2026-11-10", hasta="2026-11-10")

    assert [m["texto"] for m in d["mensajes"]] == ["la noche del 10", "la tarde del 10"] and d["total"] == 2
    assert "error" in _usar(con, hasta="el martes")


def test_memoria_recientes_sigue_devolviendo_una_lista_para_quien_ya_la_llama(con):
    _evento(con, 1, _fecha(1))
    _evento(con, 2, _fecha(2))

    filas = memoria.recientes(con, n=1)

    assert isinstance(filas, list) and [f["texto"] for f in filas] == ["mensaje 2"]


def test_el_total_cuenta_con_los_mismos_filtros_que_la_pagina(con):
    _evento(con, 1, _fecha(1), autor="Ana", para_mi="nombre")
    _evento(con, 2, _fecha(2), autor="Ana", para_mi="otros")
    _evento(con, 3, _fecha(3), autor="Luis", para_mi="privado")
    _evento(con, 4, _fecha(4), autor="Ana", para_mi="etiqueta", conversacion="Otro")

    filtros = {"autor": "Ana", "solo_para_mi": True, "conversacion": "Equipo"}
    d = _usar(con, **filtros)

    assert [m["texto"] for m in d["mensajes"]] == ["mensaje 1"] and d["total"] == 1
    assert memoria.contar_recientes(con, **filtros) == len(memoria.recientes(con, **filtros))


def test_un_antes_de_que_no_es_un_mensaje_lo_dice(con):
    _evento(con, 1, _fecha(1))

    assert "error" in _usar(con, antes_de=987654)
    assert "error" in _usar(con, antes_de="3")
    assert "error" in _usar(con, antes_de=-1)


def test_la_descripcion_le_dice_que_hay_mas_y_como_seguir():
    [h] = [h for h in herramientas.LECTURAS if h.nombre == "recientes"]
    assert "hay_mas" in h.descripcion and "antes_de" in h.descripcion and "siguiente" in h.descripcion
    assert {"autor", "hasta", "antes_de"} <= set(h.esquema["properties"])
    assert json.dumps(h.esquema)


# ── el corte de lo que viaja al modelo (`herramientas.acotar`) ───────────────

TOPE = herramientas.TOPE_SALIDA


def test_una_salida_de_70000_caracteres_llega_como_json_valido_y_dice_recortado():
    salida = {"lineas": [f"{i:05d} " + "x" * 60 for i in range(1100)], "reunion": 4}
    assert len(herramientas._json(salida)) > 70_000

    texto = herramientas.acotar(salida)

    d = json.loads(texto)
    assert len(texto) <= TOPE and d["recortado"] is True and d["reunion"] == 4
    assert d["lineas"] == salida["lineas"][:len(d["lineas"])], "las primeras, enteras y en orden"


def test_un_objeto_con_una_lista_enorme_se_recorta_por_la_lista_y_sigue_siendo_json():
    salida = {"id": 7, "texto": "corto", "alrededor": [{"id": i, "texto": "y" * 500} for i in range(400)]}

    d = json.loads(herramientas.acotar(salida))

    assert d["id"] == 7 and d["texto"] == "corto" and d["recortado"] is True
    assert 0 < len(d["alrededor"]) < 400 and d["alrededor"][0] == salida["alrededor"][0]


def test_un_texto_largo_dentro_de_un_objeto_se_corta_por_la_cola():
    salida = {"id": 3, "texto": "z" * 80_000}

    texto = herramientas.acotar(salida)

    d = json.loads(texto)
    assert len(texto) <= TOPE and d["id"] == 3 and d["recortado"] is True
    queda, marca = d["texto"].split("… [faltan ")
    assert set(queda) == {"z"} and len(queda) + int(marca.removesuffix(" caracteres]")) == 80_000


def test_un_elemento_solo_mayor_que_el_tope_queda_recortado_con_su_marca_y_no_vacio():
    """Tras la revisión: `{"lineas": ["q" * 200000]}` salía `{"lineas": []}`,
    vacío sin decir que faltaba algo."""
    for salida, donde in (({"lineas": ["q" * 200_000]}, lambda d: d["lineas"]),
                          (["q" * 200_000], lambda d: d["elementos"])):
        texto = herramientas.acotar(salida)

        d = json.loads(texto)
        [uno] = donde(d)
        assert len(texto) <= TOPE and d["recortado"] is True
        assert uno.startswith("qqqq") and uno.endswith(" caracteres]") and "… [faltan " in uno


def test_una_lista_recortada_dentro_de_un_objeto_dice_cuantos_faltan():
    salida = {"reunion": 4, "lineas": [f"{i:05d} " + "x" * 60 for i in range(1100)]}

    d = json.loads(herramientas.acotar(salida))

    assert d["faltan"] == {"lineas": 1100 - len(d["lineas"])} and 0 < len(d["lineas"]) < 1100


def test_una_lista_que_no_cabe_va_dentro_de_un_objeto_que_dice_cuantos_faltan():
    salida = [{"n": i, "t": "w" * 300} for i in range(500)]

    d = json.loads(herramientas.acotar(salida))

    assert d["recortado"] is True and d["faltan"] == 500 - len(d["elementos"]) > 0
    assert d["elementos"] == salida[:len(d["elementos"])]


def test_un_texto_largo_se_corta_y_dice_cuanto_falta():
    salida = "linea\n" * 20_000                                     # 120 000 caracteres

    texto = herramientas.acotar(salida)

    assert len(texto) <= TOPE and texto.startswith("linea\nlinea\n")
    cola = texto.rsplit("\n", 1)[-1]
    faltan = int(cola.removeprefix("[recortado: faltan ").removesuffix(" caracteres]"))
    assert len(texto) - len(cola) - 1 + faltan == len(salida), "lo que va más lo que falta es el total"


def test_lo_que_cabe_viaja_identico_a_antes():
    for salida in ("hola", {"a": [1, 2, "ñ"], "b": None}, [1, 2, 3], 42, "x" * TOPE):
        antes = salida if isinstance(salida, str) else json.dumps(salida, ensure_ascii=False, default=str)
        assert herramientas.acotar(salida) == antes


def _por_mcp(con, salida, monkeypatch):
    import io
    import sys

    from hub.secretario import mcp

    salida_estandar = io.StringIO()
    monkeypatch.setattr(sys, "stdout", salida_estandar)
    h = herramientas.Herramienta("prueba", "una de prueba", {"type": "object", "properties": {}},
                                 lambda c, p: salida)
    mcp.atender({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "prueba", "arguments": {}}},
                {"prueba": h}, con)
    return json.loads(salida_estandar.getvalue())["result"]["content"]


def test_el_mcp_manda_lo_acotado_y_no_un_json_cortado_a_la_mitad(con, monkeypatch):
    salida = {"lineas": ["l" * 100] * 1000}

    [c] = _por_mcp(con, salida, monkeypatch)

    assert c["type"] == "text" and json.loads(c["text"])["recortado"] is True and len(c["text"]) <= TOPE


def test_una_imagen_sigue_viajando_como_imagen(con, monkeypatch):
    import base64

    imagen = herramientas.Imagen(b"\x89PNG" + b"\0" * 100_000, "image/png", "la captura")

    texto, img = _por_mcp(con, imagen, monkeypatch)

    assert texto == {"type": "text", "text": "la captura"}
    assert img["type"] == "image" and base64.b64decode(img["data"]) == imagen.datos, "entera: no pasa por acotar"
