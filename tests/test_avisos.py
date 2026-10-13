"""Los tres avisos de Telegram (decisión 166): cuándo salen y cuándo NO.

Lo segundo pesa más aquí. Un aviso que llega de más se silencia —y un bot
silenciado tampoco avisa el día del viaje, que es para lo que existe—, así que
la mitad de este archivo prueba silencios: el primer vistazo, el umbral, el
episodio ya avisado, la shell que no reporta nada y el arranque en frío.

Ninguna prueba toca tmux ni Telegram: `esperando` se inyecta y el relé se prueba
aparte, en `test_rele.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hub import avisos, slots

# Títulos reales, no inventados: el spinner de Claude Code es braille (trabajando)
# y el ✳ es un glifo cualquiera (detenido). Es lo que mira `api.estado_de_panel`.
TRABAJANDO = "⠋ Escribiendo el informe"
DETENIDO = "✳ Informe listo"
SHELL = "bash"

T0 = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def en(minutos: int) -> str:
    return (T0 + timedelta(minutes=minutos)).isoformat(timespec="seconds")


def nunca(pane_id: str) -> bool:
    """No hay cuadro de permisos en ningún panel."""
    return False


def siempre(pane_id: str) -> bool:
    return True


@pytest.fixture
def escena(con):
    """Un slot con su panel, y un latido recién tomado para que no estorbe."""
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('contab','Contabilidad')")
    slot_id = slots.crear(con, "contab", "cierre de agosto")
    con.execute(
        "INSERT INTO snapshot (id, tomado_en, server_pid, preservado) VALUES (1,?,99,0)",
        (en(0),),
    )
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
           VALUES (1,'%1','trabajo',0,0,'/home/x',?,'node','',?,?)""",
        (TRABAJANDO, "contab", slot_id),
    )
    return con


def titulo(con, valor: str) -> None:
    con.execute("UPDATE panel SET titulo=? WHERE pane_id='%1'", (valor,))


def latido(con, momento: str) -> None:
    con.execute("UPDATE snapshot SET tomado_en=? WHERE id=1", (momento,))


def revisar(con, minuto: int, esperando=nunca, ajustes=None, late=True):
    """Una vuelta del relé. El arranque se fija atrás: aquí nada está en gracia.

    `late` adelanta el muestreo hasta ese minuto, que es lo que hace el
    snapshotter cada 20 s. Sin ello, todas las pruebas de sesiones recibirían
    además el aviso de latido perdido — los tres avisos salen de la misma vuelta.
    """
    if late:
        latido(con, en(minuto))
    return avisos.revisar(
        con, momento=en(minuto), ajustes=ajustes, esperando=esperando,
        arranque=en(-60),
    )


# ── cuándo NO se avisa ────────────────────────────────────────────────────────


def test_el_primer_vistazo_no_avisa_de_nada(escena):
    """🔴 Al arrancar el relé, TODOS los paneles llevan ya un rato parados.

    Sin esto la primera vuelta mandaría un aviso por cada slot abierto, que es
    la forma más rápida de que el bot acabe silenciado. Sólo se avisa de una
    parada que el relé vio producirse.
    """
    titulo(escena, DETENIDO)
    assert revisar(escena, 0) == []
    assert revisar(escena, 99) == []   # y sigue callado por muy vieja que sea


def test_no_avisa_antes_de_que_pase_el_umbral(escena):
    """Contestar en dos minutos es estar delante, y estando delante no se avisa."""
    revisar(escena, 0)                  # trabajando: se apunta
    titulo(escena, DETENIDO)
    assert revisar(escena, 2) == []     # el umbral de «quieta» son 10


def test_volver_a_trabajar_cierra_el_episodio_sin_avisar(escena):
    """Es el caso de siempre: él lo ve, contesta, y la sesión sigue."""
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    revisar(escena, 5)
    titulo(escena, TRABAJANDO)
    assert revisar(escena, 6) == []
    titulo(escena, DETENIDO)
    assert revisar(escena, 7) == []     # episodio nuevo: su umbral empieza de cero


