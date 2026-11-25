# Pruebas con el aparato

Para quien llega de nuevas con un JetKVM delante, y para su Claude Code. Si
el puente aún no está instalado, primero `INSTALAR.md`.

Las órdenes del puente, desde la carpeta donde trabaja Claude (que puede no ser
la del código), van así, siempre con `--frozen`:

```bash
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm comprobar --sin-entrar
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm diagnostico
```

`comprobar --sin-entrar` basta para saber si el puente está bien instalado.
Sin `--sin-entrar` entra en el JetKVM (si el puente no está en marcha) para
leer su firmware, y eso **cierra la web del JetKVM** a quien la tenga abierta
en un navegador: úsalo sólo con la web del aparato cerrada.

🔴 **La web del puente no se publica ni se reenvía** fuera de `127.0.0.1`
(ni puertos abiertos, ni túneles, ni proxies, ni para enseñársela a alguien):
dentro hay una terminal con Claude Code y el teclado del Mac.

## Qué es esto

El puente deja que Claude Code, en tu equipo, lea y escriba en un **Mac donde
no se puede instalar nada**, a través de un **JetKVM**: el JetKVM ve la salida
HDMI del Mac y teclea en él como un teclado USB. Claude lee un documento largo
(un procedimiento almacenado, por ejemplo) página a página desde capturas, lo
transcribe, y la **huella** que da la base de datos dice si la copia es exacta
byte a byte. Para escribir de vuelta, Claude propone un cambio, tú lo apruebas
en la pantalla del puente, el puente teclea sólo los tramos que cambian, y
**guardar en la base siempre lo haces tú** en el Mac.

## En qué estado está

**Medido, con el Mac simulado** (el que trae el puente, sin aparato):

- Leer: un procedimiento de 2.017 líneas, 57 páginas, transcrito por Claude
  sólo mirando las capturas, salió exacto a la primera (la huella coincidió).
  Eran capturas sin pérdida; con el vídeo del aparato hay que volver a medirlo.
- Escribir: un cambio de 4 tramos quedó exactamente como se acordó.
- Antes de escribir, el puente vuelve a recorrer el documento hasta el tramo
  más bajo y compara cada página con su captura: unos 0,21 s por página con el
  simulador (57 páginas, 12,3 s). Con el aparato será más lento: sin medir.
- El cliente del JetKVM, contra un JetKVM falso que habla su protocolo por
  WebRTC de verdad: entra, recibe vídeo H.264, teclea, hace clic y usa la rueda.
- El directo de la pantalla (C-0469), contra ese JetKVM falso: el vídeo H.264
  llega al navegador sin recomprimirlo y se pinta a 30 fotogramas por segundo
  (antes, 11 usando el Mac y 2 mirando), con el puntero a 83 ms de p50 y 97 de
  p95 (antes, 204 y 270), y el puente gasta la mitad de CPU (15 % frente a 30 %).

**Sin medir: todo lo que tiene que ver con el aparato.** El cliente sigue el
código del firmware (contrastado con 0.5.9, 0.5.10 y 0.5.11, ver
`docs/protocolo-jetkvm.md`), pero **nunca se ha conectado a un JetKVM real**.
No des nada de lo de abajo por bueno hasta haberlo visto.

## Antes de empezar: el modelo y las conversaciones

La barra de la terminal dice con qué modelo y qué versión de Claude Code
corre la conversación abierta. Por omisión, **Fable 5.2** (pide Claude Code
2.1.322 o posterior); se cambia en **Ajustes → Modelo de Claude** y vale para
la siguiente conversación. Para cada prueba larga conviene una conversación
con nombre (el nombre de la abierta → **Nueva**): así se puede volver a ella
después. Una sola abierta a la vez; cambiar devuelve el control del Mac a la
persona, y con una lectura o escritura en marcha no se puede.

## El plan, en orden

