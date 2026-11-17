"""La lectura `capacidades` del secretario: lo ya indexado, por la puerta de /inventario (C-0251)."""

import pytest

from hub import db, registry
from hub.models import Proyecto
from hub.secretario import archivos, conversacion, herramientas, memoria


@pytest.fixture
def indice(tmp_path, monkeypatch):
    raiz = tmp_path / "ws"
    proyectos = [Proyecto(id="ws", nombre="Ws", asiento=str(raiz)), Proyecto(id="otro", nombre="Otro")]
    monkeypatch.setattr(registry, "cargar", lambda *a, **k: proyectos)
    monkeypatch.setattr(archivos, "raices", lambda: {"ws": raiz})
    h = db.conectar()
    db.inicializar(h)
    for pid, status in (("ws", "activo"), ("otro", "activo"), ("viejo", "archivado")):
        h.execute("INSERT INTO proyecto (id,nombre,dominio,tipo,status) VALUES (?,?,'personal','proyecto',?)",
                  (pid, pid, status))

    def cap(pid, tipo, nombre, ruta, desc, usado=None):
        h.execute("INSERT INTO capacidad (proyecto_id,tipo,nombre,ruta,descripcion,usado) VALUES (?,?,?,?,?,?)",
                  (pid, tipo, nombre, ruta, desc, usado))
    cap("ws", "skill", "trace", str(raiz / ".claude/skills/trace/SKILL.md"), "Destila procedimientos " + "x" * 400,
        "2026-11-10T12:00:00+00:00")
    cap("ws", "agente", "revisor", str(raiz / ".claude/agents/revisor.md"), "Revisa cambios")
    cap("otro", "skill", "deploy", "/otro/lugar/SKILL.md", "Publica la web")
    cap("viejo", "skill", "fosil", "/viejo/SKILL.md", "De un proyecto archivado")
    h.commit()
    h.close()
    con = memoria.conectar()
    yield con
    con.close()


def test_devuelve_lo_indexado_con_ruta_relativa_y_ultimo_uso(indice):
    r = herramientas.todas()["capacidades"].funcion(indice, {})

    por_nombre = {c["nombre"]: c for c in r["capacidades"]}
    assert set(por_nombre) == {"trace", "revisor", "deploy"}, "lo archivado no sale"
    assert por_nombre["trace"]["ruta"] == ".claude/skills/trace/SKILL.md"
    assert por_nombre["trace"]["tipo"] == "skill" and por_nombre["trace"]["ultimo_uso"]
    assert por_nombre["revisor"]["ultimo_uso"] is None


def test_filtra_por_proyecto_y_por_texto(indice):
    f = herramientas.todas()["capacidades"].funcion

    assert {c["nombre"] for c in f(indice, {"proyecto": "ws"})["capacidades"]} == {"trace", "revisor"}
    assert [c["nombre"] for c in f(indice, {"texto": "PUBLICA"})["capacidades"]] == ["deploy"]
    assert [c["nombre"] for c in f(indice, {"proyecto": "ws", "texto": "revis"})["capacidades"]] == ["revisor"]
    assert "error" in f(indice, {"proyecto": "no-existe"})


def test_acota_la_descripcion_y_la_cantidad(indice):
    h = db.conectar()
    for i in range(herramientas.CAPACIDADES_MAXIMO + 5):
        h.execute("INSERT INTO capacidad (proyecto_id,tipo,nombre,ruta) VALUES ('otro','skill',?,?)",
                  (f"s{i}", f"/otro/{i}"))
    h.commit()
    h.close()

    r = herramientas.todas()["capacidades"].funcion(indice, {})

    assert r["mostradas"] == herramientas.CAPACIDADES_MAXIMO and r["total"] > r["mostradas"]
    assert "acota" in r["nota"]
    trace = herramientas.todas()["capacidades"].funcion(indice, {"texto": "trace"})["capacidades"][0]
    assert len(trace["descripcion"]) <= herramientas.CAPACIDAD_DESCRIPCION


def test_el_sistema_manda_mirar_las_capacidades_antes_de_explicar_un_flujo():
    assert "`capacidades`" in conversacion.SISTEMA and "no lo inventes" in conversacion.SISTEMA
