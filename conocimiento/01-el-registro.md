# El registro — `projects.yml`

Vive en `~/.local/share/hub/projects.yml`. Es el **único archivo que editas a
mano**, y de él sale todo lo que ves. No hace falta reiniciar nada: el siguiente
ciclo lo recoge.

Si algo se rompe, se arregla con un editor de texto.

## Un proyecto

```yaml
proyectos:
  - id: tienda
    nombre: Tienda online
    dominio: personal          # personal | laboral
    asiento: ~/dev/tienda
    estado_ref: docs/ESTADO.md
    guardrail: ask             # auto | ask | never
    status: activo             # activo | pausado | archivado
    contenedores: [tienda-]
    nota: lo que haga falta recordar
```

| Campo | Qué es |
|---|---|
| `id` | La identidad. **No cambia nunca**: los slots y las notas cuelgan de él |
| `nombre` | La etiqueta que se pinta. Cámbiala cuando quieras |
| `dominio` | Un atributo con filtro, no un muro |
| `asiento` | Desde dónde trabajas |
| `rutas` | Repos y otras ubicaciones (ver abajo) |
| `estado_ref` | Puntero al documento que dice cómo va el proyecto |
| `guardrail` | Permiso del asistente para ejecutar cosas ahí |
| `status` | `archivado` lo saca de las listas sin borrarlo |
| `contenedores` | **Prefijos** de nombres de contenedores Docker |

## Cuando el código no está en el asiento

Muy habitual: orquestas desde una carpeta y los repos están en otra. Declara
todas las rutas — **lo que no se declara, no se mide**, y un repo sin medir puede
parecer respaldado sin estarlo.

```yaml
  - id: tienda
    asiento: ~/trabajo/tienda-main
    rutas:
      - ruta: ~/dev/tienda-api
      - ruta: ~/dev/tienda-web
```

El asiento no hace falta repetirlo: ya cuenta como ruta.

## `estado_ref` — el puntero al estado

Apunta al documento que **ya tienes** y que dice en qué punto está el proyecto.
No crees uno nuevo para el hub: si tienes un `ESTADO.md`, un checkpoint o unas
notas, apunta ahí.

El hub saca de él tres cosas, buscándolas por su encabezado o en el frontmatter:

- en qué **estado** está
- qué hacer al volver — **próxima acción**
- qué está **bloqueado**

Reconoce las variantes normales («situación», «siguientes pasos», «qué espera
decisión»…). Si no encuentra nada, lo dice en vez de inventárselo.

Ejemplo de documento que el hub lee bien:

```markdown
---
estado: API en producción, falta el panel de administración.
proxima_accion: Terminar el listado de pedidos y desplegar.
bloqueado_por: Nada.
---

# Tienda — estado vigente
...
```

## Contenedores de Docker

Se atribuyen por **prefijo**, no por nombre exacto: `contenedores: [tienda-]`
cubre `tienda-db`, `tienda-redis` y `tienda-worker`.

Lo que no declara nadie sale como **sin dueño**. No se le inventa un propietario:
un contenedor sin dueño es justo el que lleva meses parado y nadie sabe si se
puede borrar.

## Conexiones

Dónde despliega cada cosa y dónde vive su credencial.

```yaml
conexiones:
  - alias: vps-pruebas
    host: 203.0.113.10
    usuario: deploy
    proposito: pruebas antes de producción
    proyectos: [tienda]
    referencia_secreto: ~/.ssh/config#vps-pruebas
```

> 🔴 **`referencia_secreto` es un PUNTERO, nunca la credencial.** El hub sólo
> comprueba si eso existe; jamás lo abre. Si escribes ahí una contraseña, quedará
> en un archivo de texto plano — para eso no es.

También puedes añadirlas desde la pantalla de Conexiones: el formulario escribe
en este mismo archivo, y sólo admite esos seis campos.

## Tipos especiales

```yaml
    tipo: kit          # es un kit, no un proyecto normal
    tipo: asistente    # es el proyecto del chat (sólo puede haber uno)
```

Sin ningún proyecto `tipo: asistente`, la pestaña del chat ni se pinta.
