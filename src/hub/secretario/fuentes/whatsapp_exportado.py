"""Chats de WhatsApp exportados a mano (decisión 326): la vía sin riesgo.

En el teléfono, en un chat: ⋮ → Más → **Exportar chat** → «Sin archivos». Sale
un `.txt` (o un `.zip` con él dentro) que se deja en
`HUB_HOME/secretario/whatsapp-exportado/`. Esta fuente lo lee y lo vuelve
mensajes de la memoria, como los de cualquier otra.

Es lo único de WhatsApp que **no incumple sus términos**: no hay ningún cliente
conectado a la cuenta, sólo un archivo que el dueño sacó con el botón de
WhatsApp. A cambio, no es en vivo: lee lo que se exporte, cuando se exporte.
Convive con la fuente provisional (`whatsapp.py`); son fuentes distintas y la
memoria no las mezcla.

El formato cambia con el teléfono y el idioma. Se entienden los de Android e
iPhone en español e inglés: `1/11/26, 10:15 - Ana: hola`,
`01/11/2026, 10:15 a. m. - Ana: hola` y `[1/11/26, 10:15:30] Ana: hola`. El
orden día/mes sale del archivo cuando un número pasa de 12; si ninguno pasa, se
supone día/mes (México) salvo `orden: mdy` en los ajustes de la fuente.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from .. import memoria
from ..piezas import Evento, Fuente, conversacion_admitida
from ..tiempo import a_utc

_LINEA = re.compile(
    r"^‎?\[?(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<c>\d{2,4}),?\s+(?P<h>\d{1,2}):(?P<m>\d{2})(?::\d{2})?"
    r"[\s  ]*(?P<ampm>[ap]\.?[\s  ]?m\.?)?\]?\s*(?:-\s)?(?P<resto>.*)$",
    re.IGNORECASE)
_NOMBRE_ARCHIVO = re.compile(r"^(?:Chat de WhatsApp con|WhatsApp Chat with|WhatsApp Chat -)\s*(?P<n>.+)$",
                             re.IGNORECASE)
_OMITIDO = re.compile(r"^<?(multimedia omitido|media omitted|imagen omitida|image omitted|audio omitido|"
                      r"audio omitted|video omitido|video omitted|sticker omitido|sticker omitted|"
                      r"documento omitido|document omitted)>?$", re.IGNORECASE)


def _dueno() -> str:
    from ..conversacion import ajustes as ajustes_secretario
    return str(ajustes_secretario().get("dueno") or "")


def carpeta() -> Path:
    return memoria.carpeta() / "whatsapp-exportado"


def _nombre_chat(archivo: str) -> str:
    base = Path(archivo).stem
    m = _NOMBRE_ARCHIVO.match(base)
    return (m.group("n") if m else base).strip() or "WhatsApp"


def _textos(ruta: Path) -> list[tuple[str, str]]:
    """(nombre del chat, texto) de un .txt o de los .txt de un .zip."""
    if ruta.suffix.lower() == ".zip":
        out = []
        with zipfile.ZipFile(ruta) as z:
            for n in z.namelist():
                if n.lower().endswith(".txt"):
                    chat = _nombre_chat(ruta.name if n.startswith("_chat") else n)
                    out.append((chat, z.read(n).decode("utf-8", errors="replace")))
        return out
    return [(_nombre_chat(ruta.name), ruta.read_text(encoding="utf-8", errors="replace"))]


def _orden(lineas: list[re.Match], forzado: str | None) -> str:
    if forzado in ("dmy", "mdy"):
        return forzado
    for m in lineas:
        if int(m["a"]) > 12:
            return "dmy"
        if int(m["b"]) > 12:
            return "mdy"
    return "dmy"


def mensajes(texto: str, orden: str | None = None) -> list[dict]:
    """Los mensajes de un export: fecha local ISO, autor y texto (multilínea unido).
    Las líneas del sistema («Los mensajes están cifrados…») no tienen autor y se saltan."""
    filas = texto.replace("\r\n", "\n").split("\n")
    marcas = [(_LINEA.match(f), f) for f in filas]
    o = _orden([m for m, _ in marcas if m], orden)
    out: list[dict] = []
    for m, cruda in marcas:
        if not m:
            if out and cruda.strip():
                out[-1]["texto"] += "\n" + cruda
            continue
        a, b, c = int(m["a"]), int(m["b"]), int(m["c"])
        dia, mes = (a, b) if o == "dmy" else (b, a)
        anio = c + 2000 if c < 100 else c
        hora = int(m["h"])
        ampm = (m["ampm"] or "").lower().replace(".", "").replace(" ", "").replace(" ", "").replace(" ", "")
        if ampm == "pm" and hora < 12:
            hora += 12
        elif ampm == "am" and hora == 12:
            hora = 0
        autor, sep, cuerpo = m["resto"].partition(": ")
        if not sep:
            out.append({"sistema": True, "texto": ""})   # para que lo que siga no se pegue al anterior
            continue
        try:
            fecha = f"{anio:04d}-{mes:02d}-{dia:02d}T{hora:02d}:{int(m['m']):02d}"
            a_utc(fecha)
        except ValueError:
            continue
        cuerpo = cuerpo.strip()
        if _OMITIDO.match(cuerpo):
            cuerpo = "[adjunto no exportado]"
        out.append({"fecha": fecha, "autor": autor.strip().lstrip("‎"), "texto": cuerpo})
    return [x for x in out if not x.get("sistema")]


class FuenteWhatsappExportado(Fuente):
    id = "whatsapp_exportado"
    nombre = "WhatsApp (exportado a mano)"
    descripcion = ("Los chats que exportes desde el teléfono (Exportar chat → Sin archivos). Sin riesgo para tu "
                   "cuenta: no se conecta nada a WhatsApp. No es en vivo: lee lo que exportes.")
    intervalo = 300

    def disponible(self) -> str | None:
        d = carpeta()
        if not d.is_dir() or not any(p.suffix.lower() in (".txt", ".zip") for p in d.iterdir()):
            return (f"no hay exportaciones: en el teléfono, en un chat, ⋮ → Más → Exportar chat → «Sin "
                    f"archivos», y deja el .txt o el .zip en {d}")
        return None

    def conversaciones(self) -> list[str]:
        d = carpeta()
        if not d.is_dir():
            return []
        nombres = set()
        for p in sorted(d.iterdir()):
            if p.suffix.lower() == ".txt":
                nombres.add(_nombre_chat(p.name))
            elif p.suffix.lower() == ".zip":
                nombres.add(_nombre_chat(p.name))
        return sorted(nombres)

    def leer(self, cursor: str, ajustes: dict) -> tuple[list[Evento], str]:
        """Cada archivo nuevo o cambiado se lee entero; la memoria quita los
        mensajes que ya tenía (`fuente + id_externo`), así que exportar otra vez
        el mismo chat sólo añade lo nuevo."""
        try:
            vistos = json.loads(cursor) if cursor else {}
        except ValueError:
            vistos = {}
        d = carpeta()
        if not d.is_dir():
            return [], json.dumps(vistos)
        # Quién es «Yo» en el export (ahí sale su nombre de contacto): `yo:` en los
        # ajustes, o el nombre del dueño de `secretario.yml`. Sin «Yo» el triaje
        # no ve lo que él prometió (decisión 302).
        nombres = ajustes.get("yo") or [_dueno()]
        yo = {str(n).strip().lower() for n in nombres if str(n or "").strip()}
        eventos: list[Evento] = []
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in (".txt", ".zip"):
                continue
            st = p.stat()
            huella = f"{st.st_size}:{int(st.st_mtime)}"
            if vistos.get(p.name) == huella:
                continue
            try:
                textos = _textos(p)
            except (OSError, zipfile.BadZipFile):
                continue
            for chat, texto in textos:
                if not conversacion_admitida(ajustes, chat):
                    continue
                repetidos: dict[str, int] = {}
                for msg in mensajes(texto, ajustes.get("orden")):
                    clave = hashlib.sha1(f"{chat}|{msg['fecha']}|{msg['autor']}|{msg['texto']}".encode()).hexdigest()[:16]
                    repetidos[clave] = repetidos.get(clave, 0) + 1
                    autor = "Yo" if msg["autor"].lower() in yo else msg["autor"]
                    eventos.append(Evento(fuente=self.id, id_externo=f"{clave}-{repetidos[clave]}",
                                          fecha=a_utc(msg["fecha"]), texto=msg["texto"], conversacion=chat,
                                          autor=autor))
            vistos[p.name] = huella
        return eventos, json.dumps(vistos)


FUENTE = FuenteWhatsappExportado()
