"""El canal de encargos entero, de un mensaje de Telegram al panel y de vuelta.

🔴 Cada pieza de este canal ya está probada con dobles —`test_buzon`,
`test_rele_encargos`, `test_entrega`, `test_encargos_cli`— y eso deja fuera
exactamente lo que se ensaya aquí: que encajen. El panel lo abre
`entrevistador`, lo encuentra `api` por la muestra del snapshotter, y `buzon`
escribe en él en el instante de entregar. Las tres pueden estar bien y el
recorrido roto, porque lo que las une no es una llamada: es un `slot_id`, una
muestra de tmux con menos de veinte segundos y un panel que sigue vivo.

**tmux es de verdad**, en el socket aparte que monta `conftest`. Lo único que se
finge es qué corre DENTRO del panel, igual que en `test_entrega.py`: no hay un
Claude Code al que pagarle un turno por test. La ventana, la sesión, el pegado y
la muerte de la ventana sí son reales, y por eso lo que le llega al agente se
comprueba leyendo la pantalla con `capture-pane` en vez de creyéndole a un
espía.

El ensayo que sostiene el diseño entero es el último: reiniciar al agente a
mitad de la entrevista. Si eso pierde algo, la frase «la ficha es el estado y la
conversación no» deja de ser verdad, y no hay nada más que la sostenga.
"""

from __future__ import annotations

import contextlib
import shutil
import time
from datetime import datetime, timedelta, timezone

import pytest

from hub import (agentes, api, asistente, buzon, config, db, encargos,
                 encargos_cli, entrevistador, registry, rele_encargos,
                 snapshotter, tmux, transcribir)

# Quien encarga escribe desde un móvil y no tiene nada más que el bot. Quien
# aprueba es otro: el gasto y el despliegue son suyos, no de ella (decisión 281).
ELLA = 77
DUENO = 1

ENCARGO = "abarrotes-lucia"

# La sesión de trabajo que ya estaba abierta antes de todo esto. No es decorado:
# sin servidor de tmux no hay muestra que tomar, y sin muestra `slots.abrir` no
# puede atar el panel recién abierto a su slot.
SESION_PREVIA = "taller-de-pruebas"

# Lo que «whisper» devuelve en esta suite. Sustituirlo es obligatorio: el
# transcriptor de verdad baja un modelo y tarda 19 s por cada tres minutos de
# audio, y lo que aquí se prueba no es que oiga bien, sino dónde acaba lo que oyó.
TRANSCRIPCION = "fío a los vecinos y lo apunto en una libreta"


def t(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# El bot, que aquí no manda nada a ningún sitio
# --------------------------------------------------------------------------- #


class BotDePrueba:
    """Apunta lo que se le pidió en vez de mandarlo, y deja meter mensajes.

    Es primo del `BotFalso` de `test_rele_encargos` y no el mismo a propósito:
    allí cada test es una llamada suelta, y aquí la conversación avanza vuelta a
    vuelta, así que hace falta poder encolar un mensaje **a mitad del recorrido**
    y preguntar después a quién fue cada cosa. Media prueba de este archivo es
    que el plan salga hacia el dueño y las preguntas hacia quien encargó.
    """

    def __init__(self) -> None:
        self.textos: list[tuple[int, str]] = []
        self.fotos: list[tuple[int, str, str]] = []
        self.escrituras: list[int] = []
        self.pendientes: list[dict] = []
        self.siguiente_id = 900

    # ── lo que el relé le pide ──────────────────────────────────────────────

    def enviar(self, chat_id, texto):
        self.siguiente_id += 1
        self.textos.append((int(chat_id), texto))
        return self.siguiente_id

    def enviar_foto(self, chat_id, ruta, pie=""):
        self.siguiente_id += 1
        self.fotos.append((int(chat_id), str(ruta), pie))
        return self.siguiente_id

    def enviar_con_botones(self, chat_id, texto, botones):
        self.con_botones = getattr(self, "con_botones", [])
        self.con_botones.append((int(chat_id), texto, list(botones)))
        return self.enviar(chat_id, texto)

    def pulsado(self, callback_id, texto=""):
        self.pulsados = getattr(self, "pulsados", []) + [callback_id]

    def quitar_botones(self, chat_id, message_id):
        self.sin_botones = getattr(self, "sin_botones", []) + [(int(chat_id), int(message_id))]

    def escribiendo(self, chat_id):
        self.escrituras.append(int(chat_id))

    def descargar(self, file_id, destino):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"un ogg que no lo es")
        return destino

    def actualizaciones(self, offset=None):
        pendientes, self.pendientes = self.pendientes, []
        return pendientes


