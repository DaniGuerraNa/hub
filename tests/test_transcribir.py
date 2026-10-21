"""Pasar un audio a texto con un comando de fuera: qué se exige y cómo se falla.

El hub no trae whisper (decisión 221 y la cabecera del módulo), así que aquí lo
que se prueba de verdad es **el trato con un programa ajeno**: que el que falta
se diga con la línea exacta que hay que escribir, que el mal configurado se
rechace antes de gastar un audio, y que los dos modos de no tener texto queden
separados.

Los transcriptores de estos tests son guiones de Python ejecutados de verdad, no
un `subprocess.run` sustituido: lo que se quiere comprobar es el manejo de un
proceso que sale con código 3 o que no imprime nada, y un doble sólo probaría el
doble.
"""

from __future__ import annotations

import sys

import pytest

from hub import transcribir


def con_comando(comando) -> dict:
    return {"transcripcion": {"comando": comando}}


def guion(codigo: str) -> list[str]:
    """Un transcriptor de mentira, pero un proceso de verdad.

    `{audio}` va como último argumento, que es donde lo pondría cualquiera.
    """
    return [sys.executable, "-c", codigo, "{audio}"]


@pytest.fixture
def audio(tmp_path):
    ruta = tmp_path / "nota-0001.oga"
    ruta.write_bytes(b"OggS-una-nota-de-voz")
    return ruta


# ── lo que falta, dicho de forma que se pueda arreglar ───────────────────────


@pytest.mark.parametrize(
    "ajustes",
    [None, {}, {"transcripcion": {}}, {"transcripcion": {"comando": ""}}],
)
def test_sin_transcriptor_el_error_trae_dentro_la_linea_de_yaml_que_falta(ajustes):
    """🔴 El mensaje de error es la documentación de esta función.

    Quien se encuentra esto no está leyendo el código: está mirando por qué un
    audio se quedó aparcado. «No hay transcriptor» a secas le deja buscando en
    qué archivo y con qué forma; con la línea dentro, lo arregla y reintenta.
    """
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.comando(ajustes)

    mensaje = str(exc.value)
    assert "encargos.yml" in mensaje
    assert "transcripcion:" in mensaje and "comando:" in mensaje
    assert "{audio}" in mensaje


def test_un_comando_que_no_dice_donde_va_el_archivo_se_rechaza_al_configurarlo():
    """Y no al usarlo, que es la diferencia entre un aviso y un audio perdido.

    Sin `{audio}` el transcriptor se ejecutaría sin recibir nada y devolvería
    vacío: eso llega como «no se entendió» y se le acabaría preguntando a la
    persona que repita algo que sí se oía. El comando se valida solo, sin audio
    delante, para que el fallo salga cuando se escribe la configuración.
    """
    with pytest.raises(transcribir.SinTranscriptor, match="dónde va el archivo"):
        transcribir.comando(con_comando("/opt/whisper/transcribe.sh --modelo base"))


# ── cadena o lista ───────────────────────────────────────────────────────────


def test_una_cadena_se_parte_respetando_las_comillas():
    """La cadena es lo que uno escribe la primera vez, así que se admite; pero
    partirla por espacios a secas rompería la primera ruta con un espacio."""
    linea = '"/opt/mis cosas/whisper.sh" --modelo base {audio}'
    assert transcribir.comando(con_comando(linea)) == [
        "/opt/mis cosas/whisper.sh", "--modelo", "base", "{audio}",
    ]


def test_una_lista_se_respeta_tal_cual():
    """La lista es la forma correcta: nada que interpretar, nada que partir por
    donde no es."""
    partes = ["/opt/mis cosas/whisper.sh", "--modelo", "base", "{audio}"]
    assert transcribir.comando(con_comando(partes)) == partes


# ── ejecutar ─────────────────────────────────────────────────────────────────


def test_el_audio_se_le_pasa_donde_el_comando_dice_audio(audio):
    """La sustitución es todo el contrato con el programa de fuera: si el
    marcador se quedara sin reemplazar, el transcriptor abriría un archivo
    llamado literalmente «{audio}»."""
    ajustes = con_comando(guion("import sys; print(sys.argv[1])"))
    assert transcribir.transcribir(audio, ajustes) == str(audio)


