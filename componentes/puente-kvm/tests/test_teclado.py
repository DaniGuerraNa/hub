"""Lo que se teclea por HID llega al Mac como el mismo texto.

El simulador interpreta los informes como macOS con «U.S.», así que esto
prueba la tabla de `hid` de verdad: si `{` saliera con la tecla equivocada,
el editor tendría otra cosa.
"""

import asyncio

import pytest

from puente_kvm import hid
from puente_kvm.simulador import Simulador


def teclear_en(sim: Simulador, texto: str, distribucion: str = "mac-us") -> None:
    async def correr():
        for p in hid.secuencia(texto, distribucion):
            await sim.informe_teclado(p.modificadores, [p.tecla])
            await sim.informe_teclado(0, [])

    asyncio.run(correr())


def test_todo_el_ascii_imprimible_llega_igual_al_editor():
    sim = Simulador(lineas=[""])
    texto = "".join(chr(i) for i in range(32, 127))
    teclear_en(sim, texto)
    assert sim.editor.lineas == [texto]


def test_los_acentos_la_enie_y_los_signos_de_apertura_llegan_por_teclas_muertas():
    sim = Simulador(lineas=[""])
    texto = "¿Año fiscal? ¡Sí! Conciliación de pingüinos: Ñandú, «O» y 10 €"
    teclear_en(sim, texto)
    assert sim.editor.lineas == [texto]


def test_los_saltos_de_linea_son_enter_y_parten_la_linea():
    sim = Simulador(lineas=[""])
    teclear_en(sim, "BEGIN\n    SELECT 1;\nEND;")
    assert sim.editor.lineas == ["BEGIN", "    SELECT 1;", "END;"]


def test_un_caracter_sin_tecla_impide_teclear_el_texto_entero():
    with pytest.raises(hid.TextoIntraducible) as e:
        hid.secuencia("SELECT 1 -- ✓ revisado")
    assert e.value.caracteres == ["✓"]


def test_los_atajos_se_leen_con_sus_modificadores():
    p = hid.combinacion("cmd+shift+down")
    assert p.modificadores == hid.GUI | hid.SHIFT
    assert p.tecla == hid.TECLAS["down"]
    with pytest.raises(ValueError):
        hid.combinacion("cmd+")
    with pytest.raises(ValueError):
        hid.combinacion("hiper+a")


# ── «Español - ISO» de macOS (generada de la de Apple) ──────────────────────
def test_en_espanol_iso_todo_el_ascii_y_lo_nuestro_llega_igual():
    sim = Simulador(lineas=[""], distribucion="mac-es")
    texto = "".join(chr(i) for i in range(32, 127)) + " ¿Año? ¡Sí! pingüino Ñandú ç Ç € º ª"
    teclear_en(sim, texto, "mac-es")
    assert sim.editor.lineas == [texto]


@pytest.mark.parametrize("caracter, pulsaciones", [
    # Lo que más se teclea en SQL y donde el Mac español difiere de U.S.:
    # comprobado contra la distribución de Apple, no recordado.
    ("@", ["alt+2"]), ("#", ["alt+3"]), ("|", ["alt+1"]), ("\\", ["alt+iso"]),
    ("[", ["alt+["]), ("]", ["alt+]"]), ("{", ["alt+'"]), ("}", ["alt+\\"]),
    ("<", ["`"]), (">", ["shift+`"]), ("=", ["shift+0"]), ("'", ["-"]),
    ("~", ["alt+;", "space"]), ("á", ["'", "a"]), ("ñ", [";"]),
])
def test_en_espanol_iso_los_simbolos_van_donde_los_pone_apple(caracter, pulsaciones):
    assert [str(p) for p in hid.caracter(caracter, "mac-es")] == pulsaciones


def test_la_distribucion_importa_lo_tecleado_para_espanol_no_sale_igual_en_us():
    # Por eso es un ajuste: con el Mac en «U.S.», la tabla española escribe otra cosa.
    sim = Simulador(lineas=[""])
    teclear_en(sim, "SELECT [id] FROM t WHERE a = 'x'", "mac-es")
    assert sim.editor.lineas != ["SELECT [id] FROM t WHERE a = 'x'"]