Cada paso dice qué mirar y qué apuntar. Lo medido va a `trabajo/entorno.md`
(la plantilla es `conocimiento/entorno.plantilla.md`); los pasos 4 a 8 son los
de la skill **`primera-conexion`**, que Claude sigue contigo: aquí sólo está el
orden y lo que hay que vigilar.

0. **Antes, con el simulador (10 minutos).** Con el aparato «Simulador» en
   Ajustes, pídele a Claude que lea el procedimiento de muestra. Así ves cómo
   va el control, la lectura, la huella y un cambio sin riesgo para nadie.
   Apunta: nada; es para conocer las pantallas.
1. **Conectar.** Cierra la web del JetKVM en tu navegador (admite una sola
   sesión: si la abres después, el puente queda fuera). En Ajustes: tipo
   «JetKVM» y su dirección (`http://192.168.x.x`). La contraseña la pones tú en
   el archivo de la contraseña (ver `INSTALAR.md`), nunca Claude.
   Mira: la placa de arriba («JetKVM · 1920×1080»), la bitácora («conectado a
   jetkvm, firmware …») y si sale un aviso de firmware fuera de lo contrastado.
   Apunta: firmware, resolución, cuánto tardó en verse el Mac.
2. **La pantalla.** ¿Se ve el Mac entero y nítido? Si es un portátil, la
   pantalla tiene que estar **duplicada**. Marca la región del editor en Ajustes
   (con la columna de números, sin la barra de estado). Apunta: la región.
   Prueba también **«⤢ Pantalla grande»** con el zoom al 100 %: ¿se lee la
   letra pequeña del Mac? (el vídeo del aparato llega comprimido; con el
   simulador se lee perfecta). Apunta: si se lee, y si el directo va fluido.
