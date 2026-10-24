/* Lo que va pasando mientras el hub se actualiza (decisión 296).
 *
 * `actualizar.sh` reinicia el hub a mitad, así que durante unos segundos nadie
 * contesta: eso no es un fallo, es el paso 5. Se sigue preguntando hasta que
 * el resultado está escrito, y entonces se recarga para enseñar la versión
 * nueva. El registro sale de un archivo, no de la memoria del proceso que se
 * reinicia: por eso sobrevive.
 */
(() => {
  const raiz = document.getElementById('act');
  if (!raiz || raiz.dataset.enMarcha !== 'si') return;
  const registro = document.getElementById('registro');
  const resultado = document.getElementById('resultado');
  let caidas = 0;

  async function mirar() {
    let d;
    try {
      const r = await fetch('/api/actualizacion', { cache: 'no-store' });
      d = await r.json();
      caidas = 0;
    } catch (e) {
      caidas++;
      if (resultado) resultado.textContent = 'el hub se está reiniciando…';
      // Media hora sin contestar ya no es un reinicio: se deja de insistir.
      if (caidas < 900) setTimeout(mirar, 2000);
      return;
    }
    if (registro && d.registro) {
      registro.textContent = d.registro;
      registro.scrollTop = registro.scrollHeight;
    }
    if (d.en_marcha) {
      if (resultado) resultado.textContent = 'en marcha';
      setTimeout(mirar, 2000);
      return;
    }
    if (resultado) resultado.textContent = d.rc === 0 ? 'terminada' : 'falló';
    setTimeout(() => location.reload(), 1500);
  }
  mirar();
})();
