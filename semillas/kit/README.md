# @NOMBRE@

@DESCRIPCION@

## Qué aporta

<!-- Una capacidad, dicha en una frase que empiece por un verbo. Si necesitas la
     palabra «y» para describirla, probablemente son dos kits. -->

## Cómo se usa

Este kit se aplica con el hub, que lo resuelve por `id`:

```bash
bash scripts/kit.sh instalar @ID@
# y desde Claude Code, en el proyecto destino: «aplica el kit @ID@»
```

**Su contenido funciona sin el hub.** Los documentos se leen y los scripts corren
a mano; lo que el hub aporta es aplicarlo, resolverlo por `id`, medir su deriva y
mantenerlo — igual que un JAR funciona sin Maven, pero nadie quiere cablear el
classpath a mano.

## Estado

<!-- 🔴 Lo primero que alguien lee cuando se plantea usarlo. Sé literal:
     qué se ha medido, qué no, y contra qué consumidor. «Debería funcionar» no es
     una medida, y este método acumula demasiados casos de afirmaciones que
     sonaban a norma y eran falsas. -->

**Sin consumidores medidos todavía.** Hasta que uno lo aplique y se vea la deriva
acertar y fallar, esto es un instrumento en verde que nadie ha visto funcionar.

## Versiones

`major.minor`. **Un tag publicado no se mueve**: si hay que corregir algo, se
publica la siguiente. Si un tag se reescribiera, todo lo que midió deriva contra
él pasaría a mentir sin avisar.

- `major` — rompe: quien lo use tiene que migrar. Dilo en el `CHANGELOG`.
- `minor` — añade o corrige sin romper.
