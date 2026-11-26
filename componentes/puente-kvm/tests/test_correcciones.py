"""Correcciones pequeñas sin una aprobación por cada una (C-0489, decisión 458 del hub).

La persona lo pidió así: si ya revisó con Claude una corrección de la
documentación, mandar diez aprobaciones de una línea no aporta nada. Al dar el
control puede marcar una casilla, y mientras dure esa concesión lo que conserva
parte del documento y cabe en un presupuesto que suma todos los cambios
(20 líneas y 1 500 caracteres) queda aprobado solo. Lo demás —un documento
nuevo, uno reescrito entero, lo que se pase— sigue esperando su sí, y partir un
cambio grande en pequeños no sirve porque el presupuesto es de la concesión.
"""

import asyncio
import json
import time

import pytest

from puente_kvm import cambios
from puente_kvm.control import INACTIVIDAD_S, TOPE_LINEAS, Control, Permiso

from .ayuda import PERSONA, esperar, puente_simulado, transcribir_como_oraculo


@pytest.fixture
def entorno():
    with puente_simulado() as (c, sim):
        yield c, sim


def dar(c, correcciones: bool = False) -> dict:
    cuerpo = {"accion": "dar", **({"correcciones": True} if correcciones else {})}
    r = c.post("/api/control", json=cuerpo, headers=PERSONA)
    assert r.status_code == 200, r.text
    return r.json()


def leer_con_el_control_dado(c, sim, verificar: bool = True) -> str:
    """Leer sin volver a dar el control (`ayuda.leer` lo da sin la casilla).

    Como con los hooks de Claude Code y su encargo en curso: sin ellos, acabar la
    lectura devolvería el Mac (C-0486), y con él se acabaría el permiso."""
    p = c.app.state.puente
    p.turno_en_curso = lambda: True
    try:
        r = c.post("/api/lecturas", json={"nombre": "usp_ConciliarMovimientos"})
        assert r.status_code == 200, r.text
        esperar(c)
    finally:
        del p.turno_en_curso
    assert c.get("/api/estado").json()["control"]["modo"] == "claude"
    lid = r.json()["id"]
    transcribir_como_oraculo(c, sim, lid)
    if verificar:
        h = c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
        assert h["verificada"]
    return lid


def proponer(c, lid: str, nuevo: list[str], descripcion: str = "corrección") -> dict:
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": descripcion})
    assert r.status_code == 200, r.text
    return r.json()


def con_una_linea(sim, i: int, texto: str = " -- corregido") -> list[str]:
    nuevo = list(sim.editor.guardado)
    nuevo[i] += texto
    return nuevo


def bitacora(c, tipo: str) -> list[dict]:
    return [e for e in c.get("/api/bitacora").json() if e["tipo"] == tipo]


# ── la puerta: sólo la persona, sólo con la casilla ─────────────────────────
def test_sin_origin_de_la_pantalla_no_se_concede_el_permiso(entorno):
    c, _ = entorno
    assert c.post("/api/control", json={"accion": "dar", "correcciones": True}).status_code == 403
    assert c.post("/api/control", json={"accion": "dar", "correcciones": True},
                  headers={"Origin": "http://otra.web"}).status_code == 403
    assert "correcciones" not in c.get("/api/estado").json()["control"]
    # Un «true» como texto no es la casilla marcada.
    assert "correcciones" not in c.post("/api/control", json={"accion": "dar", "correcciones": "true"},
                                        headers=PERSONA).json()


def test_dar_con_la_casilla_lo_dice_el_estado_y_la_bitacora(entorno):
    c, _ = entorno
    e = dar(c, correcciones=True)
    assert e["correcciones"] == {"lineas": 0, "caracteres": 0, "tope_lineas": 20, "tope_caracteres": 1500}
    assert "con correcciones pequeñas sin pedirle aprobación" in bitacora(c, "control")[-1]["detalle"]


def test_la_casilla_de_la_pantalla_dice_los_topes_de_control_py(entorno):
    """El texto de la casilla los saca del botón, no de cifras escritas en app.js:
    cambiar el tope en `control.py` no puede dejar la casilla prometiendo otro."""
    import re
    from pathlib import Path

    from puente_kvm import control

    c, _ = entorno
    boton = re.search(r'<button[^>]*id="boton-dar"[^>]*>', c.get("/panel").text).group(0)
    assert f'data-tope-lineas="{control.TOPE_LINEAS}"' in boton
    assert f'data-tope-caracteres="{control.TOPE_CARACTERES}"' in boton
    js = (Path(control.__file__).parent / "static" / "app.js").read_text()
    casilla = js[js.index("casilla: 'Correcciones pequeñas"):][:300]
    assert "d.topeLineas" in casilla and "d.topeCaracteres" in casilla
    assert not re.search(r"\b(20|1 ?500)\b", casilla)


