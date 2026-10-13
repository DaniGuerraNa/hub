"""El contrato del agente que construye. Empieza donde acaba el entrevistador.

Dos agentes y no uno, y la separación es la decisión n7 hecha código: el que
habla con la persona **sólo planifica**, que es barato; el que construye no
arranca hasta que un humano ha visto el plan y ha dicho que sí. Si fueran el
mismo, el gasto habría empezado antes de la aprobación y el gate no significaría
nada.

🔴 **Lo que construye es un sitio ESTÁTICO**, y eso no es una limitación técnica
sino la decisión n9 hecha verdad por construcción. Un MVP de encargo es de una
persona, sin uso simultáneo, y existe para que alguien lo mire y reaccione — no
para que su negocio dependa de él. Sin servidor no hay base de datos que
respaldar, ni proceso que se caiga un sábado, ni secreto que guardar. El día que
uno de éstos deje de ser una muestra, se replantea con nombre y en otro
servidor, que es lo acordado.

🔴 **Y se escribe con el CSS que ella eligió.** El estilo no es un campo más de
la ficha: es la única parte del sistema que ella pudo decidir viendo, y darle
otro CSS convertiría esa elección en un trámite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import encargos, entrevistador, estilos

# El mismo modo que el entrevistador, y por lo mismo: ver allí.
MODO = entrevistador.MODO

CARPETA_SITIO = "sitio"

INSTRUCCIONES = """\
# Construye el encargo «{encargo}»

El plan ya está aprobado. Tu trabajo es hacerlo, y nada más que lo que dice.

## Lo que hay aquí

    informe.md    el plan aprobado. **Es el alcance**, no una sugerencia.
    ficha.json    lo que contó, con sus palabras, y los huecos declarados
    bosquejo.html si existe, es la pantalla que ELLA vio y sobre la que eligió
                  el estilo: parte de ahí, no de cero
    {sitio}/estilo.css   el CSS que ELLA eligió viendo muestras. No lo edites.

Léelos en ese orden antes de escribir una línea.

## Lo que construyes

**La maqueta navegable del sistema entero**, en `{sitio}/`: **todas** las
pantallas que dice `informe.md`, con navegación real entre ellas —un `<nav>`
en la cabecera con una entrada por pantalla, y los botones que llevan de una a
otra— y datos de ejemplo suyos en cada una. Sitio **estático**: `index.html` es
la pantalla principal y cada otra pantalla es su propio `.html` al lado (o una
vista dentro de `index.html`, si son pocas), sin servidor, sin dependencias,
sin CDN. Lo que el informe dice que se apunta o se guarda, se apunta y se
guarda de verdad en `localStorage`: en la maqueta **todo lo que se ve se puede
tocar**, para que ella la use unos días como si fuera el sistema.

🔴 Es una maqueta a propósito, y no es una carencia: existe para que **una
persona** pasee por su sistema y diga «así no es» o «así sí» **mientras cambiar
es barato**. Cuando diga «así», se convierte en el sistema de verdad —con base
de datos y su acceso— en otro paso, con otro agente. Aquí no hay base de datos
ni la habrá: construirla ahora es cómo se acaba manteniendo algo que nadie
decidió.

## Las reglas

1. **El alcance es `informe.md`.** Lo que no esté ahí no se construye, aunque se
   te ocurra y sea buena idea. Lo que sobra se propone en la ronda siguiente,
   que ella ya sabe que existe.

2. 🔴 **`estilo.css` no se toca y no se sustituye.** Es el mismo CSS que pintó
   la muestra que ella señaló. Escribe tu HTML contra sus clases —`.hoja`,
   `header`, `main`, `.lista`, `.campos`, `.parrilla`…— y mira el archivo para
   ver cuáles hay. Si necesitas algo que no está, añádelo en `propio.css`
   usando **sólo** sus variables (`--fondo`, `--sup`, `--texto`, `--tenue`,
   `--acento`, `--borde`…). Un color literal rompe la promesa entera.

3. **Con datos de ejemplo dentro**, los suyos, los que contó. Una pantalla
   vacía no se puede juzgar: ella tiene que reconocer su negocio al abrirla.
   Sácalos de `ficha.json`, sin inventar cifras que parezcan reales si no lo
   son.

4. **Que funcione en el teléfono Y en la PC.** Ella lo abre en el móvil; quien
   lo revisa, en una pantalla ancha. En el teléfono nada que se salga en
   horizontal y la navegación a la vista. En la PC (la captura a 1000 px) el
   espacio se aprovecha: la navegación en una línea, listas y formularios a
   lo ancho, sin quedar como una tira estrecha con aire muerto a los lados ni
   abajo. `estilo.css` ya centra la hoja; lo que pongas en `propio.css` usa
   `@media (min-width: 700px)` para lo que cambie en ancho. **Mira las dos
   capturas**, no sólo la del móvil.

