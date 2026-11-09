"""Entrar en Google con el navegador en otra máquina (C-0214).

Con el hub en una máquina sin monitor, el navegador que acepta está en otra PC
y su `127.0.0.1` no es la máquina del hub: la vuelta de Google no llega nunca.
Se prueba con un servidor y una entrada de verdad —un socket y una tubería—,
porque lo que puede fallar aquí es justo la espera a dos cosas a la vez.
"""
from __future__ import annotations

import os
import socketserver
import threading
import urllib.request

from hub.secretario.agenda import google


def _servidor():
    return socketserver.TCPServer(("127.0.0.1", 0), google._Vuelta)


def test_la_direccion_pegada_trae_el_codigo_y_el_estado_sin_que_llegue_nadie():
    lectura, escritura = os.pipe()
    with _servidor() as srv, os.fdopen(lectura) as entrada:
        puerto = srv.server_address[1]
        os.write(escritura, f"http://127.0.0.1:{puerto}/?state=abc&code=4%2F0Ab&scope=x\n".encode())
        recibido = google._esperar_vuelta(srv, entrada)
    os.close(escritura)

    assert recibido["code"] == "4/0Ab" and recibido["state"] == "abc"


def test_tambien_vale_pegar_solo_lo_de_despues_del_interrogante():
    assert google._de_la_direccion("?state=s&code=c") == {"state": "s", "code": "c"}
    assert google._de_la_direccion("  /?error=access_denied \n") == {"error": "access_denied"}


def test_una_linea_sin_codigo_no_corta_la_espera_y_el_navegador_sigue_valiendo():
    lectura, escritura = os.pipe()
    with _servidor() as srv, os.fdopen(lectura) as entrada:
        puerto = srv.server_address[1]
        os.write(escritura, b"no se que pegar\n")
        hilo = threading.Thread(target=lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{puerto}/?state=e&code=del-navegador", timeout=5).read())
        hilo.start()
        recibido = google._esperar_vuelta(srv, entrada)
        hilo.join(5)
    os.close(escritura)

    assert recibido["code"] == "del-navegador"


def test_sin_teclado_se_sigue_esperando_al_navegador():
    """Una entrada cerrada (lanzado sin terminal) no puede dejarlo dando vueltas."""
    lectura, escritura = os.pipe()
    os.close(escritura)
    with _servidor() as srv, os.fdopen(lectura) as entrada:
        puerto = srv.server_address[1]
        hilo = threading.Thread(target=lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{puerto}/?error=access_denied", timeout=5).read())
        hilo.start()
        recibido = google._esperar_vuelta(srv, entrada)
        hilo.join(5)

    assert recibido == {"error": "access_denied"}


def test_varias_lineas_pegadas_de_golpe_se_leen_todas():
    """Con `readline`, la segunda se quedaba en el búfer y `select` no la veía."""
    lectura, escritura = os.pipe()
    with _servidor() as srv, os.fdopen(lectura) as entrada:
        os.write(escritura, b"no es esto\nhttp://127.0.0.1:1/?state=s&code=c\n")
        recibido = google._esperar_vuelta(srv, entrada)
    os.close(escritura)

    assert recibido["code"] == "c"


def test_sin_descriptor_de_entrada_solo_espera_al_navegador():
    with _servidor() as srv:
        puerto = srv.server_address[1]
        hilo = threading.Thread(target=lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{puerto}/?state=e&code=n", timeout=5).read())
        hilo.start()
        recibido = google._esperar_vuelta(srv, None)
        hilo.join(5)

    assert recibido["code"] == "n"