# ── con el permiso ──────────────────────────────────────────────────────────
def test_una_correccion_pequena_con_permiso_queda_aprobada_y_se_escribe_sin_clic(entorno):
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    nuevo = con_una_linea(sim, 20)
    r = proponer(c, lid, nuevo)
    assert r["estado"] == "aprobado" and r["aprobado_por"] == "correcciones" and r["cabe"] is None
    assert r["lineas"] == 2 and r["caracteres"] == 2 * len(sim.editor.guardado[20]) + len(" -- corregido")
    assert "Aprobado por su permiso" in r["aviso"]
    linea = bitacora(c, "aprobacion")[-1]
    assert linea["quien"] == "puente" and linea["cambio"] == r["id"]
    assert linea["detalle"].endswith("aprobado por tu permiso de correcciones pequeñas (2 líneas, "
                                     f"{r['caracteres']} caracteres)")
    assert c.get("/api/estado").json()["control"]["correcciones"]["lineas"] == 2
    pagina = c.get(f"/cambios/{r['id']}").text
    assert "aprobado por tu permiso" in pagina and 'id="aprobado-por-permiso"' in pagina
    guardado = cambios.cargar(r["id"])
    assert guardado.historial[-1]["quien"] == "puente" and guardado.historial[-1]["permiso"] is True

    # Claude lo escribe sin que nadie pulse «Aprobar».
    assert c.post(f"/api/cambios/{r['id']}/escribir").status_code == 200
    esperar(c)
    assert c.get(f"/api/cambios/{r['id']}").json()["estado"] == "escrito"
    assert sim.editor.lineas == nuevo
    # Sin hooks, escribir devuelve el Mac al acabar, y con él el resumen.
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    resumen = bitacora(c, "correcciones")
    assert len(resumen) == 1 and resumen[0]["quien"] == "puente" and resumen[0]["cambios"] == [r["id"]]
    assert resumen[0]["detalle"].startswith("Claude escribió 1 corrección sin pedirte: revísala antes de guardar")


def test_sin_el_permiso_todo_espera_la_aprobacion_como_siempre(entorno):
    c, sim = entorno
    dar(c)
    lid = leer_con_el_control_dado(c, sim)
    r = proponer(c, lid, con_una_linea(sim, 20))
    assert r["estado"] == "propuesto" and r["aprobado_por"] is None and r["cabe"] is None
    assert r["aviso"] == "Espera a que la persona lo apruebe en la pantalla del puente."
    assert c.post(f"/api/cambios/{r['id']}/escribir").status_code == 400
    assert "correcciones" not in c.get("/api/estado").json()["control"]
    # Y la aprobación de la persona sigue apuntándose como suya.
    assert c.post(f"/api/cambios/{r['id']}/aprobar", headers=PERSONA).status_code == 200
    linea = bitacora(c, "aprobacion")[-1]
    assert linea["quien"] == "persona" and linea["detalle"].endswith(": aprobado")
    assert cambios.cargar(r["id"]).aprobado_por == "persona"
    assert "aprobado por tu permiso" not in c.get(f"/cambios/{r['id']}").text


def _retomar(c, p):
    assert c.post("/api/control", json={"accion": "retomar"}, headers=PERSONA).status_code == 200


def _parar(c, p):
    assert c.post("/api/control", json={"accion": "parar"}, headers=PERSONA).status_code == 200


def _caducar(c, p):
    p.control.ultima_accion = time.time() - INACTIVIDAD_S - 1


def _reabrir(c, p):
    p.conversacion_reabierta("se reabrió Claude Code: el control vuelve a la persona")


def _dar_sin_casilla(c, p):
    dar(c)


@pytest.mark.parametrize("acabar", [_retomar, _parar, _caducar, _reabrir, _dar_sin_casilla])
def test_retomar_parar_caducar_reabrir_o_dar_sin_casilla_acaban_el_permiso(entorno, acabar):
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    p = c.app.state.puente
    assert p.control.permiso_vigente() is not None
    acabar(c, p)
    assert p.control.permiso_vigente() is None
    assert "correcciones" not in c.get("/api/estado").json()["control"]
    r = proponer(c, lid, con_una_linea(sim, 20))
    assert r["estado"] == "propuesto" and r["aprobado_por"] is None