5. **En español**, con sus palabras. Si llama «fiados» a los créditos, la
   pantalla dice «fiados».

6. 🔴 **Tus manos son `./encargo` y los archivos de `{sitio}/`, nada más.**
   No leas ni busques nada fuera de esta carpeta —y menos el código del hub:
   `./encargo mirar` se ejecuta, no se investiga—. Si una orden falla, lee lo
   que dice y sigue; si te falta algo, no existe. Un permiso que pidas se
   queda sin nadie que lo conceda y ella se queda esperando la página.
   **No uses `rm`**: si un archivo del sitio sobra, `./encargo quitar <archivo>`.

7. **Los huecos declarados en la ficha se ven.** Si algo no se supo, que la
   pantalla lo deje evidente en vez de rellenarlo con una suposición: es la
   pregunta de la ronda siguiente y tiene que poder hacerse sola.

## Cuando esté

0. `./encargo quitar <archivo>` — si algo de `{sitio}/` sobra. Sin `rm`.
1. `./encargo mirar` — pinta **cada `.html` del sitio** a 390 px (un
   teléfono) y a 1000 px, y te dice dónde quedaron los PNG. **Ábrelos y míralos de verdad** antes de
   decir que está: un `index.html` que existe no es una pantalla que se
   entiende. 🔴 No te fabriques otro navegador: el que hay a mano en esta
   máquina no baja de 500 px de ancho y te haría ver desbordada una pantalla
   que cabe perfectamente.
2. `./encargo listo` — comprueba que hay algo que enseñar y avisa a quien lo
   aprobó. **Ahí acaba tu trabajo.** Desplegar es otra cosa y la hace una
   persona.

No mandes mensajes a quien lo encargó: tú no hablas con ella. Si te falta algo
del plan, `./encargo decir` se lo pregunta a través de quien aprobó, no a ella.
"""

PRIMER_MENSAJE = """\
Vas a construir el encargo «{encargo}». Lee `INSTRUCCIONES-CONSTRUIR.md` de esta
carpeta entero antes de nada, y después `informe.md`, que es el alcance aprobado.

