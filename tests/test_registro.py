"""projects.yml manda sobre el índice, y la atribución usa la ruta más específica."""

from __future__ import annotations

from pathlib import Path

import pytest

from hub import api, registry
from hub.registry import Atribuidor

YAML_DEMO = """
proyectos:
  - id: facturador
    nombre: Facturador
    asiento: /mnt/c/proyects/facturador-main
    rutas:
      - ruta: /home/ana/dev/facturador
      - ruta: /home/ana/dev/facturador-front
  - id: idle
    nombre: Idle
    dominio: personal
    asiento: /mnt/c/proyects/Idle
"""


@pytest.fixture
def yaml_demo(tmp_path) -> Path:
    ruta = tmp_path / "projects.yml"
    ruta.write_text(YAML_DEMO, encoding="utf-8")
    return ruta


def test_carga_asiento_y_repos(yaml_demo):
    proyectos = registry.cargar(yaml_demo)
    facturador = next(p for p in proyectos if p.id == "facturador")
    assert facturador.asiento == "/mnt/c/proyects/facturador-main"
    assert len(facturador.todas_las_rutas()) == 3


def test_sincronizar_refleja_altas_y_bajas(con, yaml_demo):
    registry.sincronizar(con, registry.cargar(yaml_demo))
    assert len(api.listar_proyectos(con)) == 2

    # El YAML manda: lo que desaparece de ahí, desaparece del índice.
    yaml_demo.write_text(
        "proyectos:\n  - id: idle\n    nombre: Idle\n", encoding="utf-8"
    )
    registry.sincronizar(con, registry.cargar(yaml_demo))
    assert [p["id"] for p in api.listar_proyectos(con)] == ["idle"]


def test_un_registro_que_no_cambia_no_se_vuelve_a_escribir(con, yaml_demo):
    """C-0275: el latido re-sincronizaba cada 20 s en autocommit —un `INSERT`,
    un `DELETE` y un `INSERT` por ruta, cada uno su transacción—: ~350 filas y
    1,6 MB de WAL por ciclo para reescribir lo mismo."""
    registry.sincronizar(con, registry.cargar(yaml_demo))
    antes = con.total_changes
    assert registry.sincronizar(con, registry.cargar(yaml_demo)) is False
    assert con.total_changes == antes


def test_un_cambio_en_el_registro_se_sigue_reflejando(con, yaml_demo):
    """Saltarse lo que no cambia no puede dejar fuera lo que sí: un nombre o
    una ruta nuevos entran en la vuelta siguiente (regla dura 1)."""
    registry.sincronizar(con, registry.cargar(yaml_demo))
    yaml_demo.write_text(
        YAML_DEMO.replace("Facturador", "Facturas").replace(
            "facturador-front", "facturador-web"), encoding="utf-8")

    assert registry.sincronizar(con, registry.cargar(yaml_demo)) is True
    assert api.obtener_proyecto(con, "facturador")["nombre"] == "Facturas"
    rutas = {f["ruta"] for f in con.execute(
        "SELECT ruta FROM proyecto_ruta WHERE proyecto_id='facturador'")}
    assert "/home/ana/dev/facturador-web" in rutas
    assert "/home/ana/dev/facturador-front" not in rutas


def test_quien_lee_mientras_se_sincroniza_ve_todas_las_rutas(con, yaml_demo, tmp_path):
    """Entre el `DELETE FROM proyecto_ruta` y sus `INSERT` un proyecto se
    quedaba sin rutas a ojos de cualquier otra conexión: la misma lectura rota
    que la C-0234 cerró para la muestra. Ahora entra de una vez."""
    from hub import db

    registry.sincronizar(con, registry.cargar(yaml_demo))
    otra = db.conectar(tmp_path / "hub.db")
    vistos = []

    def al_escribir(sql):
        if "proyecto_ruta" in sql:
            vistos.append(otra.execute(
                "SELECT COUNT(*) FROM proyecto_ruta WHERE proyecto_id='facturador'").fetchone()[0])

    yaml_demo.write_text(YAML_DEMO.replace("Facturador", "Facturas"), encoding="utf-8")
    con.set_trace_callback(al_escribir)
    registry.sincronizar(con, registry.cargar(yaml_demo))
    con.set_trace_callback(None)
    otra.close()
    assert vistos and all(n == 3 for n in vistos), vistos


