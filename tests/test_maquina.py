"""La salud del equipo que se queda solo.

Lo que se protege aquí no son las cifras —esas salen del driver y del sistema—
sino **la forma de fallar**: que una medida que no se pudo tomar no pise la
anterior, y que una fuente rota no se lleve por delante a las demás. Las dos
cosas importan porque el mes que esto vale es el mes en que nadie las mira.
"""

from __future__ import annotations

import pytest

from hub import maquina


@pytest.fixture
def sin_windows(monkeypatch):
    """Una máquina sin GPU y sin Windows: Linux pelado, como un CI."""
    for fuente in ("_gpu", "_windows", "_ups"):
        monkeypatch.setattr(maquina, fuente, lambda: (_ for _ in ()).throw(FileNotFoundError()))


def test_sin_gpu_se_siguen_midiendo_los_discos(sin_windows):
    """🔴 Regla dura 14 dentro de la medición: que no haya GPU no puede dejar
    sin medir el disco, que es lo que de verdad se llena."""
    claves = {m.clave for m in maquina.medir()}

    assert "disco.wsl.libre" in claves
    assert "memoria.libre" in claves
    assert not any(c.startswith("gpu") for c in claves)


def test_si_no_se_puede_medir_nada_se_dice_y_no_se_devuelve_una_lista_vacia(monkeypatch):
    """Una lista vacía se escribiría como «cero de todo». El silencio se levanta."""
    for fuente in ("_gpu", "_discos", "_memoria_y_carga", "_windows", "_ups"):
        monkeypatch.setattr(maquina, fuente, lambda: (_ for _ in ()).throw(OSError("no")))

    with pytest.raises(maquina.MaquinaNoMedida):
        maquina.medir()


def test_una_medida_que_no_se_pudo_tomar_conserva_la_anterior(con, monkeypatch):
    """🔴 El modo de fallo caro: un cero que significa «no he mirado».

    Escribiría 0 GB libres en la pantalla y, peor, dispararía una alarma a un
    teléfono que está a 2 000 km.
    """
    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("gpu.temperatura", 62, unidad="°C")])
    maquina.escanear(con)

    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("carga", 0.5)])
    maquina.escanear(con)

    guardadas = maquina.ultimas(con)
    assert guardadas["gpu.temperatura"]["valor"] == 62
    assert guardadas["carga"]["valor"] == 0.5


def test_cada_magnitud_guarda_solo_su_ultima_lectura(con, monkeypatch):
    """No es un histórico: volver a medir lo reconstruye (regla dura 1)."""
    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("gpu.temperatura", 40)])
    maquina.escanear(con)
    monkeypatch.setattr(maquina, "medir", lambda: [maquina.Medida("gpu.temperatura", 75)])
    maquina.escanear(con)

    filas = con.execute("SELECT valor FROM maquina WHERE clave='gpu.temperatura'").fetchall()
    assert [f["valor"] for f in filas] == [75]


def test_el_texto_y_el_numero_conviven_en_la_misma_tabla(con, monkeypatch):
    """La pantalla y las alarmas leen de una sola costura, no de dos."""
    monkeypatch.setattr(maquina, "medir", lambda: [
        maquina.Medida("gpu.nombre", texto="NVIDIA GeForce RTX 4070 Ti"),
        maquina.Medida("gpu.temperatura", 61, unidad="°C"),
    ])
    maquina.escanear(con)

    assert maquina.valor(con, "gpu.temperatura") == 61
    assert maquina.valor(con, "gpu.nombre") is None
    assert maquina.ultimas(con)["gpu.nombre"]["texto"].startswith("NVIDIA")


def test_los_programas_de_windows_se_resuelven_aunque_el_PATH_no_los_traiga(monkeypatch):
    """🔴 La decisión 81 otra vez, en otro sitio.

    `hub-snapshotter` corre bajo systemd, cuyo PATH no trae los caminos de
    interoperabilidad de Windows. Se vio en la primera medición dentro del
    servicio: discos y memoria al día, y la GPU, el SAI y Windows congelados
    diez minutos atrás **sin un solo error a la vista**. Probar a mano no lo
    detecta, porque una shell interactiva sí los encuentra.
    """
    monkeypatch.setattr(maquina.shutil, "which", lambda nombre: None)

    assert maquina._programa("powershell.exe").startswith("/mnt/c/")
    assert maquina._programa("nvidia-smi.exe").startswith("/mnt/c/")
    assert maquina._programa("df") == "df"       # lo que no es de Windows, tal cual


def test_una_fuente_que_falla_lo_dice_en_voz_alta(monkeypatch, capsys):
    """Callarlo es lo que dejó al servicio midiendo la mitad (regla dura 21)."""
    def explota():
        raise FileNotFoundError("nvidia-smi.exe")

    explota.__name__ = "_gpu"
    monkeypatch.setattr(maquina, "_gpu", explota)

    maquina.medir()

    salida = capsys.readouterr().out
    assert "_gpu no midió" in salida and "nvidia-smi.exe" in salida


def test_sin_windows_debajo_se_dice_una_vez_y_no_cada_minuto(monkeypatch, capsys):
    """Instalando en limpio en un Linux sin Windows, el SAI escribía «no existe
    powershell.exe» en el registro cada minuto. No es un fallo: no aplica."""
    monkeypatch.setattr(maquina.shutil, "which", lambda nombre: None)
    monkeypatch.setattr(maquina, "RESPALDOS", {"powershell.exe": "/no/existe/powershell.exe"})
    monkeypatch.setattr(maquina, "_FALTAS_DICHAS", set())
    monkeypatch.setattr(maquina.subprocess, "run",
                        lambda *a, **k: pytest.fail("no debía intentar ejecutarlo"))

    for _ in range(3):
        assert maquina.escanear_ups(None) == 0

    assert capsys.readouterr().out.count("no hay powershell.exe") == 1
