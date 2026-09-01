"""Lectura de transcripts.

Es el suelo sobre el que se apoya el asistente: si el esqueleto pierde texto, el
asistente contesta sobre una conversación que no ocurrió. Y si revienta con un
JSONL a medio escribir, se queda ciego justo sobre la sesión que está viva, que
es la que más interesa mirar.
"""

from __future__ import annotations

import json

import pytest

from hub import transcripts
from hub.models import Proyecto, Ruta


def _escribir(ruta, lineas):
    ruta.write_text("\n".join(json.dumps(l) for l in lineas) + "\n", encoding="utf-8")
    return ruta


def _user(uuid, texto, **extra):
    return {
        "type": "user", "uuid": uuid, "timestamp": "2026-08-28T10:00:00.000Z",
        "cwd": "/tmp/demo", "gitBranch": "main", "isSidechain": False,
        "message": {"role": "user", "content": texto}, **extra,
    }


def _assistant(uuid, bloques, **extra):
    return {
        "type": "assistant", "uuid": uuid, "timestamp": "2026-08-28T10:05:00.000Z",
        "cwd": "/tmp/demo", "gitBranch": "main", "isSidechain": False,
        "message": {"role": "assistant", "model": "claude-sonnet-5", "content": bloques},
        **extra,
    }


@pytest.fixture
def sesion(tmp_path):
    return _escribir(tmp_path / "aaaaaaaa-1111-2222-3333-444444444444.jsonl", [
        {"type": "mode", "mode": "default"},
        {"type": "ai-title", "aiTitle": "Arreglar el respaldo", "sessionId": "aaaa"},
        _user("u1", "mide los commits sin respaldo"),
        _assistant("a1", [
            {"type": "thinking", "thinking": "esto no debería salir", "signature": "x"},
            {"type": "text", "text": "Voy a mirarlo."},
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "git rev-list --count HEAD --not --remotes"}},
        ]),
        _user("u2", [{"type": "tool_result", "tool_use_id": "t1", "content": "473"}]),
        _assistant("a2", [{"type": "text", "text": "Son 473 commits."}]),
        {"type": "file-history-snapshot", "messageId": "x"},
    ])


# --------------------------------------------------------------------------- #
# El slug
# --------------------------------------------------------------------------- #


def test_el_slug_convierte_cada_caracter_no_alfanumerico_en_un_guion():
    # Comprobado contra el disco: la doble `--` sale de `ana_/`, que son dos
    # caracteres no alfanuméricos seguidos. Colapsarlos daría un directorio que
    # no existe y el asistente no vería ninguna sesión de ese proyecto.
    assert transcripts.slug_de(
        "/mnt/c/Users/ana_/Escritorio/proyectos/personal"
    ) == "-mnt-c-Users-ana--Escritorio-proyectos-personal"


def test_el_slug_ignora_la_barra_final_para_no_generar_dos_directorios():
    assert transcripts.slug_de("/home/ana/dev/") == transcripts.slug_de("/home/ana/dev")


