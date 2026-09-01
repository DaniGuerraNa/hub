"""Estado de respaldo de los repos.

Existe por el hallazgo que originó este proyecto. El 2026-08-27, en la misma
sesión en que se hacía el inventario, el usuario dio por muertos dos worktrees que
tenían **473 commits sin respaldo** de los últimos 9 días, incluidos cuatro de
esa misma mañana.

El hub indexa, no gestiona: aquí no se hace push, ni se avisa, ni se expira nada
(principio 9). Se mide y se muestra. La acción es siempre del usuario.

Medir esto es caro —los repos en `/mnt/c` van por 9p— así que no entra en el
ciclo de 20 s del snapshotter: se refresca a demanda y, muy de vez en cuando,
desde el propio demonio.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .models import Proyecto

# Un repo que no responde en 10 s está en un filesystem que no vamos a esperar.
TIEMPO_LIMITE = 10

# Presupuesto total de un escaneo completo. Medido: 4,3 s en frío para los 11
# repos reales. El límite existe para el caso malo —un montaje de `/mnt/c`
# colgado, donde cada comando agota su tiempo— porque el escaneo corre dentro
# del bucle del snapshotter y un escaneo eterno lo dejaría sin muestrear justo
# cuando el sistema va peor.
PRESUPUESTO_SEGUNDOS = 45


@lru_cache(maxsize=1)
def _hay_git() -> bool:
    """Un escaneo hace ~90 llamadas: no tiene sentido resolver el PATH en cada una."""
    return shutil.which("git") is not None


def _git(ruta: str, *args: str) -> str | None:
    """Ejecuta git y devuelve su salida, o None si falló.

    Devolver None en vez de propagar es deliberado: un repo roto, un worktree
    huérfano o un montaje caído no pueden tumbar la medición de los demás.
    """
    if not _hay_git():
        return None
    try:
        salida = subprocess.run(
            ["git", "-C", ruta, *args],
            capture_output=True,
            text=True,
            timeout=TIEMPO_LIMITE,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return salida.stdout.strip() if salida.returncode == 0 else None


def es_repo(ruta: str) -> bool:
    return _git(ruta, "rev-parse", "--git-dir") is not None


def _heads_de_worktrees(ruta: str) -> list[str]:
    """El HEAD de cada worktree del repositorio, visto desde cualquiera de ellos.

    Hace falta porque `rev-list --all` NO incluye los HEAD desatados: se midió un
    repo real cuya copia principal estaba detached, con sus commits sin colgar de
    ninguna rama. Sin esto se perderían del recuento.
    """
    salida = _git(ruta, "worktree", "list", "--porcelain") or ""
    return [
        linea.split(" ", 1)[1].strip()
        for linea in salida.splitlines()
        if linea.startswith("HEAD ") and len(linea.split(" ", 1)) == 2
    ]


def _sin_push(ruta: str) -> tuple[int | None, str]:
    """Cuántos commits del REPOSITORIO no alcanza ningún remoto, y bajo qué régimen.

    `--not --remotes` es la medida honesta, y la única que funciona igual con o
    sin upstream. Comparar contra `@{u}` o contra `origin/<rama>` falla justo en
    el caso peligroso, medido en un repo real: la rama es `dev`, `origin/dev`
    **no existe**, y esa vía contaba los 576 commits del historial entero.

    Lo que se mide es el **repositorio**, no el worktree: `--all` más los HEAD de
    todos sus worktrees. Es la segunda corrección de esta función y salió de un
    fallo real —la tercera cifra inflada de este proyecto—:

        Medir sólo `HEAD` daba, el 2026-08-27, 250 + 223 = 473, que coincidía
        con la medición a mano. Coincidía **porque los worktrees estaban en el
        mismo commit**. En cuanto una sesión semiautónoma commiteó en el
        worktree `-int` y no en la copia principal, dejaron de coincidir y el hub
        pasó a sumar 250 + 278 + 238 + 251 = **1017** commits «distintos» que en
        realidad son 278 + 251 = **529**: los mismos objetos, en el mismo
        repositorio, contados hasta cuatro veces.

    Medido así, la cifra sale idéntica desde cualquier worktree del repo, que es
    exactamente la propiedad que hace que deduplicar sea correcto y no una
    aproximación.

    El régimen es información aparte, no afecta al número:
      `con-upstream` — la rama sigue a un remoto.
      `sin-upstream` — hay remoto pero esta rama no lo sigue. Un push directo no
                       funcionará sin `-u`, así que conviene saberlo.
      `sin-remoto`   — repo local puro. No es un descuido: es una decisión.
    """
    if not _git(ruta, "remote"):
        return None, "sin-remoto"

    cuenta = _git(ruta, "rev-list", "--count", "--all", *_heads_de_worktrees(ruta),
                  "--not", "--remotes")
    regimen = "con-upstream" if _git(ruta, "rev-parse", "--abbrev-ref", "@{u}") else "sin-upstream"
    return (int(cuenta) if cuenta is not None else None), regimen


def estado_de(ruta: str) -> dict | None:
    """Fotografía de respaldo de un repo. None si la ruta no es un repo git."""
    if not Path(ruta).is_dir() or not es_repo(ruta):
        return None

    rama = _git(ruta, "symbolic-ref", "--short", "HEAD")  # None si está en detached
    sin_push, regimen = _sin_push(ruta)
    porcelain = _git(ruta, "status", "--porcelain") or ""
    detras = _git(ruta, "rev-list", "--count", "HEAD..@{u}")

    return {
        "ruta": ruta,
        "rama": rama or "(detached)",
        "sin_push": sin_push,
        "regimen": regimen,
        "detras": int(detras) if detras is not None else None,
        "sucios": len([x for x in porcelain.splitlines() if x.strip()]),
        "ultimo_commit": _git(ruta, "log", "-1", "--format=%cI"),
        "worktrees": _contar_worktrees(ruta),
        # Identidad del repositorio compartido y del commit. Dos worktrees del
        # mismo repo en el mismo commit tienen los MISMOS commits sin respaldar:
        # sumarlos por separado duplicaría la cifra. `~/dev/app` y
        # `~/dev/app-int` son exactamente ese caso.
        "repo_comun": _repo_comun(ruta),
        "head": _git(ruta, "rev-parse", "HEAD"),
    }


def _repo_comun(ruta: str) -> str | None:
    """El `.git` compartido por todos los worktrees de un mismo repositorio."""
    comun = _git(ruta, "rev-parse", "--git-common-dir")
    if not comun:
        return None
    camino = Path(comun)
    if not camino.is_absolute():
        camino = Path(ruta) / comun
    try:
        return str(camino.resolve())
    except OSError:
        return str(camino)


def _contar_worktrees(ruta: str) -> int:
    """Worktrees además del principal.

    Se midió un proyecto que arrastraba 12 huérfanos, y además inflaban la
    duplicación del método. Contarlos los hace visibles sin tocarlos.
    """
    salida = _git(ruta, "worktree", "list", "--porcelain")
    if not salida:
        return 0
    return max(0, sum(1 for linea in salida.splitlines() if linea.startswith("worktree ")) - 1)


class RespaldoNoMedido(RuntimeError):
    """No se pudo medir el respaldo, por lo que sea. Lo anterior se conserva.

    Es una excepción y no un `return 0` por una razón que costó verla: **cero
    medido y cero por no haber medido no se pueden pintar igual**, y aquí los
    dos salían como «0 commits sin respaldo». Se comprobó sobre una base ya
    buena: con git, 2 commits sin respaldo y 1 repo en riesgo; quitando git del
    PATH y reescaneando, la fila desaparecía y la pantalla afirmaba que estaba
    todo a salvo.

    El hub existe porque un día aparecieron 473 commits sin respaldar. Decir
    «no hay ninguno» cuando en realidad no se ha mirado es la única mentira que
    este módulo no se puede permitir.

    Docker ya lo hacía bien: cuando no contesta, `NoRespondio` conserva la
    lectura anterior en vez de borrarla. Esto es lo mismo para git.

    🔴 Se llamó `SinGit` y era un nombre demasiado estrecho: comprobar que el
    binario existe con `which` NO es comprobar que funciona. Con git instalado
    pero fallando —`detected dubious ownership`, que es lo normal en `/mnt/c`
    desde WSL, o un repo con permisos raros— no saltaba nada, se borraba la
    tabla y volvía el «0 commits sin respaldo» con `hay_git: True`, así que ni
    siquiera salía el aviso. El defecto original, entero, por la puerta de al
    lado.
    """


def escanear(con: sqlite3.Connection, proyectos: list[Proyecto]) -> int:
    """Repuebla la tabla `repo` recorriendo todas las rutas registradas.

    Derivado del filesystem, como el catálogo: se borra y se rehace (regla dura 1).

    🔴 Se rehace **sólo si se ha podido medir**. Sin git, lo que había sigue
    donde está y quien llama se entera por `RespaldoNoMedido`.
    """
    # La caché se vacía en cada escaneo: dura lo que dura un escaneo, que es
    # para lo que existe (~90 llamadas). Sin esto, un servicio que arrancó sin
    # git seguía diciendo «no hay git» después de instalarlo —justo lo que la
    # pantalla te acaba de mandar hacer— hasta reiniciarlo.
    _hay_git.cache_clear()
    if not _hay_git():
        raise RespaldoNoMedido(
            "git no está en el PATH: no se puede medir el respaldo. Se conserva "
            "la última medición."
        )
    medido_en = datetime.now(timezone.utc).isoformat()
    limite = time.monotonic() + PRESUPUESTO_SEGUNDOS
    filas = []
    agotado = False
    for p in proyectos:
        for ruta in p.todas_las_rutas():
            if time.monotonic() > limite:
                agotado = True
                break
            estado = estado_de(ruta)
            if estado:
                filas.append((p.id, medido_en, estado))
        if agotado:
            break

    if agotado:
        # En voz alta: un escaneo truncado en silencio se lee como «no hay nada
        # sin respaldar», que es la mentira más cara que este módulo puede decir.
        print(
            f"[repos] escaneo truncado a los {PRESUPUESTO_SEGUNDOS}s: "
            f"{len(filas)} repos medidos. La cifra de respaldo está incompleta.",
            flush=True,
        )

    # 🔴 Había rutas que mirar y no salió NINGUNA medida: git está pero no
    # funciona aquí. Es indistinguible de «no tienes repos» mirando el
    # resultado, y la diferencia es justo lo que este módulo no puede
    # equivocarse. No se borra nada y se dice.
    candidatas = [r for p in proyectos for r in p.todas_las_rutas()]
    if candidatas and not filas:
        raise RespaldoNoMedido(
            f"git no pudo leer ninguno de los {len(candidatas)} repos declarados "
            "(¿permisos, `dubious ownership`, un montaje caído?). Se conserva la "
            "última medición."
        )

    # Se reemplaza LO MEDIDO y se retira lo que ya no está declarado, en vez de
    # vaciar la tabla y volver a llenarla. La diferencia importa cuando el
    # escaneo se trunca por presupuesto: con `DELETE FROM repo` los repos que no
    # dio tiempo a mirar salían a cero —«nada sin respaldar»— y con esto
    # conservan su última cifra buena, con su `medido_en` viejo delatando que es
    # de antes.
    medidas = {e["ruta"] for _, _, e in filas}
    declaradas = set(candidatas) | medidas
    marcas = ",".join("?" * len(declaradas)) or "NULL"
    con.execute(f"DELETE FROM repo WHERE ruta NOT IN ({marcas})", tuple(declaradas))

    for proyecto_id, ts, e in filas:
        con.execute(
            """INSERT OR REPLACE INTO repo
                                (proyecto_id, ruta, rama, sin_push, regimen, detras,
                                 sucios, ultimo_commit, worktrees, repo_comun, head,
                                 medido_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (proyecto_id, e["ruta"], e["rama"], e["sin_push"], e["regimen"],
             e["detras"], e["sucios"], e["ultimo_commit"], e["worktrees"],
             e["repo_comun"], e["head"], ts),
        )
    return len(filas)


def deduplicar(repos: list[dict]) -> list[dict]:
    """Una entrada por REPOSITORIO, para poder sumar sin inflar.

    Se agrupa por el `.git` compartido y nada más. La versión anterior agrupaba
    por `(repo_comun, head)` y por eso volvió a inflar en cuanto los worktrees
    dejaron de estar en el mismo commit: `~/dev/app` y `~/dev/app-int` salían
    como dos entradas y sumaban 250 + 278 = 528 sobre 278 commits reales.

    Ahora es correcto y no una aproximación, porque `_sin_push` mide el
    repositorio entero —todas sus ramas y todos los HEAD de sus worktrees— y da
    el mismo número desde cualquiera de ellos. Se conserva el primero: cuál dé
    la cara es indiferente cuando todos dicen lo mismo.
    """
    vistos: set[str] = set()
    salida = []
    for r in repos:
        clave = r.get("repo_comun")
        if clave and clave in vistos:
            continue
        if clave:
            vistos.add(clave)
        salida.append(r)
    return salida
