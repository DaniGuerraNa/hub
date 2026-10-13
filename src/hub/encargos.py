"""La ficha de un encargo: lo que se sabe del negocio de alguien y qué falta.

Un encargo nace de que una persona —no técnica, y que nunca ha especificado
software— cuente lo que necesita por audio. De ahí sale un MVP que se despliega
para que lo mire y reaccione. El planteamiento entero y sus 24 decisiones están
en dos lienzos del proyecto `hub`; aquí sólo vive la parte que se puede probar
sin red, sin tmux y sin Telegram.

🔴 **La ficha ES el estado, y la conversación no.** Es la decisión de la que
cuelga todo lo demás: si lo que ella contestó viviera en el hilo del agente,
compactar perdería la entrevista y una sesión muerta la perdería entera. Viviendo
aquí, el agente puede compactarse, reiniciarse o ser otro, y sigue. Por eso este
módulo no sabe nada de agentes: los agentes leen y escriben fichas.

🔴 **Las fases son el orden del AGENTE, no el de quien habla.** Dicho por él:
*«el usuario final no lo va a hacer secuencial, va a decir las cosas como se le
vengan a la mente»*. Así que la ficha se indexa por fase y lo que llegue cae en
la casilla que le toque, venga cuando venga. Un audio que cubra tres fases las
cierra las tres, y entonces el agente **se salta lo que ya sabe** — que es lo que
hace la entrevista corta, no sólo tolerante.

🔴 **«Suficiente» es lo que hace falta para la PRIMERA pantalla**, no para el
sistema. El ciclo es iterativo: ella verá algo y pedirá otra ronda. Definirlo
como «entenderlo todo» es cómo esto se convierte en una entrevista de una hora
que acaba sin nada que enseñar.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Fase:
    """Un tramo de la entrevista: qué se quiere saber y cómo se pregunta.

    `campo` es dónde aterriza la respuesta. `minimo` marca si hace falta para
    construir la primera pantalla — y sólo tres lo son, a propósito.
    """

    id: str
    titulo: str
    # Lo que se le pregunta, con SUS palabras y sin nombrar el sistema. La gente
    # sabe describir su día; nadie sabe contestar «¿qué módulos necesitas?».
    pregunta: str
    campo: str
    minimo: bool = True
    # Si se contesta eligiendo en vez de escribiendo. La regla que gobierna al
    # entrevistador: quien no tiene vocabulario técnico no puede describir, pero
    # sí puede elegir — y entonces se enseña en vez de preguntar.
    se_elige: bool = False


FASES: tuple[Fase, ...] = (
    # 🔴 Las dos primeras hablan del SISTEMA, con sus palabras (petición suya
    # del 19-sep): la persona ya sabe que está aquí para hacerse uno, y «cómo
    # es tu día» / «qué te quitarías de encima» se entendían como otra cosa.
    # Los ids (`dia`, `duele`) se conservan: son los campos de la ficha.
    Fase(
        "dia", "Qué quieres que haga",
        "Cuéntame qué quieres que haga el sistema por ti: qué te gustaría "
        "resolver o tener a mano, con tus palabras.",
        campo="negocio",
    ),
    Fase(
        "duele", "Qué quieres ver primero",
        "De todo eso, ¿qué es lo primero que quieres ver funcionando? La "
        "pantalla o la parte que usarías cada día.",
        campo="dolor",
    ),
    # 🔴 Tres de negocio ANTES del estilo, y ninguna es mínima (decisión 230).
    # Con sólo dos preguntas y las fotos, la primera persona real dijo que el
    # salto al diseño fue brusco y que «no sabía ni que estaba eligiendo». No
    # eran mínimas para construir y siguen sin serlo —`suficiente()` no cambia—,
    # pero son lo que hace que la primera pantalla se parezca a SU negocio y
    # no a un negocio: cómo lo hace hoy, qué apunta, y cómo se llama.
    Fase(
        "como_hoy", "Cómo lo llevas hoy",
        "¿Y cómo lo llevas hoy? En un cuaderno, por WhatsApp, en el Excel, de "
        "memoria… cuéntame cómo lo haces ahora mismo.",
        campo="como_lo_hace", minimo=False,
    ),
    Fase(
        "datos", "Qué necesitas tener a mano",
        "De eso, ¿qué es lo que apuntas o necesitas tener a mano cada vez? Lo "
        "que no se te puede olvidar.",
        campo="que_apunta", minimo=False,
    ),
    # 🔴 El nombre lo elige ELLA y es la dirección (decisión 233): cualquiera
    # vale, sólo se comprueba que esté libre. Por eso la pregunta dice que va
    # a ser una dirección, para que no conteste con una frase.
    Fase(
        "nombre", "Cómo quiere que se llame",
        "Una fácil: ¿cómo quieres que se llame tu página? Va a ser su dirección "
        "en internet, así que corto y fácil de escribir va mejor, pero vale "
        "cualquiera que no esté cogido.",
        campo="nombre", minimo=False,
    ),
    Fase(
        "estilo", "Cómo quieres que se vea",
        "Te mando unas muestras: ¿cuál se parece más a lo que te gustaría?",
        campo="estilo", se_elige=True,
    ),
    # 🔴 La última, y no es una pregunta de negocio: es SU visto bueno
    # (decisión 236). Él vio que la persona «no sabía qué estaba haciendo»:
    # contestaba preguntas y de pronto le llegaba una página. Aquí el agente
    # le dice con sus palabras qué construiría primero y le pregunta si lo
    # manda así o quiere contar más. Mientras no diga que va, `proponer` no
    # deja proponer. La pregunta es una plantilla: el resumen lo pone él.
    Fase(
        "alcance", "Si lo mandamos así",
        "Te digo qué pantallas tendría tu sistema y para qué sirve cada una, "
        "y te pregunto: ¿lo mandamos así para que lo veas, o quieres contarme "
        "más antes?",
        campo="alcance", minimo=False,
    ),
)

POR_ID = {f.id: f for f in FASES}

# Los MVP son de UNA persona, sin uso simultáneo (decisión suya). No se pregunta
# porque no es una pregunta: es la restricción que mantiene simple lo que se
# construye —sin sesiones, sin roles, sin concurrencia— y por eso vive aquí como
# constante y no como una fase más.
UN_SOLO_USUARIO = True

# Agotadas, el hueco se marca «no lo sabe» y se sigue. Quien no sabe algo no lo
# va a saber a la quinta pregunta, e insistir es la forma más rápida de que
# alguien deje de contestar — y de que el coste de la entrevista no tenga techo.
TOPE_POR_FASE = 3

NO_LO_SABE = "no-lo-sabe"

ESTADOS = (
    "recogiendo",    # la entrevista
    "propuesta",     # la ficha está llena; el informe espera su visto bueno
    "aprobado",      # él contestó al mensaje del plan
    "construyendo", "implementando",
    # Hecho y sin desplegar. Es un estado propio y no un matiz de `construyendo`
    # porque quien construye y quien publica no son el mismo: el agente cambia
    # el estado y el relé despliega en su siguiente vuelta (decisión 228). Si
    # el despliegue no está configurado, aquí se queda hasta que alguien lo
    # publique a mano.
    "construido",
    "publicado",     # con su URL; desde aquí puede abrirse otra ronda
    "descartado",
)


@dataclass
class Ficha:
    """Lo que se sabe, lo que falta y cuántas veces se ha preguntado por ello."""

    encargo_id: str
    ronda: int = 1
    estado: str = "recogiendo"
    # campo → lo contestado. `NO_LO_SABE` es un valor legítimo: un hueco
    # conocido es información, y viaja en el informe que él aprueba. Uno
    # escondido es una sorpresa a mitad de la construcción.
    campos: dict[str, str] = field(default_factory=dict)
    # fase → cuántas veces se ha preguntado ya.
    preguntado: dict[str, int] = field(default_factory=dict)
    # Todo lo que contó y no cabía en un campo. No se tira nada: lo que hoy es
    # una divagación puede ser el requisito de la ronda tres.
    dicho: list[dict[str, str]] = field(default_factory=list)

    # ── lo que se sabe ────────────────────────────────────────────────────

    def responde(self, fase_id: str, texto: str) -> None:
        """Aterriza una respuesta en su casilla, venga en su turno o no."""
        fase = POR_ID.get(fase_id)
        if not fase:
            raise ValueError(f"«{fase_id}» no es una fase: son {list(POR_ID)}")
        limpio = (texto or "").strip()
        if limpio:
            self.campos[fase.campo] = limpio

    def anota(self, texto: str, fase_id: str = "") -> None:
        """Guarda entero lo que dijo. Se llama SIEMPRE, conteste o divague."""
        limpio = (texto or "").strip()
        if limpio:
            self.dicho.append({"fase": fase_id, "texto": limpio, "cuando": ahora()})

    def contestada(self, fase_id: str) -> bool:
        fase = POR_ID[fase_id]
        return bool(self.campos.get(fase.campo))

    def agotada(self, fase_id: str) -> bool:
        return self.preguntado.get(fase_id, 0) >= TOPE_POR_FASE

    def cerrada(self, fase_id: str) -> bool:
        """Una fase deja de pedir turno cuando se contestó o se agotó."""
        return self.contestada(fase_id) or self.agotada(fase_id)

    # ── qué falta ─────────────────────────────────────────────────────────

    def siguiente(self) -> Fase | None:
        """La primera fase que sigue pidiendo turno. `None` si no queda ninguna.

        🔴 Se recorre en orden y se SALTA lo cerrado. Es lo que convierte el
        matiz de las fases en tiempo ahorrado: si un audio contestó tres cosas a
        la vez, aquí no queda nada que preguntar y la entrevista se acaba ahí.
        """
        return next((f for f in FASES if not self.cerrada(f.id)), None)

    def preguntar(self, fase_id: str) -> str:
        """Apunta que se preguntó y devuelve la pregunta. Contar es el tope."""
        self.preguntado[fase_id] = self.preguntado.get(fase_id, 0) + 1
        return POR_ID[fase_id].pregunta

    def rendirse(self, fase_id: str) -> None:
        """Agotado el tope sin respuesta, el hueco se declara y se sigue."""
        self.campos.setdefault(POR_ID[fase_id].campo, NO_LO_SABE)

    def huecos(self) -> list[str]:
        """Los mínimos sin respuesta útil. Es lo que se le dice a él al aprobar."""
        return [f.campo for f in FASES
                if f.minimo and self.campos.get(f.campo, NO_LO_SABE) == NO_LO_SABE]

    def suficiente(self) -> bool:
        """Si se puede construir la PRIMERA pantalla. No «si se sabe todo».

        Un hueco declarado no impide construir: impide construir BIEN, y eso lo
        decide él con el informe delante. Lo que sí impide es que quede una fase
        sin cerrar, porque entonces todavía hay algo que preguntar.
        """
        return all(self.cerrada(f.id) for f in FASES)

    # ── ida y vuelta ──────────────────────────────────────────────────────

    def a_json(self) -> str:
        return json.dumps({
            "encargo_id": self.encargo_id, "ronda": self.ronda,
            "estado": self.estado, "campos": self.campos,
            "preguntado": self.preguntado, "dicho": self.dicho,
        }, ensure_ascii=False)

    @classmethod
    def de_json(cls, crudo: str) -> "Ficha":
        d = json.loads(crudo)
        return cls(encargo_id=d["encargo_id"], ronda=d.get("ronda", 1),
                   estado=d.get("estado", "recogiendo"), campos=d.get("campos", {}),
                   preguntado=d.get("preguntado", {}), dicho=d.get("dicho", []))


def otra_ronda(ficha: Ficha) -> Ficha:
    """Ella vio lo publicado y pide cambios. Se conserva lo sabido.

    No se empieza de cero: lo que contó en la ronda 1 sigue siendo verdad, y
    volver a preguntárselo es la forma más rápida de que deje de contestar. Lo
    que se reabre es el hueco que ella señale, y eso lo hace `reabrir`.
    """
    return Ficha(encargo_id=ficha.encargo_id, ronda=ficha.ronda + 1,
                 estado="recogiendo", campos=dict(ficha.campos),
                 preguntado={}, dicho=list(ficha.dicho))


def reabrir(ficha: Ficha, fase_id: str) -> None:
    """Vuelve a poner una fase en juego. El tope se reinicia con ella."""
    ficha.campos.pop(POR_ID[fase_id].campo, None)
    ficha.preguntado.pop(fase_id, None)


# --------------------------------------------------------------------------- #
# Dónde vive todo esto
# --------------------------------------------------------------------------- #
#
# 🔴 **La ficha es un archivo; la base es el índice** (regla dura 1). Lo que la
# persona contó vive en `HUB_HOME/encargos/<id>/ficha.json` y lo escribe el
# agente entrevistador, que es su único autor. En la base está el estado, la
# cola y el rastro: lo que hace falta para saber qué queda por entregar.
#
# La consecuencia práctica es que hay **un solo escritor por artefacto**. El relé
# no toca la ficha ni queriendo, y el agente no toca la cola: cada uno escribe lo
# suyo y lee lo del otro.


def raiz() -> Path:
    return Path(config.HUB_HOME) / "encargos"


def carpeta(encargo_id: str) -> Path:
    """La carpeta de un encargo. Todo lo suyo está dentro y nada suyo fuera.

    Es lo que hace cumplible el guardrail `never` de la decisión n8: un encargo
    es de otra persona y el hub sólo escribe aquí dentro.
    """
    return raiz() / valido(encargo_id)


NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


def valido(encargo_id: str) -> str:
    """El id es carpeta **y** subdominio, así que se valida una vez para las dos.

    Sin esto, un id con `..` escribiría fuera de `HUB_HOME` y uno con mayúsculas
    o guion bajo daría un subdominio que no resuelve — dos fallos muy distintos
    con el mismo origen, y por eso una sola puerta.
    """
    if not NOMBRE_VALIDO.match(encargo_id or ""):
        raise ValueError(
            f"«{encargo_id}» no sirve como id de encargo: minúsculas, números y "
            "guiones, de 3 a 40 caracteres, sin empezar ni acabar en guion"
        )
    return encargo_id


# 🔴 Un id provisional es a propósito feo y obviamente temporal: el id es
# también el subdominio, y publicar en `encargo-3.ejemplo.com` no sirve de
# nada. Que `publicar` lo rechace convierte el hueco en una barrera —hay que
# ponerle nombre antes de enseñárselo a nadie— en vez de en un descuido que se
# descubre cuando ya está en internet.
ES_PROVISIONAL = re.compile(r"^encargo-\d+$")


def siguiente_provisional(con: sqlite3.Connection) -> str:
    """Un id de trabajo para un encargo que todavía no tiene nombre.

    No se deriva del nombre de la persona a propósito: el id acaba siendo un
    subdominio público, y el de alguien que sólo mandó un audio no tiene por qué
    acabar en internet. El nombre de verdad sale del negocio, y eso el agente no
    lo sabe hasta la primera respuesta.
    """
    usados = {f["id"] for f in con.execute("SELECT id FROM encargo")}
    numero = 1
    while f"encargo-{numero}" in usados:
        numero += 1
    return f"encargo-{numero}"


# Subdominios que no pueden ser de un encargo: los usa otra cosa en el mismo
# dominio, o lo usaría. Un encargo llamado «www» no es un nombre, es un choque.
RESERVADOS = frozenset({"www", "api", "mail", "hub", "app", "admin", "pizarra", "encargos"})


def a_id(texto: str) -> str | None:
    """Lo que dijo, convertido en subdominio. `None` si no queda nada usable.

    «Peluches de Ana» → `peluches-de-ana`. Sin tildes, sin signos, en
    minúsculas. Vale cualquier nombre (decisión 233): el que ella quiera es el
    suyo, y lo único que se comprueba después es que esté libre.
    """
    import unicodedata

    plano = unicodedata.normalize("NFD", (texto or "").lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    base = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", plano)).strip("-")[:40].strip("-")
    if not NOMBRE_VALIDO.match(base) or ES_PROVISIONAL.match(base):
        return None
    return base


def libre(con: sqlite3.Connection, base: str) -> str:
    """`base`, o `base-2`, `base-3`… hasta uno que no exista."""
    candidato, n = base, 1
    while ver(con, candidato):
        n += 1
        candidato = f"{base[:37]}-{n}"
    return candidato


def nombre_sugerido(con: sqlite3.Connection, ficha: "Ficha") -> str | None:
    """El id que sale de lo que contestó en «cómo se llama», o `None`.

    Nunca inventa nada: si la ficha no tiene nombre, no hay sugerencia y el
    encargo sale con el provisional (decisión 232), que es feo pero funciona.
    """
    crudo = (ficha.campos.get("nombre") or "").strip()
    if not crudo or crudo == NO_LO_SABE:
        return None
    base = a_id(crudo)
    if not base or base in RESERVADOS:
        return None
    return libre(con, base)


def renombrar(con: sqlite3.Connection, viejo: str, nuevo: str) -> str:
    """Le pone su nombre de verdad, con la carpeta y todo. Sólo antes de publicar.

    🔴 Después de publicar, el id es una URL que alguien tiene guardada: cambiarlo
    rompería el enlace que se le mandó y no habría forma de avisarle. Por eso
    esto se niega en cuanto hay `url`, que es justo cuando renombrar deja de ser
    una corrección y pasa a ser una mudanza.
    """
    fila = ver(con, viejo)
    if not fila:
        raise ValueError(f"no hay ningún encargo «{viejo}»")
    if fila["url"]:
        raise ValueError(
            f"«{viejo}» ya está publicado en {fila['url']}: renombrarlo rompería "
            "el enlace que ya tiene la persona"
        )
    nuevo = valido(nuevo)
    if nuevo in RESERVADOS:
        raise ValueError(f"«{nuevo}» está reservado: lo usa otra cosa en el mismo dominio")
    if ver(con, nuevo):
        raise ValueError(f"ya hay un encargo «{nuevo}»: está cogido, hace falta otro nombre")

    origen, destino = carpeta(viejo), carpeta(nuevo)
    if origen.is_dir():
        destino.parent.mkdir(parents=True, exist_ok=True)
        origen.rename(destino)
    # Los mensajes se mueven solos: su clave ajena es `ON UPDATE CASCADE`. El
    # registro no tiene clave ajena a propósito —es una bitácora y sobrevive a
    # que se borre el encargo—, así que ése sí hay que moverlo a mano.
    con.execute("UPDATE encargo SET id = ?, actualizado_en = ? WHERE id = ?",
                (nuevo, ahora(), viejo))
    con.execute("UPDATE encargo_registro SET encargo_id = ? WHERE encargo_id = ?",
                (nuevo, viejo))
    # Los slots de sus agentes también: llevan el id en el nombre y la carpeta
    # en la ruta, y con los viejos `cerrar_agentes` no encuentra el constructor
    # y «abrir» abriría otro al lado (decisión 234).
    con.execute(
        """UPDATE slot SET nombre = ? || substr(nombre, ?), ruta = ?
           WHERE nombre = ? OR nombre = ? || '-construir'""",
        (nuevo, len(viejo) + 1, str(destino), viejo, viejo))
    ficha = cargar_ficha(con, nuevo)
    ficha.encargo_id = nuevo
    guardar_ficha(con, ficha)
    return nuevo


def crear(con: sqlite3.Connection, encargo_id: str, user_id: int,
          titulo: str = "") -> dict:
    """Da de alta un encargo y su carpeta. Idempotente a propósito.

    Volver a llamarlo con el mismo id **no reinicia nada**: quien lo llama suele
    ser el relé al ver un mensaje, y un encargo que se reiniciara por un audio
    repetido perdería la entrevista entera.
    """
    encargo_id = valido(encargo_id)
    ya = ver(con, encargo_id)
    if ya:
        return ya
    momento = ahora()
    con.execute(
        """INSERT INTO encargo (id, titulo, user_id, creado_en, actualizado_en)
           VALUES (?, ?, ?, ?, ?)""",
        (encargo_id, titulo or encargo_id, int(user_id), momento, momento),
    )
    carpeta(encargo_id).mkdir(parents=True, exist_ok=True)
    guardar_ficha(con, Ficha(encargo_id=encargo_id))
    return ver(con, encargo_id)   # type: ignore[return-value]


def ver(con: sqlite3.Connection, encargo_id: str) -> dict | None:
    fila = con.execute("SELECT * FROM encargo WHERE id = ?", (encargo_id,)).fetchone()
    return dict(fila) if fila else None


def listar(con: sqlite3.Connection, estado: str = "") -> list[dict]:
    sql = "SELECT * FROM encargo"
    args: tuple = ()
    if estado:
        sql += " WHERE estado = ?"
        args = (estado,)
    sql += " ORDER BY actualizado_en DESC"
    return [dict(f) for f in con.execute(sql, args)]


def abierto_de(con: sqlite3.Connection, user_id: int) -> dict | None:
    """El encargo vivo de una persona, que es a donde va lo que escriba.

    Uno solo, y el más reciente si hubiera varios: el bot es una conversación y
    quien manda un audio no está eligiendo expediente. Los cerrados
    (`publicado`, `descartado`) no cuentan — ahí lo que llegue abre otra ronda,
    y eso lo decide él, no un mensaje suelto.
    """
    fila = con.execute(
        """SELECT * FROM encargo
           WHERE user_id = ? AND estado NOT IN ('descartado', 'publicado')
           ORDER BY actualizado_en DESC LIMIT 1""",
        (int(user_id),),
    ).fetchone()
    return dict(fila) if fila else None


def publicado_de(con: sqlite3.Connection, user_id: int) -> dict | None:
    """Lo último que se le publicó a alguien: a donde va lo que diga al verlo.

    Un mensaje sobre un encargo publicado no es una respuesta de entrevista: es
    ella pidiendo cambios tras ver su página, o sea el principio de otra ronda,
    y esa la decide él (decisión 234). Se busca aparte para que `procesar_mensaje`
    pueda distinguir las dos cosas.
    """
    fila = con.execute(
        """SELECT * FROM encargo WHERE user_id = ? AND estado = 'publicado'
           ORDER BY actualizado_en DESC LIMIT 1""",
        (int(user_id),),
    ).fetchone()
    return dict(fila) if fila else None


def tocar(con: sqlite3.Connection, encargo_id: str, **campos: Any) -> None:
    """Cambia campos del índice y deja constancia de cuándo. Nunca la ficha."""
    permitidos = {"titulo", "estado", "ronda", "slot_id", "url", "plan_msg",
                  "avisado_espera", "nota", "etapa"}
    sobran = set(campos) - permitidos
    if sobran:
        raise ValueError(f"no son campos del encargo: {sorted(sobran)}")
    if "estado" in campos and campos["estado"] not in ESTADOS:
        raise ValueError(f"«{campos['estado']}» no es un estado: son {list(ESTADOS)}")
    if not campos:
        return
    puestas = ", ".join(f"{c} = ?" for c in campos)
    con.execute(
        f"UPDATE encargo SET {puestas}, actualizado_en = ? WHERE id = ?",
        (*campos.values(), ahora(), encargo_id),
    )


def ruta_ficha(encargo_id: str) -> Path:
    return carpeta(encargo_id) / "ficha.json"


def guardar_ficha(con: sqlite3.Connection, ficha: Ficha) -> Path:
    """Escribe la ficha y refleja en el índice lo que el índice enseña.

    🔴 Se escribe con un temporal y un `replace`: un corte a mitad dejaría un
    JSON truncado, y la ficha es lo único de un encargo que no se puede
    reconstruir de ningún otro sitio.
    """
    destino = ruta_ficha(ficha.encargo_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".json.parcial")
    temporal.write_text(ficha.a_json(), encoding="utf-8")
    temporal.replace(destino)
    if ver(con, ficha.encargo_id):
        tocar(con, ficha.encargo_id, estado=ficha.estado, ronda=ficha.ronda)
    return destino


def cargar_ficha(con: sqlite3.Connection, encargo_id: str) -> Ficha:
    """La ficha del archivo, con estado y ronda **del índice**.

    🔴 Los dos sitios guardan `estado` y aquí se decide cuál manda: el índice.
    Lo que mueve el estado es el relé —él aprueba respondiendo a un mensaje de
    Telegram— y el relé no escribe la ficha. Si mandara el archivo, una
    aprobación suya se perdería en cuanto el agente guardara lo siguiente.
    """
    ruta = ruta_ficha(encargo_id)
    ficha = Ficha.de_json(ruta.read_text(encoding="utf-8")) if ruta.is_file() \
        else Ficha(encargo_id=encargo_id)
    fila = ver(con, encargo_id)
    if fila:
        ficha.estado = fila["estado"]
        ficha.ronda = int(fila["ronda"])
    return ficha


# --------------------------------------------------------------------------- #
# Quién puede hablar con el bot
# --------------------------------------------------------------------------- #


def anotar_persona(con: sqlite3.Connection, user_id: int, username: str = "",
                   nombre: str = "") -> dict:
    """Apunta a quien escribió, **sin darle nada**. Mismo orden que el canal.

    Aparecer en la lista es la única forma de que él pueda darle de alta, y
    escribir al bot no concede absolutamente nada: el estado inicial es
    `pendiente` y ninguna acción lo mueve sola.
    """
    con.execute(
        """INSERT INTO encargo_persona (user_id, username, nombre, visto_en)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             username = excluded.username,
             nombre   = excluded.nombre,
             visto_en = excluded.visto_en""",
        (int(user_id), username or "", nombre or "", ahora()),
    )
    return ver_persona(con, user_id)   # type: ignore[return-value]


def ver_persona(con: sqlite3.Connection, user_id: int) -> dict | None:
    fila = con.execute(
        "SELECT * FROM encargo_persona WHERE user_id = ?", (int(user_id),)
    ).fetchone()
    return dict(fila) if fila else None


def personas(con: sqlite3.Connection) -> list[dict]:
    return [dict(f) for f in con.execute(
        "SELECT * FROM encargo_persona ORDER BY es_dueno DESC, visto_en DESC")]


def editar_persona(con: sqlite3.Connection, user_id: int, **campos: Any) -> None:
    """Alias, estado y nota. Dar de alta es SIEMPRE un acto suyo, y pasa aquí.

    🔴 Los `None` se descartan, no se escriben. Un formulario que no trae un
    campo lo manda como `None`, y escribirlo tal cual mete NULL en una columna
    `NOT NULL`: un 500 al guardar un alias por no haber tocado la nota. Es el
    mismo filtro que hace `canal.editar_usuario`, y faltaba aquí.
    """
    permitidos = {"alias", "estado", "nota", "de_confianza", "canal"}
    sobran = set(campos) - permitidos
    if sobran:
        raise ValueError(f"no son campos de una persona: {sorted(sobran)}")
    if "de_confianza" in campos and campos["de_confianza"] is not None:
        campos["de_confianza"] = 1 if str(campos["de_confianza"]) in ("1", "true", "on") else 0
    campos = {c: v for c, v in campos.items() if v is not None}
    if "estado" in campos and campos["estado"] not in ("pendiente", "activo", "bloqueado"):
        raise ValueError(f"«{campos['estado']}» no es un estado de persona")
    if not campos:
        return
    antes = ver_persona(con, user_id)
    puestas = ", ".join(f"{c} = ?" for c in campos)
    con.execute(f"UPDATE encargo_persona SET {puestas} WHERE user_id = ?",
                (*campos.values(), int(user_id)))
    # 🔴 Se registra, y no es burocracia: dar de alta es lo que abre este canal a
    # una persona, y era la acción más consecuente de la pantalla sin dejar
    # rastro. Un permiso que se concede sin apunte no se puede auditar después,
    # que es justo lo que el registro del canal existe para permitir.
    if "estado" in campos and campos["estado"] != (antes or {}).get("estado"):
        registrar(con, "sale",
                  f"persona a «{campos['estado']}» (antes «{(antes or {}).get('estado', '—')}»)",
                  user_id=user_id)


def marcar_dueno(con: sqlite3.Connection, user_id: int | None) -> None:
    """Uno solo. Es quien aprueba el gasto, y dos dueños es no tener ninguno."""
    con.execute("UPDATE encargo_persona SET es_dueno = 0")
    if user_id is not None:
        con.execute(
            "UPDATE encargo_persona SET es_dueno = 1, estado = 'activo' WHERE user_id = ?",
            (int(user_id),),
        )
    registrar(con, "sale",
              "dueño del canal de encargos" if user_id is not None
              else "el canal de encargos se queda SIN dueño: nadie podrá aprobar",
              user_id=user_id)


def dueno(con: sqlite3.Connection) -> dict | None:
    fila = con.execute(
        "SELECT * FROM encargo_persona WHERE es_dueno = 1 LIMIT 1").fetchone()
    return dict(fila) if fila else None


def de_confianza(con: sqlite3.Connection, user_id: int) -> bool:
    """Si sus planes se construyen sin pasar por el dueño (decisión 236)."""
    persona = ver_persona(con, user_id)
    return bool(persona and persona["estado"] == "activo" and persona.get("de_confianza"))


def puede_hablar(con: sqlite3.Connection, user_id: int) -> bool:
    persona = ver_persona(con, user_id)
    return bool(persona and persona["estado"] == "activo")


def nombre_visible(persona: dict | None) -> str:
    if not persona:
        return "alguien"
    return (persona.get("alias") or persona.get("nombre")
            or (f"@{persona['username']}" if persona.get("username") else "")
            or f"id {persona['user_id']}")


# --------------------------------------------------------------------------- #
# El rastro
# --------------------------------------------------------------------------- #


def registrar(con: sqlite3.Connection, direccion: str, detalle: str,
              user_id: int | None = None, encargo_id: str | None = None,
              cuerpo: str = "") -> None:
    """Todo lo que entra y sale, íntegro: de aquí sale contenido de la máquina."""
    con.execute(
        """INSERT INTO encargo_registro
             (momento, direccion, user_id, encargo_id, detalle, cuerpo)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ahora(), direccion, user_id, encargo_id, detalle, cuerpo),
    )