def test_una_shell_no_avisa_nunca(escena):
    """Un panel sin glifo no reporta actividad: quieto ahí no significa nada.

    Sin esta línea, cada terminal suelta que alguien deja abierta mandaría un
    aviso de que «terminó» — y es el estado normal de una shell.
    """
    revisar(escena, 0)
    titulo(escena, SHELL)
    assert revisar(escena, 60) == []


def test_un_panel_de_la_bandeja_no_avisa(escena):
    """Los avisos son de trabajos que él nombró, no de cualquier ventana abierta."""
    escena.execute("UPDATE panel SET slot_id=NULL WHERE pane_id='%1'")
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    assert revisar(escena, 60) == []


def test_apagar_los_avisos_los_apaga_de_verdad(escena):
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    assert revisar(escena, 60, ajustes={"avisos": {"activos": False}}) == []


# ── cuándo sí ─────────────────────────────────────────────────────────────────


def test_avisa_cuando_una_sesion_lleva_rato_quieta(escena):
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    revisar(escena, 1)            # aquí el relé VE la parada: el episodio nace
    (aviso,) = revisar(escena, 12)
    assert aviso["clase"] == "quieta"
    assert aviso["clave"] == "%1"
    assert "cierre de agosto" in aviso["texto"]
    assert "Contabilidad" in aviso["texto"]


def test_un_cuadro_de_permisos_avisa_antes_y_lo_dice_distinto(escena):
    """🔴 Las dos mitades de «detenido», que el título no puede separar.

    `api.estado_de_panel` lo documenta: un panel detenido acabó **o** está
    esperando una respuesta, y desde el glifo no se sabe cuál. La pantalla sí lo
    sabe, y por eso este aviso llega a los 3 minutos y el otro a los 10: una
    sesión bloqueada en un permiso es tiempo muerto seguro.
    """
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    revisar(escena, 1, esperando=siempre)
    assert revisar(escena, 3, esperando=siempre) == []          # aún no
    (aviso,) = revisar(escena, 5, esperando=siempre)
    assert aviso["clase"] == "preguntando"
    assert "esperando que le contestes" in aviso["texto"]


def test_el_aviso_no_lleva_nada_de_la_pantalla(escena):
    """🔴 Regla dura 22 y decisión 166: sale el aviso, nunca el contenido.

    Lo que el cuadro de permisos está pidiendo se lee en el hub. Meterlo aquí
    —«para verlo sin entrar»— sacaría de la máquina justo lo que se decidió que
    no saliera, y lo haría funcionando mejor, que es lo difícil de notar.
    """
    escena.execute(
        "UPDATE panel SET titulo=?, cwd='/home/ana/clientes/acme', etiqueta=?"
        " WHERE pane_id='%1'",
        (DETENIDO, "rm -rf /home/ana/clientes/acme"),
    )
    revisar(escena, 0)
    escena.execute("UPDATE panel SET titulo=? WHERE pane_id='%1'", (TRABAJANDO,))
    revisar(escena, 1)
    escena.execute("UPDATE panel SET titulo=? WHERE pane_id='%1'", (DETENIDO,))
    revisar(escena, 2)
    (aviso,) = revisar(escena, 13)

    assert "/home/ana" not in aviso["texto"]
    assert "rm -rf" not in aviso["texto"]
    assert "clientes" not in aviso["texto"]


def test_cada_episodio_avisa_una_sola_vez(escena):
    """Un aviso cada 25 segundos se silencia el mismo día."""
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    revisar(escena, 1)
    assert len(revisar(escena, 12)) == 1
    avisos.marcar_avisado(escena, "%1", en(12))
    assert revisar(escena, 13) == []
    assert revisar(escena, 90) == []


def test_un_episodio_nuevo_vuelve_a_avisar_aunque_el_anterior_ya_avisara(escena):
    """🔴 Que el aviso salga UNA vez no puede significar que salga una vez y ya.

    Es la mitad silenciosa del «una sola vez»: si `avisado` no se limpiara al
    cambiar de episodio, el primer aviso de cada slot sería también el último, y
    el síntoma —un slot que deja de avisar— no se nota hasta que hace falta.
    """
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    revisar(escena, 1)
    assert len(revisar(escena, 12)) == 1
    avisos.marcar_avisado(escena, "%1", en(12))

    titulo(escena, TRABAJANDO)
    revisar(escena, 13)
    titulo(escena, DETENIDO)
    revisar(escena, 14)
    assert len(revisar(escena, 25)) == 1


