/* El banco de dictado (C-0312): una frase cada vez, leída en voz alta.
 *
 * Graba con `HubGrabar` y las restricciones de la conversación con el
 * secretario —que es por donde más se dicta—: así se mide con el grabador de
 * verdad. Con cada toma va lo que dio el micrófono (`getSettings()`), porque
 * lo pedido no es siempre lo que se aplica. Al parar se sube a
 * `/api/voz/banco`, que guarda el audio con su frase y no transcribe nada.
 *
 * El aparato (PC o teléfono) sale de `?aparato=` o, si no lo dice, del ancho
 * de la pantalla; se cambia con sus dos botones. Los datos llegan en
 * `#banco-datos` (`api.banco_dictado`): la página pinta la primera frase y
 * esto sigue desde ahí sin recargar.
 */
(() => {
  const raiz = document.getElementById('banco');
  const fuente = document.getElementById('banco-datos');
  if (!raiz || !fuente || !window.HubGrabar) return;
  let datos;
  try { datos = JSON.parse(fuente.textContent || '{}'); } catch (e) { return; }
  const frases = Array.isArray(datos.frases) ? datos.frases : [];
  const aparatos = Array.isArray(datos.aparatos) ? datos.aparatos : [];
  const categorias = datos.categorias || {};
  if (!frases.length || !aparatos.length) return;

  const $ = (id) => document.getElementById(id);
  const texto = $('banco-texto');
  const meta = $('banco-meta');
  const estado = $('banco-estado');
  const principal = $('banco-grabar');
  const repetir = $('banco-repetir');
  const siguiente = $('banco-siguiente');
  const micro = $('banco-micro');

  // Las frases largas rondan el medio minuto leídas: a los 90 s sin «Parar»
  // se para sola, y esa toma no se guarda (lo leído quedó cortado o sobra).
  const TOPE_MS = 90000;
  // Por debajo de este ancho es el teléfono (el mismo corte que la plantilla).
  const ANCHO_TELEFONO = 700;

  const ids = aparatos.map((a) => a.id);
  const nombreDe = (a) => (aparatos.find((x) => x.id === a) || {}).nombre || a;
  const pedido = (() => {
    try { return new URLSearchParams(location.search || '').get('aparato'); } catch (e) { return null; }
  })();
  let aparato = ids.includes(pedido) ? pedido
    : ((window.innerWidth || 0) <= ANCHO_TELEFONO && ids.includes('telefono') ? 'telefono' : ids[0]);
  let indice = 0;
  let toma = null;
  // Del clic a que el navegador abre el micrófono pasa un rato: mientras, no
  // se cambia de frase ni de aparato ni se abre otro micrófono, o la toma se
  // subiría con la referencia de otra frase.
  let abriendo = false;
  const ocupado = () => abriendo || !!toma || fase === 'guardando';
  // lista: sin grabar · grabando · guardando · grabada · completo: todas grabadas
  let fase = 'lista';

  const grabada = (f, a) => !!(f.grabada && f.grabada[a || aparato]);
  const hechas = (a) => frases.filter((f) => grabada(f, a)).length;
  const primeraSinGrabar = (desde) => {
    for (let k = 0; k < frases.length; k += 1) {
      const i = (desde + k) % frases.length;
      if (!grabada(frases[i])) return i;
    }
    return -1;
  };

  function decir(t, grabando) {
    estado.textContent = t;
    estado.classList.toggle('grabando', !!grabando);
  }

  function pintar() {
    const f = frases[indice];
    if (fase === 'completo') {
      texto.textContent = `Las ${frases.length} frases están grabadas en este aparato.`;
      if (meta) meta.textContent = 'Terminado';
    } else {
      texto.textContent = f.texto;
      if (meta) meta.textContent = `${categorias[f.categoria] || f.categoria} · ${indice + 1} de ${frases.length}`;
    }
    // Una sola acción principal a la vista: grabar (o parar), y con la toma
    // ya guardada, seguir.
    const conGrabar = fase === 'lista' || fase === 'grabando' || fase === 'guardando';
    principal.hidden = !conGrabar;
    principal.textContent = fase === 'grabando' ? 'Parar' : fase === 'guardando' ? 'Guardando…' : 'Grabar';
    principal.disabled = fase === 'guardando';
    repetir.hidden = fase !== 'grabada';
    siguiente.hidden = !(fase === 'lista' || fase === 'grabada');
    siguiente.textContent = fase === 'grabada' ? 'Siguiente' : 'Saltar esta';
    siguiente.classList.toggle('cta', fase === 'grabada');
    siguiente.classList.toggle('sutil', fase !== 'grabada');

    const n = hechas(aparato);
    $('banco-cuenta').textContent = String(n);
    $('banco-total').textContent = String(frases.length);
    $('banco-barra').style.setProperty('width', `${Math.round((100 * n) / frases.length)}%`);
    document.querySelectorAll('[data-cuenta-aparato]').forEach((el) => {
      const a = el.dataset.cuentaAparato;
      if (ids.includes(a)) el.textContent = `${hechas(a)}/${frases.length}`;
    });
    document.querySelectorAll('[data-elegir-aparato]').forEach((b) => {
      const a = b.dataset.elegirAparato;
      if (ids.includes(a)) b.setAttribute('aria-pressed', a === aparato ? 'true' : 'false');
    });
    document.querySelectorAll('[data-nombre-aparato]').forEach((el) => { el.textContent = nombreDe(aparato); });
    // Borrar y vaciar van por formulario: que lleven el aparato que se ve.
    document.querySelectorAll('[data-campo-aparato]').forEach((c) => { c.value = aparato; });
    document.querySelectorAll('[data-fila-frase]').forEach((li) => {
      const x = frases.find((y) => y.id === li.dataset.filaFrase);
      if (!x) return;
      li.classList.toggle('hecha', grabada(x));
      li.classList.toggle('actual', fase !== 'completo' && x === f);
    });
  }

  function ir(i) {
    indice = i;
    fase = grabada(frases[i]) ? 'grabada' : 'lista';
    decir(fase === 'grabada' ? 'Ésta ya está grabada: puedes repetirla o seguir.'
                             : 'Pulsa «Grabar» y léela en voz alta, como hablas siempre.');
    pintar();
  }

  function completo() {
    fase = 'completo';
    const otro = ids.find((a) => a !== aparato && hechas(a) < frases.length);
    decir(otro ? `Listo en este aparato. Falta grabarlas en ${nombreDe(otro)}.`
               : 'Listo. Para repetir una, búscala en «Todas las frases».');
    pintar();
  }

  function seguir(desde) {
    const i = primeraSinGrabar(desde);
    if (i < 0) completo();
    else ir(i);
  }

  function mostrarMicro(a) {
    if (!micro || !a) return;
    const si = (v) => (v === true ? 'sí' : v === false ? 'no' : '?');
    const partes = [];
    if ('echoCancellation' in a) partes.push(`quitar eco: ${si(a.echoCancellation)}`);
    if ('noiseSuppression' in a) partes.push(`quitar ruido: ${si(a.noiseSuppression)}`);
    if ('autoGainControl' in a) partes.push(`ganancia automática: ${si(a.autoGainControl)}`);
    if (a.sampleRate) partes.push(`${a.sampleRate} Hz`);
    if (a.channelCount) partes.push(a.channelCount === 1 ? '1 canal' : `${a.channelCount} canales`);
    micro.textContent = partes.length ? `Lo que dio el micrófono: ${partes.join(' · ')}` : '';
    micro.hidden = !partes.length;
  }

  async function grabar() {
    // La frase y el aparato, fijados al empezar: lo que se sube es lo que se leyó.
    const f = frases[indice];
    const deAparato = aparato;
    const antes = fase;
    abriendo = true;
    principal.disabled = true;
    repetir.disabled = true;
    decir('Abriendo el micrófono…');
    let esta;
    try {
      esta = await HubGrabar.grabar({ restricciones: HubGrabar.RESTRICCIONES.conversacion });
    } catch (e) {
      abriendo = false;
      principal.disabled = false;
      repetir.disabled = false;
      fase = antes;
      pintar();
      decir(`No se puede grabar: ${e.message}`);
      return;
    }
    abriendo = false;
    repetir.disabled = false;
    toma = esta;
    fase = 'grabando';
    const desde = Date.now();
    pintar();
    principal.disabled = false;
    decir('● Grabando… léela y pulsa «Parar» al terminar.', true);
    const cuenta = setInterval(() => {
      decir(`● Grabando… ${Math.round((Date.now() - desde) / 1000)} s`, true);
    }, 1000);
    let cortada = false;
    const tope = setTimeout(() => { if (toma === esta) { cortada = true; esta.parar(); } }, TOPE_MS);
    const audio = await esta.terminado;
    clearInterval(cuenta);
    clearTimeout(tope);
    toma = null;
    mostrarMicro(esta.ajustes);
    if (cortada) {
      fase = grabada(f, deAparato) ? 'grabada' : 'lista';
      pintar();
      decir(`Se paró sola a los ${Math.round(TOPE_MS / 1000)} s y no la guardé: vuelve a grabarla.`);
      return;
    }
    if (!audio) {
      fase = grabada(f) ? 'grabada' : 'lista';
      pintar();
      decir('No se grabó nada. Vuelve a intentarlo.');
      return;
    }
    fase = 'guardando';
    pintar();
    decir('Guardando…');
    const j = await HubGrabar.subir(audio, {
      url: '/api/voz/banco',
      campos: { frase: f.id, aparato: deAparato, texto: f.texto,
                micro: JSON.stringify({ ...esta.ajustes, restricciones: 'conversacion' }) },
    });
    if (!j || !j.ok) {
      fase = grabada(f) ? 'grabada' : 'lista';
      pintar();
      decir(`No se guardó: ${(j && j.error) || 'sin respuesta del hub'}. Vuelve a grabarla.`);
      return;
    }
    f.grabada = { ...(f.grabada || {}), [deAparato]: true };
    fase = 'grabada';
    pintar();
    decir(`Guardada (${Math.max(1, Math.round((Date.now() - desde) / 1000))} s). Pulsa «Siguiente».`);
  }

  const empezar = () => grabar().catch((e) => {
    toma = null;
    abriendo = false;
    principal.disabled = false;
    repetir.disabled = false;
    fase = grabada(frases[indice]) ? 'grabada' : 'lista';
    pintar();
    decir(`Algo falló al grabar: ${e && e.message ? e.message : e}`);
  });

  principal.addEventListener('click', () => {
    if (abriendo) return;
    if (toma) { toma.parar(); return; }
    if (fase === 'lista') empezar();
  });
  repetir.addEventListener('click', () => { if (!ocupado() && fase === 'grabada') empezar(); });
  siguiente.addEventListener('click', () => {
    if (ocupado()) return;
    if (fase === 'grabada') { seguir((indice + 1) % frases.length); return; }
    const i = primeraSinGrabar((indice + 1) % frases.length);
    if (i < 0 || i === indice) decir('Es la única que falta.');
    else ir(i);
  });
  document.querySelectorAll('[data-elegir-aparato]').forEach((b) => b.addEventListener('click', () => {
    const a = b.dataset.elegirAparato;
    if (!ids.includes(a) || ocupado() || a === aparato) return;
    aparato = a;
    try { history.replaceState(null, '', `?aparato=${a}`); } catch (e) { /* sin historial, igual */ }
    seguir(0);
  }));
  document.querySelectorAll('[data-ir]').forEach((b) => b.addEventListener('click', () => {
    if (ocupado()) return;
    const i = frases.findIndex((f) => f.id === b.dataset.ir);
    if (i < 0) return;
    ir(i);
    if (texto.scrollIntoView) texto.scrollIntoView({ block: 'center' });
  }));

  seguir(0);
})();
