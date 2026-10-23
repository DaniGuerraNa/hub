"""La guía: por dónde empezar y qué hay en cada pantalla.

Existe para quien estrena el hub en otra máquina (decisión 271): quince
pantallas, un registro vacío y nadie al lado que lo explique. La pantalla
`/guia` y la orden `hub guia` del asistente leen de aquí, así que el mapa que ve
una persona y el que usa el asistente para guiarla son **el mismo**: si una
pantalla cambia de sitio, se cambia en un lugar.

🔴 Los pasos se **miden**, no se marcan a mano: «hecho» sale del estado real
del hub (regla dura 13). Una casilla que alguien marcó y que ya no es verdad
—borró su único proyecto— enseñaría un camino recorrido que no lo está. Y no
hay «no volver a mostrar» guardado en ningún sitio: la guía no avisa ni se
impone, está en el raíl para quien la busque (regla 3 del producto).
"""

from __future__ import annotations

import sqlite3
from typing import Any

#: Lo que hay en cada pantalla. `que_haces` son acciones, escritas como las
#: diría quien las usa: el asistente las repite al guiar.
PANTALLAS: list[dict[str, Any]] = [
    {"grupo": "El día a día", "ruta": "/", "nombre": "Panorama",
     "para_que": "Lo que pide tu atención ahora: lo que espera en la bandeja, el trabajo sin respaldar y tus proyectos.",
     "que_haces": ["Crear un proyecto nuevo (botón «Proyecto nuevo», junto a Proyectos)",
                   "Entrar a la ficha de un proyecto pulsándolo",
                   "Restaurar tus ventanas si se perdió una sesión de trabajo"]},
    {"grupo": "El día a día", "ruta": "/trabajo", "nombre": "Trabajo",
     "para_que": "Donde se pasa el día: slots a la izquierda, terminal en medio y, a la derecha, cuatro pestañas: Nota, Lienzos, Consultas y Programados.",
     "que_haces": ["Pulsar un slot para ir a su ventana",
                   "Abrir la ventana de un slot cerrado (botón «Lanzar», bajo su nombre)",
                   "Escribir la nota de lo que estás haciendo (pestaña Nota; se guarda sola)",
                   "Ver y marcar los lienzos que publican tus sesiones (pestaña Lienzos)",
                   "Ver las preguntas que tus sesiones mandaron por Telegram y su respuesta (pestaña Consultas)",
                   "Dejar un mensaje para que Claude lo lea a una hora, una sola vez (pestaña Programados)",
                   "Organizar desde la bandeja las ventanas que aún no tienen slot"]},
    {"grupo": "El día a día", "ruta": "/proyecto/<id>", "nombre": "Ficha de un proyecto",
     "para_que": "Todo de un proyecto: su estado, su respaldo, su consumo, sus contenedores y sus slots.",
     "que_haces": ["Crear un slot (sección Slots → «Slot nuevo»)", "Lanzar un slot para abrir su ventana",
                   "Editar o archivar un slot"]},
    {"grupo": "El día a día", "ruta": "/orquestador", "nombre": "Orquestador",
     "para_que": "Le das una tarea (escrita o dictada) y él se la pide a las sesiones de tus proyectos, paso a paso.",
     "que_haces": ["Mandar una tarea nueva", "Contestar lo que te pregunta",
                   "Confirmar o negar que toque un proyecto con guardrail «ask»",
                   "Detener o reanudar una tarea",
                   "Darle alcance por proyecto en Orquestador → Permisos"]},
    {"grupo": "El día a día", "ruta": "/navegante", "nombre": "Navegante",
     "para_que": "El navegador que maneja Claude, con un guardián que pausa lo que modifica. La primera vez enseña cómo prepararlo. Luego: encenderlo, verlo en vivo, enseñarle un flujo haciéndolo tú y contestar lo que pide permiso.",
     "que_haces": ["Encender el navegador y abrir la vista en vivo",
                   "Poner el guardián con una política",
                   "Grabar un flujo haciéndolo tú, y componer fragmentos",
                   "Correr un flujo y ver si falló, con su captura",
                   "Permitir una vez o negar una acción que el guardián pausó"]},
    {"grupo": "El día a día", "ruta": "/reuniones", "nombre": "Reuniones",
     "para_que": "Grabar una reunión que tienes en otro monitor (pantalla, audio de la aplicación y tu micro) y leerla procesada: resumen, decisiones, tareas y transcripción.",
     "que_haces": ["Elegir monitor, aplicación y micrófono, y pulsar Grabar",
                   "Leer el resumen y lo que te toca", "Buscar en la transcripción con sus capturas",
                   "Comprimir el audio de las reuniones ya procesadas",
                   "La primera vez: preparar el procesado e instalar el agente de Windows, paso a paso"]},
    {"grupo": "El día a día", "ruta": "/intercambio", "nombre": "Intercambio",
     "para_que": "La carpeta por la que pasan archivos entre el teléfono y las sesiones.",
     "que_haces": ["Subir un archivo desde el teléfono", "Bajarte lo que dejó una sesión",
                   "Agrupar por tema, fecha o tipo"]},
    {"grupo": "Vigilar", "ruta": "/respaldo", "nombre": "Respaldo",
     "para_que": "Qué trabajo no está respaldado: commits sin subir y repos sin remoto. La razón de ser del hub.",
     "que_haces": ["Ver qué repos tienen commits sin subir", "Volver a medir con «Medir ahora»"]},
    {"grupo": "Vigilar", "ruta": "/servicios", "nombre": "Servicios",
     "para_que": "De quién es cada contenedor de Docker, antes de parar ninguno.",
     "que_haces": ["Ver qué proyecto es dueño de cada contenedor", "Arrancar, parar o reiniciar uno, de uno en uno"]},
    {"grupo": "Vigilar", "ruta": "/maquina", "nombre": "Máquina",
     "para_que": "Cómo está el equipo cuando no hay nadie delante: disco, memoria, GPU y, si hay un SAI, si se fue la luz.",
     "que_haces": ["Ver cómo va el equipo y lo que el hub no pudo medir"]},
    {"grupo": "Vigilar", "ruta": "/consumo", "nombre": "Consumo",
     "para_que": "Cuántos tokens ha costado cada proyecto en los últimos días (Claude Code borra su registro a los 30).",
     "que_haces": ["Comparar el gasto entre proyectos y por días"]},
    {"grupo": "Consultar", "ruta": "/inventario", "nombre": "Inventario",
     "para_que": "Qué tienes construido (kits, skills, scripts), quién lo usa y qué lleva meses sin tocarse.",
     "que_haces": ["Buscar una capacidad que ya hiciste", "Ver qué kits tiene cada proyecto"]},
    {"grupo": "Consultar", "ruta": "/archivos", "nombre": "Archivos",
     "para_que": "Explorar las carpetas de tus proyectos, sin poder tocarlas.",
     "que_haces": ["Navegar por las carpetas", "Abrir una terminal en una carpeta"]},
    {"grupo": "Consultar", "ruta": "/contexto", "nombre": "Contexto",
     "para_que": "Todo el estado del hub en un texto, para pegarlo al principio de una sesión.",
     "que_haces": ["Copiar el contexto y pegarlo en una sesión nueva"]},
    {"grupo": "Ajustes", "ruta": "/conexiones", "nombre": "Conexiones",
     "para_que": "Dónde despliega cada cosa y dónde vive su credencial (nunca la credencial).",
     "que_haces": ["Declarar un servidor, dónde vive su llave y qué proyectos lo usan"]},
    {"grupo": "Ajustes", "ruta": "/acceso", "nombre": "Acceso",
     "para_que": "Usar el hub desde el teléfono u otro aparato, por una red privada: por qué nombres se entra, qué aparatos pueden y si la terminal se abre desde fuera.",
     "que_haces": ["Dar de alta un aparato con un QR («Generar el QR») o quitarlo",
                   "Abrir o cerrar la terminal desde fuera (interruptor apagado de fábrica y en cada reinicio)",
                   "Ver los nombres admitidos; se declaran en acceso.yml, exactos y sin comodines"]},
    {"grupo": "Ajustes", "ruta": "/canal", "nombre": "Canal",
     "para_que": "El canal de Telegram: quién puede escribir a qué proyecto, y el registro de lo que entra y sale.",
     "que_haces": ["Conceder o quitar permisos del canal"]},
    {"grupo": "Ajustes", "ruta": "/encargos", "nombre": "Encargos",
     "para_que": "Encargos que te manda otra gente por el bot, y quién puede mandarlos.",
     "que_haces": ["Ver los encargos y su conversación", "Dar de alta a quien puede mandarlos"]},
]


