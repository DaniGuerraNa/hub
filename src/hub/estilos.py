"""El catálogo de estilos que se le enseña a quien encarga algo.

🔴 Existe por la regla que gobierna al entrevistador: **quien no tiene
vocabulario técnico no puede describir, pero sí puede elegir.** «¿Qué estilo
quieres?» no tiene respuesta posible para alguien que nunca ha pedido software;
«¿cuál de estos se parece más a lo tuyo?» con doce fotos delante, sí.

Tres decisiones que hacen que la muestra sirva, y las tres se pueden romper sin
que nada falle visiblemente:

1. 🔴 **Todas enseñan LA MISMA pantalla.** Si cada estilo mostrara otro
   contenido, estaría eligiendo contenido y no estilo — y entonces la respuesta
   no dice nada sobre cómo quiere que se vea lo suyo. Por eso hay un solo
   `ESTRUCTURA` y lo único que cambia es el CSS.
2. **Son capturas de páginas de verdad, no paletas ni moodboards.** Tiene que
   poder pensar «lo mío podría verse así». Un rectángulo de colores no permite
   pensar eso.
3. **Los textos son genéricos a propósito** (decisión suya para la v1). Nombrar
   su negocio en la muestra la empujaría a juzgar el contenido.

Los PNG **no viven en el repo**: se generan desde este archivo y se guardan en
`HUB_HOME`. El fuente es el CSS, que se lee y se revisa; una imagen binaria en
git no se puede revisar y engorda para siempre.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import config, mirar


@dataclass(frozen=True)
class Estilo:
    """Un aspecto posible. `nombre` es lo que ella lee, así que va en su idioma
    y sin una sola palabra técnica: nadie elige «alto contraste, tipografía de
    palo seco».

    🔴 `tokens` existe para que AÑADIR UNA PANTALLA no obligue a tocar los doce
    estilos. Lo que es propio de cada pantalla —las casillas de un calendario,
    las cifras de un panel— se escribe una sola vez en `COMUN` contra estas
    variables, y cada estilo las rellena con su paleta. Sin esto, la sexta
    pantalla pedía sesenta bloques de CSS nuevos y el catálogo dejaba de crecer.
    """

    id: str
    nombre: str
    css: str
    # --fondo --sup --texto --tenue --acento --sobre-acento --borde --radio
    tokens: str = ""


@dataclass(frozen=True)
class Pantalla:
    """Una clase de pantalla que un negocio pequeño reconoce como «lo mío».

    🔴 El catálogo de pantallas tiene el invariante AL REVÉS que el de estilos:
    aquí todas se pintan con el MISMO estilo, porque si cada una llevara el
    suyo se estaría comparando el aspecto en vez de lo que la pantalla hace.
    """

    id: str
    nombre: str
    html: str


# Las pantallas. Todas usan el MISMO vocabulario de clases —`.lista`, `.total`,
# `.acciones`— más lo suyo propio, que va en `COMUN` contra los tokens. Así
# añadir una no obliga a tocar los doce estilos.

PANTALLAS: tuple[Pantalla, ...] = (
    Pantalla("movimientos", "Lo que entra y sale en el día", """
  <main>
    <h1>Movimientos de hoy</h1>
    <p class="sub">Lunes · 3 sin cobrar</p>
    <ul class="lista">
      <li><span class="q">2</span><span class="n">Primer artículo</span><span class="p">$ 48.00</span></li>
      <li><span class="q">1</span><span class="n">Segundo artículo</span><span class="p">$ 125.50</span></li>
      <li class="deuda"><span class="q">5</span><span class="n">Tercer artículo</span><span class="p">$ 90.00</span></li>
      <li><span class="q">1</span><span class="n">Cuarto artículo</span><span class="p">$ 17.25</span></li>
      <li><span class="q">3</span><span class="n">Quinto artículo</span><span class="p">$ 64.00</span></li>
      <li class="deuda"><span class="q">1</span><span class="n">Sexto artículo</span><span class="p">$ 31.00</span></li>
      <li><span class="q">2</span><span class="n">Séptimo artículo</span><span class="p">$ 58.50</span></li>
      <li><span class="q">4</span><span class="n">Octavo artículo</span><span class="p">$ 22.00</span></li>
      <li class="deuda"><span class="q">1</span><span class="n">Noveno artículo</span><span class="p">$ 145.00</span></li>
    </ul>
    <div class="total"><span>Total del día</span><b>$ 280.75</b></div>
    <div class="acciones">
      <button class="primario">Agregar</button>
      <button class="secundario">Ver pendientes</button>
    </div>
  </main>
"""),
    Pantalla("calendario", "Un calendario del mes", """
  <main>
    <h1>Septiembre</h1>
    <p class="sub">4 con algo agendado</p>
    <div class="calendario">
      <span class="dow">L</span><span class="dow">M</span><span class="dow">M</span>
      <span class="dow">J</span><span class="dow">V</span><span class="dow">S</span><span class="dow">D</span>
      <span class="dia fuera">31</span><span class="dia">1</span><span class="dia">2</span><span class="dia">3</span>
      <span class="dia marcado">4<i></i></span><span class="dia">5</span><span class="dia">6</span>
      <span class="dia">7</span><span class="dia">8</span><span class="dia marcado">9<i></i></span>
      <span class="dia">10</span><span class="dia">11</span><span class="dia">12</span><span class="dia">13</span>
      <span class="dia">14</span><span class="dia hoy">15</span><span class="dia">16</span>
      <span class="dia">17</span><span class="dia marcado">18<i></i></span><span class="dia">19</span><span class="dia">20</span>
      <span class="dia">21</span><span class="dia">22</span><span class="dia">23</span>
      <span class="dia">24</span><span class="dia marcado">25<i></i></span><span class="dia">26</span><span class="dia">27</span>
      <span class="dia">28</span><span class="dia">29</span><span class="dia">30</span>
      <span class="dia fuera">1</span><span class="dia fuera">2</span><span class="dia fuera">3</span><span class="dia fuera">4</span>
    </div>
    <div class="total"><span>Próximo</span><b>Jueves 18</b></div>
    <div class="acciones">
      <button class="primario">Agendar</button>
      <button class="secundario">Ver semana</button>
    </div>
  </main>
"""),
    Pantalla("clientes", "Una lista de personas", """
  <main>
    <h1>Clientes</h1>
    <p class="sub">28 en total · 3 con saldo</p>
    <ul class="lista fichas">
      <li><span class="ini">RM</span><span class="n">Primera persona<em>Desde marzo</em></span><span class="p">al día</span></li>
      <li class="deuda"><span class="ini">JL</span><span class="n">Segunda persona<em>Desde enero</em></span><span class="p">$ 340.00</span></li>
      <li><span class="ini">AC</span><span class="n">Tercera persona<em>Desde agosto</em></span><span class="p">al día</span></li>
      <li class="deuda"><span class="ini">MT</span><span class="n">Cuarta persona<em>Desde mayo</em></span><span class="p">$ 85.50</span></li>
      <li><span class="ini">PG</span><span class="n">Quinta persona<em>Desde febrero</em></span><span class="p">al día</span></li>
      <li class="deuda"><span class="ini">SV</span><span class="n">Sexta persona<em>Desde julio</em></span><span class="p">$ 120.00</span></li>
      <li><span class="ini">DR</span><span class="n">Séptima persona<em>Desde abril</em></span><span class="p">al día</span></li>
    </ul>
    <div class="total"><span>Por cobrar</span><b>$ 545.50</b></div>
    <div class="acciones">
      <button class="primario">Agregar</button>
      <button class="secundario">Buscar</button>
    </div>
  </main>
