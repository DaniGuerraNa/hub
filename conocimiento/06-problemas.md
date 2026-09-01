# Cuando algo no funciona

Antes de nada:

```bash
bash scripts/doctor.sh
systemctl --user status hub-web hub-snapshotter
journalctl --user -u hub-web -n 40 --no-pager
```

## La página no carga

El servicio puede no estar corriendo, o el puerto estar ocupado por otra cosa.

```bash
systemctl --user restart hub-web
ss -ltn | grep 8787
```

Si el puerto está ocupado por otro programa, instala en otro:
`HUB_PORT=8788 bash scripts/instalar.sh`.

## Cambié el código y no se aplica

**Las plantillas se recargan solas; el Python no.**

```bash
systemctl --user restart hub-web
```

## Cambié algo del navegador y sigo viendo lo viejo

No debería pasar: los estáticos se sirven con `Cache-Control: no-cache`. Si aun
así ocurre, recarga con `Ctrl+Shift+R`.

## No aparece ningún proyecto

Comprueba que tu registro existe y que es YAML válido:

```bash
cat ~/.local/share/hub/projects.yml
uv run python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path.home().joinpath('.local/share/hub/projects.yml').read_text()); print('YAML válido')"
```

El error más común es indentar mal un proyecto y dejarlo fuera de la lista
`proyectos:`.

## La pantalla de servicios está vacía

O no tienes Docker, o no está corriendo. Si tienes Docker Desktop en Windows,
tiene que estar abierto. Pulsa **Reescanear** después.

Si Docker no contesta, el hub enseña la última lectura buena y lo dice — no la
borra.

## Dice que tengo commits sin respaldo y creo que no

Compruébalo:

```bash
git -C <ruta> log --oneline HEAD --not --remotes | wc -l
```

Cuenta los commits que **no alcanza ningún remoto**, no los que van por detrás de
tu rama. Si tu rama local no existe en `origin`, todos sus commits cuentan — y es
correcto: no están en ninguna otra parte.

## La terminal se ve rara o pierde caracteres

Prueba a cambiar el tamaño de letra con `A−`/`A+`: fuerza un remedido. Si
persiste, recarga la pestaña.

## El asistente no responde

```bash
tmux ls | grep asistente
```

Desde el chat, **Terminal** abre su sesión cruda para ver qué está pasando.
Comprueba también que `claude` está en el PATH y con sesión iniciada.

## Empezar de cero sin perder el registro

La base de datos es un índice: se reconstruye escaneando.

```bash
systemctl --user stop hub-web hub-snapshotter
rm ~/.local/share/hub/hub.db*
systemctl --user start hub-web hub-snapshotter
```

⚠️ Esto **sí borra las notas de tus slots**, que es lo único que vive sólo ahí.
Cópialas antes si te importan.

## Desinstalar

```bash
bash scripts/desinstalar.sh           # servicios fuera, datos intactos
bash scripts/desinstalar.sh --datos   # además borra ~/.local/share/hub
```