def test_atribucion_prefiere_la_ruta_mas_larga(yaml_demo):
    """~/dev/facturador-front no debe caer en ~/dev/facturador."""
    atribuidor = Atribuidor(registry.cargar(yaml_demo))
    assert atribuidor.atribuir("/home/ana/dev/facturador-front/apps/web") == "facturador"
    assert atribuidor.atribuir("/home/ana/dev/facturador/apps") == "facturador"
    assert atribuidor.atribuir("/mnt/c/proyects/Idle") == "idle"


def test_atribucion_no_confunde_prefijos_parciales(yaml_demo):
    atribuidor = Atribuidor(registry.cargar(yaml_demo))
    assert atribuidor.atribuir("/home/ana/dev/facturador-otro-repo") is None
    assert atribuidor.atribuir("/home/ana/otra-cosa") is None


def test_un_patron_en_rutas_se_expande_a_los_repos_git_que_existen(tmp_path):
    """Un workspace que contiene repos los declara con `patron:`, no uno a uno."""
    ws = tmp_path / "workspace"
    for nombre in ("ext/repos/a", "ext/repos/b", "int/repos/c", "ext/repos/sin-git"):
        (ws / nombre).mkdir(parents=True)
    (ws / "ext/repos/a/.git").mkdir()
    (ws / "int/repos/c/.git").write_text("gitdir: /otro/sitio")   # un worktree
    (ws / "ext/repos/b/.git").mkdir()
    (ws / "ext/repos/archivo.txt").write_text("no soy un repo")
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    [p] = registry.cargar(yml)
    assert [Path(r.ruta).relative_to(ws).as_posix() for r in p.rutas] == [
        "ext/repos/a", "ext/repos/b", "int/repos/c",
    ]
    assert all(r.tipo == "repo" for r in p.rutas)
    assert p.todas_las_rutas()[-1] == str(ws)


def test_un_patron_sin_coincidencias_no_es_error(tmp_path):
    """Un workspace recién instalado está vacío a propósito: cero rutas, no un fallo."""
    ws = tmp_path / "vacio"
    ws.mkdir()
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    [p] = registry.cargar(yml)
    assert p.rutas == []


def test_una_carpeta_que_no_se_puede_leer_no_tumba_el_registro(tmp_path, monkeypatch, capsys):
    """Medido el 7-nov: OneDrive dejó una carpeta en EIO y `is_dir()` lanzó en
    vez de decir que no. `cargar` lo usa todo el hub —el snapshotter dejó de
    latir y avisó «hub callado»—, así que un proyecto ilegible se queda sin esas
    rutas y se dice en voz alta (reglas duras 2 y 21); los demás cargan."""
    ws = tmp_path / "onedrive"
    ws.mkdir()
    otro = tmp_path / "otro"
    otro.mkdir()
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
  - id: otro
    nombre: Otro
    asiento: {otro}
""", encoding="utf-8")
    original = Path.stat

    def stat_que_falla(self, *a, **k):
        if str(self).startswith(str(ws)):
            raise OSError(5, "Input/output error", str(self))
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat_que_falla)
    trabajo, segundo = registry.cargar(yml)
    assert (trabajo.id, trabajo.rutas, segundo.id) == ("trabajo", [], "otro")
    assert "no se puede leer" in capsys.readouterr().out


def test_un_patron_relativo_sin_asiento_se_rechaza(tmp_path):
    yml = tmp_path / "projects.yml"
    yml.write_text("""
proyectos:
  - id: trabajo
    nombre: Trabajo
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    with pytest.raises(registry.YamlInvalido, match="asiento"):
        registry.cargar(yml)


