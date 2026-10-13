"""El canal de encargos entero, sin Telegram: para ensayar con agentes DE VERDAD.

    HUB_HOME=<carpeta-de-ensayo> uv run python scripts/ensayo-encargos/rele.py

Base propia (la de HUB_HOME), agentes reales en tmux, y un bot que en vez de
mandar a Telegram escribe en `salida.jsonl` y lee de `entrada.jsonl`. Es lo
que permitió el recorrido completo del 19-sep (decisiones 240-242): una
persona inventada de punta a punta —alta, entrevista, boceto, plan, botones,
construcción, publicación y segunda ronda— sin un teléfono delante.

🔴 HUB_HOME tiene que ser una carpeta APARTE: con la real, esto y `hub-encargos`
se pisarían el mismo encargo. Copia dentro `encargos.yml` (la transcripción y
el bloque `despliegue`; el token no se usa) y la carpeta `estilos/`, y deja un
`projects.yml` con `proyectos: []`. Ver `alta.py` y `hablar.py` al lado.
"""
import json, os, sys, time, traceback
from pathlib import Path

SB = Path(os.environ.get("HUB_HOME", "")).resolve()
if not SB.is_dir() or SB == Path.home() / ".local/share/hub":
    sys.exit("HUB_HOME tiene que apuntar a una carpeta de ensayo aparte (ver el docstring)")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from hub import config, db, rele_encargos, registry, snapshotter  # noqa: E402

ENTRADA, SALIDA, LOG = SB / "entrada.jsonl", SB / "salida.jsonl", SB / "rele.log"
ENTRADA.touch(); SALIDA.touch()


def log(*a):
    with LOG.open("a") as f:
        f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


class BotDeArchivo:
    """Lo que el relé le pide al bot, apuntado en archivos en vez de mandado."""

    def __init__(self):
        # Al arrancar no se vuelve a inyectar lo ya leído, y los ids siguen:
        # reiniciar el relé a mitad es parte del ensayo, no un accidente.
        self.leidas = len(ENTRADA.read_text().splitlines())
        self.uid = self.leidas
        ids = [json.loads(l)["message_id"] for l in SALIDA.read_text().splitlines() if l.strip()]
        self.mid = max(ids + [1000])

    def _fuera(self, **d):
        self.mid += 1
        d["message_id"] = self.mid; d["t"] = time.strftime("%H:%M:%S")
        with SALIDA.open("a") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        return self.mid

    def enviar(self, chat_id, texto): return self._fuera(a=int(chat_id), texto=texto)
    def enviar_foto(self, chat_id, ruta, pie=""): return self._fuera(a=int(chat_id), foto=str(ruta), pie=pie)
    def enviar_con_botones(self, chat_id, texto, botones): return self._fuera(a=int(chat_id), texto=texto, botones=list(botones))
    def pulsado(self, callback_id, texto=""): log("pulsado", callback_id, texto)
    def quitar_botones(self, chat_id, message_id): log("quitar_botones", chat_id, message_id)
    def escribiendo(self, chat_id): log("escribiendo…", chat_id)
    def descargar(self, file_id, destino): raise RuntimeError("el ensayo no lleva audios")

    def actualizaciones(self, offset=None):
        lineas = ENTRADA.read_text().splitlines()
        nuevas, self.leidas = lineas[self.leidas:], len(lineas)
        out = []
        for l in nuevas:
            if not l.strip():
                continue
            d = json.loads(l); self.uid += 1
            de = {"id": d["user"], "username": d.get("username", f"u{d['user']}"),
                  "first_name": d.get("nombre", "Persona")}
            if d.get("boton"):
                out.append({"update_id": self.uid, "callback_query": {
                    "id": f"cb{self.uid}", "from": de, "data": d["boton"],
                    "message": {"message_id": d["message_id"], "chat": {"id": d["user"]}}}})
            else:
                self.mid += 1
                m = {"message_id": self.mid, "from": de, "text": d["text"], "chat": {"id": d["user"]}}
                if d.get("reply_to"):
                    m["reply_to_message"] = {"message_id": d["reply_to"]}
                out.append({"update_id": self.uid, "message": m})
            log("entra", json.dumps(d, ensure_ascii=False)[:120])
        return out


def main():
    con = db.conectar(config.DB_PATH); db.inicializar(con)
    bot = BotDeArchivo(); offset = None; ajustes = rele_encargos.ajustes()
    atrib = registry.Atribuidor(registry.cargar())
    ultimo_snap = 0.0
    log("arranca; despliegue:", rele_encargos.despliegue_configurado(ajustes))
    while True:
        try:
            # Sin demonio de snapshots, aquí se muestrea a mano: es el puente por
            # el que el hub sabe en qué panel vive el slot de cada agente.
            if time.time() - ultimo_snap > 8:
                snapshotter.capturar(con, atrib); ultimo_snap = time.time()
            offset = rele_encargos.una_vuelta(con, bot, offset, ajustes)
        except Exception:  # noqa: BLE001 - como el relé real: una vuelta mala no lo mata
            log("EXC", traceback.format_exc())
        time.sleep(2)


if __name__ == "__main__":
    main()
