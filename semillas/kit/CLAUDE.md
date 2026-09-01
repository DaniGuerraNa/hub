# CLAUDE.md — kit @ID@

Guía para trabajar **dentro de este kit**. Lo que hace y para quién es está en
`README.md`; el contrato, en `kit.yml`.

## Qué es un kit

Una capa que aporta una capacidad a un proyecto al aplicarse. No es una librería
de código: es contenido —método, skills, agentes, herramientas— que acaba dentro
del repo de otra persona.

De ahí sale la regla que gobierna todo lo demás:

> **Este kit no puede exigir el hub para que su contenido funcione; sólo para
> organizarlo.** Sus documentos se leen y sus scripts corren a mano.

## Al añadir algo

1. **Declara el destino en `kit.yml`.** Lo que no está en `aplica:` no llega a
   ningún consumidor, y no fallará: simplemente no estará.
2. **Elige el modo con criterio**, no por costumbre:
   - se **apunta** lo que se lee y nadie edita;
   - se **materializa** lo que otro programa busca en una ruta fija (skills,
     agentes, hooks: Claude Code no sigue apuntadores);
   - se **copia** lo que se edita — y entonces divergir es lo correcto.
3. **Parametriza en vez de cablear.** Si un script lleva dentro una ruta, un
   stack o el nombre de un proyecto, no es del kit: es de aquel proyecto. Sácalo
   a `parametros:`.

## Al cambiar algo que ya usa alguien

- **`major` si rompe**, y entonces hay que decir en el `CHANGELOG` qué tiene que
  hacer quien migre. `minor` si sólo añade o corrige.
- **Un tag publicado no se toca.** Se publica el siguiente.
- Antes de publicar, mira quién lo usa: `bash scripts/kit.sh estado` en el hub.

## Lo que hace que este kit sea creíble

**Verlo acertar y verlo fallar.** Aplícalo a un consumidor real, rompe a
propósito un archivo propagado, comprueba que la deriva lo marca, restáuralo y
comprueba que vuelve. Escríbelo en el `README`, con la salida literal y no con un
resumen.

Un instrumento en verde que nadie ha visto en rojo no demuestra nada — y este
método acumula demasiados casos de afirmaciones que sonaban a norma y eran
falsas.

## Lo que no va aquí

- **Nada que nombre al proyecto que lo originó.** Ni su ruta, ni su stack, ni su
  concepto. Una plantilla que hay que reescribir entera no ahorra nada, y encima
  invita a copiar afirmaciones ajenas.
- **Nada que sólo sirva a un proyecto.** Eso es del proyecto.
- **Secretos.** Ni tokens, ni contraseñas, ni `.env`. Un puntero a dónde vive la
  credencial, y nada más.