"""),
    Pantalla("agenda", "Las horas de un día", """
  <main>
    <h1>Jueves 18</h1>
    <p class="sub">5 citas · una hora libre</p>
    <ul class="lista horas">
      <li><span class="q">09:00</span><span class="n">Primera actividad<em>45 min</em></span><span class="p">4</span></li>
      <li><span class="q">10:00</span><span class="n">Segunda actividad<em>60 min</em></span><span class="p">7</span></li>
      <li class="libre"><span class="q">11:00</span><span class="n">Libre</span><span class="p">—</span></li>
      <li><span class="q">12:00</span><span class="n">Tercera actividad<em>90 min</em></span><span class="p">12</span></li>
      <li><span class="q">16:00</span><span class="n">Cuarta actividad<em>45 min</em></span><span class="p">5</span></li>
      <li class="deuda"><span class="q">18:00</span><span class="n">Quinta actividad<em>60 min</em></span><span class="p">3</span></li>
    </ul>
    <div class="total"><span>Personas hoy</span><b>31</b></div>
    <div class="acciones">
      <button class="primario">Agendar</button>
      <button class="secundario">Ver mes</button>
    </div>
  </main>
"""),
    Pantalla("inventario", "Lo que hay y lo que falta", """
  <main>
    <h1>Existencias</h1>
    <p class="sub">3 por reponer</p>
    <ul class="lista">
      <li><span class="q">48</span><span class="n">Primer artículo</span><span class="p">bien</span></li>
      <li class="deuda"><span class="q">2</span><span class="n">Segundo artículo</span><span class="p">reponer</span></li>
      <li><span class="q">130</span><span class="n">Tercer artículo</span><span class="p">bien</span></li>
      <li class="deuda"><span class="q">0</span><span class="n">Cuarto artículo</span><span class="p">agotado</span></li>
      <li><span class="q">27</span><span class="n">Quinto artículo</span><span class="p">bien</span></li>
      <li class="deuda"><span class="q">4</span><span class="n">Sexto artículo</span><span class="p">reponer</span></li>
      <li><span class="q">61</span><span class="n">Séptimo artículo</span><span class="p">bien</span></li>
      <li><span class="q">15</span><span class="n">Octavo artículo</span><span class="p">bien</span></li>
    </ul>
    <div class="total"><span>Valor estimado</span><b>$ 12,430</b></div>
    <div class="acciones">
      <button class="primario">Registrar entrada</button>
      <button class="secundario">Ver faltantes</button>
    </div>
  </main>
"""),
    Pantalla("panel", "Un resumen de cómo va", """
  <main>
    <h1>Cómo va el mes</h1>
    <p class="sub">Del 1 al 17 de septiembre</p>
    <div class="cifras">
      <div class="cifra"><span>Ventas</span><b>$ 48,200</b><i>+12%</i></div>
      <div class="cifra"><span>Por cobrar</span><b>$ 3,140</b><i>6 personas</i></div>
      <div class="cifra"><span>Movimientos</span><b>284</b><i>17 al día</i></div>
      <div class="cifra"><span>Sin existencia</span><b>3</b><i>de 96</i></div>
    </div>
    <div class="barras">
      <span style="height:38%"></span><span style="height:55%"></span><span style="height:30%"></span>
      <span style="height:72%"></span><span style="height:61%"></span><span style="height:88%"></span>
      <span style="height:44%"></span><span style="height:67%"></span><span style="height:52%"></span>
      <span style="height:79%"></span><span style="height:35%"></span><span style="height:93%"></span>
    </div>
    <div class="total"><span>Mejor día</span><b>Sábado 13</b></div>
    <div class="acciones">
      <button class="primario">Ver detalle</button>
      <button class="secundario">Exportar</button>
    </div>
  </main>
"""),
    # Las cinco siguientes no son otra lista con otros datos: cada una es una
    # FORMA distinta —capturar, entregar, consultar, ojear, repartir horas— y
    # ésa es la pregunta que contesta este catálogo. Una séptima lista con otro
    # título habría sido una opción de menos disfrazada de una más.
    Pantalla("formulario", "Dar de alta algo nuevo", """
  <main>
    <h1>Nuevo registro</h1>
    <p class="sub">Lo que lleva * no se puede dejar vacío</p>
    <div class="campos">
      <label><span class="et">Nombre *</span><span class="campo">Primer artículo</span></label>
      <label><span class="et">Precio *</span><span class="campo">$ 48.00</span></label>
      <label><span class="et">Cantidad</span><span class="campo">12</span></label>
      <label><span class="et">Unidad</span><span class="campo">Pieza</span></label>
      <label><span class="et">Grupo</span><span class="campo pendiente">Sin grupo</span></label>
      <label><span class="et">Código</span><span class="campo pendiente">Opcional</span></label>
      <label><span class="et">Mínimo</span><span class="campo">5</span></label>
      <label><span class="et">Proveedor</span><span class="campo pendiente">Sin asignar</span></label>
      <label class="ancho"><span class="et">Nota</span><span class="campo area">Se entrega los martes por la mañana</span></label>
      <label class="ancho opcion"><span class="casilla"></span>Avisar cuando queden menos del mínimo</label>
    </div>
    <div class="total"><span>Se guarda en</span><b>Existencias</b></div>
    <div class="acciones">
      <button class="primario">Guardar</button>
      <button class="secundario">Cancelar</button>
    </div>
  </main>
"""),
    Pantalla("ficha", "Todo lo de una persona", """
  <main>
    <h1>Cuarta persona</h1>
    <p class="sub">Desde mayo · 14 visitas</p>
    <div class="ficha">
      <div class="ficha-cab">
        <span class="ini grande">MT</span>
        <div class="datos">
          <div><span>Teléfono</span><b>555 000 0000</b></div>
          <div><span>Correo</span><b>correo@ejemplo.com</b></div>
          <div><span>Dónde</span><b>Calle Segunda 123</b></div>
          <div><span>Última visita</span><b>Hace 3 días</b></div>
        </div>
      </div>
      <h2 class="apartado">Últimos movimientos</h2>
      <ul class="historial">
        <li><span class="q">12 sep</span><span class="n">Primer concepto</span><span class="p">$ 145.00</span></li>
        <li><span class="q">04 sep</span><span class="n">Segundo concepto</span><span class="p">$ 62.00</span></li>
        <li class="deuda"><span class="q">28 ago</span><span class="n">Tercer concepto</span><span class="p">$ 85.50</span></li>
        <li><span class="q">19 ago</span><span class="n">Cuarto concepto</span><span class="p">$ 210.00</span></li>
        <li><span class="q">02 ago</span><span class="n">Quinto concepto</span><span class="p">$ 38.00</span></li>
        <li><span class="q">27 jul</span><span class="n">Sexto concepto</span><span class="p">$ 96.00</span></li>
        <li><span class="q">15 jul</span><span class="n">Séptimo concepto</span><span class="p">$ 54.50</span></li>
        <li><span class="q">03 jul</span><span class="n">Octavo concepto</span><span class="p">$ 128.00</span></li>
      </ul>
    </div>
    <div class="total"><span>Saldo</span><b>$ 85.50</b></div>
    <div class="acciones">
      <button class="primario">Registrar cobro</button>
      <button class="secundario">Editar datos</button>
    </div>
  </main>
"""),
    # Las cifras cuadran a propósito (294.75 − 12 = 282.75, y de $300 sobran
    # 17.25). Un comprobante de muestra cuyas sumas no salen lo nota justo quien
    # se pasa el día cuadrando la caja, y a partir de ahí desconfía de todo.
    Pantalla("comprobante", "Un comprobante para entregar", """
  <main>
    <h1>Comprobante</h1>
    <p class="sub">Folio 001284 · 18 de septiembre, 13:40</p>
    <div class="ticket">
      <div class="ticket-cab"><b>Tu negocio</b><em>Mostrador 1</em></div>
      <ul class="renglones">
        <li><span class="q">2</span><span class="n">Primer artículo<em>$ 24.00 c/u</em></span><span class="p">$ 48.00</span></li>
        <li><span class="q">1</span><span class="n">Segundo artículo<em>$ 125.50 c/u</em></span><span class="p">$ 125.50</span></li>
        <li><span class="q">3</span><span class="n">Tercer artículo<em>$ 18.00 c/u</em></span><span class="p">$ 54.00</span></li>
        <li><span class="q">1</span><span class="n">Cuarto artículo<em>$ 17.25 c/u</em></span><span class="p">$ 17.25</span></li>
        <li><span class="q">2</span><span class="n">Quinto artículo<em>$ 9.50 c/u</em></span><span class="p">$ 19.00</span></li>
        <li><span class="q">1</span><span class="n">Sexto artículo<em>$ 31.00 c/u</em></span><span class="p">$ 31.00</span></li>
      </ul>
      <div class="sumas">
        <div><span>Suma</span><b>$ 294.75</b></div>
        <div><span>Descuento</span><b>− $ 12.00</b></div>
        <div class="cobrado"><span>Total</span><b>$ 282.75</b></div>
      </div>
      <p class="sello">Gracias por su compra</p>
    </div>
    <div class="total"><span>Pagó con</span><b>Efectivo · cambio $ 17.25</b></div>
    <div class="acciones">
      <button class="primario">Imprimir</button>
      <button class="secundario">Enviar copia</button>
    </div>
  </main>
