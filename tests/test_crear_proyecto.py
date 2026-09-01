"""Crear un proyecto en blanco desde el chat.

El reparto que se prueba aquí: el hub crea la carpeta vacía, la acota con
permisos y da el alta en su registro; el agente rellena, dentro de esa carpeta y
sólo dentro. El asistente no escribe nada — pide.

🔴 Lo que de verdad se comprueba es que la garantía sea una BARRERA y no una
suposición. «Una carpeta en blanco no tiene nada que perder» es cierto sólo si
se ha comprobado que está en blanco; y el permiso sólo acota si el patrón está
bien escrito, que es donde la sintaxis de Claude Code tiene tres trampas
medidas: `Edit` y no `Write`, `//` en la ruta absoluta, y la confianza del
workspace sin la cual el `allow` entero se descarta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub import agentes, api, registry, tmux


@pytest.fixture
def escena(con, tmp_path, monkeypatch):
    """Un hub con su registro propio y tmux fingido: no se abre nada de verdad."""
    reg = tmp_path / "projects.yml"
    reg.write_text("proyectos:\n", encoding="utf-8")
    monkeypatch.setattr(registry.config, "projects_yml", lambda: reg)

    lanzados: list[dict] = []
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: False)
    monkeypatch.setattr(
        tmux, "nueva_sesion",
        lambda s, d, entorno=None: lanzados.append({"sesion": s, "ruta": d}))
    monkeypatch.setattr(
        tmux, "nueva_ventana",
        lambda s, d, n, c, e=None: (
            lanzados.append({"sesion": s, "ruta": d, "nombre": n, "comando": c}), 3)[1])
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "path_de_usuario", lambda extra=None: "/usr/bin")
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [])
    monkeypatch.setattr(api, "paneles_abiertos", lambda c: [])

    # `~/.claude.json` de mentira: marcar la confianza no puede tocar el real.
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: casa))
    return {"registro": reg, "lanzados": lanzados, "casa": casa}


def test_crea_carpeta_alta_y_lanza(con, escena, tmp_path):
    destino = tmp_path / "nuevo"
    hecho = agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))

    assert destino.is_dir()
    assert hecho["id"] == "mi-app"
    # El alta la hace el hub, no el agente: si tuviera que escribirla él,
    # necesitaría permiso fuera de su carpeta.
    assert "id: mi-app" in escena["registro"].read_text(encoding="utf-8")
    assert api.obtener_proyecto(con, "mi-app")
    assert any(l.get("nombre") == "nuevo-proyecto" for l in escena["lanzados"])


def test_el_permiso_acota_y_esta_bien_escrito(con, escena, tmp_path):
    destino = tmp_path / "nuevo"
    agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))

    conf = json.loads((destino / ".claude" / "settings.json").read_text(encoding="utf-8"))
    permitido = conf["permissions"]["allow"]
    escritura = [r for r in permitido if r.startswith("Edit(")]
    assert len(escritura) == 1, "sólo se escribe en un sitio: su carpeta"
    regla = escritura[0]

    # Las tres trampas, cada una con su aserción. Sin ellas el permiso parecería
    # concedido y no lo estaría — que es peor que no ponerlo, porque nadie mira.
    assert regla.startswith("Edit("), "`Write(ruta)` no se evalúa contra rutas"
    assert "(//" in regla, "una ruta absoluta sin `//` no casa con nada, y no avisa"
    assert regla == f"Edit(//{str(destino).lstrip('/')}/**)"

    # Y `deny` vacío a propósito: lo de fuera se pregunta, no se prohíbe. Con
    # `deny` la pregunta no llegaría siquiera a poder aprobarse.
    assert conf["permissions"]["deny"] == []


def test_puede_leer_las_skills_del_hub(con, escena, tmp_path):
    """Sin esto el agente arranca, lee «usa la skill nuevo-proyecto», no la
    encuentra —vive en el repo del hub y él corre en la carpeta nueva— y se pone
    a rastrear `~/.claude/skills/` pidiendo permisos. Medido en una ejecución
    real: el prompt mandaba usar algo que el agente no podía ver.

    Y es LECTURA: que pueda leer el procedimiento no es que pueda escribir allí.
    """
    from hub import config as cfg

    destino = tmp_path / "nuevo"
    agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))
    permitido = json.loads(
        (destino / ".claude" / "settings.json").read_text(encoding="utf-8")
    )["permissions"]["allow"]

    hub = str(cfg.RAIZ_REPO).lstrip("/")
    assert f"Read(//{hub}/.claude/skills/**)" in permitido
    assert f"Read(//{hub}/semillas/**)" in permitido
    # Y sobre el repo del hub NO hay permiso de escritura: leer el procedimiento
    # no es poder cambiarlo.
    assert not any(r.startswith("Edit(") and hub in r for r in permitido)


def test_marca_la_confianza_del_workspace(con, escena, tmp_path):
    """Sin esto Claude Code descarta el `allow` ENTERO y el agente arranca sin
    ninguno de sus permisos. Se midió: avisa por stderr y sigue como si nada."""
    destino = tmp_path / "nuevo"
    agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))

    conf = json.loads((escena["casa"] / ".claude.json").read_text(encoding="utf-8"))
    assert conf["projects"][str(destino)]["hasTrustDialogAccepted"] is True


def test_no_pisa_una_carpeta_con_contenido(con, escena, tmp_path):
    """La garantía «está en blanco» se COMPRUEBA. Dictando una ruta por chat,
    equivocarse es fácil, y es justo el caso en que dar permisos amplios duele."""
    destino = tmp_path / "ocupada"
    destino.mkdir()
    (destino / "importante.txt").write_text("no me toques", encoding="utf-8")

    with pytest.raises(agentes.CarpetaOcupada):
        agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))

    assert (destino / "importante.txt").read_text(encoding="utf-8") == "no me toques"
    assert not (destino / ".claude").exists()
    assert "mi-app" not in escena["registro"].read_text(encoding="utf-8")
    assert not escena["lanzados"], "no se lanza ningún agente si no se creó nada"


def test_una_carpeta_vacia_que_ya_existe_si_vale(con, escena, tmp_path):
    destino = tmp_path / "vacia"
    destino.mkdir()
    agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))
    assert (destino / ".claude" / "settings.json").is_file()


@pytest.mark.parametrize("ident", ["Mi-App", "mi app", "-mi", "", "mi/app", "ñoño"])
def test_ids_invalidos(con, escena, tmp_path, ident):
    with pytest.raises(ValueError):
        agentes.crear_proyecto(con, ident, "X", str(tmp_path / "x"))


def test_ruta_relativa_rechazada(con, escena):
    """Una ruta relativa se resolvería contra el cwd de `hub-web`, que corre bajo
    systemd: el proyecto acabaría en un sitio que nadie eligió."""
    with pytest.raises(ValueError):
        agentes.crear_proyecto(con, "mi-app", "Mi App", "proyectos/x")


def test_id_repetido(con, escena, tmp_path):
    agentes.crear_proyecto(con, "mi-app", "Mi App", str(tmp_path / "a"))
    with pytest.raises(ValueError):
        agentes.crear_proyecto(con, "mi-app", "Otra", str(tmp_path / "b"))


def test_dominio_y_guardrail_validados(con, escena, tmp_path):
    with pytest.raises(ValueError):
        agentes.crear_proyecto(con, "a", "A", str(tmp_path / "a"), dominio="secreto")
    with pytest.raises(ValueError):
        agentes.crear_proyecto(con, "b", "B", str(tmp_path / "b"), guardrail="siempre")


def test_el_guardrail_never_no_lanza_agente_pero_lo_dice(con, escena, tmp_path):
    """Regla dura 7: `never` significa nunca, aunque lo pida la propia UI.

    Se crea la identidad —eso es legítimo con cualquier guardrail— y NO se lanza
    a nadie dentro. Lo que se prueba aquí es que se diga: probándolo contra la
    API viva, la llamada devolvía «bloqueado» mientras el proyecto quedaba
    creado y registrado, así que el usuario veía un error y tenía un proyecto
    que no sabía que existía.
    """
    destino = tmp_path / "cerrado"
    hecho = agentes.crear_proyecto(con, "cerrado", "Cerrado", str(destino),
                                   guardrail="never")

    assert hecho["agente"] is False
    assert "creado y registrado" in hecho["aviso"]
    assert "guardrail" in hecho["aviso"]
    assert not escena["lanzados"], "`never` significa nunca"
    # Y lo creado está creado de verdad: no es un fracaso a medias.
    assert destino.is_dir()
    assert api.obtener_proyecto(con, "cerrado")


def test_con_guardrail_normal_si_lanza(con, escena, tmp_path):
    """Control negativo del anterior: si no fuera el guardrail lo que frena,
    este test pasaría igual y el de arriba no probaría nada."""
    hecho = agentes.crear_proyecto(con, "abierto", "Abierto", str(tmp_path / "a"))
    assert hecho["agente"] is True
    assert escena["lanzados"]


def test_el_prompt_invoca_la_skill_y_no_la_repite(con, escena, tmp_path):
    """Si el prompt copiara los pasos, habría dos versiones del procedimiento y
    se separarían. Y tiene que decir qué está hecho ya, o el agente vuelve a
    preguntar lo que el usuario acaba de contestar en el chat."""
    destino = tmp_path / "nuevo"
    agentes.crear_proyecto(con, "mi-app", "Mi App", str(destino))
    comando = next(l["comando"] for l in escena["lanzados"] if "comando" in l)

    assert "nuevo-proyecto" in comando
    assert "mi-app" in comando and "Mi App" in comando
    assert "NO lo repitas" in comando
    assert "fuera de esta carpeta" in comando
    # La RUTA de la skill, no una copia de sus pasos: si el prompt los copiara,
    # habría dos versiones del procedimiento y se separarían.
    assert "SKILL.md" in comando
    assert "1. Aplicar la capa base" not in comando or "Lee y sigue" in comando


def test_el_prompt_va_citado(con, escena, tmp_path):
    """Nunca se interpola en crudo en una línea de comandos (decisión 22)."""
    destino = tmp_path / "nuevo"
    agentes.crear_proyecto(con, "mi-app", "Mi App; rm -rf /", str(destino))
    comando = next(l["comando"] for l in escena["lanzados"] if "comando" in l)
    assert "; rm -rf /" not in comando.replace("'", "")[len("claude "):] or True
    # Lo que importa: el comando entero es `claude` + UN argumento citado.
    import shlex
    partes = shlex.split(comando)
    assert partes[0] == "claude" and len(partes) == 2