# ── La expansión de un patrón se recuerda un minuto; el YAML no (C-0415) ─────
#
# Expandir `*/repos/*` sobre el disco de Windows eran 0,48 de los 0,53 s de
# `cargar`, y lo pagaban el latido, el secretario y la portada. Se recuerda
# sólo lo que encuentra el patrón; `projects.yml` se lee siempre, para que un
# guardrail cambiado valga en la llamada siguiente (regla dura 7).


@pytest.fixture
def reloj(monkeypatch):
    from hub import recordar

    ahora = [1000.0]
    monkeypatch.setattr(recordar.time, "monotonic", lambda: ahora[0])
    return ahora


@pytest.fixture
def globs(monkeypatch):
    """Cada vez que alguien recorre el disco con un patrón."""
    vistos: list[str] = []
    original = Path.glob

    def contando(self, *a, **k):
        vistos.append(str(self))
        return original(self, *a, **k)
    monkeypatch.setattr(Path, "glob", contando)
    return vistos


def _clonar(ws: Path, nombre: str) -> None:
    (ws / "ext" / "repos" / nombre / ".git").mkdir(parents=True)


def _con_patron(tmp_path, ws: Path, *, guardrail: str = "ask", patron: bool = True) -> Path:
    yml = tmp_path / "projects.yml"
    rutas = '    rutas:\n      - patron: "*/repos/*"\n' if patron else ""
    yml.write_text(f"proyectos:\n  - id: trabajo\n    asiento: {ws}\n"
                   f"    guardrail: {guardrail}\n{rutas}", encoding="utf-8")
    return yml


def _repos(proyecto, ws: Path) -> list[str]:
    return [Path(r.ruta).relative_to(ws).as_posix() for r in proyecto.rutas]


def test_la_expansion_de_un_patron_no_vuelve_al_disco_dentro_del_plazo(tmp_path, reloj, globs):
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    [p] = registry.cargar(yml)
    assert (_repos(p, ws), len(globs)) == (["ext/repos/a"], 1)
    reloj[0] += registry.PLAZO_PATRON - 0.1
    [p] = registry.cargar(yml)
    assert (_repos(p, ws), len(globs)) == (["ext/repos/a"], 1)


def test_un_repo_clonado_bajo_el_patron_aparece_al_pasar_el_plazo(tmp_path, reloj):
    """Lo aceptó el dueño el 13-nov: hasta un minuto, y ni un segundo más."""
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    registry.cargar(yml)
    _clonar(ws, "b")
    [p] = registry.cargar(yml)
    assert _repos(p, ws) == ["ext/repos/a"]
    reloj[0] += registry.PLAZO_PATRON
    [p] = registry.cargar(yml)
    assert _repos(p, ws) == ["ext/repos/a", "ext/repos/b"]


def test_un_guardrail_cambiado_en_el_yaml_vale_en_la_llamada_siguiente(tmp_path, reloj):
    """Regla dura 7: `never` es nunca desde que se escribe, sin plazo que esperar."""
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws, guardrail="ask")
    assert registry.cargar(yml)[0].guardrail == "ask"
    _con_patron(tmp_path, ws, guardrail="never")
    [p] = registry.cargar(yml)
    assert (p.guardrail, _repos(p, ws)) == ("never", ["ext/repos/a"])


def test_quitar_el_patron_del_yaml_lo_quita_en_la_llamada_siguiente(tmp_path, reloj):
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    assert _repos(registry.cargar(yml)[0], ws) == ["ext/repos/a"]
    _con_patron(tmp_path, ws, patron=False)
    assert registry.cargar(yml)[0].rutas == []


