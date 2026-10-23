# navegador-lab

Que Claude maneje un navegador de verdad —con tu sesión de AWS iniciada en un
perfil propio— para leer, recorrer y documentar, **dentro de lo que tú
permitas**, y que aprenda un flujo viéndote hacerlo una vez.

Quien tenga el repo propio, con su carpeta `investigacion/` (no viaja con el hub),
que empiece por `investigacion/00-resumen.md`: qué se eligió, qué está medido y
qué límites tiene.

## Las piezas

```
            tú ─── hub /navegante · nav aprobar ───┐
                                                    ▼
Claude ── agent-browser / nav flujo ──► Chrome (perfil propio, CDP) ──► consola
                                           ▲
                         guardián ─────────┘  pausa o corta cada petición que
                         (política YAML)      modifica; registro de todo
```

- `consola_falsa/` — consola de AWS de mentira (API Gateway, Logs Insights,
  inicio de sesión, botones que modifican y registran el intento).
- `navegador/guardian.py` — el guardián. `politica.py` decide; `aprobaciones.py`
  es la cola de preguntas (un archivo por pregunta).
- `navegador/flujo.py` — grabación → flujo YAML. `reproducir.py` lo repite.
- `navegador/cli.py` → `bin/nav`.
- `flujos/` — `apigateway-mapa.yml` y `logs-insights-consulta.yml`.
- `politicas/` — `consola-falsa.yml` y `aws-lectura.yml` (sin probar contra AWS).
- `.claude/skills/navegador/` — cómo lo usa Claude.

## Arrancar de cero

```bash
cd ~/projects/navegador-lab
uv sync                                   # Python: guardián, reproductor, consola falsa
npm install                               # agent-browser y @playwright/cli (package.json)
npx playwright install chromium           # si no hay Chrome en el PATH (o pon NAV_CHROME)
ln -s ~/projects/navegador-lab/bin/nav ~/.local/bin/nav   # opcional: `nav` desde cualquier sitio
uv run uvicorn consola_falsa.app:app --port 8790          # la consola falsa, para probar
nav navegador --visible                   # Chrome con perfil propio y CDP en 127.0.0.1:9222
nav guardian --fondo                      # sin guardián, nada frena un borrado
nav panel                                 # vista en vivo en http://localhost:4848
```

`nav navegador` crea el perfil en `$NAV_DATOS/perfil` con permisos `0700`:
ahí quedan las cookies de las sesiones que abras. Ciérralo con `nav cerrar`
(las cookies se escriben al cerrar; matarlo las pierde).

### Variables

| Variable | Por omisión | Para qué |
|---|---|---|
| `NAV_DATOS` | `~/.local/share/navegador-lab` | Todo lo que no va a git (abajo) |
| `NAV_CDP` | `http://127.0.0.1:9222` | El Chrome al que se engancha el guardián y los flujos |
| `NAV_PERFIL` | `$NAV_DATOS/perfil` | El perfil de Chrome (cookies) |
| `NAV_CHROME` | `google-chrome`, `chromium` o el Chromium de Playwright | Qué Chrome abrir |
| `NAV_FLUJOS` | — | Una colección de flujos extra, delante de las demás |
| `NAV_PANTALLA` | `:99` | Pantalla virtual (Xvfb) donde se pinta el Chrome con ventana. Sin Xvfb instalado, cae a headless, que algunos sitios bloquean (403) |
| `HUB_HOME` | `~/.local/share/hub` | Dónde deja el guardián el timbre para el hub |

### Lo que vive fuera de git (`$NAV_DATOS`)

`perfil/` (🔴 cookies de tus sesiones, incluida AWS), `config.yml` (accesos
directos), `aprobaciones/` (las preguntas del guardián y sus respuestas),
`registro.jsonl` (todo lo que vio el guardián), `salidas/` (corridas y
capturas), `vigilancia/` (qué guardián vigila qué Chrome), `flujos/` (la
colección **trabajo**) y `politicas/` (las privadas, como `trabajo-aws`).
**Nada de esto se respalda**: si se pierde la máquina, los flujos y políticas
del trabajo se pierden con ella.

### `nav flujo --sin-guardian`

Corre un flujo aunque ningún guardián vigile ese Chrome (lo usan los tests).
Es sólo para el dueño y contra la consola falsa; a Claude se lo deniega
`.claude/settings.json`, igual que arrancar o parar el guardián y aprobar.

## Usarlo: la pantalla Navegante del hub

Todo se maneja desde **Navegante** en el hub (rama `navegador`; mientras no se
fusione, se sirve aparte: `cd ~/projects/hub-navegador && uv run uvicorn hub.web:app --port 8788`
→ <http://localhost:8788/navegante>). Así, sin `HUB_HOME` propio, **comparte los
datos del hub real** (slots, notas, timbres): es a propósito para probar con lo
de verdad, pero lo que se haga ahí se hace en el hub de siempre.

1. **Encender** el navegador → **Vigilar** con una política → **Preparar vista**
   y **Abrir ↗**: ahí lo ves y lo manejas tú (iniciar sesión, grabar).
2. **Enseñarle un flujo**: «Empezar a grabar», lo haces en la vista en vivo,
   y «Parar y guardar» con nombre, pantallas (dónde empieza y acaba) y
   parámetros (`clave=valor`, lo que cambia la próxima vez).
3. **Componer**: une fragmentos en orden. El **mapa** enseña qué sale de cada pantalla.
4. **Flujos → Correr** con sus parámetros; el resultado sale en **Corridas**
   como tablas. Si falla, enseña el paso, el error y lo que se veía.
5. Lo que el guardián pausa aparece arriba, en **Te pregunta**.

Con Claude: abre `claude` en `~/projects/navegador-lab` (la skill `navegador`
sabe todo esto) y pídele cosas mientras miras la vista en vivo.

Lo mismo por terminal: `bin/nav --help` (y `ln -s ~/projects/navegador-lab/bin/nav ~/.local/bin/nav`).

## Lo del trabajo

- Flujos laborales → colección **trabajo** (`~/.local/share/navegador-lab/flujos`, fuera de git).
- Política **trabajo-aws** (`~/.local/share/navegador-lab/politicas/`), en modo
  preguntar. Lee su cabecera: cómo afinarla en la primera sesión.
- Pon el portal de AWS como **acceso directo** (Navegante → Accesos directos).

## Los tests

```bash
uv run pytest -q          # 22 tests, ~40 s, Chromium real contra consola_falsa
```

## Contra AWS de verdad (cuando lo decidas)

1. Un permission set de lectura en IAM Identity Center (03 §3.1 propone
   `ViewOnlyAccess` + `CloudWatchLogsReadOnlyAccess` acotado, sesión de 1 h).
2. `bin/nav navegador --visible https://<tu-portal>.awsapps.com/start` e inicias
   sesión tú, con ese rol.
3. Vigilar con la política `trabajo-aws` (privada, en modo preguntar).
4. La primera vez, mira `bin/nav registro 50` para ajustar `permitir` y
   `silenciar`: la lista de esa política es una suposición sin medir.
