---
name: proponer-cambio
description: Lleva un cambio hecho aquí de vuelta al editor del Mac — propuesta con diff, aprobación de la persona en el puente, escritura tramo a tramo y verificación con la huella tras guardar. Úsala cuando haya que aplicar en el Mac cualquier modificación de un objeto leído.
---

# Proponer y escribir un cambio

**Acceso:** proponer es libre. **Escribir exige dos síes de la persona:** que
apruebe el cambio en el puente y que te dé el control. **Guardar o ejecutar en el
Mac nunca es tuyo.**

**Correcciones pequeñas.** Si al darte el control marcó «correcciones pequeñas»
(`estado()` lo dice en `control.correcciones`), un cambio que conserva parte del
documento y cabe en lo que queda (20 líneas y 1 500 caracteres en todo el encargo,
contando lo que quitas más lo que pones) vuelve de `proponer_cambio` ya aprobado
(`aprobado_por: "correcciones"`): escríbelo sin pedirle nada y dile qué corregiste.
- **Todas las correcciones del encargo en UN cambio.** El presupuesto es para el
  encargo entero, no por cambio.
- Si `cabe` no es null, no cabe: díselo con ese motivo y espera su aprobación,
  como siempre. **Nunca partas un cambio para que quepa**, ni lo rehagas más
  pequeño a trozos: eso es saltarse su aprobación.
- Un documento nuevo, o uno reescrito entero, nunca entra: lo aprueba ella.
- El permiso dura lo que dura ese control: si lo retoma, pulsa Parar, terminas
  tu turno o se lo dio otra vez, con o sin la casilla, lo que aún no escribiste
  vuelve a esperar su sí.
- **Sólo en la región del editor de Ajustes.** Si la lectura se hizo en otra
  zona (otra ventana), el cambio nunca entra en el permiso, aunque quepa: lo
  aprueba ella. Si la persona marcó «Trabajo delicado», no hay permiso: todo
  espera su aprobación.

**Otra ventana que la de Ajustes.** El cambio se escribe en la zona de su
lectura, pero con los **atajos del programa calibrado en Ajustes** (ir al
principio, Av Pág, «Ir a la línea», fin de línea). En otro programa pueden hacer
otra cosa: en VS Code, `Cmd+L` no es «Ir a la línea» (selecciona la línea). No
escribas allí sin avisarle antes de qué atajos se van a pulsar y de que pueden
no servir; si no casan, el puente no escribe, pero dile qué esperar. Notas y el
navegador no tienen números de línea: no entran en lectura → cambio.

Herramientas, en una sola búsqueda:
`select:mcp__puente-kvm__estado,mcp__puente-kvm__proponer_cambio,mcp__puente-kvm__estado_cambio,mcp__puente-kvm__escribir_cambio,mcp__puente-kvm__ver_tramo`.

1. **Parte de una lectura verificada** (`leer-documento`). Sin huella que
   coincida, el diff se calcula contra una copia que puede no ser la real: dilo
   y pide verificarla antes.

   **Un encargo es UN cambio con todos sus tramos**: si te piden tocar dos
   párrafos (o diez), van todos en la misma propuesta, y el puente los escribe
   de abajo arriba. Si después hace falta un segundo cambio sobre el mismo
   documento, antes **vuelve a leerlo** (skill `leer-documento`): el segundo compara
   la pantalla con las capturas de su lectura, y tras escribir el primero ya no
   casan. Puedes, porque el control sigue dado hasta que acabas el encargo.
2. **Edita la copia** `trabajo/<objeto>.sql`. Cambios mínimos: cada línea que
   cambia es un tramo que se teclea, y teclear es lento y es donde se rompe.
   Nada de reformatear lo que no cambias. Todo carácter tiene que poderse
   teclear con la fuente del Mac que dice Ajustes («U.S.», «Español - ISO» o una medida, que sólo teclea lo verificado: acentos y ñ sí; emojis y símbolos raros no; tampoco lo que pida una tecla reservada, como `≈` con Opción+X).
3. `proponer_cambio(lectura, descripcion, ruta="trabajo/<objeto>.sql")`.
   Explícale a la persona en la terminal **qué cambia y por qué**, tramo a
   tramo, y que lo tiene para revisar en el puente (le sale un aviso con
   «Revisar»).
4. **Espera** a que lo apruebe (`estado_cambio`). Si lo rechaza, pregunta qué
   ajustar. (Con el permiso de correcciones y el cambio ya aprobado, sigue.)
5. Con el cambio aprobado, pide el control y `escribir_cambio(cambio)`. Antes de
   escribir, el puente comprueba que la pantalla es la del documento leído; si
   falla, no escribe nada: cuéntale por qué y qué hacer (normalmente, volver al
   documento, o leerlo de nuevo si cambió).
   Una escritura larga puede tardar mucho: `escribir_cambio` contesta a los
   10 min con «Sigue en marcha» (Claude Code corta una herramienta a los 30) y el
   puente la acaba solo. Consulta `estado_cambio` o termina tu turno: el control
   vuelve a la persona **cuando acaba**, no antes. No toques la configuración del
   puente ni de Claude Code para alargar esperas. Dile
   que no toque el Mac hasta entonces (Parar sí la corta en el acto).
6. Revisa cada tramo con `ver_tramo`: llega sólo la franja que cambió al
   escribirlo (lo demás está igual que antes de teclear); si necesitas el
   resto, `entera=True`. Si alguno no quedó como debía, dilo con precisión
   (tramo, línea, qué se ve).
7. Pídele que lo revise en el Mac y **lo guarde o ejecute ella**, y termina tu
   turno: el control sigue contigo mientras trabajas, y vuelve a ella cuando
   acabas (no antes: no le pidas que corrija a mitad). Después, la
   huella (consulta en el puente o `consultar-catalogo`) → el puente dice si lo
   guardado es exactamente lo acordado. Hasta entonces, el cambio no está hecho.
