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
- **Mirar y cambiar en su Windows con una orden de PowerShell** (C-0240,
  decisión 404): `mirar_en_pc` sólo corre lo que `orden_pc` admite como
  lectura del estado del sistema; `cambiar_en_pc`, lo demás, con su sí a esa
  orden exacta y caducado a los 15 min. Las dos, sólo con él delante.

🔴 Todas comprueban que salió (regla dura 17): abrir en la PC espera a que el
agente confirme que la abrió; abrir un slot, a que tmux devuelva el panel; y
escribir en una sesión, a ver salir el mensaje (`entrega.entregar`).
"""

from __future__ import annotations

import time

from ... import api, db, entrega, orden_pc, orquestador, reuniones, slots, tmux, tui
from .. import memoria
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

    Sin preguntar monitor, app ni micrófono: se repite el micro de la última
    grabación y, si ahora hay una app de llamadas sonando, se graba ésa. Con
    app, el monitor es donde esté su ventana (C-0456): repetir el de la vez
    anterior grabó semanas una pantalla sin la reunión. La reserva, si el
    agente no la encuentra, la pone `reuniones.grabar`."""

    id = "grabar_reunion"
    gesto = "grabar"
    nombre = "Grabar una reunión"
    resumen = "Empieza a grabar en Reuniones la pantalla donde está la llamada, su audio y el micro de la última vez."
    descripcion = ("Empieza a grabar una reunión en Reuniones con los ajustes de la última grabación (app de la "
                   "llamada y micrófono); si ahora hay una app de llamadas sonando, graba ésa, y la pantalla "
                   "donde esté su ventana. "
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
        apps = a.get("apps") or []
        sonando = apps_sonando(a)
        app = sonando[0] if sonando else (previa.get("app") or "")
        if app and app not in {x["nombre"] for x in apps}:
            app = ""   # la de la última vez no tiene audio ahora: sólo pantalla y micro
        # Sin orden previa sólo se graba si el agente buscará la ventana: uno
        # anterior a la 0.3.0 grabaría la reserva sin que nada lo dijera.
        busca = bool(app) and reuniones.sigue_ventana(a)
        if not busca and not previa.get("monitor") and previa.get("monitor") != 0:
            raise RuntimeError("no hay una grabación anterior de la que copiar los ajustes: la primera, "
                               "desde la pantalla Reuniones")
        micro = str(previa.get("micro") or "")
        if micro and micro not in {str(m["n"]) for m in a.get("microfonos") or []}:
            micro = ""   # Windows renumera los micros: mejor grabar sin él que no grabar
        try:
            o = reuniones.grabar("" if busca else str(previa["monitor"]), app, micro,
                                 str(params.get("titulo") or ""), seguir_app=busca)
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


_PUEDE_MIRAR = ", ".join(sorted(orden_pc.CMDLETS_LECTURA))
_CLASES = ", ".join(sorted(orden_pc.CLASES_LECTURA))
_PROGRAMAS = "; ".join(" o ".join("«" + " ".join((n, *f)) + "»" for f in formas)
                       for n, formas in orden_pc.NATIVOS_LECTURA.items())


class MirarEnPc(Accion):
    id = "mirar_en_pc"
    gesto = "pc"
    nombre = "Mirar en tu PC"
    resumen = ("Corre en tu Windows una orden de PowerShell que sólo mira (monitores, aparatos, controladores, "
               "discos, red, servicios) y te dice lo que sale. Lo que no sea sólo mirar no lo corre.")
    descripcion = ("Corre en el Windows del dueño una orden de PowerShell que SÓLO MIRA el estado del sistema y "
                   "devuelve lo que escribe: modelos de monitores (Get-CimInstance WmiMonitorID -Namespace root\\wmi), "
                   "aparatos (Get-PnpDevice -Class Monitor|USB|Keyboard…), controladores, discos, red, servicios, "
                   "procesos, eventos y el registro (Get-ItemProperty 'HKLM:\\…'). Admite estos comandos y sus alias "
                   f"de siempre: {_PUEDE_MIRAR}; y solos, exactamente así: {_PROGRAMAS}. Con Get-CimInstance o "
                   f"Get-WmiObject, sólo estas clases (sin mayúsculas importa): {_CLASES}. Los argumentos, escritos "
                   "tal cual (sin $variables ni (expresiones)), salvo en Select-Object, Where-Object, ForEach-Object, "
                   "Sort-Object y Format-*; el valor separado del parámetro (-Path X, no -Path:X). Sin métodos "
                   "(.Algo()), sin `>`, sin -ComputerName, sin $env:, ForEach-Object sólo con { … }; Get-ChildItem y "
                   "Get-ItemProperty sólo en el registro. No lee archivos (para eso, leer_archivo). Si la orden no "
                   "es sólo mirar, no corre y te dice por qué: entonces, si hace falta, cambiar_en_pc. Para "
                   "pantallazos, red o programas instalados ya está diagnosticar_pc. Tarda unos segundos.")
    parametros = {"type": "object", "properties": {"comando": {"type": "string"}}, "required": ["comando"]}
    riesgo = "lectura"
    nivel_inicial = "auto"
    solo_con_el_dueno = True

    def ejecutar(self, con, params):
        try:
            r = orden_pc.leer(str(params.get("comando") or ""))
        except orden_pc.NoEsLectura as exc:
            raise RuntimeError(f"{exc}. Si de verdad hace falta, pídela con cambiar_en_pc: la aprueba él") from None
        # Lo que escribe la PC puede llevar una llave: no sale al modelo (302).
        return memoria.ocultar_secretos(orden_pc.legible(r))


class CambiarEnPc(Accion):
    id = "cambiar_en_pc"
    gesto = "pc"
    nombre = "Cambiar algo en tu PC"
    resumen = ("Corre en tu Windows una orden de PowerShell que cambia algo. Siempre con tu sí a esa orden "
               "exacta, que ves entera; si apruebas pasados 15 minutos, no la corre.")
    descripcion = ("Corre en el Windows del dueño una orden de PowerShell que cambia algo, o que mirar_en_pc no "
                   "admite. SIEMPRE pide su sí a la orden exacta, que él lee entera antes: escríbela clara, sin "
                   "abreviar ni codificar, con rutas enteras (sin cd ni Set-Location) y una sola cosa por orden. Corre "
                   "en la carpeta temporal de Windows. En `motivo`, qué hace y por qué. No se aceptan "
                   "ni con su sí: las carpetas de sus proyectos (o una que las contenga), puertos, cortafuegos o "
                   "tailscale, docker, volver a WSL (wsl, bash, \\\\wsl$), pedir administrador (RunAs) ni "
                   "Invoke-Expression o nada codificado. Dile que se lo pediste, no que ya está.")
    parametros = {"type": "object", "properties": {"comando": {"type": "string"}}, "required": ["comando"]}
    riesgo = "irreversible"
    nivel_inicial = "ask"
    # Sólo `ejecutar_aprobadas` sabe que la aprobó (como `encargar_al_orquestador`).
    quiere_aprobacion = True
    solo_con_el_dueno = True
    caduca_s = 15 * 60

    def comprobar(self, params):
        v = orden_pc.clasificar(str(params.get("comando") or ""))
        if v.nunca:
            raise ValueError(f"esa orden no se puede ni pedir: {v.nunca}")
        # Lo que la hace no ser lectura, sacado del analizador: lo lee el dueño.
        return "sólo mira: podías correrla sin preguntar" if v.lectura else "; ".join(v.motivos[:4])

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError("esto sólo se hace con el sí del dueño a esta orden")
        r = orden_pc.cambiar(str(params.get("comando") or ""))
        return memoria.ocultar_secretos(orden_pc.legible(r))


ACCIONES = [EscribirEnSesion(), AbrirEnPc(), AbrirSlot(), GrabarReunion(), PararGrabacion(), MirarEnPc(),
            CambiarEnPc()]