"""),
    Pantalla("cuadricula", "Los artículos con su foto", """
  <main>
    <h1>Artículos</h1>
    <p class="sub">96 en total · 2 sin existencia</p>
    <div class="mosaico">
      <div class="pieza"><span class="miniatura">A</span><b>Primer artículo</b><span class="precio">$ 48.00</span></div>
      <div class="pieza"><span class="miniatura">B</span><b>Segundo artículo</b><span class="precio">$ 125.50</span></div>
      <div class="pieza"><span class="miniatura">C</span><b>Tercer artículo</b><span class="precio">$ 18.00</span></div>
      <div class="pieza agotado"><span class="miniatura">D</span><b>Cuarto artículo</b><span class="precio">Sin existencia</span></div>
      <div class="pieza"><span class="miniatura">E</span><b>Quinto artículo</b><span class="precio">$ 9.50</span></div>
      <div class="pieza"><span class="miniatura">F</span><b>Sexto artículo</b><span class="precio">$ 64.00</span></div>
      <div class="pieza"><span class="miniatura">G</span><b>Séptimo artículo</b><span class="precio">$ 31.00</span></div>
      <div class="pieza agotado"><span class="miniatura">H</span><b>Octavo artículo</b><span class="precio">Sin existencia</span></div>
      <div class="pieza"><span class="miniatura">I</span><b>Noveno artículo</b><span class="precio">$ 22.00</span></div>
    </div>
    <div class="total"><span>Mostrando</span><b>9 de 96</b></div>
    <div class="acciones">
      <button class="primario">Agregar</button>
      <button class="secundario">Buscar</button>
    </div>
  </main>
"""),
    Pantalla("horario", "La semana entera, por salas", """
  <main>
    <h1>Semana del 15</h1>
    <p class="sub">3 salas · 20 horas ocupadas</p>
    <div class="parrilla">
      <span class="dow"></span><span class="dow">Lun</span><span class="dow">Mar</span>
      <span class="dow">Mié</span><span class="dow">Jue</span><span class="dow">Vie</span>
      <span class="hora">09:00</span>
      <span class="bloque">Grupo A<em>Sala 1</em></span><span class="hueco"></span>
      <span class="bloque">Grupo A<em>Sala 1</em></span><span class="hueco"></span>
      <span class="bloque">Grupo A<em>Sala 1</em></span>
      <span class="hora">10:00</span>
      <span class="bloque lleno">Grupo B<em>Sala 2 · lleno</em></span>
      <span class="bloque">Grupo B<em>Sala 2</em></span><span class="hueco"></span>
      <span class="bloque">Grupo B<em>Sala 2</em></span><span class="hueco"></span>
      <span class="hora">11:00</span>
      <span class="hueco"></span><span class="bloque">Grupo C<em>Sala 1</em></span>
      <span class="bloque">Grupo C<em>Sala 1</em></span><span class="hueco"></span>
      <span class="bloque">Grupo C<em>Sala 1</em></span>
      <span class="hora">12:00</span>
      <span class="bloque">Grupo D<em>Sala 1</em></span><span class="hueco"></span>
      <span class="hueco"></span><span class="bloque">Grupo D<em>Sala 1</em></span>
      <span class="hueco"></span>
      <span class="hora">16:00</span>
      <span class="bloque lleno">Grupo E<em>Sala 2 · lleno</em></span>
      <span class="bloque">Grupo E<em>Sala 2</em></span>
      <span class="bloque lleno">Grupo E<em>Sala 2 · lleno</em></span>
      <span class="bloque">Grupo E<em>Sala 2</em></span>
      <span class="bloque">Grupo E<em>Sala 2</em></span>
      <span class="hora">17:00</span>
      <span class="hueco"></span><span class="bloque">Grupo F<em>Sala 1</em></span>
      <span class="hueco"></span><span class="bloque">Grupo F<em>Sala 1</em></span>
      <span class="hueco"></span>
      <span class="hora">18:00</span>
      <span class="bloque">Grupo G<em>Sala 3</em></span><span class="hueco"></span>
      <span class="bloque">Grupo G<em>Sala 3</em></span><span class="hueco"></span>
      <span class="hueco"></span>
    </div>
    <div class="total"><span>Sala más ocupada</span><b>Sala 1</b></div>
    <div class="acciones">
      <button class="primario">Agendar</button>
      <button class="secundario">Ver día</button>
    </div>
  </main>
"""),
)

PANTALLA_POR_ID = {p.id: p for p in PANTALLAS}

# La que se usa para enseñar ESTILOS: siempre la misma, o se compararía el
# contenido. Y el estilo con el que se enseñan las PANTALLAS: siempre el mismo,
# por lo mismo al revés.
PANTALLA_DE_REFERENCIA = "movimientos"
ESTILO_DE_REFERENCIA = "claro"

# La cabecera es igual en todas las pantallas: es lo que hace que dos capturas
# del mismo estilo se reconozcan como el mismo producto.
ENVOLTORIO = """
<div class="hoja">
  <header>
    <div class="marca">Tu negocio</div>
    <nav><a>Hoy</a><a>Historial</a><a>Ajustes</a></nav>
  </header>
  {pantalla}
