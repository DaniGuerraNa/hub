"""Inventario de capacidades y medición de deriva de kits.

Lo que importa aquí es que el dato sea honesto: una medida equivocada de "esto
no se usa" o "esto no ha derivado" es peor que no tener el dato, porque se actúa
sobre ella.
"""

from __future__ import annotations

import pytest

from hub import catalogo
from hub.models import Proyecto, Ruta


def _escribir(ruta, texto=""):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


@pytest.fixture
def proyecto(tmp_path):
    raiz = tmp_path / "demo"
    _escribir(raiz / ".claude/agents/dev-backend.md",
              "---\nname: dev-backend\ndescription: >\n  Implementador\n  backend.\nmodel: opus\n---\n\n# Cuerpo\n")
    _escribir(raiz / ".claude/agents/sin-frontmatter.md", "# Sólo cuerpo\n")
    _escribir(raiz / ".claude/skills/local-db/SKILL.md",
              "---\nname: local-db\ndescription: Levanta la DB local.\n---\n")
    _escribir(raiz / ".claude/skills/vacia/SKILL.md", "")
    return Proyecto(id="demo", nombre="Demo", asiento=str(raiz))


def test_encuentra_agentes_y_skills_por_convencion(proyecto):
    caps = catalogo.capacidades_de(proyecto)
    por_nombre = {c["nombre"]: c for c in caps}

    assert por_nombre["dev-backend"]["tipo"] == "agente"
    assert por_nombre["dev-backend"]["modelo"] == "opus"
    assert por_nombre["dev-backend"]["descripcion"] == "Implementador backend."
    assert por_nombre["local-db"]["tipo"] == "skill"


def test_un_archivo_sin_frontmatter_usa_su_nombre_de_fichero(proyecto):
    caps = {c["nombre"] for c in catalogo.capacidades_de(proyecto)}
    assert "sin-frontmatter" in caps


def test_una_skill_vacia_se_marca_incompleta(proyecto):
    """SKILL.md de 0 bytes fue deuda real: no puede aparecer como sana."""
    caps = {c["nombre"]: c for c in catalogo.capacidades_de(proyecto)}
    assert caps["vacia"]["status"] == "incompleto"
    assert caps["local-db"]["status"] == "activo"


def test_no_duplica_cuando_una_ruta_esta_dos_veces(tmp_path):
    raiz = tmp_path / "demo"
    _escribir(raiz / ".claude/agents/uno.md", "---\nname: uno\n---\n")
    p = Proyecto(id="demo", nombre="Demo", asiento=str(raiz), rutas=[Ruta(ruta=str(raiz))])
    assert len(catalogo.capacidades_de(p)) == 1


# ───────────────────────── deriva de kits ─────────────────────────


@pytest.fixture
def kit_y_consumidor(tmp_path):
    kit = tmp_path / "kit"
    consumidor = tmp_path / "cons"

    _escribir(kit / "metodo/igual.md", "mismo contenido")
    _escribir(consumidor / "docs/igual.md", "mismo contenido")

    _escribir(kit / "metodo/cambiado.md", "original")
    _escribir(consumidor / "docs/cambiado.md", "MODIFICADO en el consumidor")

    _escribir(kit / "herramientas/declarado.sh", "generico")
    _escribir(consumidor / "tools/declarado.sh", "adaptado al motor")

    _escribir(kit / "metodo/ausente.md", "existe sólo en el kit")

    _escribir(kit / "consumidores/cons.md", f"""
RUTA: {consumidor}

MAPA: metodo/igual.md -> docs/igual.md
MAPA: metodo/cambiado.md -> docs/cambiado.md
MAPA: herramientas/declarado.sh -> tools/declarado.sh
MAPA: metodo/ausente.md -> docs/ausente.md

DIVERGE: tools/declarado.sh # Conoce el motor del consumidor. Es una decisión.
""")
    kit_p = Proyecto(id="kit", nombre="Kit", tipo="kit", asiento=str(kit))
    cons_p = Proyecto(id="cons", nombre="Consumidor", asiento=str(consumidor))
    return kit_p, [kit_p, cons_p]


def test_mide_la_deriva_archivo_por_archivo(kit_y_consumidor):
    """«Debería estar igual» no es una medida: se compara el contenido."""
    kit, proyectos = kit_y_consumidor
    enlaces, _ = catalogo.dependencias_de_kit(kit, proyectos)
    estado = {e["destino"]: e["estado"] for e in enlaces}

    assert estado["docs/igual.md"] == "igual"
    assert estado["docs/cambiado.md"] == "difiere"
    assert estado["docs/ausente.md"] == "falta"


