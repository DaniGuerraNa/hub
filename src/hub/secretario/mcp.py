"""Las herramientas del secretario servidas por MCP, por la entrada estándar.

Es el MCP que `CLAUDE.md` anunciaba («el futuro MCP se monta sobre `api.py`»):
lee el hub por `api.py` y la memoria por `memoria.py`, sin caminos paralelos.

Escrito a mano y sin la librería `mcp` a propósito: el protocolo que hace falta
son tres métodos JSON-RPC (`initialize`, `tools/list`, `tools/call`), y la
librería arrastra un servidor web entero para eso. Lo arranca `claude -p` con
`--mcp-config`, como hijo de `hub-secretario` — nunca de `hub-web`, que no
debe ver las llaves de las fuentes (decisión 298).
"""

from __future__ import annotations

import base64
import json
import sys
import traceback

from . import herramientas, memoria

VERSION_PROTOCOLO = "2025-06-18"


def _responder(id_, resultado=None, error=None) -> None:
    m = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        m["error"] = error
    else:
        m["result"] = resultado
    sys.stdout.write(json.dumps(m, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def atender(mensaje: dict, todas: dict, con) -> None:
    metodo, id_ = mensaje.get("method"), mensaje.get("id")
    if metodo == "initialize":
        pedida = (mensaje.get("params") or {}).get("protocolVersion") or VERSION_PROTOCOLO
        _responder(id_, {"protocolVersion": pedida, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "secretario", "version": "1"}})
    elif metodo == "tools/list":
        _responder(id_, {"tools": [{"name": h.nombre, "description": h.descripcion, "inputSchema": h.esquema}
                                   for h in todas.values()]})
    elif metodo == "tools/call":
        p = mensaje.get("params") or {}
        h = todas.get(p.get("name"))
        if not h:
            _responder(id_, {"content": [{"type": "text", "text": "herramienta desconocida"}], "isError": True})
            return
        try:
            salida = h.funcion(con, p.get("arguments") or {})
            if isinstance(salida, herramientas.Imagen):
                # Una imagen va como `content` de tipo `image`: Claude Code se
                # la enseña al modelo (medido el 7-nov, 2.1.280, decisión 384).
                _responder(id_, {"content": [
                    {"type": "text", "text": salida.texto},
                    {"type": "image", "data": base64.b64encode(salida.datos).decode(), "mimeType": salida.tipo}]})
                return
            texto = salida if isinstance(salida, str) else json.dumps(salida, ensure_ascii=False, default=str)
            _responder(id_, {"content": [{"type": "text", "text": texto[:60000]}]})
        except Exception as exc:  # una herramienta rota se dice; no tumba al servidor
            traceback.print_exc(file=sys.stderr)
            _responder(id_, {"content": [{"type": "text", "text": f"falló: {exc}"}], "isError": True})
    elif id_ is not None:
        _responder(id_, error={"code": -32601, "message": f"método no soportado: {metodo}"})
    # Las notificaciones (sin id) no llevan respuesta.


def main() -> None:
    todas = herramientas.todas()
    con = memoria.conectar()
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            atender(json.loads(linea), todas, con)
        except ValueError:
            _responder(None, error={"code": -32700, "message": "JSON no válido"})


if __name__ == "__main__":
    main()
