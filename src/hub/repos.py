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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturoAgotado
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

# Cuántos repos se miden a la vez. Medido el 2026-09-07 sobre los 66 del
# workspace laboral, que viven en `/mnt/c`: 61 s de uno en uno, 20 s con 4
# hilos, 14,5 s con 8 y 12,6 s con 16. El codo está en 8 — pasar a 16 gana un
# 13 % y duplica los subprocesos simultáneos contra un montaje 9p, que es justo
# lo que `TIEMPO_LIMITE` existe para contener. Cada repo son ~11 llamadas a git
# que se pasan la vida esperando al disco, así que el GIL no estorba.
HILOS_DE_ESCANEO = 8


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


def _sucios(ruta: str) -> int:
    """Archivos con trabajo de verdad sin guardar. **No** los que sólo cambiaron
    de fin de línea.

    `git status --porcelain` a secas daba 3006 archivos en el workspace laboral
    y los de verdad son 79: 44 de sus 66 repos no tenían absolutamente nada
    aparte del retorno de carro. Es lo normal en un árbol clonado desde Windows
    y leído desde WSL, o sea en casi todo lo que este hub vigila —vive bajo
    `/mnt/c`—, así que no es una rareza del trabajo sino el caso general.

    Un 38× de inflación es justo lo que la regla dura 13 prohíbe: la pantalla
    diría «66 repos con cambios sin commitear» siempre, todos los días, y se
    aprendería a ignorarla. Entonces el día que uno de esos avisos sea real
    tampoco se mirará.

    `--numstat` con `--ignore-cr-at-eol` **omite** el archivo cuyo diff se queda
    vacío al ignorar el CR; se filtra igual por `0 0` por si otra versión de git
    prefiere listarlo. Un borrado da `0 n` y una modificación binaria `- -`:
    los dos son cambios reales y los dos cuentan.
    """
    numstat = _git(ruta, "diff", "--ignore-cr-at-eol", "--numstat", "HEAD") or ""
    con_contenido = 0
    for linea in numstat.splitlines():
        partes = linea.split("\t")
        if len(partes) == 3 and (partes[0], partes[1]) != ("0", "0"):
            con_contenido += 1
    # Los no seguidos no salen en ningún `diff`, y son la mitad de lo que de
    # verdad se pierde si el disco muere: un archivo nuevo sin añadir.
    #
    # `ls-files --others` y no `status --porcelain`: da lo mismo y cuesta 0,06 s
    # en vez de 1,52 s en un repo de `/mnt/c` —`status` compara el contenido de
    # todo lo seguido, que aquí ya lo hace el `diff` de arriba—. Y cuenta los
    # archivos uno a uno donde `status` colapsa una carpeta entera sin seguir en
    # una sola línea: si el disco muere se pierden los cinco, no «uno».
    sin_seguir = _git(ruta, "ls-files", "--others", "--exclude-standard") or ""
    return con_contenido + len([x for x in sin_seguir.splitlines() if x.strip()])


def estado_de(ruta: str) -> dict | None:
    """Fotografía de respaldo de un repo. None si la ruta no es un repo git."""
    if not Path(ruta).is_dir() or not es_repo(ruta):
        return None

    rama = _git(ruta, "symbolic-ref", "--short", "HEAD")  # None si está en detached
    sin_push, regimen = _sin_push(ruta)
    detras = _git(ruta, "rev-list", "--count", "HEAD..@{u}")

    return {
        "ruta": ruta,
        "rama": rama or "(detached)",
        "sin_push": sin_push,
        "regimen": regimen,
        "detras": int(detras) if detras is not None else None,
        "sucios": _sucios(ruta),
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
    pares = [(p.id, ruta) for p in proyectos for ruta in p.todas_las_rutas()]
    filas = []
    agotado = False

    # En paralelo porque de uno en uno ya no cabe en el presupuesto (decisión
    # 170): los 66 repos del workspace laboral tardan 61 s ellos solos, y con el
    # recorrido secuencial se agotaba a los 45 s dejando fuera no sólo los diez
    # últimos suyos, sino TODOS los proyectos que vienen después en el YAML.
    ejecutor = ThreadPoolExecutor(max_workers=HILOS_DE_ESCANEO)
    try:
        lanzados = [(pid, ejecutor.submit(estado_de, ruta)) for pid, ruta in pares]
        restantes: list[tuple[str, object]] = []
        for indice, (pid, futuro) in enumerate(lanzados):
            try:
                estado = futuro.result(timeout=max(0.0, limite - time.monotonic()))
            except FuturoAgotado:
                agotado = True
                restantes = lanzados[indice + 1:]
                break
            except Exception:
                continue  # un repo roto no puede tumbar la medición de los demás
            if estado:
                filas.append((pid, medido_en, estado))

        # Al agotarse el presupuesto se recoge lo que los otros hilos YA tenían
        # terminado. Descartarlo volvería la truncadura dependiente del orden de
        # `projects.yml` —los mismos proyectos del final sin medir en cada
        # ciclo, siempre— y esa es la peor forma de estar incompleto: no es que
        # falten datos, es que faltan siempre los mismos y nadie lo nota.
        for pid, futuro in restantes:
            if not futuro.done():
                continue
            try:
                estado = futuro.result(timeout=0)
            except Exception:
                continue
            if estado:
                filas.append((pid, medido_en, estado))
    finally:
        # 🔴 `wait=False`: agotado el presupuesto NO se espera a los hilos que
        # siguen corriendo. Esperarlos aquí devolvería el escaneo eterno que el
        # presupuesto existe para evitar —un `/mnt/c` colgado son 10 s por cada
        # una de las ~11 llamadas de git—, y el snapshotter se quedaría sin
        # muestrear justo el día que el sistema va peor (regla dura 14).
        ejecutor.shutdown(wait=False, cancel_futures=True)

    if agotado:
        # En voz alta: un escaneo truncado en silencio se lee como «no hay nada
        # sin respaldar», que es la mentira más cara que este módulo puede decir.
        print(
            f"[repos] escaneo truncado a los {PRESUPUESTO_SEGUNDOS}s: "
            f"{len(filas)} de {len(pares)} rutas medidas. La cifra de respaldo "
            "está incompleta.",
            flush=True,
        )

    # 🔴 Había rutas que mirar y no salió NINGUNA medida: git está pero no
    # funciona aquí. Es indistinguible de «no tienes repos» mirando el
    # resultado, y la diferencia es justo lo que este módulo no puede
    # equivocarse. No se borra nada y se dice.
    candidatas = [ruta for _, ruta in pares]
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
