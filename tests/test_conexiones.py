"""Conexiones: punteros a credenciales, nunca credenciales.

Regla dura 5 y decisión 28. Un índice de proyectos que empieza a guardar
secretos multiplica el radio de daño de cualquier fallo, así que aquí se prueba
sobre todo lo que el módulo **no** debe hacer.
"""

from __future__ import annotations

from hub import conexiones, registry
from hub.models import Conexion


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
