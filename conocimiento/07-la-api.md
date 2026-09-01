# La API de lectura

Todo lo que el hub mide se puede leer en JSON. No es una función aparte: **es la
misma costura que consume su propia interfaz**, así que lo que ves en pantalla y
lo que sale por aquí no se pueden contradecir.

Sirve para lo de siempre — un script tuyo, un `jq` rápido, un panel propio — y
para lo que originó el asistente: pegar el estado al principio de una sesión de
Claude sin tener que contarlo a mano.

## Verla entera

```
http://127.0.0.1:8787/api/docs
```

Es la documentación que FastAPI genera del código, así que **no puede quedarse
desactualizada**: si un endpoint cambia, cambia ahí. Empieza por ahí antes que
por esta lista, que es un resumen.

## Lo que más se usa

| Endpoint | Qué devuelve |
|---|---|
| `/api/contexto` | **Todo el estado en una llamada**: proyectos, respaldo, servicios, conexiones, bandeja, paneles, capacidades y kits |
| `/api/contexto?formato=md` | Lo mismo en markdown, escrito para pegarlo tal cual |
| `/api/resumen` | Lo que pinta la portada |
| `/api/proyectos` · `/api/proyecto/<id>` | El registro, ya indexado |
| `/api/respaldo` | Commits sin respaldar, repos en riesgo, y `hay_git` |
| `/api/servicios` | Contenedores, con su dueño |
| `/api/conexiones` | Datos de conexión y el estado del puntero — **nunca la credencial** |
| `/api/inventario` | Capacidades, con `medido_en` para saber de cuándo es la foto |
| `/api/kits` | Kits, su deriva y sus consumidores |
| `/api/paneles` | Los paneles de tmux del último muestreo |
| `/api/buscar?q=` | Búsqueda sobre todo lo indexado |
| `/api/sesiones` · `/api/sesion/<id>` | Sesiones de Claude Code y su contenido, ya filtrado |

```bash
curl -s localhost:8787/api/respaldo | jq .commits_sin_respaldo
curl -s "localhost:8787/api/contexto?formato=md"
```

## Lo que hay que saber antes de automatizar nada

**Las cifras son del último escaneo, no de este instante.** Medir cuesta —git y
docker son procesos externos— así que el hub guarda lo medido y lo refresca por
ciclos o cuando se lo pides. `/api/respaldo` y `/api/inventario` traen su
`medido_en`: úsalo, o acabarás tratando una foto de la semana pasada como si
fuera de ahora.

**Un cero puede significar «no he podido mirar».** Por eso `/api/respaldo` trae
`hay_git`: si es `false`, el cero no dice que no tengas trabajo sin respaldar,
dice que no se pudo comprobar. La regla vale para todo el hub.

🔴 **Escribir es otra cosa.** Los endpoints que cambian algo comprueban de dónde
viene la petición: un `POST` desde otra página web se rechaza con 403. Desde
`curl` o desde un script tuyo funcionan —no mandan cabecera `Origin`—, pero eso
es deliberado y no un descuido: quien puede ejecutar `curl` en tu máquina ya
puede ejecutar cualquier cosa. Lo que se cierra es que una web que visites
maneje tu hub por detrás.

Y por lo mismo: **no expongas el puerto a la red**. La API es de lectura, pero
`/terminal` da acceso de shell y vive en el mismo servidor.

### Los dos que crean cosas

| Endpoint | Qué hace |
|---|---|
| `POST /api/proyecto/nuevo` | `{id, nombre, ruta, dominio?, guardrail?, estado_ref?}` |
| `POST /api/kit/nuevo` | `{id, nombre, ruta, guardrail?}` — copia `semillas/kit/` |

Los dos crean una carpeta **vacía**, la acotan con permisos, dan el alta en el
registro y lanzan un agente dentro. Y los dos contestan siempre con `ok`, sin
lanzar excepciones a la cara:

- `{"ok": false, "ocupada": true}` — la ruta ya tiene contenido. No se toca nada.
- `{"ok": true, "agente": false, "aviso": "…"}` — con `guardrail: never` la cosa
  **queda creada y registrada**, pero no se lanza a nadie. 🔴 Míralo: dar por
  hecho que `ok` implica agente deja un proyecto que existe y que nadie sabe que
  existe.
- `{"ok": true, "agente": true, "session": "…", "ventana": N}` — dónde mirarlo.
