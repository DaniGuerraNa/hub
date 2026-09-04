# La sala limpia: probar una instalación como la vería otra persona

Contesta: **¿qué le pasa a alguien que clona esto y lo instala, sin mí al lado?**

Los tests en verde no lo contestan. Lo que más ha dolido aquí —un test que sólo
pasaba en la máquina donde nació, un botón que no abría terminal porque tmux
nunca se había arrancado, tres preguntas seguidas para acabar sin capa base—
tenía la suite entera en verde y sólo apareció cuando **otra persona** lo
instaló en limpio. La sala limpia reproduce a esa persona sin esperar a que
exista.

## Qué es

Un contenedor Ubuntu recién instalado con **sólo** lo que pide el doctor (git,
tmux, uv, Claude Code), un usuario nuevo sin `~/.claude`, y un Claude sin
memoria, sin skills de usuario y sin tmux abierto. Dentro, un script hace **una**
petición —«instala este repo»— y contesta «sí, adelante» a cada parada. Cada
turno que añade es una pregunta que la persona tuvo que responder.

Los archivos están en `scripts/sala-limpia/`: el `Dockerfile`, `persona.sh` (la
persona simulada) y `sala.sh` (el mando).

## Procedimiento

```bash
bash scripts/sala-limpia/sala.sh construir      # una vez; la imagen se reutiliza
bash scripts/sala-limpia/sala.sh arrancar       # contenedor nuevo + clon del hub desde GitHub
bash scripts/sala-limpia/sala.sh hub            # «instala este repo», y comprueba que contesta
bash scripts/sala-limpia/sala.sh kit ~/ruta/al/kit          # copia el kit y pide instalarlo
bash scripts/sala-limpia/sala.sh pedir anexar "anexa mi proyecto ~/workspace: es laboral …"
bash scripts/sala-limpia/sala.sh ver kit-mi-kit             # el transcript
bash scripts/sala-limpia/sala.sh dentro "tmux ls; cat ~/.local/share/hub/projects.yml"
bash scripts/sala-limpia/sala.sh borrar
```

`arrancar` clona el hub **desde GitHub**, no desde tu carpeta: se prueba lo que
está publicado, que es lo que la otra persona va a recibir. Si quieres probar
un cambio antes de publicarlo, `dentro` te deja copiarlo (`docker cp` y
`chown persona`), pero entonces lo que has probado no es lo publicado, y hay
que decirlo así.

**Las credenciales.** `arrancar` copia tu `~/.claude/.credentials.json` al
contenedor: la persona simulada usa tu cuenta. Viven sólo ahí y se van con
`borrar`. Nunca se hornean en la imagen ni se comparte un contenedor con ellas.

## Cómo se lee un transcript

Cada `### TURNO n` después del primero es una parada. Por cada una, pregunta:

| Lo que ves | Qué significa |
|---|---|
| Una pregunta con respuesta obvia («¿instalo sin servicios?») | La skill tenía un default y no lo tomó. Se arregla en la skill, no en la persona |
| La misma pregunta repetida dos o tres turnos | Era una elección A/B: un «sí» no la contesta. Una persona real la contesta, pero también es una parada que sobra si había default |
| Un consejo que no aplica a la máquina («edita `/etc/wsl.conf`» en un Ubuntu que no es WSL) | El doctor o la skill dan por hecho tu máquina. Es el hallazgo más peligroso: la persona lo hace |
| «Listo» sin pregunta | Donde una persona real se queda. **Comprueba lo prometido** con `dentro`: `curl` al hub, `tmux ls`, `ls` del workspace, el registro |
| `### CORTADO en el turno 8` | La skill no converge sola. Grave |

Y dos cosas que el transcript no dice y hay que mirar:

- **Qué tocó del sistema.** `dentro "ls /etc/wsl.conf; cat ~/.config/systemd/user/*"`.
  Lo que la persona simulada hizo con un `sudo` es lo que haría la real.
- **Qué quedó a medias.** Un hub «instalado» sin snapshotter parece instalado y
  no relee el registro. Un workspace con `.claude/hub/kits.yml` y sin
  `project.yml` sale como capa base incompleta en la primera pantalla.

## Auditar un kit

Para cada kit, en este orden, y anotando los turnos de cada paso:

1. `hub` hasta ver 200 y los dos procesos (`hub.web`, `hub.snapshotter`).
2. `kit <ruta>` con la petición por defecto. Esperado: **un turno, cero
   preguntas**, y `find ~/workspace` enseña lo que el `kit.yml` declara en
   `aplica`. Lo que falte, o lo que sobre, es deriva desde el minuto uno.
3. `pedir anexar "anexa mi proyecto ~/workspace …"` con la frase que la guía del
   kit le da a la persona. Esperado: un bloque correcto en `projects.yml` sin
   más de una pregunta, y ningún archivo nuevo en el workspace que la guía no
   prometa (ni `.git`, ni un documento de estado inventado).
4. Una acción real del kit desde el workspace: `pedir primera "haz el onboarding
   de …" ~/workspace`, o la que el kit prometa como primer uso. Esperado: hace
   lo que dice, escribe sólo donde su `SKILL.md` dice, y el reporte final no
   miente sobre lo que quedó.
5. `dentro` para lo que el transcript no enseña: `tmux ls`, el registro, el
   workspace, `/etc`.

Escribe el resultado **literal** —turnos, preguntas, qué quedó— en el `README`
del kit, en «Estado». Un kit auditado en sala limpia dice: *«3-sep, instalación
en un turno, alta en dos, onboarding correcto; quedó X sin resolver»*. Un kit
que sólo dice «funciona» no se ha visto fallar.

## Cuándo pasar por aquí

- Antes de promocionar el hub a `main`: `hub` entero. Es lo que la regla de
  publicación llama «haberlo usado».
- Antes de publicar una versión de un kit que otra persona instala.
- Cuando alguien reporte «me hizo muchas preguntas» o «no me abrió X»: se
  reproduce aquí antes de tocar nada, porque desde tu máquina no se ve.

## Lo que la sala limpia no ve

- Windows nativo, macOS, otro shell: la imagen es Ubuntu con bash.
- systemd de usuario: el contenedor no lo tiene, así que la instalación
  siempre cae al arranque a mano. La ruta con servicios sólo se prueba en WSL o
  en un Linux real.
- Lo que una persona haría distinto de decir «sí»: `RESPUESTA="no"` o
  `RESPUESTA="A"` cambian esa actitud, pero siguen siendo una persona de una
  sola palabra.