def test_lo_aprobado_por_una_concesion_que_acabo_no_se_escribe_y_vuelve_a_esperar(entorno):
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    r = proponer(c, lid, con_una_linea(sim, 20))
    assert r["estado"] == "aprobado"
    # La persona retoma y vuelve a dar el control, también con la casilla: es otra concesión.
    _retomar(c, None)
    dar(c, correcciones=True)
    antes = list(sim.editor.lineas)
    e = c.post(f"/api/cambios/{r['id']}/escribir")
    assert e.status_code == 400 and "ya acabó" in e.json()["detail"]
    esperar(c)
    assert sim.editor.lineas == antes
    guardado = cambios.cargar(r["id"])
    assert guardado.estado == "propuesto" and guardado.aprobado_por == "persona" and guardado.permiso is None
    assert guardado.historial[-1]["quien"] == "puente" and "ya acabó" in guardado.historial[-1]["que"]
    # Y el presupuesto de la concesión nueva no se tocó.
    assert c.get("/api/estado").json()["control"]["correcciones"]["lineas"] == 0


def test_lo_aprobado_por_una_concesion_que_acabo_la_pagina_lo_enseña_esperando_y_aprobarlo_lo_hace_suyo(entorno):
    """Lo encontró el revisor de C-0489: la página seguía diciendo «Aprobado: listo
    para escribir» con la concesión ya acabada, y el botón no era el de aprobar.
    Mirarla (un GET) no cambia nada en disco; aprobarlo lo pasa a la persona."""
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    r = proponer(c, lid, con_una_linea(sim, 20))
    vigente = c.get(f"/cambios/{r['id']}").text
    assert "Aprobado: listo para escribir" in vigente and "data-aprobar" not in vigente
    _retomar(c, None)

    pagina = c.get(f"/cambios/{r['id']}").text
    assert "Aprobado: listo para escribir" not in pagina and "data-escribir" not in pagina
    assert "Revisa y decide" in pagina and "data-aprobar" in pagina and 'id="permiso-acabado"' in pagina
    assert "espera tu aprobación" in pagina and 'title="No te lo pidió' not in pagina
    assert "espera tu aprobación" in c.get("/panel").text
    guardado = cambios.cargar(r["id"])
    assert guardado.estado == "aprobado" and guardado.aprobado_por == "correcciones"

    assert c.post(f"/api/cambios/{r['id']}/aprobar", headers=PERSONA).status_code == 200
    guardado = cambios.cargar(r["id"])
    assert guardado.estado == "aprobado" and guardado.aprobado_por == "persona" and guardado.permiso is None
    assert bitacora(c, "aprobacion")[-1]["quien"] == "persona"
    assert "Aprobado: listo para escribir" in c.get(f"/cambios/{r['id']}").text
    # Ya no depende de ninguna concesión: se escribe sin la casilla.
    dar(c)
    assert c.post(f"/api/cambios/{r['id']}/escribir").status_code == 200
    esperar(c)
    assert c.get(f"/api/cambios/{r['id']}").json()["estado"] == "escrito"
    # Aprobar dos veces lo de la persona sigue sin valer.
    otro = proponer(c, lid, con_una_linea(sim, 60))
    assert c.post(f"/api/cambios/{otro['id']}/aprobar", headers=PERSONA).status_code == 200
    assert c.post(f"/api/cambios/{otro['id']}/aprobar", headers=PERSONA).status_code == 400


def test_escribir_comprueba_la_concesion_por_su_cuenta():
    """La misma comprobación en `cambios.escribir`, no sólo en la API: quien lo llame
    sin el permiso vigente no escribe, y el cambio vuelve a `propuesto`."""
    original = ["uno", "dos", "tres"]
    nuevo = ["uno", "dos!", "tres"]
    c = cambios.Cambio(id="prueba-abc123", lectura="l", descripcion="d", creado=time.time(),
                       original=original, nuevo=nuevo, tramos=cambios.tramos_de(original, nuevo))
    permiso = Permiso("concesion-1")
    cambios.aprobar(c, permiso)
    assert c.estado == "aprobado" and c.permiso == "concesion-1" and permiso.escritos == [c.id]
    with pytest.raises(ValueError, match="ya acabó"):
        asyncio.run(cambios.escribir(None, c, "claude", None))
    assert cambios.cargar(c.id).estado == "propuesto"