# --------------------------------------------------------------------------- #
# El canal montado
# --------------------------------------------------------------------------- #


class Canal:
    """La base, el relé y tmux de verdad, con las manos para moverlo todo."""

    def __init__(self, con, bot, panel) -> None:
        self.con = con
        self.bot = bot
        # El estado del panel: qué corre dentro y si puede recibir ahora mismo.
        self.panel = panel
        self.offset: int | None = None
        self._update = 0
        self._message = 100

    # ── lo que pasa fuera ───────────────────────────────────────────────────

    def llega(self, user_id: int, texto: str = "", *, voz: str = "",
              responde_a: int | None = None) -> int:
        """Alguien escribe al bot. Devuelve el `message_id` de lo que mandó."""
        self._update += 1
        self._message += 1
        mensaje: dict = {
            "message_id": self._message,
            "from": {"id": user_id, "username": f"persona{user_id}",
                     "first_name": f"Persona {user_id}"},
        }
        if texto:
            mensaje["text"] = texto
        if voz:
            mensaje["voice"] = {"file_id": voz, "duration": 34}
        if responde_a:
            mensaje["reply_to_message"] = {"message_id": responde_a}
        self.bot.pendientes.append({"update_id": self._update, "message": mensaje})
        return self._message

    def vuelta(self) -> None:
        """Una iteración del relé: la misma que corre el servicio cada dos segundos."""
        self.offset = rele_encargos.una_vuelta(self.con, self.bot, self.offset, {})

    def muestrear(self) -> None:
        """Lo que hace el snapshotter cada 20 s: mirar tmux y apuntar lo que ve.

        Aquí se le pide a mano porque en la suite no hay demonio, y sin muestra
        el hub no sabe en qué panel vive un slot — que es justo el puente por el
        que pasa todo lo que este archivo ensaya.
        """
        snapshotter.capturar(self.con, registry.Atribuidor(registry.cargar()))

    # ── lo que pasa dentro ──────────────────────────────────────────────────

    def abrir_agente(self, encargo_id: str = ENCARGO) -> dict:
        sitio = entrevistador.abrir_agente(self.con, encargo_id)
        self.muestrear()
        return {**sitio, **(self.donde(encargo_id) or {})}

    def donde(self, encargo_id: str = ENCARGO) -> dict | None:
        """En qué panel vive ahora mismo el agente de un encargo, según el hub."""
        fila = encargos.ver(self.con, encargo_id)
        if not fila or not fila["slot_id"]:
            return None
        return api.panel_de_slot(self.con, int(fila["slot_id"]))

    def pantalla(self, pane_id: str, esperando: str = "",
                 segundos: float = 3.0) -> str:
        """Lo que se ve en el panel de verdad. `-J` junta lo que el ancho partió.

        Con `esperando` se espera a VERLO, hasta un tope. Pegar y leer son dos
        órdenes distintas de tmux y entre ellas hay un proceso echando el texto a
        la pantalla: mirar sin esperar es una prueba que pasa aquí y falla un día
        de cada veinte en la máquina de otro.
        """
        limite = time.monotonic() + segundos
        while True:
            visto = tmux.capturar_panel(pane_id, unir_lineas=True)
            if not esperando or esperando in visto or time.monotonic() >= limite:
                return visto
            time.sleep(0.05)

    # ── utilidades ──────────────────────────────────────────────────────────

    def dichos_a(self, chat_id: int) -> list[str]:
        return [texto for destino, texto in self.bot.textos if destino == chat_id]

    def envejecer(self, minutos: int = 5) -> None:
        """Como si lo aparcado llevara esperando un rato. El reloj no se toca."""
        self.con.execute("UPDATE encargo_mensaje SET recibido_en = ?",
                         (t(minutes=-minutos),))


