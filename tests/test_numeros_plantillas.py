"""Las cifras, en español en todas las pantallas (C-0398, UI-50).

Convivían «64.0 MB» y «10.3 GB» con «47,5 %» y «50.013», y un «1
contenedor(es) sin proyecto» que suena a plantilla. Las cifras pasan por
`numero`, `tamano` y `millones` (registrados en `web._entorno`), y el plural
se escribe como en el resto del hub: `contenedor{{ 'es' if n != 1 }}`.
"""

from __future__ import annotations

import re

from hub import intercambio, navegador, web

PLANTILLAS = web._AQUI / "templates"

#: Un número formateado a la inglesa en una plantilla: `'%.1f' | format`,
#: `round(1)` pintado tal cual o el separador de miles de Python.
A_LA_INGLESA = (
    re.compile(r"['\"]%\.\d+f"),
    re.compile(r"\|\s*round\(\s*[1-9]"),
    re.compile(r"['\"]\{:,\}['\"]"),
    # «repo(s)», «contenedor(es)»; no la llamada a una macro (`cifra(s) }}`).
    re.compile(r"\w\((?:es|s)\)(?!\s*[}%])"),
)

#: Donde un decimal con punto es lo correcto: un valor de CSS no es texto.
EXCEPCIONES = {
    "consumo.html": {"'%.2f"},
}


def test_ninguna_plantilla_pinta_una_cifra_a_la_inglesa_ni_un_plural_con_parentesis():
    culpables, sobran = {}, {}
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        nombre = str(archivo.relative_to(PLANTILLAS))
        # Sin comentarios ni guiones: `escapar(s)` en JavaScript no es un plural.
        texto = re.sub(r"\{#.*?#\}|<script\b.*?</script>", "", archivo.read_text(encoding="utf-8"), flags=re.S)
        hallado = {m.group(0) for p in A_LA_INGLESA for m in p.finditer(texto)}
        admitido = EXCEPCIONES.get(nombre, set())
        if hallado - admitido:
            culpables[nombre] = sorted(hallado - admitido)
        if admitido - hallado:
            sobran[nombre] = sorted(admitido - hallado)
    assert not culpables, culpables
    assert not sobran, f"ya no hacen falta: {sobran}"


def test_el_tamano_de_intercambio_es_el_de_siempre_con_coma():
    """Había dos: el de `navegador` («64,0 MB») y una copia en `intercambio`
    que lo decía a la inglesa («64.0 MB»)."""
    assert intercambio.tamano(64 * 1024 ** 2) == "64,0 MB"
    assert intercambio.tamano is navegador.tamano


def test_la_memoria_y_la_carga_de_la_maquina_van_con_coma():
    from hub import api, avisos
    medidas = {"memoria.libre": {"valor": 12.34, "medido_en": "2026-11-13T10:00:00+00:00"},
               "carga": {"valor": 0.5, "medido_en": "2026-11-13T10:00:00+00:00"}}
    filas = {f["nombre"]: f["valor"] for f in api._tarjetas_de_maquina(medidas, avisos.limites_maquina({}))}
    assert filas["Memoria de WSL"] == "12,3" and filas["Carga"] == "0,50"
