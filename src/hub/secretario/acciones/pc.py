"""Hacer cosas en la PC del dueño (definición 5.3, decisión 313).

- **Abrir una pantalla del hub** en su navegador de Windows: la abre el agente
  de Reuniones, que ya habla con el hub cada segundo y la abre pegada a su
  sesión de Windows. Sólo pantallas del hub, nunca una web de fuera. (La 313
  decía que WSL no podía lanzar programas de Windows; desde el 7-nov se sabe
  que sí, también bajo systemd de usuario, y por eso leer la PC va directo por
  `hub.diagnostico`. Lo que cambie algo en la PC sigue por el agente, o no va:
  decisión 386.)
- **Abrir la ventana de un slot** en tmux, como el botón «Lanzar»: la misma
  función (`slots.abrir`), que deja la shell lista y no escribe nada en ella.
- **Escribirle a la sesión de un slot** (C-0225, decisión 395): el mensaje que
  el dueño le pidió pasar a su Claude Code ya abierto, para seguir él después
  en esa misma sesión. Por `entrega.entregar`, con su sí a ese texto.

🔴 Todas comprueban que salió (regla dura 17): abrir en la PC espera a que el
agente confirme que la abrió; abrir un slot, a que tmux devuelva el panel; y
escribir en una sesión, a ver salir el mensaje (`entrega.entregar`).
"""

from __future__ import annotations

import time

from ... import api, db, entrega, orquestador, reuniones, slots, tmux, tui
from ..piezas import Accion

#: La primera línea de lo que el secretario escribe en una sesión. Lo redacta
#: el modelo a partir de lo que dijo el dueño, no lo escribió él (como razona
#: la 351): la sesión tiene que saber quién le habla, y es también lo que busca
#: `respuesta_de_sesion` para leer lo que contestó. No es `entrega.marcar`, que
#: es para lo que llega de terceros.
MARCA_SESION = "[Del secretario, por encargo del dueño]"

ESPERA_S = 6


