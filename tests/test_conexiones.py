"""Conexiones: punteros a credenciales, nunca credenciales.

Regla dura 5 y decisión 28. Un índice de proyectos que empieza a guardar
secretos multiplica el radio de daño de cualquier fallo, así que aquí se prueba
sobre todo lo que el módulo **no** debe hacer.
"""

from __future__ import annotations

from hub import api, conexiones, registry
from hub.models import Conexion, Proyecto, Ruta


def test_detecta_un_secreto_pegado_en_claro():
    """Si alguien pega una contraseña «temporalmente», hay que decirlo en alto."""
    assert conexiones.revisar_secretos({"alias": "vps", "password": "x"}) == ["password"]
    assert conexiones.revisar_secretos({"api_key": "x", "token": "y"}) == ["api_key", "token"]


def test_una_conexion_normal_no_dispara_falsas_alarmas():
    assert conexiones.revisar_secretos(
        {"alias": "vps", "host": "h", "referencia_secreto": "~/.ssh/config#vps"}
    ) == []


def test_el_puntero_se_comprueba_pero_nunca_se_abre(tmp_path):
    archivo = tmp_path / "config"
    archivo.write_text("Host vps\n  User ana\n", encoding="utf-8")
    assert conexiones.puntero_existe(f"{archivo}#vps") is True
    assert conexiones.puntero_existe(f"{tmp_path}/no-existe#vps") is False


def test_una_url_de_gestor_de_secretos_no_se_sondea():
    """Sondear la URL de un gestor de secretos sería tocar el almacén. No se hace."""
    assert conexiones.puntero_existe("https://vault.example/kv/vps") is None
    assert conexiones.puntero_existe(None) is None
    assert conexiones.puntero_existe("") is None


def test_sincronizar_guarda_datos_de_conexion_y_el_estado_del_puntero(con, tmp_path):
    archivo = tmp_path / "config"
    archivo.write_text("x", encoding="utf-8")
    conexiones.sincronizar(con, [
        Conexion(alias="vps-pruebas", host="h", usuario="ana",
                 proposito="pruebas", proyectos=["facturador", "hub"],
                 referencia_secreto=f"{archivo}#vps-pruebas"),
    ])

    fila = con.execute("SELECT * FROM conexion").fetchone()
    assert fila["alias"] == "vps-pruebas" and fila["puntero_ok"] == 1
    vinculos = [f[0] for f in con.execute(
        "SELECT proyecto_id FROM conexion_proyecto ORDER BY proyecto_id")]
    assert vinculos == ["facturador", "hub"]


def test_el_yaml_manda_lo_que_se_quita_desaparece(con):
    conexiones.sincronizar(con, [Conexion(alias="vieja")])
    conexiones.sincronizar(con, [Conexion(alias="nueva")])
    assert [f[0] for f in con.execute("SELECT alias FROM conexion")] == ["nueva"]


def test_se_cargan_del_mismo_projects_yml(tmp_path):
    """Van en el mismo archivo a propósito: un segundo sitio que recordar es
    exactamente el problema que el hub existe para resolver."""
    yml = tmp_path / "projects.yml"
    yml.write_text(
        "proyectos: []\n"
        "conexiones:\n"
        "  - alias: vps\n    host: 203.0.113.10\n    proyectos: [facturador]\n"
        "    referencia_secreto: ~/.ssh/config#vps\n",
        encoding="utf-8",
    )
    cargadas = registry.cargar_conexiones(yml)
    assert len(cargadas) == 1
    assert cargadas[0].alias == "vps" and cargadas[0].proyectos == ["facturador"]


def test_una_contrasena_pegada_en_el_yaml_se_avisa_y_no_se_guarda(tmp_path, capsys, con):
    """Guardarla en silencio sería justo lo que la decisión 28 existe para impedir."""
    yml = tmp_path / "projects.yml"
    yml.write_text(
        "conexiones:\n  - alias: vps\n    host: h\n    password: secreta123\n",
        encoding="utf-8",
    )
    cargadas = registry.cargar_conexiones(yml)

    assert "NO guarda secretos" in capsys.readouterr().out
    conexiones.sincronizar(con, cargadas)
    fila = con.execute("SELECT * FROM conexion").fetchone()
    assert "secreta123" not in str(tuple(fila))


def test_un_projects_yml_sin_conexiones_no_falla(tmp_path):
    yml = tmp_path / "projects.yml"
    yml.write_text("proyectos: []\n", encoding="utf-8")
    assert registry.cargar_conexiones(yml) == []


# ── Lo que un proyecto tiene concedido ──────────────────────────────────────
#
# Decisión 197. El hub reparte DIRECCIONES de dónde vive una credencial, y el
# reparto lo gobierna la lista `proyectos:` de cada conexión. Aquí se prueba
# sobre todo que esa lista concede de verdad y no es una etiqueta.


def _con_proyectos(con, rutas: dict[str, list[str]]) -> None:
    proyectos = [
        Proyecto(id=pid, nombre=pid.title(), asiento=rs[0],
                 rutas=[Ruta(ruta=r) for r in rs[1:]])
        for pid, rs in rutas.items()
    ]
    registry.sincronizar(con, proyectos)


