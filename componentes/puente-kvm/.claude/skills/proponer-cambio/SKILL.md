---
name: proponer-cambio
description: Lleva un cambio hecho aquí de vuelta al editor del Mac — propuesta con diff, aprobación de la persona en el puente, escritura tramo a tramo y verificación con la huella tras guardar. Úsala cuando haya que aplicar en el Mac cualquier modificación de un objeto leído.
---

# Proponer y escribir un cambio

**Acceso:** proponer es libre. **Escribir exige dos síes de la persona:** que
apruebe el cambio en el puente y que te dé el control. **Guardar o ejecutar en el
Mac nunca es tuyo.**

1. **Parte de una lectura verificada** (`leer-documento`). Sin huella que
   coincida, el diff se calcula contra una copia que puede no ser la real: dilo
   y pide verificarla antes.
2. **Edita la copia** `trabajo/<objeto>.sql`. Cambios mínimos: cada línea que
   cambia es un tramo que se teclea, y teclear es lento y es donde se rompe.
   Nada de reformatear lo que no cambias. Todo carácter tiene que poderse
   teclear con la fuente del Mac que dice Ajustes («U.S.» o «Español - ISO»: acentos y ñ sí; emojis y símbolos raros no).
3. `proponer_cambio(lectura, descripcion, ruta="trabajo/<objeto>.sql")`.
   Explícale a la persona en la terminal **qué cambia y por qué**, tramo a
   tramo, y que lo tiene para revisar en el puente (le sale un aviso con
   «Revisar»).
4. **Espera** a que lo apruebe (`estado_cambio`). Si lo rechaza, pregunta qué
   ajustar.
5. Con el cambio aprobado, pide el control y `escribir_cambio(cambio)`. Antes de
   escribir, el puente comprueba que la pantalla es la del documento leído; si
   falla, no escribe nada: cuéntale por qué y qué hacer (normalmente, volver al
   documento, o leerlo de nuevo si cambió).
6. Revisa cada tramo con `ver_tramo`. Si alguno no quedó como debía, dilo con
   precisión (tramo, línea, qué se ve).
7. Pídele que lo revise en el Mac y **lo guarde o ejecute ella**. Después, la
   huella (consulta en el puente o `consultar-catalogo`) → el puente dice si lo
   guardado es exactamente lo acordado. Hasta entonces, el cambio no está hecho.