# La frase exacta con la que se apunta el saludo a quien no tiene alta. Vive
# aquí y no en el relé porque es a la vez lo que se escribe y lo que se busca:
# dos cadenas parecidas en dos sitios harían que el saludo se mandara siempre.
MARCA_SALUDO = "saludo a quien todavía no tiene alta"


def ya_saludado(con: sqlite3.Connection, user_id: int) -> bool:
    """Si a esta persona ya se le contestó el «todavía no puedo ayudarte».

    Se mira en el registro y no en una columna nueva a propósito: el registro ES
    el rastro de lo que salió de la máquina, y preguntarle a él en vez de a una
    marca paralela hace imposible que las dos cosas discrepen.
    """
    return con.execute(
        """SELECT 1 FROM encargo_registro
           WHERE user_id = ? AND direccion = 'sale' AND detalle = ? LIMIT 1""",
        (int(user_id), MARCA_SALUDO),
    ).fetchone() is not None


def por_plan_msg(con: sqlite3.Connection, message_id: int) -> dict | None:
    """El encargo cuyo plan se mandó en ese mensaje. La llave de la aprobación."""
    fila = con.execute(
        "SELECT * FROM encargo WHERE plan_msg = ?", (int(message_id),)
    ).fetchone()
    return dict(fila) if fila else None


