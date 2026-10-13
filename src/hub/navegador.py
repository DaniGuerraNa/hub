"""Ver qué hay en el disco. Sólo nombres y rutas, y sólo donde el hub ya mira.

Existe por un caso concreto: estando fuera, alguien pregunta «¿tienes el repo
tal?» y la respuesta está en una máquina que no se tiene delante. Recorrer
carpetas en un móvil es malo, así que lo que este módulo sirve es **inventario**
—qué hay y dónde—, no un gestor de archivos.

🔴 **Tres cosas que este módulo NO hace, y ninguna es una versión corta.**

1. **No sirve contenido.** Ni `cat`, ni previsualización, ni descargas. Decisión
   suya del 2026-09-14, y la garantía es estructural y no un filtro: una lista de
   patrones que prometa esconder `.env` es una red, no una promesa —lo mismo que
   `CLAUDE.md` dice del filtro del canal (regla 22)—. Aquí no hace falta ninguna
   red, porque no hay ninguna función que lea un archivo.
2. **No escribe.** Ni renombra, ni borra, ni sube. La regla fundacional del
   proyecto es que el hub indexa y nunca toca dentro de proyectos ajenos, y la
   regla 16 se lo prohíbe al asistente: sería absurdo que la web pudiera sobre
   sus repos lo que el asistente tiene vetado.
3. **No ejecuta.** Ni abre ventanas, ni lanza nada. Es lo que mantiene esto
   **fuera** del interruptor de terminal (decisión 163): el navegador se puede
   usar con la terminal remota apagada, que es el 95 % de las veces.

🔴 **Y la que sí es de seguridad: el orden de `resolver()`.**

Un navegador es un endpoint que recibe una ruta, o sea que sin confinamiento es
`?ruta=/etc/shadow`. Con Tailscale eso deja de ser teórico: el argumento de
`web.py` —«quien puede hacer curl aquí ya puede hacer bash»— se cae en cuanto
entra un móvil, porque **el móvil no es la máquina** (decisión 160).

Se resuelve PRIMERO y se comprueba DESPUÉS, nunca al revés, y las raíces se
resuelven también. Al revés se salta de dos maneras distintas:

- con `..` en la ruta, que sólo desaparece al resolver;
- con un **symlink** dentro de un repo apuntando fuera, que ni siquiera contiene
  `..`. No es hipotético en árboles clonados desde Windows.

Es la misma forma que la regla 9 (todo destino de tmux se valida antes de llegar
a la línea de comandos) y la 10 (`shlex.quote`): la comprobación va pegada al
borde, no repartida por quien llama.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

# Un directorio con `node_modules` dentro tiene decenas de miles de entradas y
# ninguna de ellas es lo que se venía a buscar. Se corta y se DICE cuántas
# quedaron: una lista truncada en silencio se lee como «no está» (regla 13).
TOPE = 500


class FueraDeRaiz(ValueError):
    """La ruta no cae bajo ninguna raíz que el hub indexe. No se sirve nada."""


class NoNavegable(ValueError):
    """Existe y está dentro, pero no se puede listar (no es carpeta, o no hay permiso)."""


def normalizar(ruta: str | Path) -> Path:
    """`~`, `..` y symlinks fuera, en una sola operación.

    `resolve()` no exige que exista (`strict=False` es el defecto): resuelve lo
    que puede y deja el resto. Nos vale, porque después se comprueba la
    existencia por separado y con un mensaje propio.
    """
    return Path(ruta).expanduser().resolve()


def raices(rutas: Iterable[str]) -> list[Path]:
    """Las raíces, resueltas y sin repetidas.

    🔴 Resolverlas también, y no sólo el candidato, es la mitad que se olvida: si
    una raíz es un symlink —`~/dev` apuntando a otro disco—, comparar un destino
    ya resuelto contra una raíz sin resolver **niega el acceso legítimo**, y el
    síntoma sería «el hub no ve mis repos» sin ninguna pista de por qué.
    """
    vistas: dict[Path, None] = {}
    for ruta in rutas:
        if ruta:
            vistas.setdefault(normalizar(ruta), None)
    return list(vistas)


def dentro(destino: Path, confin: Sequence[Path]) -> bool:
    """Si un destino YA RESUELTO cae bajo alguna raíz ya resuelta."""
    return any(destino.is_relative_to(raiz) for raiz in confin)


def resolver(ruta: str, confin: Sequence[Path]) -> Path:
    """La ruta pedida, resuelta y confinada. `FueraDeRaiz` si se sale.

    🔴 Este es el único sitio por el que una ruta de fuera llega al disco. Todo
    lo demás de este módulo recibe un `Path` que ya pasó por aquí.
    """
    destino = normalizar(ruta)
    if not dentro(destino, confin):
        raise FueraDeRaiz(
            f"«{ruta}» no está bajo ninguna ruta que el hub indexe. "
            "El navegador sólo enseña lo que hay en `projects.yml`."
        )
    return destino


def _es_repo(carpeta: Path) -> bool:
    """`.git` puede ser directorio o, en un worktree, un archivo que apunta."""
    return (carpeta / ".git").exists()


def _raiz_de(destino: Path, confin: Sequence[Path]) -> Path | None:
    """La raíz más específica que lo contiene.

    La más larga, igual que `registry.Atribuidor`: un repo declarado dentro de un
    asiento pertenece al repo, no al asiento. Usar otro criterio aquí haría que
    las migas subieran a un sitio distinto del que dice el resto del hub.
    """
    candidatas = [r for r in confin if destino.is_relative_to(r)]
    return max(candidatas, key=lambda r: len(str(r))) if candidatas else None


def migas(destino: Path, confin: Sequence[Path]) -> list[dict]:
    """El camino desde su raíz hasta aquí, cada tramo navegable.

    Se corta en la raíz a propósito: más arriba no hay nada que el hub pueda
    servir, y una miga que lleva a un error es peor que no tenerla.
    """
    raiz = _raiz_de(destino, confin)
    if raiz is None:
        return []
    tramos = [{"nombre": raiz.name or str(raiz), "ruta": str(raiz)}]
    acumulado = raiz
    for parte in destino.relative_to(raiz).parts:
        acumulado = acumulado / parte
        tramos.append({"nombre": parte, "ruta": str(acumulado)})
    return tramos


def arriba(destino: Path, confin: Sequence[Path]) -> str | None:
    """El padre, si sigue confinado. `None` en la raíz: ahí no se sube."""
    padre = destino.parent
    if padre == destino or not dentro(padre, confin):
        return None
    return str(padre)


def _entrada(hijo: Path, confin: Sequence[Path]) -> dict:
    carpeta = hijo.is_dir()
    dato = {
        "nombre": hijo.name,
        "ruta": str(hijo),
        "carpeta": carpeta,
        "repo": carpeta and _es_repo(hijo),
        "tamano": None,
        # Un symlink que apunta fuera del confín se ENSEÑA —está ahí, y ocultarlo
        # sería mentir sobre el contenido de la carpeta— pero se marca, para que
        # la interfaz no ofrezca un enlace que `resolver` va a rechazar.
        "fuera": hijo.is_symlink() and not dentro(normalizar(hijo), confin),
    }
    if not carpeta:
        try:
            dato["tamano"] = hijo.stat().st_size
        except OSError:
            pass  # Un symlink roto no tiene tamaño; el resto de la fila sí vale.
    return dato


def listar(ruta: str, confin: Sequence[Path]) -> dict:
    """Qué hay en esa carpeta. Nombres, no contenido."""
    destino = resolver(ruta, confin)
    if not destino.exists():
        raise NoNavegable(f"«{ruta}» ya no existe.")
    if not destino.is_dir():
        raise NoNavegable(
            f"«{destino.name}» es un archivo. El navegador enseña dónde está, "
            "no lo que dice."
        )
    try:
        hijos = list(destino.iterdir())
    except OSError as exc:
        raise NoNavegable(f"no se pudo leer «{destino}»: {exc}") from exc

    # Los ocultos no se listan —en un árbol de repos son ruido— pero se CUENTAN.
    # Esconderlos sin decirlo hace que una carpeta con sólo dotfiles parezca
    # vacía, y entonces el navegador miente en vez de simplificar.
    ocultos = sum(1 for h in hijos if h.name.startswith("."))
    visibles = sorted(
        (h for h in hijos if not h.name.startswith(".")),
        # Carpetas primero y sin distinguir mayúsculas: es el orden con el que se
        # busca con el pulgar, no el de `ls`.
        key=lambda h: (not h.is_dir(), h.name.lower()),
    )
    return {
        "ruta": str(destino),
        "migas": migas(destino, confin),
        "arriba": arriba(destino, confin),
        "entradas": [_entrada(h, confin) for h in visibles[:TOPE]],
        "ocultos": ocultos,
        "truncado": max(0, len(visibles) - TOPE),
    }


def minimas(confin: Sequence[Path]) -> list[Path]:
    """Las raíces que no cuelgan de otra raíz. Son los sitios por donde empezar.

    Sin esto, la pantalla de inicio del navegador tendría 68 entradas sólo del
    workspace del trabajo —su asiento y los 67 repos de dentro, todos declarados
    en `projects.yml`— y las de los demás proyectos se perderían entre ellas. Los
    repos no desaparecen: están un clic más abajo, que es donde viven de verdad.

    No es lo mismo que quedarse con los asientos: los repos de un proyecto pueden
    vivir fuera de su asiento —`~/dev/algo` con el asiento en `/mnt/c/...`— y ésos
    sí tienen que salir arriba, porque no hay ninguna raíz desde la que llegar.
    """
    return [r for r in confin if not any(r != otra and r.is_relative_to(otra) for otra in confin)]


def tamano(bytes_: int | None) -> str:
    """El tamaño de un archivo en la escala en que se lee de un vistazo.

    Se enseña porque es metadato, no contenido: saber que un log ocupa 2 GB
    cambia lo que vas a hacer con él, y para eso no hace falta abrirlo. Va en
    múltiplos de 1024 —que es lo que cuenta `stat`— y con coma decimal, como el
    resto de las cifras del hub.
    """
    if bytes_ is None:
        return ""
    if bytes_ < 1024:
        return f"{bytes_} B"
    valor = float(bytes_)
    for sufijo in ("kB", "MB", "GB", "TB"):
        valor /= 1024
        if valor < 1024:
            texto = f"{valor:.1f}" if valor < 100 else f"{valor:.0f}"
            return texto.replace(".", ",") + " " + sufijo
    return f"{valor:.0f} PB"