</div>
"""

# Base mínima común: lo que hace la captura comparable entre estilos, más lo
# propio de cada pantalla escrito UNA vez contra los tokens. Ahí está el truco
# que permite que el catálogo crezca: una pantalla nueva se escribe aquí y
# funciona en los doce estilos sin tocar ninguno.
COMUN = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { width: 720px; height: 1000px; overflow: hidden; }
  .hoja { width: 100%; height: 100%; display: flex; flex-direction: column; }
  header { display: flex; align-items: center; justify-content: space-between; }
  nav { display: flex; }
  main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
  .lista { list-style: none; }
  .lista li { display: grid; grid-template-columns: 44px 1fr auto; align-items: center; }
  /* 🔴 `flex:1` + `min-height:0` + `overflow:hidden`: el cuerpo absorbe el aire
     que sobra Y cede el que falta. Sin lo segundo, un estilo de letra grande
     empuja el total y los botones fuera del marco — y un botón cortado no se
     lee como un estilo, se lee como algo roto. Se vio en «papel». */
  .lista, .calendario, .barras, .campos, .ticket, .renglones, .ficha, .historial, .mosaico, .parrilla { flex: 1; min-height: 0; overflow: hidden; }
  .total { display: flex; align-items: center; justify-content: space-between; }
  .acciones { display: flex; }
  button { border: 0; font: inherit; cursor: pointer; }

  /* ── lo propio de cada pantalla, contra los tokens del estilo ──────────── */

  /* Las filas se reparten el alto en vez de apilarse arriba: si no, el
     calendario deja un tercio en blanco bajo la última semana — el mismo
     desperdicio de foto que ya se corrigió en la lista, otra vez. */
  .calendario { display: grid; grid-template-columns: repeat(7, 1fr);
                grid-template-rows: auto repeat(6, 1fr);
                gap: 6px; margin-top: 20px; }
  .dow { text-align: center; font-size: 12px; color: var(--tenue); padding-bottom: 4px; }
  .dia { position: relative; display: flex; align-items: center; justify-content: center;
         min-height: 0; font-size: 17px; background: var(--sup);
         border: 1px solid var(--borde); border-radius: var(--radio); }
  .dia.fuera { opacity: .25; }
  .dia.hoy { border: 2px solid var(--acento); font-weight: 700; }
  .dia.marcado { background: var(--acento); color: var(--sobre-acento); border-color: var(--acento); }
  .dia i { position: absolute; bottom: 7px; width: 6px; height: 6px;
           border-radius: 50%; background: var(--sobre-acento); }

  .lista.fichas li { grid-template-columns: 56px 1fr auto; }
  .ini { display: flex; align-items: center; justify-content: center;
         width: 40px; height: 40px; border-radius: 50%; font-size: 14px;
         background: var(--acento); color: var(--sobre-acento); }
  .n em { display: block; font-size: 12px; font-style: normal;
          color: var(--tenue); margin-top: 2px; }
  .lista.horas li.libre { opacity: .45; }

  .cifras { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 22px; }
  .cifra { padding: 18px; background: var(--sup);
           border: 1px solid var(--borde); border-radius: var(--radio); }
  .cifra span { display: block; font-size: 13px; color: var(--tenue); }
  .cifra b { display: block; font-size: 28px; margin: 6px 0 2px; }
  .cifra i { font-size: 12px; font-style: normal; color: var(--acento); }
  .barras { display: flex; align-items: flex-end; gap: 8px; margin-top: 18px; }
  .barras span { flex: 1; background: var(--acento); min-height: 4px;
                 border-radius: var(--radio) var(--radio) 0 0; }

  /* El formulario reparte el aire sobrante entre las filas en vez de dejarlo
     todo abajo, por lo mismo que el calendario: media foto vacía no se lee como
     una pantalla de verdad. Y al revés, cuando la letra es grande las filas se
     juntan hasta el hueco mínimo antes de empujar nada fuera del marco. */
  .campos { display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
            align-content: space-between; margin-top: 24px; }
  .et { display: block; font-size: 13px; color: var(--tenue); margin-bottom: 7px; }
  .campo { display: block; padding: 15px 14px; font-size: 16px; background: var(--sup);
           border: 1px solid var(--borde); border-radius: var(--radio); }
  .campo.pendiente { color: var(--tenue); }
  .campo.area { min-height: 92px; }
  .ancho { grid-column: 1 / -1; }
  .opcion { display: flex; align-items: center; font-size: 15px; }
  /* La palomita se dibuja con dos bordes girados y no con un carácter: escrita
     como glifo sale de otro tamaño en «papel» o en «retro», que son los estilos
     con fuente propia — y ahí una casilla marcada deja de parecerlo. */
  .casilla { position: relative; flex: none; width: 20px; height: 20px;
             margin-right: 11px; background: var(--acento);
             border: 1px solid var(--acento); border-radius: 4px; }
  .casilla::after { content: ''; position: absolute; left: 6px; top: 2px;
                    width: 5px; height: 10px; transform: rotate(45deg);
                    border: solid var(--sobre-acento); border-width: 0 2px 2px 0; }

  /* El comprobante es un documento dentro de la pantalla, no una lista más: por
     eso tiene marco propio y sus renglones NO reusan `.lista`. En los estilos
     que pintan la lista como tarjetas sueltas, un ticket de tarjetas apiladas
     deja de parecer un ticket. */
  .ticket { display: flex; flex-direction: column; margin-top: 22px; padding: 22px 24px;
            background: var(--sup); border: 1px solid var(--borde);
            border-radius: var(--radio); }
  .ticket-cab { display: flex; align-items: baseline; justify-content: space-between;
                padding-bottom: 14px; border-bottom: 1px solid var(--borde); }
  .ticket-cab em { font-style: normal; font-size: 13px; color: var(--tenue); }
  .renglones { list-style: none; padding-top: 6px; }
  .renglones li { display: grid; grid-template-columns: 34px 1fr auto;
                  align-items: center; padding: 11px 0; font-size: 15px; }
  .sumas { padding-top: 12px; border-top: 1px solid var(--borde); }
  .sumas div { display: flex; justify-content: space-between;
               padding: 5px 0; font-size: 15px; color: var(--tenue); }
  .sumas .cobrado { margin-top: 8px; padding-top: 12px; color: var(--texto);
                    border-top: 1px solid var(--borde); }
  .sumas .cobrado b { font-size: 24px; }
  .sello { margin-top: 14px; padding-top: 14px; text-align: center; font-size: 13px;
           color: var(--tenue); border-top: 1px dashed var(--borde); }

  .ficha { display: flex; flex-direction: column; margin-top: 22px; }
  .ficha-cab { display: flex; gap: 20px; padding: 20px; background: var(--sup);
               border: 1px solid var(--borde); border-radius: var(--radio); }
  .ini.grande { width: 72px; height: 72px; font-size: 26px; flex: none; }
  .datos { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 18px; flex: 1; }
  .datos span { display: block; font-size: 12px; color: var(--tenue); }
  .datos b { font-size: 15px; }
  .apartado { font-size: 15px; margin: 24px 0 2px; }
  .historial { list-style: none; }
  .historial li { display: grid; grid-template-columns: 78px 1fr auto; align-items: center;
                  padding: 16px 2px; font-size: 15px; border-bottom: 1px solid var(--borde); }

  .mosaico { display: grid; grid-template-columns: repeat(3, 1fr); grid-auto-rows: 1fr;
             gap: 12px; margin-top: 22px; }
  /* La tarjeta va del color del lienzo y el hueco de la foto del de las
     superficies, y no al revés: con las dos del mismo tono la cuadrícula se ve
     como una pantalla a medio cargar en vez de como un catálogo. */
  .pieza { display: flex; flex-direction: column; min-height: 0; overflow: hidden;
           padding: 14px; background: var(--fondo); border: 1px solid var(--borde);
           border-radius: var(--radio); }
  /* El hueco de la foto va marcado con la inicial y un trazo discontinuo: la
     muestra se genera sin conexión y no puede traer imágenes, y un recuadro
     liso se lee como algo que falta en vez de como una foto por poner. */
  .miniatura { flex: 1; min-height: 40px; display: flex; align-items: center;
               justify-content: center; margin-bottom: 11px; font-size: 30px;
               color: var(--tenue); background: var(--sup);
               border: 1px dashed var(--borde); border-radius: var(--radio); }
  .pieza b { font-size: 15px; }
  .precio { font-size: 14px; margin-top: 3px; }
  .pieza.agotado { opacity: .55; }

  .parrilla { display: grid; grid-template-columns: 52px repeat(5, 1fr);
              grid-template-rows: auto repeat(7, 1fr); gap: 6px; margin-top: 20px; }
  .hora { display: flex; align-items: center; font-size: 12px; color: var(--tenue); }
  /* Sólo lo lleno se pinta con el acento. Con las treinta y cinco casillas del
     mismo color la parrilla se lee como una mancha y deja de verse lo único que
     se mira aquí: qué hueco queda libre. */
  .bloque { display: flex; flex-direction: column; justify-content: center;
            min-height: 0; overflow: hidden; padding: 6px 9px; font-size: 13px;
            background: var(--sup); border: 1px solid var(--borde);
            border-left: 4px solid var(--acento); border-radius: var(--radio); }
  .bloque em { display: block; font-style: normal; font-size: 11px; color: var(--tenue); }
  .bloque.lleno { background: var(--acento); color: var(--sobre-acento);
                  border-color: var(--acento); }
  .bloque.lleno em { color: var(--sobre-acento); opacity: .8; }
  .hueco { border: 1px dashed var(--borde); border-radius: var(--radio); opacity: .7; }
"""


