"""Una fecha se enseña de una sola forma en todas las pantallas (C-0396).

Había ocho formatos —«06/11 22:48 UTC», «2026-10-21 06:25 (UTC)», «visto
2026-11-11 21:26»…—, la mitad en UTC, y un dato de hace 62 días se leía igual
que uno de hoy. `reloj.cuando` da las piezas y `ui.cuando` (`_ui.html`) las
pinta: hora de la casa, «hace X», y en color de espera cuando una medición
pasa su umbral.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from hub import web

INTERFACES = sorted(web._PLANTILLAS)


def _pintar(cual: str, llamada: str, **datos) -> str:
    entorno = web._PLANTILLAS[cual].env
    return entorno.from_string('{% import "_ui.html" as ui %}' + llamada).render(**datos).strip()


@pytest.fixture
def casa(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")


@pytest.mark.parametrize("cual", INTERFACES)
def test_ui_cuando_pinta_hace_con_la_hora_local_en_el_title(cual, casa):
    hace_3h = (datetime.now(timezone.utc) - timedelta(hours=3, minutes=1)).isoformat()

    html = _pintar(cual, "{{ ui.cuando(x) }}", x=hace_3h)

    assert re.fullmatch(r'<time class="cuando" datetime="[^"]+-06:00" title="\d\d/\d\d \d\d:\d\d">hace 3 h</time>',
                        html), html


@pytest.mark.parametrize("cual", INTERFACES)
def test_ui_cuando_pasado_su_umbral_se_pinta_viejo(cual, casa):
    hace_3h = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

    viejo = _pintar(cual, "{{ ui.cuando(x, umbral=3600) }}", x=hace_3h)
    al_dia = _pintar(cual, "{{ ui.cuando(x, umbral=86400) }}", x=hace_3h)

    assert 'class="cuando viejo"' in viejo
    assert 'class="cuando"' in al_dia


@pytest.mark.parametrize("cual", INTERFACES)
def test_ui_cuando_en_sus_formas(cual, casa):
    x = (datetime.now(timezone.utc) - timedelta(hours=3, minutes=1)).isoformat()
    local = _pintar(cual, "{{ ui.cuando(x, forma='local') }}", x=x)
    ambos = _pintar(cual, "{{ ui.cuando(x, forma='ambos') }}", x=x)
    dia = _pintar(cual, "{{ ui.cuando(x, forma='dia') }}", x=x)

    assert re.search(r'"cuando" datetime="[^"]+">\d\d/\d\d \d\d:\d\d</time>', local), local
    assert re.search(r'>\d\d/\d\d \d\d:\d\d \(hace 3 h\)</time>', ambos), ambos
    assert re.search(r'title="\d\d/\d\d \d\d:\d\d">\d\d/\d\d</time>', dia), dia


@pytest.mark.parametrize("cual", INTERFACES)
@pytest.mark.parametrize("forma", ["hace", "local", "ambos", "dia", "hora"])
def test_el_title_de_un_instante_es_la_fecha_exacta_y_no_cambia_con_el_reloj(cual, casa, forma):
    """Un `title` con «hace 3 min» cambia cada minuto, y dentro de un
    `data-region` eso anula el «sin cambios no se toca» de `sin-recarga.js`
    (tras la revisión de C-0396). El «hace» va en el texto, donde se enseña."""
    x = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()

    html = _pintar(cual, "{{ ui.cuando(x, forma=f) }}", x=x, f=forma)

    pista = re.search(r'title="([^"]*)"', html)
    assert not pista or re.fullmatch(r"\d\d/\d\d(/\d{4})? \d\d:\d\d", pista.group(1)), html


@pytest.mark.parametrize("cual", INTERFACES)
def test_ui_cuando_sin_fecha_pinta_una_raya_y_lo_que_no_es_fecha_sale_tal_cual(cual, casa):
    assert _pintar(cual, "{{ ui.cuando(x) }}", x=None) == "—"
    assert _pintar(cual, "{{ ui.cuando(x) }}", x="") == "—"
    assert _pintar(cual, "{{ ui.cuando(x) }}", x="<b>ayer</b>") == "&lt;b&gt;ayer&lt;/b&gt;"


def test_el_color_de_viejo_es_el_de_espera_y_no_reutiliza_su_clase():
    """`.espera` ya es un modificador de `.insignia`, `.placa` y `.aviso`."""
    base = (web._AQUI / "templates" / "base.html").read_text(encoding="utf-8")

    assert re.search(r"time\.cuando\.viejo\s*\{\s*color\s*:\s*var\(--espera\)", base)


# ── Ninguna plantilla recorta ni pinta una fecha por su cuenta ───────────────

PLANTILLAS = web._AQUI / "templates"

#: Lo que delata una fecha pintada a mano: la UTC a la vista, la `T` del ISO
#: quitada con `replace`, o un recorte de la cadena (`[:10]` el día, `[:16]`
#: hasta el minuto, `[11:16]` la hora, `[8:10]`/`[5:7]` día y mes…).
A_MANO = (
    re.compile(r"(?:\}\}|\d)\s*\(?UTC\b"),
    re.compile(r"replace\(\s*['\"]T['\"]"),
    re.compile(r"[\w.)\]]+\[\s*\d*\s*:\s*(?:7|10|16|19)\s*\]"),
    re.compile(r"[\w.)\]]+\[\s*(?:4|5|6|8|9|11|13)\s*:\s*\d+\s*\]"),
)

#: Las que siguen pintándose a mano, cada una con su porqué. 🔴 Esta lista
#: sólo puede encoger: el test falla también si sobra una entrada.
EXCEPCIONES: dict[str, set[str]] = {
    # La fecha sale del id de la reunión (`AAAAMMDD-HHMM…`), no de un ISO.
    "reunion.html": {"d.id[4:6]", "d.id[6:8]", "d.id[9:11]", "d.id[11:13]"},
    "reuniones.html": {"x.id[4:6]", "x.id[6:8]", "x.id[9:11]", "x.id[11:13]"},
    # `api.navegante` sigue con la hora de la máquina y su propio formato
    # (fila con aviso de MAPA): otra ficha.
    "navegante.html": {"c.cuando[4:6]", "c.cuando[6:8]", "c.cuando[9:11]", "c.cuando[11:13]",
                       "c.cuando[13:15]"},
    "navegante_corrida.html": {"c.cuando[4:6]", "c.cuando[6:8]", "c.cuando[9:11]", "c.cuando[11:13]"},
}


def _sin_comentarios(texto: str) -> str:
    return re.sub(r"\{#.*?#\}|/\*.*?\*/", "", texto, flags=re.S)


def _a_mano(archivo) -> set[str]:
    texto = _sin_comentarios(archivo.read_text(encoding="utf-8"))
    return {m.group(0).strip() for patron in A_MANO for m in patron.finditer(texto)}


def test_ninguna_plantilla_pinta_una_fecha_a_mano():
    culpables, sobran = {}, {}
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        nombre = str(archivo.relative_to(PLANTILLAS))
        hallado, admitido = _a_mano(archivo), EXCEPCIONES.get(nombre, set())
        if hallado - admitido:
            culpables[nombre] = sorted(hallado - admitido)
        if admitido - hallado:
            sobran[nombre] = sorted(admitido - hallado)
    assert not culpables, f"fechas pintadas a mano; usa ui.cuando: {culpables}"
    assert not sobran, f"ya no hacen falta; quítalas de EXCEPCIONES: {sobran}"


#: La actividad de un slot, un proyecto o una idea. Pintarla de «viejo»
#: sería «llevas X días sin tocar», que es gestión y el principio 9 prohíbe.
ACTIVIDAD = re.compile(r"\b(?:ultima_actividad|creada|movida|ultimo_commit|modificado|usado)\b")


def _llamadas_a_cuando(texto: str):
    """Los argumentos de cada `ui.cuando(…)`, contando paréntesis."""
    for m in re.finditer(r"\bui\.cuando\(", texto):
        nivel, i = 1, m.end()
        while nivel and i < len(texto):
            nivel += {"(": 1, ")": -1}.get(texto[i], 0)
            i += 1
        yield texto[m.end():i - 1]


def _primer_argumento(args: str) -> str:
    nivel = 0
    for i, c in enumerate(args):
        nivel += {"(": 1, "[": 1, ")": -1, "]": -1}.get(c, 0)
        if c == "," and nivel == 0:
            return args[:i]
    return args


def test_la_actividad_de_un_slot_proyecto_o_idea_nunca_lleva_umbral():
    culpables = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        for args in _llamadas_a_cuando(_sin_comentarios(archivo.read_text(encoding="utf-8"))):
            primero = _primer_argumento(args)
            resto = args[len(primero):]
            con_umbral = "umbral" in resto or re.match(r"\s*,\s*[^\s=]+\s*(?:,|$)", resto)
            if con_umbral and ACTIVIDAD.search(primero):
                culpables.append(f"{archivo.name}: ui.cuando({args})")
    assert not culpables, culpables


def test_cada_umbral_es_el_de_una_medicion_del_hub():
    """Un umbral escrito a mano es una cifra que hay que poder defender (regla
    13): cada uno es la cadencia que el hub ya promete para esa medición."""
    from hub import api, copia_base, salud, version

    defendibles = {
        salud.MAL_SEGUNDOS: "la muestra de tmux: el latido ya va mal",
        api.SERVICIOS_VIGENTES_SEGUNDOS: "el ciclo lento: tres vueltas sin lectura",
        int(copia_base.VIEJA_A_LOS.total_seconds()): "la copia diaria de la base",
        int(version.ATRASADO.total_seconds()) if hasattr(version.ATRASADO, "total_seconds")
        else int(version.ATRASADO): "mirar si hay versión nueva",
    }
    usados = {}
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        for args in _llamadas_a_cuando(_sin_comentarios(archivo.read_text(encoding="utf-8"))):
            m = re.search(r"umbral\s*=\s*([^,)]+)", args)
            if m:
                usados.setdefault(m.group(1).strip(), []).append(archivo.name)
    assert usados, "ninguna medición lleva umbral"
    raros = {v: d for v, d in usados.items() if not v.isdigit() or int(v) not in defendibles}
    assert not raros, f"umbrales que no son la cadencia de ninguna medición: {raros}"


@pytest.mark.parametrize("cual", INTERFACES)
def test_ui_cuando_sin_hace_no_dice_cuanto_lleva_ni_en_el_title(cual, casa):
    """Para lo que espera al dueño: «sólo se cuenta, sin decir cuánto lleva»
    (regla dura 3)."""
    hace_3d = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    html = _pintar(cual, "{{ ui.cuando(x, forma='local', con_hace=false) }}", x=hace_3d)

    assert "hace" not in html and "title=" not in html, html


#: Lo que no puede decir cuánto hace, ni en el `title`: lo que vence o espera
#: al dueño (regla dura 3) y la actividad de un slot, proyecto o idea
#: (principio 9: «hace 5 d» sobre un slot es «llevas cinco días sin tocarlo»).
SIN_HACE = re.compile(r"\b(?:vence|recordar_en|ultima_actividad)\b|\br\.creada\b")
#: En el Tablero, la fecha de una idea —tomada o no— es su actividad.
SIN_HACE_EN = {"tablero.html": re.compile(r"\b(?:creada|movida)\b")}


def test_lo_que_vence_o_espera_al_dueno_ni_la_actividad_dicen_cuanto_lleva():
    """Un compromiso vencido con «(hace 3 d)» al lado sería la cuenta que la
    regla dura 3 no deja hacer; una solicitud, lo mismo. Y la última actividad
    de un slot o la fecha de una idea con su «hace» (tras la revisión de
    C-0396) es la gestión que el principio 9 prohíbe."""
    culpables = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        propio = SIN_HACE_EN.get(archivo.name)
        for args in _llamadas_a_cuando(_sin_comentarios(archivo.read_text(encoding="utf-8"))):
            primero = _primer_argumento(args)
            if (SIN_HACE.search(primero) or (propio and propio.search(primero))) and "con_hace=false" not in args:
                culpables.append(f"{archivo.name}: ui.cuando({args})")
    assert not culpables, culpables


def test_un_umbral_solo_donde_la_pantalla_puede_volver_a_medir():
    """Un color de «viejo» sin nada que hacer al lado es ruido (tras la
    revisión de C-0396/C-0401): Máquina y Consumo se miden solos en el ciclo
    lento y no tienen «Medir ahora», así que ahí la fecha va sin umbral."""
    sin_accion = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        texto = _sin_comentarios(archivo.read_text(encoding="utf-8"))
        con_umbral = any("umbral" in args for args in _llamadas_a_cuando(texto))
        puede = "ui.refrescar(" in texto or re.search(r'action="/[\w/-]+/escanear"', texto)
        if con_umbral and not puede:
            sin_accion.append(archivo.name)
    assert not sin_accion, sin_accion


@pytest.mark.parametrize("cual", INTERFACES)
def test_banco_y_actualizaciones_pintan_su_fecha_con_ui_cuando(cual, casa):
    """Tras la revisión de C-0396: el banco de dictado pintaba «2026-11-12
    03:00» (su `cuando`, hora de la máquina sin zona) y Actualizaciones su
    `mirado_local` aparte. Las dos van por `ui.cuando`."""
    banco = (PLANTILLAS / "banco_dictado.html").read_text(encoding="utf-8")
    actualizaciones = (PLANTILLAS / "actualizaciones.html").read_text(encoding="utf-8")

    assert "{{ r.cuando }}" not in banco and "ui.cuando(r.cuando" in banco
    assert "mirado_local" not in actualizaciones and "ui.cuando(vers.mirado_en" in actualizaciones
    assert re.search(r">12/11(/2026)? 03:00</time>", _pintar(cual, "{{ ui.cuando(x, forma='local') }}",
                                                             x="2026-11-12 03:00"))