# ── el presupuesto ──────────────────────────────────────────────────────────
def test_diez_cambios_de_tres_lineas_los_primeros_caben_y_el_que_se_pasa_espera(entorno):
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    estados, gastado = [], 0
    for k in range(10):
        nuevo = list(sim.editor.guardado)
        for i in range(10 + 10 * k, 13 + 10 * k):
            nuevo[i] += f" -- {k}"
        r = proponer(c, lid, nuevo, f"tres líneas {k}")
        assert r["lineas"] == 6
        estados.append((r["estado"], r["cabe"]))
        if r["estado"] == "aprobado":
            gastado += r["caracteres"]
    # 3 × 6 = 18 de 20: el cuarto ya no cabe, ni ninguno de los siguientes.
    assert [e for e, _ in estados] == ["aprobado"] * 3 + ["propuesto"] * 7
    assert estados[3][1] == "6 líneas; quedan 2"
    assert all(m == "6 líneas; quedan 2" for _, m in estados[3:])
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(con_una_linea(sim, 150, "x" * 1200)),
                                     "descripcion": "larga"}).json()
    assert r["estado"] == "propuesto" and r["cabe"] == f"{r['caracteres']} caracteres; quedan {1500 - gastado}"
    assert "No cabe en su permiso de correcciones pequeñas (" in r["aviso"] and "No lo partas" in r["aviso"]
    # Lo que aún cabe (2 líneas), cabe.
    r = proponer(c, lid, con_una_linea(sim, 140))
    assert r["estado"] == "aprobado"
    assert c.get("/api/estado").json()["control"]["correcciones"]["lineas"] == TOPE_LINEAS


def _cambio(original: list[str], nuevo: list[str]) -> cambios.Cambio:
    return cambios.Cambio(id="x", lectura="l", descripcion="d", creado=0.0, original=original, nuevo=nuevo,
                          tramos=cambios.tramos_de(original, nuevo))


def test_reemplazar_el_documento_entero_o_escribir_uno_de_cero_no_cabe():
    p = Permiso("c")
    assert cambios.cabe(_cambio(["uno"], ["dos"]), p).startswith("no conserva ninguna línea del original")
    assert cambios.cabe(_cambio(["", "a", ""], ["", "b", ""]), p).startswith("no conserva ninguna línea")
    assert cambios.cabe(_cambio([], ["nuevo"]), p).startswith("el documento leído está vacío")
    assert cambios.cabe(_cambio([""], ["nuevo"]), p).startswith("el documento leído está vacío")
    assert cambios.cabe(_cambio(["uno", "dos"], ["uno", "dos!"]), p) is None
    with pytest.raises(ValueError, match="no cabe"):
        cambios.aprobar(_cambio(["uno"], ["dos"]), p)
    assert p.lineas == 0 and p.escritos == []


def test_quitar_mas_de_la_mitad_del_documento_no_cabe_aunque_quepa_en_el_presupuesto():
    """Lo encontró el revisor de C-0489: cambiar 9 de 10 líneas cabía (18 líneas,
    conserva una), y eso es reescribirlo, no corregirlo."""
    p = Permiso("c")
    original = [f"línea {i}" for i in range(10)]
    nueve = [original[0]] + [f"otra {i}" for i in range(1, 10)]
    assert cambios.cabe(_cambio(original, nueve), p).startswith("quita 9 de las 10 líneas con texto del original")
    cinco = original[:5] + [f"otra {i}" for i in range(5, 10)]
    assert cambios.cabe(_cambio(original, cinco), p) is None
    # Las líneas en blanco no cuentan como documento.
    con_blancos = ["", "a", "", "b", "", "c", "", ""]
    assert cambios.cabe(_cambio(con_blancos, ["", "A", "", "B", "", "c", "", ""]), p).startswith(
        "quita 2 de las 3 líneas con texto")


def test_la_medida_suma_lo_que_quita_y_lo_que_pone():
    c = _cambio(["a", "bb", "c", "d"], ["a", "BBB", "c", "nuevo", "d"])
    assert cambios.medida(c) == (3, 2 + 3 + 5)


def test_un_cambio_guardado_antes_carga_aprobado_por_la_persona(hogar_aparte):
    c = _cambio(["uno"], ["uno", "dos"])
    c.id = "viejo-000001"
    c.guardar()
    ruta = c.carpeta / "cambio.json"
    datos = json.loads(ruta.read_text())
    del datos["aprobado_por"], datos["permiso"]
    ruta.write_text(json.dumps(datos))
    viejo = cambios.cargar("viejo-000001")
    assert viejo.aprobado_por == "persona" and viejo.permiso is None


def test_cada_dar_es_una_concesion_nueva():
    ctl = Control()
    ctl.dar(correcciones=True)
    primero = ctl.permiso_vigente()
    assert primero is not None
    ctl.dar(correcciones=True)
    assert ctl.permiso_vigente() is not primero and ctl.permiso_vigente().id != primero.id
    ctl.dar()
    assert ctl.permiso_vigente() is None