def test_una_divergencia_declarada_no_cuenta_como_deriva(kit_y_consumidor):
    """Son decisiones, no defectos: no deben ensuciar la señal."""
    kit, proyectos = kit_y_consumidor
    enlaces, divergencias = catalogo.dependencias_de_kit(kit, proyectos)
    estado = {e["destino"]: e["estado"] for e in enlaces}

    assert estado["tools/declarado.sh"] == "divergencia-declarada"
    assert divergencias[0]["archivo"] == "tools/declarado.sh"
    assert "decisión" in divergencias[0]["razon"]


def test_resuelve_el_consumidor_por_su_ruta(kit_y_consumidor):
    kit, proyectos = kit_y_consumidor
    enlaces, _ = catalogo.dependencias_de_kit(kit, proyectos)
    assert {e["consumidor_id"] for e in enlaces} == {"cons"}


# ───────────────────────── medición de uso ─────────────────────────


def test_los_metodos_no_se_miden_por_nombre():
    """Un método es un documento que se lee: medirlo así lo marcaría olvidado siempre."""
    assert catalogo.patron_de_uso({"tipo": "metodo", "nombre": "x", "ruta": "/a/x.md"}) is None


def test_agentes_y_skills_se_buscan_entrecomillados():
    patron = catalogo.patron_de_uso({"tipo": "agente", "nombre": "dev-backend", "ruta": "/a.md"})
    assert patron == '"dev-backend"'


def test_los_scripts_se_buscan_por_nombre_de_fichero():
    """`mutar.py` y `mutar.sh` comparten nombre y no son lo mismo."""
    p1 = catalogo.patron_de_uso({"tipo": "script", "nombre": "mutar", "ruta": "/k/mutar.py"})
    p2 = catalogo.patron_de_uso({"tipo": "script", "nombre": "mutar", "ruta": "/k/mutar.sh"})
    assert p1 == "mutar.py" and p2 == "mutar.sh"


def test_el_buscador_cae_a_grep_si_no_hay_ripgrep(monkeypatch):
    """`rg` era un alias del shell: `subprocess` no lo veía y la medición se saltaba."""
    monkeypatch.setattr(catalogo.shutil, "which", lambda x: None if x == "rg" else "/bin/grep")
    assert catalogo.buscador()[0] == "grep"

    monkeypatch.setattr(catalogo.shutil, "which", lambda x: f"/usr/bin/{x}")
    assert catalogo.buscador()[0] == "rg"

    monkeypatch.setattr(catalogo.shutil, "which", lambda x: None)
    assert catalogo.buscador() is None


def test_sin_buscador_no_se_inventa_uso(monkeypatch):
    monkeypatch.setattr(catalogo, "buscador", lambda: None)
    assert catalogo.medir_uso([{"tipo": "agente", "nombre": "x", "ruta": "/a"}]) == {}


def test_un_reescaneo_rapido_no_borra_la_medicion_de_uso(con, proyecto, monkeypatch):
    """Borrarla dejaría todo como «sin uso detectado», que se lee como olvidado."""
    monkeypatch.setattr(catalogo, "medir_uso",
                        lambda caps: {c["ruta"]: "2026-08-01T00:00:00+00:00" for c in caps})
    catalogo.escanear(con, [proyecto], medir=True)
    medidas = con.execute("SELECT COUNT(*) c FROM capacidad WHERE usado IS NOT NULL").fetchone()["c"]
    assert medidas > 0

    # Reescaneo rápido: no vuelve a medir, pero tampoco olvida.
    monkeypatch.setattr(catalogo, "medir_uso", lambda caps: {})
    catalogo.escanear(con, [proyecto], medir=False)
    assert con.execute(
        "SELECT COUNT(*) c FROM capacidad WHERE usado IS NOT NULL"
    ).fetchone()["c"] == medidas


def test_el_inventario_dice_cuando_se_escaneo(con, tmp_path):
    """🔴 Una foto vieja y una recién medida se veían idénticas.

    «0 sin uso detectado» significa cosas muy distintas si el escaneo es de hoy
    o de antes de escribir media docena de skills, y la pantalla no daba forma
    de saber cuál de las dos estaba enseñando. `repo` y `servicio` ya llevaban
    su `medido_en`; `capacidad` no.
    """
    from hub import api, catalogo
    from hub.models import Proyecto

    raiz = tmp_path / "proy"
    (raiz / ".claude" / "skills" / "saludar").mkdir(parents=True)
    (raiz / ".claude" / "skills" / "saludar" / "SKILL.md").write_text(
        "---\nname: saludar\ndescription: di hola\n---\n", encoding="utf-8"
    )
    p = Proyecto(id="proy", nombre="Proy", dominio="personal", asiento=str(raiz))
    con.execute(
        "INSERT INTO proyecto (id,nombre,dominio,tipo) VALUES ('proy','Proy','personal','proyecto')"
    )

    antes = api.inventario(con)
    assert antes["medido_en"] is None, "sin escanear no puede haber fecha"

    catalogo.escanear(con, [p])
    despues = api.inventario(con)
    assert despues["total"] >= 1
    assert despues["medido_en"], "escaneó y no dejó marca de cuándo"
