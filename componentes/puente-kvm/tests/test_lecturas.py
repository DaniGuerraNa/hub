"""Transcribir, ensamblar por número de línea y verificar con la huella."""

from puente_kvm import huellas, lecturas
from puente_kvm.simulador import huella_sqlserver


def lectura_con(paginas: dict[int, str]) -> lecturas.Lectura:
    l = lecturas.nueva("prueba")
    l.paginas = [lecturas.Pagina(n=n) for n in paginas]
    l.guardar()
    for n, texto in paginas.items():
        lecturas.transcribir(l, n, texto, "claude")
    return l


def test_la_sangria_se_conserva_y_los_espacios_finales_no():
    lineas, errores = lecturas.analizar("1|BEGIN\n2|    SELECT 1;   \n3|")
    assert lineas == [(1, "BEGIN"), (2, "    SELECT 1;"), (3, "")]
    assert errores == []


def test_un_salto_en_la_numeracion_es_un_error_de_la_pagina():
    _, errores = lecturas.analizar("1|a\n2|b\n4|d")
    assert errores == ["los números saltan de 2 a 4"]


def test_las_paginas_solapadas_que_dicen_lo_mismo_se_ensamblan_sin_conflicto():
    l = lectura_con({1: "1|a\n2|b\n3|c", 2: "3|c\n4|d"})
    ens = lecturas.ensamblar(l)
    assert ens.lineas == ["a", "b", "c", "d"]
    assert ens.completo


def test_dos_paginas_que_leen_distinto_la_misma_linea_son_un_conflicto_hasta_resolverlo():
    l = lectura_con({1: "1|a\n2|IF @x = 0", 2: "2|IF @x = O\n3|c"})
    ens = lecturas.ensamblar(l)
    assert [c["linea"] for c in ens.conflictos] == [2]
    assert not ens.completo
    lecturas.resolver(l, 2, "IF @x = 0")
    ens = lecturas.ensamblar(l)
    assert ens.completo and ens.lineas[1] == "IF @x = 0"


def test_una_linea_que_ninguna_pagina_leyo_es_un_hueco():
    l = lectura_con({1: "1|a\n2|b", 2: "5|e\n6|f"})
    ens = lecturas.ensamblar(l)
    assert ens.huecos == [(3, 4)]
    assert not ens.completo


def test_la_huella_de_sql_server_se_reconoce_entre_las_variantes():
    lineas = ["CREATE PROCEDURE x", "AS", "    SELECT 'año';"]
    v = huellas.buscar(lineas, huella_sqlserver(lineas))
    assert v == {"algoritmo": "sha256", "codificacion": "utf-16-le", "fin": "CRLF", "final": False,
                 "hex": huella_sqlserver(lineas)}


def test_un_solo_caracter_mal_leido_hace_que_ninguna_variante_coincida():
    bien = ["IF @Total > 0", "    SELECT 1;"]
    mal = ["IF @Total > O", "    SELECT 1;"]
    assert huellas.buscar(mal, huella_sqlserver(bien)) is None


def test_la_copia_se_da_por_exacta_solo_si_la_huella_coincide():
    l = lectura_con({1: "1|a\n2|b"})
    assert not lecturas.comprobar_huella(l, huella_sqlserver(["a", "B"]))["verificada"]
    r = lecturas.comprobar_huella(l, huella_sqlserver(["a", "b"]))
    assert r["verificada"] and "UTF-16-LE" in r["variante"]


def test_el_identificador_conserva_las_letras_con_tilde_sin_la_tilde():
    assert lecturas.nueva("Conciliación año").id.startswith("conciliacion-ano-")
    assert lecturas.slug("Revisión 2") == "revision-2"