ESTILOS: tuple[Estilo, ...] = (
    Estilo("claro", "Claro y sencillo", """
  body { background:#fff; color:#1c1c1e; font-family:'Helvetica Neue',Arial,sans-serif; }
  .hoja { padding:38px 42px; }
  header { padding-bottom:22px; border-bottom:1px solid #ececec; }
  .marca { font-size:17px; font-weight:600; letter-spacing:-.2px; }
  nav { gap:22px; font-size:14px; color:#8e8e93; }
  main { padding-top:34px; }
  h1 { font-size:34px; font-weight:600; letter-spacing:-.8px; }
  .sub { color:#8e8e93; font-size:15px; margin-top:6px; }
  .lista { margin-top:30px; }
  .lista li { padding:17px 0; border-bottom:1px solid #f2f2f2; font-size:16px; }
  .q { color:#c7c7cc; font-variant-numeric:tabular-nums; }
  .p { font-variant-numeric:tabular-nums; }
  .deuda .n::after { content:' · sin cobrar'; color:#ff9500; font-size:13px; }
  .total { margin-top:30px; font-size:17px; } .total b { font-size:26px; }
  .acciones { gap:12px; margin-top:34px; }
  button { padding:15px 26px; border-radius:10px; font-size:15px; font-weight:500; }
  .primario { background:#1c1c1e; color:#fff; }
  .secundario { background:#f2f2f7; color:#1c1c1e; }
""", tokens="--fondo:#fff;--sup:#f7f7f9;--texto:#1c1c1e;--tenue:#8e8e93;--acento:#1c1c1e;--sobre-acento:#fff;--borde:#ececec;--radio:10px;"),
    Estilo("calido", "Cálido, como una tienda de barrio", """
  body { background:#fdf6ec; color:#43301f; font-family:Georgia,'Times New Roman',serif; }
  .hoja { padding:40px 44px; }
  header { padding-bottom:20px; border-bottom:2px solid #e7d3b8; }
  .marca { font-size:20px; font-weight:700; color:#a84b21; }
  nav { gap:20px; font-size:14px; color:#9c7b56; }
  main { padding-top:32px; }
  h1 { font-size:36px; color:#5c3a1e; }
  .sub { color:#9c7b56; font-size:16px; margin-top:8px; font-style:italic; }
  .lista { margin-top:28px; }
  .lista li { padding:18px 20px; margin-bottom:10px; background:#fffdf8;
              border:1px solid #efe0cb; border-radius:14px; font-size:17px; }
  .q { color:#c39a6b; font-weight:700; }
  .deuda { border-color:#e0a96d; background:#fdf1e0; }
  .total { margin-top:26px; padding:20px 22px; background:#a84b21; color:#fff; border-radius:14px; }
  .total b { font-size:28px; }
  .acciones { gap:12px; margin-top:30px; }
  button { padding:16px 30px; border-radius:999px; font-size:16px; }
  .primario { background:#a84b21; color:#fff; }
  .secundario { background:transparent; color:#a84b21; border:2px solid #dcc09a; }
""", tokens="--fondo:#fdf6ec;--sup:#fffdf8;--texto:#43301f;--tenue:#9c7b56;--acento:#a84b21;--sobre-acento:#fff;--borde:#efe0cb;--radio:14px;"),
    Estilo("nocturno", "Oscuro", """
  body { background:#0f1115; color:#e6e8ec; font-family:'Segoe UI',Roboto,sans-serif; }
  .hoja { padding:38px 42px; }
  header { padding-bottom:22px; border-bottom:1px solid #22262e; }
  .marca { font-size:17px; font-weight:600; }
  nav { gap:22px; font-size:14px; color:#6b7280; }
  main { padding-top:34px; }
  h1 { font-size:33px; font-weight:600; }
  .sub { color:#6b7280; font-size:15px; margin-top:6px; }
  .lista { margin-top:28px; }
  .lista li { padding:17px 18px; margin-bottom:8px; background:#161a21;
              border:1px solid #22262e; border-radius:12px; font-size:16px; }
  .q { color:#4b5563; } .p { color:#8ab4f8; font-variant-numeric:tabular-nums; }
  .deuda { border-color:#4a3a1a; } .deuda .p { color:#f0b429; }
  .total { margin-top:26px; padding:20px; background:#161a21; border-radius:12px; font-size:16px; }
  .total b { font-size:27px; color:#8ab4f8; }
  .acciones { gap:12px; margin-top:32px; }
  button { padding:15px 28px; border-radius:10px; font-size:15px; }
  .primario { background:#3b82f6; color:#fff; }
  .secundario { background:#1c2129; color:#c3c7cf; }
""", tokens="--fondo:#0f1115;--sup:#161a21;--texto:#e6e8ec;--tenue:#6b7280;--acento:#3b82f6;--sobre-acento:#fff;--borde:#22262e;--radio:12px;"),
    Estilo("vivo", "Con mucho color", """
  body { background:#fff; color:#111; font-family:'Arial Black',Impact,sans-serif; }
  .hoja { padding:0; }
  header { padding:26px 36px; background:#ff3b30; color:#fff; }
  .marca { font-size:20px; letter-spacing:-.5px; }
  nav { gap:18px; font-size:13px; font-family:Arial,sans-serif; }
  main { padding:34px 36px; }
  h1 { font-size:46px; line-height:.95; letter-spacing:-1.5px; }
  .sub { font-family:Arial,sans-serif; font-weight:400; color:#666; font-size:16px; margin-top:12px; }
  .lista { margin-top:28px; }
  .lista li { padding:18px; margin-bottom:8px; background:#ffe600; font-size:17px;
              font-family:Arial,sans-serif; font-weight:700; }
  .lista li:nth-child(even) { background:#00d2a0; }
  .q { font-size:20px; }
  .deuda { background:#7c4dff !important; color:#fff; }
  .total { margin-top:26px; padding:24px; background:#111; color:#ffe600; }
  .total b { font-size:32px; }
  .acciones { gap:10px; margin-top:28px; }
  button { padding:18px 30px; font-size:16px; }
  .primario { background:#ff3b30; color:#fff; }
  .secundario { background:#111; color:#fff; }
""", tokens="--fondo:#fff;--sup:#ffe600;--texto:#111;--tenue:#666;--acento:#ff3b30;--sobre-acento:#fff;--borde:#111;--radio:0;"),
    Estilo("serio", "Formal y ordenado", """
  body { background:#f7f8fa; color:#1a2332; font-family:Georgia,serif; }
  .hoja { padding:36px 40px; }
  header { padding-bottom:18px; border-bottom:3px double #c9d2de; }
  .marca { font-size:19px; font-weight:700; color:#12315b; letter-spacing:.3px; }
  nav { gap:20px; font-size:13px; color:#5a6b80; font-family:Arial,sans-serif; text-transform:uppercase; letter-spacing:.06em; }
  main { padding-top:30px; }
  h1 { font-size:30px; color:#12315b; }
  .sub { color:#5a6b80; font-size:14px; margin-top:8px; font-family:Arial,sans-serif; }
  .lista { margin-top:24px; background:#fff; border:1px solid #d6dde6; }
  .lista li { padding:16px 20px; border-bottom:1px solid #eef1f5; font-size:15px; font-family:Arial,sans-serif; }
  .q { color:#8794a5; font-variant-numeric:tabular-nums; }
  .p { font-variant-numeric:tabular-nums; font-weight:600; }
  .deuda { background:#fdf8ec; }
  .total { margin-top:22px; padding:18px 20px; background:#12315b; color:#fff; font-family:Arial,sans-serif; }
  .total b { font-size:24px; }
  .acciones { gap:10px; margin-top:26px; }
  button { padding:13px 26px; font-size:14px; font-family:Arial,sans-serif; border-radius:3px; }
  .primario { background:#12315b; color:#fff; }
  .secundario { background:#fff; color:#12315b; border:1px solid #c9d2de; }
""", tokens="--fondo:#f7f8fa;--sup:#fff;--texto:#1a2332;--tenue:#5a6b80;--acento:#12315b;--sobre-acento:#fff;--borde:#d6dde6;--radio:3px;"),
    Estilo("natural", "Verde y natural", """
  body { background:#f4f7f0; color:#23331f; font-family:'Trebuchet MS',sans-serif; }
  .hoja { padding:40px 44px; }
  header { padding-bottom:20px; }
  .marca { font-size:19px; font-weight:600; color:#3f7c3a; }
  nav { gap:20px; font-size:14px; color:#7d9276; }
  main { padding-top:26px; }
  h1 { font-size:34px; color:#2c5a28; }
  .sub { color:#7d9276; font-size:15px; margin-top:8px; }
  .lista { margin-top:28px; }
  .lista li { padding:18px 20px; margin-bottom:9px; background:#fff;
              border-left:5px solid #7cb342; border-radius:0 12px 12px 0; font-size:16px; }
  .q { color:#9bb094; }
  .deuda { border-left-color:#e8a33d; }
  .total { margin-top:26px; padding:20px 22px; background:#3f7c3a; color:#fff; border-radius:14px; }
  .total b { font-size:27px; }
  .acciones { gap:12px; margin-top:30px; }
  button { padding:15px 28px; border-radius:999px; font-size:15px; }
  .primario { background:#7cb342; color:#fff; }
  .secundario { background:#e6eee2; color:#3f7c3a; }
""", tokens="--fondo:#f4f7f0;--sup:#fff;--texto:#23331f;--tenue:#7d9276;--acento:#3f7c3a;--sobre-acento:#fff;--borde:#dfe8da;--radio:12px;"),
    Estilo("suave", "Suave y amable", """
  body { background:#fbf7ff; color:#3a3350; font-family:'Segoe UI',Verdana,sans-serif; }
  .hoja { padding:40px 44px; }
  header { padding-bottom:22px; }
  .marca { font-size:19px; font-weight:600; color:#7a63c7; }
  nav { gap:20px; font-size:14px; color:#a99ec9; }
  main { padding-top:26px; }
  h1 { font-size:34px; font-weight:600; }
  .sub { color:#a99ec9; font-size:15px; margin-top:8px; }
  .lista { margin-top:28px; }
  .lista li { padding:19px 22px; margin-bottom:10px; background:#fff; border-radius:20px; font-size:16px; }
  .q { color:#c9c0e0; }
  .deuda { background:#fff2f6; }
  .total { margin-top:26px; padding:22px; background:#efe8ff; border-radius:20px; font-size:16px; }
  .total b { font-size:28px; color:#7a63c7; }
  .acciones { gap:12px; margin-top:30px; }
  button { padding:16px 30px; border-radius:20px; font-size:15px; }
  .primario { background:#7a63c7; color:#fff; }
  .secundario { background:#fff; color:#7a63c7; }
""", tokens="--fondo:#fbf7ff;--sup:#fff;--texto:#3a3350;--tenue:#a99ec9;--acento:#7a63c7;--sobre-acento:#fff;--borde:#ece5fa;--radio:20px;"),
    Estilo("retro", "Con aire de antes", """
  body { background:#f3e9d2; color:#3c2f22; font-family:'Courier New',monospace; }
  .hoja { padding:36px 40px; }
  header { padding-bottom:16px; border-bottom:3px solid #3c2f22; }
  .marca { font-size:20px; font-weight:700; text-transform:uppercase; letter-spacing:2px; }
  nav { gap:16px; font-size:13px; text-transform:uppercase; }
  main { padding-top:28px; }
  h1 { font-size:32px; text-transform:uppercase; letter-spacing:-.5px; }
  .sub { font-size:15px; margin-top:8px; }
  .lista { margin-top:26px; border:3px solid #3c2f22; }
  .lista li { padding:15px 18px; border-bottom:1px dashed #a89574; font-size:15px; }
  .q { font-weight:700; }
  .deuda { background:#e0793b; color:#fff; }
  .total { margin-top:22px; padding:18px; border:3px solid #3c2f22; background:#d9534f; color:#fff; }
  .total b { font-size:26px; }
  .acciones { gap:10px; margin-top:26px; }
  button { padding:14px 26px; font-size:14px; text-transform:uppercase;
           border:3px solid #3c2f22; font-family:inherit; font-weight:700; }
  .primario { background:#e0793b; color:#fff; }
  .secundario { background:#f3e9d2; color:#3c2f22; }
""", tokens="--fondo:#f3e9d2;--sup:#f3e9d2;--texto:#3c2f22;--tenue:#a89574;--acento:#e0793b;--sobre-acento:#fff;--borde:#3c2f22;--radio:0;"),
    Estilo("tecnico", "De aspecto técnico", """
  body { background:#0d0f12; color:#d4d8dd; font-family:'SF Mono',Consolas,monospace; }
  .hoja { padding:32px 36px; }
  header { padding-bottom:16px; border-bottom:1px solid #1e2228; }
  .marca { font-size:15px; color:#00e39a; }
  .marca::before { content:'$ '; color:#4a5058; }
  nav { gap:18px; font-size:13px; color:#4a5058; }
  main { padding-top:28px; }
  h1 { font-size:26px; font-weight:500; letter-spacing:-.3px; }
  .sub { color:#4a5058; font-size:14px; margin-top:8px; }
  .lista { margin-top:26px; border:1px solid #1e2228; }
  .lista li { padding:14px 16px; border-bottom:1px solid #15181d; font-size:14px; }
  .q { color:#4a5058; } .p { color:#00e39a; }
  .deuda .p { color:#ffb020; }
  .total { margin-top:22px; padding:16px; border:1px solid #00e39a; font-size:14px; }
  .total b { font-size:24px; color:#00e39a; }
  .acciones { gap:10px; margin-top:26px; }
  button { padding:13px 24px; font-size:13px; font-family:inherit; border:1px solid #2a3038; }
  .primario { background:#00e39a; color:#0d0f12; border-color:#00e39a; }
  .secundario { background:transparent; color:#d4d8dd; }
""", tokens="--fondo:#0d0f12;--sup:#12151a;--texto:#d4d8dd;--tenue:#4a5058;--acento:#00e39a;--sobre-acento:#0d0f12;--borde:#1e2228;--radio:0;"),
    Estilo("elegante", "Elegante", """
  body { background:#12100e; color:#efe8dd; font-family:'Didot',Garamond,Georgia,serif; }
  .hoja { padding:46px 50px; }
  header { padding-bottom:26px; border-bottom:1px solid #3a332b; }
  .marca { font-size:18px; letter-spacing:5px; text-transform:uppercase; color:#c9a227; }
  nav { gap:24px; font-size:12px; letter-spacing:2px; text-transform:uppercase; color:#8a8078; }
  main { padding-top:40px; }
  h1 { font-size:42px; font-weight:400; letter-spacing:-.5px; }
  .sub { color:#8a8078; font-size:14px; margin-top:12px; letter-spacing:2px; text-transform:uppercase; }
  .lista { margin-top:34px; }
  .lista li { padding:20px 0; border-bottom:1px solid #26221d; font-size:17px; }
  .q { color:#6b6259; } .p { color:#c9a227; }
  .deuda .n { font-style:italic; }
  .total { margin-top:30px; padding-top:24px; border-top:1px solid #c9a227; font-size:14px;
           letter-spacing:2px; text-transform:uppercase; }
  .total b { font-size:30px; color:#c9a227; letter-spacing:0; }
  .acciones { gap:14px; margin-top:36px; }
  button { padding:15px 34px; font-size:12px; letter-spacing:2px; text-transform:uppercase; font-family:Arial,sans-serif; }
  .primario { background:#c9a227; color:#12100e; }
  .secundario { background:transparent; color:#efe8dd; border:1px solid #3a332b; }
""", tokens="--fondo:#12100e;--sup:#1a1713;--texto:#efe8dd;--tenue:#8a8078;--acento:#c9a227;--sobre-acento:#12100e;--borde:#3a332b;--radio:0;"),
    Estilo("papel", "Como una libreta", """
  body { background:#fffdf5; color:#2f2b26;
         font-family:'Bradley Hand','Segoe Print','Comic Sans MS',cursive;
         background-image:repeating-linear-gradient(#fffdf5 0 31px,#e8e2d0 31px 32px); }
  .hoja { padding:40px 46px; }
  header { padding-bottom:18px; border-bottom:2px solid #2f2b26; }
  .marca { font-size:22px; font-weight:700; }
  nav { gap:18px; font-size:15px; color:#7a7264; }
  main { padding-top:26px; }
  h1 { font-size:36px; }
  .sub { color:#7a7264; font-size:16px; margin-top:8px; }
  .lista { margin-top:26px; }
  .lista li { padding:14px 4px; border-bottom:1px solid #ddd6c2; font-size:19px; }
  .q { color:#a89f8c; }
  .deuda .n { text-decoration:underline wavy #e07b39; }
  .total { margin-top:26px; padding:16px 18px; border:3px solid #2f2b26; border-radius:16px 4px 16px 4px; font-size:18px; }
  .total b { font-size:28px; }
  .acciones { gap:14px; margin-top:30px; }
  button { padding:14px 28px; font-size:17px; font-family:inherit;
           border:3px solid #2f2b26; border-radius:16px 4px 16px 4px; }
  .primario { background:#2f2b26; color:#fffdf5; }
  .secundario { background:transparent; color:#2f2b26; }
""", tokens="--fondo:#fffdf5;--sup:#fffdf5;--texto:#2f2b26;--tenue:#a89f8c;--acento:#2f2b26;--sobre-acento:#fffdf5;--borde:#2f2b26;--radio:12px;"),
    Estilo("compacto", "Todo a la vista", """
  body { background:#eef1f4; color:#20262e; font-family:Arial,Helvetica,sans-serif; font-size:14px; }
  .hoja { padding:20px 24px; }
  header { padding:10px 14px; background:#20262e; color:#fff; border-radius:4px; }
  .marca { font-size:15px; font-weight:700; }
  nav { gap:14px; font-size:12px; color:#9aa5b1; }
  main { padding-top:16px; }
  h1 { font-size:20px; }
  .sub { color:#6b7684; font-size:12px; margin-top:3px; }
  .lista { margin-top:14px; background:#fff; border:1px solid #d3d9df; border-radius:4px; }
  .lista li { padding:9px 12px; border-bottom:1px solid #eef1f4; font-size:13px; }
  .q { color:#9aa5b1; font-variant-numeric:tabular-nums; }
  .p { font-variant-numeric:tabular-nums; font-weight:700; }
  .deuda { background:#fff8e6; }
  .total { margin-top:12px; padding:10px 14px; background:#fff; border:1px solid #d3d9df;
           border-radius:4px; font-size:13px; }
  .total b { font-size:20px; }
  .acciones { gap:8px; margin-top:14px; }
  button { padding:9px 18px; font-size:13px; border-radius:4px; }
  .primario { background:#0b6bcb; color:#fff; }
  .secundario { background:#fff; color:#20262e; border:1px solid #d3d9df; }
""", tokens="--fondo:#eef1f4;--sup:#fff;--texto:#20262e;--tenue:#9aa5b1;--acento:#0b6bcb;--sobre-acento:#fff;--borde:#d3d9df;--radio:4px;"),
)