def _cuenta(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def pasos(con: sqlite3.Connection, paneles: list[dict], niveles: dict[str, str],
          existe=lambda ruta: True) -> list[dict[str, Any]]:
    """Los primeros pasos, cada uno con `hecho` medido sobre el estado real.

    `paneles`, `niveles` y `existe` llegan de fuera —de `api.py`— para que esto
    no lea tmux ni el disco por su cuenta (una sola costura de lectura).

    🔴 Un proyecto cuenta sólo si su carpeta **existe**. El registro recién
    instalado trae dos de ejemplo con rutas inventadas, y contándolos el paso
    «registra tu primer proyecto» salía hecho sin que nadie hubiera registrado
    nada (visto en la sala limpia del 16-oct).
    """
    hay_asistente = _cuenta(con, "SELECT COUNT(*) FROM proyecto WHERE tipo = 'asistente'") > 0
    filas = con.execute(
        "SELECT id, asiento FROM proyecto WHERE tipo NOT IN ('asistente', 'kit') ORDER BY id").fetchall()
    proyectos = [f for f in filas if f[1] and existe(f[1])]
    fantasmas = [f[0] for f in filas if not (f[1] and existe(f[1]))]
    slots = _cuenta(con, "SELECT COUNT(*) FROM slot WHERE status = 'activo'")
    con_slot = sum(1 for p in paneles if p.get("slot_id"))
    repos = _cuenta(con, "SELECT COUNT(*) FROM repo")
    con_nivel = sum(1 for n in niveles.values() if n and n != "nada")
    primero = proyectos[0][0] if proyectos else None

    lista = [
        {"id": "asistente", "titulo": "Instala el asistente",
         "por_que": "Es el chat de abajo a la derecha. Te explica cada pantalla, te lleva a ella y "
                    "hace contigo lo básico: registrar proyectos, crear slots, apuntar notas.",
         "como": "En una terminal, dentro de la carpeta del hub: bash scripts/sembrar-asistente.sh. "
                 "Se declara solo; en menos de un minuto sale el chat.",
         "hecho": hay_asistente, "enlace": None, "pregunta": None},
        {"id": "proyecto", "titulo": "Registra tu primer proyecto",
         "por_que": "Todo lo que el hub enseña sale de su registro. Sin proyectos, las pantallas están vacías.",
         "como": "Si ya existe, pídeselo al asistente («quiero registrar un proyecto que ya tengo»). "
                 "Si es nuevo, botón «Proyecto nuevo» en el Panorama."
                 + (f" En tu registro hay {len(fantasmas)} cuya carpeta no existe "
                    f"({', '.join(fantasmas[:3])}{'…' if len(fantasmas) > 3 else ''}): no cuentan. "
                    "Si son los de ejemplo, bórralos de projects.yml cuando quieras."
                    if fantasmas else ""),
         "hecho": bool(proyectos), "enlace": {"ruta": "/", "etiqueta": "Ir al Panorama"},
         "pregunta": "Quiero registrar mi primer proyecto en el hub. Guíame paso a paso."},
        {"id": "slot", "titulo": "Crea un slot",
         "por_que": "Un slot es una línea de trabajo con nombre («bug del login»). Guarda su nota "
                    "aunque se caiga todo, y te lleva a su ventana con un clic.",
         "como": "En la ficha del proyecto, sección Slots: «Slot nuevo», debajo de la lista.",
         "hecho": slots > 0,
         "enlace": {"ruta": f"/proyecto/{primero}#slots" if primero else "/",
                    "etiqueta": "Ir a sus slots" if primero else "Ir al Panorama"},
         "pregunta": "¿Qué es un slot y cómo creo el primero?"},
        {"id": "trabajo", "titulo": "Trabaja desde Trabajo",
         "por_que": "Slots a la izquierda, terminal en medio, nota a la derecha: es donde se pasa el día.",
         "como": "En la lista de la izquierda, «Lanzar» bajo el slot abre su ventana. Lo que abras sin slot cae a la bandeja.",
         "hecho": con_slot > 0, "enlace": {"ruta": "/trabajo", "etiqueta": "Ir a Trabajo"},
         "pregunta": "Explícame la pantalla de Trabajo: qué hay en cada parte y cómo la uso."},
        {"id": "respaldo", "titulo": "Mira qué falta por respaldar",
         "por_que": "Commits sin subir y repos sin remoto: lo que perderías si hoy se rompe el disco.",
         "como": "Respaldo lo mide solo cada rato; «Medir ahora» lo mide en el momento.",
         "hecho": repos > 0, "enlace": {"ruta": "/respaldo", "etiqueta": "Ir a Respaldo"},
         "pregunta": "¿Cómo leo la pantalla de Respaldo y qué hago con lo que sale?"},
        {"id": "orquestador", "titulo": "Prueba el orquestador", "opcional": True,
         "por_que": "Le das una tarea y él se la pide a las sesiones de tus proyectos, sin que estés delante.",
         "como": "Primero dale alcance a un proyecto en Orquestador → Permisos; por defecto no llega a ninguno.",
         "hecho": con_nivel > 0, "enlace": {"ruta": "/orquestador/permisos", "etiqueta": "Ir a Permisos"},
         "pregunta": "¿Cómo funciona el orquestador y qué nivel le doy a un proyecto?"},
    ]
    siguiente = next((p for p in lista if not p["hecho"] and not p.get("opcional")), None)
    for p in lista:
        p.setdefault("opcional", False)
        p["siguiente"] = p is siguiente
        if not hay_asistente:
            p["pregunta"] = None     # sin asistente, «Guíame» sólo podría fallar
    return lista


def mapa() -> list[dict[str, Any]]:
    """Las pantallas, agrupadas en el orden en que se presentan."""
    grupos: dict[str, list[dict[str, Any]]] = {}
    for p in PANTALLAS:
        grupos.setdefault(p["grupo"], []).append(p)
    return [{"grupo": g, "pantallas": ps} for g, ps in grupos.items()]
