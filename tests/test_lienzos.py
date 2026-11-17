"""Los lienzos: la carpeta como fuente de verdad, y la guarda que protege tu edición."""

from __future__ import annotations

import os
import time

import pytest
import yaml

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


# ── un valor por línea (C-0387) ──────────────────────────────────────────────
#
# El panel lee el cuerpo línea a línea (`static/lienzos.js`): un valor escrito
# en bloque YAML se pintaba como «>-» y el texto se perdía. La puerta de
# publicar lo garantiza: en `decisiones` lo pasa a una línea; en las demás
# plantillas lo rechaza diciendo dónde y cómo escribirlo.


_CON_BLOQUES = """puntos:
  - id: n1
    punto: "contador en memoria"
    justificacion: >-
      dos procesos dan
      el mismo número
    decision: no
  # un comentario que se queda
  - id: n2
    punto: el IVA
    justificacion: |
      está en tres sitios:
      «factura», «ticket» y «resumen»
    decision: pendiente
    campo_de_manana: 42
otra_cosa: "sin tocar"
"""


def _cuerpo_publicado(titulo: str) -> str:
    return lienzos.leer("pedidos", lienzos.slug(titulo)).cuerpo


def test_un_valor_en_bloque_se_publica_en_una_linea_con_el_texto_entero():
    lienzos.escribir("pedidos", "Con bloques", _CON_BLOQUES, plantilla="decisiones")
    cuerpo = _cuerpo_publicado("Con bloques")

    assert ">-" not in cuerpo and "|\n" not in cuerpo
    assert '    justificacion: "dos procesos dan el mismo número"\n' in cuerpo
    assert ('    justificacion: "está en tres sitios:\\n«factura», «ticket» y «resumen»\\n"\n'
            in cuerpo)
    # Lo leído es lo mismo antes y después: sólo cambia cómo va escrito.
    antes = yaml.load(_CON_BLOQUES, Loader=yaml.BaseLoader)
    assert yaml.load(cuerpo, Loader=yaml.BaseLoader) == antes


def test_un_valor_que_sigue_en_la_linea_de_abajo_tambien():
    cuerpo = ("puntos:\n  - id: n1\n    punto: esto es plano\n      y sigue aquí\n"
              "    decision: pendiente\n")
    lienzos.escribir("pedidos", "Sigue abajo", cuerpo, plantilla="decisiones")

    assert _cuerpo_publicado("Sigue abajo") == (
        'puntos:\n  - id: n1\n    punto: "esto es plano y sigue aquí"\n'
        "    decision: pendiente\n")


def test_un_cuerpo_que_ya_va_en_lineas_no_cambia_ni_un_byte():
    """Ni las comillas, ni los comentarios, ni un lienzo que YAML estricto no
    acepta pero el panel lee bien (dos puntos dentro de un valor sin comillas:
    hay uno así entre los de verdad)."""
    for cuerpo in (
        'puntos:\n  - id: n1\n    punto: \'simple\'   # nota\n    decision: si\n',
        "puntos:\n  - id: n1\n    punto: el plazo: viernes\n    decision: pendiente\n",
        "- Validar en el servidor\n- Avisar en la misma pantalla\n",
        "texto suelto\nque no es YAML de nada\n",
    ):
        assert lienzos.normalizar_cuerpo("decisiones", cuerpo) == cuerpo


def test_decision_no_sigue_siendo_no_tras_normalizar():
    """Con `safe_load`, `decision: no` sería `False`: se carga todo como texto
    (`BaseLoader`) y además esa línea ni se reescribe."""
    cuerpo = lienzos.normalizar_cuerpo("decisiones", _CON_BLOQUES)
    assert "    decision: no\n" in cuerpo
    assert "False" not in cuerpo and "false" not in cuerpo


def test_los_campos_que_el_hub_no_conoce_sobreviven_a_normalizar():
    cuerpo = lienzos.normalizar_cuerpo("decisiones", _CON_BLOQUES)
    assert "    campo_de_manana: 42\n" in cuerpo
    assert 'otra_cosa: "sin tocar"\n' in cuerpo
    assert "  # un comentario que se queda\n" in cuerpo


_GRAFO_CON_BLOQUE = ("orientacion: >-\n  vertical\npiezas:\n"
                     "  - {id: a, tipo: entrada, nombre: A}\n")


@pytest.mark.parametrize("plantilla, cuerpo, linea, clave", [
    ("comparativa", "criterios: [coste, rapidez]\nopciones:\n  - nombre: A\n"
                    "    nota: >-\n      la barata\n      pero lenta\n", 4, "nota"),
    ("pasos", _GRAFO_CON_BLOQUE, 1, "orientacion"),
    ("arquitectura", _GRAFO_CON_BLOQUE, 1, "orientacion"),
])
def test_un_bloque_en_otra_plantilla_se_rechaza_diciendo_la_linea_y_como_escribirlo(
        plantilla, cuerpo, linea, clave):
    """Sólo en una clave que el panel lee: ahí se pintaría el «>-»."""
    with pytest.raises(ValueError) as exc:
        lienzos.escribir("pedidos", "Comparar", cuerpo, plantilla=plantilla)
    mensaje = str(exc.value)
    assert f"línea {linea}" in mensaje and f"«{clave}»" in mensaje
    assert "en una línea" in mensaje and "\\n" in mensaje
    assert lienzos.leer("pedidos", "comparar") is None


