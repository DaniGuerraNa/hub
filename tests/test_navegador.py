"""El navegador de archivos: qué enseña, y sobre todo qué no.

🔴 La mitad de este archivo son intentos de salirse del confín. Un navegador es
un endpoint que recibe una ruta, así que sin confinamiento es `?ruta=/etc/shadow`
—y con la red privada del viaje eso deja de ser teórico, porque el móvil no es
la máquina (decisión 160)—. Los ataques se escriben aquí en vez de confiar en
que `resolve()` haga lo correcto: `resolve()` hace lo correcto, lo que falla es
el ORDEN en que se le llama.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hub import navegador


@pytest.fixture()
def arbol(tmp_path: Path) -> Path:
    """Dos raíces hermanas y una carpeta fuera de las dos."""
    (tmp_path / "raiz/repo-uno/src").mkdir(parents=True)
    (tmp_path / "raiz/repo-uno/.git").mkdir()
    (tmp_path / "raiz/repo-uno/LEEME.md").write_text("hola")
    (tmp_path / "raiz/.oculto").mkdir()
    (tmp_path / "otra-raiz").mkdir()
    (tmp_path / "secreto").mkdir()
    (tmp_path / "secreto/claves.txt").write_text("nada bueno")
    return tmp_path


@pytest.fixture()
def confin(arbol: Path) -> list[Path]:
    return navegador.raices([str(arbol / "raiz"), str(arbol / "otra-raiz")])


# ─────────────────────────── el confinamiento ───────────────────────────


def test_una_ruta_bajo_una_raiz_se_sirve(arbol, confin):
    destino = navegador.resolver(str(arbol / "raiz/repo-uno"), confin)
    assert destino == (arbol / "raiz/repo-uno").resolve()


def test_una_ruta_hermana_de_la_raiz_se_rechaza(arbol, confin):
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(str(arbol / "secreto"), confin)


def test_una_ruta_absoluta_del_sistema_se_rechaza(confin):
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver("/etc", confin)


def test_subir_con_puntos_suspensivos_no_saca_del_confin(arbol, confin):
    """El ataque de libro: `..` sólo desaparece al resolver.

    Si se comprobara el prefijo ANTES de resolver, esta ruta empieza por la raíz
    buena y pasaría el filtro entera.
    """
    ataque = str(arbol / "raiz" / ".." / "secreto")
    assert str(arbol / "raiz") in ataque  # el prefijo bueno está ahí
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(ataque, confin)


def test_un_symlink_que_apunta_fuera_no_deja_salir(arbol, confin):
    """El ataque que no trae `..` y por eso se escapa de las comprobaciones de texto.

    En árboles clonados desde Windows no es una hipótesis.
    """
    puerta = arbol / "raiz/puerta"
    puerta.symlink_to(arbol / "secreto", target_is_directory=True)
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(str(puerta), confin)
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(str(puerta / "claves.txt"), confin)


def test_un_symlink_que_apunta_dentro_si_deja_pasar(arbol, confin):
    """Lo simétrico, que es lo que impide arreglar esto prohibiendo symlinks."""
    atajo = arbol / "raiz/atajo"
    atajo.symlink_to(arbol / "raiz/repo-uno", target_is_directory=True)
    assert navegador.resolver(str(atajo), confin) == (arbol / "raiz/repo-uno").resolve()


def test_una_raiz_que_es_symlink_no_bloquea_lo_que_contiene(arbol):
    """🔴 La otra mitad: resolver el candidato y NO la raíz niega lo legítimo.

    El síntoma sería «el hub no ve mis repos», sin ninguna pista del porqué.
    """
    enlace = arbol / "raiz-enlazada"
    enlace.symlink_to(arbol / "raiz", target_is_directory=True)
    confin = navegador.raices([str(enlace)])
    assert navegador.resolver(str(enlace / "repo-uno"), confin)
    # Y por la ruta real también, que es la misma carpeta con otro nombre.
    assert navegador.resolver(str(arbol / "raiz/repo-uno"), confin)


def test_la_propia_raiz_se_puede_listar(arbol, confin):
    assert navegador.listar(str(arbol / "raiz"), confin)["entradas"]


def test_sin_ninguna_raiz_no_se_sirve_nada(arbol):
    """Un índice vacío no es un índice que lo permite todo."""
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(str(arbol), [])


def test_la_virgulilla_se_expande_antes_de_comprobar(arbol, confin, monkeypatch):
    """`~` sin expandir sería una carpeta literal llamada «~», no la de casa."""
    monkeypatch.setenv("HOME", str(arbol / "raiz"))
    assert navegador.resolver("~/repo-uno", confin) == (arbol / "raiz/repo-uno").resolve()


# ───────────────────────────── el listado ─────────────────────────────


def test_las_carpetas_van_antes_que_los_archivos(arbol, confin):
    nombres = [e["nombre"] for e in navegador.listar(str(arbol / "raiz/repo-uno"), confin)["entradas"]]
    assert nombres == ["src", "LEEME.md"]


def test_un_repositorio_se_marca_como_tal(arbol, confin):
    entradas = navegador.listar(str(arbol / "raiz"), confin)["entradas"]
    assert [e["repo"] for e in entradas if e["nombre"] == "repo-uno"] == [True]


def test_los_ocultos_no_se_listan_pero_se_cuentan(arbol, confin):
    """Esconderlos en silencio haría que una carpeta con sólo dotfiles pareciera vacía."""
    datos = navegador.listar(str(arbol / "raiz"), confin)
    assert datos["ocultos"] == 1
    assert all(not e["nombre"].startswith(".") for e in datos["entradas"])


def test_el_tope_se_dice_en_vez_de_truncar_en_silencio(arbol, confin, monkeypatch):
    monkeypatch.setattr(navegador, "TOPE", 3)
    for i in range(10):
        (arbol / "otra-raiz" / f"cosa-{i:02d}").mkdir()
    datos = navegador.listar(str(arbol / "otra-raiz"), confin)
    assert len(datos["entradas"]) == 3
    assert datos["truncado"] == 7


def test_un_symlink_de_salida_se_enseña_marcado_y_no_como_carpeta_normal(arbol, confin):
    """Se ve que está —está ahí— pero se ve que no se puede entrar."""
    (arbol / "raiz/puerta").symlink_to(arbol / "secreto", target_is_directory=True)
    entradas = navegador.listar(str(arbol / "raiz"), confin)["entradas"]
    puerta = next(e for e in entradas if e["nombre"] == "puerta")
    assert puerta["fuera"] is True


def test_un_archivo_no_se_lista_como_carpeta(arbol, confin):
    with pytest.raises(navegador.NoNavegable):
        navegador.listar(str(arbol / "raiz/repo-uno/LEEME.md"), confin)


def test_lo_que_ya_no_existe_lo_dice_y_no_revienta(arbol, confin):
    with pytest.raises(navegador.NoNavegable):
        navegador.listar(str(arbol / "raiz/fantasma"), confin)


def test_el_tamaño_es_metadato_pero_el_contenido_no_sale_nunca(arbol, confin):
    """🔴 La garantía estructural: ninguna función de este módulo lee un archivo."""
    entradas = navegador.listar(str(arbol / "raiz/repo-uno"), confin)["entradas"]
    leeme = next(e for e in entradas if e["nombre"] == "LEEME.md")
    assert leeme["tamano"] == 4
    assert "hola" not in repr(entradas)
    assert not any("contenido" in e or "texto" in e for e in entradas)


# ───────────────────────── migas y navegación ─────────────────────────


def test_las_migas_se_cortan_en_la_raiz(arbol, confin):
    """Más arriba no hay nada que servir: una miga que lleva a un error sobra."""
    datos = navegador.listar(str(arbol / "raiz/repo-uno/src"), confin)
    assert [m["nombre"] for m in datos["migas"]] == ["raiz", "repo-uno", "src"]


def test_desde_la_raiz_no_se_puede_subir(arbol, confin):
    assert navegador.listar(str(arbol / "raiz"), confin)["arriba"] is None


def test_desde_dentro_se_sube_hasta_la_raiz_y_ahi_se_para(arbol, confin):
    datos = navegador.listar(str(arbol / "raiz/repo-uno"), confin)
    assert datos["arriba"] == str((arbol / "raiz").resolve())


def test_las_migas_eligen_la_raiz_mas_especifica(arbol):
    """El mismo criterio que `registry.Atribuidor`: la más larga gana.

    Con otro criterio, las migas subirían a un sitio distinto del que el resto
    del hub considera dueño de esa carpeta.
    """
    confin = navegador.raices([str(arbol / "raiz"), str(arbol / "raiz/repo-uno")])
    datos = navegador.listar(str(arbol / "raiz/repo-uno/src"), confin)
    assert [m["nombre"] for m in datos["migas"]] == ["repo-uno", "src"]


def test_minimas_colapsa_las_raices_que_cuelgan_de_otra(arbol):
    confin = navegador.raices([
        str(arbol / "raiz"), str(arbol / "raiz/repo-uno"), str(arbol / "otra-raiz"),
    ])
    assert sorted(p.name for p in navegador.minimas(confin)) == ["otra-raiz", "raiz"]


def test_minimas_conserva_un_repo_que_vive_fuera_de_su_asiento(arbol):
    """No es lo mismo que quedarse con los asientos: hay repos sueltos."""
    confin = navegador.raices([str(arbol / "raiz"), str(arbol / "otra-raiz")])
    assert len(navegador.minimas(confin)) == 2


def test_minimas_da_lo_mismo_que_comparar_cada_raiz_con_todas():
    """La forma rápida (por partes) contra la de antes, con las trampas de un
    prefijo de texto: `/a/b` no contiene a `/a/bc`, y `/` lo contiene todo."""
    def a_mano(confin):
        return [r for r in confin if not any(r != o and r.is_relative_to(o) for o in confin)]

    casos = [
        ["/a/b", "/a/bc", "/a/b/c", "/x"],
        ["/a/b/c/d", "/a/b", "/a"],
        ["/", "/a", "/b/c"],
        ["/a/b", "/a/b", "/a/b/c"],
        ["/solo"],
        [],
    ]
    for caso in casos:
        confin = [Path(p) for p in caso]
        assert navegador.minimas(confin) == a_mano(confin), caso


# ─────────────── las rutas declaradas, recordadas (C-0310) ───────────────
#
# 🔴 Lo único que se recuerda es cómo se resuelven las raíces DECLARADAS. La
# ruta que pide quien navega se resuelve y se confina siempre en fresco: estas
# pruebas fijan que recordar el confín no abre nada que no estuviera abierto.


def test_una_ruta_fuera_del_confin_sigue_rechazada_con_las_raices_recordadas(arbol):
    rutas = [str(arbol / "raiz"), str(arbol / "otra-raiz")]
    navegador.raices(rutas)
    confin = navegador.raices(rutas)  # ya de memoria
    for fuera in ("/etc", str(arbol / "secreto"), str(arbol / "raiz/../secreto")):
        with pytest.raises(navegador.FueraDeRaiz):
            navegador.resolver(fuera, confin)


def test_un_enlace_que_pasa_a_apuntar_fuera_se_rechaza_aunque_se_pidiera_antes(arbol):
    """El destino no se recuerda: un enlace dentro de un repo que hace un
    segundo llevaba dentro y ahora lleva fuera se rechaza ya."""
    confin = navegador.raices([str(arbol / "raiz")])
    enlace = arbol / "raiz/atajo"
    enlace.symlink_to(arbol / "raiz/repo-uno", target_is_directory=True)
    assert navegador.listar(str(enlace), confin)["ruta"] == str((arbol / "raiz/repo-uno").resolve())
    enlace.unlink()
    enlace.symlink_to(arbol / "secreto", target_is_directory=True)
    confin = navegador.raices([str(arbol / "raiz")])
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(str(enlace), confin)
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.listar(str(enlace / "claves.txt"), confin)


def test_una_raiz_que_cambia_de_destino_no_abre_lo_nuevo_mientras_se_recuerda(arbol):
    """Lo viejo del confín sólo puede seguir enseñando lo que ya enseñaba:
    lo nuevo, resuelto en fresco, cae fuera de la raíz recordada."""
    raiz = arbol / "raiz-enlazada"
    raiz.symlink_to(arbol / "raiz", target_is_directory=True)
    navegador.raices([str(raiz)])
    raiz.unlink()
    raiz.symlink_to(arbol / "secreto", target_is_directory=True)
    confin = navegador.raices([str(raiz)])  # de memoria: sigue siendo `raiz`
    assert confin == [(arbol / "raiz").resolve()]
    with pytest.raises(navegador.FueraDeRaiz):
        navegador.resolver(str(raiz / "claves.txt"), confin)


def test_las_declaradas_se_resuelven_una_vez_por_plazo(arbol, monkeypatch):
    from hub import recordar

    reloj = [1000.0]
    monkeypatch.setattr(recordar.time, "monotonic", lambda: reloj[0])
    resueltas = []
    original = navegador.normalizar
    monkeypatch.setattr(navegador, "normalizar", lambda r: resueltas.append(r) or original(r))
    rutas = [str(arbol / "raiz"), str(arbol / "otra-raiz")]
    navegador.raices(rutas)
    navegador.raices(rutas)
    assert len(resueltas) == 2
    reloj[0] += navegador.PLAZO_DECLARADAS_S
    navegador.raices(rutas)
    assert len(resueltas) == 4


# ────────────────────────────── el tamaño ──────────────────────────────


@pytest.mark.parametrize("bytes_, esperado", [
    (None, ""), (0, "0 B"), (999, "999 B"), (1024, "1,0 kB"),
    (1536, "1,5 kB"), (1024 ** 2, "1,0 MB"), (2 * 1024 ** 3, "2,0 GB"),
])
def test_el_tamaño_se_lee_de_un_vistazo(bytes_, esperado):
    assert navegador.tamano(bytes_) == esperado
