"""Los dos scripts de operador: guardar un secreto y dar de alta un servidor.

🔴 Se prueban ejecutándolos con un `HOME` de mentira. Son scripts que escriben
en `~/.ssh` y crean archivos con secretos dentro: «lo probé a mano y funcionó»
es exactamente la garantía que no vale aquí, porque los modos de fallo que
importan —permisos flojos, un alias duplicado, pisar lo que ya había— no se ven
al ejecutarlos bien una vez.

Ninguna prueba sale a la red ni toca el `~/.ssh` de quien las corre.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SECRETO = RAIZ / "scripts" / "guardar-secreto.sh"
ALTA = RAIZ / "scripts" / "alta-conexion.sh"


def correr(script: Path, *args, casa: Path, entrada: str = "", ruta_extra: str = ""):
    entorno = {**os.environ, "HOME": str(casa)}
    if ruta_extra:
        entorno["PATH"] = f"{ruta_extra}:{entorno['PATH']}"
    return subprocess.run(
        ["bash", str(script), *args], input=entrada, capture_output=True,
        text=True, timeout=60, env=entorno,
    )


# ── guardar un secreto ────────────────────────────────────────────────────────


def test_el_secreto_queda_solo_para_su_dueno(tmp_path):
    """Un token legible por cualquiera del sistema es un token filtrado, y el
    archivo se ve perfectamente normal: nada avisa."""
    destino = tmp_path / "secretos" / "bot.env"
    r = correr(SECRETO, str(destino), "TOKEN_BOT", casa=tmp_path, entrada="abc123\n")

    assert r.returncode == 0, r.stderr
    assert destino.read_text().strip() == "TOKEN_BOT=abc123"
    assert oct(destino.stat().st_mode)[-3:] == "600"
    assert oct(destino.parent.stat().st_mode)[-3:] == "700"


def test_el_valor_NO_viaja_por_la_linea_de_comandos(tmp_path):
    """🔴 La razón de que este script exista.

    Un secreto en los argumentos queda en el historial del shell y lo ve
    cualquiera que mire `ps` mientras corre. Dos sitios donde nadie lo va a
    borrar. Por eso sólo se acepta por la entrada estándar.
    """
    fuente = SECRETO.read_text(encoding="utf-8")
    assert "read -rs valor" in fuente
    # Y que no haya una puerta de atrás por argumento: sólo dos posicionales.
    assert '"${3:-}"' not in fuente


def test_sin_valor_no_se_crea_nada(tmp_path):
    """Un Enter en falso no puede dejar un archivo con la clave vacía: el hub
    lo leería como «hay token» y el fallo saldría como un 401 de Telegram, a
    tres capas de distancia."""
    destino = tmp_path / "bot.env"
    r = correr(SECRETO, str(destino), "TOKEN_BOT", casa=tmp_path, entrada="\n")

    assert r.returncode != 0
    assert not destino.exists()


def test_guardar_otro_secreto_no_borra_el_primero(tmp_path):
    """🔴 Pisar el archivo entero borraría los demás secretos que vivan ahí, y
    esa pérdida NO deja rastro: el archivo sigue siendo válido."""
    destino = tmp_path / "bot.env"
    correr(SECRETO, str(destino), "PRIMERO", casa=tmp_path, entrada="uno\n")
    correr(SECRETO, str(destino), "SEGUNDO", casa=tmp_path, entrada="dos\n")

    contenido = destino.read_text()
    assert "PRIMERO=uno" in contenido and "SEGUNDO=dos" in contenido


def test_reescribir_la_misma_clave_la_sustituye(tmp_path):
    """Y no deja las dos: un archivo con la clave dos veces es una bomba de
    relojería, porque quien lo lee se queda con una y nadie sabe con cuál."""
    destino = tmp_path / "bot.env"
    correr(SECRETO, str(destino), "TOKEN_BOT", casa=tmp_path, entrada="viejo\n")
    correr(SECRETO, str(destino), "TOKEN_BOT", casa=tmp_path, entrada="nuevo\n")

    lineas = [l for l in destino.read_text().splitlines() if l.startswith("TOKEN_BOT")]
    assert lineas == ["TOKEN_BOT=nuevo"]


def test_el_puntero_que_imprime_es_el_que_entiende_el_hub(tmp_path):
    """Lo que imprime se pega tal cual en `/conexiones` o en `canal.yml`. Si el
    formato no casa, el usuario lo pega igual y el fallo aparece después."""
    from hub import telegram

    destino = tmp_path / "secretos" / "bot.env"
    r = correr(SECRETO, str(destino), "TOKEN_BOT", casa=tmp_path, entrada="abc123\n")
    puntero = r.stdout.strip().splitlines()[-1].strip()

    assert telegram.leer_token(puntero.replace("~", str(tmp_path), 1)) == "abc123"


def test_una_clave_en_minusculas_se_rechaza(tmp_path):
    r = correr(SECRETO, str(tmp_path / "x.env"), "token", casa=tmp_path, entrada="a\n")
    assert r.returncode == 2
    # Y se dice cómo se usa, no sólo que está mal: un «no sirve» a secas obliga
    # a volver al archivo a ver qué esperaba.
    assert "uso:" in r.stderr


def test_los_argumentos_valen_en_cualquier_orden(tmp_path):
    """🔴 Le pasó a la primera, y el mensaje que salía era el peor posible:
    hablaba de «nombre de clave» enseñando una RUTA.

    Son dos argumentos que se distinguen a simple vista —una ruta lleva barras,
    una clave son mayúsculas—, así que exigir el orden sólo sirve para que
    alguien lo falle. Y al fallarlo no está haciendo nada ambiguo.
    """
    destino = tmp_path / "bot.env"
    r = correr(SECRETO, "TOKEN_BOT", str(destino), casa=tmp_path, entrada="abc123\n")

    assert r.returncode == 0, r.stderr
    assert destino.read_text().strip() == "TOKEN_BOT=abc123"
    assert "al revés" in r.stderr, "lo arregló en silencio: hay que decirlo"


def test_pasar_el_VALOR_como_argumento_se_dice_por_su_nombre(tmp_path):
    """🔴 El error que de verdad se comete, y es el que este script existe para
    evitar: «guardar el token» suena a darle el token.

    Contestar «no sirve como nombre de clave» ahí es inútil — el problema no es
    el nombre, es que el secreto acaba de pasar por la línea de comandos, o sea
    por el historial y por `ps`. Hay que decir eso y cómo deshacerlo.
    """
    parece_token = "8123456789:AAFmQ7bZk3xR1pLwYt2VnCd9eHjKsGaUvBo"
    r = correr(SECRETO, str(tmp_path / "x.env"), parece_token,
               casa=tmp_path, entrada="")

    assert r.returncode == 2
    assert "parece el VALOR" in r.stderr
    assert "historial" in r.stderr
    assert "/revoke" in r.stderr, "hay que decir que ese token ya no vale"
    # 🔴 Y no se repite el secreto en la salida: quejarse de un token
    # enseñándolo otra vez lo deja también en el scrollback del terminal.
    assert parece_token not in r.stderr and parece_token not in r.stdout


def test_una_clave_en_minusculas_propone_la_buena(tmp_path):
    """Es el fallo cercano más común, y proponer la corrección ahorra el viaje
    de ida y vuelta al archivo a ver qué esperaba."""
    r = correr(SECRETO, str(tmp_path / "x.env"), "telegram_token",
               casa=tmp_path, entrada="")
    assert "TELEGRAM_TOKEN" in r.stderr


def test_un_valor_sospechosamente_corto_se_avisa_al_GUARDARLO(tmp_path):
    """🔴 Pasó: se pegó un token cortado, el archivo quedó perfectamente válido
    y el fallo sólo apareció al preguntarle a Telegram, horas después y a una
    capa de distancia.

    Aquí no se puede saber si un secreto es correcto, pero sí que tiene una
    pinta rara. No se rechaza —hay secretos legítimamente cortos— pero se dice
    donde todavía es barato arreglarlo.
    """
    destino = tmp_path / "bot.env"
    r = correr(SECRETO, str(destino), "TELEGRAM_TOKEN", casa=tmp_path, entrada="corto\n")

    assert r.returncode == 0                       # se guarda igual
    assert destino.read_text().strip() == "TELEGRAM_TOKEN=corto"
    assert "sólo 5 caracteres" in r.stderr
    assert "forma de token de Telegram" in r.stderr


def test_un_token_con_buena_pinta_no_molesta(tmp_path):
    """Un aviso que salta siempre se aprende a ignorar, y entonces el día que
    importa tampoco se lee (regla dura 13)."""
    bueno = "8123456789:AAFmQ7bZk3xR1pLwYt2VnCd9eHjKsGaUvBo"
    r = correr(SECRETO, str(tmp_path / "bot.env"), "TELEGRAM_TOKEN",
               casa=tmp_path, entrada=bueno + "\n")

    assert r.returncode == 0
    assert "⚠" not in r.stderr
    assert bueno not in r.stdout and bueno not in r.stderr


def test_dos_rutas_no_se_adivinan(tmp_path):
    """Corregir el orden sólo vale cuando no hay duda. Con dos cosas que no son
    una clave, inventarse cuál era cuál sería escribir un secreto en un sitio
    que nadie pidió."""
    r = correr(SECRETO, str(tmp_path / "a.env"), str(tmp_path / "b.env"),
               casa=tmp_path, entrada="x\n")
    assert r.returncode == 2


# ── dar de alta un servidor ───────────────────────────────────────────────────


@pytest.fixture
def ssh_de_mentira(tmp_path):
    """`ssh` y `ssh-copy-id` falsos: el alta no puede probarse contra un
    servidor de verdad, pero sí todo lo que hace ANTES de tocar la red."""
    if not shutil.which("ssh-keygen"):
        pytest.skip("hace falta ssh-keygen")
    binarios = tmp_path / "bin"
    binarios.mkdir()
    (binarios / "ssh").write_text(
        "#!/bin/sh\n"
        # Sin la marca, «entrar sin contraseña» falla: es el estado inicial.
        "[ -f \"$HOME/.entra\" ] && exit 0\nexit 255\n"
    )
    (binarios / "ssh-copy-id").write_text(
        "#!/bin/sh\ntouch \"$HOME/.entra\"\necho copiada\n"
    )
    for f in binarios.iterdir():
        f.chmod(0o755)
    return str(binarios)


def test_el_alta_deja_clave_bloque_y_comprobacion(tmp_path, ssh_de_mentira):
    r = correr(ALTA, "vps-pruebas", "10.0.0.4", "deploy", "2222",
               casa=tmp_path, ruta_extra=ssh_de_mentira)

    assert r.returncode == 0, r.stderr
    clave = tmp_path / ".ssh" / "vps-pruebas"
    assert clave.is_file() and oct(clave.stat().st_mode)[-3:] == "600"
    config = (tmp_path / ".ssh" / "config").read_text()
    assert "Host vps-pruebas" in config
    assert "Port 2222" in config and "User deploy" in config
    assert "IdentityFile" in config
    assert "se entra con la clave" in r.stdout


def test_repetir_el_alta_no_duplica_el_bloque(tmp_path, ssh_de_mentira):
    """🔴 Un alias repetido hace que ssh use el PRIMERO y el segundo no se
    aplique nunca. El síntoma es «cambié el puerto y sigue sin funcionar», y no
    hay nada en pantalla que lo explique."""
    for _ in range(2):
        correr(ALTA, "vps-pruebas", "10.0.0.4", "deploy",
               casa=tmp_path, ruta_extra=ssh_de_mentira)

    config = (tmp_path / ".ssh" / "config").read_text()
    assert config.count("Host vps-pruebas") == 1


def test_no_se_da_por_bueno_sin_comprobar_que_entra(tmp_path):
    """Que `ssh-copy-id` no falle no significa que se entre: lo que importa es
    entrar SIN contraseña, y eso sólo lo dice intentarlo."""
    binarios = tmp_path / "bin"; binarios.mkdir()
    (binarios / "ssh").write_text("#!/bin/sh\nexit 255\n")          # nunca entra
    (binarios / "ssh-copy-id").write_text("#!/bin/sh\nexit 0\n")    # pero dice que sí
    for f in binarios.iterdir():
        f.chmod(0o755)

    r = correr(ALTA, "vps-pruebas", "10.0.0.4", "deploy",
               casa=tmp_path, ruta_extra=str(binarios))

    assert r.returncode != 0
    assert "no se pudo entrar" in r.stderr


def test_la_clave_se_crea_sin_passphrase_a_proposito(tmp_path):
    """El despliegue corre sin nadie delante: una passphrase sólo lo rompería a
    las tres de la mañana. Lo que la protege son sus permisos."""
    assert '-N ""' in ALTA.read_text(encoding="utf-8")


def test_un_alias_raro_se_rechaza(tmp_path):
    r = correr(ALTA, "VPS Ejemplo", "10.0.0.4", "deploy", casa=tmp_path)
    assert r.returncode == 2
