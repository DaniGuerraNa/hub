"""La pantalla de archivos, de la costura de lectura al HTML servido.

La garantía que más importa aquí no es que enseñe bien: es **lo que nunca sale**.
El navegador existe para contestar «¿tengo el repo tal?» estando lejos de la
máquina, así que su respuesta viaja por la red privada a un móvil que se puede
perder. Enseña nombres y rutas; contenido, nunca.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from hub import api, busqueda, db, navegador, web

SECRETO = "contraseña-que-no-debe-salir-jamas"


@pytest.fixture
def arbol(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "api-clientes/.git").mkdir(parents=True)
    (raiz / "api-clientes/src").mkdir()
    (raiz / "api-clientes/.env").write_text(SECRETO)
    (raiz / "sin-git").mkdir()
    (tmp_path / "fuera").mkdir()
    (tmp_path / "fuera/claves.txt").write_text(SECRETO)
    return tmp_path


@pytest.fixture
def con(arbol, tmp_path):
    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    raiz = str(arbol / "proyectos")
    con.execute(
        "INSERT INTO proyecto (id, nombre, asiento, estado_ref) VALUES ('demo','Demo',?,'E.md')",
        (raiz,),
    )
    for ruta, tipo in ((raiz, "asiento"), (f"{raiz}/api-clientes", "repo")):
        con.execute(
            "INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo',?,?)",
            (ruta, tipo),
        )
    con.execute(
        """INSERT INTO repo (proyecto_id, ruta, rama, sin_push, regimen, sucios,
                             worktrees, repo_comun, head, medido_en)
           VALUES ('demo',?,'dev',3,'con-upstream',7,1,?,'abc','2026-09-14')""",
        (f"{raiz}/api-clientes", f"{raiz}/api-clientes/.git"),
    )
    yield con
    con.close()


# ────────────────────────── la costura de lectura ──────────────────────────


def test_sin_ruta_da_los_sitios_por_donde_empezar(con, arbol):
    """Y colapsados: el repo declarado cuelga del asiento, así que no sale dos veces."""
    datos = api.explorar(con, "")
    assert [e["nombre"] for e in datos["entradas"]] == ["proyectos"]
    assert datos["entradas"][0]["proyecto"] == "Demo"


def test_la_portada_y_una_carpeta_tienen_la_misma_forma(con, arbol):
    """Un caso especial para la portada sería una segunda plantilla que se olvida."""
    assert set(api.explorar(con, "")) >= {"ruta", "migas", "arriba", "entradas"}
    dentro = api.explorar(con, str(arbol / "proyectos"))
    assert set(dentro) >= {"ruta", "migas", "arriba", "entradas"}


def test_un_repo_llega_con_lo_que_el_hub_ya_midió(con, arbol):
    """Sin ejecutar `git`: lo caro va en el ciclo lento (regla 14)."""
    entradas = api.explorar(con, str(arbol / "proyectos"))["entradas"]
    repo = next(e for e in entradas if e["nombre"] == "api-clientes")
    assert repo["rama"] == "dev"
    assert repo["sucios"] == 7
    assert repo["medido_en"] == "2026-09-14"


def test_una_carpeta_sin_git_no_finge_tener_rama(con, arbol):
    entradas = api.explorar(con, str(arbol / "proyectos"))["entradas"]
    sin = next(e for e in entradas if e["nombre"] == "sin-git")
    assert sin["repo"] is False
    assert "rama" not in sin


def test_cada_entrada_sabe_de_qué_proyecto_es(con, arbol):
    entradas = api.explorar(con, str(arbol / "proyectos"))["entradas"]
    assert {e["proyecto_id"] for e in entradas} == {"demo"}


def test_lo_que_está_fuera_del_índice_no_se_explora(con, arbol):
    with pytest.raises(navegador.FueraDeRaiz):
        api.explorar(con, str(arbol / "fuera"))


# ─────────────────────────── la pantalla servida ───────────────────────────


@pytest.fixture
def cliente(con, monkeypatch, tmp_path):
    monkeypatch.setattr(web, "conexion", lambda: db.conectar(tmp_path / "hub.db"))
    return TestClient(web.app)


def test_la_pantalla_se_sirve(cliente, arbol):
    r = cliente.get("/archivos", params={"ruta": str(arbol / "proyectos")})
    assert r.status_code == 200
    assert "api-clientes" in r.text


def test_el_contenido_de_un_archivo_no_sale_nunca(cliente, arbol):
    """La garantía es estructural: no hay ninguna función que lea un archivo.

    Se comprueba sobre el HTML entero —no sobre el JSON— porque lo que llega al
    móvil es esto.
    """
    r = cliente.get("/archivos", params={"ruta": str(arbol / "proyectos/api-clientes")})
    assert r.status_code == 200
    assert SECRETO not in r.text


def test_un_dotfile_no_se_lista_pero_se_dice_que_está(cliente, arbol):
    r = cliente.get("/archivos", params={"ruta": str(arbol / "proyectos/api-clientes")})
    # Pegado a `</span>`: la hoja de estilo trae `.envoltura` y un `in` suelto
    # daría verde por una clase de CSS. Un test que pasa por el motivo
    # equivocado deja de avisar el día que importa.
    assert ".env</span>" not in r.text
    assert "oculta" in r.text


def test_pedir_algo_de_fuera_avisa_en_vez_de_dar_un_500(cliente, arbol):
    """El que lo ve está lejos: un error genérico ahí no se puede depurar."""
    r = cliente.get("/archivos", params={"ruta": "/etc"})
    assert r.status_code == 200
    assert "no está bajo ninguna ruta" in r.text


def test_tras_un_error_se_cae_a_las_raíces_y_no_a_una_pantalla_vacía(cliente):
    r = cliente.get("/archivos", params={"ruta": "/etc"})
    assert "proyectos" in r.text


def test_una_ruta_que_ya_no_existe_lo_dice(cliente, arbol):
    r = cliente.get("/archivos", params={"ruta": str(arbol / "proyectos/fantasma")})
    assert "ya no existe" in r.text


# ──────────────────────────────── el buscador ────────────────────────────────


def test_un_repo_se_encuentra_escribiendo_su_nombre(con):
    """Es la pregunta real: «¿tengo el repo tal?», con alguien esperando."""
    busqueda.reindexar(con)
    hallazgos = busqueda.buscar(con, "api-clientes")
    assert any(h["clase"] == "repo" for h in hallazgos)


def test_el_hallazgo_lleva_al_navegador_y_no_a_ningún_sitio(con, arbol):
    busqueda.reindexar(con)
    repo = next(h for h in busqueda.buscar(con, "api-clientes") if h["clase"] == "repo")
    assert repo["url"].startswith("/archivos?ruta=")


def test_una_ruta_con_espacios_y_almohadilla_sobrevive_al_enlace(con, tmp_path, monkeypatch):
    """Los árboles que vienen de OneDrive traen espacios, y `#` corta una URL.

    Las barras se dejan legibles a propósito —son válidas en una query— pero lo
    que rompería el enlace no puede pasar en crudo.
    """
    rara = "/tmp/Mis Cosas/c#digo"
    con.execute(
        """INSERT INTO repo (proyecto_id, ruta, rama, regimen, sucios, worktrees,
                             medido_en)
           VALUES ('demo',?,'main','sin-remoto',0,1,'2026-09-14')""",
        (rara,),
    )
    busqueda.reindexar(con)
    hallazgo = next(h for h in busqueda.buscar(con, "digo") if h["clase"] == "repo")
    destino = hallazgo["url"]
    assert " " not in destino and "#" not in destino
    assert unquote(destino.split("ruta=", 1)[1]) == rara


def test_el_respaldo_sin_fts_también_encuentra_repos(con, monkeypatch):
    """🔴 Un respaldo que encuentra menos clases convierte «no hay FTS5» en «no existe».

    Y el que pregunta está lejos de la máquina y no lo puede comprobar.
    """
    monkeypatch.setattr(db, "hay_fts", lambda c: False)
    monkeypatch.setattr(busqueda.db, "hay_fts", lambda c: False)
    hallazgos = busqueda.buscar(con, "api-clientes")
    assert any(h["clase"] == "repo" for h in hallazgos)


# ──────────────────── abrir una terminal en esta carpeta ────────────────────
#
# 🔴 Lo que se protege: que abrir una ventana **no sea ejecutar**, y que la ruta
# se resuelva contra las raíces ANTES de tocar tmux. Un endpoint que recibe una
# ruta y abre una shell ahí es, sin confín, el agujero entero del navegador.


@pytest.fixture
def tmux_falso(monkeypatch):
    """Apunta qué ventana se abrió y qué se escribió dentro."""
    abiertas = []

    def abrir_en(ruta, nombre, session, texto=""):
        abiertas.append({"ruta": ruta, "nombre": nombre, "session": session, "texto": texto})
        return "%9"

    monkeypatch.setattr(web.slots, "abrir_en", abrir_en)
    return abiertas


def test_abre_la_ventana_en_la_carpeta_que_se_está_mirando(cliente, arbol, tmux_falso):
    carpeta = str(arbol / "proyectos/api-clientes")

    r = cliente.post("/archivos/terminal", data={"ruta": carpeta}, follow_redirects=False)

    assert r.status_code in (302, 303)
    assert tmux_falso[0]["ruta"] == carpeta
    assert tmux_falso[0]["texto"] == ""      # sin comando: sólo la ventana


def test_una_ruta_fuera_del_indice_no_abre_ninguna_ventana(cliente, arbol, tmux_falso):
    """El mismo ataque que el resto del navegador, por la puerta de tmux."""
    r = cliente.post("/archivos/terminal", data={"ruta": str(arbol / "fuera")},
                     follow_redirects=False)

    assert tmux_falso == []
    assert "aviso=" in r.headers["location"]


def test_un_archivo_no_es_una_carpeta_donde_abrir_una_terminal(cliente, arbol, tmux_falso):
    r = cliente.post("/archivos/terminal",
                     data={"ruta": str(arbol / "proyectos/api-clientes/.env")},
                     follow_redirects=False)

    assert tmux_falso == []
    assert "aviso=" in r.headers["location"]


def test_el_comando_preparado_llega_escrito_y_con_la_ruta_puesta(
    cliente, arbol, tmux_falso, tmp_path, monkeypatch
):
    """`{ruta}` la rellena la carpeta: es el dato que no se teclea en un móvil."""
    yml = tmp_path / "comandos.yml"
    yml.write_text("comandos:\n  - id: clonar\n    nombre: Clonar\n"
                   "    plantilla: bash clonar.sh {repo} {ruta}\n", encoding="utf-8")
    monkeypatch.setenv("HUB_COMANDOS_YML", str(yml))
    carpeta = str(arbol / "proyectos")

    cliente.post("/archivos/terminal",
                 data={"ruta": carpeta, "comando": "clonar", "hueco_repo": "mi-api"},
                 follow_redirects=False)

    assert tmux_falso[0]["texto"] == f"bash clonar.sh mi-api {carpeta}"


def test_si_falta_un_hueco_no_se_abre_nada(cliente, arbol, tmux_falso, tmp_path, monkeypatch):
    """Ni ventana ni comando a medias: se vuelve diciendo qué falta."""
    yml = tmp_path / "comandos.yml"
    yml.write_text("comandos:\n  - id: clonar\n    plantilla: bash clonar.sh {repo}\n",
                   encoding="utf-8")
    monkeypatch.setenv("HUB_COMANDOS_YML", str(yml))

    r = cliente.post("/archivos/terminal",
                     data={"ruta": str(arbol / "proyectos"), "comando": "clonar"},
                     follow_redirects=False)

    assert tmux_falso == []
    assert "repo" in unquote(r.headers["location"])