POR_ID = {e.id: e for e in ESTILOS}


def pagina(estilo: Estilo, pantalla: Pantalla | None = None) -> str:
    """El HTML de una muestra: un estilo pintando una pantalla.

    Los tokens del estilo van en `:root` ANTES de su CSS, para que lo propio de
    cada pantalla —que vive en `COMUN` y habla en variables— coja su paleta sin
    que el estilo haya tenido que declarar nada de esa pantalla.
    """
    pantalla = pantalla or PANTALLA_POR_ID[PANTALLA_DE_REFERENCIA]
    return (f"<!doctype html><html lang=es><meta charset=utf-8>"
            f"<style>:root{{{estilo.tokens}}}{COMUN}{estilo.css}</style>"
            f"{ENVOLTORIO.format(pantalla=pantalla.html)}</html>")


def _navegador() -> str | None:
    """Chrome hace falta para GENERAR el catálogo, nunca para usarlo: las
    capturas quedan en disco y el bot manda archivos.

    Elegirlo vive en `mirar.py`, que es donde está escrito por qué el navegador
    de Windows no sirve para comprobar un ancho de móvil. Aquí da igual —las
    muestras se pintan a 720 px— pero tener dos formas de elegir navegador
    acabaría con una de las dos equivocada.
    """
    return mirar.cual()


