"""Recordar lo caro de leer, y sobre todo dejar de recordarlo a tiempo (C-0310).

Una caché que acierta es fácil; lo que se prueba aquí es que no devuelve
nada viejo: un archivo que cambia, que se reemplaza por otro del mismo
tamaño, que no se pudo leer, o algo que quien llama modificó después.
"""

from __future__ import annotations

import os

import pytest

from hub import recordar

LEIDOS: list[str] = []


def _contar_lineas(ruta):
    LEIDOS.append(ruta.name)
    return {"lineas": ruta.read_text().count("\n")}


def _primera(ruta):
    LEIDOS.append("primera")
    return ruta.read_text().splitlines()[0]


def _que_falla(ruta):
    LEIDOS.append("falla")
    raise ValueError("roto")


def _sin_nada(ruta):
    LEIDOS.append("x")
    return None


@pytest.fixture(autouse=True)
def _limpio():
    LEIDOS.clear()


def test_lo_leido_se_recuerda_mientras_el_archivo_no_cambie(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\ndos\n")
    assert recordar.por_archivo(a, _contar_lineas) == {"lineas": 2}
    assert recordar.por_archivo(a, _contar_lineas) == {"lineas": 2}
    assert LEIDOS == ["a.txt"]


def test_un_archivo_que_crece_se_vuelve_a_leer(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    recordar.por_archivo(a, _contar_lineas)
    with a.open("a") as f:
        f.write("dos\n")
    assert recordar.por_archivo(a, _contar_lineas) == {"lineas": 2}
    assert LEIDOS == ["a.txt", "a.txt"]


def test_otro_archivo_con_el_mismo_tamano_y_la_misma_fecha_se_vuelve_a_leer(tmp_path):
    """Escribir aparte y renombrar encima: misma fecha y tamaño, otro inodo."""
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    os.utime(a, ns=(1_000_000_000, 1_000_000_000))
    recordar.por_archivo(a, _contar_lineas)
    nuevo = tmp_path / "nuevo.txt"
    nuevo.write_text("d\no\n")
    os.utime(nuevo, ns=(1_000_000_000, 1_000_000_000))
    os.replace(nuevo, a)
    assert recordar.por_archivo(a, _contar_lineas) == {"lineas": 2}


def test_mutar_lo_devuelto_no_cambia_lo_recordado(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    primera = recordar.por_archivo(a, _contar_lineas, copia=dict)
    primera["proyecto_id"] = "otro"
    segunda = recordar.por_archivo(a, _contar_lineas, copia=dict)
    assert segunda == {"lineas": 1}
    assert LEIDOS == ["a.txt"]


def test_lo_que_falla_al_leer_no_se_recuerda(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    for _ in range(2):
        with pytest.raises(ValueError):
            recordar.por_archivo(a, _que_falla)
    assert LEIDOS == ["falla", "falla"]


def test_sin_archivo_se_lee_cada_vez_y_decide_quien_lee(tmp_path):
    assert recordar.por_archivo(tmp_path / "no-esta", _sin_nada) is None
    assert recordar.por_archivo(tmp_path / "no-esta", _sin_nada) is None
    assert LEIDOS == ["x", "x"]


def test_dos_lectores_del_mismo_archivo_no_se_pisan(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\ndos\n")
    assert recordar.por_archivo(a, _contar_lineas) == {"lineas": 2}
    assert recordar.por_archivo(a, _primera) == "uno"


def test_una_lambda_no_se_puede_recordar(tmp_path):
    """Por identidad no acertaría nunca; por nombre, dos se pisarían."""
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    with pytest.raises(ValueError):
        recordar.por_archivo(a, lambda r: 1)


def test_al_llenarse_sale_lo_que_lleva_mas_tiempo_sin_usarse(tmp_path, monkeypatch):
    monkeypatch.setattr(recordar, "TOPE", 2)
    archivos = []
    for nombre in ("a", "b", "c"):
        archivo = tmp_path / nombre
        archivo.write_text(nombre)
        archivos.append(archivo)
    a, b, c = archivos
    recordar.por_archivo(a, _contar_lineas)
    recordar.por_archivo(b, _contar_lineas)
    recordar.por_archivo(a, _contar_lineas)   # a vuelve a ser la reciente
    recordar.por_archivo(c, _contar_lineas)   # sale b
    LEIDOS.clear()
    recordar.por_archivo(a, _contar_lineas)
    recordar.por_archivo(b, _contar_lineas)
    assert LEIDOS == ["b"]


def test_por_tiempo_recuerda_hasta_el_plazo_y_ni_un_segundo_mas(monkeypatch):
    reloj = [100.0]
    monkeypatch.setattr(recordar.time, "monotonic", lambda: reloj[0])
    calculos = []

    def calcular():
        calculos.append(reloj[0])
        return len(calculos)

    assert recordar.por_tiempo(("x", 1), calcular, 60) == 1
    reloj[0] = 159.9
    assert recordar.por_tiempo(("x", 1), calcular, 60) == 1
    reloj[0] = 160.0
    assert recordar.por_tiempo(("x", 1), calcular, 60) == 2
    assert recordar.por_tiempo(("x", 2), calcular, 60) == 3


def test_ultimo_da_lo_ultimo_que_salio_bien_pasado_el_plazo_y_no_lo_renueva(monkeypatch):
    """C-0435: quien no pudo calcular de nuevo prefiere lo último bueno a
    nada. Un cálculo que lanza no lo pisa, y dárselo no lo hace fresco."""
    reloj = [100.0]
    monkeypatch.setattr(recordar.time, "monotonic", lambda: reloj[0])
    assert recordar.ultimo(("x", 1)) is None
    assert recordar.ultimo(("x", 1), ()) == ()
    recordar.por_tiempo(("x", 1), lambda: ("a",), 60)
    reloj[0] = 1000.0

    def falla():
        raise OSError("EIO")
    with pytest.raises(OSError):
        recordar.por_tiempo(("x", 1), falla, 60)
    assert recordar.ultimo(("x", 1)) == ("a",)
    assert recordar.por_tiempo(("x", 1), lambda: ("b",), 60) == ("b",), "no lo renovó"


def test_olvidar_lo_quita_todo(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    recordar.por_archivo(a, _contar_lineas)
    recordar.olvidar()
    recordar.por_archivo(a, _contar_lineas)
    assert LEIDOS == ["a.txt", "a.txt"]


def _que_no_pudo(ruta):
    LEIDOS.append("nada")
    return None


def test_un_archivo_que_no_dio_nada_se_vuelve_a_leer(tmp_path):
    # Quien lee suele tragarse el fallo y devolver `None`: recordado, un
    # «no pude» (sin permiso, lectura a medias) no se curaba solo.
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    assert recordar.por_archivo(a, _que_no_pudo) is None
    assert recordar.por_archivo(a, _que_no_pudo) is None
    assert LEIDOS == ["nada", "nada"]


def test_cambiar_los_permisos_hace_que_se_lea_otra_vez(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("uno\n")
    recordar.por_archivo(a, _contar_lineas)
    antes = len(LEIDOS)
    os.chmod(a, 0o600)
    os.utime(a, ns=(a.stat().st_atime_ns, a.stat().st_mtime_ns))
    recordar.por_archivo(a, _contar_lineas)
    assert len(LEIDOS) == antes + 1


# ── C-0326: un almacén por lector, cada uno con su tope ──────────────────────
#
# Con un solo almacén de 2048 para todos, un lector que recorre más archivos
# que el tope (el consumo: mil transcripts y subiendo) echa en cada pasada lo
# que va a pedir en la siguiente, en el mismo orden: falla todos los aciertos
# y nadie lo nota, porque el resultado es el mismo, sólo que leyéndolo todo.

def _otro_lector(ruta):
    LEIDOS.append(f"otro:{ruta.name}")
    return ruta.stat().st_size


def _varios(tmp_path, cuantos):
    archivos = []
    for n in range(cuantos):
        archivo = tmp_path / f"{n:02d}.txt"
        archivo.write_text(f"{n}\n")
        archivos.append(archivo)
    return archivos


def test_cada_lector_tiene_su_tope_y_no_echa_lo_de_otro(tmp_path, monkeypatch):
    monkeypatch.setattr(recordar, "TOPE", 3)
    archivos = _varios(tmp_path, 8)
    for archivo in archivos[:3]:
        recordar.por_archivo(archivo, _contar_lineas)
    for archivo in archivos:                    # ocho de otro lector, con su tope
        recordar.por_archivo(archivo, _otro_lector, tope=8)
    LEIDOS.clear()
    for archivo in archivos[:3]:
        recordar.por_archivo(archivo, _contar_lineas)
    for archivo in archivos:
        recordar.por_archivo(archivo, _otro_lector, tope=8)
    assert LEIDOS == [], "un lector echó lo recordado por el otro, o su tope no le valió"


def test_con_mas_archivos_que_el_tope_por_omision_el_segundo_recorrido_acierta_todo(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(recordar, "TOPE", 4)
    archivos = _varios(tmp_path, 10)
    tope = max(recordar.TOPE, 2 * len(archivos))
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas, tope=tope)
    LEIDOS.clear()
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas, tope=tope)
    assert LEIDOS == []


def test_sin_subir_el_tope_un_recorrido_mas_largo_que_el_no_acierta_nada(tmp_path, monkeypatch):
    """El fallo silencioso que el `tope` por lector existe para evitar: se
    deja escrito para que quien recuerde muchos archivos sepa que lo pide."""
    monkeypatch.setattr(recordar, "TOPE", 4)
    archivos = _varios(tmp_path, 10)
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas)
    LEIDOS.clear()
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas)
    assert len(LEIDOS) == 10


def test_lo_que_ya_no_se_pide_es_lo_primero_que_sale_al_llenarse(tmp_path):
    """Un transcript podado deja de pedirse: se queda el último de la fila y
    sale antes que ninguno de los que sí se siguen leyendo."""
    archivos = _varios(tmp_path, 6)
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas, tope=6)
    vivos = archivos[2:]
    nuevos = [tmp_path / "n1.txt", tmp_path / "n2.txt"]
    for nuevo in nuevos:
        nuevo.write_text("x\n")
    for archivo in vivos + nuevos:
        recordar.por_archivo(archivo, _contar_lineas, tope=6)
    LEIDOS.clear()
    for archivo in vivos + nuevos:
        recordar.por_archivo(archivo, _contar_lineas, tope=6)
    assert LEIDOS == []


def test_quedarse_con_suelta_lo_que_ya_no_esta_y_solo_de_ese_lector(tmp_path):
    """Un transcript podado no vuelve a pedirse: sin esto lo suyo seguía
    recordado hasta que el almacén se llenara, que con el tope al doble de
    los archivos puede no pasar nunca."""
    archivos = _varios(tmp_path, 4)
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas)
        recordar.por_archivo(archivo, _otro_lector)
    assert recordar.quedarse_con(_contar_lineas, archivos[:2]) == 2
    LEIDOS.clear()
    for archivo in archivos:
        recordar.por_archivo(archivo, _contar_lineas)
        recordar.por_archivo(archivo, _otro_lector)
    assert LEIDOS == ["02.txt", "03.txt"], "soltó de más, de menos o lo de otro lector"
    assert recordar.quedarse_con(_primera, archivos) == 0      # un lector que no recordó nada