def test_sin_marcar_avisado_se_vuelve_a_intentar(escena):
    """Si Telegram no responde, el aviso sigue siendo cierto en la vuelta siguiente.

    Son 46 fallos de red en cinco días en este canal: darlo por mandado al
    primer timeout es perder el aviso justo cuando la red va mal.
    """
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    revisar(escena, 1)
    assert len(revisar(escena, 12)) == 1
    assert len(revisar(escena, 13)) == 1


def test_los_umbrales_se_pueden_cambiar(escena):
    revisar(escena, 0)
    titulo(escena, DETENIDO)
    ajustes = {"avisos": {"quieta_min": 30}}
    revisar(escena, 1, ajustes=ajustes)
    assert revisar(escena, 12, ajustes=ajustes) == []
    assert len(revisar(escena, 32, ajustes=ajustes)) == 1


def test_un_umbral_de_cero_no_se_acepta():
    """Un cero convertiría el aviso en un chorro, o sea lo rompería sin parecerlo."""
    assert avisos.umbrales({"avisos": {"quieta_min": 0}})["quieta"] == 10
    assert avisos.umbrales({"avisos": {"quieta_min": "diez"}})["quieta"] == 10
    assert avisos.umbrales({"avisos": {"quieta_min": 30}})["quieta"] == 30


# ── el latido ─────────────────────────────────────────────────────────────────


def test_el_latido_perdido_avisa_una_vez(escena):
    latido(escena, en(-20))
    (aviso,) = revisar(escena, 0, late=False)
    assert aviso["clase"] == "sin-latido"
    assert aviso["clave"] == avisos.CLAVE_HUB
    avisos.marcar_avisado(escena, avisos.CLAVE_HUB, en(0))
    assert revisar(escena, 1, late=False) == []


def test_el_latido_que_vuelve_no_manda_nada(escena):
    """Tres avisos y ninguno más (decisión 166): el episodio se cierra callado."""
    latido(escena, en(-20))
    revisar(escena, 0, late=False)
    avisos.marcar_avisado(escena, avisos.CLAVE_HUB, en(0))
    latido(escena, en(1))
    assert revisar(escena, 1, late=False) == []
    # Y el corte siguiente sí vuelve a avisar: el episodio anterior se cerró.
    latido(escena, en(1))
    assert [a["clase"] for a in revisar(escena, 30, late=False)] == ["sin-latido"]


def test_tras_un_arranque_en_frio_el_latido_tiene_gracia(escena):
    """🔴 El caso que el viaje tiene que cubrir, y donde el aviso mentiría.

    Al encender, el último snapshot es de ANTES del apagón y el muestreo aún no
    ha escrito el primero. Sin gracia, el hub avisaría de que dejó de latir
    justo cuando está arrancando bien — y ese aviso es el que hay que creerse.
    """
    latido(escena, en(-600))
    recien = avisos.revisar(
        escena, momento=en(0), esperando=nunca, arranque=en(-1)
    )
    assert recien == []
    # Pasada la gracia, si de verdad no late, avisa.
    tarde = avisos.revisar(
        escena, momento=en(10), esperando=nunca, arranque=en(-1)
    )
    assert [a["clase"] for a in tarde] == ["sin-latido"]


def test_un_panel_que_desaparece_se_olvida(escena):
    """Un `pane_id` reciclado por tmux no puede heredar el episodio del anterior.

    Si lo heredara, heredaría también su `avisado` y el aviso bueno no saldría.
    """
    apuntados = lambda: {f["clave"] for f in escena.execute("SELECT clave FROM aviso")}

    revisar(escena, 0)
    assert "%1" in apuntados()
    escena.execute("DELETE FROM panel WHERE pane_id='%1'")
    revisar(escena, 1)
    assert "%1" not in apuntados()
    assert avisos.CLAVE_HUB in apuntados()   # el latido no es un panel: se queda


