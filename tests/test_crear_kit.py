"""Crear un kit desde la interfaz.

Mismo reparto que crear un proyecto —el hub pone la carpeta, la semilla y el
alta; el diseño lo escribe un agente dentro— y por eso este archivo comprueba
sobre todo lo que NO comparte con él:

🔴 Que la semilla llegue con el `id` y el `nombre` puestos. `semillas/kit/kit.yml`
trae valores de ejemplo (`id: mi-kit`), no marcadores, porque `@` no puede abrir
un escalar plano en YAML y con `@ID@` la plantilla no parseaba. La consecuencia
es que copiarla tal cual deja un kit llamándose `mi-kit`, y el choque no aparece
al crearlo sino mucho después, al medirlo contra el segundo.

🔴 Que el alta lleve `tipo: kit`. Sin eso el kit nace como proyecto normal: el
hub lo mide, pero no sale en la vista de kits ni el CLI lo reconoce.
"""

from __future__ import annotations

import pytest
import yaml

from hub import agentes, api, registry, tmux
from pathlib import Path


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

    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: casa))
    return {"registro": reg, "lanzados": lanzados}


def test_crea_el_repo_desde_la_semilla_con_su_alta(con, escena, tmp_path):
    destino = tmp_path / "kit-nuevo"
    hecho = agentes.crear_kit(con, "notificar", "Notificaciones", str(destino))

    assert hecho["id"] == "notificar"
    # La semilla entera, no sólo el manifiesto: el CLAUDE.md y el CHANGELOG
    # llevan las reglas del formato y sin ellos el agente empieza a ciegas.
    for archivo in ("kit.yml", "CLAUDE.md", "CHANGELOG.md", "README.md"):
        assert (destino / archivo).is_file(), archivo
    assert api.obtener_proyecto(con, "notificar")
    assert any(l.get("nombre") == "nuevo-kit" for l in escena["lanzados"])


def test_el_manifiesto_llega_con_su_id_y_su_nombre_puestos(con, escena, tmp_path):
    """🔴 Lo que evita que el segundo kit choque con el primero.

    Se parsea de verdad en vez de buscar la cadena: lo que importa no es que el
    texto aparezca, es que el YAML resultante siga siendo válido y diga eso.
    """
    destino = tmp_path / "kit-nuevo"
    agentes.crear_kit(con, "notificar", "Notificaciones", str(destino))

    manifiesto = yaml.safe_load((destino / "kit.yml").read_text(encoding="utf-8"))
    assert manifiesto["id"] == "notificar"
    assert manifiesto["nombre"] == "Notificaciones"
    assert manifiesto["version"] == "0.1"


def test_no_se_toca_el_comentario_que_explica_los_valores_de_ejemplo(con, escena, tmp_path):
    """El control negativo del reemplazo. Anclarlo al principio de línea es lo
    que distingue sustituir el valor de arrasar el archivo: `mi-kit` aparece en
    la prosa que cuenta por qué son valores de ejemplo y no marcadores, y esa
    explicación es la que evita que el siguiente los convierta en `@ID@` otra
    vez — que fue lo que no parseaba."""
    destino = tmp_path / "kit-nuevo"
    agentes.crear_kit(con, "notificar", "Notificaciones", str(destino))

    texto = (destino / "kit.yml").read_text(encoding="utf-8")
    assert "VALORES DE EJEMPLO" in texto
    assert "@ID@" in texto, "el comentario que explica el fallo del parser"
    assert "\nid: notificar\n" in texto
    assert "\nid: mi-kit\n" not in texto


def test_el_alta_lo_marca_como_kit_y_no_como_proyecto(con, escena, tmp_path):
    """Sin `tipo: kit` el kit existe pero es invisible como kit: no sale en la
    vista de kits del inventario ni el CLI lo reconoce."""
    agentes.crear_kit(con, "notificar", "Notificaciones", str(tmp_path / "k"))

    declarado = yaml.safe_load(escena["registro"].read_text(encoding="utf-8"))
    fila = next(p for p in declarado["proyectos"] if p["id"] == "notificar")
    assert fila["tipo"] == "kit"
    assert next(p for p in registry.cargar(escena["registro"])
                if p.id == "notificar").tipo == "kit"