3. **El teclado del Mac** (antes de dejar teclear a Claude). Al ver un teclado
   USB nuevo, macOS puede abrir el **asistente de configuración del teclado**
   («pulsa la tecla a la derecha de Mayús izquierda»): si aparece, ciérralo o
   elige **ANSI**. Con ISO, `` ` `` y `~` (en «U.S.») o `< >` (en «Español -
   ISO») salen en otra tecla. Comprueba que la fuente de entrada activa es la
   que elegiste en Ajustes → Teclado (**«U.S.»** o **«Español - ISO»**; también
   se cambia junto a «Pegar texto») y que **Bloq Mayús está apagado**. Pega un
   texto con acentos («¿Qué tal? Ñandú, “canción” —ya»): si sale con símbolos
   raros, el Mac tiene otro teclado que el elegido.
   Apunta: qué apareció y qué elegiste.
4. **Tecleo de prueba** en una pestaña de script nueva y vacía (skill, paso 4).
   Apunta: la pausa entre teclas con la que no se pierde ningún carácter.
5. **Atajos** (skill, paso 5): ir al principio y al final, Av Pág (¿una página
   exacta?), ir a la línea (¿se abre un diálogo?, ¿deja el cursor en la
   columna 1?), fin de línea. Si «ir a la línea» falla con «no se abrió nada en
   la pantalla», el atajo no es ése o el diálogo es muy pequeño: apúntalo.
6. **Lectura de la pestaña de prueba** (skill, paso 6). Mira si alguna página
   sale marcada «la pantalla se movía». Apunta: líneas por página, y los
   segundos por página (salen en el informe de `diagnostico`).
   Después, en una hoja o una web larga, pídele que la recorra con
   **`recorrer_pantalla`** (la zona de las celdas, desde arriba): ¿llega al
   final y dice cuánto subió cada página? Si dice «no sé cuánto subió», el
   ruido del vídeo es más que su margen. Si dice «no casa del todo con el final
   de la anterior», la página llegó entera porque lo de arriba no salió igual
   que en la anterior (ruido, o una medida corta): no se pierde nada, sólo
   cuesta más. Apunta: páginas, segundos y cuántas llegaron enteras así.
7. **Huella** de un objeto real pequeño (skill, paso 7). Apunta: la consulta que
   funcionó y la variante que coincide.
8. **Escritura de prueba** en la pestaña de prueba: Claude propone un cambio
   pequeño sobre la lectura del paso 6, tú lo apruebas, se escribe. Mira cada
   tramo en el Mac. **No guardes.** Apunta: si quedó exacto y cuánto tardó la
   comprobación previa (bitácora: «las páginas 1–N son las leídas (x s)»). Y
   si `ver_tramo` le llegó a Claude recortado a lo que cambió o entero: con el
   ruido del vídeo puede salir entero, que no es un fallo, sólo cuesta más. Y si
   alguno llegó entero diciendo «quizá sólo el cursor»: el cursor parpadea entre
   la captura de antes de teclear y la de después, y una caja de su anchura no
   se enseña como lo que cambió; si pasa con un tramo que sí se escribió, el
   cursor no estaba en la misma columna en las dos (apúntalo).
9. Cierra la pestaña de prueba **sin guardar**. Sólo entonces, un documento
   real.
10. **Una reunión de prueba**, cuando haya una (o un vídeo con voz en el Mac).
   En el Mac: Ajustes del Sistema → Sonido → Salida → el dispositivo USB del
   JetKVM (no «JetKVM v1»). Pulsa **«● Estoy en reunión»**: la imagen se corta
   unos segundos (reconecta con el sonido) y aparece «Grabando». Si sale «No ha
   llegado sonido» mientras alguien habla, la salida del Mac no es la del
   JetKVM. Para oírla tú a la vez, en Configuración de Audio MIDI, «+» →
   «Crear dispositivo de salida múltiple» con el JetKVM y tus auriculares, y
   elígelo como salida (con él no van las teclas de volumen). Pulsa **«■ Salí
   de la reunión»** y mira en Reuniones del hub, a los pocos minutos, la
   transcripción. Apunta: si llegó sonido, si se oye bien en la transcripción,
   y si el Mac volvió a sonar por sus altavoces tras la prueba.
11. **Jiggler y despertar.** Pulsa «Jiggler: apagado»: debe pasar a «Frecuente,
   cada 30 s». Deja el Mac sin tocar un minuto: ¿se mueve el puntero (de 1 a 3
   píxeles) y no se bloquea? Después pon el Mac en reposo (menú Apple → Reposo, usando el Mac
   desde el puente) y pulsa **«Despertar el Mac»**. Apunta: si despertó, cuántos
   segundos tardó la imagen y qué dijo el aviso. Si el Mac tiene la pantalla
   bloqueada con contraseña al volver, el jiggler no la evita: sólo evita que
   se bloquee mientras está encendido.
12. **El directo: que usar el Mac vaya fluido.** Abre la pantalla del puente
   con la medida encendida, en otra pestaña: `http://127.0.0.1:8794/panel?medir=1`
   (el panel solo, sin la terminal). Encima de la imagen sale una placa: con el
   JetKVM tiene que decir **«vídeo H.264»**. Si dice «imágenes (MJPEG)»: lo del
   puente lo dicen la bitácora y `diagnostico` («Directo»); lo del navegador
   (el códec que no sabe decodificar, por ejemplo), su consola (F12), en una
   línea «Puente: la pantalla va por imágenes». Pulsa «Usar
   el Mac desde aquí» y mueve el ratón por el Mac un minuto, parando de vez en
   cuando: la placa va diciendo los fotogramas por segundo que se pintan, los
   Mbit/s, los descartes (fotogramas tirados porque el navegador no daba
   abasto) y el retraso del puntero, p50 y p95 de los últimos 50 movimientos.
   Ese retraso es aproximado: de mandar el movimiento a que cambie la pantalla
   justo donde tiene que aparecer el puntero del Mac. Compáralo con la web del
   JetKVM a ojo (ciérrala antes de volver al puente: una sola sesión).
   Apunta: lo que dice la placa (fotogramas/s, Mbit/s, descartes, p50 y p95),
   el códec que sale en la consola del navegador si vuelve a imágenes, y si se
   nota distinto de la web del JetKVM. Con el JetKVM falso, en este equipo, el
   mismo directo da 30 fotogramas/s y 83 ms de p50 (`tests/medir_directo.py`).