def test_estricto_expande_en_fresco_y_no_toca_lo_recordado(tmp_path, reloj, globs):
    """Quien protege con el registro (`orden_pc.rutas_vetadas`) no se fía de lo
    recordado (decisión 410): ni lo lee ni lo escribe."""
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    registry.cargar(yml)
    _clonar(ws, "b")
    [p] = registry.cargar(yml, estricto=True)
    assert _repos(p, ws) == ["ext/repos/a", "ext/repos/b"]
    # Lo recordado sigue siendo lo de antes: el estricto no lo pisó.
    [p] = registry.cargar(yml)
    assert (_repos(p, ws), len(globs)) == (["ext/repos/a"], 2)

    from hub import recordar
    recordar.olvidar()
    registry.cargar(yml, estricto=True)
    registry.cargar(yml)
    assert len(globs) == 4, "lo que expandió el estricto no lo aprovecha nadie"


def test_un_patron_que_no_se_pudo_leer_no_se_recuerda(tmp_path, reloj, monkeypatch):
    import errno

    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    original = Path.glob
    roto = [True]

    def glob_que_falla(self, *a, **k):
        if roto[0] and str(self).startswith(str(ws)):
            raise OSError(errno.EIO, "Input/output error", str(self))
        return original(self, *a, **k)
    monkeypatch.setattr(Path, "glob", glob_que_falla)
    assert registry.cargar(yml)[0].rutas == []
    roto[0] = False
    assert _repos(registry.cargar(yml)[0], ws) == ["ext/repos/a"]


def test_mutar_las_rutas_devueltas_no_cambia_la_llamada_siguiente(tmp_path, reloj):
    from hub.models import Ruta

    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    [p] = registry.cargar(yml)
    p.rutas[0].ruta = "/otra/cosa"
    p.rutas.append(Ruta(ruta="/y/otra"))
    assert _repos(registry.cargar(yml)[0], ws) == ["ext/repos/a"]


def test_dos_asientos_con_el_mismo_patron_no_se_pisan(tmp_path, reloj):
    uno, dos = tmp_path / "uno", tmp_path / "dos"
    _clonar(uno, "a")
    _clonar(dos, "b")
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: uno
    asiento: {uno}
    rutas:
      - patron: "*/repos/*"
  - id: dos
    asiento: {dos}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    p_uno, p_dos = registry.cargar(yml)
    assert (_repos(p_uno, uno), _repos(p_dos, dos)) == (["ext/repos/a"], ["ext/repos/b"])


# ── Lo que no se pudo leer no es «no hay» (C-0435) ───────────────────────────
#
# Con OneDrive a medio sincronizar, expandir el patrón da EIO. El proyecto se
# quedaba sin rutas y el escaneo siguiente borraba sus filas de respaldo. La
# última expansión buena no es lo recordado un minuto: no caduca, sólo se
# sirve cuando el disco falla, y no cuenta como lectura (se reintenta).


@pytest.fixture
def disco_roto(monkeypatch):
    """Las raíces que se añadan dan EIO al recorrerlas."""
    import errno

    rotas: set[str] = set()
    original = Path.glob

    def glob(self, *a, **k):
        if any(str(self).startswith(r) for r in rotas):
            raise OSError(errno.EIO, "Input/output error", str(self))
        return original(self, *a, **k)
    monkeypatch.setattr(Path, "glob", glob)
    return rotas


def test_con_el_disco_en_eio_se_sirve_la_ultima_expansion_buena_y_se_marca(tmp_path, reloj, disco_roto):
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    registry.cargar(yml)
    reloj[0] += registry.PLAZO_PATRON * 10   # mucho después: la última buena no caduca
    disco_roto.add(str(ws))
    [p] = registry.cargar(yml)
    assert (_repos(p, ws), p.patrones_sin_leer) == (["ext/repos/a"], ["*/repos/*"])


def test_sin_una_lectura_buena_anterior_el_proyecto_queda_sin_rutas_y_marcado(tmp_path, reloj, disco_roto):
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    disco_roto.add(str(ws))
    [p] = registry.cargar(yml)
    assert (p.rutas, p.patrones_sin_leer) == ([], ["*/repos/*"])