# ── lo que ve la persona ────────────────────────────────────────────────────
def test_sobre_una_lectura_sin_verificar_se_aprueba_con_su_marca(entorno):
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim, verificar=False)
    r = proponer(c, lid, con_una_linea(sim, 20))
    assert r["estado"] == "aprobado" and r["lectura_verificada"] is False
    assert r["aviso"].startswith("La lectura de la que parte está sin verificar")
    assert bitacora(c, "aprobacion")[-1]["detalle"].endswith(", sobre una lectura sin verificar")
    assert "sobre una lectura sin verificar" in c.get(f"/cambios/{r['id']}").text
    assert "sobre una lectura sin verificar" in c.get("/panel").text


def test_al_retomar_el_mac_la_bitacora_resume_lo_que_escribio_sin_pedir(entorno):
    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    p = c.app.state.puente
    # Con un turno en curso el control sigue tras escribir (C-0486): lo devuelve la persona.
    p.turno_en_curso = lambda: True
    r = proponer(c, lid, con_una_linea(sim, 20))
    assert c.post(f"/api/cambios/{r['id']}/escribir").status_code == 200
    esperar(c)
    assert c.get("/api/estado").json()["control"]["modo"] == "claude"
    assert bitacora(c, "correcciones") == []
    # Uno aprobado pero sin escribir no cuenta: no hay nada que revisar.
    proponer(c, lid, con_una_linea(sim, 60), "sin escribir")
    _retomar(c, p)
    resumen = bitacora(c, "correcciones")
    assert len(resumen) == 1 and resumen[0]["cambios"] == [r["id"]]
    assert "Claude escribió 1 corrección sin pedirte" in resumen[0]["detalle"]


def test_si_el_control_caduca_la_bitacora_resume_igual_lo_que_escribio_sin_pedir(entorno):
    """Lo encontró el revisor de C-0489: al caducar, `Control` ya lo había soltado
    y el resumen buscaba el permiso vigente, que ya no había. Ahora el permiso
    se coge antes de soltar y se le pasa al resumen."""
    from puente_kvm import mediciones

    c, sim = entorno
    dar(c, correcciones=True)
    lid = leer_con_el_control_dado(c, sim)
    p = c.app.state.puente
    p.turno_en_curso = lambda: True
    r = proponer(c, lid, con_una_linea(sim, 20))
    assert c.post(f"/api/cambios/{r['id']}/escribir").status_code == 200
    esperar(c)
    assert c.get("/api/estado").json()["control"]["modo"] == "claude"
    assert bitacora(c, "correcciones") == []
    _caducar(c, p)
    # Lo primero que mira el control después: aquí, devolverlo por un fin de turno.
    p.devolver_control("Claude terminó: el Mac vuelve a ti para revisar y guardar", por="fin_turno")
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    resumen = bitacora(c, "correcciones")
    assert len(resumen) == 1 and resumen[0]["cambios"] == [r["id"]]
    assert "Claude escribió 1 corrección sin pedirte" in resumen[0]["detalle"]
    # Un solo «devuelto», el de la caducidad: devolverlo después ya no tenía nada que devolver.
    devueltos = [json.loads(l) for f in sorted(mediciones.carpeta().glob("*.jsonl"))
                 for l in f.read_text().splitlines() if l.strip()]
    devueltos = [l for l in devueltos if l["tipo"] == "control" and l.get("evento") == "devuelto"]
    assert [l["por"] for l in devueltos] == ["caducidad"]
    assert not any("Claude terminó" in l["detalle"] for l in bitacora(c, "control"))


def test_sin_haber_escrito_nada_al_devolver_no_hay_resumen(entorno):
    c, _ = entorno
    dar(c, correcciones=True)
    c.app.state.puente.devolver_control("Claude terminó: el Mac vuelve a ti para revisar y guardar")
    assert bitacora(c, "correcciones") == []


def test_las_puertas_que_devuelven_el_mac_no_dan_el_control_ni_el_permiso():
    """Lo de `test_control_por_turno`, para lo que añade C-0489: el resumen se lee
    al devolver, y leerlo no puede conceder nada."""
    import inspect
    import re

    from puente_kvm.app import Puente

    for metodo in (Puente.resumen_correcciones, Puente.devolver_control, Puente.aprobar_cambio,
                   Puente._al_caducar, Puente.olvidar_pendiente):
        fuente = inspect.getsource(metodo)
        assert ".dar(" not in fuente and ".parar(" not in fuente
        assert not re.search(r"control\.(modo|permiso|concesion)\s*=[^=]", fuente)