class AbrirEnPc(Accion):
    id = "abrir_en_pc"
    gesto = "pc"
    nombre = "Abrirte una pantalla en la PC"
    resumen = "Abre una pantalla del hub en el navegador de tu PC (lo hace el agente de Windows)."
    descripcion = ("Abre una pantalla del hub en el navegador de la PC del dueño, para que la vea en grande. "
                   "`ruta` es una ruta del hub: «/trabajo», «/trabajo?slot=3», «/reuniones/AAAAMMDD-HHMMSS», "
                   "«/proyecto/<id>», «/respaldo», «/secretario?p=pendientes». Nunca una URL de fuera.")
    parametros = {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": ["ruta"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        a = reuniones.agente()
        if not a.get("vivo"):
            raise RuntimeError("el agente de Windows no está conectado: sin él no puedo abrir nada en la PC")
        pid = reuniones.pedir_abrir(params["ruta"])
        fin = time.monotonic() + ESPERA_S
        while time.monotonic() < fin:
            if reuniones.abierta(pid):
                return f"abierta en la PC: {params['ruta']}"
            time.sleep(0.3)
        raise RuntimeError("el agente no confirmó que la abriera: puede que tenga una versión vieja "
                           "(Reuniones → «Copiar el agente» y reiniciarlo)")


class AbrirSlot(Accion):
    id = "abrir_slot"
    gesto = "pc"
    nombre = "Abrir la ventana de un slot"
    resumen = "Abre la terminal de un slot en Trabajo, como el botón «Lanzar»."
    descripcion = ("Abre la ventana de trabajo (tmux) de un slot por su id, como el botón «Lanzar». No escribe "
                   "nada en ella. Para que la vea en la PC, después usa abrir_en_pc con «/trabajo?slot=<id>».")
    parametros = {"type": "object", "properties": {"slot": {"type": "integer"}}, "required": ["slot"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        h = db.conectar()
        try:
            panel = slots.abrir(h, int(params["slot"]))
        finally:
            h.close()
        if not panel:
            raise RuntimeError("tmux no devolvió la ventana")
        return f"ventana del slot {params['slot']} abierta ({panel}); se ve en /trabajo?slot={params['slot']}"


class EscribirEnSesion(Accion):
    id = "escribir_en_sesion"
    gesto = "pc"
    nombre = "Escribirle a una sesión de trabajo"
    resumen = ("Le pasa un mensaje tuyo a la sesión de Claude Code (o Codex) que ya tienes abierta en un slot, "
               "para que trabaje con su contexto y sigas tú en ella.")
    descripcion = ("Escribe un mensaje en la sesión de un agente (Claude Code, Codex) YA ABIERTA en un slot, como "
                   "si lo tecleara el dueño: úsala cuando te pida «díselo a la sesión que tengo abierta», «pásale "
                   "esto a mi terminal de trabajo», para que esa sesión lo haga con su contexto y él siga en ella. "
                   "`slot`: su id (`hub_slots`). `ventana`: la de `hub_slots` → `agentes`, sólo si el slot tiene "
                   "más de una con agente. `texto`: el encargo completo y autocontenido, en sus palabras; va con "
                   "una primera línea que dice que es tuyo por encargo suyo. Un solo intento: si la sesión está "
                   "trabajando, con un permiso o un menú abierto, no se escribe y te dice por qué. Lo que conteste, "
                   "con `respuesta_de_sesion`. No es el orquestador: no abre sesiones ni sigue la tarea.")
    parametros = {"type": "object", "properties": {
        "slot": {"type": "integer"}, "texto": {"type": "string"}, "ventana": {"type": "string"}},
        "required": ["slot", "texto"]}
    # 🔴 Irreversible: un mensaje en un agente es una instrucción, no se
    # deshace. Por eso pregunta SIEMPRE, aunque lo pongan en `auto` (techo de la
    # 303), y se decide viendo el texto exacto. En `auto` sería un segundo
    # orquestador sin cerradura ni alcance (254-256).
    riesgo = "irreversible"
    nivel_inicial = "ask"
    saca_datos = True

    def ejecutar(self, con, params):
        texto = (params.get("texto") or "").strip()
        if not texto:
            raise ValueError("un mensaje vacío no se escribe")
        h = db.conectar()
        try:
            slot = api.obtener_slot(h, int(params["slot"]))
            if not slot:
                raise ValueError(f"no hay ningún slot {params['slot']}")
            # Regla dura 7. Con `ask`, su aprobación de este texto ya es su sí (279).
            if orquestador.guardrail_de(h, slot["proyecto_id"]) == "never":
                raise PermissionError(f"el proyecto {slot['proyecto_id']} tiene guardrail never: no se le escribe")
            panel = elegir_ventana(api.paneles_de_slot(h, slot["id"]), params.get("ventana"))
            # Los `%N` se reutilizan al reiniciar tmux: con un muestreo de otro
            # servidor, ese id podría ser ya el agente de otro proyecto (revisor).
            muestra = api.snapshot_actual(h)
            if not muestra or muestra["server_pid"] != tmux.servidor_pid():
                raise RuntimeError("tmux se reinició después del último muestreo: espera unos segundos "
                                   "a que se vuelva a mirar y pídemelo otra vez")
        finally:
            h.close()
        # Si el orquestador espera algo de esa ventana, un mensaje encima le
        # mezclaría la respuesta que está esperando.
        viva = orquestador.viva()
        if viva and any(e["pane_id"] == panel["pane_id"] and e["estado"] == "esperando"
                        for e in viva.get("esperas", [])):
            raise RuntimeError(f"el orquestador espera una respuesta de esa ventana (tarea {viva['id']}): "
                               "no le escribo encima")
        try:
            entrega.entregar(panel["pane_id"], f"{MARCA_SESION}\n{texto}")
        except entrega.EscritoSinConfirmar as exc:
            # 🔴 Antes que `PanelNoApto`, del que hereda: el texto ya está en el
            # cuadro. Ni se da por hecho ni se repite (sería repetir la orden).
            raise RuntimeError(f"lo escribí en {panel['pane_id']} pero no vi que saliera: míralo en la "
                               "ventana antes de pedírmelo otra vez") from exc
        except entrega.PanelNoApto as exc:
            raise RuntimeError(f"no le escribí a {panel['pane_id']}: {exc}") from exc
        return (f"escrito en la sesión del slot «{slot['nombre']}» ({panel['pane_id']}); lo que conteste, "
                "con respuesta_de_sesion")


def elegir_ventana(paneles: list[dict], ventana: str | None) -> dict:
    """La ventana con agente del slot a la que escribir, resuelta al ejecutar.

    🔴 Nunca la primera a secas: «Trabajo» tenía un `claude` y ocho `bash`
    restaurados con el glifo de Claude en el título (261), y otro slot dos
    agentes. Con una sola, ésa; con varias, la pedida o un error que las
    enumera para que pregunte en vez de adivinar."""
    con_agente = [p for p in paneles if tui.reconocer(p.get("comando") or "", p.get("titulo") or "")]
    if ventana:
        elegida = next((p for p in con_agente if p["pane_id"] == str(ventana).strip()), None)
        if not elegida:
            raise ValueError(f"la ventana {ventana} no es de ese slot o no tiene un agente abierto")
        return elegida
    if len(con_agente) == 1:
        return con_agente[0]
    if not con_agente:
        raise ValueError("ese slot no tiene ninguna ventana con un agente abierto: ábrela o pídele que la abra")
    lista = "; ".join(f"{p['pane_id']}: {p.get('etiqueta') or p.get('titulo') or ''}".strip() for p in con_agente)
    raise ValueError(f"ese slot tiene {len(con_agente)} ventanas con agente, dime cuál: {lista}")


class GrabarReunion(Accion):
    """Empezar a grabar con lo de la última vez (definición 9.1).

    Sin preguntar monitor, app ni micrófono: se repite lo de la última grabación
    y, si ahora hay una app de llamadas sonando, se graba ésa. Es lo que alguien
    haría a mano en la pantalla de Reuniones, sin la pantalla."""

    id = "grabar_reunion"
    gesto = "grabar"
    nombre = "Grabar una reunión"
    resumen = "Empieza a grabar en Reuniones con el monitor, la app y el micro de la última vez."
    descripcion = ("Empieza a grabar una reunión en Reuniones con los ajustes de la última grabación (monitor, "
                   "app de la llamada y micrófono); si ahora hay una app de llamadas sonando, graba ésa. "
                   "`titulo` opcional. Graba voces de otras personas: úsala sólo si el dueño lo pide.")
    parametros = {"type": "object", "properties": {"titulo": {"type": "string"}}}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        from ..disparadores import apps_sonando
        a = reuniones.agente()
        if not a.get("vivo"):
            raise RuntimeError("el agente de Windows no está conectado: sin él no se puede grabar")
        if a.get("grabando") or reuniones.orden().get("grabar"):
            return "ya estaba grabando: no empiezo otra"
        previa = reuniones.orden()
        if not previa.get("monitor") and previa.get("monitor") != 0:
            raise RuntimeError("no hay una grabación anterior de la que copiar los ajustes: la primera, "
                               "desde la pantalla Reuniones")
        apps = a.get("apps") or []
        sonando = apps_sonando(a)
        app = sonando[0] if sonando else (previa.get("app") or "")
        if app and app not in {x["nombre"] for x in apps}:
            app = ""   # la de la última vez no tiene audio ahora: sólo pantalla y micro
        micro = str(previa.get("micro") or "")
        if micro and micro not in {str(m["n"]) for m in a.get("microfonos") or []}:
            micro = ""   # Windows renumera los micros: mejor grabar sin él que no grabar
        try:
            o = reuniones.grabar(str(previa["monitor"]), app, micro,
                                 str(params.get("titulo") or ""))
        except ValueError as exc:
            raise RuntimeError(str(exc)) from None
        # Regla dura 17: no está grabando hasta que el agente lo dice.
        fin = time.monotonic() + ESPERA_S
        while time.monotonic() < fin:
            if reuniones.agente().get("grabando"):
                return f"grabando ({o['id']}){' el audio de ' + app if app else ' sin audio de app'}"
            time.sleep(0.3)
        raise RuntimeError("di la orden de grabar, pero el agente no confirmó que empezara: mira la pantalla "
                           "Reuniones")


class PararGrabacion(Accion):
    id = "parar_grabacion"
    gesto = "grabar"
    nombre = "Parar la grabación"
    resumen = "Para la grabación de Reuniones en curso; luego se procesa sola."
    descripcion = "Para la grabación de reunión en curso. Después se transcribe y resume sola."
    parametros = {"type": "object", "properties": {}}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        try:
            o = reuniones.parar()
        except ValueError as exc:
            raise RuntimeError(str(exc)) from None
        return f"parada la grabación {o.get('id')}; se procesa sola cuando el agente cierre los archivos"


ACCIONES = [EscribirEnSesion(), AbrirEnPc(), AbrirSlot(), GrabarReunion(), PararGrabacion()]
