"""Los tres avisos de Telegram (decisión 166), y sólo tres.

El principio 9 dice que el hub informa y no gestiona, **sin avisos**, y esto es
la excepción acotada que la decisión 166 abrió a propósito: *«una sesión está
parada esperándote»* es información que estando fuera no se puede obtener de
ninguna otra forma; *«llevas cinco días sin tocar este slot»* es gestión, y eso
sigue prohibido. La lista es CERRADA por el mismo motivo que la de acciones del
canal: si añadir un aviso fuera escribir otra cadena, el principio se erosiona
por uso y nadie se entera del día en que dejó de valer.

🔴 **Este módulo no manda nada.** Decide qué toca avisar; quien habla con
Telegram es el relé, que es el único proceso que lee el token (regla dura 22).
Separarlo no es orden: es lo que permite probar los tres avisos enteros sin red.

🔴 **El aviso es el aviso, nunca el contenido.** Ni la pantalla del panel, ni lo
que el cuadro de permisos está pidiendo. Es la misma línea que ya sigue
`avisar_al_dueno`: él puede leerlo en el hub, y lo que sale de la máquina no
vuelve a entrar.

## Cómo se sabe que una sesión paró

De `api.estado_de_panel`, que lee el glifo que Claude Code escribe en el título
y ya distingue `trabajando` de `detenido`. Lo que ese estado **no** puede decir
—y su docstring lo dice— es cuál de las dos cosas es un panel detenido: si acabó
o si está esperando una respuesta. Esa mitad se resuelve mirando la pantalla en
el instante de avisar (`asistente.esperando_confirmacion`), que es donde el
cuadro de permisos sí se reconoce porque sus marcas están medidas.

De Codex no se conocen sus diálogos (decisión 200), así que un Codex parado en
uno se cuenta como «quieta». Por eso ese aviso dice «acabó o está esperando
algo» y no «terminó»: es exactamente lo que el hub sabe, y afirmar de más aquí
sería enseñar una certeza que no existe.

## Por qué hay umbrales, y por qué el primer vistazo no avisa

Sin umbral, cada vez que se pregunta algo desde la propia silla y la sesión acaba
llegaría un aviso; el bot se silencia el mismo día y entonces tampoco avisa el
día del viaje, que es para lo que existe. El umbral es el proxy honesto de «no
hay nadie delante»: si contesta en segundos, el panel vuelve a `trabajando` y el
episodio se cierra sin que salga nada.

Y **la primera vez que se ve un panel no se avisa nunca**, sólo se apunta. Al
arrancar el relé todos los paneles están ya parados, y sin esto la primera
vuelta mandaría un aviso por cada uno. El efecto secundario es bueno: si se
pierde la tabla, lo que se pierde es silencio, no una tanda de avisos repetidos
(regla dura 1 — esto es una caché de lo que se vio, reconstruible mirando tmux).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from . import api, maquina

# La lista, y nada que no esté aquí. **Cerrada sigue**: lo que la decisión 248
# abrió no es la puerta, es una familia — la salud del equipo, que es de la
# misma clase que `sin-latido` y no de la de «llevas cinco días sin tocar este
# slot». Sigue prohibido lo que el principio 9 llama gestión, y añadir aquí una
# cadena sin una decisión escrita con su razón sigue siendo erosionarlo.
CLASES = ("preguntando", "quieta", "sin-latido", "temperatura", "disco", "luz")

# Minutos por defecto. Se pueden cambiar en `canal.yml`, sección `avisos`.
#
# El de «preguntando» es más corto que el de «quieta» a propósito: una sesión
# bloqueada en un cuadro de permisos es tiempo muerto seguro, mientras que una
# que acaba de terminar puede estar a punto de recibir lo siguiente.
UMBRALES = {"preguntando": 3, "quieta": 10, "sin-latido": 5}

# Los de la máquina NO son minutos, así que viven aparte: meterlos en el mismo
# diccionario haría que «85» se leyera como una espera. Grados y gigas libres.
#
# 85 °C porque una GPU de esta gama trabaja a 80 sin despeinarse: avisar antes
# sería avisar de que está funcionando. 10 GB libres porque por debajo de eso
# Windows empieza a fallar de formas que no se parecen a «disco lleno», y
# arreglarlo desde 2 000 km ya no es fácil.
LIMITES = {"temperatura": 85, "disco": 10}

# Una medida vieja no dispara nada. Si el muestreo murió, lo que hay que saber
# es eso —y de eso avisa `sin-latido`—, no que la última temperatura conocida,
# de hace seis horas, pasa de 85.
MINUTOS_DE_VIGENCIA = 60

# La clave del latido del hub. No es un panel, así que no colisiona con ninguno:
# los de tmux siempre empiezan por «%».
CLAVE_HUB = "hub"

# Cuándo empezó a vivir este proceso. Se fija al importar, que en el relé es su
# arranque, y existe para una sola cosa: la gracia del aviso de latido.
#
# 🔴 Sin ella, el aviso saltaría justo en el caso que el viaje tiene que cubrir.
# Tras un arranque en frío el último snapshot es **de antes del apagón**, así que
# durante los primeros segundos el latido parece perdido aunque todo esté
# arrancando bien. Y no vale mirar sólo si la fila es nueva: el relé se reinicia
# solo (`Restart=always`), y entonces la fila ya existe.
ARRANQUE = datetime.now(timezone.utc).isoformat(timespec="seconds")


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _momento(valor: str | None) -> datetime:
    """Un ISO a `datetime` con zona. Sin zona se asume UTC, como toda la base."""
    fecha = datetime.fromisoformat(valor or ahora())
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _minutos(desde: str | None, hasta: str) -> int:
    return int((_momento(hasta) - _momento(desde)).total_seconds() // 60)


def umbrales(ajustes: dict | None = None) -> dict[str, int]:
    """Los minutos de cada aviso, con lo que diga `canal.yml` encima.

    Un valor que no sea un entero positivo se ignora y vale el de fábrica: un
    cero ahí convertiría el aviso en un chorro, que es la forma de romperlo sin
    que parezca roto.
    """
    valores = dict(UMBRALES)
    seccion = (ajustes or {}).get("avisos") or {}
    # Sobre `UMBRALES` y no sobre `CLASES`: los de la máquina son grados y
    # gigas, y buscarles un `_min` haría creer que hay una espera detrás.
    for clase in UMBRALES:
        try:
            minutos = int(seccion.get(f"{clase}_min"))
        except (TypeError, ValueError):
            continue
        if minutos > 0:
            valores[clase] = minutos
    return valores


def limites_maquina(ajustes: dict | None = None) -> dict[str, float]:
    """Los de la máquina: grados de la GPU y gigas libres de disco.

    Se leen de `canal.yml` como los otros —`temperatura: 80`, `disco: 20`— y un
    valor que no sea un número positivo se ignora, por lo mismo que allí: un
    cero aquí no apagaría la alarma, la dejaría sonando para siempre.
    """
    valores = dict(LIMITES)
    seccion = (ajustes or {}).get("avisos") or {}
    for clave in LIMITES:
        try:
            limite = float(seccion.get(clave))
        except (TypeError, ValueError):
            continue
        if limite > 0:
            valores[clave] = limite
    return valores


def activos(ajustes: dict | None = None) -> bool:
    """Encendidos salvo que se apaguen a mano. Un aviso apagado de fábrica es un
    aviso que el día del viaje sigue apagado porque nadie se acordó."""
    seccion = (ajustes or {}).get("avisos") or {}
    return seccion.get("activos", True) is not False


# --------------------------------------------------------------------------- #
# La memoria de lo que ya se vio
# --------------------------------------------------------------------------- #


def _visto(con: sqlite3.Connection, clave: str) -> dict | None:
    fila = con.execute("SELECT * FROM aviso WHERE clave = ?", (clave,)).fetchone()
    return dict(fila) if fila else None


def anotar(con: sqlite3.Connection, clave: str, estado: str, momento: str) -> dict:
    """Guarda el estado de algo y devuelve cómo quedó, con de dónde viene.

    `desde` sólo se mueve cuando el estado CAMBIA: es la edad del episodio, y es
    lo único contra lo que tiene sentido comparar un umbral. Y `avisado` se
    limpia en cada cambio, que es lo que hace que cada episodio avise una vez.

    🔴 `previo` se GUARDA y no se deduce de la fila anterior, que es lo que hacía
    esto la primera vez y estaba mal: en la vuelta siguiente el estado ya no
    cambia, así que «lo anterior» pasaba a ser el estado actual y el episodio se
    olvidaba de haber venido de `trabajando` — o sea, no avisaba nunca. Lo
    destapó la prueba, no la lectura.
    """
    anterior = _visto(con, clave)
    if anterior and anterior["estado"] == estado:
        return {**anterior, "nuevo": False}

    previo = anterior["estado"] if anterior else None
    con.execute(
        """INSERT INTO aviso (clave, estado, previo, desde, avisado)
           VALUES (?,?,?,?,NULL)
           ON CONFLICT(clave) DO UPDATE SET
             estado=excluded.estado, previo=excluded.previo,
             desde=excluded.desde, avisado=NULL""",
        (clave, estado, previo, momento),
    )
    return {
        "clave": clave, "estado": estado, "previo": previo,
        "desde": momento, "avisado": None, "nuevo": anterior is None,
    }


def marcar_avisado(con: sqlite3.Connection, clave: str, momento: str | None = None) -> None:
    con.execute(
        "UPDATE aviso SET avisado = ? WHERE clave = ?", (momento or ahora(), clave)
    )


def olvidar(con: sqlite3.Connection, claves: set[str]) -> None:
    """Quita de la memoria los paneles que ya no existen.

    Sin esto, un `pane_id` reciclado por tmux tras un corte heredaría el episodio
    del panel anterior —y con él su `avisado`—, así que el aviso bueno no
    saldría. Es el mismo motivo por el que los bindings se reconcilian por epoch.

    🔴 **Sólo borra claves con forma de panel**, y esto no es un detalle: la
    primera versión borraba todo lo que no fuera un panel vivo o el latido, así
    que al llegar los episodios de la máquina (decisión 248) los barría en cada
    vuelta — y un episodio que se olvida es un aviso que se repite **cada 27
    segundos** hasta que alguien silencia el bot. Lo cazó su propia prueba, no
    la lectura. Un `pane_id` de tmux siempre empieza por «%»; lo que no tiene
    esa forma no es un panel y aquí no se toca.
    """
    con.executemany(
        "DELETE FROM aviso WHERE clave = ?",
        [(f["clave"],) for f in con.execute("SELECT clave FROM aviso")
         if f["clave"].startswith("%") and f["clave"] not in claves],
    )


# --------------------------------------------------------------------------- #
# Los tres avisos
# --------------------------------------------------------------------------- #


def _texto_sesion(clase: str, panel: dict, minutos: int) -> str:
    """Qué se dice. Lo justo para saber adónde ir, y ni una línea de la pantalla."""
    quien = panel.get("slot_nombre") or panel.get("etiqueta") or "una sesión"
    donde = panel.get("proyecto_nombre") or panel.get("proyecto_id") or "sin proyecto"
    if clase == "preguntando":
        return (
            f"«{quien}» ({donde}) lleva {minutos} min esperando que le contestes.\n"
            "Lo que pide se lee en el hub, en /trabajo."
        )
    return (
        f"«{quien}» ({donde}) lleva {minutos} min quieta: acabó o está esperando algo.\n"
        "Desde el título no se puede saber cuál de las dos; se ve en /trabajo."
    )


def _de_las_sesiones(
    con: sqlite3.Connection, momento: str, limites: dict[str, int],
    esperando: Callable[[str], bool],
) -> list[dict]:
    paneles = [p for p in api.paneles_abiertos(con) if p.get("slot_id")]
    olvidar(con, {p["pane_id"] for p in paneles})

    pendientes = []
    for panel in paneles:
        estado = api.estado_de_panel(panel)
        # 🔴 Un cuadro de permisos abierto es un estado propio, medido en la
        # pantalla, y NO exige haber visto trabajar al panel (decisión 230).
        # La regla de abajo —avisar sólo de una parada que se vio producirse—
        # dejó sin aviso al primer agente de encargo atascado en un permiso:
        # trabaja a ráfagas de veinte segundos entre mensaje y mensaje, y el
        # relé nunca lo pilló «trabajando». Una sesión que ya estaba quieta al
        # arrancar no es noticia; una que está pidiendo permiso, siempre.
        if estado == "detenido" and esperando(panel["pane_id"]):
            estado = "preguntando"
        marca = anotar(con, panel["pane_id"], estado, momento)
        if marca["avisado"]:
            continue

        edad = _minutos(marca["desde"], momento)
        if estado == "preguntando":
            if edad < limites["preguntando"]:
                continue
            clase = "preguntando"
        # Sólo se avisa de una parada que hemos VISTO producirse: el panel
        # estaba trabajando y dejó de hacerlo. Un panel que ya estaba quieto
        # cuando el relé arrancó no es noticia, es el estado normal del mundo.
        elif estado == "detenido" and marca["previo"] == "trabajando" \
                and edad >= limites["quieta"]:
            clase = "quieta"
        else:
            continue
        pendientes.append({
            "clase": clase, "clave": panel["pane_id"],
            "texto": _texto_sesion(clase, panel, edad),
        })
    return pendientes


def _del_latido(
    con: sqlite3.Connection, momento: str, limite: int, arranque: str
) -> list[dict]:
    """El hub dejó de latir: el muestreo no escribe.

    🔴 Su alcance es exactamente el que puede tener: lo manda el relé, así que
    cubre «el snapshotter murió y la máquina sigue viva», no «se fue la luz». De
    eso avisa el nodo de Tailscale apareciendo *offline* en el móvil, que es la
    respuesta que la decisión 159 le dio a este agujero — un latido que se echa
    en falta necesita a alguien FUERA que lo eche en falta.

    Tampoco avisa de que volvió: son tres avisos y ninguno más (decisión 166).
    El episodio se cierra en silencio y el siguiente corte vuelve a avisar.
    """
    if _minutos(arranque, momento) < limite:
        return []   # la gracia del arranque en frío; ver `ARRANQUE`

    fila = con.execute("SELECT MAX(tomado_en) AS ultimo FROM snapshot").fetchone()
    ultimo = fila["ultimo"] if fila else None
    if not ultimo:
        return []

    edad = _minutos(ultimo, momento)
    marca = anotar(con, CLAVE_HUB, "callado" if edad >= limite else "late", momento)
    if marca["estado"] != "callado" or marca["avisado"]:
        return []
    return [{
        "clase": "sin-latido", "clave": CLAVE_HUB,
        "texto": (
            f"El hub dejó de latir: el muestreo no escribe desde hace {edad} min.\n"
            "El relé sigue vivo, así que es `hub-snapshotter` o la base."
        ),
    }]


def _reciente(medida: dict, momento: str) -> bool:
    """Una medida vieja no dispara nada. Ver `MINUTOS_DE_VIGENCIA`."""
    return _minutos(medida["medido_en"], momento) <= MINUTOS_DE_VIGENCIA


def _de_la_maquina(
    con: sqlite3.Connection, momento: str, limites: dict[str, float]
) -> list[dict]:
    """El equipo se está calentando, o se está quedando sin disco.

    🔴 Es el único aviso que no habla del trabajo sino de la casa, y existe por
    una razón con fecha: el equipo se queda **un mes solo**. Sin nadie delante
    nadie oye el ventilador ni ve el aviso de disco de Windows, y las dos cosas
    avisan de sobra… en una pantalla que no está mirando nadie.

    🔴 **Una medida vieja no dispara nada.** Si el muestreo murió, lo que hay
    que saber es eso —y de eso avisa `sin-latido`—, no que la última
    temperatura conocida, de hace seis horas, pasaba de 85. Mandar las dos
    cosas a la vez convierte un aviso claro en dos que se contradicen.
    """
    medidas = maquina.ultimas(con)
    avisos_: list[dict] = []

    for clave, estado_malo, texto in (
        (
            "gpu.temperatura",
            "alta",
            "🌡️ La GPU va a {valor:.0f} °C (el límite avisado son {limite:.0f}).\n"
            "Nadie está delante: si sigue subiendo, míralo antes de que se apague sola.",
        ),
        (
            "disco.windows.libre",
            "poco",
            "💾 Al disco de Windows le quedan {valor:.0f} GB (el límite son {limite:.0f}).\n"
            "Por debajo de eso Windows falla de formas que no parecen «disco lleno».",
        ),
        (
            "disco.wsl.libre",
            "poco",
            "💾 Al disco de WSL le quedan {valor:.0f} GB (el límite son {limite:.0f}).\n"
            "Ahí viven el hub y su base.",
        ),
    ):
        medida = medidas.get(clave)
        if not medida or medida["valor"] is None:
            continue
        if not _reciente(medida, momento):
            continue

        limite = limites["temperatura" if clave.startswith("gpu") else "disco"]
        fuera = (
            medida["valor"] >= limite if clave.startswith("gpu")
            else medida["valor"] <= limite
        )
        marca = anotar(con, f"maquina:{clave}", estado_malo if fuera else "bien", momento)
        if not fuera or marca["avisado"]:
            continue
        avisos_.append({
            "clase": "temperatura" if clave.startswith("gpu") else "disco",
            "clave": f"maquina:{clave}",
            "texto": texto.format(valor=medida["valor"], limite=limite),
        })

    # 🔴 La luz, que es el aviso que más vale de los tres: llega **mientras
    # todavía hay corriente en el SAI**, o sea con minutos de margen, en vez de
    # con el silencio de una casa apagada. Sólo existe porque el SAI está
    # conectado por USB; sin él, esta rama no hace nada.
    estado = medidas.get("ups.estado")
    if estado and estado["valor"] is not None and _reciente(estado, momento):
        sobre_bateria = estado["valor"] == maquina.SOBRE_BATERIA
        marca = anotar(con, "maquina:ups", "bateria" if sobre_bateria else "corriente", momento)
        if sobre_bateria and not marca["avisado"]:
            carga = (medidas.get("ups.carga") or {}).get("valor")
            minutos = (medidas.get("ups.minutos") or {}).get("valor")
            resto = []
            if carga is not None:
                resto.append(f"{carga:.0f} % de batería")
            if minutos is not None:
                resto.append(f"~{minutos:.0f} min de margen")
            avisos_.append({
                "clase": "luz", "clave": "maquina:ups",
                "texto": (
                    "🔌 Se fue la luz en casa: el equipo está tirando del SAI"
                    + (" (" + ", ".join(resto) + ")." if resto else ".")
                    + "\nSi no vuelve, Windows se apagará solo y el hub caerá con él."
                ),
            })
    return avisos_


def revisar(
    con: sqlite3.Connection,
    momento: str | None = None,
    ajustes: dict | None = None,
    esperando: Callable[[str], bool] | None = None,
    arranque: str | None = None,
) -> list[dict]:
    """Qué avisos toca mandar ahora mismo. **No manda ninguno.**

    `esperando` se inyecta —por defecto, mirar el cuadro de permisos en la
    pantalla del panel— porque es lo único de aquí que toca tmux: pasarlo como
    argumento es lo que permite probar los tres avisos enteros sin un servidor.
    """
    if not activos(ajustes):
        return []
    if esperando is None:
        from . import asistente
        esperando = asistente.esperando_confirmacion

    momento = momento or ahora()
    limites = umbrales(ajustes)
    limites_de_maquina = limites_maquina(ajustes)
    return (
        _de_las_sesiones(con, momento, limites, esperando)
        + _del_latido(con, momento, limites["sin-latido"], arranque or ARRANQUE)
        + _de_la_maquina(con, momento, limites_de_maquina)
    )


def ultimos(con: sqlite3.Connection, limite: int = 20) -> list[dict[str, Any]]:
    """Lo que el relé tiene apuntado, para poder enseñarlo sin adivinar."""
    return [
        dict(f) for f in con.execute(
            "SELECT * FROM aviso WHERE avisado IS NOT NULL"
            " ORDER BY avisado DESC LIMIT ?", (limite,)
        )
    ]


def panorama(
    con: sqlite3.Connection, ajustes: dict | None = None, dueno: dict | None = None
) -> dict[str, Any]:
    """Si los avisos están armados y a quién irían. Para poder verlo, no deducirlo.

    Un aviso es lo único del hub que se comprueba **no estando delante**, así que
    la pantalla tiene que decir antes de salir de viaje si va a llegar. Sin esto,
    el punto 4 del ensayo del §8 se comprueba a ciegas: se espera un mensaje y no
    llega, y no hay forma de saber si es que no había nada que avisar, si el
    canal está mudo o si nadie está marcado como dueño.
    """
    return {
        "activos": activos(ajustes),
        "umbrales": umbrales(ajustes),
        "dueno": dueno,
        "vigilados": con.execute(
            "SELECT COUNT(*) AS n FROM aviso WHERE clave <> ?", (CLAVE_HUB,)
        ).fetchone()["n"],
        "ultimos": ultimos(con, 5),
    }