## Qué mandar de vuelta

- El informe de **`diagnostico`** (la orden de arriba): lleva versiones,
  firmware, estados, tiempos y los últimos errores, **sin** la contraseña, sin
  lo tecleado y sin nombres de objetos (lo entrecomillado sale como «…»).
  Léelo antes de mandarlo.
- **`trabajo/entorno.md` sin contenido del trabajo**: borra la sección
  «Leído» (lleva nombres de objetos) y cualquier nombre de servidor o de base.
- Nada de `trabajo/` más, ni capturas: llevan el código del trabajo.

## Riesgos conocidos

- **Fuente de entrada del Mac.** El puente teclea para la que dice Ajustes →
  Teclado («U.S.», «Español - ISO» o una medida); si el Mac tiene otra (la
  latinoamericana, por ejemplo), `{ } [ ] | \ ~ @` salen distintos y nadie se
  entera hasta la huella. Se mide con la skill `calibrar-teclado` (C-0481), que
  aún no se ha probado con el aparato real.
- **El asistente de teclado de macOS** al ver un teclado USB nuevo (paso 3):
  ANSI frente a ISO cambia dónde salen `` ` `` y `~`.
- **Bloq Mayús** encendido invierte mayúsculas: el puente no lo mira.
- **Una sola sesión en el aparato**: abrir su web en un navegador echa al puente
  (la bitácora lo dice: «otra sesión abrió el JetKVM»). Se vuelve con
  «Reconectar» del panel (o «Reconectar el aparato» en Ajustes), que **devuelve
  el control a la persona**. Con una reunión grabándose no deja: cortaría su sonido.
- **El Mac en reposo**: el aparato lo dice solo (`usbState` «suspended»), y el
  panel enseña «El Mac está en reposo» con «Despertar el Mac»; el aviso se va
  en cuanto vuelve la imagen. Comprobar con el aparato que el evento llega así
  (su forma está leída del código, no medida).
- **Versión del firmware**: fuera de 0.5.9–0.5.11 puede funcionar, pero nadie
  la ha leído.
- **Cosas que se mueven encima del editor** (notificaciones, el salvapantallas,
  el cursor del ratón): una página capturada moviéndose queda marcada, y el
  puente no escribe sobre una pantalla que no se queda quieta.
- **Autocompletado, cierre de paréntesis y sangría automática** del cliente de
  base de datos: si están encendidos, lo tecleado no queda igual (README,
  «Preparar el Mac»).
- **WSL2 con su red NAT** (la de por omisión): el vídeo y el teclado van por
  WebRTC hasta un aparato de la red local, sin servidor STUN, y eso desde
  detrás del NAT de WSL2 **no se ha medido**. Si no conecta o se corta, el modo
  de red espejo de WSL (`networkingMode=mirrored` en `.wslconfig` de Windows)
  lo evitaría; cambiarlo es tocar el sistema de la persona: pregúntale antes.
- **`comprobar` sin `--sin-entrar`** cierra la web del JetKVM si está abierta en
  un navegador (ver arriba).
- **Parar** (arriba a la derecha) corta en el acto lo que esté haciendo Claude.

## Al terminar las pruebas

Si el puente se desinstala: hay que quitar su servicio
(`bash scripts/servicio.sh quitar`, o parar `arrancar.sh`). **La carpeta de
trabajo, con lo leído del Mac, se queda** (y los datos del puente en
`PUENTE_HOME`) hasta que la persona la borre: nada la borra solo. Ver
`INSTALAR.md`, «Quitar».

## Cuando el cliente del JetKVM no conecta o hace algo distinto

Mira la última sección de `docs/protocolo-jetkvm.md`: dónde mirar, cómo
comparar con el código de tu versión del firmware, y cómo probar un arreglo
primero contra `tests/jetkvm_falso.py` y después contra el aparato sin teclear
en un documento real.
