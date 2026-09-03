"""El CLI de kits: lo que de verdad teclea la gente.

Hasta la auditoría del 1 de septiembre este archivo no existía. `kits.py` y
`catalogo.py` tenían 59 tests entre los dos, y `listar`, `instalar`, `ruta`,
`estado`, `arbol` y `verificar` —la única superficie que `FLUJOS.md` y las tres
skills mandan usar— tenían **cobertura cero**.

No es un detalle de higiene: es la causa de dos de los defectos encontrados. El
arreglo de los kits en desarrollo se hizo en `estado` y no se replicó en
`arbol`, y nada lo detectó; y `instalar base 99.9` devolvía éxito para una
versión que no existe.
"""

from __future__ import annotations

import pytest

from hub import config, kits, kits_cli


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Un HUB_HOME y un HUB_KITS propios, sin tocar los de nadie."""
    monkeypatch.setattr(config, "HUB_HOME", tmp_path / "home")
    monkeypatch.setattr(config, "HUB_KITS", tmp_path / "kits")
    (tmp_path / "home").mkdir()
    (tmp_path / "kits").mkdir()
    return tmp_path


def _kit_en_desarrollo(raiz):
    """Un kit que provee una capacidad y pide otra que nadie da."""
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "avisar.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (raiz / "kit.yml").write_text(
        'id: endev\nversion: "0.1"\n'
        "expone:\n  - id: notificar#enviar-mensaje\n    tipo: script\n"
        "    ruta: avisar.sh\n"
        "consume:\n  - id: inexistente#nadie-la-da\n",
        encoding="utf-8",
    )


class _ProyectoKit:
    """Lo mínimo que `resolver_en_desarrollo` mira del registro."""

    def __init__(self, id_, asiento):
        self.id = id_
        self.tipo = "kit"
        self.asiento = str(asiento)


# ── arbol ────────────────────────────────────────────────────────────────────


def test_arbol_ve_los_kits_en_desarrollo(entorno, monkeypatch, capsys):
    """🔴 El defecto: `arbol` sólo miraba los instalados y mentía dos veces.

    Decía que nadie provee `notificar#enviar-mensaje` cuando el kit que la
    provee estaba abierto en el registro, y **callaba** que ese mismo kit pide
    una capacidad obligatoria sin proveedor — saliendo con código 0.
    """
    raiz = entorno / "endev"
    _kit_en_desarrollo(raiz)
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_ProyectoKit("endev", raiz)]
    )

    codigo = kits_cli.arbol()
    salida = capsys.readouterr().out

    assert "notificar#enviar-mensaje" in salida, "no vio la capacidad que sí existe"
    assert "inexistente#nadie-la-da" in salida, "calló una obligatoria sin proveedor"
    assert codigo == 1, "una obligatoria sin proveedor no puede salir con éxito"


def test_arbol_sin_nada_lo_dice_y_no_falla(entorno, monkeypatch, capsys):
    monkeypatch.setattr(kits_cli.registry, "cargar", lambda: [])
    assert kits_cli.arbol() == 0
    assert "No hay kits" in capsys.readouterr().out


def test_un_registro_roto_no_ciega_al_arbol(entorno, monkeypatch, capsys):
    """El árbol es un instrumento: prefiere medir de menos a no medir."""
    def explota():
        raise RuntimeError("registro ilegible")

    monkeypatch.setattr(kits_cli.registry, "cargar", explota)
    assert kits_cli.arbol() == 0


def test_un_manifiesto_roto_se_dice_en_voz_alta(entorno, monkeypatch, capsys):
    """Si desaparece en silencio, sus capacidades expuestas se esfuman con él
    y los demás kits salen con falsos «sin proveedor»."""
    raiz = entorno / "roto"
    raiz.mkdir()
    (raiz / "kit.yml").write_text("esto: no es un kit\n", encoding="utf-8")
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_ProyectoKit("roto", raiz)]
    )
    kits_cli.arbol()
    assert "manifiesto inválido" in capsys.readouterr().err


# ── la versión se comprueba, también en el kit interno ───────────────────────


@pytest.mark.parametrize("version", ["99.9", "2.0", "pepino"])
def test_instalar_una_version_que_no_existe_falla(entorno, version, capsys):
    """🔴 Antes devolvía éxito y la ruta de la única versión que hay.

    Un consumidor que declarase `base: 99.9` mediría su deriva contra la 1.0
    creyendo estar en otra — justo lo que `kits.yml` promete que no pasa.
    """
    assert kits_cli.instalar(kits.ID_BASE, version) == 1
    assert "no existe" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["99.9", "pepino"])
def test_la_ruta_de_una_version_que_no_existe_falla(entorno, version, capsys):
    assert kits_cli.ruta(kits.ID_BASE, version) == 1
    assert "no existe" in capsys.readouterr().err


def test_la_version_buena_sigue_funcionando(entorno, capsys):
    """El control positivo: endurecer no puede romper el caso normal."""
    catalogada = kits.catalogo()[kits.ID_BASE]["version"]
    assert kits_cli.instalar(kits.ID_BASE, catalogada) == 0
    assert kits_cli.ruta(kits.ID_BASE, None) == 0
    assert "semillas/base" in capsys.readouterr().out


# ── códigos de salida: el CLI se encadena en scripts ────────────────────────


def test_un_kit_que_no_esta_en_el_catalogo_falla(entorno, capsys):
    assert kits_cli.instalar("no-existe-jamas", None) == 1
    assert "no está en el catálogo" in capsys.readouterr().err


def test_listar_funciona_con_el_catalogo_por_defecto(entorno, capsys):
    assert kits_cli.listar() == 0
    assert kits.ID_BASE in capsys.readouterr().out


# ── `verificar` comprueba lo que el kit PROMETE, no sólo lo que copia ────────


def _kit(tmp_path, cuerpo, archivos=()):
    raiz = tmp_path / "probeta"
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "kit.yml").write_text(cuerpo, encoding="utf-8")
    for rel in archivos:
        f = raiz / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("contenido\n", encoding="utf-8")
    return raiz


def test_un_origen_que_es_carpeta_se_denuncia(entorno, tmp_path, capsys):
    """🔴 Era un instrumento en verde que no medía nada.

    `_hash` se tragaba el `IsADirectoryError` —es un `OSError`— y devolvía None
    en los dos lados; `None == None` daba «igual». «Quiero propagar una carpeta
    entera» es un error de novato natural, y el hub lo aplaudía para siempre.
    """
    raiz = _kit(
        tmp_path,
        'id: probeta\nversion: "1.0"\naplica:\n  - origen: skills\n'
        "    destino: .claude/skills\n    modo: materializado\n",
    )
    (raiz / "skills").mkdir()
    assert kits_cli.verificar(str(raiz)) == 1
    assert "es una carpeta" in capsys.readouterr().out


def test_una_capacidad_sin_su_archivo_se_denuncia(entorno, tmp_path, capsys):
    """Se comprobaba `aplica` y no `expone`: un kit podía prometer una
    capacidad cuyo script no existe y salir en verde."""
    raiz = _kit(
        tmp_path,
        'id: probeta\nversion: "1.0"\nexpone:\n  - id: algo#hacer-algo\n'
        "    tipo: script\n    ruta: herramientas/fantasma.sh\n",
    )
    assert kits_cli.verificar(str(raiz)) == 1
    assert "fantasma.sh" in capsys.readouterr().out


def test_un_gancho_de_mantenimiento_fantasma_se_denuncia(entorno, tmp_path, capsys):
    raiz = _kit(
        tmp_path,
        'id: probeta\nversion: "1.0"\nmantenimiento:\n  verificar: no-existe.sh\n',
    )
    assert kits_cli.verificar(str(raiz)) == 1
    assert "no-existe.sh" in capsys.readouterr().out


def test_un_kit_correcto_sigue_pasando(entorno, tmp_path, capsys):
    """El control positivo: endurecer no puede volverse quisquilloso."""
    raiz = _kit(
        tmp_path,
        'id: probeta\nversion: "1.0"\nexpone:\n  - id: algo#hacer-algo\n'
        "    tipo: script\n    ruta: herramientas/real.sh\n"
        "aplica:\n  - origen: skills/uno.md\n    destino: .claude/skills/uno.md\n"
        "    modo: materializado\n",
        archivos=("herramientas/real.sh", "skills/uno.md"),
    )
    assert kits_cli.verificar(str(raiz)) == 0


@pytest.mark.parametrize("version", ["1.10", "2.0", "1.0"])
def test_una_version_sin_comillas_se_rechaza(entorno, tmp_path, version):
    """🔴 YAML lee `1.10` como el número 1.1 y `str()` lo casaba con el patrón.

    El kit se publicaba como `v1.10`, la carpeta se llamaba `1.10`, y el hub
    trabajaba con `1.1`: `resolver` devolvía None y el consumidor quedaba
    irresoluble. Un cero que desaparece en silencio.
    """
    raiz = _kit(tmp_path, f"id: probeta\nversion: {version}\n")
    with pytest.raises(kits.KitInvalido, match="comillas"):
        kits.leer_manifiesto(raiz)


@pytest.mark.parametrize("id_malo", ["Mi_Kit_Guay", "MAYUS", "con espacio", "-empieza-mal"])
def test_un_id_con_forma_rara_se_rechaza(entorno, tmp_path, id_malo):
    """El `id` acaba siendo nombre de carpeta y clave del catálogo."""
    raiz = _kit(tmp_path, f'id: "{id_malo}"\nversion: "1.0"\n')
    with pytest.raises(kits.KitInvalido, match="no sirve como `id`"):
        kits.leer_manifiesto(raiz)


# ── choques, desfasados, aplicar y quitar ────────────────────────────────────


def _consumidor(tmp_path, declarados, contenido="contenido de a\n"):
    proy = tmp_path / "proy"
    (proy / ".claude" / "hub").mkdir(parents=True)
    (proy / "docs").mkdir(parents=True)
    (proy / "docs" / "compartido.md").write_text(contenido, encoding="utf-8")
    (proy / ".claude" / "hub" / "kits.yml").write_text(declarados, encoding="utf-8")
    return proy


def _kit_instalado(entorno, id_kit, version, destino="docs/compartido.md"):
    raiz = entorno / "kits" / id_kit / version
    raiz.mkdir(parents=True)
    (raiz / "g.md").write_text("contenido de a\n", encoding="utf-8")
    (raiz / "kit.yml").write_text(
        f'id: {id_kit}\nversion: "{version}"\naplica:\n  - origen: g.md\n'
        f"    destino: {destino}\n    modo: materializado\n",
        encoding="utf-8",
    )
    return raiz


def test_dos_kits_que_escriben_el_mismo_archivo_se_denuncian(
    entorno, tmp_path, monkeypatch, capsys
):
    """🔴 Dejaba el proyecto en un estado imposible de arreglar.

    Aplicar uno deja al otro en `difiere`, aplicar el otro deshace el primero, y
    el hub lo presentaba como dos diagnósticos independientes: quien lo veía
    sólo sabía que algo no cuadraba, no que se estaban pisando.
    """
    _kit_instalado(entorno, "choca-a", "1.0")
    _kit_instalado(entorno, "choca-b", "1.0")
    proy = _consumidor(
        tmp_path,
        'kits:\n  - id: choca-a\n    version: "1.0"\n'
        '  - id: choca-b\n    version: "1.0"\n',
    )
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_Consumidor("proy", proy)]
    )

    codigo = kits_cli.estado(None)
    salida = capsys.readouterr().out
    assert "escriben los dos en" in salida
    assert "choca-a" in salida and "choca-b" in salida
    assert codigo == 1, "un choque no puede salir con éxito"


def test_los_apuntadores_no_chocan_entre_si(entorno, tmp_path):
    """Se componen en un solo bloque del `CLAUDE.md`: ahí no se estorban.

    Es el control que evita convertir el aviso en ruido permanente.
    """
    a = _kit_instalado(entorno, "ap-a", "1.0")
    b = _kit_instalado(entorno, "ap-b", "1.0")
    for raiz in (a, b):
        texto = (raiz / "kit.yml").read_text(encoding="utf-8")
        (raiz / "kit.yml").write_text(
            texto.replace("materializado", "apuntador"), encoding="utf-8"
        )
    manifiestos = [kits.leer_manifiesto(a), kits.leer_manifiesto(b)]
    assert kits.colisiones(manifiestos) == {}


def test_un_consumidor_atrasado_se_marca_desfasado(
    entorno, tmp_path, monkeypatch, capsys
):
    """Lo que le faltaba a `mantener-kit` para ser ejecutable.

    El procedimiento dice «aplica a cada consumidor, uno por uno» y no había
    ninguna forma de saber cuáles lo estaban: se leía a mano el `kits.yml` de
    cada proyecto.
    """
    _kit_instalado(entorno, "solo", "1.0")
    _kit_instalado(entorno, "solo", "1.2")
    proy = _consumidor(tmp_path, 'kits:\n  - id: solo\n    version: "1.0"\n')
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_Consumidor("proy", proy)]
    )

    assert kits_cli.estado(None) == 1
    assert "DESFASADO: hay 1.2" in capsys.readouterr().out


def test_al_dia_no_se_marca_desfasado(entorno, tmp_path, monkeypatch, capsys):
    _kit_instalado(entorno, "solo", "1.0")
    proy = _consumidor(tmp_path, 'kits:\n  - id: solo\n    version: "1.0"\n')
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_Consumidor("proy", proy)]
    )
    kits_cli.estado(None)
    assert "DESFASADO" not in capsys.readouterr().out


def test_aplicar_imprime_el_plan_y_no_escribe(entorno, tmp_path, monkeypatch, capsys):
    """🔴 `prompt_aplicar` era código muerto fuera de los tests.

    El hub calculaba el plan entero y no lo enseñaba por ninguna salida:
    aplicar un kit se hacía a mano, unos quince pasos. Y sigue sin escribir,
    que no es una limitación — es la primera regla del hub.
    """
    _kit_instalado(entorno, "solo", "1.0")
    proy = _consumidor(tmp_path, 'kits:\n  - id: solo\n    version: "1.0"\n',
                       contenido="algo distinto\n")
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_Consumidor("proy", proy)]
    )

    assert kits_cli.aplicar("solo", "proy") == 0
    salida = capsys.readouterr().out
    assert "docs/compartido.md" in salida and "actualizar" in salida
    assert "no escribe" in salida
    # Lo que importa: el archivo del consumidor sigue como estaba.
    assert (proy / "docs" / "compartido.md").read_text() == "algo distinto\n"


def test_quitar_dice_que_queda_suelto_y_no_borra(entorno, tmp_path, monkeypatch, capsys):
    """La respuesta útil no es «hecho», es la lista: un kit deja archivos que
    igual siguen haciendo falta, y decidirlo es del usuario."""
    _kit_instalado(entorno, "solo", "1.0")
    proy = _consumidor(tmp_path, 'kits:\n  - id: solo\n    version: "1.0"\n')
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_Consumidor("proy", proy)]
    )

    assert kits_cli.quitar("solo", "proy") == 0
    assert "docs/compartido.md" in capsys.readouterr().out
    assert (proy / "docs" / "compartido.md").exists(), "borró un archivo"


def test_quitar_un_kit_que_el_proyecto_no_declara_falla(
    entorno, tmp_path, monkeypatch, capsys
):
    proy = _consumidor(tmp_path, "kits: []\n")
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_Consumidor("proy", proy)]
    )
    assert kits_cli.quitar("solo", "proy") == 1


class _Consumidor:
    """Un proyecto normal del registro (no un kit)."""

    def __init__(self, id_, asiento):
        self.id = id_
        self.nombre = id_
        self.tipo = "proyecto"
        self.asiento = str(asiento)

    def todas_las_rutas(self):
        return [self.asiento]


def test_verificar_ve_los_kits_en_desarrollo(entorno, monkeypatch, capsys):
    """🔴 El mismo defecto que tenía `arbol`, en otro comando.

    `verificar <id>` sólo resolvía los instalados, así que fallaba con «no
    encuentro» justo mientras escribes el kit — que es cuando más se verifica.
    El arreglo estaba hecho en `estado` y en `arbol` y aquí no; salió aplicando
    el primer kit a un consumidor real.
    """
    raiz = entorno / "endev"
    _kit_en_desarrollo(raiz)
    monkeypatch.setattr(
        kits_cli.registry, "cargar", lambda: [_ProyectoKit("endev", raiz)]
    )

    assert kits_cli.verificar("endev") == 0
    assert "manifiesto válido" in capsys.readouterr().out


def test_verificar_un_id_que_no_existe_sigue_fallando(entorno, monkeypatch, capsys):
    """Resolver más no puede volverse resolver cualquier cosa."""
    monkeypatch.setattr(kits_cli.registry, "cargar", lambda: [])
    assert kits_cli.verificar("no-existe") == 1


# ── instalar un kit que todavía se está escribiendo ──────────────────────────
#
# 🔴 Salió de un caso real el 2026-09-03: aplicar un kit a un proyecto empieza
# por `instalar`, y con un kit en desarrollo el comando moría con un
# `fatal: Remote branch v0.1 not found in upstream origin` de git en crudo.
#
# Ese mensaje no dice qué hacer, y lo que hay que hacer es NADA: el kit ya se
# resuelve desde el registro y `ruta`, `estado` y `aplicar` funcionaban contra
# él. Quien lo intentó leyó el fatal, dio el gestor por roto y aplicó el kit a
# mano. Un paso del procedimiento que falla con el error de otra herramienta se
# lee como «esto no funciona».


@pytest.fixture
def catalogo_en_desarrollo(entorno, monkeypatch, tmp_path):
    """Un kit declarado en el catálogo y sin ningún tag publicado."""
    raiz = tmp_path / "kit-endev"
    _kit_en_desarrollo(raiz)
    monkeypatch.setattr(
        kits, "catalogo",
        lambda: {"endev": {"id": "endev", "version": "0.1", "origen": str(raiz)}},
    )
    monkeypatch.setattr(kits_cli.registry, "cargar", lambda: [_ProyectoKit("endev", raiz)])
    return raiz


def test_instalar_un_kit_EN_DESARROLLO_no_es_un_error(catalogo_en_desarrollo, capsys):
    assert kits_cli.instalar("endev", None) == 0
    salida = capsys.readouterr().out
    assert "EN DESARROLLO" in salida
    assert str(catalogo_en_desarrollo) in salida, "tiene que decir dónde se resuelve"


def test_dice_cómo_congelarlo_en_vez_de_dejarte_a_medias(catalogo_en_desarrollo, capsys):
    """El siguiente paso, escrito: publicar el tag es lo único que convierte un
    kit en desarrollo en una versión medible por otros."""
    kits_cli.instalar("endev", None)
    assert "tag v0.1" in capsys.readouterr().out


def test_la_version_TAMBIEN_se_comprueba_en_desarrollo(catalogo_en_desarrollo, capsys):
    """🔴 Un kit en desarrollo es UNA versión concreta —la de su `kit.yml`—, no
    todas las que le pidas. Sin esto, `instalar endev 9.9` contestaba «en
    desarrollo» y salía con éxito, y quien declarase `9.9` mediría su deriva
    contra la 0.1 creyendo estar en otra."""
    assert kits_cli.instalar("endev", "9.9") == 1
    assert "no existe" in capsys.readouterr().err


def test_lo_ya_instalado_se_dice_aunque_el_kit_se_este_escribiendo(
    catalogo_en_desarrollo, entorno, capsys
):
    """Las dos cosas conviven: la copia congelada de la 0.1 en disco y el repo
    donde nace la siguiente. Confundirlas haría creer que no hay nada instalado
    cuando sí lo hay."""
    kits.ruta_de("endev", "0.1").mkdir(parents=True)
    assert kits_cli.instalar("endev", None) == 0
    salida = capsys.readouterr().out
    assert "ya estaba instalado" in salida
    assert "EN DESARROLLO" not in salida


def test_un_kit_NORMAL_sin_su_tag_dice_qué_hacer(entorno, monkeypatch, tmp_path, capsys):
    """El otro camino: si no está en el registro como kit, el fallo de git sigue
    siendo un fallo — pero acompañado de las dos salidas que tiene."""
    raiz = tmp_path / "kit-suelto"
    _kit_en_desarrollo(raiz)
    # Un repo de VERDAD y sin tags: es el caso real. Con una carpeta que no es
    # repo, git se queja de otra cosa —«repository does not exist»— y el test
    # pasaría por el camino equivocado.
    import subprocess
    for orden in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                  ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                   "commit", "-qm", "kit"]):
        subprocess.run(orden, cwd=raiz, capture_output=True, check=False)
    monkeypatch.setattr(
        kits, "catalogo",
        lambda: {"endev": {"id": "endev", "version": "0.1", "origen": str(raiz)}},
    )
    monkeypatch.setattr(kits_cli.registry, "cargar", lambda: [])

    assert kits_cli.instalar("endev", None) == 1
    err = capsys.readouterr().err
    assert "tag v0.1" in err, "hay que decir cómo publicarlo"
    assert "tipo: kit" in err, "y la otra salida: declararlo en desarrollo"