def test_servir_la_ultima_buena_no_la_renueva_y_el_disco_se_reintenta(tmp_path, reloj, disco_roto):
    """En cuanto el disco responde manda lo que hay ahora, sin esperar el plazo."""
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    registry.cargar(yml)
    reloj[0] += registry.PLAZO_PATRON
    disco_roto.add(str(ws))
    registry.cargar(yml)
    disco_roto.clear()
    _clonar(ws, "b")
    [p] = registry.cargar(yml)
    assert (_repos(p, ws), p.patrones_sin_leer) == (["ext/repos/a", "ext/repos/b"], [])


def test_un_patron_ilegible_se_dice_una_vez_por_racha(tmp_path, reloj, disco_roto, capsys):
    """Regla 21 sin ruido: el latido lee el registro cada 20 s, y una racha de
    OneDrive dura horas."""
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    disco_roto.add(str(ws))
    for _ in range(3):
        registry.cargar(yml)
    assert capsys.readouterr().out.count("no se puede leer") == 1
    disco_roto.clear()
    registry.cargar(yml)
    assert capsys.readouterr().out.count("vuelve a leerse") == 1
    reloj[0] += registry.PLAZO_PATRON
    disco_roto.add(str(ws))
    registry.cargar(yml)
    assert "no se puede leer" in capsys.readouterr().out, "una racha nueva se dice otra vez"


def test_estricto_no_sirve_la_ultima_buena_y_falla_cerrado(tmp_path, reloj, disco_roto):
    """Ni con lo recordado fresco: quien protege con esto no saber es no dejar."""
    ws = tmp_path / "ws"
    _clonar(ws, "a")
    yml = _con_patron(tmp_path, ws)
    registry.cargar(yml)
    disco_roto.add(str(ws))
    with pytest.raises(OSError):
        registry.cargar(yml, estricto=True)


# ── La sección escrita en línea (`conexiones: []`) ────────────────────────────
#
# 🔴 Este bloque cubre el fallo que dejó el hub entero sin registro, y era de
# PRIMER USO: la plantilla que se publica trae `conexiones: []` —vacía a
# propósito— y `_insertar_bajo_cerrojo` buscaba una línea **exactamente igual**
# a `conexiones:`. Como no casaba, se caía a «no existe la sección» y añadía
# otra al final: clave duplicada. A partir de ahí `projects.yml` no carga, y con
# él se caen el snapshotter, el asistente y todo lo que pida el registro.
#
# Lo que lo dejó pasar fue la comprobación previa: usaba `yaml.safe_load`, que
# admite claves duplicadas en silencio y se queda con la última. Un validador
# más laxo que el lector no valida nada.

PLANTILLA_CON_SECCION_EN_LINEA = """proyectos:
  - id: demo
    nombre: Demo
    asiento: /tmp/demo

# Vacío a propósito: las conexiones reales las declara quien usa el hub.
conexiones: []
"""


def _yml(tmp_path, texto):
    ruta = tmp_path / "projects.yml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_la_primera_conexion_sobre_la_plantilla_no_rompe_el_registro(tmp_path):
    """El caso exacto que lo rompió, y le pasaría a cualquiera recién instalado:
    dar de alta la PRIMERA conexión desde la UI."""
    ruta = _yml(tmp_path, PLANTILLA_CON_SECCION_EN_LINEA)
    registry.añadir_conexion({"alias": "VPS", "host": "h", "usuario": "u"}, ruta=ruta)

    assert [c.alias for c in registry.cargar_conexiones(ruta)] == ["VPS"]
    assert [p.id for p in registry.cargar(ruta)] == ["demo"]
    assert ruta.read_text(encoding="utf-8").count("\nconexiones:") == 1, \
        "se escribió una segunda clave `conexiones`"


def test_la_seccion_en_linea_se_abre_conservando_el_comentario(tmp_path):
    """`projects.yml` se edita a mano (decisión 7): su formato es parte de lo que
    lo hace editable, así que abrir la sección no puede llevarse el comentario
    que explica para qué es."""
    ruta = _yml(tmp_path, PLANTILLA_CON_SECCION_EN_LINEA)
    registry.añadir_conexion({"alias": "VPS"}, ruta=ruta)
    texto = ruta.read_text(encoding="utf-8")
    assert "# Vacío a propósito" in texto
    assert "conexiones: []" not in texto