@pytest.fixture
def panel_con_agente(monkeypatch):
    """Lo único que se finge: qué corre DENTRO del panel.

    Son las cuatro señales que `entrega` mira para decidir —el comando del
    panel, si el cuadro acepta entrada, si está pensando y si el mensaje se vio
    salir—, las mismas que finge `test_entrega.py`. `tmux.titulo_panel` se queda
    real a propósito: es la señal con la que `quien_hay` detecta un panel muerto,
    y en el ensayo del reinicio esa muerte tiene que ser de verdad.

    🔴 Lo que **no** se finge es el pegado. El texto entra de verdad en el panel
    de tmux, así que lo que recibe el agente se comprueba leyendo la pantalla y
    no creyéndole a un espía.
    """
    estado = {"comando": "claude", "listo": True, "ocupado": False, "despacha": True}
    monkeypatch.setattr(tmux, "comando_de_panel", lambda pane_id: estado["comando"])
    monkeypatch.setattr(asistente, "listo", lambda pane_id: estado["listo"])
    monkeypatch.setattr(asistente, "ocupado", lambda pane_id: estado["ocupado"])
    monkeypatch.setattr(asistente, "despachar",
                        lambda pane_id, texto, **k: estado["despacha"])
    return estado


def _sesiones_abiertas() -> set[str]:
    try:
        return {p["session"] for p in tmux.listar_paneles()}
    except Exception:       # noqa: BLE001 - sin servidor no hay ninguna
        return set()


@pytest.fixture
def canal(tmp_path, monkeypatch, panel_con_agente):
    """El canal entero en pie, y todo lo que abra cerrado al salir."""
    if not shutil.which("tmux"):
        pytest.skip("tmux no disponible")

    # 🔴 `conftest` aísla el disco del hub pero no el HOME de quien ejecuta la
    # suite, y `entrevistador.acotar` marca la carpeta como de confianza
    # escribiendo en `~/.claude.json`. Sin esto, correr estos tests edita el
    # archivo de configuración de Claude Code de quien los ejecuta.
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))

    # 🔴 Ninguna ventana de esta suite arranca un `claude` de verdad. `cat`
    # mantiene el panel vivo y hace visible lo que se le pega, que es lo que
    # permite comprobar la entrega contra la pantalla.
    monkeypatch.setattr(agentes, "comando",
                        lambda prompt, sin_preguntar=False, modo="": "cat")
    monkeypatch.setattr(transcribir, "transcribir",
                        lambda ruta, ajustes: TRANSCRIPCION)

    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    encargos.anotar_persona(con, DUENO, "quienaprueba", "Quien Aprueba")
    encargos.marcar_dueno(con, DUENO)

    de_antes = _sesiones_abiertas()
    taller = tmp_path / "taller"
    taller.mkdir()
    tmux.nueva_sesion(SESION_PREVIA, str(taller), "trabajo", "cat")

    montado = Canal(con, BotDePrueba(), panel_con_agente)
    montado.muestrear()
    try:
        yield montado
    finally:
        con.close()
        # Se cierra aunque el test haya fallado, y se cierra **lo que abrió este
        # test y nada más**: una sesión suelta en el socket de pruebas es basura
        # que hereda quien corra la suite después, y matar por nombre fijo se
        # queda corto en cuanto una función abra su ventana en otro sitio.
        for sesion in _sesiones_abiertas() - de_antes:
            with contextlib.suppress(Exception):
                tmux._correr(["kill-session", "-t", f"={sesion}"])


# --------------------------------------------------------------------------- #
# Los pasos del recorrido, para no repetirlos en cada test
# --------------------------------------------------------------------------- #


def dar_de_alta_y_abrirle_el_encargo(canal: Canal) -> dict:
    """Lo que hace el dueño desde el hub cuando ve aparecer a alguien.

    Empieza por el saludo de ella porque es el único orden posible: el alta se
    le da a quien ya apareció, y aparecer es haber escrito.
    """
    canal.llega(ELLA, "hola, me dijeron que aquí me podían ayudar")
    canal.vuelta()
    encargos.editar_persona(canal.con, ELLA, estado="activo", alias="Lucía")
    encargos.crear(canal.con, ENCARGO, ELLA, "Abarrotes de Lucía")
    return canal.abrir_agente(ENCARGO)


