# El hub en una máquina aparte

Una segunda máquina sin monitor —un PC viejo, un mini PC— que tiene el hub y tu
trabajo, y que usas desde tu PC de siempre. Se puede, y casi todo es lo que ya
hace [Acceso](/acceso) para entrar desde el móvil. Lo que esta guía añade es lo
que cambia cuando **nadie se sienta nunca delante de esa máquina**: cómo das de
alta el primer aparato sin pantalla, cómo vuelve sola tras un apagón y por dónde
entras si algo se rompe.

## Lo que necesitas

- En la máquina del hub: **Linux, o Windows con WSL2**, y el hub instalado
  con sus servicios (`INSTALAR.md`). El instalador deja puesto el *linger*, que
  mantiene los servicios vivos sin ninguna terminal abierta.
- **Una red privada** entre las dos máquinas. Con Tailscale: instalado en las
  dos y, si la del hub es Windows, **el de Windows**, no uno dentro de WSL.
- **SSH** a la máquina del hub. Lo usarás una vez para el primer aparato y,
  después, sólo si algo falla.

## Ponerla en marcha

1. **Publica el hub en la red privada.** En la máquina del hub (si es Windows,
   en PowerShell de Windows):

   ```
   tailscale serve --bg 8787
   ```

   `--bg` hace que se guarde: sin él, `serve` muere al cerrar esa terminal y
   tras un apagón no estaría. Si usas otro puerto (`HUB_PORT`), pon ése.
2. **Declara su nombre** en `~/.local/share/hub/acceso.yml`, el de la red
   privada y exacto (sin `*`):

   ```yaml
   hosts:
     - mi-servidor.tu-red.ts.net
   ```
3. **Da de alta tu PC.** Desde tu PC, entra por SSH a la máquina del hub y, en
   la carpeta del hub:

   ```bash
   uv run python -m hub.acceso alta "Mi PC"
   ```

   Imprime un QR y, debajo, un enlace. **No hace falta escanear nada**: abre
   ese enlace en el navegador de tu PC antes de 10 minutos y queda dada de
   alta. El móvil, después, desde [Acceso](/acceso) con su QR.
4. Entra a `https://mi-servidor.tu-red.ts.net` desde tu PC.

## Que vuelva sola tras un apagón

Sin nadie delante, un corte de luz sólo tiene vuelta si estas piezas están
puestas. Ninguna avisa si falta: se descubre el día que no puedes entrar. Por
eso **[Máquina](/maquina) → Salud** mide las que puede en cuanto hay un nombre
en `acceso.yml`, y dice el arreglo de la que falte.

| Pieza | Dónde | Cómo |
|---|---|---|
| Encender al volver la luz | BIOS | «Restore on AC power loss» o «AC BACK» → *Power On* / *Always On*. El hub no lo puede ver |
| WSL arranca sin iniciar sesión | Windows | `scripts/arrancar-sin-sesion.ps1`, una vez, en PowerShell **como administrador**. Crea una tarea al encender que no guarda tu contraseña |
| Tailscale conecta sin sesión | Windows | `tailscale set --unattended=true`. Sin esto se queda esperando a que alguien entre en Windows |
| No suspenderse | Windows | `powercfg /change standby-timeout-ac 0` |
| La red privada lleva al hub | las dos | `tailscale serve --bg 8787` (arriba) |
| Los servicios, sin terminal | Linux/WSL | `loginctl enable-linger $USER`; lo pone el instalador |
| Tus ventanas de trabajo | hub | Marca los slots como persistentes (↻) y, al volver, [Panorama](/) te ofrece reabrirlos. Si quieres tmux en marcha sin entrar, `scripts/tmux-arranque.service` es un ejemplo |

Con el hub en WSL, PowerShell de Windows llega al script por la ruta de red
de WSL (cambia la distro, tu usuario y la carpeta donde clonaste el hub):

```
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\tu-usuario\hub\scripts\arrancar-sin-sesion.ps1
```

En un Linux sin Windows debajo, Tailscale ya corre como servicio del sistema y
no tiene la pega de la sesión; ahí sólo cuentan la BIOS, `serve` y el linger.

**Pruébalo una vez de verdad**: apaga, enciende **sin iniciar sesión** y entra
desde tu PC. Es la única forma de saber que la cadena entera funciona.

## Si no puedes entrar por el navegador

SSH sigue ahí. Para usar el hub aunque la puerta de Acceso falle:

```bash
ssh -L 8787:127.0.0.1:8787 usuario@mi-servidor
```

y abre `http://localhost:8787` en tu PC. Entras como si estuvieras delante,
sin alta ni interruptor: no es un agujero, porque quien tiene SSH ya tiene una
shell en esa máquina.

## Lo que todavía no funciona entre dos máquinas

- **Reuniones** necesita su agente de Windows en la misma máquina que el hub:
  con el hub aparte no graba las llamadas de tu PC.
- **El relevo del secretario** —abrirte en la PC lo que sólo tú puedes hacer
  ahí— se queda en «Te espera», dentro de su pantalla.
- **El diagnóstico de Windows** del secretario («me salió una pantalla azul»)
  revisa la máquina del hub, no tu PC.
- **Si la máquina entera se cae, nadie avisa**: el aviso de «hub callado» lo
  manda ella misma. Lo verás en la app de Tailscale, con la máquina
  desconectada.
- **La terminal remota se apaga en cada reinicio** del hub, a propósito: tras
  una actualización o un apagón, se vuelve a abrir en [Acceso](/acceso).
- **Conectar Google Calendar** (`uv run python -m hub.secretario
  google-entrar`) se hace por SSH: abre el enlace en tu PC, acepta, y la página
  a la que te lleva no cargará. Copia su dirección entera y pégala en la
  terminal.
- **Abrir un proyecto en tu editor** no lo hace el hub: con VS Code, su
  extensión *Remote - SSH* abre la carpeta de la máquina del hub.