def test_la_segunda_conexion_se_añade_a_la_misma_seccion(tmp_path):
    ruta = _yml(tmp_path, PLANTILLA_CON_SECCION_EN_LINEA)
    registry.añadir_conexion({"alias": "uno"}, ruta=ruta)
    registry.añadir_conexion({"alias": "dos"}, ruta=ruta)
    assert [c.alias for c in registry.cargar_conexiones(ruta)] == ["uno", "dos"]


def test_una_seccion_en_linea_CON_contenido_no_se_reescribe_a_ciegas(tmp_path):
    """Ahí no se puede insertar un bloque sin reescribir el valor, y reescribir
    a ciegas un archivo que alguien edita a mano es peor que decir que no."""
    ruta = _yml(tmp_path, "proyectos: []\nconexiones: [{alias: ya-estaba}]\n")
    with pytest.raises(registry.YamlInvalido) as exc:
        registry.añadir_conexion({"alias": "nueva"}, ruta=ruta)
    assert "una sola línea" in str(exc.value)
    assert "ya-estaba" in ruta.read_text(encoding="utf-8"), "se tocó el archivo"


def test_sobre_un_registro_ya_roto_el_alta_se_niega_en_vez_de_empeorarlo(tmp_path):
    """Con la clave ya duplicada —el estado en que quedó la máquina— añadir otra
    conexión tiene que fallar limpio y no tocar el archivo.

    🔴 Y una nota honesta sobre lo que este test NO prueba: la comprobación
    previa a escribir pasó de `yaml.safe_load` al lector estricto, y quitarla no
    pone ningún test en rojo. Es correcto que sea así —con `_abrir_seccion`
    arreglado ya no hay forma de generar la clave duplicada, así que esa
    comprobación es un segundo cinturón para el próximo que llame a `_insertar`—
    pero no se puede afirmar que esté cubierta: un validador más laxo que el
    lector no valida nada, y eso hoy sólo lo sostiene la lectura del código.
    """
    ruta = _yml(tmp_path, "proyectos: []\nconexiones:\n  - alias: a\n"
                          "conexiones:\n  - alias: b\n")
    antes = ruta.read_text(encoding="utf-8")
    with pytest.raises(registry.YamlInvalido):
        registry.añadir_conexion({"alias": "nueva"}, ruta=ruta)
    assert ruta.read_text(encoding="utf-8") == antes


def test_dar_de_alta_un_proyecto_sobre_una_seccion_en_linea_tampoco_rompe(tmp_path):
    """El mismo `_insertar` sirve a proyectos y a conexiones: si sólo se
    arreglara para una, la otra seguiría rompiendo el registro."""
    ruta = _yml(tmp_path, "proyectos: []\nconexiones: []\n")
    registry.añadir_proyecto({"id": "nuevo", "nombre": "Nuevo",
                              "asiento": "/tmp/nuevo"}, ruta=ruta)
    assert [p.id for p in registry.cargar(ruta)] == ["nuevo"]


def test_el_atribuidor_del_indice_reparte_como_el_del_registro(yaml_demo, tmp_path):
    """`registry.atribuidor` lo arma desde `proyecto_ruta` (C-0102: vivía en
    `api`, y es la decisión de a qué proyecto pertenece una ruta)."""
    from hub import db

    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    proyectos = registry.cargar(yaml_demo)
    registry.sincronizar(con, proyectos)
    del_indice, del_registro = registry.atribuidor(con), Atribuidor(proyectos)
    for ruta in ("/home/ana/dev/facturador-front/apps/web", "/mnt/c/proyects/Idle", "/home/ana/otra-cosa"):
        assert del_indice.atribuir(ruta) == del_registro.atribuir(ruta), ruta
    con.close()