def contar_el_negocio_mientras_no_puede_recibir(canal: Canal) -> None:
    """Tres mensajes seguidos —uno hablado— con el panel ocupado.

    Es el caso de verdad: quien describe su negocio hablando manda los audios de
    tres en tres, y lo hace justo mientras el agente está pensando el anterior.
    """
    canal.panel["ocupado"] = True
    canal.llega(ELLA, "abro a las siete, antes de que pase la gente al trabajo")
    canal.llega(ELLA, voz="AUDIO-DE-LUCIA")
    canal.llega(ELLA, "y los sábados vendo el doble que un día normal")
    canal.vuelta()      # los aparca a los tres
    canal.vuelta()      # baja el audio, lo transcribe e intenta entregar


def llenar_la_ficha(canal: Canal) -> None:
    """La ficha se llena con las manos del agente, que es como se llena de verdad."""
    encargos_cli.main(["--encargo", ENCARGO, "responde", "dia",
                       "abro a las siete y atiendo el mostrador todo el día"])
    encargos_cli.main(["--encargo", ENCARGO, "responde", "duele",
                       "llevar los fiados en una libreta"])
    # Con sus palabras, no con el id: es como contesta quien vio seis fotos, y
    # la CLI es la que lo convierte en el estilo que existe.
    encargos_cli.main(["--encargo", ENCARGO, "responde", "como_hoy", "en una libreta"])
    encargos_cli.main(["--encargo", ENCARGO, "responde", "datos", "quién y cuánto"])
    encargos_cli.main(["--encargo", ENCARGO, "responde", "nombre", "La Esquina"])
    encargos_cli.main(["--encargo", ENCARGO, "responde", "alcance", "dale"])
    encargos_cli.main(["--encargo", ENCARGO, "responde", "estilo",
                       "la segunda, la de la tienda de barrio"])


# --------------------------------------------------------------------------- #
# 1. Escribir al bot no concede nada, y a la vez no pierde a nadie
# --------------------------------------------------------------------------- #


def test_quien_escribe_sin_alta_no_consigue_nada_pero_queda_a_la_vista(canal):
    """🔴 Las dos mitades son inseparables, y por separado cada una es un fallo.

    Si no quedara apuntada, el dueño no tendría por dónde darle de alta: el bot
    es el único sitio donde ella existe. Si además de quedar apuntada
    consiguiera algo, cualquiera que averiguase el nombre del bot abriría
    trabajo en una máquina que no es suya.
    """
    canal.llega(ELLA, "hola, me dijeron que aquí me podían ayudar con mi tienda")
    canal.vuelta()

    assert encargos.listar(canal.con) == []
    assert encargos.ver_persona(canal.con, ELLA)["estado"] == "pendiente"
    assert ELLA in [p["user_id"] for p in encargos.personas(canal.con)]

    canal.vuelta()
    canal.vuelta()
    assert canal.dichos_a(ELLA) == [rele_encargos.SALUDO_SIN_ALTA], \
        "una línea para que no mire un silencio, no una por vuelta"


# --------------------------------------------------------------------------- #
# 2. El agente vive en un panel, y el encargo sabe en cuál
# --------------------------------------------------------------------------- #


def test_el_agente_queda_vivo_en_un_panel_y_el_encargo_apunta_a_su_slot(canal):
    """El puente entre el índice y la terminal, que es por donde pasa todo.

    Si el encargo no supiera en qué slot vive su agente, `buzon.drenar` no
    tendría dónde entregar y todo lo que llegara se quedaría en cola para
    siempre **sin que nada fallara**: el bot contestando «escribiendo…» y nadie
    leyendo nunca. Por eso se comprueban las dos puntas, el slot y el panel.
    """
    sitio = dar_de_alta_y_abrirle_el_encargo(canal)

    fila = encargos.ver(canal.con, ENCARGO)
    assert fila["slot_id"] == sitio["slot_id"]
    assert canal.donde(ENCARGO)["pane_id"] == sitio["pane_id"]
    assert tmux.titulo_panel(sitio["pane_id"]) is not None, "el panel no está vivo"

    # Y su contrato está en la carpeta, que es lo que hace barato reiniciarlo.
    carpeta = encargos.carpeta(ENCARGO)
    assert (carpeta / "INSTRUCCIONES.md").is_file()
    assert (carpeta / "encargo").is_file()


# --------------------------------------------------------------------------- #
# 3. Lo que llega mientras el agente no puede oír
# --------------------------------------------------------------------------- #


