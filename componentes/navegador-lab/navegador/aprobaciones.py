"""La cola de aprobaciones: un archivo por pregunta.

Archivos y no una base ni un socket, para que cualquiera pueda contestar —la
terminal (`nav aprobar`), el hub o un puente de Telegram— sin acoplarse al
guardián. La pregunta lleva sólo lo necesario para decidir (acción, método,
destino sin query); nunca el cuerpo de la petición.

Sin respuesta en `espera` segundos, la respuesta es NO: una petición colgada que
se aprueba sola cuando nadie mira es justo lo que esto existe para evitar.
"""
import asyncio
import json
import secrets
import time
from pathlib import Path


class Aprobaciones:
    def __init__(self, carpeta: Path, espera: float = 300, al_preguntar=None):
        self.carpeta, self.espera, self.al_preguntar = Path(carpeta), espera, al_preguntar

    async def pedir(self, **pregunta) -> bool:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        pid = time.strftime("%H%M%S-") + secrets.token_hex(3)
        ruta = self.carpeta / f"{pid}.json"
        ruta.write_text(json.dumps({"id": pid, "estado": "pendiente", "creada": time.time(),
                                    **pregunta}, ensure_ascii=False))
        if self.al_preguntar:
            try:
                self.al_preguntar(pid)
            except Exception as e:   # un aviso que no sale no puede tumbar la pregunta
                print(f"no salió el aviso de {pid}: {e}", flush=True)
        fin = time.monotonic() + self.espera
        while time.monotonic() < fin:
            await asyncio.sleep(0.3)
            estado = json.loads(ruta.read_text()).get("estado")
            if estado in ("aprobada", "denegada"):
                return estado == "aprobada"
        d = json.loads(ruta.read_text())
        d["estado"] = "caducada"
        ruta.write_text(json.dumps(d, ensure_ascii=False))
        return False

    def pendientes(self) -> list[dict]:
        if not self.carpeta.exists():
            return []
        out = [json.loads(r.read_text()) for r in sorted(self.carpeta.glob("*.json"))]
        return [d for d in out if d.get("estado") == "pendiente"]

    def responder(self, pid: str, aprobar: bool) -> dict:
        ruta = self.carpeta / f"{pid}.json"
        if "/" in pid or not ruta.exists():
            raise KeyError(pid)
        d = json.loads(ruta.read_text())
        if d.get("estado") != "pendiente":
            raise ValueError(f"ya está {d.get('estado')}")
        d["estado"] = "aprobada" if aprobar else "denegada"
        d["respondida"] = time.time()
        ruta.write_text(json.dumps(d, ensure_ascii=False))
        return d