def test_el_texto_vuelve_sin_los_espacios_de_los_bordes(audio):
    """Los transcriptores sueltan saltos de línea al final. Ese blanco viajaría
    hasta la ficha del encargo y de ahí al prompt del agente."""
    ajustes = con_comando(guion('print("\\n  abro a las siete y apunto los fiados\\n")'))
    assert transcribir.transcribir(audio, ajustes) == "abro a las siete y apunto los fiados"


def test_un_audio_que_no_esta_no_llega_a_ejecutar_nada(tmp_path, monkeypatch):
    """Lanzar el proceso para que falle dentro cuesta segundos y devuelve un
    error del transcriptor sobre un archivo que nunca existió."""
    monkeypatch.setattr(
        transcribir.subprocess, "run",
        lambda *a, **k: pytest.fail("no había audio y aun así se ejecutó el transcriptor"),
    )
    with pytest.raises(transcribir.SinTranscriptor, match="no existe el audio"):
        transcribir.transcribir(tmp_path / "no-esta.oga", con_comando(guion("pass")))


# ── los tres modos de no obtener texto, y por qué no son el mismo ────────────


def test_no_haber_podido_y_no_haber_entendido_son_errores_distintos():
    """🔴 El test que fija la distinción entera.

    «No se pudo transcribir» se arregla —falta un modelo, falta ffmpeg— y se
    reintenta con el mismo audio. «Se transcribió y no dijo nada» no se arregla
    tocando la máquina: hay que preguntarle a la persona. Si una heredara de la
    otra, un `except` escrito de buena fe las juntaría y el audio mudo entraría
    en la cola de reintentos para siempre.
    """
    assert not issubclass(transcribir.NoSeEntendio, transcribir.SinTranscriptor)
    assert not issubclass(transcribir.SinTranscriptor, transcribir.NoSeEntendio)


def test_un_codigo_de_salida_distinto_de_cero_trae_el_stderr_dentro(audio):
    """Lo que falla aquí suele ser un modelo sin descargar o un ffmpeg que no
    está, y esos mensajes traen el remedio dentro. Resumirlos lo quita."""
    ajustes = con_comando(guion(
        'import sys; sys.stderr.write("no encuentro el modelo base"); sys.exit(3)'
    ))
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.transcribir(audio, ajustes)

    assert "no encuentro el modelo base" in str(exc.value)
    assert "3" in str(exc.value)


def test_una_salida_vacia_es_no_haberse_entendido_y_no_un_fallo(audio):
    """Devolver `""` en vez de levantar haría indistinguibles los dos casos
    justo donde hay que distinguirlos: quien llama no sabría si reintentar."""
    ajustes = con_comando(guion('print("   ")'))
    with pytest.raises(transcribir.NoSeEntendio):
        transcribir.transcribir(audio, ajustes)


def test_un_ejecutable_que_no_existe_sale_como_sin_transcriptor(audio):
    """Y no como un `FileNotFoundError` desnudo.

    Quien llama atrapa los dos errores de este módulo; un tercero que se escapa
    tumba la vuelta del relé, y encima con un mensaje que habla de archivos
    —lo que hace pensar en el audio, no en la configuración.
    """
    ajustes = con_comando(["/opt/no-instalado/whisper.sh", "{audio}"])
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.transcribir(audio, ajustes)
    assert "/opt/no-instalado/whisper.sh" in str(exc.value)


def test_una_transcripcion_que_se_eterniza_se_corta_en_vez_de_colgar_el_rele(
    audio, monkeypatch
):
    """El relé es un solo proceso y atiende a todo el mundo.

    Un transcriptor que se queda pensando no deja un encargo sin contestar: los
    deja todos. El tope se baja aquí para no tener que esperar los 300 s reales.
    """
    monkeypatch.setattr(transcribir, "TOPE_SEGUNDOS", 1)
    ajustes = con_comando(guion("import time; time.sleep(30)"))

    with pytest.raises(transcribir.SinTranscriptor, match="se cortó"):
        transcribir.transcribir(audio, ajustes)