def registro(con: sqlite3.Connection, limite: int = 100, encargo_id: str = "",
             desde: int = 0) -> list[dict]:
    """El rastro, de lo nuevo a lo viejo. Con `desde` se pagina.

    Pagina como el del canal porque esto **no se poda nunca**: sin desplazamiento,
    lo que pasó antes de las últimas cien líneas era inalcanzable desde la
    pantalla, y un registro que sólo se puede mirar por el final no sirve para
    averiguar cuándo empezó algo.
    """
    sql = "SELECT * FROM encargo_registro"
    args: list = []
    if encargo_id:
        sql += " WHERE encargo_id = ?"
        args.append(encargo_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [int(limite), int(desde)]
    return [dict(f) for f in con.execute(sql, args)]


def cuenta_registro(con: sqlite3.Connection, encargo_id: str = "") -> int:
    """Cuántas líneas hay en total. Sin esto, un tope de 60 que deja 60 y un
    registro que tiene 60 se ven exactamente igual en la pantalla."""
    if encargo_id:
        fila = con.execute(
            "SELECT COUNT(*) n FROM encargo_registro WHERE encargo_id = ?",
            (encargo_id,)).fetchone()
    else:
        fila = con.execute("SELECT COUNT(*) n FROM encargo_registro").fetchone()
    return int(fila["n"])