def test_tres_mensajes_con_el_panel_ocupado_no_se_pierden_ni_entran_a_la_fuerza(canal):
    """🔴 La promesa entera del buzón: *«que los mensajes no se pierdan»*.

    Un compact tarda dos o tres minutos, y ella no lo sabe. Los dos fallos que
    esto impide son opuestos: descartar lo que llega mientras tanto, o
    escribirlo igual en una TUI que no está lista —donde se pierde sin dejar
    rastro, porque desde fuera todo parece normal—.
    """
    sitio = dar_de_alta_y_abrirle_el_encargo(canal)
    contar_el_negocio_mientras_no_puede_recibir(canal)

    cola = buzon.en_cola(canal.con, ENCARGO)
    assert len(cola) == 3, "se perdió alguno de los tres"
    assert TRANSCRIPCION in [m["texto"] for m in cola], "el audio no llegó a la cola"
    assert all("trabajando" in (m["detalle"] or "") for m in cola)
    assert "canal de encargos" not in canal.pantalla(sitio["pane_id"]), \
        "se escribió en un panel que no estaba apto"


def test_una_espera_larga_se_dice_una_vez_y_no_en_cada_vuelta(canal):
    """Un bot que se narra cada minuto acaba silenciado, y entonces el aviso que
    importe tampoco se leerá. El indicador «escribiendo…» cubre las esperas
    cortas sin dejar rastro; la línea es para cuando el silencio ya se lee como
    «no me hace caso»."""
    dar_de_alta_y_abrirle_el_encargo(canal)
    contar_el_negocio_mientras_no_puede_recibir(canal)

    canal.envejecer(minutos=5)
    canal.vuelta()
    canal.vuelta()
    canal.vuelta()

    assert canal.dichos_a(ELLA) == [buzon.AVISO_DE_ESPERA]
    assert canal.bot.escrituras.count(ELLA) >= 1, "faltó el «escribiendo…»"


# --------------------------------------------------------------------------- #
# 4. Cuando el panel vuelve
# --------------------------------------------------------------------------- #


def test_al_volver_el_panel_los_tres_entran_en_un_solo_lote_y_enmarcados(canal):
    """🔴 En lote porque cada entrega es un turno, y un turno relee el contexto
    entero: tres entregas sueltas son tres despertares.

    Y enmarcados porque lo escribió una persona en un móvil (regla dura 22): el
    marco dice de quién es el texto y que un audio es lo que whisper OYÓ. Sin esa
    distinción, un error de transcripción se lee como un requisito raro del
    negocio y el agente lo construye.
    """
    sitio = dar_de_alta_y_abrirle_el_encargo(canal)
    contar_el_negocio_mientras_no_puede_recibir(canal)

    canal.panel["ocupado"] = False
    canal.vuelta()

    assert buzon.en_cola(canal.con, ENCARGO) == []
    pantalla = canal.pantalla(sitio["pane_id"], esperando="los sábados")
    assert "Mensajes de «Lucía»" in pantalla and "canal de encargos (3)" in pantalla
    assert "abro a las siete" in pantalla and "los sábados" in pantalla
    assert "transcrito" in pantalla, "el audio llegó sin decir que es una transcripción"

    entradas = [m for m in buzon.conversacion(canal.con, ENCARGO)
                if m["direccion"] == "entra"]
    assert {m["lote"] for m in entradas} != {None}
    assert len({m["lote"] for m in entradas}) == 1, "no entraron en un solo lote"


def test_tras_pedir_paciencia_no_se_narra_la_vuelta_porque_la_contestacion_lo_es(canal):
    """Decisión 235: que el lote entre en el panel no es que le hayan contestado.
    Aquí el «agente» es `cat` y no contesta nunca: se le pidió paciencia una
    vez, el bot sigue tecleando, y no se añade ningún «ya estoy» en falso."""
    dar_de_alta_y_abrirle_el_encargo(canal)
    contar_el_negocio_mientras_no_puede_recibir(canal)
    canal.envejecer(minutos=3)
    canal.vuelta()                       # se le pide paciencia

    canal.panel["ocupado"] = False
    canal.vuelta()                       # entra el lote
    canal.vuelta()
    canal.vuelta()

    assert canal.dichos_a(ELLA) == [buzon.AVISO_DE_ESPERA]
    assert canal.bot.escrituras[-1] == ELLA, "sigue tecleando: nadie le ha contestado"


