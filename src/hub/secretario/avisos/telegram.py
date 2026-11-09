"""Avisos por el Telegram del canal de consulta.

El secretario deja un timbre y lo manda `hub-canal`, el único que tiene ese
token (regla dura 22): este servicio nunca ve el token del bot. La cola es
`timbre` (decisión 341); aquí sólo se dice qué pantalla y qué título lleva.
"""

from __future__ import annotations

from ... import timbre
from . import Aviso, Canal

TOPE = 900
#: El título por omisión de un `Aviso` repite la pantalla: no se manda.
_SIN_TITULO = Aviso.__dataclass_fields__["titulo"].default


class CanalTelegram(Canal):
    id = "telegram"
    nombre = "Telegram"

    def disponible(self):
        """Listo sólo si el aviso va a llegar a alguien (C-0060).

        Con `canal.yml` no basta: sin un token que `hub-canal` haya podido leer,
        el timbre se queda en la cola; sin dueño marcado en /canal, el relé lo
        descarta. En los dos casos la cadena apuntaba «salió por telegram» y no
        llegaba a nadie, y respaldo no es caer en silencio (decisión 306). Sin
        abrir el token: lo dice el veredicto que deja el relé (C-0144)."""
        import sqlite3

        from ... import canal, config, db, rele
        if not config.canal_yml().is_file():
            return "el Canal no está configurado (/canal)"
        token = rele.estado()
        if not token.get("configurado"):
            return f"hub-canal no tiene un token que sirva: {token.get('detalle')}"
        try:
            con = db.conectar()
            try:
                quien = canal.dueno(con)
            finally:
                con.close()
        except (sqlite3.Error, db.BaseIlegible) as exc:
            return f"no se pudo mirar quién es el dueño en /canal: {exc}"
        return None if quien else "nadie está marcado como dueño en /canal"

    def mandar(self, aviso: Aviso):
        timbre.tocar(aviso.texto[:TOPE], pantalla="Secretario",
                     titulo=None if aviso.titulo == _SIN_TITULO else aviso.titulo)


PROVEEDOR = CanalTelegram()