def _para_el_navegador(chrome: str, ruta: Path) -> str:
    """La misma ruta, dicha como la entiende ESE navegador. Ver `mirar.para`."""
    return mirar.para(chrome, ruta)


def carpeta() -> Path:
    return Path(config.HUB_HOME) / "estilos"


def nombre_de_archivo(estilo: Estilo, pantalla: Pantalla | None = None) -> str:
    """Cómo se llama la captura de esta pareja, sin extensión.

    Vive aparte de `capturar` porque hay dos sitios que necesitan saberlo: quien
    las pinta y quien las manda por Telegram. Escrito dos veces, el día que
    cambiara el criterio el bot enseñaría cuatro muestras de seis y quien
    eligiera creería que las vio todas — un fallo que no se ve desde fuera.

    La pantalla de referencia no lleva sufijo para que las doce del catálogo de
    estilos se llamen como su estilo, que es como se nombran al enseñarlas.
    """
    pantalla = pantalla or PANTALLA_POR_ID[PANTALLA_DE_REFERENCIA]
    return (estilo.id if pantalla.id == PANTALLA_DE_REFERENCIA
            else f"{pantalla.id}-{estilo.id}")


_ORDINALES = {
    "primera": 1, "primero": 1, "uno": 1, "una": 1,
    "segunda": 2, "segundo": 2, "dos": 2,
    "tercera": 3, "tercero": 3, "tres": 3,
    "cuarta": 4, "cuarto": 4, "cuatro": 4,
    "quinta": 5, "quinto": 5, "cinco": 5,
    "sexta": 6, "sexto": 6, "seis": 6,
}


def _plano(texto: str) -> str:
    """Sin tildes, en minúsculas. Nadie escribe «Cálido» con tilde en un móvil."""
    sin = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in sin if unicodedata.category(c) != "Mn")


def identificar(respuesta: str, grupo: str = "estilos") -> str | None:
    """Qué muestra eligió, a partir de lo que contestó. `None` si no se sabe.

    🔴 Existe porque el primer ensayo con un agente de verdad lo destapó: la
    ficha guardó *«Cálido, como una tienda de barrio»* —el **nombre** de la
    muestra, que es lo que se le enseñó— y el constructor buscaba un **id**. Sin
    esto, el estilo elegido se perdía en silencio y se construía con el de
    referencia: la única decisión que ella pudo tomar viendo, descartada sin que
    nada lo dijera.

    Se admite el id, el nombre, un número y un ordinal escrito, porque a
    «¿cuál se parece más?» se contesta de las cuatro formas y ninguna es rara.
    Lo que **no** se hace es adivinar: si no casa, devuelve `None` y quien
    pregunte volverá a preguntar, que es mejor que construir lo que no se eligió.
    """
    dicho = _plano(respuesta).strip(" .,:;!¡¿?«»\"'")
    if not dicho:
        return None
    pares = catalogo().get(grupo) or []
    opciones = [(e.id, e.nombre) if grupo == "estilos" else (p.id, p.nombre)
                for e, p in pares]

    # En este orden, y el orden es la cautela: lo exacto primero, lo suelto al
    # final. «Claro» está dentro de «me gusta el claro» y también dentro de «no
    # lo tengo claro», así que el parecido sólo decide cuando no hay nada mejor.
    for identificador, _ in opciones:
        if dicho == _plano(identificador):
            return identificador
    for identificador, nombre in opciones:
        if dicho == _plano(nombre):
            return identificador

    # Se parte con la expresión y no con `split()`: «la segunda, la de…» deja
    # el token «segunda,» con la coma pegada, y entonces el ordinal no casaba.
    # Es el caso más normal de todos —así contesta quien acaba de ver seis
    # fotos— y fallaba en silencio devolviendo «no se sabe».
    palabras = re.findall(r"[a-z0-9]+", dicho)
    numeros = [int(t) for t in palabras if t.isdigit()]
    numeros += [_ORDINALES[p] for p in palabras if p in _ORDINALES]
    for n in numeros:
        if 1 <= n <= len(opciones):
            return opciones[n - 1][0]

    palabras = set(palabras)
    for identificador, nombre in opciones:
        if _plano(nombre) in dicho or _plano(identificador) in palabras:
            return identificador
    return None


