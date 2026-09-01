"""El registro aguanta que dos cosas escriban a la vez.

`projects.yml` es la fuente de verdad (decisión 7) y hasta la auditoría del 1 de
septiembre se reescribía con un `write_text` pelado: leer el archivo entero,
añadirle un bloque y volcarlo, sin cerrojo entre lo uno y lo otro.

Lo que se midió, y lo que estos tests impiden que vuelva:

- Con 8 altas simultáneas el archivo acabó **ilegible** — una línea `l` suelta,
  resto de «personal» cortado a medias.
- Con un escritor y un lector, **2838 de 3635 lecturas vieron CERO proyectos**.
  Eso no es cosmético: una lectura vacía dispara los `DELETE FROM` de respaldo,
  inventario y conexiones, que se quedan sin nada que reinsertar.

Y no hace falta que haya dos personas usando el hub: el snapshotter lee este
archivo cada 20 s mientras la web lo reescribe.
"""

from __future__ import annotations

import threading
import time

import pytest
import yaml

from hub import registry


SEMILLA = "proyectos:\n" + "".join(
    f"  - id: pre{i}\n    nombre: P{i}\n    dominio: personal\n    asiento: /tmp/p{i}\n"
    for i in range(10)
)


@pytest.fixture
def registro(tmp_path, monkeypatch):
    ruta = tmp_path / "projects.yml"
    ruta.write_text(SEMILLA, encoding="utf-8")
    monkeypatch.setenv("HUB_PROJECTS_YML", str(ruta))
    monkeypatch.setattr(registry.config, "projects_yml", lambda: ruta)
    return ruta


def test_ocho_altas_a_la_vez_no_pierden_ninguna_ni_rompen_el_archivo(registro):
    """El caso exacto que dejó el registro ilegible."""
    n = 8
    barrera = threading.Barrier(n)
    resultado: dict[int, str] = {}

    def alta(i: int) -> None:
        barrera.wait()
        try:
            registry.añadir_proyecto(
                {"id": f"n{i}", "nombre": f"N{i}", "dominio": "personal",
                 "ruta": f"/tmp/n{i}"}
            )
            resultado[i] = "ok"
        except Exception as exc:  # noqa: BLE001 — cualquier fallo es un fallo
            resultado[i] = type(exc).__name__

    hilos = [threading.Thread(target=alta, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert set(resultado.values()) == {"ok"}, resultado
    # Se lee: si el archivo quedó a medias, esto levanta ScannerError.
    ids = [p.id for p in registry.cargar()]
    # Nada de lo que ya estaba se perdió...
    assert sum(1 for x in ids if x.startswith("pre")) == 10
    # ...y todas las altas están, no sólo la última que escribió.
    assert sorted(x for x in ids if x.startswith("n")) == [f"n{i}" for i in range(n)]


def test_un_alta_duplicada_la_rechaza_una_sola_vez(registro):
    """La guarda de duplicados era un TOCTOU: las dos decían que sí.

    Con el cerrojo, exactamente una gana y la otra se entera.
    """
    barrera = threading.Barrier(2)
    resultado: dict[int, str] = {}

    def alta(i: int) -> None:
        barrera.wait()
        try:
            registry.añadir_proyecto(
                {"id": "gemelo", "nombre": f"G{i}", "dominio": "personal",
                 "ruta": "/tmp/gemelo"}
            )
            resultado[i] = "ok"
        except Exception:  # noqa: BLE001
            resultado[i] = "rechazada"

    hilos = [threading.Thread(target=alta, args=(i,)) for i in (0, 1)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert sorted(resultado.values()) == ["ok", "rechazada"], resultado
    assert [p.id for p in registry.cargar()].count("gemelo") == 1


def test_quien_lee_mientras_se_escribe_nunca_ve_el_archivo_a_medias(tmp_path):
    """La mitad del defecto que no era de concurrencia entre escritores.

    `write_text` trunca y luego escribe. Ese hueco es lo que veía el
    snapshotter. `os.replace` no lo tiene: se ve la versión vieja entera o la
    nueva entera.
    """
    ruta = tmp_path / "projects.yml"
    ruta.write_text(SEMILLA, encoding="utf-8")
    parar = threading.Event()
    vistas: list[int | str] = []

    def escritor() -> None:
        while not parar.is_set():
            registry._escribir_atomico(ruta, SEMILLA)

    def lector() -> None:
        while not parar.is_set():
            try:
                datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                vistas.append("ilegible")
                continue
            vistas.append(len(datos.get("proyectos") or []))

    hilos = [threading.Thread(target=escritor), threading.Thread(target=lector)]
    for h in hilos:
        h.start()
    time.sleep(0.4)
    parar.set()
    for h in hilos:
        h.join()

    assert vistas, "el lector no llegó a leer nada: la prueba no probó nada"
    assert set(vistas) == {10}, f"vio el archivo a medias: {set(vistas)}"


def test_no_deja_temporales_tirados(tmp_path):
    """Un `.tmp` huérfano en HUB_HOME es basura que nadie va a limpiar."""
    # Subcarpeta propia: `tmp_path` la comparten los fixtures autouse, y mirar
    # ahí medía la basura de otros en vez de la de esta función.
    casa = tmp_path / "registro"
    casa.mkdir()
    ruta = casa / "projects.yml"
    for _ in range(5):
        registry._escribir_atomico(ruta, SEMILLA)
    assert [p.name for p in casa.iterdir()] == ["projects.yml"]
