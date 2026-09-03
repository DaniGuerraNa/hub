"""Los lienzos: la carpeta como fuente de verdad, y la guarda que protege tu edición."""

from __future__ import annotations

import os
import time

import pytest

from hub import lienzos


def _publicar(**cambios):
    args = dict(proyecto_id="pedidos", titulo="Flujo de pedidos",
                cuerpo="piezas: []\n", plantilla="arquitectura", slot="diseño")
    args.update(cambios)
    return lienzos.escribir(**args)


def _envejecer(lienzo, segundos: float):
    """Simula que el archivo se tocó DESPUÉS de publicarse.

    Se mueve el mtime en vez de dormir: dormir cinco segundos por test para
    superar el margen de 2 s convertiría la suite en algo que nadie corre.
    """
    marca = os.stat(lienzo.ruta).st_mtime + segundos
    os.utime(lienzo.ruta, (marca, marca))


# ─────────────────────── dónde viven y cómo se llaman ───────────────────────


def test_el_lienzo_vive_en_la_carpeta_del_proyecto_no_en_la_del_slot():
    lienzo = _publicar()
    assert lienzo.ruta.parent.name == "pedidos"
    assert lienzo.ruta.name == "flujo-de-pedidos.md"
    # El slot se conserva, pero como dato: no compone la ruta.
    assert lienzo.slot == "diseño"
    assert "diseño" not in str(lienzo.ruta)


def test_el_slot_sobrevive_a_releer_el_archivo():
    _publicar()
    assert lienzos.leer("pedidos", "flujo-de-pedidos").slot == "diseño"


def test_el_titulo_se_convierte_en_un_nombre_de_archivo_usable():
    assert lienzos.slug("Revisión de Facturación") == "revision-de-facturacion"
    assert lienzos.slug("λ validar / SQS") == "validar-sqs"
    assert lienzos.slug("¿Qué?  ¡Sí!") == "que-si"


def test_un_titulo_sin_nada_usable_se_rechaza_en_vez_de_crear_un_archivo_raro():
    with pytest.raises(ValueError):
        _publicar(titulo="¿?  ///")


def test_un_id_de_proyecto_con_puntos_suspensivos_no_sale_de_la_carpeta():
    # `../../..` en el id compondría una ruta fuera de HUB_HOME.
    with pytest.raises(ValueError):
        lienzos.carpeta_de("../../etc")


def test_un_id_de_lienzo_invalido_no_lee_nada_en_vez_de_recorrer_el_disco():
    _publicar()
    assert lienzos.leer("pedidos", "../../../etc/passwd") is None


# ─────────────────────── la guarda que protege tu edición ───────────────────


def test_republicar_lo_que_nadie_toco_actualiza_sin_quejarse():
    _publicar()
    segundo = _publicar(cuerpo="piezas: [nueva]\n")
    assert segundo.id == "flujo-de-pedidos"
    assert "nueva" in lienzos.leer("pedidos", "flujo-de-pedidos").cuerpo


def test_republicar_encima_de_TU_edicion_se_niega_y_dice_como_seguir():
    """🔴 El caso que destruye trabajo: tú corriges y él regenera."""
    lienzo = _publicar()
    _envejecer(lienzo, 600)          # lo editaste diez minutos después

    with pytest.raises(lienzos.SinPermiso) as fallo:
        _publicar(cuerpo="lo que él vuelve a generar\n")

    # El mensaje tiene que traer la salida, no sólo la negativa.
    assert "--revisar" in str(fallo.value) and "--forzar" in str(fallo.value)
    # Y sobre todo: tu contenido sigue ahí.
    assert lienzos.leer("pedidos", "flujo-de-pedidos").cuerpo == "piezas: []\n"


def test_con_revisar_se_publica_al_lado_y_no_pisa():
    lienzo = _publicar()
    _envejecer(lienzo, 600)

    nuevo = _publicar(cuerpo="la propuesta nueva\n", revisar=True)

    assert nuevo.id == "flujo-de-pedidos-2"
    assert lienzos.leer("pedidos", "flujo-de-pedidos").cuerpo == "piezas: []\n"
    assert lienzos.leer("pedidos", "flujo-de-pedidos-2").cuerpo == "la propuesta nueva\n"


def test_con_forzar_si_pisa_porque_lo_has_pedido():
    lienzo = _publicar()
    _envejecer(lienzo, 600)
    _publicar(cuerpo="pisado a propósito\n", forzar=True)
    assert lienzos.leer("pedidos", "flujo-de-pedidos").cuerpo == "pisado a propósito\n"