def hoja(estilo_id: str) -> str:
    """El CSS de un estilo, listo para un sitio de verdad y no para una captura.

    🔴 Es lo que cierra el círculo de la decisión f1. Ella no describió un
    estilo: **señaló una foto**. Si lo construido se escribiera con un CSS
    cualquiera, esa elección habría sido un trámite. Dándole el mismo CSS que
    pintó la muestra, lo que ve se parece a lo que eligió porque literalmente lo
    es.

    Sale sin el tamaño fijo de la captura: aquello son 720×1000 para que las
    doce muestras se comparen, y un sitio real se mira en un teléfono.
    """
    estilo = POR_ID.get(estilo_id)
    if not estilo:
        raise ValueError(f"«{estilo_id}» no es un estilo: son {sorted(POR_ID)}")
    sin_marco = COMUN.replace(
        "body { width: 720px; height: 1000px; overflow: hidden; }",
        "body { min-height: 100vh; }",
    ).replace(
        ".hoja { width: 100%; height: 100%; display: flex; flex-direction: column; }",
        ".hoja { width: 100%; min-height: 100vh; max-width: 900px; margin: 0 auto;"
        " display: flex; flex-direction: column; }",
    )
    # El id va en el comentario además del nombre: son distintos —«nocturno» se
    # llama «Oscuro»— y el id es lo que hay en la ficha, así que sin él no se
    # puede comprobar de un vistazo que lo construido use lo que ella eligió.
    return (f"/* Estilo «{estilo.nombre}» ({estilo.id}), el mismo que pintó la\n"
            f"   muestra que eligió. Generado por el hub; no editar a mano. */\n"
            f":root{{{estilo.tokens}}}\n{sin_marco}\n{estilo.css}\n")


BOSQUEJO = "bosquejo.html"


def envolver_bosquejo(estilo_id: str, cuerpo: str, marca: str = "") -> str:
    """El boceto que escribió el agente, vestido con el CSS de un estilo.

    🔴 Decisión 239. Las muestras del catálogo son la MISMA pantalla de fiados
    en doce aires, y a quien tiene una tómbola le parecen de otro sitio: no se
    ve a sí misma y elige a ciegas. El boceto lo escribe el entrevistador con
    sus palabras y sus datos —una sola pantalla, contra estas mismas clases—,
    y aquí se pinta en cada aire. Sigue sin ser la página: es la pregunta
    «¿cuál aire?» hecha sobre algo que ella reconoce.
    """
    # La cabecera con SU nombre la pone el hub, como el catálogo pone la suya:
    # el agente escribe el `<main>`, que es donde está su negocio. Si ya trae
    # la hoja entera, se respeta.
    if 'class="hoja"' not in cuerpo:
        cuerpo = (f'<div class="hoja"><header><div class="marca">'
                  f'{marca or "Tu negocio"}</div></header>{cuerpo}</div>')
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<style>{hoja(estilo_id)}{BOCETO_A_390}</style></head><body>{cuerpo}</body></html>"
    )


# 🔴 Lo que el boceto necesita a 390 px y el catálogo a 720 no. Se vio pintando
# el primer boceto de horas, no leyendo: la columna de 44 px que le sobra a un
# «2» no le cabe a un «10:00» y la hora pisaba el nombre; y con siete filas la
# hoja crecía —`min-height`— hasta empujar el total y los botones fuera de la
# foto, que es justo el «botón cortado se lee como roto» que la lista cede
# sitio para evitar. Va DESPUÉS del CSS del estilo para ganar la cascada, y
# sólo aquí: un sitio de verdad se desplaza, y ahí `min-height` es lo correcto.
BOCETO_A_390 = """
  body { height: 100vh; min-height: 0; overflow: hidden; }
  .hoja { height: 100vh; min-height: 0; padding: 26px 22px; }
  .lista li { grid-template-columns: minmax(44px, max-content) 1fr auto; column-gap: 12px; }
"""


def ruta_muestra(estilo: Estilo, pantalla: Pantalla | None = None,
                 destino: Path | None = None) -> Path:
    """Dónde está —o dónde quedará— el PNG de esta pareja.

    🔴 La extensión va aquí y no en quien llama. Se escribió una vez suelta y el
    resultado fue que el bot creía que faltaban las doce muestras: buscaba
    «claro» donde el archivo es «claro.png». Un nombre construido en dos sitios
    se separa, y lo hace en silencio.
    """
    return (destino or carpeta()) / f"{nombre_de_archivo(estilo, pantalla)}.png"


def capturar(estilo: Estilo, pantalla: Pantalla | None = None,
             destino: Path | None = None) -> Path:
    """Pinta la muestra y la guarda como PNG. Devuelve dónde quedó."""
    chrome = _navegador()
    if not chrome:
        raise RuntimeError(
            "no hay Chrome ni Chromium para generar las muestras. Sólo hace "
            "falta para generarlas: una vez hechas, el bot manda los archivos."
        )
    pantalla = pantalla or PANTALLA_POR_ID[PANTALLA_DE_REFERENCIA]
    nombre = nombre_de_archivo(estilo, pantalla)
    salida = (destino or carpeta())
    salida.mkdir(parents=True, exist_ok=True)
    fuente = salida / f"{nombre}.html"
    fuente.write_text(pagina(estilo, pantalla), encoding="utf-8")
    png = ruta_muestra(estilo, pantalla, salida)
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-sandbox",
         "--window-size=720,1000", "--force-device-scale-factor=2",
         f"--screenshot={_para_el_navegador(chrome, png)}",
         _para_el_navegador(chrome, fuente)],
        capture_output=True, timeout=90, check=False,
    )
    fuente.unlink(missing_ok=True)
    if not png.is_file():
        raise RuntimeError(f"Chrome no produjo la captura de «{nombre}»")
    return png


def catalogo() -> dict[str, list[tuple[Estilo, Pantalla]]]:
    """Qué muestra va en cada catálogo. **Aquí vive el invariante**, y por eso
    está separado de pintarlas: la regla se puede comprobar sin un navegador.

    🔴 Son dos catálogos porque contestan preguntas distintas, y el invariante
    va al revés en cada uno. Mezclarlos los arruina los dos:

        estilos    doce aspectos sobre LA MISMA pantalla
                   → «¿cuál se parece más a lo tuyo?»
        pantallas  once pantallas con EL MISMO aspecto
                   → «¿cuál de éstas te serviría?»

    Si una muestra de estilo enseñara un calendario y otra una lista, ella
    estaría comparando qué es en vez de cómo se ve; y si cada pantalla llevara
    su propio estilo, compararía el aspecto en vez de para qué sirve.
    """
    referencia = PANTALLA_POR_ID[PANTALLA_DE_REFERENCIA]
    neutro = POR_ID[ESTILO_DE_REFERENCIA]
    return {
        "estilos": [(e, referencia) for e in ESTILOS],
        "pantallas": [(neutro, p) for p in PANTALLAS],
    }


def generar(destino: Path | None = None) -> dict[str, list[Path]]:
    """Pinta los dos catálogos. Se llama a mano, no en cada arranque."""
    return {nombre: [capturar(e, p, destino) for e, p in pares]
            for nombre, pares in catalogo().items()}
