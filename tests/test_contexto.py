"""El contexto completo — la costura de lectura del asistente (§9).

Lo que se pega al principio de una sesión tiene que ser cierto y tiene que caber:
si mezcla cosas sanas con cosas que exigen acción, se deja de leer entero y deja
de servir.
"""

from __future__ import annotations

import pytest

from hub import api, busqueda


@pytest.fixture
def poblado(con, tmp_path):
    estado = tmp_path / "ESTADO.md"
    estado.write_text(
        "## Estado\n\nen marcha\n\n## Próxima acción\n\ncerrar el escalón 1\n",
        encoding="utf-8",
    )
    con.execute(
        """INSERT INTO proyecto (id, nombre, asiento, estado_ref, nota)
           VALUES ('demo','Demo',?,'ESTADO.md','una nota')""",
        (str(tmp_path),),
    )
    con.execute(
        "INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo',?,'asiento')",
        (str(tmp_path),),
    )
    con.execute(
        """INSERT INTO repo (proyecto_id, ruta, rama, sin_push, regimen, sucios,
                             worktrees, repo_comun, head, medido_en)
           VALUES ('demo','/dev/demo','dev',250,'sin-upstream',2,0,'/dev/demo/.git','abc','2026-08-28')"""
    )
    con.execute(
        """INSERT INTO repo (proyecto_id, ruta, rama, sin_push, regimen, sucios,
                             worktrees, repo_comun, head, medido_en)
           VALUES ('demo','/dev/demo-int','dev',250,'sin-upstream',0,0,'/dev/demo/.git','abc','2026-08-28')"""
    )
    con.execute(
        """INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, detalle, medido_en)
           VALUES ('demo-db','demo','pg','running','Up','2026-08-28')"""
    )
    con.execute(
        """INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, detalle, medido_en)
           VALUES ('huerfano',NULL,'x','exited','Exited','2026-08-28')"""
    )
    busqueda.reindexar(con)
    return con


def test_reune_todo_el_estado_en_una_sola_llamada(poblado):
    """El asistente lee esto en vez de levantar una sesión por proyecto."""
    c = api.contexto(poblado)
    assert [p["id"] for p in c["proyectos"]] == ["demo"]
    assert c["respaldo"]["commits_sin_respaldo"] == 250
    assert c["servicios"]["total"] == 2


def test_el_markdown_abre_con_lo_que_no_esta_respaldado(poblado):
    texto = api.contexto_markdown(poblado)
    assert "250 commits sin respaldo" in texto.splitlines()[2]


def test_el_markdown_trae_el_estado_que_el_proyecto_declaro(poblado):
    texto = api.contexto_markdown(poblado)
    assert "**Estado:** en marcha" in texto
    assert "**Próxima acción:** cerrar el escalón 1" in texto


def test_no_suma_dos_veces_los_worktrees_del_mismo_commit(poblado):
    """Dos filas, 250 cada una, mismo repo y mismo HEAD: son los mismos commits."""
    texto = api.contexto_markdown(poblado)
    assert texto.count("250 commits sin push") == 1


def test_solo_lista_los_repos_que_exigen_accion(poblado):
    """Una lista de todo lo sano es ruido que hace que se deje de leer lo que sí importa."""
    poblado.execute("UPDATE repo SET sin_push = 0, sucios = 0")
    texto = api.contexto_markdown(poblado)
    assert "commits sin push" not in texto
    assert "Todo lo commiteado está respaldado" in texto


def test_un_contenedor_sin_dueno_sale_aparte(poblado):
    assert "huerfano" in api.contexto_markdown(poblado).split("## Sin atribuir")[1]


def test_un_proyecto_sin_bloque_de_estado_lo_dice_en_vez_de_callarlo(con):
    """Callarlo dejaría creer que el proyecto está bien, que es la lectura cara."""
    con.execute(
        "INSERT INTO proyecto (id, nombre, estado_ref) VALUES ('x','X','docs/NO.md')"
    )
    assert "Sin bloque de estado legible" in api.contexto_markdown(con)


def test_un_proyecto_que_no_declara_documento_vigente_tambien_se_dice(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('x','X')")
    assert "No declara qué documento suyo está vigente" in api.contexto_markdown(con)
