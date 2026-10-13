"""El tercer agente: de la maqueta al sistema (decisión 244).

Lo que se fija aquí es dónde están las puertas —quién puede abrirlo y sobre
qué— y qué NO hace: no ve contraseñas, no sale de su carpeta, y la maqueta
que le sirve de especificación no se toca.
"""

from __future__ import annotations

import json

import pytest

from hub import config, constructor, db, encargos, implementador


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "hub.db")
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    yield con
    con.close()


@pytest.fixture
def escena(con):
    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.editar_persona(con, 77, estado="activo", alias="Rosa")
    encargos.anotar_persona(con, 1, "eldueno", "El Dueño")
    encargos.marcar_dueno(con, 1)
    encargos.crear(con, "encargo-1", 77)
    con.commit()
    return con


@pytest.fixture
def maqueta_publicada(escena):
    sitio = constructor.sitio("encargo-1")
    sitio.mkdir(parents=True, exist_ok=True)
    (sitio / "index.html").write_text("<main>Citas de hoy</main>", encoding="utf-8")
    (sitio / "clientas.html").write_text("<main>Clientas</main>", encoding="utf-8")
    (sitio / "estilo.css").write_text(":root{}", encoding="utf-8")
    encargos.tocar(escena, "encargo-1", estado="publicado", url="https://encargo-1.test")
    escena.commit()
    return escena


def test_preparar_copia_la_maqueta_a_static_y_deja_el_arranque(maqueta_publicada):
    destino = implementador.preparar(maqueta_publicada, "encargo-1")

    assert (destino / "static" / "index.html").is_file()
    assert (destino / "static" / "clientas.html").is_file()
    assert (destino / "static" / "estilo.css").is_file()
    main = (destino / "main.py").read_text(encoding="utf-8")
    assert "DATOS" in main and "StaticFiles" in main and "/salud" in main
    contrato = (encargos.carpeta("encargo-1") / "INSTRUCCIONES-IMPLEMENTAR.md").read_text(encoding="utf-8")
    assert "localStorage" in contrato and "curl" in contrato and "Nada de acceso" in contrato
    # La maqueta sigue intacta: es la especificación.
    assert (constructor.sitio("encargo-1") / "index.html").is_file()


def test_preparar_no_pisa_lo_que_el_agente_ya_escribio(maqueta_publicada):
    destino = implementador.preparar(maqueta_publicada, "encargo-1")
    (destino / "main.py").write_text("# lo mío", encoding="utf-8")
    (destino / "static" / "index.html").write_text("<main>ya con fetch</main>", encoding="utf-8")

    implementador.preparar(maqueta_publicada, "encargo-1")

    assert (destino / "main.py").read_text(encoding="utf-8") == "# lo mío"
    assert "fetch" in (destino / "static" / "index.html").read_text(encoding="utf-8")


def test_sin_maqueta_no_hay_que_implementar(escena):
    encargos.tocar(escena, "encargo-1", estado="publicado")
    with pytest.raises(ValueError, match="no tiene maqueta"):
        implementador.preparar(escena, "encargo-1")


def test_empezar_solo_sobre_una_maqueta_publicada(escena, monkeypatch):
    monkeypatch.setattr(implementador, "abrir_agente", lambda c, e: {"pane_id": "%1"})
    for estado in ("recogiendo", "construyendo", "construido"):
        encargos.tocar(escena, "encargo-1", estado=estado)
        with pytest.raises(ValueError, match="no es una maqueta publicada"):
            implementador.empezar(escena, "encargo-1")


def test_empezar_cambia_la_etapa_cierra_agentes_y_abre_el_implementador(maqueta_publicada, monkeypatch):
    from hub import entrevistador

    pasos = []
    monkeypatch.setattr(entrevistador, "cerrar_agentes", lambda c, e: pasos.append("cerrar") or [])
    monkeypatch.setattr(implementador, "abrir_agente", lambda c, e: pasos.append("abrir") or {"pane_id": "%1"})

    implementador.empezar(maqueta_publicada, "encargo-1")

    fila = encargos.ver(maqueta_publicada, "encargo-1")
    assert fila["etapa"] == "sistema" and fila["estado"] == "aprobado" and fila["plan_msg"] is None
    assert pasos == ["cerrar", "abrir"]
    # Y no se puede empezar dos veces: ya no es maqueta.
    with pytest.raises(ValueError):
        implementador.empezar(maqueta_publicada, "encargo-1")


def test_abrir_el_implementador_exige_etapa_sistema(maqueta_publicada):
    with pytest.raises(ValueError, match="etapa maqueta"):
        implementador.abrir_agente(maqueta_publicada, "encargo-1")


def test_el_acceso_deja_el_hash_y_devuelve_la_contrasena_una_sola_vez(escena):
    import bcrypt

    assert not implementador.tiene_acceso("encargo-1")
    clave = implementador.generar_acceso("encargo-1")

    assert len(clave) >= 10
    hash_ = (encargos.carpeta("encargo-1") / implementador.ACCESO).read_text(encoding="utf-8").strip()
    assert hash_.startswith("$2") and clave not in hash_
    assert bcrypt.checkpw(clave.encode(), hash_.encode())
    assert implementador.tiene_acceso("encargo-1")
    # Regla dura 5: en ningún archivo del encargo queda la contraseña.
    for archivo in encargos.carpeta("encargo-1").rglob("*"):
        if archivo.is_file():
            assert clave not in archivo.read_text(encoding="utf-8", errors="replace")


def test_acotar_le_da_curl_y_le_niega_el_hub(escena, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    carpeta = encargos.carpeta("encargo-1")
    implementador.acotar(carpeta)
    reglas = json.loads((carpeta / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert "Bash(curl:*)" in reglas["allow"]
    assert any(r.startswith("Read(//") and "hub" in r for r in reglas["deny"])
    assert not any("bypass" in r for r in reglas["allow"])


def test_el_arranque_generado_sirve_de_verdad(maqueta_publicada, tmp_path, monkeypatch):
    """No es un texto: `main.py` tiene que importar y contestar /salud con la
    base en DATOS, porque es lo que el agente extiende y lo que la imagen corre."""
    import importlib.util
    import sys

    destino = implementador.preparar(maqueta_publicada, "encargo-1")
    monkeypatch.setenv("DATOS", str(tmp_path / "datos"))
    spec = importlib.util.spec_from_file_location("app_de_prueba", destino / "main.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["app_de_prueba"] = spec.loader and spec.loader.exec_module(modulo) or modulo

    from fastapi.testclient import TestClient

    cliente = TestClient(modulo.app)
    assert cliente.get("/salud").json() == {"ok": True}
    assert "Citas de hoy" in cliente.get("/").text
    assert (tmp_path / "datos" / "app.db").is_file()