def test_una_distribucion_que_no_existe_no_se_adivina():
    with pytest.raises(ValueError):
        hid.secuencia("hola", "mac-latam")


# ── lo que se pega desde fuera (C-0466) ─────────────────────────────────────
# Lo copiado de una respuesta de Claude o de un correo trae comillas tipográficas,
# rayas y acentos de todo tipo: antes, con «U.S.», «—» o «“» impedían pegar nada.
COPIADO = "“Listo” — it’s ‘así’… • ç Ç © ® ™ ± ≠ ≤ ≥ ÷ ° · ¿Qué tal? ¡Sí! ñandú, pingüino, À è ô ã õ ë ÿ"


@pytest.mark.parametrize("distribucion", hid.DISTRIBUCIONES)
def test_lo_copiado_de_una_respuesta_se_pega_igual_con_las_dos_distribuciones(distribucion):
    sim = Simulador(lineas=[""], distribucion=distribucion)
    teclear_en(sim, COPIADO, distribucion)
    assert sim.editor.lineas == [COPIADO]


def test_un_acento_suelto_tras_la_letra_se_recompone_antes_de_teclear():
    import unicodedata
    descompuesto = unicodedata.normalize("NFD", "Canción del pingüino")
    assert "́" in descompuesto  # «o» más el acento, como lo da a veces el portapapeles
    sim = Simulador(lineas=[""])
    teclear_en(sim, descompuesto)
    assert sim.editor.lineas == ["Canción del pingüino"]


@pytest.mark.parametrize("caracter, pulsaciones", [
    # Los que ya estaban a mano siguen en sus teclas, y los nuevos más comunes,
    # contrastados con las copias de la distribución de Apple.
    ("á", ["alt+e", "a"]), ("Á", ["alt+shift+y"]), ("ñ", ["alt+n", "n"]), ("Ñ", ["alt+n", "shift+n"]),
    ("ü", ["alt+u", "u"]), ("à", ["alt+`", "a"]), ("ê", ["alt+i", "e"]),
    ("¡", ["alt+1"]), ("¿", ["alt+shift+/"]), ("º", ["alt+0"]), ("ª", ["alt+9"]),
    ("€", ["alt+shift+2"]), ("°", ["alt+shift+8"]), ("…", ["alt+;"]), ("«", ["alt+\\"]), ("»", ["alt+shift+\\"]),
    ("ç", ["alt+c"]), ("Ç", ["alt+shift+c"]), ("—", ["alt+shift+-"]), ("–", ["alt+-"]),
    ("“", ["alt+["]), ("”", ["alt+shift+["]), ("‘", ["alt+]"]), ("’", ["alt+shift+]"]),
])
def test_en_us_los_caracteres_van_donde_los_pone_apple(caracter, pulsaciones):
    assert [str(p) for p in hid.caracter(caracter, "mac-us")] == pulsaciones


def test_en_us_nada_usa_la_tecla_iso_que_un_teclado_ansi_no_tiene():
    assert all(t != "iso" for pasos in hid._MAC_US.values() for _, t in pasos)


@pytest.mark.parametrize("distribucion, tabla", [("mac-us", hid._MAC_US), ("mac-es", hid._MAC_ES)])
def test_la_tabla_entera_va_y_vuelve_por_el_mac_simulado_sin_choques(distribucion, tabla):
    # El simulador sale de las mismas tablas: esto prueba que son coherentes (ninguna
    # tecla da dos caracteres, cada acento compone su letra), no lo que da el Mac de
    # verdad; eso lo contrastan los casos de arriba y el paso 3 con el aparato.
    texto = "".join(c for c in tabla if not c.isspace())
    sim = Simulador(lineas=[""], distribucion=distribucion)
    teclear_en(sim, texto, distribucion)
    assert sim.editor.lineas == [texto]
