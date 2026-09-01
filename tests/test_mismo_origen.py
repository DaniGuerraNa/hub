"""El hub sólo atiende a quien viene de él mismo.

🔴 El defecto que esto cierra, medido en una instalación limpia: cualquier
página abierta en el navegador del usuario podía conectarse a
`ws://127.0.0.1:8787/ws/terminal/<sesión>`, **recibir el contenido del PTY** —244
bytes en la prueba— y escribir en él. Es una shell entregada por visitar una web.

Escuchar sólo en `127.0.0.1` protege de la red, no del navegador: el navegador
de la víctima ya está dentro. Y los navegadores permiten abrir WebSockets entre
orígenes sin la restricción de lectura que sí aplican a `fetch`.

La defensa se apoya en una asimetría que conviene tener escrita: `Origin` se
falsifica trivialmente desde `curl`, pero **no desde el JavaScript de una
página** — lo pone el navegador y es una cabecera prohibida. Como el vector es
el navegador, comprobarla lo cierra entero. Que `curl` se la salte no es un
hueco: quien puede ejecutar `curl` aquí ya puede ejecutar `bash`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub import web


AJENOS = [
    "https://sitio-malicioso.example",
    "http://evil.test",
    "null",
    "https://127.0.0.1.malicioso.example",  # el truco del sufijo
    "http://localhost.attacker.tld",
]
PROPIOS = [
    "http://127.0.0.1:8787",
    "http://localhost:8787",
    "http://127.0.0.1:8899",  # otro puerto: sigue siendo el hub
    "http://localhost",
]


@pytest.fixture
def cliente():
    return TestClient(web.app)


@pytest.mark.parametrize("origen", AJENOS)
def test_una_web_ajena_no_abre_la_terminal(origen):
    assert not web.origen_permitido(origen)


@pytest.mark.parametrize("origen", PROPIOS)
def test_el_hub_se_abre_a_si_mismo(origen):
    """Incluido en otro puerto.

    La primera versión ataba la lista a `config.WEB_PORT` y rechazaba al origen
    legítimo en cuanto uvicorn arrancaba en otro puerto — que es justo lo que
    imprime el instalador con `--sin-servicios`. Se quedaba sin terminal y sin
    decir por qué.
    """
    assert web.origen_permitido(origen)


def test_sin_origen_se_deja_pasar():
    """`curl` y el `bin/hub` del asistente no mandan `Origin`, y deben seguir."""
    assert web.origen_permitido(None)


@pytest.mark.parametrize("origen", AJENOS)
def test_una_web_ajena_no_puede_lanzar_un_agente(cliente, origen):
    """`/api/agente/lanzar` corre `claude` con un prompt: es ejecución remota.

    El cuerpo va como `text/plain` a propósito: es una petición «simple», la que
    NO dispara preflight y por tanto la que un atacante usaría de verdad.
    """
    r = cliente.post(
        "/api/agente/lanzar",
        headers={"Origin": origen, "Content-Type": "text/plain"},
        content='{"proyecto_id":"x","prompt":"y"}',
    )
    assert r.status_code == 403
    assert "otro sitio web" in r.text


def test_las_lecturas_no_se_bloquean(cliente):
    """Sólo se filtra lo que MUTA. Un GET no cambia nada y romperlo sería ruido."""
    assert cliente.get("/api/paneles", headers={"Origin": AJENOS[0]}).status_code == 200


def test_un_host_forjado_se_rechaza(cliente):
    """DNS-rebinding: sin esto, un dominio del atacante resuelve a 127.0.0.1 y
    el navegador trata al hub como mismo origen, pudiendo además LEER."""
    r = cliente.get("/api/paneles", headers={"Host": "banco-malicioso.example"})
    assert r.status_code == 400


def test_el_websocket_rechaza_antes_de_aceptar(cliente):
    """No basta con cerrar después: aceptar ya abre el espejo del PTY."""
    with pytest.raises(Exception):  # noqa: B017 — el cliente levanta al ver el 403
        with cliente.websocket_connect(
            "/ws/terminal/loquesea", headers={"Origin": AJENOS[0]}
        ):
            pass