def test_un_bloque_que_yaml_no_entiende_se_rechaza_y_no_se_publica():
    cuerpo = "puntos:\n  - id: n1\n    justificacion: |\n      uno\n   - dos: [\n"
    with pytest.raises(ValueError, match="«justificacion»"):
        lienzos.escribir("pedidos", "Roto", cuerpo, plantilla="decisiones")
    assert lienzos.leer("pedidos", "roto") is None


# ── Sólo lo que rompe al panel (C-0387, tras la revisión cruzada) ────────────
#
# Un lienzo que antes se publicaba y se veía bien no puede empezar a
# rechazarse. La puerta sólo mira las claves que el panel lee de cada
# plantilla; fuera de `decisiones`, sólo rechaza un indicador de bloque.

_COMPARATIVA_EN_HTML = """<table class="opciones">
<style>
  .opciones td {
    font-family: "Inter",
      sans-serif;
  }
</style>
<tr><td>A</td><td>B</td></tr>
</table>
"""

_ARQUITECTURA_CON_NOTA = """plantilla: arquitectura
nota: lo que falta por decidir
  - si la cola va antes
  - quién la vigila
piezas:
  - {id: a, tipo: entrada, nombre: "A"}
  - {id: b, tipo: computo, nombre: "B"}
flujo:
  - a -> b
"""


@pytest.mark.parametrize("plantilla, cuerpo", [
    ("comparativa", _COMPARATIVA_EN_HTML),
    ("arquitectura", _ARQUITECTURA_CON_NOTA),
])
def test_un_cuerpo_que_el_panel_leia_bien_se_sigue_publicando_tal_cual(plantilla, cuerpo):
    """Los dos casos del revisor: daban 400. El panel los enseñaba (crudo el
    HTML, dibujada la arquitectura: `nota` no la lee)."""
    lienzos.escribir("pedidos", "Tal cual", cuerpo, plantilla=plantilla)
    assert lienzos.leer("pedidos", "tal-cual").cuerpo == cuerpo


def test_en_decisiones_lo_que_el_panel_no_lee_tampoco_se_toca():
    """El HTML o el markdown publicados con la plantilla por omisión se ven
    crudos: un valor partido de algo que no es un punto no se reescribe ni
    tumba la publicación."""
    lienzos.escribir("pedidos", "Html", _COMPARATIVA_EN_HTML, plantilla="decisiones")
    assert lienzos.leer("pedidos", "html").cuerpo == _COMPARATIVA_EN_HTML


#: Los ejemplos de las plantillas del kit `lienzos`, tal cual (13-nov).
_EJEMPLOS_DEL_KIT = {
    "decisiones": """puntos:
  - id: n1
    punto: "Las facturas se numeran con un contador en memoria"
    justificacion: "Dos procesos a la vez dan el mismo número. Ya pasó: dos facturas con el 1042."
    propone: "Pasar el contador a una secuencia de la base."
    decision: pendiente
  - id: n2
    punto: "Los importes son float"
    justificacion: "0,1 + 0,2 no da 0,3. Acaba en un descuadre que nadie sabe explicar."
    propone: "Migrar a decimal. Toca la base y el modelo."
    decision: pendiente
""",
    "arquitectura": """plantilla: arquitectura
orientacion: auto          # auto | horizontal | vertical  (opcional)
piezas:
  - {id: apigw, tipo: entrada, nombre: "API Gateway /pedidos"}
  - {id: l1, tipo: computo, nombre: "λ validar"}
  - {id: q1, tipo: cola, nombre: "SQS pedidos"}
  - {id: db1, tipo: almacen, nombre: "Aurora pedidos"}
flujo:
  - apigw -> l1        # flujo: lo que empuja el trabajo hacia adelante
  - l1 -> q1
  - l1 ~> db1          # lectura: consulta algo y sigue
""",
    "comparativa": """plantilla: comparativa
criterios: [coste, "a quién bloquea", reversible]
opciones:
  - nombre: "Migrar ahora"
    valores: ["2 días", "a todo el equipo", "no"]
    nota: "hay que parar los despliegues"
  - nombre: "Migrar por módulos"
    valores: ["2 semanas", "a nadie", "sí"]
  - nombre: "No migrar"
    valores: ["0", "a nadie", "sí"]
    nota: "la deuda sigue creciendo"
eleccion: "Migrar por módulos"
porque: "es el único reversible sin parar a nadie"
""",
    "pasos": """plantilla: pasos
piezas:
  - {id: from, tipo: entrada, nombre: "1 · FROM / JOIN"}
  - {id: where, tipo: computo, nombre: "2 · WHERE"}
  - {id: select, tipo: cola, nombre: "5 · SELECT"}
flujo:
  - from -> where
  - where -> select
""",
}


@pytest.mark.parametrize("plantilla", sorted(_EJEMPLOS_DEL_KIT))
def test_los_ejemplos_de_las_plantillas_del_kit_se_publican_sin_cambiar(plantilla):
    cuerpo = _EJEMPLOS_DEL_KIT[plantilla]
    assert lienzos.normalizar_cuerpo(plantilla, cuerpo) == cuerpo


def test_las_claves_que_mira_la_puerta_son_las_que_lee_el_panel():
    """La puerta decide con `CLAVES_DEL_PANEL`; si el panel deja de leer una
    clave o la renombra, esto lo dice en vez de rechazar por algo que ya no
    rompe nada."""
    import re
    from pathlib import Path

    js = (Path(lienzos.__file__).parent / "static" / "lienzos.js").read_text(encoding="utf-8")
    for plantilla, claves in lienzos.CLAVES_DEL_PANEL.items():
        for clave in claves:
            assert re.search(rf"\b{clave}\b", js), (plantilla, clave)