def test_el_slug_resuelve_las_rutas_reales_de_un_proyecto(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", tmp_path)
    proyecto = Proyecto(
        id="tienda", nombre="Tienda", asiento="/mnt/c/proyectos/tienda",
        rutas=[Ruta(ruta="/home/ana/dev/tienda")],
    )
    # Sólo existe uno de los dos: el que no está en disco no se inventa.
    (tmp_path / "-home-ana-dev-tienda").mkdir()
    assert [d.name for d in transcripts.directorios_de(proyecto)] == [
        "-home-ana-dev-tienda"
    ]


# --------------------------------------------------------------------------- #
# El esqueleto
# --------------------------------------------------------------------------- #


def test_el_esqueleto_conserva_todo_el_texto_y_tira_lo_demas(sesion):
    mensajes = transcripts.esqueleto(sesion)["mensajes"]

    textos = [m["texto"] for m in mensajes]
    assert textos == [
        "mide los commits sin respaldo",
        "Voy a mirarlo.",
        "Son 473 commits.",
    ]
    # El `thinking` y el `tool_result` no dejan rastro; la llamada sí, en una línea.
    crudo = json.dumps(mensajes, ensure_ascii=False)
    assert "no debería salir" not in crudo
    assert "473" in textos[2] and "tool_result" not in crudo


def test_una_llamada_a_herramienta_queda_en_una_linea_reconocible(sesion):
    mensajes = transcripts.esqueleto(sesion)["mensajes"]
    assert mensajes[1]["herramientas"] == [
        "[Bash: git rev-list --count HEAD --not --remotes]"
    ]


def test_un_mensaje_que_solo_traia_tool_result_no_aparece_como_turno(sesion):
    # Es el 99 % del volumen y no lo dijo nadie: si apareciera, el chat mostraría
    # mensajes vacíos del usuario entre cada herramienta.
    assert all(m["uuid"] != "u2" for m in transcripts.esqueleto(sesion)["mensajes"])


def test_el_content_string_y_el_content_lista_se_tratan_igual(tmp_path):
    ruta = _escribir(tmp_path / "bbbbbbbb-1111-2222-3333-444444444444.jsonl", [
        _user("u1", "en string plano"),
        _user("u2", [{"type": "text", "text": "en lista"}]),
    ])
    assert [m["texto"] for m in transcripts.esqueleto(ruta)["mensajes"]] == [
        "en string plano", "en lista",
    ]


def test_los_sidechains_de_subagentes_quedan_fuera(tmp_path):
    # Un subagente tiene su propia conversación. Mezclarla haría que el asistente
    # contase como dicho al usuario algo que sólo se dijo dentro de un agente.
    ruta = _escribir(tmp_path / "cccccccc-1111-2222-3333-444444444444.jsonl", [
        _user("u1", "principal"),
        _user("s1", "dentro del subagente", isSidechain=True),
        _assistant("s2", [{"type": "text", "text": "respuesta del subagente"}],
                   isSidechain=True),
        _assistant("a1", [{"type": "text", "text": "respuesta principal"}]),
    ])
    assert [m["texto"] for m in transcripts.esqueleto(ruta)["mensajes"]] == [
        "principal", "respuesta principal",
    ]


def test_un_jsonl_a_medio_escribir_no_revienta(tmp_path):
    # Es el caso normal: la sesión viva está escribiendo mientras el chat lee.
    ruta = tmp_path / "dddddddd-1111-2222-3333-444444444444.jsonl"
    ruta.write_text(
        json.dumps(_user("u1", "completo")) + "\n" + '{"type":"assistant","mess',
        encoding="utf-8",
    )
    assert [m["texto"] for m in transcripts.esqueleto(ruta)["mensajes"]] == ["completo"]


def test_desde_uuid_devuelve_solo_lo_posterior(sesion):
    mensajes = transcripts.esqueleto(sesion, desde_uuid="a1")["mensajes"]
    assert [m["uuid"] for m in mensajes] == ["a2"]


def test_un_desde_uuid_desconocido_devuelve_todo_en_vez_de_nada(sesion):
    # Pasa cuando la sesión se limpió o se compactó bajo los pies del chat.
    # Repintar entero es correcto; quedarse en blanco parecería que no hay nada.
    assert len(transcripts.esqueleto(sesion, desde_uuid="fantasma")["mensajes"]) == 3


# --------------------------------------------------------------------------- #
# El índice
# --------------------------------------------------------------------------- #


def test_el_indice_toma_el_titulo_que_claude_ya_escribio(sesion):
    ficha = transcripts.resumir_sesion(sesion)
    assert ficha["titulo"] == "Arreglar el respaldo"
    assert ficha["rama"] == "main"
    assert ficha["duracion_min"] == 5
    assert ficha["turnos"] == 1  # sólo el humano de verdad, no el tool_result


def test_un_archivo_sin_mensajes_utiles_no_entra_en_el_indice(tmp_path):
    ruta = _escribir(tmp_path / "eeeeeeee-1111-2222-3333-444444444444.jsonl", [
        {"type": "mode", "mode": "default"},
        {"type": "file-history-snapshot", "messageId": "x"},
    ])
    assert transcripts.resumir_sesion(ruta) is None


def test_listar_sesiones_filtra_por_fecha_antes_de_abrir_los_archivos(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", tmp_path)
    directorio = tmp_path / transcripts.slug_de("/tmp/demo")
    directorio.mkdir()
    vieja = _escribir(directorio / "11111111-1111-1111-1111-111111111111.jsonl",
                      [_user("u1", "vieja")])
    _escribir(directorio / "22222222-2222-2222-2222-222222222222.jsonl",
              [_user("u2", "nueva")])
    import os
    os.utime(vieja, (0, 0))

    proyecto = Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")
    sesiones = transcripts.listar_sesiones([proyecto], desde="2026-01-01T00:00:00Z")
    assert [s["id"] for s in sesiones] == ["22222222-2222-2222-2222-222222222222"]
    assert sesiones[0]["proyecto_id"] == "demo"


# --------------------------------------------------------------------------- #
# El zoom
# --------------------------------------------------------------------------- #


def test_el_zoom_devuelve_el_tramo_con_lo_que_el_esqueleto_descarta(sesion):
    tramo = transcripts.zoom(sesion, desde="a1", hasta="u2")
    assert [l["uuid"] for l in tramo["lineas"]] == ["a1", "u2"]
    tipos = [b["type"] for l in tramo["lineas"] for b in l["contenido"]]
    assert "thinking" in tipos and "tool_result" in tipos


def test_el_zoom_sin_limites_devuelve_la_sesion_entera(sesion):
    assert len(transcripts.zoom(sesion)["lineas"]) == 4


# --------------------------------------------------------------------------- #
# Seguridad e id de sesión
# --------------------------------------------------------------------------- #


def test_un_id_de_sesion_con_traversal_no_resuelve_a_ninguna_ruta(tmp_path):
    # El id llega por la URL. Sin validar, `../../..` sale del directorio de
    # transcripts y convierte un endpoint de lectura en lectura de disco libre.
    for veneno in ["../../etc/passwd", "..", "a/b", "id con espacios", ""]:
        assert transcripts.ruta_de_sesion(veneno, [tmp_path]) is None


def test_ruta_de_sesion_encuentra_el_archivo_por_su_id(sesion):
    hallada = transcripts.ruta_de_sesion(sesion.stem, [sesion.parent])
    assert hallada == sesion


# --------------------------------------------------------------------------- #
# Ocupación de contexto (vía B)
# --------------------------------------------------------------------------- #


def test_la_ocupacion_suma_la_entrada_del_ultimo_turno_incluida_la_cacheada(tmp_path):
    # Verificado contra el un transcript real: 363.229 tokens. La salida no
    # cuenta porque ya viene dentro de la entrada del turno siguiente.
    ruta = _escribir(tmp_path / "ffffffff-1111-2222-3333-444444444444.jsonl", [
        _assistant("a1", [{"type": "text", "text": "primero"}]),
        _assistant("a2", [{"type": "text", "text": "último"}]),
    ])
    lineas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines()]
    lineas[0]["message"]["usage"] = {"input_tokens": 1, "cache_read_input_tokens": 10,
                                    "cache_creation_input_tokens": 0, "output_tokens": 99}
    lineas[1]["message"]["usage"] = {"input_tokens": 2, "cache_read_input_tokens": 151350,
                                    "cache_creation_input_tokens": 686, "output_tokens": 664}
    _escribir(ruta, lineas)

    ocupacion = transcripts.ultima_ocupacion(ruta)
    assert ocupacion["tokens"] == 152038
    assert ocupacion["origen"] == "transcript"


def test_sin_usage_la_ocupacion_es_none_en_vez_de_cero(tmp_path):
    # Cero se leería como «la ventana está vacía», que es justo lo contrario de
    # «no lo sé». Regla dura 13: una cifra que no se puede defender no se muestra.
    ruta = _escribir(tmp_path / "99999999-1111-2222-3333-444444444444.jsonl", [
        _user("u1", "hola"),
    ])
    assert transcripts.ultima_ocupacion(ruta) is None
