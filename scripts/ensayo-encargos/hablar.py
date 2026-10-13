"""Hablar con el canal de ensayo y esperar la contestación.

    hablar.py "<texto>"                     como la persona
    hablar.py --dueno "<texto>" [reply_to]  como el dueño (contestando a un mensaje)
    hablar.py --boton <message_id> <data>   pulsar un botón (aprobado, no, "otra ronda")
    hablar.py --espera                      sólo esperar a que salga algo

Mete el mensaje en `entrada.jsonl` de HUB_HOME y espera (hasta 150 s) a que
salga algo nuevo en `salida.jsonl`; imprime todo lo nuevo, con su message_id,
que es lo que hace falta para contestar a un plan o pulsar su botón.
"""
import json, os, sys, time
from pathlib import Path

SB = Path(os.environ.get("HUB_HOME", "")).resolve()
E, S = SB / "entrada.jsonl", SB / "salida.jsonl"
ELLA, DUENO = 555000002, 555000001
antes = len(S.read_text().splitlines()) if S.exists() else 0
args = sys.argv[1:]
if args and args[0] == "--boton":
    d = {"user": DUENO, "nombre": "Quien aprueba", "boton": args[2], "message_id": int(args[1])}
elif args and args[0] == "--dueno":
    d = {"user": DUENO, "nombre": "Quien aprueba", "text": args[1]}
    if len(args) > 2:
        d["reply_to"] = int(args[2])
elif args and args[0] == "--espera":
    d = None
else:
    d = {"user": ELLA, "nombre": "Persona", "text": " ".join(args)}
if d:
    with E.open("a") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
tope = time.time() + 150
quieto = None
while time.time() < tope:
    lineas = S.read_text().splitlines()
    if len(lineas) > antes:
        # Las fotos y su pregunta salen en tanda: se espera a 6 s de silencio.
        if quieto is None or len(lineas) != quieto[0]:
            quieto = (len(lineas), time.time())
        elif time.time() - quieto[1] > 6:
            break
    time.sleep(1.5)
for l in S.read_text().splitlines()[antes:]:
    m = json.loads(l)
    a = "ELLA " if m["a"] == ELLA else "DUEÑO"
    cuerpo = m.get("texto") or ("FOTO " + m["foto"] + " · " + m.get("pie", ""))
    print(f"[{m['t']} → {a} #{m['message_id']}] {cuerpo}" + (f"  botones={m['botones']}" if m.get("botones") else ""))