def test_desde_el_directorio_de_un_proyecto_llegan_sus_conexiones(con):
    _con_proyectos(con, {"facturador": ["/casa/facturador"]})
    conexiones.sincronizar(con, [
        Conexion(alias="vps", host="203.0.113.10", usuario="root",
                 proyectos=["facturador"], referencia_secreto="~/.ssh/config#vps"),
    ])

    r = api.conexiones_concedidas(con, "/casa/facturador")

    assert r["proyecto_id"] == "facturador"
    assert [c["alias"] for c in r["conexiones"]] == ["vps"]
    assert r["conexiones"][0]["referencia_secreto"] == "~/.ssh/config#vps"


def test_un_subdirectorio_cuenta_como_estar_dentro_del_proyecto(con):
    """Nadie ejecuta un comando desde la raíz del repo: se trabaja dentro."""
    _con_proyectos(con, {"facturador": ["/casa/facturador"]})
    conexiones.sincronizar(con, [Conexion(alias="vps", proyectos=["facturador"])])

    r = api.conexiones_concedidas(con, "/casa/facturador/apps/backend/src")

    assert r["proyecto_id"] == "facturador" and len(r["conexiones"]) == 1


def test_la_concesion_es_lo_que_reparte_no_el_hecho_de_preguntar(con):
    """🔴 El corazón de esto: preguntar desde dentro de un proyecto NO basta.

    Si estar en el directorio bastara, la lista `proyectos:` no concedería nada
    y cualquier sesión vería todos los servidores del usuario.
    """
    _con_proyectos(con, {"facturador": ["/casa/facturador"],
                         "tienda": ["/casa/tienda"]})
    conexiones.sincronizar(con, [Conexion(alias="vps", proyectos=["facturador"])])

    assert api.conexiones_concedidas(con, "/casa/tienda") == {
        "proyecto_id": "tienda", "conexiones": []
    }


def test_no_se_puede_pedir_la_conexion_de_otro_proyecto_por_su_nombre(con):
    """El id de un proyecto no es un secreto: está en la UI y en el YAML.

    Por eso la función no acepta un proyecto —sólo una ruta— y pasarle el id
    como si fuera un directorio no atribuye nada.
    """
    _con_proyectos(con, {"facturador": ["/casa/facturador"]})
    conexiones.sincronizar(con, [Conexion(alias="vps", proyectos=["facturador"])])

    assert api.conexiones_concedidas(con, "facturador")["proyecto_id"] is None


def test_desde_fuera_de_todo_proyecto_no_hay_nada_que_repartir(con):
    _con_proyectos(con, {"facturador": ["/casa/facturador"]})
    conexiones.sincronizar(con, [Conexion(alias="vps", proyectos=["facturador"])])

    for ruta in ("/tmp", "/casa", "/casa/facturador-viejo", ""):
        assert api.conexiones_concedidas(con, ruta) == {
            "proyecto_id": None, "conexiones": []
        }, ruta


def test_gana_la_ruta_mas_especifica_igual_que_para_los_paneles(con):
    """Mismo criterio que reparte paneles, y a propósito: si aquí ganara otra
    ruta, el mismo directorio sería de un proyecto en /trabajo y de otro en el
    comando, y sólo se notaría el día que se entra al servidor equivocado."""
    _con_proyectos(con, {"taller": ["/casa/dev"],
                         "tienda": ["/casa/dev/tienda"]})
    conexiones.sincronizar(con, [
        Conexion(alias="vps-taller", proyectos=["taller"]),
        Conexion(alias="vps-tienda", proyectos=["tienda"]),
    ])

    r = api.conexiones_concedidas(con, "/casa/dev/tienda/src")
    assert [c["alias"] for c in r["conexiones"]] == ["vps-tienda"]


def test_atribuye_por_cualquiera_de_las_rutas_del_proyecto_no_solo_el_asiento(con):
    """Un proyecto puede orquestarse desde /mnt/c con su código en ~/dev: si sólo
    valiera el asiento, preguntar desde el repo no encontraría nada."""
    _con_proyectos(con, {"facturador": ["/mnt/c/proyectos/facturador",
                                        "/casa/dev/facturador-back"]})
    conexiones.sincronizar(con, [Conexion(alias="vps", proyectos=["facturador"])])

    r = api.conexiones_concedidas(con, "/casa/dev/facturador-back")
    assert r["proyecto_id"] == "facturador" and len(r["conexiones"]) == 1


def test_lo_que_viaja_es_el_puntero_y_el_estado_del_puntero(con, tmp_path):
    """Nunca la credencial: en la base no hay ninguna, y aquí se comprueba que
    lo que sale es la dirección y si esa dirección existe."""
    archivo = tmp_path / "config"
    archivo.write_text("Host vps\n", encoding="utf-8")
    _con_proyectos(con, {"facturador": ["/casa/facturador"]})
    conexiones.sincronizar(con, [
        Conexion(alias="vps", proyectos=["facturador"],
                 referencia_secreto=f"{archivo}#vps"),
    ])

    c = api.conexiones_concedidas(con, "/casa/facturador")["conexiones"][0]

    assert c["referencia_secreto"] == f"{archivo}#vps"
    assert c["puntero_ok"] == 1
    assert "Host vps" not in str(c)  # el archivo se comprueba, no se abre