def test_un_lienzo_recien_publicado_no_se_declara_editado_por_ti():
    """CONTROL NEGATIVO de la guarda.

    Sin el margen de 2 s, el propio acto de escribir deja el mtime por encima
    de `publicado_en` y TODA republicación fallaría. Una protección que salta
    siempre se aprende a saltar, y entonces no protege el día que importa.
    """
    lienzo = _publicar()
    assert lienzo.editado_por_el_usuario() is False
    _publicar(cuerpo="otra vez\n")     # no debe levantar SinPermiso


def test_guardar_tu_edicion_no_reinicia_la_marca_de_publicacion():
    """Si `guardar_edicion` refrescara `publicado_en`, la señal se borraría justo
    al crearse y la guarda no saltaría nunca."""
    lienzo = _publicar()
    publicado = lienzo.publicado_en

    lienzos.guardar_edicion(lienzo, "lo que yo escribí\n")
    releido = lienzos.leer("pedidos", "flujo-de-pedidos")
    assert releido.publicado_en == publicado

    _envejecer(releido, 600)
    assert lienzos.leer("pedidos", "flujo-de-pedidos").editado_por_el_usuario() is True


# ─────────────────────── la carpeta es la fuente de verdad ──────────────────


def test_borrar_el_archivo_lo_quita_del_listado_sin_tocar_ningun_indice():
    _publicar()
    _publicar(titulo="Contratos", cuerpo="")
    assert len(lienzos.listar("pedidos")) == 2

    lienzos.leer("pedidos", "contratos").ruta.unlink()
    assert [l.id for l in lienzos.listar("pedidos")] == ["flujo-de-pedidos"]


def test_un_archivo_copiado_a_mano_aparece_sin_registrarlo_en_ninguna_parte():
    _publicar()
    carpeta = lienzos.carpeta_de("pedidos")
    (carpeta / "traido-a-mano.md").write_text(
        "---\ntitulo: Traído a mano\nplantilla: pasos\n---\ncuerpo\n", encoding="utf-8")

    ids = {l.id: l for l in lienzos.listar("pedidos")}
    assert ids["traido-a-mano"].titulo == "Traído a mano"
    assert ids["traido-a-mano"].plantilla == "pasos"


def test_un_frontmatter_roto_no_esconde_el_lienzo():
    """Reventar aquí dejaría el panel vacío sin decir por qué; lo que el usuario
    quiere recuperar es el cuerpo."""
    carpeta = lienzos.carpeta_de("pedidos")
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "roto.md").write_text(
        "---\ntitulo: [sin cerrar\n---\nel cuerpo se salva\n", encoding="utf-8")

    lienzo = lienzos.leer("pedidos", "roto")
    assert lienzo is not None
    assert "el cuerpo se salva" in lienzo.cuerpo


def test_los_campos_que_el_hub_no_conoce_sobreviven_a_reescribir():
    """Una plantilla futura puede añadir campos: republicar no debe borrarlos."""
    lienzo = _publicar()
    # Un campo que este hub aún no entiende, añadido conservando la cabecera.
    texto = lienzo.ruta.read_text(encoding="utf-8")
    lienzo.ruta.write_text(texto.replace("---\n", "---\ninventado: 42\n", 1),
                           encoding="utf-8")
    _envejecer(lienzo, -600)      # lo escribió Claude: no es una edición tuya

    _publicar(cuerpo="nuevo\n")

    final = lienzo.ruta.read_text(encoding="utf-8")
    assert "inventado: 42" in final
    assert "nuevo" in final


def test_un_lienzo_sin_marca_de_publicacion_no_se_pisa():
    """🔴 Ante la duda, no se destruye.

    Un archivo traído a mano —o uno cuyo frontmatter se rompió al editarlo fuera
    de la web— no tiene `publicado_en`. Leerlo como «no consta que sea suyo,
    luego puedo pisarlo» convertía esos dos casos en los ÚNICOS donde republicar
    borra sin avisar, que es justo al revés de como debe fallar esto.
    """
    carpeta = lienzos.carpeta_de("pedidos")
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "traido.md").write_text("lo puse yo a mano\n", encoding="utf-8")

    with pytest.raises(lienzos.SinPermiso):
        _publicar(titulo="traido", cuerpo="lo que él genera\n")

    assert (carpeta / "traido.md").read_text(encoding="utf-8") == "lo puse yo a mano\n"


def test_sin_carpeta_el_listado_es_vacio_y_no_revienta():
    assert lienzos.listar("proyecto-que-no-existe") == []
    assert lienzos.todos() == []


# ─────────────────────── buscar entre proyectos ─────────────────────────────


