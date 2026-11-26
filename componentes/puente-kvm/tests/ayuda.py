"""Lo que comparten las pruebas que recorren el puente contra el Mac simulado."""

from __future__ import annotations

import contextlib
import time

from fastapi.testclient import TestClient

from puente_kvm import config, muestras
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

PERSONA = {"Origin": "http://testserver"}


@contextlib.contextmanager
def puente_simulado(lineas: int = 160, retardo_ms: int = 2):
    """Un puente con el Mac simulado delante, como lo arranca el servicio."""
    config.guardar_ajustes({**config.AJUSTES_POR_OMISION,
                            "perfil": {**config.PERFIL_POR_OMISION, "retardo_tecla_ms": retardo_ms}})
    sim = Simulador(lineas=muestras.procedimiento(lineas))
    with TestClient(crear_app(sim, hosts={"testserver"})) as c:
        yield c, sim


def esperar(c: TestClient, tope: float = 60) -> None:
    fin = time.time() + tope
    time.sleep(0.1)
    while c.get("/api/estado").json()["tarea"]:
        assert time.time() < fin, "la tarea no termina"
        time.sleep(0.1)


def transcribir_como_oraculo(c: TestClient, sim: Simulador, lectura: str, estropear: int | None = None):
    """Transcribe cada página con el texto real que mostraba (lo que haría un lector perfecto)."""
    r = c.get(f"/api/lecturas/{lectura}").json()
    lineas = sim.editor.guardado
    filas = sim.editor.filas
    for k in range(1, r["paginas"] + 1):
        arriba = min((k - 1) * filas, max(0, len(lineas) - filas))
        trozo = []
        for i in range(arriba, min(arriba + filas, len(lineas))):
            texto = lineas[i]
            if estropear == i + 1:
                texto = texto.replace("0", "O", 1) if "0" in texto else texto + "x"
            trozo.append(f"{i + 1}|{texto}")
        res = c.post(f"/api/lecturas/{lectura}/paginas/{k}", json={"texto": "\n".join(trozo)})
        assert res.status_code == 200, res.text


def leer(c: TestClient) -> str:
    assert c.post("/api/control", json={"accion": "dar"}, headers=PERSONA).status_code == 200
    r = c.post("/api/lecturas", json={"nombre": "usp_ConciliarMovimientos"})
    assert r.status_code == 200, r.text
    esperar(c)
    return r.json()["id"]


def leida_y_verificada(c: TestClient, sim: Simulador) -> str:
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    h = c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert h["verificada"]
    return lid


def proponer_y_aprobar(c: TestClient, lectura: str, nuevo: list[str], descripcion: str = "prueba") -> str:
    r = c.post("/api/cambios", json={"lectura": lectura, "texto": "\n".join(nuevo), "descripcion": descripcion})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA).status_code == 200
    return cid


def mcp_contra(c: TestClient, monkeypatch) -> None:
    """Las herramientas de Claude (`mcp_servidor`) hablando con este puente de prueba, por su API."""
    import io

    from PIL import Image

    from puente_kvm import mcp_servidor

    def respuesta(r):
        if r.status_code >= 400:
            raise mcp_servidor.ErrorPuente(str(r.json().get("detail")), estado=r.status_code)
        return r

    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        return respuesta(c.request(metodo, ruta, json=cuerpo)).json()

    async def bajar(ruta):
        return Image.open(io.BytesIO(respuesta(c.get(ruta)).content)).convert("RGB")

    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    # La medición de cada herramienta (C-0483), en el acto: suelta, en una
    # prueba la cancelaría el final de `asyncio.run` antes de salir.
    monkeypatch.setattr(mcp_servidor, "_enviar", lambda cuerpo: c.post("/api/mediciones/herramienta", json=cuerpo))


# ── el teclado del Mac (C-0481) ─────────────────────────────────────────────
def pulsar_en(sim: Simulador, pulsaciones) -> None:
    """Los informes que mandaría el puente, directos al Mac simulado. En un hilo
    aparte: las pruebas de navegador ya tienen un bucle de asyncio en éste."""
    import asyncio
    import threading

    async def correr():
        for p in pulsaciones:
            await sim.informe_teclado(p.modificadores, [p.tecla])
            await sim.informe_teclado(0, [])

    hilo = threading.Thread(target=lambda: asyncio.run(correr()))
    hilo.start()
    hilo.join()


def vaciar(sim: Simulador) -> None:
    """Una pestaña de script nueva y vacía."""
    sim.editor.lineas, sim.editor.cursor, sim.editor.ancla = [""], (0, 0), None


def ejecutar_como_sql_server(lineas: list[str]) -> dict[int, dict]:
    """Lo que devolvería SQL Server al ejecutar la consulta de prueba tal como quedó
    tecleada en el editor: con lo que de verdad salió, no con lo que se quería."""
    import hashlib
    import re

    texto = "\n".join(lineas)
    assert texto.startswith("SELECT n, LEN(t)") and "HASHBYTES('SHA2_256', t)" in texto, texto[:200]
    salida = {}
    for n, literal in re.findall(r"\((\d+), N'((?:[^']|'')*)'\)", texto):
        t = literal.replace("''", "'")
        salida[int(n)] = {"largo": len(t), "huella": hashlib.sha256(t.encode("utf-16-le")).hexdigest()[:16].upper()}
    return salida


def rejilla(filas: dict[int, dict]) -> str:
    """Las filas como las copiaría Claude de la rejilla de resultados."""
    return "\n".join(f"{n} | {f['largo']} | {f['huella']}" for n, f in sorted(filas.items()))


def medida_verificada(fuente="mac-es", nombre: str = "Latinoamericano", reservadas=("alt+x",)) -> dict:
    """Una medida hecha de punta a punta contra un Mac simulado con `fuente`, sin la API."""
    from puente_kvm import hid, teclados

    sim = Simulador(lineas=[""], fuente=fuente)
    pulsar_en(sim, teclados.sondeo(reservadas))
    b = teclados.guardar(teclados.construir(sim.editor.lineas, nombre))
    for _ in range(5):
        try:
            consulta, ronda = teclados.consulta(b, reservadas=reservadas)
        except ValueError:
            break
        vaciar(sim)
        pulsar_en(sim, hid.secuencia(consulta, teclados.distribucion_del_borrador(b), reservadas))
        teclados.empezar_ronda(b, ronda)
        teclados.comprobar(b, ejecutar_como_sql_server(sim.editor.lineas))
        teclados.guardar(b)
    assert teclados.resumen(b)["elegible"], teclados.resumen(b)
    return b