def test_lo_que_el_agente_encola_con_su_cli_sale_hacia_quien_encargo(canal):
    """🔴 El reparto de la regla dura 22: quien redacta no tiene el token.

    El agente corre en un panel de tmux y lo único que puede hacer es encolar;
    mandarlo es del relé, que es el único proceso que lee el token del bot. Que
    el mensaje salga —y salga hacia ella y no hacia quien aprueba— es lo que
    demuestra que las dos mitades siguen unidas.
    """
    dar_de_alta_y_abrirle_el_encargo(canal)

    assert encargos_cli.main(
        ["--encargo", ENCARGO, "decir", "Entendido. ¿Y quién te ayuda los sábados?"]
    ) == 0
    canal.vuelta()

    assert canal.dichos_a(ELLA) == ["Entendido. ¿Y quién te ayuda los sábados?"]
    assert canal.dichos_a(DUENO) == [], "una pregunta de la entrevista no es asunto suyo"
    assert buzon.salientes(canal.con) == [], "quedó encolado después de salir"


# --------------------------------------------------------------------------- #
# 6. El plan, que es lo único que autoriza gasto
# --------------------------------------------------------------------------- #


def test_el_plan_sale_hacia_el_dueno_y_no_hacia_quien_encargo(canal):
    """Quien aprueba paga el gasto y el despliegue público. Ella no."""
    dar_de_alta_y_abrirle_el_encargo(canal)
    llenar_la_ficha(canal)
    informe = encargos.carpeta(ENCARGO) / "informe.md"
    informe.write_text("Una pantalla con los fiados del día.\n", encoding="utf-8")

    assert encargos_cli.main(["--encargo", ENCARGO, "proponer", str(informe)]) == 0
    canal.vuelta()

    # A ella no le llega el plan; le llega UNA línea diciendo qué pasa ahora
    # (233), porque la primera persona real sólo vio que el bot se calló.
    (a_ella,) = canal.dichos_a(ELLA)
    assert "Te aviso yo" in a_ella and "Plan del encargo" not in a_ella
    assert "Plan del encargo" in canal.dichos_a(DUENO)[-1]
    assert "los fiados del día" in canal.dichos_a(DUENO)[-1]
    assert encargos.ver(canal.con, ENCARGO)["plan_msg"], \
        "sin `plan_msg` la aprobación no tiene a qué atarse"


def test_aprobar_solo_funciona_respondiendo_a_ese_mensaje(canal):
    """🔴 El fallo que esto evita: un «aprobado» escrito a otra cosa lanza una
    construcción y un despliegue que nadie pidió.

    Es la acción más privilegiada del sistema, así que lo que la dispara tiene
    que ser inequívoco: ese mensaje, ese hilo y esa palabra.
    """
    dar_de_alta_y_abrirle_el_encargo(canal)
    llenar_la_ficha(canal)
    informe = encargos.carpeta(ENCARGO) / "informe.md"
    informe.write_text("Una pantalla con los fiados del día.\n", encoding="utf-8")
    encargos_cli.main(["--encargo", ENCARGO, "proponer", str(informe)])
    canal.vuelta()
    plan_msg = encargos.ver(canal.con, ENCARGO)["plan_msg"]

    canal.llega(DUENO, "aprobado")          # suelto, en otra conversación
    canal.vuelta()
    assert encargos.ver(canal.con, ENCARGO)["estado"] == "propuesta"

    canal.llega(DUENO, "aprobado", responde_a=plan_msg)
    canal.vuelta()

    # «Ya no espera su visto bueno» y no un estado concreto: el «sí» ES el
    # permiso para gastar, así que detrás puede arrancar el constructor solo
    # (decisión 223) y dejarlo en «construyendo» sin que nadie toque nada más.
    assert encargos.ver(canal.con, ENCARGO)["estado"] != "propuesta"
    assert any("APROBADO" in r["detalle"]
               for r in encargos.registro(canal.con, encargo_id=ENCARGO))


# --------------------------------------------------------------------------- #
# 7. 🔴 Reiniciar al agente a mitad
# --------------------------------------------------------------------------- #