def test_no_pisa_una_carpeta_con_contenido(con, escena, tmp_path):
    """Y el mensaje dice por qué, que aquí no es sólo prudencia: extraer un kit
    de un proyecto que ya lo tenía produce una copia de ese proyecto."""
    ocupada = tmp_path / "ocupada"
    ocupada.mkdir()
    (ocupada / "algo.md").write_text("mío", encoding="utf-8")

    with pytest.raises(agentes.CarpetaOcupada) as exc:
        agentes.crear_kit(con, "notificar", "Notificaciones", str(ocupada))
    assert "copia" in str(exc.value)
    assert (ocupada / "algo.md").read_text(encoding="utf-8") == "mío"
    assert not (ocupada / "kit.yml").exists()
    assert not escena["lanzados"]


def test_una_carpeta_vacia_que_ya_existe_si_vale(con, escena, tmp_path):
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    assert agentes.crear_kit(con, "notificar", "N", str(vacia))["agente"] is True


@pytest.mark.parametrize("ident", ["Mi-Kit", "mi kit", "-mi", "", "mi/kit", "ñ"])
def test_ids_invalidos(con, escena, tmp_path, ident):
    with pytest.raises(ValueError):
        agentes.crear_kit(con, ident, "N", str(tmp_path / "k"))
    assert not (tmp_path / "k").exists(), "no se crea nada si el id no vale"


def test_un_id_que_ya_existe_se_rechaza(con, escena, tmp_path):
    agentes.crear_kit(con, "notificar", "N", str(tmp_path / "uno"))
    with pytest.raises(ValueError, match="notificar"):
        agentes.crear_kit(con, "notificar", "Otro", str(tmp_path / "dos"))


def test_ruta_relativa_rechazada(con, escena):
    with pytest.raises(ValueError, match="absoluta"):
        agentes.crear_kit(con, "notificar", "N", "kits/notificar")


def test_el_guardrail_never_deja_la_semilla_pero_no_lanza(con, escena, tmp_path):
    """Igual que en proyectos: se crea, no se lanza, y se DICE. Callarlo dejaba
    un kit creado que el usuario no sabía que existía."""
    destino = tmp_path / "cerrado"
    hecho = agentes.crear_kit(con, "cerrado", "Cerrado", str(destino),
                              guardrail="never")

    assert hecho["agente"] is False
    assert "creado y registrado" in hecho["aviso"]
    assert (destino / "kit.yml").is_file(), "la semilla sí queda puesta"
    assert not escena["lanzados"], "`never` significa nunca"
    assert api.obtener_proyecto(con, "cerrado")


def test_con_guardrail_normal_si_lanza(con, escena, tmp_path):
    """Control negativo del anterior: sin esto, el de arriba pasaría igual
    aunque nada llegara nunca a lanzarse."""
    hecho = agentes.crear_kit(con, "abierto", "Abierto", str(tmp_path / "a"))
    assert hecho["agente"] is True
    assert escena["lanzados"]


def test_el_prompt_invoca_la_skill_y_no_la_repite(con, escena, tmp_path):
    """Dos copias del procedimiento se separan con el tiempo, y la que se queda
    vieja es siempre la que nadie mira."""
    agentes.crear_kit(con, "notificar", "N", str(tmp_path / "k"))
    comando = next(l["comando"] for l in escena["lanzados"] if l.get("comando"))

    assert "nuevo-kit/SKILL.md" in comando
    # Señales de que el procedimiento se invoca en vez de copiarse: la skill
    # tiene cuatro preguntas y aquí sólo se las nombra.
    assert "cuatro preguntas" in comando
    assert "Ya está hecho" in comando and "notificar" in comando


def test_el_prompt_avisa_de_lo_que_no_se_puede_saltar(con, escena, tmp_path):
    agentes.crear_kit(con, "notificar", "N", str(tmp_path / "k"))
    comando = next(l["comando"] for l in escena["lanzados"] if l.get("comando"))
    # Con los espacios colapsados: el prompt va justificado a 79 columnas y estas
    # frases cruzan el salto de línea. Atar el test al ancho lo rompería el día
    # que alguien reajuste un párrafo, sin que nada haya dejado de decirse.
    seguido = " ".join(comando.split())
    assert "no es una plantilla, es una copia" in seguido
    assert "verlo acertar Y verlo fallar" in seguido
