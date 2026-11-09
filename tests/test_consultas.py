"""El orquestador le pregunta al secretario, y el secretario contesta o eleva (C-0151 fase 2, decisión 348).

Lo que se fija:

- **El reparto lo decide el código**, por el motivo: lo del dueño (plan,
  nunca, choque, producto) o sin motivo va al dueño; lo operativo, al
  secretario. Una pregunta que nombra la lista de «nunca sin el dueño» sube
  aunque el motivo diga otra cosa.
- **Lo que contesta el secretario no es el sí del dueño**: llega marcado como
  suyo, y no puede contestar una pregunta del dueño.
- **Una pregunta no se queda en un secretario parado**: a los 10 minutos, o
  en el acto si no late, sube al dueño.
- **El aviso elevado lleva su resumen, sin código ni rutas.**
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from hub import orquestador as orq
from hub.secretario import consultas, memoria, motor


def _activa(pedido="haz algo en alfa"):
    tarea_id = orq.crear(pedido)
    with orq.editar(tarea_id) as t:
        t["estado"] = orq.ACTIVA
    return tarea_id


def _timbres() -> list[str]:
    return [json.loads(r.read_text())["texto"] for r in orq.timbres_pendientes()]


@pytest.fixture
def mem():
    from hub import db
    h = db.conectar()   # el índice del hub, que `hub_orquestador` lee por `api`
    db.inicializar(h)
    h.close()
    m = memoria.conectar()
    yield m
    m.close()


@pytest.fixture
def modelo(monkeypatch):
    """Lo que «contesta» el modelo lo pone el test; se guarda lo que recibió."""
    llamado: dict = {"salida": None, "prompts": []}

    def llamar(prompt, **kw):
        llamado["prompts"].append(prompt)
        assert kw["herramientas"] is False, "el secretario contesta sin herramientas"
        if isinstance(llamado["salida"], Exception):
            raise llamado["salida"]
        return motor.Respuesta(texto="", sesion="", estructurada=llamado["salida"], segundos=0.1, coste=0.0, modelo="m")

    monkeypatch.setattr(consultas.motor, "llamar", llamar)
    return llamado


@pytest.fixture
def avisos_enviados(monkeypatch):
    enviados: list[dict] = []
    monkeypatch.setattr(consultas.avisos, "mandar", lambda texto, **kw: enviados.append({"texto": texto, **kw}) or "webpush")
    return enviados


# ── el reparto ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("motivo,texto,para", [
    ("sesion", "¿a cuál de las dos sesiones mando?", "secretario"),
    ("fallo", "los tests fallaron dos veces igual, ¿reintento con más contexto?", "secretario"),
    ("duda", "¿lo apunto en el avance o espero al final?", "secretario"),
    ("plan", "este es el plan, ¿lo ejecuto?", "dueno"),
    ("producto", "¿el botón va arriba o abajo?", "dueno"),
    (None, "¿a cuál de las dos sesiones mando?", "dueno"),
    ("duda", "¿hago push a main cuando acabe?", "dueno"),
    ("sesion", "la sesión pide un permiso para seguir", "dueno"),
    ("fallo", "¿lo despliego a producción para probar?", "dueno"),
])
def test_el_motivo_decide_a_quien_va_y_lo_del_dueno_siempre_gana(motivo, texto, para):
    assert orq.para_quien(texto, motivo) == para


def test_un_motivo_que_no_existe_se_rechaza():
    _activa()
    with pytest.raises(ValueError, match="motivo"):
        orq.preguntar("¿algo?", "porque-si")


def test_la_pregunta_al_secretario_no_toca_el_timbre_del_dueno():
    tarea_id = _activa()
    assert orq.preguntar("¿a cuál de las dos sesiones?", "sesion") == "secretario"
    t = orq.cargar(tarea_id)
    assert t["estado"] == orq.ESPERANDO_SECRETARIO and t["estado"] in orq.VIVAS
    assert _timbres() == []
    assert orq.preguntar("este es el plan", "plan") == "dueno"
    assert len(_timbres()) == 1


# ── lo que contesta el secretario ────────────────────────────────────────────

def test_el_secretario_contesta_y_el_orquestador_sabe_que_no_es_el_si_del_dueno(mem, modelo):
    tarea_id = _activa()
    orq.preguntar("¿a cuál de las dos sesiones mando?", "sesion")
    modelo["salida"] = {"decision": "contestar", "respuesta": "a la fija del Tablero"}

    assert consultas.atender(mem) == 1

    t = orq.cargar(tarea_id)
    assert t["pregunta"] is None and t["estado"] == orq.ACTIVA
    (aviso,) = t["despertar"]
    assert "El secretario contestó" in aviso and "no el sí del dueño" in aviso
    (linea,) = [b for b in orq.bitacora(tarea_id) if b["tipo"] == "respuesta"]
    assert linea["de"] == "secretario"
    assert "¿a cuál de las dos sesiones" in modelo["prompts"][0]
    assert consultas.atender(mem) == 0, "contestada, no se vuelve a mirar"


def test_el_secretario_no_puede_contestar_una_pregunta_del_dueno():
    tarea_id = _activa()
    orq.preguntar("este es el plan, ¿lo ejecuto?", "plan")
    with pytest.raises(ValueError, match="es del dueño"):
        orq.responder(tarea_id, "sí, adelante", origen="secretario", de="secretario")
    assert orq.cargar(tarea_id)["pregunta"]["para"] == "dueno"


def test_el_dueno_puede_contestar_una_que_aun_tiene_el_secretario():
    tarea_id = _activa()
    orq.preguntar("¿a cuál de las dos?", "sesion")
    orq.responder(tarea_id, "a la mía no")
    assert orq.cargar(tarea_id)["despertar"][0].startswith("El dueño contestó")


def test_el_secretario_no_confirma_proyectos_ni_cambia_niveles():
    """En el código, no en el docstring que explica por qué no. Todo el
    secretario: `confirmar` y `fijar_nivel` son sólo de la web (348)."""
    from pathlib import Path
    for archivo in Path(consultas.__file__).parent.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        nombres = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
        nombres |= {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
        assert not nombres & {"confirmar", "fijar_nivel", "_confirmar_alcance"}, archivo
    arbol = ast.parse(inspect.getsource(consultas))
    claves = {k.arg for n in ast.walk(arbol) if isinstance(n, ast.Call) for k in n.keywords}
    assert "aprobada" not in claves and "encargar_idea" not in {n.attr for n in ast.walk(arbol)
                                                               if isinstance(n, ast.Attribute)}


def test_la_respuesta_de_una_pregunta_no_se_aplica_a_la_siguiente(mem, modelo, monkeypatch):
    """Revisor: el dueño contesta mientras el modelo piensa y llega otra."""
    tarea_id = _activa()
    orq.preguntar("¿la primera?", "sesion")

    def entretanto(prompt, **kw):
        orq.responder(tarea_id, "la contesto yo")
        with orq.editar(tarea_id) as t:
            t["estado"] = orq.ACTIVA
        orq.preguntar("¿la segunda?", "sesion")
        return motor.Respuesta(texto="", sesion="", estructurada={"decision": "contestar", "respuesta": "uno"},
                               segundos=0.1, coste=0.0, modelo="m")
    monkeypatch.setattr(consultas.motor, "llamar", entretanto)
    consultas.atender(mem)
    assert orq.cargar(tarea_id)["pregunta"]["texto"] == "¿la segunda?"


def test_un_fallo_raro_del_modelo_tambien_eleva(mem, modelo, avisos_enviados):
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    modelo["salida"] = KeyError("rara")
    consultas.atender(mem)
    assert orq.cargar(tarea_id)["pregunta"]["para"] == "dueno"


# ── elevar ───────────────────────────────────────────────────────────────────

def test_si_eleva_el_aviso_lleva_su_resumen_sin_codigo_ni_rutas(mem, modelo, avisos_enviados):
    tarea_id = _activa()
    orq.preguntar("¿reintento con el otro modelo?", "fallo")
    modelo["salida"] = {"decision": "elevar",
                        "resumen": "Los tests de `test_voz.py` fallan en /home/x/hub/src/hub/voz.py y hay que elegir."}

    consultas.atender(mem)

    t = orq.cargar(tarea_id)
    assert t["estado"] == orq.ESPERANDO_DUENO and t["pregunta"]["para"] == "dueno"
    (aviso,) = avisos_enviados
    assert "fallan" in aviso["texto"] and "test_voz.py" not in aviso["texto"] and "/home" not in aviso["texto"]
    assert aviso["enlace"] == f"/orquestador?tarea={tarea_id}"
    assert "/home" not in t["pregunta"]["resumen"]
    assert [b["por"] for b in orq.bitacora(tarea_id) if b["tipo"] == "elevada"] == ["secretario"]


def test_si_el_modelo_no_contesta_se_eleva_igual(mem, modelo, avisos_enviados):
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    modelo["salida"] = motor.MotorCaido("sin red")
    consultas.atender(mem)
    assert orq.cargar(tarea_id)["pregunta"]["para"] == "dueno"
    assert len(avisos_enviados) == 1


def test_sin_canal_de_avisos_toca_el_timbre(mem, modelo, monkeypatch):
    def sin_canal(texto, **kw):
        raise consultas.avisos.SinCanal("ninguno")
    monkeypatch.setattr(consultas.avisos, "mandar", sin_canal)
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    modelo["salida"] = {"decision": "elevar", "resumen": "no sé"}
    consultas.atender(mem)
    assert any(tarea_id in t for t in _timbres())


def test_elevar_dos_veces_no_avisa_dos_veces():
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    assert orq.elevar(tarea_id, "uno") is True
    assert orq.elevar(tarea_id, "dos") is False
    assert orq.cargar(tarea_id)["pregunta"]["resumen"] == "uno"


# ── el plazo ─────────────────────────────────────────────────────────────────

def _hace(minutos: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat(timespec="seconds")


@pytest.fixture
def latido(monkeypatch):
    estado = {"vivo": True}
    monkeypatch.setattr(orq, "_secretario_vivo", lambda: estado["vivo"])
    monkeypatch.setattr(orq, "_despertar", lambda tarea_id: {})
    monkeypatch.setattr(orq, "_vigilar_quieta", lambda tarea: None)
    return estado


def test_a_los_diez_minutos_sube_sola_al_dueno(con, latido):
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    orq.bombear(con)
    assert orq.cargar(tarea_id)["pregunta"]["para"] == "secretario" and _timbres() == []

    with orq.editar(tarea_id) as t:
        t["pregunta"]["hecha"] = _hace(orq.MINUTOS_SECRETARIO + 1)
    orq.bombear(con)

    t = orq.cargar(tarea_id)
    assert t["pregunta"]["para"] == "dueno" and t["estado"] == orq.ESPERANDO_DUENO
    assert len(_timbres()) == 1
    assert [b["por"] for b in orq.bitacora(tarea_id) if b["tipo"] == "elevada"] == ["latido"]
    orq.bombear(con)
    assert len(_timbres()) == 1, "una vez elevada, no se vuelve a avisar"


def test_con_el_secretario_parado_sube_en_el_acto(con, latido):
    latido["vivo"] = False
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    orq.bombear(con)
    assert orq.cargar(tarea_id)["pregunta"]["para"] == "dueno"
    assert len(_timbres()) == 1


def test_el_secretario_que_llega_tarde_no_pisa_lo_elevado(mem, modelo):
    tarea_id = _activa()
    orq.preguntar("¿a cuál?", "sesion")
    tomada = orq.tomar_consulta(tarea_id)
    assert tomada and orq.tomar_consulta(tarea_id) is None, "dos vueltas no la miran a la vez"
    orq.elevar(tarea_id, por="latido")
    with pytest.raises(ValueError):
        orq.responder(tarea_id, "a la primera", origen="secretario", de="secretario")


def test_el_contrato_le_explica_los_motivos():
    ruta = orq.preparar() / "CLAUDE.md"
    texto = ruta.read_text(encoding="utf-8")
    for m in orq.MOTIVOS:
        assert f"`{m}`" in texto
    assert "no el sí del dueño" in texto


# ── fase 3: contestar desde el chat del secretario ───────────────────────────

def _turno_del_dueno(mem, texto, monkeypatch):
    from hub.secretario import conversacion
    t = conversacion.recibir(mem, texto)
    rid = conversacion.decir(mem, t["hilo"], "…")    # el turno que el secretario está escribiendo
    memoria.poner(mem, f"turno_en_curso:{t['hilo']}", rid)
    monkeypatch.setenv("SECRETARIO_HILO", str(t["hilo"]))


def test_desde_el_chat_se_manda_su_mensaje_tal_cual(mem, monkeypatch):
    from hub.secretario import herramientas
    tarea_id = _activa()
    orq.preguntar("este es el plan, ¿lo ejecuto?", "plan")
    _turno_del_dueno(mem, "sí, pero sin tocar la base", monkeypatch)

    r = herramientas.todas()["contestar_al_orquestador"].funcion(mem, {})

    assert r["ok"] and r["tarea"] == tarea_id
    t = orq.cargar(tarea_id)
    assert t["pregunta"] is None and t["despertar"][0].startswith("El dueño contestó")
    assert "«sí, pero sin tocar la base»" in t["despertar"][0]
    (linea,) = [b for b in orq.bitacora(tarea_id) if b["tipo"] == "respuesta"]
    assert linea["de"] == "dueno" and linea["origen"] == "chat del secretario"


def test_la_herramienta_no_acepta_texto_del_modelo():
    from hub.secretario import herramientas
    assert herramientas.todas()["contestar_al_orquestador"].esquema["properties"] == {}


def test_sin_pregunta_abierta_no_manda_nada(mem, monkeypatch):
    from hub.secretario import herramientas
    _activa()
    _turno_del_dueno(mem, "vale", monkeypatch)
    assert "error" in herramientas.todas()["contestar_al_orquestador"].funcion(mem, {})


def test_el_secretario_ve_la_pregunta_abierta(mem):
    from hub.secretario import herramientas
    _activa()
    orq.preguntar("¿a cuál?", "sesion")
    (t,) = [x for x in herramientas.todas()["hub_orquestador"].funcion(mem, {}) if x.get("pregunta")]
    assert t["pregunta"]["para"] == "secretario"


def test_con_semanas_de_tareas_el_secretario_ve_la_viva_y_las_ultimas(mem):
    """C-0073: leía `orquestador.listar()[:20]`, que va de la más vieja a la más
    nueva: con más de veinte tareas, la que estaba en marcha no salía."""
    from hub.secretario import herramientas
    viejas = [orq.crear(f"tarea vieja {i}") for i in range(22)]
    for tarea_id in viejas:
        with orq.editar(tarea_id) as t:
            t["estado"] = orq.TERMINADA
    viva = _activa("la de ahora")
    orq.preguntar("¿a cuál?", "sesion")

    vistas = herramientas.todas()["hub_orquestador"].funcion(mem, {})

    assert len(vistas) == 20
    assert vistas[0]["id"] == viva and vistas[0]["pregunta"]["para"] == "secretario"
    assert vistas[1]["id"] == viejas[-1], "las cerradas, de la más reciente hacia atrás"


def test_un_mensaje_anterior_no_contesta_una_pregunta_posterior(mem, monkeypatch):
    """Revisor: un «sí» a otra cosa no puede pasar a aprobar un plan que llegó
    después de escribirlo."""
    from hub.secretario import herramientas
    tarea_id = _activa()
    _turno_del_dueno(mem, "sí", monkeypatch)
    mem.execute("UPDATE turno SET creado = '2000-01-01T00:00:00+00:00' WHERE rol = 'dueno'")
    orq.preguntar("este es el plan, ¿lo ejecuto?", "plan")
    r = herramientas.todas()["contestar_al_orquestador"].funcion(mem, {})
    assert "después de su mensaje" in r["error"]
    assert orq.cargar(tarea_id)["pregunta"]["texto"].startswith("este es el plan")


def test_los_nombres_que_no_salen_se_tapan_si_la_lista_esta():
    """La red de nombres propios: aquí `publicacion` existe y su lista se usa.
    El nombre sale de la propia lista: escrito aquí, este archivo —que viaja—
    no pasaría su lint."""
    import re as _re

    pytest.importorskip("hub.publicacion", reason="en el producto no viaja: no hay lista")
    nombre = next(p for p in consultas._nombres_propios() if _re.escape(p) == p)
    assert nombre not in consultas._limpio(f"Lo pidió {nombre} ayer")


def test_en_una_instalacion_sin_publicacion_el_aviso_sale_igual(monkeypatch):
    """🔴 C-0221: `publicacion` no viaja con el producto, y su `import` dejaba al
    secretario sin arrancar. Sin la lista, se limpian código y rutas igual."""
    import importlib as _importlib

    real = _importlib.import_module

    def sin_publicacion(nombre, *a, **k):
        if nombre == "hub.publicacion":
            raise ModuleNotFoundError("No module named 'hub.publicacion'", name="hub.publicacion")
        return real(nombre, *a, **k)

    monkeypatch.setattr(consultas.importlib, "import_module", sin_publicacion)
    assert consultas._nombres_propios() == ()
    assert consultas._limpio("Falla `x.py` en /srv/hub/app y hay que elegir") == "Falla … en … y hay que elegir"
