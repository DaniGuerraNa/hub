"""WhatsApp, PROVISIONAL (decisiones 323 y 331): lo que vuelca un lector de WhatsApp Web.

Tres escriben aquí, con `origen` en cada línea: el colector sin ventana de
abajo (`vivo`/`recogido`), y el lector que corre dentro de WhatsApp Web en tu
Chrome (`extension`) o en la app de escritorio de Windows (`escritorio`),
`componentes/whatsapp-web/lector/`. Los dos últimos no abren ninguna sesión
nueva: leen la que ya usas. `comparar()` dice cuál vio qué.

El hub no habla con WhatsApp. Un proceso aparte en Node
(`componentes/whatsapp-web/colector.js`, con whatsapp-web.js sobre el WhatsApp
Web real) escucha la cuenta del dueño y escribe en
`HUB_HOME/secretario/whatsapp/`:

- `mensajes.jsonl`: un mensaje por línea, sólo se añade;
- `chats.json`: la lista de chats, para elegir «Sólo estas»;
- `estado.json`: qué hace y su latido, cada minuto.

Esta fuente sólo lee esos archivos: no abre la sesión ni la toca, así que
`hub-web` puede pintar `disponible()` sin ver ninguna llave (decisión 298).

🔴 **Riesgo:** WhatsApp no permite clientes no oficiales y puede cerrar la
cuenta aunque sólo se lea (`INVESTIGACION-WHATSAPP.md` §3). Por eso está
apagada por omisión, como todas menos la del hub, y es provisional: la
recomendación de la investigación es whatsmeow, y cambiar a él es cambiar el
colector, no esta fuente, si escribe el mismo JSONL.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ... import config, llavero
from .. import memoria
from ..piezas import Evento, Fuente, alias_del_dueno, conversacion_admitida, para_mi

#: Sin latido en este tiempo, el colector está parado (escribe uno por minuto).
LATIDO_MAXIMO = 300
#: Líneas por lectura: un JSONL de semanas no entra de golpe en la memoria; lo
#: que queda se lee en la vuelta siguiente, con el cursor donde se quedó.
POR_LECTURA = 2000
ORDEN = "uv run python -m hub.secretario whatsapp"

# Lo que no se descarga, dicho para quien lee la memoria: «[audio]» a secas
# haría creer que se escuchó.
TIPOS = {
    "image": "[imagen]", "video": "[vídeo]", "audio": "[audio sin transcribir]",
    "ptt": "[nota de voz sin transcribir]", "document": "[documento]", "sticker": "[sticker]",
    "location": "[ubicación]", "vcard": "[contacto]", "multi_vcard": "[contactos]",
    "poll_creation": "[encuesta]", "album": "[álbum]",
}


def carpeta() -> Path:
    return memoria.carpeta() / "whatsapp"


def secretos() -> Path:
    """Dónde guarda la sesión el colector. La misma variable que lee él: un
    `credenciales:` en `fuentes.yml` aquí no movería su carpeta, y dos sitios
    que deben coincidir acaban no coincidiendo."""
    return Path(os.environ.get("HUB_SECRETARIO_WHATSAPP", "~/.secretos/secretario-whatsapp")).expanduser()


#: Para el inventario del llavero (C-0143). Es una sesión vinculada: no se
#: sube, se vuelve a vincular.
LLAVES = (llavero.Llave("secretario-whatsapp", "la sesión de WhatsApp vinculada", lambda: str(secretos()),
                        sesion=True),)


def _estado() -> dict:
    try:
        return json.loads((carpeta() / "estado.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _hace(segundos: float) -> str:
    if segundos < 3600:
        return f"{int(segundos // 60)} min"
    if segundos < 86400:
        return f"{int(segundos // 3600)} h"
    return f"{int(segundos // 86400)} días"


#: Los lectores dentro de WhatsApp Web (decisión 331) y qué hay que abrir para que lean.
LECTORES = {"extension": "WhatsApp Web en Chrome, con la extensión del hub",
            "escritorio": "la app de WhatsApp de Windows y su lector (escritorio.cmd)"}


def _disponible_lector(est: dict) -> str | None:
    try:
        latido = datetime.fromisoformat(str(est.get("latido")).replace("Z", "+00:00"))
        pasado = (datetime.now(timezone.utc) - latido).total_seconds()
    except ValueError:
        pasado = float("inf")
    if est.get("estado") == "escuchando" and pasado <= LATIDO_MAXIMO:
        return None
    detalle = f" ({est['detalle']})" if est.get("detalle") else ""
    return f"no está leyendo{detalle}: abre {LECTORES[est['origen']]}"


def comparar(dias: int = 7) -> dict:
    """Qué vio cada lector en los últimos `dias`: cuántos, cuántos sólo él y su
    retraso mediano en segundos (de `hora` a `visto`). Para elegir entre la
    extensión y la app con lo medido, no con lo que suena bien en papel."""
    desde = datetime.now(timezone.utc).timestamp() - dias * 86400
    vistos: dict[str, dict[str, float]] = {}
    try:
        lineas = (carpeta() / "mensajes.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        lineas = []
    for cruda in lineas:
        try:
            l = json.loads(cruda)
            hora = datetime.fromisoformat(str(l["hora"]).replace("Z", "+00:00")).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        if hora < desde:
            continue
        try:
            retraso = datetime.fromisoformat(str(l["visto"]).replace("Z", "+00:00")).timestamp() - hora
        except (ValueError, KeyError, TypeError):
            retraso = float("nan")
        vistos.setdefault(str(l.get("origen") or "?"), {}).setdefault(str(l["id"]), retraso)
    todos = set().union(*[set(v) for v in vistos.values()]) if vistos else set()
    out = {"mensajes": len(todos), "por_origen": {}}
    for origen, ids in sorted(vistos.items()):
        otros = set().union(*[set(v) for o, v in vistos.items() if o != origen]) if len(vistos) > 1 else set()
        retrasos = sorted(r for r in ids.values() if r == r)
        out["por_origen"][origen] = {
            "vistos": len(ids), "solo_este": len(set(ids) - otros),
            "retraso_mediano_s": round(retrasos[len(retrasos) // 2], 1) if retrasos else None,
        }
    return out


def _texto(linea: dict) -> str:
    texto = (linea.get("texto") or "").strip()
    marca = TIPOS.get(linea.get("tipo") or "chat")
    if marca is None and linea.get("multimedia"):
        marca = "[adjunto]"
    if marca:
        return f"{marca} {texto}".strip()
    return texto


class FuenteWhatsapp(Fuente):
    id = "whatsapp"
    nombre = "WhatsApp (provisional)"
    descripcion = ("Tus chats de WhatsApp, leídos dentro de WhatsApp Web (extensión de Chrome o app de escritorio) "
                   "o por el colector sin ventana. Sólo lectura. No es oficial: WhatsApp podría bloquear la cuenta.")
    intervalo = 60

    def disponible(self) -> str | None:
        est = _estado()
        estado = est.get("estado")
        if est.get("origen") in LECTORES:
            return _disponible_lector(est)
        if not est and not (secretos() / "session").is_dir():
            return f"no hay sesión de WhatsApp: corre «{ORDEN} entrar» y escanea el QR"
        if estado in ("sin-sesion", "esperando-qr"):
            return f"no hay sesión de WhatsApp: corre «{ORDEN} entrar» y escanea el QR"
        if estado == "sesion-cerrada":
            return f"WhatsApp cerró la sesión: vuelve a vincular con «{ORDEN} entrar»"
        if estado == "vinculada":
            return f"ya está vinculada; falta arrancar el colector: «{ORDEN} escuchar»"
        try:
            latido = datetime.fromisoformat(str(est.get("latido")).replace("Z", "+00:00"))
        except ValueError:
            return f"el colector no ha escrito nunca: arráncalo con «{ORDEN} escuchar»"
        pasado = (datetime.now(timezone.utc) - latido).total_seconds()
        if pasado > LATIDO_MAXIMO:
            detalle = f" ({est['detalle']})" if est.get("detalle") else ""
            return (f"el colector no está escribiendo desde hace {_hace(pasado)}{detalle}: "
                    f"arráncalo con «{ORDEN} escuchar»")
        return None

    def conversaciones(self) -> list[str]:
        try:
            chats = json.loads((carpeta() / "chats.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [c["nombre"] for c in chats if isinstance(c, dict) and c.get("nombre")]

    def leer(self, cursor: str, ajustes: dict) -> tuple[list[Evento], str]:
        """Desde el byte donde se quedó. El cursor lleva también el inodo: si el
        archivo se borró o se cambió por otro, se empieza de cero y la memoria
        quita los repetidos (`fuente + id_externo`)."""
        ruta = carpeta() / "mensajes.jsonl"
        try:
            pos = json.loads(cursor) if cursor else {}
        except ValueError:
            pos = {}
        try:
            st = ruta.stat()
        except FileNotFoundError:
            return [], json.dumps(pos)
        offset = int(pos.get("offset") or 0)
        if pos.get("inodo") != st.st_ino or offset > st.st_size:
            offset = 0
        incluir = [c.strip().lower() for c in ajustes.get("incluir") or []]
        eventos: list[Evento] = []
        with ruta.open("rb") as f:
            f.seek(offset)
            for _ in range(POR_LECTURA):
                cruda = f.readline()
                # Una última línea sin salto es una que el colector aún está
                # escribiendo: se deja para la vuelta siguiente, entera.
                if not cruda.endswith(b"\n"):
                    break
                offset += len(cruda)
                try:
                    linea = json.loads(cruda)
                except ValueError:
                    continue  # una línea rota no para las demás
                if not isinstance(linea, dict) or not linea.get("id"):
                    continue
                ev = self._evento(linea, ajustes, incluir)
                if ev:
                    eventos.append(ev)
        return eventos, json.dumps({"offset": offset, "inodo": st.st_ino})

    def _evento(self, linea: dict, ajustes: dict, incluir: list[str]) -> Evento | None:
        chat = str(linea.get("chat") or "")
        nombre = str(linea.get("chat_nombre") or chat)
        if chat == "status@broadcast":
            return None
        # Los canales (difusión de terceros) no son conversaciones suyas: sólo
        # si los pide por nombre, como en Telegram.
        if chat.endswith("@newsletter") and nombre.lower() not in incluir:
            return None
        if not conversacion_admitida(ajustes, nombre):
            return None
        texto = _texto(linea)
        if not texto:
            return None
        # Las etiquetas de WhatsApp llegan como un número (@5215…), no como su
        # nombre: en un grupo, por ahora, sólo se sabe si lo nombran (decisión 332).
        return Evento(fuente=self.id, id_externo=str(linea["id"]), fecha=str(linea.get("hora") or ""),
                      texto=texto, conversacion=nombre, autor=str(linea.get("autor") or ""),
                      para_mi="" if linea.get("de_mi") else para_mi(texto, alias_del_dueno(ajustes),
                                                                    grupo=bool(linea.get("grupo"))))


def componente() -> Path:
    return config.RAIZ_REPO / "componentes" / "whatsapp-web"


def colector(orden: str) -> int:  # pragma: no cover - abre WhatsApp Web de verdad
    """Lanza el colector con el mismo `HUB_HOME` que este hub, para que escriba
    donde esta fuente lee. Sin `npm install` previo lo dice en vez de fallar
    con una traza de Node."""
    if orden == "comparar":
        print(json.dumps(comparar(), ensure_ascii=False, indent=2))
        return 0
    if orden not in ("entrar", "escuchar", "comprobar"):
        print("uso: uv run python -m hub.secretario whatsapp entrar | escuchar | comprobar | comparar")
        return 2
    if not shutil.which("node"):
        print("falta Node (22 o más) para el colector de WhatsApp")
        return 2
    if not (componente() / "node_modules" / "whatsapp-web.js").is_dir():
        print(f"falta instalar el colector: cd {componente()} && PUPPETEER_SKIP_DOWNLOAD=1 npm ci")
        return 2
    env = os.environ | {"HUB_HOME": str(config.HUB_HOME)}
    return subprocess.call(["node", "colector.js", orden], cwd=componente(), env=env)


FUENTE = FuenteWhatsapp()
