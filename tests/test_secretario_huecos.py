"""De «no sé hacerlo» a «ya sé» (C-0252): el recorrido de un hueco, en un solo sitio.

Lo que el secretario no supo hacer se apunta (`no_se_hacer`), con el sí del
dueño pasa a idea del tablero y, tomada, a una ficha. `hub.secretario.huecos`
cruza las tres cosas una sola vez: Confianza lo pinta (`api.secretario_huecos`)
y el ciclo de `hub-secretario` lo usa para decirle, una vez y en el chat, que
ya sabe hacerlo.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from hub import api, config, db, ideas
from hub.secretario import huecos, memoria, piezas

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def con():
    h = db.conectar(config.DB_PATH)
    db.inicializar(h)
    h.close()
    c = memoria.conectar()
    yield c
    c.close()


def _hueco_con_idea(que: str, estado: str = "nueva", ref: str = "") -> int:
    """Como lo deja el camino de verdad: el hueco en la bitácora y su idea marcada."""
    m = memoria.conectar()
    memoria.apuntar(m, "hueco", params={"que": que}, resultado="sin herramienta")
    m.close()
    h = db.conectar(config.DB_PATH)
    i = ideas.apuntar(h, "poder " + que, origen="secretario", hueco=que)
    if estado == "tomada":
        ideas.tomar(h, i, ref)
    h.commit()
    h.close()
    return i


def _ficha(carpeta: Path, ident: str, estado: str, **extra) -> Path:
    cab = {"id": ident, "titulo": "x", "tipo": "funcion", "tamano": "S", "estado": estado, "quien": "claude",
           "modulos": []} | extra
    ruta = carpeta / f"{ident}-x.md"
    ruta.write_text("---\n" + yaml.safe_dump(cab, allow_unicode=True) + "---\n\n## Qué se pidió\n", encoding="utf-8")
    return ruta


def _con_fichas(tmp_path: Path) -> Path:
    carpeta = tmp_path / "cambios"
    carpeta.mkdir()
    (memoria.carpeta() / "secretario.yml").write_text(f"parte_fichas: {carpeta}\n", encoding="utf-8")
    return carpeta


# ── un solo cruce, un solo sitio ─────────────────────────────────────────────

def test_el_cruce_vive_en_huecos_y_api_no_tiene_una_copia():
    """El servicio necesita el mismo cruce que Confianza: copiarlo sería el
    segundo camino que MAPA.md existe para evitar."""
    assert not hasattr(api, "_mejoras_de_huecos")
    assert "huecos.mejoras" in Path(api.__file__).read_text(encoding="utf-8")


def test_confianza_pinta_lo_que_dice_huecos(con, monkeypatch):
    memoria.apuntar(con, "hueco", params={"que": "Mover  un Archivo"}, resultado="sin herramienta")
    monkeypatch.setattr(huecos, "mejoras", lambda: {"mover un archivo": {"etiqueta": "de prueba"}})

    (g,) = api.secretario_huecos(con)
    assert g["que"] == "Mover un Archivo" and g["mejora"] == {"etiqueta": "de prueba"}


def test_un_hueco_se_reconoce_igual_en_la_bitacora_y_en_el_tablero(con):
    assert ideas.clave_hueco("  Cancelar\tuna  CITA ") == "cancelar una cita"
    i = _hueco_con_idea("Cancelar  una cita")
    h = db.conectar(config.DB_PATH)
    try:
        assert ideas.de_huecos(h)[ideas.clave_hueco("cancelar una cita")]["id"] == i
    finally:
        h.close()
    assert huecos.mejoras()["cancelar una cita"]["idea"] == i


def test_la_carpeta_de_fichas_sale_de_secretario_yml_o_no_hay(tmp_path):
    assert piezas.carpeta_de_fichas() is None   # el producto: `cambios/` no viaja
    (memoria.carpeta() / "secretario.yml").write_text("parte_fichas: ~/en-casa/cambios\n", encoding="utf-8")
    assert piezas.carpeta_de_fichas() == Path("~/en-casa/cambios").expanduser()
    # No comprueba que exista: el parte y la lectura `fichas` lo dicen cada uno a su manera.
    (memoria.carpeta() / "secretario.yml").write_text(f"parte_fichas: {tmp_path / 'no-existe'}\n", encoding="utf-8")
    assert piezas.carpeta_de_fichas() == tmp_path / "no-existe"


def test_nadie_mas_resuelve_la_carpeta_de_fichas_por_su_cuenta():
    """Se resolvía en cuatro sitios (el parte, «Te espera», la lectura `fichas`
    y Confianza): cuatro lectores de la misma clave acaban entendiendo cosas
    distintas (C-0040)."""
    sueltos = [str(p.relative_to(RAIZ)) for p in (RAIZ / "src" / "hub").rglob("*.py")
               if p.name != "piezas.py" and 'ajuste("parte_fichas")' in p.read_text(encoding="utf-8")]
    assert not sueltos, f"resuelven `parte_fichas` sin `piezas.carpeta_de_fichas`: {sueltos}"


def test_sin_carpeta_de_fichas_la_mejora_se_queda_en_el_estado_de_la_idea(con):
    _hueco_con_idea("cancelar una cita", "tomada", "C-0300")
    m = huecos.mejoras()["cancelar una cita"]
    assert m["ficha"] is None and m["etiqueta"] == "apuntado como mejora · tomada"


def test_con_su_ficha_la_mejora_dice_en_que_estado_esta(con, tmp_path):
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "en-curso")
    _hueco_con_idea("cancelar una cita", "tomada", "C-0300")
    m = huecos.mejoras()["cancelar una cita"]
    assert m["ficha"] == {"id": "C-0300", "estado": "en-curso"}
    assert m["etiqueta"] == "apuntado como mejora · en curso"


# ── «ya sé hacerlo», una vez y en el chat ────────────────────────────────────

def _turnos(con) -> list[str]:
    return [f["texto"] for f in con.execute("SELECT texto FROM turno WHERE rol = 'secretario' ORDER BY id")]


@pytest.fixture
def sin_telefono(monkeypatch):
    """Lo que intentara salir al teléfono, apuntado: no puede salir nada."""
    from hub.secretario import avisos
    salido: list = []
    monkeypatch.setattr(avisos, "mandar", lambda *a, **k: salido.append(("mandar", a, k)))
    monkeypatch.setattr(avisos, "intentar", lambda *a, **k: salido.append(("intentar", a, k)))
    return salido


def test_la_resuelve_de_una_ficha_es_texto_o_lista_de_nombres():
    from hub import fichas
    assert fichas.resuelve({}) == []
    assert fichas.resuelve({"resuelve": "ideas"}) == ["ideas"]
    assert fichas.resuelve({"resuelve": ["ideas", " accion_apuntar_idea "]}) == ["ideas", "accion_apuntar_idea"]
    assert fichas.resuelve({"resuelve": ["", None]}) == []
    assert fichas.resuelve({"resuelve": {"no": "vale"}}) == []


def test_con_la_ficha_en_curso_no_dice_nada(con, tmp_path, sin_telefono):
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "en-curso", resuelve="ideas")
    _hueco_con_idea("ver las ideas del tablero", "tomada", "C-0300")

    assert huecos.recoger(con) == 0
    assert _turnos(con) == []


def test_hecha_pero_con_una_herramienta_que_no_existe_aqui_no_lo_dice(con, tmp_path, sin_telefono):
    """Regla dura 13: «hecha en una copia de trabajo» no es «cargada en el
    servicio que corre». Lo que no está en este proceso no se anuncia."""
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13", resuelve=["ideas", "accion_que_no_existe"])
    _hueco_con_idea("ver las ideas del tablero", "tomada", "C-0300")

    assert huecos.recoger(con) == 0
    assert _turnos(con) == []


def test_una_herramienta_que_ahora_no_esta_disponible_cuenta_como_que_no_existe(con, tmp_path, sin_telefono):
    """`agenda` sin calendario conectado no se ofrece (C-0408): decir «ya sé»
    con ella sería prometer algo que ahora sólo puede fallar."""
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13", resuelve="agenda")
    _hueco_con_idea("mirar mi calendario", "tomada", "C-0300")

    assert huecos.recoger(con) == 0


def test_sin_resuelve_una_mejora_hecha_no_se_anuncia(con, tmp_path, sin_telefono):
    """Una mejora que no es una herramienta no es comprobable aquí: Confianza
    ya enseña que está hecha."""
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13")
    _hueco_con_idea("ver las ideas del tablero", "tomada", "C-0300")

    assert huecos.recoger(con) == 0


def test_hecha_con_su_herramienta_lo_dice_una_vez_en_el_chat_y_no_al_telefono(con, tmp_path, sin_telefono):
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13", resuelve=["ideas"])
    i = _hueco_con_idea("Ver las ideas del tablero", "tomada", "C-0300")

    assert huecos.recoger(con) == 1
    (texto,) = _turnos(con)
    assert "ya sé" in texto.lower() and "«Ver las ideas del tablero»" in texto and "C-0300" in texto
    b = con.execute("SELECT params FROM bitacora WHERE accion = 'hueco_resuelto'").fetchone()
    assert b and f'"idea": {i}' in b["params"] and '"ficha": "C-0300"' in b["params"]
    assert memoria.leer(con, huecos.CLAVE) == [i]
    assert sin_telefono == []

    assert huecos.recoger(con) == 0, "a la segunda vuelta ya está dicho"
    assert len(_turnos(con)) == 1


def test_lo_ya_dicho_no_vuelve_a_leer_las_fichas_en_cada_vuelta(con, tmp_path, sin_telefono, monkeypatch):
    """La idea sigue `tomada` para siempre: sin esto, cada vuelta leería todas
    las fichas por algo que ya contó (regla dura 14)."""
    from hub import fichas
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13", resuelve="ideas")
    _hueco_con_idea("ver las ideas del tablero", "tomada", "C-0300")
    assert huecos.recoger(con) == 1

    leidas: list = []
    monkeypatch.setattr(fichas, "listar", lambda *a, **k: leidas.append(a) or [])
    assert huecos.recoger(con) == 0
    assert leidas == []
    # Confianza sí las sigue leyendo: enseña el estado de cada una.
    huecos.mejoras()
    assert len(leidas) == 1


def test_una_herramienta_solo_con_el_dueno_tambien_se_reconoce(con, tmp_path, sin_telefono, monkeypatch):
    """El ciclo no tiene hilo, y `todas()` sin él esconde lo que sólo se hace
    con el dueño delante. Para saber si existe se mira con él (404)."""
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13", resuelve="investigar")
    _hueco_con_idea("buscar precios en la web", "tomada", "C-0300")

    assert huecos.recoger(con) == 1


def test_sin_carpeta_de_fichas_no_hay_nada_que_recoger(con, sin_telefono):
    """El producto no trae `cambios/`: ahí el cierre se queda en el estado de la idea."""
    _hueco_con_idea("ver las ideas del tablero", "tomada", "C-0300")
    assert huecos.recoger(con) == 0
    assert _turnos(con) == []


def test_el_texto_del_hueco_sale_con_sus_datos_tapados(con, tmp_path, sin_telefono):
    from hub.secretario import misdatos
    misdatos.confirmar("telefono", "5512345678")
    carpeta = _con_fichas(tmp_path)
    _ficha(carpeta, "C-0300", "hecha", cerrada="2026-11-13", resuelve="ideas")
    _hueco_con_idea("llamar al 5512345678", "tomada", "C-0300")

    assert huecos.recoger(con) == 1
    (texto,) = _turnos(con)
    assert "5512345678" not in texto and "[tu teléfono]" in texto
    b = con.execute("SELECT params FROM bitacora WHERE accion = 'hueco_resuelto'").fetchone()
    assert "5512345678" not in b["params"]


def test_huecos_no_es_un_aviso_ni_llama_al_modelo():
    """Regla dura 3 y decisión 379: «ya sé hacer X» no sale al teléfono ni es
    un asunto; y la frase se arma por guion. Lo comprueba el árbol, no el
    comportamiento de hoy: un import nuevo bastaría para romperlo."""
    arbol = ast.parse((RAIZ / "src" / "hub" / "secretario" / "huecos.py").read_text(encoding="utf-8"))
    importado = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            importado |= {a.name.rsplit(".", 1)[-1] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            importado |= {(n.module or "").rsplit(".", 1)[-1]} | {a.name for a in n.names}
    assert not importado & {"avisos", "asuntos", "motor", "timbre"}, importado