def test_reiniciar_al_agente_no_pierde_lo_sabido_ni_lo_que_esperaba_en_la_cola(
    canal, capsys
):
    """🔴 La propiedad de la que cuelga el diseño entero.

    Si la entrevista viviera en el hilo del agente, cerrar su ventana la
    perdería —y un compact la perdería a medias, que es peor—. Vive en la ficha
    y en la cola, así que el agente puede morirse, reiniciarse o ser otro, y lo
    que ella contó sigue estando y lo que llegó mientras tanto sigue esperando.

    Se mata la ventana de tmux de verdad. Es la única forma de ensayarlo: un
    doble diría que el panel murió tanto si murió como si no, y lo que aquí se
    comprueba es justamente que el hub se entera.
    """
    sitio = dar_de_alta_y_abrirle_el_encargo(canal)
    encargos_cli.main(["--encargo", ENCARGO, "responde", "dia",
                       "abro a las siete y fío a los vecinos de siempre"])

    canal.panel["ocupado"] = True
    canal.llega(ELLA, "se me olvidaba: los sábados vendo el doble")
    canal.vuelta()
    canal.vuelta()
    assert len(buzon.en_cola(canal.con, ENCARGO)) == 1

    tmux.cerrar_ventana(sitio["session"], int(sitio["window_idx"]))
    canal.muestrear()

    # Sin panel no se entrega, y sobre todo no se da por entregado.
    canal.vuelta()
    assert len(buzon.en_cola(canal.con, ENCARGO)) == 1
    assert buzon.drenar(canal.con, ENCARGO)["resultado"] == "sin-panel"

    nuevo = canal.abrir_agente(ENCARGO)
    # 🔴 No se compara el `pane_id`: al morir la última ventana muere el servidor
    # de tmux entero, y al volver **recicla los identificadores** —`%1` vuelve a
    # ser el primer panel—. Comparar la cadena daría por bueno un fallo distinto
    # del que este test persigue. Lo que importa es que abrió de verdad y que el
    # panel de ahora está vivo.
    assert nuevo["ya_estaba"] is False, "creyó que el agente muerto seguía abierto"
    assert tmux.titulo_panel(nuevo["pane_id"]) is not None

    # Lo que ya se sabía sigue sabiéndose, y el agente nuevo lo lee de un
    # archivo en vez de acordarse.
    encargos_cli.main(["--encargo", ENCARGO, "ficha"])
    ficha_en_pantalla = capsys.readouterr().out
    assert "fío a los vecinos de siempre" in ficha_en_pantalla
    assert "1 mensaje(s) sin leer" in ficha_en_pantalla

    # Y lo que estaba en la cola sigue en la cola, hasta que hay dónde dejarlo.
    canal.panel["ocupado"] = False
    canal.vuelta()
    assert buzon.en_cola(canal.con, ENCARGO) == []
    assert "los sábados vendo el doble" in canal.pantalla(
        nuevo["pane_id"], esperando="los sábados vendo el doble")


# --------------------------------------------------------------------------- #
# 7. Una ventana que muere al arrancar se dice, con su motivo (decisión 231)
# --------------------------------------------------------------------------- #


def test_una_ventana_que_muere_al_arrancar_se_dice_con_su_motivo(canal, monkeypatch):
    """🔴 Lo que pasó con el primer constructor abierto por el relé: el `claude`
    que encontró rechazó `--permission-mode manual`, la ventana se cerró con el
    error dentro y el hub registró «abierto». Aquí el comando muere a
    propósito, con un tmux de verdad, y lo que se comprueba es que el motivo
    llega a quien llamó y que no queda ventana."""
    from hub import agentes, entrevistador

    monkeypatch.setattr(
        agentes, "comando",
        lambda prompt, sin_preguntar=False, modo="":
            # Con un instante de vida, como un programa de verdad: lo que se
            # escribe antes de que tmux empiece a leer el terminal se pierde.
            "sh -c 'sleep 0.3; echo \"error: option manual is invalid\"; exit 1'")
    encargos.anotar_persona(canal.con, ELLA, "ella", "Ella")
    encargos.editar_persona(canal.con, ELLA, estado="activo")
    encargos.crear(canal.con, ENCARGO, ELLA)

    with pytest.raises(RuntimeError, match="option manual is invalid"):
        entrevistador.abrir_agente(canal.con, ENCARGO)

    assert not [p for p in tmux.listar_paneles() if p.get("window_name") == ENCARGO
                or p.get("titulo") == ENCARGO], "no queda ventana muerta colgando"
