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


@pytest.mark.parametrize("origen,host,pasa", [
    ("http://127.0.0.1:8787", "127.0.0.1:8787", True),
    ("http://localhost:8899", "localhost:8899", True),      # el hub en otro puerto
    ("http://localhost", "localhost", True),
    ("http://[::1]:8787", "[::1]:8787", True),
    ("http://127.0.0.1:5173", "127.0.0.1:8787", False),     # otra web de casa
    ("http://localhost:8000", "127.0.0.1:8787", False),     # la app de un encargo
    ("http://127.0.0.1", "127.0.0.1:8787", False),
    ("http://127.0.0.1:8787", "hub.ejemplo.ts.net", False),  # casa pidiendo a la red privada
])
def test_desde_casa_el_origen_lleva_el_puerto_del_hub(origen, host, pasa):
    """C-0153: una página de otro puerto de 127.0.0.1 no es el hub, y desde casa
    la terminal no pide nada más. El puerto se compara con el `Host` de la
    petición, no con el configurado (por eso el hub en otro puerto sigue)."""
    assert web.acceso.origen_permitido(origen, host) is pasa


def test_la_puerta_y_el_websocket_pasan_el_host_de_la_peticion(monkeypatch):
    """Sin el `Host`, la comparación de puerto no se haría (C-0153)."""
    vistos: list = []
    monkeypatch.setattr(web, "_hosts_de_prueba", lambda: ())
    monkeypatch.setattr(web.acceso, "origen_permitido", lambda o, h=None: vistos.append((o, h)) or False)
    cliente = TestClient(web.app, base_url="http://127.0.0.1:8787")
    cliente.post("/tablero/idea", data={"texto": "x"}, headers={"origin": "http://127.0.0.1:5173"})
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        # El arnés de websockets no toma el nombre de `base_url`: se dice.
        with cliente.websocket_connect("/ws/terminal/x", headers={"origin": "http://127.0.0.1:5173",
                                                                   "host": "127.0.0.1:8787"}):
            pass
    assert vistos == [("http://127.0.0.1:5173", "127.0.0.1:8787")] * 2


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


# ── C-0104: todas las rutas, no una ──────────────────────────────────────────

def _rellenar(ruta: str) -> str:
    """Una URL concreta para una plantilla de ruta: `{x}` → `x1`, `{x:path}` → `a/b`."""
    import re
    return re.sub(r"\{(\w+)(:path)?\}", lambda m: "a/b" if m.group(2) else f"{m.group(1)}1", ruta)


def _mutantes():
    from starlette.routing import Route
    return sorted({(m, r.path) for r in web.app.routes if isinstance(r, Route)
                   for m in (r.methods or ()) if m in web.MUTAN})


def _websockets():
    from starlette.routing import WebSocketRoute
    return sorted(r.path for r in web.app.routes if isinstance(r, WebSocketRoute))


def test_el_recorrido_encuentra_las_rutas():
    """Si `app.routes` cambiara de forma (routers, montajes), los dos de abajo
    pasarían sin probar nada. Esto los ata a algo que se cuenta."""
    assert len(_mutantes()) > 50 and "/api/agente/lanzar" in {p for _, p in _mutantes()}
    assert any(p.startswith("/ws/terminal") for p in _websockets())


@pytest.mark.parametrize("metodo,ruta", _mutantes())
def test_ninguna_ruta_que_muta_atiende_a_una_web_ajena(cliente, metodo, ruta):
    """Recorre `app.routes` entero (C-0104). Antes se probaba sólo
    `/api/agente/lanzar`: una ruta que se mueva a otro router al partir
    `web.py` podría quedar fuera de la puerta y nada lo diría."""
    r = cliente.request(metodo, _rellenar(ruta), headers={"Origin": AJENOS[0], "Content-Type": "text/plain"},
                        content="{}")
    assert r.status_code == 403 and "otro sitio web" in r.text, f"{metodo} {ruta} → {r.status_code}"


@pytest.mark.parametrize("ruta", _websockets())
def test_ningun_websocket_acepta_a_una_web_ajena(cliente, ruta):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with cliente.websocket_connect(_rellenar(ruta), headers={"Origin": AJENOS[0]}) as ws:
            ws.receive_bytes()
    assert exc.value.code == 1008, f"{ruta} cerró con {exc.value.code}, no por política"