Empieza por `./encargo ficha` para ver qué se sabe y qué huecos quedaron.
"""


def sitio(encargo_id: str) -> Path:
    return encargos.carpeta(encargo_id) / CARPETA_SITIO


def preparar(con: sqlite3.Connection, encargo_id: str) -> Path:
    """Deja la carpeta lista para construir: el contrato y el CSS que eligió.

    El CSS se escribe aquí y no lo elige el agente a propósito. Es el único
    punto del sistema donde una decisión de ella —señalar una foto— se convierte
    en algo concreto, y dejarlo a criterio del constructor sería perderla justo
    al final.
    """
    fila = encargos.ver(con, encargo_id)
    if not fila:
        raise ValueError(f"no hay ningún encargo «{encargo_id}»")

    carpeta = encargos.carpeta(encargo_id)
    destino = sitio(encargo_id)
    destino.mkdir(parents=True, exist_ok=True)

    ficha = encargos.cargar_ficha(con, encargo_id)
    # `identificar` como segunda oportunidad: la ficha debería traer ya el id
    # —`encargo responde` lo resuelve— pero una ficha vieja, o escrita a mano,
    # puede traer el nombre. Vale la pena intentarlo antes de rendirse.
    elegido = (estilos.identificar(ficha.campos.get("estilo") or "", "estilos")
               or "")
    if elegido not in estilos.POR_ID:
        # No se adivina, pero tampoco se para: que no eligiera estilo —o que
        # eligiera describiéndolo— no puede impedir construir. Se usa el de
        # referencia y se DICE en las instrucciones, para que el constructor
        # sepa que ese aspecto no lo decidió nadie.
        elegido = estilos.ESTILO_DE_REFERENCIA
    (destino / "estilo.css").write_text(estilos.hoja(elegido), encoding="utf-8")

    (carpeta / "INSTRUCCIONES-CONSTRUIR.md").write_text(
        INSTRUCCIONES.format(encargo=encargo_id, sitio=CARPETA_SITIO),
        encoding="utf-8",
    )
    return destino


def acotar(carpeta: Path) -> None:
    """Lo mismo que el entrevistador: su carpeta y sus manos, nada más.

    🔴 Tampoco arranca en `bypassPermissions`, y aquí importa todavía más: éste
    sí escribe archivos. Lo que se le permite de antemano es exactamente su
    trabajo —editar dentro y llamar a su CLI—, así que no tiene por qué
    preguntar nunca; y si pregunta, la pregunta significa algo.
    """
    from . import agentes

    from . import config

    raiz_hub = config.RAIZ_REPO
    conf = carpeta / ".claude"
    conf.mkdir(parents=True, exist_ok=True)
    patron = "//" + str(carpeta).lstrip("/").rstrip("/") + "/**"
    (conf / "settings.json").write_text(
        json.dumps({
            "permissions": {
                "allow": [
                    f"Edit({patron})",
                    f"Read({patron})",
                    # 🔴 Las DOS formas, y no es redundancia: una regla de
                    # `Bash` casa contra la cadena que se escribe, no contra el
                    # archivo que acaba ejecutándose. El agente teclea
                    # `./encargo ficha` —es lo que dice su contrato— y la regla
                    # absoluta no casaba con eso: en modo `manual` se quedaba
                    # pidiendo permiso para lo único que sabe hacer, con nadie
                    # delante para dárselo. Medido abriéndolo, no leído.
                    "Bash(./encargo:*)",
                    f"Bash({carpeta / 'encargo'}:*)",
                ],
                # 🔴 Denegado, no «sin permitir»: lo denegado se rechaza al
                # instante y el agente sigue; lo no permitido PREGUNTA, y en
                # modo manual sin nadie delante eso es quedarse parado. Dos
                # constructores reales se atascaron así, los dos queriendo
                # leer el código del hub por curiosidad (decisión 238).
                "deny": [
                    f"Read(//{str(raiz_hub).lstrip('/')}/**)",
                    "Bash(grep:*)", "Bash(rg:*)", "Bash(find:*)",
                ],
            }
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    agentes._confiar(carpeta)


def abrir_agente(con: sqlite3.Connection, encargo_id: str) -> dict:
    """Pone al constructor a trabajar. Sólo sobre algo aprobado.

    🔴 La comprobación del estado ES el gate de la decisión n7. Es lo único que
    separa «alguien vio el plan y dijo que sí» de «un agente se puso a gastar
    porque una función se llamó desde el sitio equivocado».
    """
    from . import agentes, api, slots

    fila = encargos.ver(con, encargo_id)
    if not fila:
        raise ValueError(f"no hay ningún encargo «{encargo_id}»")
    if fila["estado"] not in ("aprobado", "construyendo"):
        raise ValueError(
            f"«{encargo_id}» está en «{fila['estado']}»: construir sólo empieza "
            "sobre un plan aprobado, que es donde está el permiso para gastar"
        )

    carpeta = encargos.carpeta(encargo_id)
    entrevistador.preparar(con, encargo_id)     # el envoltorio `encargo`
    preparar(con, encargo_id)
    acotar(carpeta)
    entrevistador.asegurar_proyecto(con)

    # 🔴 Slot APARTE del entrevistador, no el suyo. Son dos contratos distintos
    # en la misma carpeta: reusar el panel dejaría al constructor heredando las
    # instrucciones del otro, y a quien mire la ventana sin saber cuál de los
    # dos está corriendo.
    nombre = f"{encargo_id}-construir"
    slot_id = _slot_llamado(con, nombre)
    if slot_id and (vivo := entrevistador.panel_vivo(con, slot_id)):
        return {"slot_id": slot_id, "pane_id": vivo["pane_id"],
                **entrevistador.donde_esta(vivo["pane_id"]), "ya_estaba": True}
    if not slot_id:
        slot_id = slots.crear(
            con, entrevistador.PROYECTO, nombre, ruta=str(carpeta),
            nota="Constructor del encargo. Lo abre el hub; no escribas aquí tú.",
        )
    slots.editar(con, slot_id, ruta=str(carpeta), comando=agentes.comando(
        PRIMER_MENSAJE.format(encargo=encargo_id), modo=MODO))

    pane_id = slots.abrir(con, slot_id, conservar_al_morir=True)
    if not pane_id:
        raise RuntimeError(f"no se pudo abrir la ventana de construcción de «{encargo_id}»")
    entrevistador.comprobar_arranque(pane_id)
    encargos.tocar(con, encargo_id, estado="construyendo")
    encargos.registrar(con, "sale", "abierto el agente constructor",
                       encargo_id=encargo_id)
    return {"slot_id": slot_id, "pane_id": pane_id,
            **entrevistador.donde_esta(pane_id), "ya_estaba": False}


def _slot_llamado(con: sqlite3.Connection, nombre: str) -> int | None:
    fila = con.execute(
        "SELECT id FROM slot WHERE nombre = ? AND status = 'activo' LIMIT 1",
        (nombre,),
    ).fetchone()
    return int(fila["id"]) if fila else None
