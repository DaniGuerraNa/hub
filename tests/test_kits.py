"""El mecanismo de kits: manifiesto, resolución por id, medición y huérfanos.

Un kit es una capa que aporta una capacidad a un proyecto. El hub es el gestor:
los resuelve por `id`, los instala con la versión en la ruta —como `~/.m2`— y
mide qué está al día. Lo que NO hace es escribir dentro de un proyecto ajeno:
calcula el plan y lo propone.

Lo que se fija aquí es sobre todo lo que puede mentir en silencio: una versión
que se resuelve mal, una copia comparada con la vara equivocada, un archivo
huérfano que nadie ve, y una capacidad que nadie provee.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hub import config, kits


@pytest.fixture
def kit_demo(tmp_path) -> Path:
    """Un kit con los tres modos, para no probar sólo el caso fácil."""
    raiz = tmp_path / "kit-demo"
    (raiz / "metodo").mkdir(parents=True)
    (raiz / "skills" / "avisar").mkdir(parents=True)
    (raiz / "plantillas").mkdir(parents=True)
    (raiz / "metodo" / "guia.md").write_text("la guía\n", encoding="utf-8")
    (raiz / "skills" / "avisar" / "SKILL.md").write_text("la skill\n", encoding="utf-8")
    (raiz / "plantillas" / "rol.md").write_text("plantilla de @ROL@\n", encoding="utf-8")
    (raiz / "kit.yml").write_text(textwrap.dedent("""
        id: demo
        nombre: Kit de demostración
        version: "1.0"
        expone:
          - id: demo#hacer-algo
            tipo: script
            ruta: metodo/guia.md
        consume:
          - id: notificar#enviar-mensaje
            opcional: true
        requiere:
          binarios: [git]
        aplica:
          - origen: metodo/guia.md
            destino: docs/guia.md
            modo: apuntador
          - origen: skills/avisar/SKILL.md
            destino: .claude/skills/avisar/SKILL.md
            modo: materializado
          - origen: plantillas/rol.md
            destino: .claude/agents/rol.md
            modo: copia
            parametros: [rol]
    """).strip() + "\n", encoding="utf-8")
    return raiz


# ── el manifiesto ────────────────────────────────────────────────────────────

def test_lee_el_manifiesto_completo(kit_demo):
    kit = kits.leer_manifiesto(kit_demo)
    assert kit.id == "demo" and kit.version == "1.0"
    assert kit.capacidades_expuestas == ["demo#hacer-algo"]
    assert kit.requiere() == []                        # la única que consume es opcional
    assert kit.requiere(opcionales=True) == ["notificar#enviar-mensaje"]
    assert [a.modo for a in kit.aplica] == ["apuntador", "materializado", "copia"]


def test_un_manifiesto_roto_se_descubre_al_leerlo_y_dice_que_falta(tmp_path):
    """Descubrirlo a mitad de aplicar dejaría el proyecto a medias."""
    raiz = tmp_path / "malo"
    raiz.mkdir()
    (raiz / "kit.yml").write_text('nombre: sin id\nversion: "1.0"\n', encoding="utf-8")
    with pytest.raises(kits.KitInvalido, match="id"):
        kits.leer_manifiesto(raiz)


@pytest.mark.parametrize("version", ["1", "v1.0", "1.0.0", "latest", ""])
def test_rechaza_versiones_que_no_son_major_minor(tmp_path, version):
    raiz = tmp_path / f"v{version or 'vacia'}"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(f'id: x\nversion: "{version}"\n', encoding="utf-8")
    with pytest.raises(kits.KitInvalido, match="major.minor"):
        kits.leer_manifiesto(raiz)


def test_una_capacidad_no_puede_llamarse_como_su_proveedor(tmp_path):
    """`telegram#enviar` haría imposible sustituir el proveedor.

    Y poder sustituirlo es el motivo entero de que las capacidades existan: el
    kit que consume no debe depender de un nombre propio, sino de un contrato.
    Aquí sólo se puede validar la FORMA; el criterio lo pone quien lo escribe.
    """
    raiz = tmp_path / "mal-nombre"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(
        'id: x\nversion: "1.0"\nexpone:\n  - id: NoEsUnContrato\n', encoding="utf-8"
    )
    with pytest.raises(kits.KitInvalido, match="dominio#verbo-objeto"):
        kits.leer_manifiesto(raiz)


def test_una_capacidad_suelta_dice_que_le_falta_el_id(tmp_path):
    """La forma corta es el error que sale solo al escribir un kit a mano.

    `- notificar#enviar-mensaje` en vez de `- id: notificar#enviar-mensaje`
    reventaba con un `AttributeError` desde dentro del parser, y quien escribe
    su primer kit veía un traceback del hub sin forma de saber que le sobraba un
    guion. `KitInvalido` existe para decir qué falta, no «error».

    Salió de escribir el kit `telegram` el 2026-09-02.
    """
    raiz = tmp_path / "suelta"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(
        'id: x\nversion: "1.0"\nconsume:\n  - orquestacion#pactar-sesion\n',
        encoding="utf-8",
    )
    with pytest.raises(kits.KitInvalido, match="suelto"):
        kits.leer_manifiesto(raiz)


@pytest.mark.parametrize("destino", ["/etc/passwd", "../../fuera.md", "a/../../b.md"])
def test_un_destino_no_puede_salir_del_proyecto(tmp_path, destino):
    """Un kit puede venir de cualquier sitio. Esto no es paranoia, es la puerta."""
    raiz = tmp_path / "fuga"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(
        f'id: x\nversion: "1.0"\naplica:\n  - origen: a.md\n    destino: {destino}\n',
        encoding="utf-8",
    )
    with pytest.raises(kits.KitInvalido, match="sale del proyecto"):
        kits.leer_manifiesto(raiz)


@pytest.mark.parametrize(
    "origen", ["/etc/passwd", "../../../.ssh/config", "a/../../../.aws/credentials"]
)
def test_un_origen_no_puede_salir_del_kit(tmp_path, origen):
    """La otra mitad de la puerta, que estuvo abierta.

    Vigilar sólo el destino deja pasar lo contrario: un kit ajeno que declara
    `origen: ../../../.ssh/config` y un destino inocente. Pasaba `verificar` en
    verde, y el prompt del agente lista el destino pero NO el origen, así que
    quien revisaba el plan no tenía dónde verlo. Acababa dentro de un repo que
    después se commitea.
    """
    raiz = tmp_path / "fuga"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(
        f'id: x\nversion: "1.0"\naplica:\n  - origen: {origen}\n    destino: a.md\n',
        encoding="utf-8",
    )
    with pytest.raises(kits.KitInvalido, match="sale del kit"):
        kits.leer_manifiesto(raiz)


# ── el repositorio local, con la versión en la ruta ──────────────────────────

def test_las_versiones_coexisten(tmp_path, monkeypatch):
    """Como `~/.m2`: un proyecto en 1.2 y otro en 2.0, sin migrar a la vez."""
    monkeypatch.setattr(config, "HUB_KITS", tmp_path / "kits")
    for v in ("1.2", "2.0", "1.10"):
        kits.ruta_de("demo", v).mkdir(parents=True)

    assert kits.instalados()["demo"] == ["1.2", "1.10", "2.0"]  # 1.10 > 1.2, no alfabético
    assert kits.resolver("demo", "1.2") == kits.ruta_de("demo", "1.2")
    assert kits.resolver("demo").name == "2.0"                  # sin pedir, la más alta
    assert kits.resolver("demo", "9.9") is None
    assert kits.resolver("inexistente") is None


def test_el_catalogo_del_usuario_gana_sobre_el_del_repo(tmp_path, monkeypatch):
    """Así se añaden kits propios sin tocar el repo del hub."""
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    (tmp_path / "kits.yml").write_text(
        'kits:\n  - id: base\n    version: "9.9"\n    origen: mío\n', encoding="utf-8"
    )
    catalogo = kits.catalogo()
    assert catalogo["base"]["version"] == "9.9"
    assert catalogo["base"]["origen"] == "mío"


# ── la medición ──────────────────────────────────────────────────────────────

@pytest.fixture
def proyecto(tmp_path, kit_demo):
    """Un proyecto con el kit ya aplicado, como lo dejaría el agente."""
    raiz = tmp_path / "proyecto"
    (raiz / "docs").mkdir(parents=True)
    (raiz / ".claude" / "skills" / "avisar").mkdir(parents=True)
    (raiz / ".claude" / "agents").mkdir(parents=True)
    (raiz / ".claude" / "hub").mkdir(parents=True)
    (raiz / "docs" / "guia.md").write_text("la guía\n", encoding="utf-8")
    (raiz / ".claude" / "skills" / "avisar" / "SKILL.md").write_text("la skill\n", encoding="utf-8")
    (raiz / ".claude" / "agents" / "rol.md").write_text("plantilla de revisor\n", encoding="utf-8")
    (raiz / ".claude" / "hub" / "kits.yml").write_text(textwrap.dedent("""
        kits:
          - id: demo
            version: "1.0"
            aplicado: 2026-08-31
            destinos:
              - docs/guia.md
              - .claude/skills/avisar/SKILL.md
              - .claude/agents/rol.md
    """).strip() + "\n", encoding="utf-8")
    return raiz


def test_el_registro_lo_declara_el_consumidor(proyecto):
    """Vive dentro del proyecto: si alguien lo clona, sabe qué kits lleva."""
    (declarado,) = kits.kits_declarados([str(proyecto)])
    assert declarado["id"] == "demo" and declarado["version"] == "1.0"


def test_todo_al_dia_se_mide_como_al_dia(proyecto, kit_demo):
    kit = kits.leer_manifiesto(kit_demo)
    (declarado,) = kits.kits_declarados([str(proyecto)])
    estados = {m["destino"]: m["estado"] for m in kits.medir([str(proyecto)], kit, declarado)}
    assert estados["docs/guia.md"] == "igual"
    assert estados[".claude/skills/avisar/SKILL.md"] == "igual"
    # La copia no se compara por contenido: salió de esta misma versión.
    assert estados[".claude/agents/rol.md"] == "al-dia"


def test_se_ha_visto_marcar_difiere_y_volver_a_igual(proyecto, kit_demo):
    """Verlo acertar y verlo fallar. Un verde que nadie ha visto en rojo no vale.

    Es el control negativo del instrumento: se rompe a propósito, se comprueba
    que lo detecta, se restaura y se comprueba que vuelve.
    """
    kit = kits.leer_manifiesto(kit_demo)
    declarado = kits.kits_declarados([str(proyecto)])[0]
    guia = proyecto / "docs" / "guia.md"
    original = guia.read_text(encoding="utf-8")

    guia.write_text(original + "# ROTURA DELIBERADA\n", encoding="utf-8")
    estados = {m["destino"]: m["estado"] for m in kits.medir([str(proyecto)], kit, declarado)}
    assert estados["docs/guia.md"] == "difiere"

    guia.write_text(original, encoding="utf-8")
    estados = {m["destino"]: m["estado"] for m in kits.medir([str(proyecto)], kit, declarado)}
    assert estados["docs/guia.md"] == "igual"


def test_una_copia_editada_no_se_marca_como_defecto(proyecto, kit_demo):
    """«Se copia lo que se edita»: la plantilla EXISTE para divergir.

    Compararla byte a byte encendería la señal siempre, y una señal que se
    enciende siempre se aprende a ignorar — y entonces el día que importe
    tampoco se mirará.
    """
    kit = kits.leer_manifiesto(kit_demo)
    declarado = kits.kits_declarados([str(proyecto)])[0]
    (proyecto / ".claude" / "agents" / "rol.md").write_text(
        "esto ya no se parece en nada al original\n", encoding="utf-8"
    )
    estados = {m["destino"]: m["estado"] for m in kits.medir([str(proyecto)], kit, declarado)}
    assert estados[".claude/agents/rol.md"] == "al-dia"


def test_una_copia_avisa_cuando_el_kit_sube_de_version(proyecto, kit_demo):
    """No se propaga —es del proyecto— pero se dice que su origen cambió."""
    kit = kits.leer_manifiesto(kit_demo)
    kit.version = "1.1"
    declarado = kits.kits_declarados([str(proyecto)])[0]
    estados = {m["destino"]: m["estado"] for m in kits.medir([str(proyecto)], kit, declarado)}
    assert estados[".claude/agents/rol.md"] == "origen-cambiado"


def test_lo_que_falta_se_ve(proyecto, kit_demo):
    kit = kits.leer_manifiesto(kit_demo)
    declarado = kits.kits_declarados([str(proyecto)])[0]
    (proyecto / "docs" / "guia.md").unlink()
    plan = kits.plan_de_aplicacion([str(proyecto)], kit, declarado)
    assert [p["destino"] for p in plan["pendientes"]] == ["docs/guia.md"]


# ── huérfanos ────────────────────────────────────────────────────────────────

def test_los_huerfanos_se_nombran_al_cambiar_de_version(proyecto, kit_demo):
    """Maven no lo necesita; aquí los archivos se quedan dentro del repo.

    Sin esto, lo que ya no respalda nadie se acumula y la deriva empieza a medir
    contra cosas que ningún kit sostiene.
    """
    kit = kits.leer_manifiesto(kit_demo)
    declarado = dict(kits.kits_declarados([str(proyecto)])[0])
    declarado["destinos"] = declarado["destinos"] + ["docs/viejo.md"]
    (proyecto / "docs" / "viejo.md").write_text("de la versión anterior\n", encoding="utf-8")

    assert kits.huerfanos([str(proyecto)], kit, declarado) == ["docs/viejo.md"]
    # Y sigue en disco: el hub dice qué sobra, no lo borra.
    assert (proyecto / "docs" / "viejo.md").exists()


def test_no_se_llama_huerfano_a_lo_que_ya_no_existe(proyecto, kit_demo):
    kit = kits.leer_manifiesto(kit_demo)
    declarado = dict(kits.kits_declarados([str(proyecto)])[0])
    declarado["destinos"] = declarado["destinos"] + ["docs/borrado-hace-tiempo.md"]
    assert kits.huerfanos([str(proyecto)], kit, declarado) == []


# ── capacidades ──────────────────────────────────────────────────────────────

def test_una_capacidad_opcional_sin_proveedor_se_dice_en_voz_alta(kit_demo):
    """«Que se informe para que el usuario sea consciente».

    Una capacidad ausente y callada es un instrumento en verde que nadie ha
    visto funcionar.
    """
    kit = kits.leer_manifiesto(kit_demo)
    r = kits.resolver_capacidades([kit])
    assert r["degradados"] == [{"kit_id": "demo", "capacidad": "notificar#enviar-mensaje"}]
    assert r["faltan"] == []


def test_la_dependencia_es_de_la_capacidad_no_del_kit(kit_demo, tmp_path):
    """Cualquier kit que exponga el contrato satisface al que lo consume.

    Es lo que permite cambiar de Telegram a Slack sin tocar a quien lo usa.
    """
    otro = tmp_path / "kit-slack"
    otro.mkdir()
    (otro / "kit.yml").write_text(textwrap.dedent("""
        id: slack
        version: "1.0"
        expone:
          - id: notificar#enviar-mensaje
            tipo: script
            ruta: enviar.sh
    """).strip() + "\n", encoding="utf-8")

    r = kits.resolver_capacidades([kits.leer_manifiesto(kit_demo), kits.leer_manifiesto(otro)])
    assert r["degradados"] == []
    assert r["proveedores"]["notificar#enviar-mensaje"] == ["slack"]


def test_una_capacidad_obligatoria_sin_proveedor_no_se_confunde_con_una_opcional(tmp_path):
    raiz = tmp_path / "exigente"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(textwrap.dedent("""
        id: exigente
        version: "1.0"
        consume:
          - id: notificar#enviar-mensaje
    """).strip() + "\n", encoding="utf-8")
    r = kits.resolver_capacidades([kits.leer_manifiesto(raiz)])
    assert r["faltan"] and not r["degradados"]


# ── el plan, que se propone y no se ejecuta ──────────────────────────────────

def test_el_plan_es_una_propuesta_para_un_agente_no_una_escritura(proyecto, kit_demo):
    """El hub calcula; escribir dentro de otro repo lo hace un agente allí."""
    kit = kits.leer_manifiesto(kit_demo)
    declarado = kits.kits_declarados([str(proyecto)])[0]
    (proyecto / "docs" / "guia.md").unlink()

    plan = kits.plan_de_aplicacion([str(proyecto)], kit, declarado)
    prompt = kits.prompt_aplicar("Proyecto", str(proyecto), kit, plan)

    assert "docs/guia.md" in prompt and "crear" in prompt
    assert ".claude/hub/kits.yml" in prompt          # deja rastro de lo aplicado
    assert "divergencia sin declarar" in prompt      # y el criterio, no sólo la orden
    # Nada se ha escrito por calcularlo.
    assert not (proyecto / "docs" / "guia.md").exists()


def test_el_plan_avisa_de_los_binarios_que_faltan(proyecto, kit_demo):
    kit = kits.leer_manifiesto(kit_demo)
    kit.binarios = ["un-binario-que-no-existe-en-ninguna-parte"]
    plan = kits.plan_de_aplicacion([str(proyecto)], kit, None)
    assert plan["binarios_ausentes"] == ["un-binario-que-no-existe-en-ninguna-parte"]


# ── la capa base es el kit obligatorio ───────────────────────────────────────

def test_la_base_es_un_kit_valido_y_viene_con_el_hub():
    """Aplicar la base y aplicar un kit son la misma operación."""
    base = kits.leer_manifiesto(config.RAIZ_REPO / "semillas" / "base")
    assert base.id == kits.ID_BASE
    assert base.version == kits.VERSION_BASE
    destinos = [a.destino for a in base.aplica]
    # El registro de kits lo pone la base: vive dentro de `.claude/hub/`, que es
    # lo que ella crea. Sin declararlo, el primer `aplicar` no tendría dónde
    # anotarse.
    assert ".claude/hub/kits.yml" in destinos
    assert ".claude/hub/project.yml" in destinos


def test_el_catalogo_del_repo_declara_la_base_como_obligatoria():
    assert kits.catalogo()[kits.ID_BASE]["obligatorio"] is True


# ── el gestor, de extremo a extremo ──────────────────────────────────────────

def _git(cwd, *args):
    import subprocess
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(cwd),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def test_se_instala_por_id_desde_el_tag_de_su_version(tmp_path, monkeypatch, kit_demo):
    """El gestor entero: catálogo → clone del tag → resolución por id.

    Instalar `1.0` es clonar el repo del kit en el tag `v1.0`. Es lo que hace
    que un proyecto pueda quedarse en una versión mientras el kit avanza.
    """
    _git(kit_demo, "init", "-q", "-b", "main")
    _git(kit_demo, "add", "-A")
    _git(kit_demo, "commit", "-qm", "kit 1.0")
    _git(kit_demo, "tag", "v1.0")

    # Una versión más, con un archivo menos: así el tag viejo tiene que notarse.
    (kit_demo / "metodo" / "guia.md").write_text("la guía, revisada\n", encoding="utf-8")
    _git(kit_demo, "add", "-A")
    _git(kit_demo, "commit", "-qm", "kit 1.1")
    _git(kit_demo, "tag", "v1.1")

    monkeypatch.setattr(config, "HUB_KITS", tmp_path / "repositorio")
    monkeypatch.setattr(config, "HUB_HOME", tmp_path / "datos")
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / "kits.yml").write_text(
        f'kits:\n  - id: demo\n    version: "1.0"\n    origen: {kit_demo}\n',
        encoding="utf-8",
    )

    datos = kits.catalogo()["demo"]
    destino = kits.instalar("demo", "1.0", datos["origen"])
    assert destino == kits.ruta_de("demo", "1.0")

    # Se resuelve por id, que es lo que cierra el apuntador: un proyecto dice
    # «uso demo 1.0» y el hub sabe dónde está, se mueva quien se mueva.
    assert kits.resolver("demo", "1.0") == destino
    kit = kits.leer_manifiesto(destino)
    assert kit.version == "1.0"
    # Y trae el contenido de SU tag, no el de la punta.
    assert (destino / "metodo" / "guia.md").read_text(encoding="utf-8") == "la guía\n"

    # La segunda versión convive con la primera, no la sustituye.
    kits.instalar("demo", "1.1", datos["origen"])
    assert kits.instalados()["demo"] == ["1.0", "1.1"]
    assert (kits.ruta_de("demo", "1.1") / "metodo" / "guia.md").read_text(
        encoding="utf-8"
    ) == "la guía, revisada\n"


def test_instalar_dos_veces_no_vuelve_a_descargar(tmp_path, monkeypatch, kit_demo):
    """Idempotente: correrlo de nuevo no rehace ni pisa lo que ya está."""
    _git(kit_demo, "init", "-q", "-b", "main")
    _git(kit_demo, "add", "-A")
    _git(kit_demo, "commit", "-qm", "kit")
    _git(kit_demo, "tag", "v1.0")
    monkeypatch.setattr(config, "HUB_KITS", tmp_path / "repositorio")

    primero = kits.instalar("demo", "1.0", str(kit_demo))
    testigo = primero / "TESTIGO"
    testigo.write_text("no me pises\n", encoding="utf-8")
    segundo = kits.instalar("demo", "1.0", str(kit_demo))
    assert segundo == primero and testigo.exists()


def test_un_tag_que_no_existe_lo_dice_y_no_deja_basura(tmp_path, monkeypatch, kit_demo):
    _git(kit_demo, "init", "-q", "-b", "main")
    _git(kit_demo, "add", "-A")
    _git(kit_demo, "commit", "-qm", "kit")
    _git(kit_demo, "tag", "v1.0")
    monkeypatch.setattr(config, "HUB_KITS", tmp_path / "repositorio")

    with pytest.raises(kits.KitInvalido, match="no se pudo obtener"):
        kits.instalar("demo", "9.9", str(kit_demo))
    assert not kits.instalados().get("demo")


# ── kits de máquina ──────────────────────────────────────────────────────────
#
# Salieron de migrar uno real: instalaba dos comandos en
# `~/.local/bin` y no escribía en ningún proyecto. Su `aplica` está vacío con
# razón, y forzarle destinos habría sido inventar un consumidor inexistente.

@pytest.fixture
def kit_de_maquina(tmp_path) -> Path:
    raiz = tmp_path / "herramienta"
    raiz.mkdir()
    (raiz / "instalar.sh").write_text("#!/usr/bin/env bash\necho instalando\n", encoding="utf-8")
    (raiz / "kit.yml").write_text(textwrap.dedent("""
        id: herramienta
        version: "1.0"
        expone:
          - id: idioma#explicar-texto
            tipo: script
            ruta: bin/x
        aplica: []
        instalar: instalar.sh
    """).strip() + "\n", encoding="utf-8")
    return raiz


def test_un_kit_sin_aplica_pero_con_instalador_es_de_maquina(kit_de_maquina):
    kit = kits.leer_manifiesto(kit_de_maquina)
    assert kit.de_maquina is True
    assert kit.instalar == "instalar.sh"


def test_un_kit_que_propaga_archivos_no_es_de_maquina(kit_demo):
    assert kits.leer_manifiesto(kit_demo).de_maquina is False


def test_un_instalador_declarado_que_no_existe_se_rechaza(tmp_path):
    """Prometer un instalador que no está falla en manos de quien lo instale."""
    raiz = tmp_path / "mentirosa"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(
        'id: x\nversion: "1.0"\ninstalar: no-existe.sh\n', encoding="utf-8"
    )
    with pytest.raises(kits.KitInvalido, match="no está en el kit"):
        kits.leer_manifiesto(raiz)


@pytest.mark.parametrize("ruta", ["/usr/bin/algo", "../fuera.sh"])
def test_el_instalador_tiene_que_estar_dentro_del_kit(tmp_path, ruta):
    raiz = tmp_path / f"fuga{abs(hash(ruta))}"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(f'id: x\nversion: "1.0"\ninstalar: {ruta}\n', encoding="utf-8")
    with pytest.raises(kits.KitInvalido, match="dentro del kit"):
        kits.leer_manifiesto(raiz)


def test_un_kit_de_maquina_no_deja_pendientes_en_ningun_proyecto(kit_de_maquina, tmp_path):
    """No propaga nada, así que no puede estar «desactualizado» en un proyecto."""
    proyecto = tmp_path / "cualquiera"
    proyecto.mkdir()
    plan = kits.plan_de_aplicacion([str(proyecto)], kits.leer_manifiesto(kit_de_maquina), None)
    assert plan["archivos"] == [] and plan["pendientes"] == []


# ── excepciones declaradas ───────────────────────────────────────────────────
#
# Salieron de migrar el kit de orquestación, que tiene dos consumidores reales y
# once decisiones entre los dos: archivos que no heredan y archivos que heredan
# distinto, cada uno con su motivo. Sin representarlas, migrar habría convertido
# once decisiones en once defectos aparentes — y una medición llena de falsos
# positivos es una medición que se deja de mirar.

def test_una_excepcion_declarada_no_cuenta_como_deriva(proyecto, kit_demo):
    kit = kits.leer_manifiesto(kit_demo)
    declarado = dict(kits.kits_declarados([str(proyecto)])[0])
    declarado["excepciones"] = {"docs/guia.md": "Aquí el método es propio."}

    (proyecto / "docs" / "guia.md").write_text("otra cosa completamente\n", encoding="utf-8")
    plan = kits.plan_de_aplicacion([str(proyecto)], kit, declarado)

    estados = {a["destino"]: a["estado"] for a in plan["archivos"]}
    assert estados["docs/guia.md"] == "declarada"
    assert plan["pendientes"] == []


def test_una_excepcion_cubre_tambien_lo_que_no_se_hereda(proyecto, kit_demo):
    """No heredar algo con motivo es una decisión, no un archivo que falta."""
    kit = kits.leer_manifiesto(kit_demo)
    declarado = dict(kits.kits_declarados([str(proyecto)])[0])
    declarado["excepciones"] = {"docs/guia.md": "No aplica a este proyecto."}
    (proyecto / "docs" / "guia.md").unlink()

    assert kits.plan_de_aplicacion([str(proyecto)], kit, declarado)["pendientes"] == []


def test_el_motivo_viaja_hasta_el_prompt(proyecto, kit_demo):
    """Sin el motivo, quien aplique el kit no sabe por qué no debe tocarlo."""
    kit = kits.leer_manifiesto(kit_demo)
    declarado = dict(kits.kits_declarados([str(proyecto)])[0])
    declarado["excepciones"] = {"docs/guia.md": "Atado al motor de este proyecto."}

    plan = kits.plan_de_aplicacion([str(proyecto)], kit, declarado)
    prompt = kits.prompt_aplicar("P", str(proyecto), kit, plan)
    assert "Atado al motor de este proyecto" in prompt
    assert "no tocar" in prompt.lower()


def test_sin_excepcion_declarada_el_cambio_local_sigue_siendo_deriva(proyecto, kit_demo):
    """El control negativo: declarar es lo que cambia el veredicto, no editar."""
    kit = kits.leer_manifiesto(kit_demo)
    declarado = kits.kits_declarados([str(proyecto)])[0]
    (proyecto / "docs" / "guia.md").write_text("editado sin declarar\n", encoding="utf-8")

    plan = kits.plan_de_aplicacion([str(proyecto)], kit, declarado)
    assert [a["destino"] for a in plan["pendientes"]] == ["docs/guia.md"]


# ── el kit que estás escribiendo ─────────────────────────────────────────────

def test_un_kit_del_registro_se_resuelve_sin_publicarlo(kit_demo):
    """Editar y medir en el mismo minuto, sin pasar por un tag.

    Obligar a publicar para ver cada cambio acabaría con alguien moviendo un tag
    ya publicado, que es lo único que no puede pasar.
    """
    class _P:
        id, tipo, asiento = "demo", "kit", str(kit_demo)

    assert kits.resolver_en_desarrollo("demo", [_P()]) == kit_demo
    assert kits.resolver_en_desarrollo("otro", [_P()]) is None


def test_un_proyecto_normal_no_se_resuelve_como_kit(kit_demo):
    class _P:
        id, tipo, asiento = "demo", "proyecto", str(kit_demo)

    assert kits.resolver_en_desarrollo("demo", [_P()]) is None


def test_una_carpeta_sin_manifiesto_no_se_resuelve_como_kit(tmp_path):
    vacia = tmp_path / "sin-manifiesto"
    vacia.mkdir()

    class _P:
        id, tipo, asiento = "x", "kit", str(vacia)

    assert kits.resolver_en_desarrollo("x", [_P()]) is None


# ── proyectos con varias rutas ───────────────────────────────────────────────

def test_se_mide_contra_la_ruta_que_tiene_la_capa_base(tmp_path, kit_demo):
    """Un proyecto puede orquestarse desde una carpeta y tener el código en otra.

    Medir contra la primera ruta de la lista daba «falta» en los tres archivos
    de la capa base **con los tres escritos y en su sitio**: la cifra estaba mal,
    no el proyecto. Apareció con uno real de seis ubicaciones.
    """
    codigo = tmp_path / "dev" / "codigo"
    codigo.mkdir(parents=True)
    asiento = tmp_path / "asiento"
    (asiento / "docs").mkdir(parents=True)
    (asiento / ".claude" / "hub").mkdir(parents=True)
    (asiento / "docs" / "guia.md").write_text("la guía\n", encoding="utf-8")

    # El código va primero en la lista, como devuelve el registro de verdad.
    raices = [str(codigo), str(asiento)]
    assert kits.raiz_de(raices) == asiento

    kit = kits.leer_manifiesto(kit_demo)
    estados = {m["destino"]: m["estado"] for m in kits.medir(raices, kit, None)}
    assert estados["docs/guia.md"] == "igual"


def test_sin_capa_base_se_cae_a_la_primera_ruta(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    assert kits.raiz_de([str(a), str(b)]) == a
    assert kits.raiz_de([]) is None


# ── El modo `apuntador` se mide como se documenta ────────────────────────────


def _kit_con_apuntador(tmp_path):
    raiz = tmp_path / "kit"
    raiz.mkdir()
    (raiz / "kit.yml").write_text(
        'id: demo\nversion: "1.0"\naplica:\n  - origen: guia.md\n'
        "    destino: docs/guia.md\n    modo: apuntador\n",
        encoding="utf-8",
    )
    (raiz / "guia.md").write_text("la verdad vive aquí", encoding="utf-8")
    return kits.leer_manifiesto(raiz)


def _con_bloque(proyecto, linea="Este proyecto usa: demo v1.0"):
    proyecto.mkdir(exist_ok=True)
    (proyecto / "CLAUDE.md").write_text(
        f"# Proyecto\n\n{kits.MARCA_BLOQUE}\n{linea}\n\nOtras cosas.\n",
        encoding="utf-8",
    )


def test_un_apuntador_aplicado_como_manda_la_skill_esta_al_dia(tmp_path):
    """🔴 El defecto que esto cierra.

    La skill dice **«NO copies el archivo»** y la medición marcaba `falta`
    precisamente porque el archivo no estaba. Seguir el procedimiento producía
    deriva permanente; ponerlo en verde exigía duplicar el contenido, que es el
    error que este modo existe para impedir.
    """
    kit = _kit_con_apuntador(tmp_path)
    proyecto = tmp_path / "proy"
    _con_bloque(proyecto)
    assert [m["estado"] for m in kits.medir([str(proyecto)], kit)] == ["apuntado"]
    # Y no se cuenta como trabajo pendiente.
    assert kits.plan_de_aplicacion([str(proyecto)], kit)["pendientes"] == []


def test_sin_el_bloque_sigue_faltando(tmp_path):
    """El control negativo: si no se aplicó, tiene que decirlo."""
    kit = _kit_con_apuntador(tmp_path)
    proyecto = tmp_path / "proy"
    proyecto.mkdir()
    assert [m["estado"] for m in kits.medir([str(proyecto)], kit)] == ["falta"]


def test_nombrar_el_kit_de_pasada_no_cuenta_como_aplicarlo(tmp_path):
    """«Esto lo hereda de demo» en la prosa no es haberlo aplicado.

    Por eso se busca dentro del bloque generado y no en todo el archivo.
    """
    kit = _kit_con_apuntador(tmp_path)
    proyecto = tmp_path / "proy"
    proyecto.mkdir()
    (proyecto / "CLAUDE.md").write_text(
        "# Proyecto\n\nEsto lo hereda de demo, más o menos.\n", encoding="utf-8"
    )
    assert [m["estado"] for m in kits.medir([str(proyecto)], kit)] == ["falta"]


def test_el_bloque_de_otro_kit_no_vale(tmp_path):
    kit = _kit_con_apuntador(tmp_path)
    proyecto = tmp_path / "proy"
    _con_bloque(proyecto, linea="Este proyecto usa: otra-cosa v2.0")
    assert [m["estado"] for m in kits.medir([str(proyecto)], kit)] == ["falta"]


def test_la_plantilla_de_kit_nuevo_parsea():
    """🔴 El simétrico del test de arriba, que no existía — y por eso.

    `semillas/kit/kit.yml` NO era YAML válido: `id: @ID@` sin comillas, y `@` es
    un indicador reservado que no puede abrir un escalar plano. El primer kit de
    cualquiera moría en `kit.sh verificar` con un error del parser señalando una
    línea que esa persona no había escrito, sin forma de distinguir «la
    plantilla viene rota» de «me equivoqué yo». Y la semilla viaja al producto.

    La causa es la de siempre en este repo: existía el test de `semillas/base` y
    no el de `semillas/kit`. Lo que no se mide, se rompe sin que nadie lo note.
    """
    raiz = config.RAIZ_REPO / "semillas" / "kit"
    plantilla = kits.leer_manifiesto(raiz)          # no levanta: eso es el test
    assert plantilla.version

    # `aplica: []` viene VACÍO a propósito —lo rellena quien crea el kit— pero
    # los tres modos tienen que estar de ejemplo, o la plantilla no enseña nada.
    texto = (raiz / "kit.yml").read_text(encoding="utf-8")
    for modo in ("apuntador", "materializado", "copia"):
        assert modo in texto, f"la plantilla no enseña el modo `{modo}`"


def test_la_plantilla_no_nombra_al_proyecto_que_la_origino():
    """Una plantilla que nombra su origen no es una plantilla, es una copia.

    Los patrones se toman de `publicacion`, no se escriben aquí: la primera
    versión de este test llevaba la lista literal dentro y el lint de datos
    personales se disparó contra el propio test. Es la trampa que ya está
    documentada en `publicacion.AUTOEXCLUIDO` y en `test_css_componentes.py`
    —un lint que salta al leer el archivo que explica la regla— y volvió a
    aparecer aquí. Reutilizar la fuente única la evita del todo.

    Y por eso mismo el test **se salta en el producto**: `publicacion` no viaja
    allí, porque allí no hay ninguna frontera que vigilar. Sin este `skip`, el
    producto llegaba a quien lo clona con un test en rojo — que es exactamente
    lo que `publicacion.EXCLUIDOS` explica que se quiere evitar.
    """
    publicacion = pytest.importorskip(
        "hub.publicacion", reason="sólo aplica en el repo de desarrollo"
    )

    raiz = config.RAIZ_REPO / "semillas" / "kit"
    for archivo in raiz.rglob("*"):
        if not archivo.is_file():
            continue
        for patron in (publicacion._BLOQUEANTE, publicacion._AVISO):
            hallazgos = publicacion.rastros_en(archivo, patron)
            assert not hallazgos, f"{archivo.name}: {hallazgos}"


# ── `materializado`: la cabecera obligatoria no es deriva ────────────────────


def _kit_materializado(tmp_path):
    raiz = tmp_path / "kit"
    (raiz / "skills").mkdir(parents=True)
    (raiz / "kit.yml").write_text(
        'id: saludador\nversion: "1.0"\naplica:\n'
        "  - origen: skills/saludar.md\n    destino: .claude/skills/saludar.md\n"
        "    modo: materializado\n",
        encoding="utf-8",
    )
    (raiz / "skills" / "saludar.md").write_text(
        "---\nname: saludar\n---\n\nDi hola.\n", encoding="utf-8"
    )
    return kits.leer_manifiesto(raiz), (raiz / "skills" / "saludar.md").read_text()


def _estado_de(proyecto, kit):
    return [m["estado"] for m in kits.medir([str(proyecto)], kit)][0]


CABECERAS = [
    "<!-- del kit saludador v1.0 — no editar aquí -->\n\n",
    "# del kit saludador v1.0 — no editar aquí\n\n",
    "// del kit saludador v1.0 — no editar aquí\n\n",
]


@pytest.mark.parametrize("cabecera", CABECERAS)
def test_la_cabecera_obligatoria_no_cuenta_como_deriva(tmp_path, cabecera):
    """🔴 Seguir la skill producía deriva permanente e irreparable.

    `aplicar-kit` **obliga** a copiar cada `materializado` con la cabecera «del
    kit X vN — no editar aquí», y el prompt que genera el propio hub la repite.
    La medición comparaba bytes, así que el destino tenía una línea de más y
    salía `difiere` para siempre. Ponerlo en verde exigía desobedecer la skill.

    Es el mismo defecto que ya se había arreglado para `apuntador`, en la rama
    de al lado del mismo `if`. Y `materializado` es el modo de las skills, los
    agentes y los hooks: el contenido más habitual de un kit.

    La cabecera se acepta en cualquier lenguaje de comentario porque la escribe
    un agente, y el tipo de archivo lo decide el kit.
    """
    kit, contenido = _kit_materializado(tmp_path)
    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(cabecera + contenido, encoding="utf-8")
    assert _estado_de(proyecto, kit) == "igual"


def test_una_skill_con_frontmatter_lleva_la_cabecera_DETRAS_y_sigue_al_dia(tmp_path):
    """🔴 El mismo defecto, reaparecido por el caso que más importa: una skill.

    Un `SKILL.md` necesita `---` en su PRIMERA línea o el frontmatter no parsea
    y la skill deja de existir para quien la busca —se comprobó: `name` sale
    `None`—. Así que ahí la cabecera **no puede ir delante**, tiene que ir
    detrás del frontmatter.

    Y el recorte devolvía `lineas[ultima+1:]`, o sea todo lo posterior a la
    cabecera: se llevaba el frontmatter del destino y lo dejaba distinto del
    origen **para siempre**, en el modo que existe justamente para skills,
    agentes y hooks. Nada visible fallaba; sólo un `difiere` eterno.
    """
    kit, contenido = _kit_materializado(tmp_path)
    frontmatter = '---\nname: saludar\ndescription: "Saluda: con dos puntos dentro"\n---\n'
    kit_ruta = kit.raiz / "skills" / "saludar.md"
    kit_ruta.write_text(frontmatter + "\n" + contenido, encoding="utf-8")

    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(
        frontmatter
        + "\n<!-- del kit saludador v1.0 — no editar aquí -->\n\n"
        + contenido,
        encoding="utf-8",
    )

    assert _estado_de(proyecto, kit) == "igual"


def test_la_cabecera_de_una_skill_no_puede_ir_antes_del_frontmatter(tmp_path):
    """CONTROL NEGATIVO: se comprueba que el problema que motiva lo anterior es real.

    Si esto dejara de fallar algún día, es que el frontmatter ya se parsea con
    algo delante — y entonces la regla de ponerla detrás sobra.
    """
    from hub import catalogo

    ruta = tmp_path / "SKILL.md"
    ruta.write_text(
        "<!-- del kit saludador v1.0 -->\n---\nname: saludar\n---\ncuerpo\n",
        encoding="utf-8",
    )
    assert catalogo.leer_frontmatter(ruta) == {}


def test_sin_cabecera_tambien_esta_al_dia(tmp_path):
    """Tolerar la cabecera no puede volverse exigirla."""
    kit, contenido = _kit_materializado(tmp_path)
    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(contenido, encoding="utf-8")
    assert _estado_de(proyecto, kit) == "igual"


def test_la_deriva_de_verdad_se_sigue_viendo(tmp_path):
    """El control que hace que el arreglo valga algo.

    Si tolerar la cabecera se tragara también los cambios reales, la medición
    entera dejaría de servir: sería un instrumento en verde permanente.
    """
    kit, contenido = _kit_materializado(tmp_path)
    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(
        CABECERAS[0] + contenido.replace("Di hola", "Di adiós"), encoding="utf-8"
    )
    assert _estado_de(proyecto, kit) == "difiere"


def test_una_cabecera_de_otro_kit_no_se_descuenta(tmp_path):
    """Sólo se ignora la cabecera de ESTE kit, no cualquier comentario."""
    kit, contenido = _kit_materializado(tmp_path)
    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(
        "<!-- del kit otro-kit v9.9 -->\n\n" + contenido, encoding="utf-8"
    )
    assert _estado_de(proyecto, kit) == "difiere"


# ── el bloque del apuntador: ni falsos rojos ni falsos verdes ────────────────


BLOQUES_VALIDOS = [
    "<!-- kits — generado, no editar a mano -->\nEste proyecto usa: telegram v1.0\n",
    # Guion normal en vez de raya larga: exigir la cadena byte a byte daba
    # `falta` a quien lo había aplicado bien.
    "<!-- kits - generado, no editar -->\nEste proyecto usa: telegram v1.0\n",
    # Línea en blanco tras el marcador: cortaba el bloque en vacío.
    "<!-- kits — generado -->\n\nEste proyecto usa: telegram v1.0\n",
    # Lista markdown de varios párrafos, que es como lo escribe un agente.
    "<!-- kits — generado -->\n\n- telegram v1.0\n\n- otra-cosa v2.0\n",
]

BLOQUES_QUE_NO_CUENTAN = [
    # `\b` trata el guion como frontera: `telegram` casaba dentro de
    # `notificar-telegram` y un kit salía aplicado por el nombre de otro.
    "<!-- kits — generado -->\nEste proyecto usa: notificar-telegram v1.0\n",
    "<!-- kits — generado -->\nEste proyecto usa: telegram-avanzado v1.0\n",
    "<!-- kits — generado -->\nEste proyecto usa: otra-cosa v2.0\n",
    "# Proyecto\n\nEsto usa telegram por ahí, en la prosa.\n",
]


def _kit_telegram(tmp_path):
    raiz = tmp_path / "kit"
    raiz.mkdir()
    (raiz / "g.md").write_text("contenido\n", encoding="utf-8")
    (raiz / "kit.yml").write_text(
        'id: telegram\nversion: "1.0"\naplica:\n  - origen: g.md\n'
        "    destino: docs/g.md\n    modo: apuntador\n",
        encoding="utf-8",
    )
    return kits.leer_manifiesto(raiz)


@pytest.mark.parametrize("bloque", BLOQUES_VALIDOS)
def test_el_bloque_se_reconoce_aunque_no_sea_byte_a_byte(tmp_path, bloque):
    kit = _kit_telegram(tmp_path)
    proyecto = tmp_path / "proy"
    proyecto.mkdir()
    (proyecto / "CLAUDE.md").write_text(bloque, encoding="utf-8")
    assert _estado_de(proyecto, kit) == "apuntado"


@pytest.mark.parametrize("bloque", BLOQUES_QUE_NO_CUENTAN)
def test_un_id_dentro_de_otro_no_cuenta_como_aplicado(tmp_path, bloque):
    """Tolerar el formato no puede volverse tolerar cualquier cosa."""
    kit = _kit_telegram(tmp_path)
    proyecto = tmp_path / "proy"
    proyecto.mkdir()
    (proyecto / "CLAUDE.md").write_text(bloque, encoding="utf-8")
    assert _estado_de(proyecto, kit) == "falta"


def test_da_igual_si_la_cabecera_va_PEGADA_al_frontmatter(tmp_path):
    """🔴 El mismo defecto una vez más, y por un detalle invisible: DÓNDE se
    pone la cabecera dentro del hueco.

    `_sin_cabecera` se lleva la cabecera y las líneas en blanco que la siguen,
    pero el origen conserva las suyas. Si el contenido empezaba con una blanca
    justo donde se insertó —el caso de una skill: `---`, frontmatter, `---`,
    blanca, título— el destino se quedaba con una línea menos y salía `difiere`
    para siempre.

    Medido el 2026-09-03 sobre dos consumidores del mismo kit: el que la puso
    tras la blanca salía al día y el que la pegó al `---`, en rojo. Ninguna
    instrucción decía cuál de las dos era la buena, porque nadie sabía que
    hubiera dos.
    """
    kit, contenido = _kit_materializado(tmp_path)
    frontmatter = '---\nname: saludar\n---\n'
    (kit.raiz / "skills" / "saludar.md").write_text(
        frontmatter + "\n" + contenido, encoding="utf-8"
    )

    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    # Pegada al cierre del frontmatter, sin respetar la blanca del origen.
    destino.write_text(
        frontmatter + "<!-- del kit saludador v1.0 — no editar aquí -->\n\n" + contenido,
        encoding="utf-8",
    )
    assert _estado_de(proyecto, kit) == "igual"


def test_perdonar_las_blancas_NO_tapa_un_cambio_de_verdad(tmp_path):
    """El control que sostiene lo de arriba. La relajación es sólo para líneas
    vacías y sólo cuando había cabecera: cualquier cambio de contenido sigue
    saliendo, o la medición dejaría de servir para lo único que hace."""
    kit, contenido = _kit_materializado(tmp_path)
    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(
        "<!-- del kit saludador v1.0 — no editar aquí -->\n\n"
        + contenido
        + "una línea que el kit no tiene\n",
        encoding="utf-8",
    )
    assert _estado_de(proyecto, kit) == "difiere"


def test_sin_cabecera_la_comparacion_sigue_siendo_EXACTA(tmp_path):
    """Un archivo sin cabecera no entra en la relajación: ahí una línea en
    blanco de más sí es una diferencia, y darla por buena sería relajar la
    medición entera por un caso que no la necesita."""
    kit, contenido = _kit_materializado(tmp_path)
    proyecto = tmp_path / "proy"
    destino = proyecto / ".claude" / "skills" / "saludar.md"
    destino.parent.mkdir(parents=True)
    destino.write_text(contenido + "\n\n", encoding="utf-8")
    assert _estado_de(proyecto, kit) == "difiere"