def test_un_cuadro_de_permisos_avisa_aunque_no_se_viera_trabajar(escena):
    """🔴 Decisión 230. El primer agente de encargo atascado en un permiso no
    avisó: trabaja a ráfagas de veinte segundos y el relé nunca lo pilló
    «trabajando», así que la parada no se «vio producirse». Un cuadro de
    permisos abierto es evidencia por sí mismo: se mide en la pantalla."""
    titulo(escena, DETENIDO)
    assert revisar(escena, 0, esperando=siempre) == []
    assert revisar(escena, 2, esperando=siempre) == []
    (aviso,) = revisar(escena, 3, esperando=siempre)
    assert aviso["clase"] == "preguntando"


def test_una_sesion_quieta_desde_el_principio_sigue_sin_avisar(escena):
    """La otra mitad no cambia: sin cuadro de permisos, lo que ya estaba quieto
    al arrancar no es noticia."""
    titulo(escena, DETENIDO)
    for minuto in (0, 5, 15):
        assert revisar(escena, minuto) == []


# ── la máquina que se queda sola (decisión 248) ───────────────────────────────


def medida(con, clave: str, valor: float, momento: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO maquina (clave, valor, texto, unidad, medido_en)"
        " VALUES (?,?,'','',?)",
        (clave, valor, momento),
    )


def test_la_gpu_caliente_avisa_una_vez_y_no_en_cada_vuelta(escena):
    """Un episodio, un aviso. Lo contrario silencia el bot el mismo día."""
    medida(escena, "gpu.temperatura", 91, en(0))

    primera = [a["clase"] for a in revisar(escena, 1)]
    avisos.marcar_avisado(escena, "maquina:gpu.temperatura", en(1))  # lo hace el relé al mandarlo
    segunda = [a["clase"] for a in revisar(escena, 2)]

    assert primera == ["temperatura"]
    assert segunda == []


def test_la_gpu_trabajando_no_es_una_gpu_caliente(escena):
    """80 °C es una GPU de esta gama haciendo su trabajo, no una avería."""
    medida(escena, "gpu.temperatura", 80, en(0))

    assert revisar(escena, 1) == []


def test_una_medida_vieja_no_dispara_nada(escena):
    """🔴 Si el muestreo murió, lo que hay que saber es eso —y de eso avisa el
    latido—, no la última temperatura conocida de hace seis horas."""
    medida(escena, "gpu.temperatura", 91, en(0))

    assert [a["clase"] for a in revisar(escena, 90)] == []


def test_el_disco_avisa_por_abajo_y_la_temperatura_por_arriba(escena):
    """Los dos límites miran en direcciones contrarias: es el error fácil."""
    medida(escena, "disco.windows.libre", 4, en(0))
    medida(escena, "gpu.temperatura", 40, en(0))

    clases = [a["clase"] for a in revisar(escena, 1)]

    assert clases == ["disco"]


def test_el_limite_se_puede_cambiar_desde_el_canal(escena):
    """El de fábrica es una opinión; la habitación de cada uno es otra cosa."""
    medida(escena, "gpu.temperatura", 70, en(0))

    assert revisar(escena, 1) == []
    assert [a["clase"] for a in revisar(escena, 2, ajustes={"avisos": {"temperatura": 65}})] \
        == ["temperatura"]


def test_lo_que_vuelve_a_su_sitio_puede_volver_a_avisar(escena):
    """El episodio se cierra en silencio y el siguiente vuelve a contar."""
    medida(escena, "gpu.temperatura", 91, en(0))
    assert len(revisar(escena, 1)) == 1
    avisos.marcar_avisado(escena, "maquina:gpu.temperatura", en(1))

    medida(escena, "gpu.temperatura", 50, en(2))
    assert revisar(escena, 3) == []

    medida(escena, "gpu.temperatura", 92, en(4))
    assert [a["clase"] for a in revisar(escena, 5)] == ["temperatura"]
