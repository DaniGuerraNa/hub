"""El gestor de kits, desde la línea de comandos.

Funciona **sin la API levantada**: instalar los kits pasa antes de que el
servidor exista, y un gestor que necesita el servicio corriendo no sirve durante
la instalación, que es justo cuando hace falta.

Se invoca desde el repo del hub:

    bash scripts/kit.sh listar
    bash scripts/kit.sh instalar <id> [version]
    bash scripts/kit.sh ruta <id> [version]      ← lo que resuelve un apuntador
    bash scripts/kit.sh estado [proyecto_id]     ← deriva, desfasados, choques
    bash scripts/kit.sh arbol                    ← quién provee qué, y qué falta
    bash scripts/kit.sh verificar <ruta|id>
    bash scripts/kit.sh aplicar <id> <proyecto>  ← el plan y el encargo
    bash scripts/kit.sh quitar <id> <proyecto>   ← qué quedaría suelto

🔴 `aplicar` y `quitar` **no escriben nada**: imprimen. El hub calcula y
propone; escribir dentro del repo de otro proyecto lo hace un agente que corre
allí, con el usuario mirando el diff.

🔴 Este texto es lo que ve quien teclea el comando sin argumentos, así que tiene
que enseñar la forma que FUNCIONA. Anunciaba `hub kit …`, que no existe como
subcomando de nada, y `python -m hub.kits_cli`, que falla fuera del entorno del
proyecto. El envoltorio `scripts/kit.sh` es lo único que resuelve el `uv run`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import config, kits, registry


def _kits_conocidos() -> list[kits.Kit]:
    """Los kits instalados **y los que se están escribiendo**.

    🔴 Antes sólo miraba los instalados, y `arbol` mentía en las dos
    direcciones: decía «nadie provee `notificar#enviar-mensaje`» cuando el kit
    que la provee estaba abierto en el registro, y **callaba** que ese mismo kit
    pedía una capacidad obligatoria sin proveedor — saliendo además con código
    0. Justo mientras escribes un kit, que es cuando más falta hace.

    El arreglo ya se había hecho en `estado` y no se replicó aquí: es el defecto
    que un test del CLI habría cazado, y el CLI no tenía ninguno.

    Un manifiesto roto tampoco desaparece en silencio: se dice y se sigue, o sus
    capacidades expuestas se esfuman y provocan falsos «sin proveedor» en los
    demás.
    """
    leidos: list[kits.Kit] = []
    vistos: set[str] = set()
    for id_kit, versiones in kits.instalados().items():
        ruta = kits.ruta_de(id_kit, versiones[-1])
        try:
            leidos.append(kits.leer_manifiesto(ruta))
            vistos.add(id_kit)
        except kits.KitInvalido as exc:
            print(f"  ⚠️ {id_kit} {versiones[-1]}: manifiesto inválido ({exc})",
                  file=sys.stderr)

    try:
        proyectos = registry.cargar()
    except Exception:  # noqa: BLE001 — un registro roto no ciega al árbol entero
        proyectos = []
    for p in proyectos:
        if getattr(p, "tipo", None) != "kit" or p.id in vistos:
            continue
        raiz = kits.resolver_en_desarrollo(p.id, proyectos)
        if not raiz:
            continue
        try:
            leidos.append(kits.leer_manifiesto(raiz))
            vistos.add(p.id)
        except kits.KitInvalido as exc:
            print(f"  ⚠️ {p.id} (en desarrollo): manifiesto inválido ({exc})",
                  file=sys.stderr)
    return leidos


def listar() -> int:
    catalogo = kits.catalogo()
    puestos = kits.instalados()
    if not catalogo:
        print("El catálogo está vacío. Declara kits en kits.yml o en"
              f" {config.HUB_HOME}/kits.yml")
        return 0
    print(f"{'ID':<20} {'CATÁLOGO':<10} {'INSTALADO':<22} ORIGEN")
    for id_kit, datos in sorted(catalogo.items()):
        versiones = puestos.get(id_kit, [])
        estado = ", ".join(versiones) if versiones else "—"
        origen = datos.get("origen", "?")
        marca = " *" if datos.get("obligatorio") else ""
        print(f"{id_kit + marca:<20} {datos.get('version', '?'):<10} {estado:<22} {origen}")
    if any(d.get("obligatorio") for d in catalogo.values()):
        print("\n* obligatorio: lo lleva todo proyecto.")
    return 0


def instalar(id_kit: str, version: str | None) -> int:
    datos = kits.catalogo().get(id_kit)
    if not datos:
        print(f"«{id_kit}» no está en el catálogo. `listar` enseña los que hay.",
              file=sys.stderr)
        return 1
    del_catalogo = str(datos.get("version") or "")
    version = version or del_catalogo
    origen = str(datos.get("origen") or "")
    if origen == "interno":
        # 🔴 La versión SE COMPRUEBA aunque el kit venga con el hub. Antes no:
        # `instalar base 99.9` —y `ruta base pepino`— devolvían la ruta de la
        # única versión que existe, con éxito y sin decir nada. Un consumidor
        # que declarase `base: 99.9` mediría su deriva contra la 1.0 creyendo
        # estar en otra, que es exactamente lo que el propio `kits.yml` promete
        # que no pasa: «si un tag se reescribiera, todo lo que midió deriva
        # contra él pasaría a mentir sin avisar».
        if version != del_catalogo:
            print(
                f"{id_kit} {version} no existe: el hub trae la {del_catalogo}.",
                file=sys.stderr,
            )
            return 1
        # La base la trae el hub consigo: no hay nada que descargar.
        print(f"{id_kit} {version} viene con el hub: {config.RAIZ_REPO / 'semillas' / id_kit}")
        return 0
    # 🔴 Un kit EN DESARROLLO no se instala, y decirlo es el arreglo.
    #
    # `instalar` clona el tag `v<version>` del origen. Un kit que aún se está
    # escribiendo no lo ha publicado —de los cuatro del catálogo, sólo uno tiene
    # tag—, así que el comando moría con un `fatal: Remote branch v0.1 not found
    # in upstream origin` de git en crudo. Ese mensaje no dice qué hacer, y lo
    # que hay que hacer no es publicar un tag: es NADA, porque el kit ya se
    # resuelve desde el registro y todo lo demás —`ruta`, `estado`, `aplicar`—
    # funcionaba perfectamente contra él.
    #
    # Costó una aplicación de kit a mano: quien lo intentó leyó el fatal, dio el
    # comando por roto y siguió por su cuenta. Un paso del procedimiento que
    # falla con un error de otra herramienta se lee como «esto no funciona».
    # Primero lo ya instalado: una versión congelada que ya está en disco se
    # informa como tal, aunque el kit se esté escribiendo a la vez. Las dos
    # cosas conviven —la copia de `1.0` y el repo donde nace la `1.1`— y
    # confundirlas haría creer que no hay nada instalado cuando sí lo hay.
    ya = kits.ruta_de(id_kit, version)
    if ya.is_dir():
        print(f"  ✓ {id_kit} {version} ya estaba instalado → {ya}")
        return 0

    try:
        proyectos = registry.cargar()
    except Exception:      # el registro puede no existir todavía
        proyectos = []
    en_desarrollo = kits.resolver_en_desarrollo(id_kit, proyectos)
    if en_desarrollo:
        # 🔴 Y la versión se COMPRUEBA, igual que con `base`. Sin esto,
        # `instalar lienzos 9.9` contestaba «en desarrollo» y salía con éxito:
        # el kit en desarrollo es UNA versión concreta —la que declara su
        # `kit.yml`—, no todas las que le pidas. Un consumidor que declarase
        # `9.9` mediría su deriva contra la 0.1 creyendo estar en otra.
        try:
            suya = kits.leer_manifiesto(en_desarrollo).version
        except Exception:
            suya = ""
        if suya and version != suya:
            print(
                f"{id_kit} {version} no existe: el kit en desarrollo va por la"
                f" {suya} ({en_desarrollo}).",
                file=sys.stderr,
            )
            return 1
        print(f"{id_kit} {version} está EN DESARROLLO: no hay nada que instalar.")
        print(f"  se resuelve desde el registro → {en_desarrollo}")
        print("  publica el tag cuando lo congeles:"
              f" git -C {en_desarrollo} tag v{version}")
        return 0

    try:
        destino = kits.instalar(id_kit, version, origen)
    except kits.KitInvalido as e:
        print(str(e), file=sys.stderr)
        # El fallo más probable con diferencia, y el que no se explica solo.
        if "not found in upstream" in str(e) or f"v{version}" in str(e):
            print(
                f"\nEl origen no tiene la etiqueta `v{version}`. O bien:\n"
                f"  · publícala:  git -C {origen} tag v{version}\n"
                f"  · o declara el kit en tu `projects.yml` con `tipo: kit`"
                " para trabajarlo en desarrollo, sin publicar nada.",
                file=sys.stderr,
            )
        return 1
    print(f"  ✓ {id_kit} {version} → {destino}")

    # Un kit puede traer su propio instalador —los que ponen herramientas en la
    # máquina en vez de archivos en un proyecto—. Se dice; no se ejecuta. Correr
    # un script de un repositorio ajeno sin permiso es lo que el hub no hace.
    try:
        kit = kits.leer_manifiesto(destino)
    except kits.KitInvalido as e:
        print(f"  ⚠️ el kit está en disco pero su manifiesto no es válido: {e}")
        return 1
    if kit.instalar:
        print("\n  Este kit trae su propio instalador. Míralo y, si te convence:")
        print(f"      bash {destino / kit.instalar}")
    for b in kit.binarios:
        if not _hay(b):
            print(f"  ⚠️ necesita `{b}` y no está en el PATH")
    return 0


def ruta(id_kit: str, version: str | None) -> int:
    """Dónde está un kit. Es lo que resuelve un apuntador."""
    if id_kit == kits.ID_BASE:
        # Misma comprobación que en `instalar`: pedir una versión que no existe
        # devolvía la ruta de la única que hay, en silencio y con éxito.
        del_catalogo = str((kits.catalogo().get(id_kit) or {}).get("version") or "")
        if version and version != del_catalogo:
            print(
                f"{id_kit} {version} no existe: el hub trae la {del_catalogo}.",
                file=sys.stderr,
            )
            return 1
        print(config.RAIZ_REPO / "semillas" / "base")
        return 0
    encontrada = kits.resolver(id_kit, version)
    if not encontrada:
        print(f"{id_kit} no está instalado. `instalar {id_kit}` lo trae.", file=sys.stderr)
        return 1
    print(encontrada)
    return 0


def estado(proyecto_id: str | None) -> int:
    # `todos` se conserva aparte: los kits en desarrollo se resuelven desde el
    # registro, y filtrando por un proyecto se perdían de vista — el kit dejaba
    # de encontrarse y salía «no instalado» sólo por haber acotado la consulta.
    todos = registry.cargar()
    proyectos = todos
    if proyecto_id:
        proyectos = [p for p in todos if p.id == proyecto_id]
        if not proyectos:
            print(f"No hay ningún proyecto «{proyecto_id}» en el registro.", file=sys.stderr)
            return 1

    hubo = False
    problemas = 0
    for p in proyectos:
        declarados = kits.kits_declarados(p.todas_las_rutas())
        if not declarados:
            continue
        hubo = True
        print(f"\n{p.nombre} ({p.id})")
        resueltos: list[kits.Kit] = []
        for d in declarados:
            en_desarrollo = False
            if d["id"] == kits.ID_BASE:
                instalado = config.RAIZ_REPO / "semillas" / "base"
            else:
                instalado = kits.resolver(d["id"], d.get("version"))
                if not instalado:
                    # El kit que se está escribiendo: se resuelve desde el
                    # registro para poder editarlo y medirlo sin publicar.
                    instalado = kits.resolver_en_desarrollo(d["id"], todos)
                    en_desarrollo = instalado is not None
            if not instalado:
                print(f"  {d['id']} {d.get('version', '?')} — 🔴 no instalado en esta máquina"
                      f" · `instalar {d['id']} {d.get('version', '')}`".rstrip())
                problemas += 1
                continue
            try:
                kit = kits.leer_manifiesto(instalado)
            except kits.KitInvalido as e:
                print(f"  {d['id']} — 🔴 manifiesto inválido: {e}")
                problemas += 1
                continue
            resueltos.append(kit)
            plan = kits.plan_de_aplicacion(p.todas_las_rutas(), kit, d)
            pendientes = len(plan["pendientes"])
            declaradas = sum(1 for a in plan["archivos"] if a["estado"] == "declarada")
            resumen = "al día" if not pendientes else f"{pendientes} archivo(s) por revisar"
            if declaradas:
                # Aparte: son decisiones con motivo, no deuda. Contarlas como
                # deriva haría que la cifra dejara de mirarse.
                resumen += f" · {declaradas} excepción(es) declarada(s)"
            fuente = "  ← en desarrollo, desde el registro" if en_desarrollo else ""
            # Hay una versión posterior a la que este consumidor declara. Es lo
            # que `mantener-kit` necesita para saber a quién visitar, y hasta
            # ahora había que averiguarlo leyendo a mano cada `kits.yml`.
            nueva = kits.version_mas_nueva(kit.id, d.get("version"))
            if nueva and not en_desarrollo:
                fuente += f"  ← DESFASADO: hay {nueva}"
                problemas += 1
            print(f"  {kit.id} {kit.version} — {resumen}{fuente}")
            if pendientes:
                problemas += 1
            for a in plan["pendientes"]:
                print(f"      {a['estado']}: {a['destino']}")
            for h in plan["huerfanos"]:
                print(f"      sobra de una versión anterior (no se borra solo): {h}")
            for b in plan["binarios_ausentes"]:
                print(f"      ⚠️ necesita `{b}` y no está en el PATH")

        # 🔴 Dos kits que escriben el mismo archivo dejan el proyecto en un
        # estado irreparable: aplicar uno rompe al otro. Se dice aquí, con los
        # dos nombres, en vez de presentarlo como dos derivas sin relación.
        for destino, quienes in kits.colisiones(resueltos).items():
            print(f"  🔴 {' y '.join(quienes)} escriben los dos en `{destino}`:")
            print("      aplicar uno deshace al otro. Decide cuál manda y "
                  "declara el otro como excepción en `.claude/hub/kits.yml`.")
            problemas += 1

    if not hubo:
        print("Ningún proyecto declara kits todavía"
              " (se declaran en su `.claude/hub/kits.yml`).")
    # Sale distinto de cero si hay algo que atender, para poder encadenarlo en
    # un script o en un hook. Salía 0 siempre, y un instrumento que no se puede
    # consultar desde otro sitio se acaba mirando sólo cuando ya duele.
    return 1 if problemas else 0


def arbol() -> int:
    """Quién provee qué, y qué se pide sin proveedor.

    El equivalente de `mvn dependency:tree`: sin esto, un kit que consume algo
    que nadie da se queda callado, y eso es un instrumento en verde que nadie ha
    visto funcionar.
    """
    conocidos = _kits_conocidos()
    if not conocidos:
        print("No hay kits instalados ni en desarrollo.")
        return 0
    r = kits.resolver_capacidades(conocidos)

    print("Capacidades disponibles")
    for cid, quienes in sorted(r["proveedores"].items()):
        print(f"  {cid:<34} ← {', '.join(quienes)}")
        if len(quienes) > 1:
            print("      ⚠️ dos kits proveen lo mismo: elige tú cuál manda")

    if r["degradados"]:
        print("\nOpcionales sin proveedor — esas partes no existen hoy")
        for d in r["degradados"]:
            print(f"  {d['kit_id']} pide {d['capacidad']}")

    if r["faltan"]:
        print("\n🔴 Obligatorias sin proveedor — el kit no puede funcionar")
        for f in r["faltan"]:
            print(f"  {f['kit_id']} pide {f['capacidad']}")
        return 1
    return 0


def _en_desarrollo(id_kit: str):
    """La raíz de un kit declarado en el registro como `tipo: kit`."""
    try:
        return kits.resolver_en_desarrollo(id_kit, registry.cargar())
    except Exception:  # noqa: BLE001 — un registro roto no ciega a `verificar`
        return None


def verificar(donde: str) -> int:
    """Valida un manifiesto. Se usa antes de publicar una versión."""
    ruta_kit = Path(donde)
    if not ruta_kit.is_dir():
        # También los que se están ESCRIBIENDO, no sólo los instalados. El
        # arreglo estaba hecho en `estado` y en `arbol` y aquí no: verificar un
        # kit por su id fallaba con «no encuentro» justo mientras lo escribes,
        # que es cuando más se verifica. Se descubrió aplicando el primero.
        resuelta = (
            config.RAIZ_REPO / "semillas" / "base"
            if donde == kits.ID_BASE
            else kits.resolver(donde) or _en_desarrollo(donde)
        )
        if not resuelta:
            print(f"No encuentro «{donde}» ni como ruta ni como kit instalado.",
                  file=sys.stderr)
            return 1
        ruta_kit = resuelta
    try:
        kit = kits.leer_manifiesto(ruta_kit)
    except kits.KitInvalido as e:
        print(f"🔴 {e}", file=sys.stderr)
        return 1

    clase = "de máquina" if kit.de_maquina else "de proyecto"
    print(f"  ✓ {kit.id} {kit.version} — manifiesto válido, kit {clase}")
    # `is_file()`: un `origen` que es una CARPETA existía y pasaba en verde, y
    # después la medición no medía nada. Se dice aquí, que es donde se mira un
    # kit antes de publicarlo.
    faltan = [a.origen for a in kit.aplica if not (ruta_kit / a.origen).is_file()]
    for f in faltan:
        que = "es una carpeta, y `aplica` propaga archivos uno a uno" \
            if (ruta_kit / f).is_dir() else "y ese archivo no está en el kit"
        print(f"  🔴 declara `{f}`: {que}")

    # Lo mismo para lo que el kit PROMETE: se comprobaba `aplica` y no `expone`,
    # así que un kit podía anunciar una capacidad cuyo script no existe y salir
    # en verde. Una capacidad sin su archivo es una promesa que nadie cumple.
    for entrada in kit.expone:
        ruta_expuesta = entrada.get("ruta") if isinstance(entrada, dict) else None
        if ruta_expuesta and not (ruta_kit / ruta_expuesta).exists():
            faltan.append(ruta_expuesta)
            print(f"  🔴 expone `{entrada.get('id')}` y su `{ruta_expuesta}` no está")

    verificar_gancho = (kit.mantenimiento or {}).get("verificar")
    if verificar_gancho and not (ruta_kit / verificar_gancho).exists():
        faltan.append(verificar_gancho)
        print(f"  🔴 `mantenimiento.verificar` apunta a `{verificar_gancho}`, que no está")

    for c in kit.capacidades_expuestas:
        print(f"  expone {c}")
    for c in kit.consume:
        marca = "opcional" if c.get("opcional") else "obligatoria"
        print(f"  consume {c['id']} ({marca})")
    for a in kit.aplica:
        print(f"  aplica {a.destino} ({a.modo})")
    if kit.instalar:
        print(f"  instalador propio: {kit.instalar}")
    for b in kit.binarios:
        print(f"  necesita {b} — {'ok' if _hay(b) else '🔴 no está en el PATH'}")
    return 1 if faltan else 0


def _hay(binario: str) -> bool:
    """`shutil.which` y no `command -v`: éste resuelve también alias y funciones
    del shell, que no existen para un subproceso. Ya mordió con `rg`."""
    import shutil

    return shutil.which(binario) is not None


def _resolver(id_kit: str, version: str | None, proyectos: list):
    """El kit, venga de donde venga: instalado, interno o en desarrollo."""
    if id_kit == kits.ID_BASE:
        return config.RAIZ_REPO / "semillas" / "base"
    return kits.resolver(id_kit, version) or kits.resolver_en_desarrollo(id_kit, proyectos)


def aplicar(id_kit: str, proyecto_id: str) -> int:
    """Imprime el plan y el encargo. **No escribe nada.**

    🔴 Esto existía y no lo llamaba nadie. `kits.prompt_aplicar` calculaba el
    plan entero —qué crear, qué actualizar, qué no tocar, qué sobra, qué
    binarios faltan— y era código muerto fuera de los tests: aplicar un kit se
    hacía a mano, unos quince pasos, con el hub sabiendo decirlos.

    Sigue sin escribir, y eso no es una limitación: escribir dentro del repo de
    otro proyecto es lo que la primera regla del hub prohíbe. Lo hace un agente
    que corre ahí, con el usuario mirando el diff.
    """
    proyectos = registry.cargar()
    p = next((x for x in proyectos if x.id == proyecto_id), None)
    if not p:
        print(f"No hay ningún proyecto «{proyecto_id}» en el registro.", file=sys.stderr)
        return 1

    declarado = next(
        (d for d in kits.kits_declarados(p.todas_las_rutas()) if d["id"] == id_kit), None
    )
    raiz = _resolver(id_kit, (declarado or {}).get("version"), proyectos)
    if not raiz:
        print(f"«{id_kit}» no está instalado. `instalar {id_kit}` lo trae.",
              file=sys.stderr)
        return 1
    try:
        kit = kits.leer_manifiesto(raiz)
    except kits.KitInvalido as e:
        print(f"🔴 {e}", file=sys.stderr)
        return 1

    plan = kits.plan_de_aplicacion(p.todas_las_rutas(), kit, declarado)
    destino = kits.raiz_de(p.todas_las_rutas())
    print(kits.prompt_aplicar(p.nombre, str(destino), kit, plan))
    print("\n" + "─" * 70)
    print("Esto es una PROPUESTA: el hub no escribe en tu proyecto. Revísala,")
    print(f"abre Claude Code en {destino} y pásasela.")
    return 0


def quitar(id_kit: str, proyecto_id: str) -> int:
    """Qué quedaría suelto si este proyecto dejara de usar el kit. No borra.

    No borra por lo mismo de siempre —el hub no escribe en repos ajenos— y
    porque la respuesta útil no es «hecho», es **la lista**: un kit deja
    archivos que igual siguen haciendo falta, y decidirlo uno a uno es del
    usuario.
    """
    proyectos = registry.cargar()
    p = next((x for x in proyectos if x.id == proyecto_id), None)
    if not p:
        print(f"No hay ningún proyecto «{proyecto_id}» en el registro.", file=sys.stderr)
        return 1

    declarado = next(
        (d for d in kits.kits_declarados(p.todas_las_rutas()) if d["id"] == id_kit), None
    )
    if not declarado:
        print(f"«{proyecto_id}» no declara el kit «{id_kit}».", file=sys.stderr)
        return 1

    raiz = _resolver(id_kit, declarado.get("version"), proyectos)
    destino = kits.raiz_de(p.todas_las_rutas())
    print(f"Si «{p.nombre}» deja de usar `{id_kit}`, esto queda suelto en {destino}:\n")

    escritos = list(declarado.get("destinos") or [])
    apuntados = []
    if raiz:
        try:
            kit = kits.leer_manifiesto(raiz)
            apuntados = [a.destino for a in kit.aplica if a.modo == "apuntador"]
            escritos = escritos or [a.destino for a in kit.aplica
                                    if a.modo != "apuntador"]
        except kits.KitInvalido:
            pass

    for d in sorted(set(escritos) - set(apuntados)):
        existe = (destino / d).exists() if destino else False
        print(f"  {'archivo' if existe else 'ya no está'}: {d}")
    if apuntados:
        print(f"\n  Y su línea en el bloque de kits del CLAUDE.md ({len(apuntados)}"
              " apuntador(es), que no son archivos).")
    print("\nEl hub NO borra nada de esto: decide tú qué sigue haciendo falta y")
    print(f"quita el kit de `{destino}/.claude/hub/kits.yml` cuando termines.")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "ayuda"):
        print(__doc__)
        return 0
    orden, *resto = argv
    if orden == "listar":
        return listar()
    if orden == "instalar" and resto:
        return instalar(resto[0], resto[1] if len(resto) > 1 else None)
    if orden == "ruta" and resto:
        return ruta(resto[0], resto[1] if len(resto) > 1 else None)
    if orden == "estado":
        return estado(resto[0] if resto else None)
    if orden == "arbol":
        return arbol()
    if orden == "verificar" and resto:
        return verificar(resto[0])
    if orden == "aplicar" and len(resto) > 1:
        return aplicar(resto[0], resto[1])
    if orden == "quitar" and len(resto) > 1:
        return quitar(resto[0], resto[1])
    print(f"No entiendo «{' '.join(argv)}».\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
