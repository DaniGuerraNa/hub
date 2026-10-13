"""El botón de pánico: levantar el hub por Telegram cuando no se puede entrar.

Idea suya, y la razón por la que vale la pena no es obvia: **Telegram es una
conexión que sale de casa**. Funciona donde el hub no —si Tailscale se cae, si
el router hace algo raro, si `hub-web` se quedó colgado—, y por eso es un
segundo camino que no depende del primero. Sin esto, un `hub-web` muerto
estando de viaje sólo se arregla con el escritorio remoto, o llamando a alguien.

🔴 **La lista de acciones es cerrada, y esto no es una precaución: es la línea
entera.** Un «ejecuta este comando» por Telegram significa que quien entre en
ese chat tiene una shell en la máquina de casa, y entonces toda la puerta que
sostiene el acceso remoto —el alta de dispositivos (160), el interruptor de la
terminal (163)— pasaría a colgar de la seguridad de una cuenta de Telegram. Se
puede pedir UNA cosa, la que él pidió: que el hub vuelva a levantarse.

🔴 **Sólo el dueño**, comparando `user_id`, y queda en el registro del canal
como todo lo que entra y sale. Y lo ejecuta `hub-canal`, que es el proceso que
ya lee el token (regla dura 22); `hub-web` no toca esto ni podría — es
precisamente al que se reinicia.

Lo que este botón **no** puede hacer, dicho aquí para que nadie lo espere: vive
dentro de WSL, así que si la VM muere, muere con ella —de eso se encarga sola
la tarea de Windows que la sostiene— y si Windows se cuelga o se va la luz, no
hay software que valga. Para eso están el SAI y el arranque por BIOS.
"""

from __future__ import annotations

import subprocess

# Lo que se reinicia, por nombre exacto y de uno en uno (el criterio de la
# regla dura 12 sobre docker vale igual aquí). `hub-canal` NO está en la lista:
# es quien lee el mensaje y quien contesta, así que reiniciarlo sería colgar la
# llamada en mitad de la frase — y systemd ya lo levanta solo si cae.
SERVICIOS = ("hub-web", "hub-snapshotter")

# Se escribe entero y sin acento obligatorio. Una palabra rara a propósito: un
# botón de pánico que se dispara por un «ok» mal puesto reinicia el hub en
# mitad de una sesión de trabajo.
ORDENES = ("panico", "pánico", "/panico", "/pánico")

ESPERA = 30


def reconocer(texto: str) -> bool:
    """¿Es el botón de pánico? Exacto, sin prefijos ni frases que lo contengan."""
    return texto.strip().lower() in ORDENES


def reiniciar() -> tuple[bool, str]:
    """Levanta el hub. Devuelve si quedó vivo y qué contar.

    No se afirma «reiniciado» por que `systemctl` devuelva 0: eso dice que la
    orden salió, no que el hub conteste. Es la misma trampa de la decisión 151
    —un comando que sale bien y no deja detrás lo que parecía— y aquí la
    pagaría alguien que está lejos y se queda tranquilo con un hub muerto.
    """
    hechos: list[str] = []
    for servicio in SERVICIOS:
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", servicio],
                capture_output=True, text=True, timeout=ESPERA, check=True,
            )
            hechos.append(servicio)
        except Exception as exc:
            return False, f"no se pudo reiniciar {servicio}: {exc}"

    vivo, detalle = _contesta()
    if not vivo:
        return False, f"reinicié {', '.join(hechos)} pero el hub no contesta: {detalle}"
    return True, (
        f"Hub reiniciado ({', '.join(hechos)}) y contestando {detalle}.\n"
        "Ojo: la terminal desde fuera vuelve a estar cerrada — se apaga en cada "
        "reinicio a propósito, la abres en /acceso."
    )


def _contesta() -> tuple[bool, str]:
    """Que el hub sirva una página, que es lo que se quería comprobar."""
    import time
    import urllib.error
    import urllib.request

    from . import config

    url = f"http://127.0.0.1:{config.WEB_PORT}/"
    for intento in range(6):
        inicio = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=5) as respuesta:
                if respuesta.status == 200:
                    return True, f"en {time.monotonic() - inicio:.1f} s"
        except (urllib.error.URLError, OSError) as exc:
            ultimo = str(exc)
        else:
            ultimo = f"código {respuesta.status}"
        time.sleep(1 + intento)   # arrancar tarda; no se le pregunta una vez y ya
    return False, ultimo