def test_buscar_encuentra_lienzos_de_otros_proyectos():
    """El panel enseña los del proyecto; buscar sirve justamente para lo demás."""
    _publicar()
    lienzos.escribir(proyecto_id="estudio", titulo="Orden de ejecución SQL",
                     plantilla="pasos", slot="sql")

    assert [l.id for l in lienzos.buscar("sql")] == ["orden-de-ejecucion-sql"]
    assert [l.id for l in lienzos.buscar("FLUJO")] == ["flujo-de-pedidos"]
    assert lienzos.buscar("no-existe-esto") == []


def test_buscar_sin_texto_no_devuelve_el_mundo_entero():
    _publicar()
    assert lienzos.buscar("") == []
    assert lienzos.buscar("   ") == []


def test_el_listado_va_del_mas_reciente_al_mas_viejo():
    primero = _publicar(titulo="Viejo")
    time.sleep(0.01)
    _publicar(titulo="Nuevo")
    _envejecer(primero, -600)

    assert [l.titulo for l in lienzos.listar("pedidos")] == ["Nuevo", "Viejo"]


# ── archivar ──────────────────────────────────────────────────────────────────
#
# El panel listaba todo lo del proyecto para siempre y el hub no poda nada solo
# (principio 9). Con dos ya cuesta: el que terminaste de usar estorba al que
# estás usando.


def test_archivar_lo_saca_de_la_lista_sin_borrarlo():
    _publicar(titulo="Uno", cuerpo="a: 1\n")
    _publicar(titulo="Dos", cuerpo="b: 2\n")

    lienzos.archivar("pedidos", "uno")

    assert [l.id for l in lienzos.listar("pedidos")] == ["dos"]
    assert [l.id for l in lienzos.listar("pedidos", archivados=True)] == ["uno"]
    assert lienzos.leer("pedidos", "uno").cuerpo.strip() == "a: 1"


def test_desarchivar_lo_devuelve():
    _publicar(titulo="Uno", cuerpo="a: 1\n")
    lienzos.archivar("pedidos", "uno")
    lienzos.archivar("pedidos", "uno", archivar=False)

    assert [l.id for l in lienzos.listar("pedidos")] == ["uno"]
    assert lienzos.leer("pedidos", "uno").archivado_en is None


def test_archivar_NO_lo_marca_como_editado_por_ti():
    """🔴 Archivar no es editar.

    `editado_por_el_usuario()` compara el mtime con `publicado_en`, y reescribir
    el archivo para poner la marca lo dejaría «editado por ti» para siempre: la
    protección de `escribir()` saltaría en un lienzo que nadie tocó, y un aviso
    que salta sin motivo se aprende a ignorar. Ése protege de destruir
    correcciones hechas a mano.
    """
    lienzo = _publicar(titulo="Uno", cuerpo="a: 1\n")

    # Se envejece la publicación Y el archivo a la vez: un lienzo de hace meses
    # que nadie ha tocado. Sin esto el test pasaba por casualidad —publicar y
    # archivar caían en el mismo segundo y el margen de 2 s lo absorbía— y no
    # detectaba nada; se comprobó quitando la preservación del mtime.
    viejo_iso = "2020-01-01T00:00:00+00:00"
    lienzo.publicado_en = viejo_iso
    lienzos._volcar(lienzo)
    marca = lienzos._a_epoch(viejo_iso)
    os.utime(lienzo.ruta, (marca, marca))
    assert lienzos.leer("pedidos", "uno").editado_por_el_usuario() is False

    lienzos.archivar("pedidos", "uno")

    assert lienzos.leer("pedidos", "uno").editado_por_el_usuario() is False
    # Y por tanto Claude puede seguir republicando sin pedir permiso.
    lienzos.escribir("pedidos", "Uno", "a: 2\n")


def test_archivar_conserva_lo_que_el_hub_no_conoce():
    """El frontmatter se reescribe entero: lo que traiga una plantilla futura
    tiene que sobrevivir, igual que al editar desde la web."""
    lienzo = _publicar(titulo="Uno", cuerpo="a: 1\n")
    lienzo.extra["campo_de_manana"] = 42
    lienzos._volcar(lienzo)

    lienzos.archivar("pedidos", "uno")

    assert lienzos.leer("pedidos", "uno").extra.get("campo_de_manana") == 42


def test_el_buscador_SI_encuentra_los_archivados():
    """Archivar los quita de la lista, no de la memoria. Es la diferencia con
    borrar, y es lo que hace que archivar no dé miedo."""
    _publicar(titulo="Migración a decimal", cuerpo="a: 1\n")
    lienzos.archivar("pedidos", "migracion-a-decimal")

    assert [l.id for l in lienzos.buscar("decimal")] == ["migracion-a-decimal"]


def test_archivar_algo_que_no_existe_no_revienta():
    assert lienzos.archivar("pedidos", "no-existe") is None
