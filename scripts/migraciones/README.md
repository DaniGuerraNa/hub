# Pasos de versión

Un archivo `X.Y.Z.sh` aquí es lo que una instalación tiene que hacer **una vez**
al pasar a la versión `X.Y.Z`, además de lo que `actualizar.sh` hace siempre.

`actualizar.sh` corre, en orden de versión, los de las versiones que cruza:
de la instalada (sin contarla) a la nueva (contándola). Una instalación anterior
al protocolo cuenta como `0.1.0`.

## Lo que ya hace `actualizar.sh` siempre, y por tanto NO va aquí

- bajar el código, `uv sync` y el doctor;
- regenerar los cuatro units de systemd y reiniciar los que estaban en marcha;
- poner al día los archivos del asistente desde su semilla;
- comprobar que el hub contesta y apuntar la versión.

## Lo que sí va aquí

Lo que no se deduce de comparar archivos: mover o renombrar algo dentro de
`HUB_HOME`, convertir un archivo de configuración a un formato nuevo, avisar de
algo que hay que hacer a mano y **parar** si no está hecho.

## El contrato

- Recibe `RAIZ` (el clon) y `HUB_HOME` en el entorno.
- **Idempotente**: si falla a medias, `actualizar.sh` no apunta la versión y el
  paso se vuelve a correr entero.
- Sale con un código distinto de 0 si no pudo: `actualizar.sh` para ahí.
- Nunca borra datos de la persona. Si algo se reemplaza, lo de antes queda al
  lado.
- Lo prueba un test que lo ejecuta contra un `HUB_HOME` temporal.

La 0.2.0, la primera con número, no necesita pasos propios: todo lo que una
instalación anterior tiene que hacer para llegar a ella es lo de siempre.
