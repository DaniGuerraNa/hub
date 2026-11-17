"""El registro propio de `hub-web` (C-0245): sólo lo que importa, nunca el ruido.

Se ejecuta el middleware ASGI de verdad, con una app mínima detrás: lo que se
prueba es qué sale al registro, no un doble.
"""

from __future__ import annotations

import asyncio

import pytest

from hub import web


def _correr(app_interna, ruta="/x", consulta=b"", metodo="GET", tipo="http"):
    mensajes = []

    async def enviar(m):
        mensajes.append(m)

    async def recibir():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": tipo, "method": metodo, "path": ruta, "query_string": consulta}
    mw = web._RegistroDeAcceso(app_interna)
    asyncio.run(mw(scope, recibir, enviar))
    return mensajes


def _app(estado, retraso=0.0, trozos=1):
    async def app(scope, recibir, enviar):
        if retraso:
            await asyncio.sleep(retraso)
        await enviar({"type": "http.response.start", "status": estado, "headers": []})
        for i in range(trozos):
            await enviar({"type": "http.response.body", "body": b"x", "more_body": i < trozos - 1})
    return app


def test_una_peticion_rapida_y_buena_no_escribe_nada(capsys):
    _correr(_app(200))
    _correr(_app(304))
    assert capsys.readouterr().out == ""


def test_un_error_se_apunta_con_metodo_ruta_estado_y_milisegundos(capsys):
    _correr(_app(500), ruta="/api/algo", metodo="POST")
    salida = capsys.readouterr().out
    assert salida.count("\n") == 1
    assert "POST /api/algo -> 500 en " in salida and " ms" in salida


def test_una_peticion_lenta_se_apunta_aunque_sea_un_200(capsys, monkeypatch):
    monkeypatch.setattr(web, "UMBRAL_LENTA_S", 0.05)
    _correr(_app(200, retraso=0.1), ruta="/lenta")
    assert "GET /lenta -> 200" in capsys.readouterr().out


def test_la_linea_no_lleva_la_cadena_de_consulta(capsys):
    _correr(_app(404), ruta="/buscar", consulta=b"q=secreto&token=abc")
    salida = capsys.readouterr().out
    assert "/buscar" in salida and "secreto" not in salida and "token" not in salida


def test_una_excepcion_se_apunta_como_500_y_se_vuelve_a_lanzar(capsys):
    async def rota(scope, recibir, enviar):
        raise RuntimeError("se rompió")

    with pytest.raises(RuntimeError):
        _correr(rota, ruta="/boom")
    salida = capsys.readouterr().out
    assert "GET /boom -> 500" in salida and "RuntimeError" in salida
    assert salida.count("\n") == 1


def test_una_excepcion_tras_arrancar_la_respuesta_no_se_apunta_dos_veces(capsys):
    async def a_medias(scope, recibir, enviar):
        await enviar({"type": "http.response.start", "status": 500, "headers": []})
        raise RuntimeError("a medias")

    with pytest.raises(RuntimeError):
        _correr(a_medias)
    assert capsys.readouterr().out.count("\n") == 1


def test_las_respuestas_en_streaming_pasan_trozo_a_trozo_sin_retenerse():
    mensajes = _correr(_app(200, trozos=3))
    assert [m["type"] for m in mensajes] == ["http.response.start"] + ["http.response.body"] * 3


def test_un_websocket_pasa_sin_tocarse(capsys):
    llamado = []

    async def ws(scope, recibir, enviar):
        llamado.append(scope["type"])

    _correr(ws, tipo="websocket")
    assert llamado == ["websocket"] and capsys.readouterr().out == ""


def test_la_aplicacion_real_lleva_el_registro_y_la_plantilla_apaga_el_de_uvicorn():
    from pathlib import Path
    assert any(m.cls is web._RegistroDeAcceso for m in web.app.user_middleware)
    plantilla = (Path(web.__file__).parents[2] / "scripts" / "hub-web.service.plantilla").read_text()
    assert "--no-access-log" in plantilla


def test_una_peticion_que_corta_el_navegador_no_se_apunta_como_error(capsys):
    async def app(scope, recibir, enviar):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _correr(app)
    assert capsys.readouterr().out == ""
