/* El filtro de la pantalla de archivos. Lo único con JavaScript que hay aquí.
 *
 * La navegación son enlaces normales a propósito: la pantalla se usa desde el
 * móvil y con la red de un aeropuerto, y un listado que necesita JavaScript para
 * pintarse es un listado que a veces no se pinta. Lo que sí necesita ejecutarse
 * es esto: una carpeta de repos tiene 40 entradas y encontrar una con el pulgar
 * es peor que escribir tres letras.
 *
 * Filtra lo que YA está en la página; no pregunta nada al hub. Por eso no puede
 * encontrar lo que quedó fuera del tope de `navegador.TOPE` —y por eso el pie
 * dice cuántas quedaron, en vez de dejar creer que se está filtrando sobre todo.
 *
 * Se prueba ejecutándolo (`tests/test_archivos_js.py`, regla dura 11).
 */
(function () {
  const filtro = document.getElementById('filtro-arch');
  if (!filtro) return;

  /* `[data-fijo]` es «.. subir»: no es una entrada de la carpeta y filtrarla
   * dejaría sin salida a quien escribe algo que no casa con nada. */
  const filas = Array.from(document.querySelectorAll('.fila-arch:not([data-fijo])'));

  const vacio = document.createElement('p');
  vacio.className = 'tenue';
  vacio.style.cssText = 'padding:14px 13px;margin:0';
  vacio.hidden = true;
  if (filtro.closest('.tarjeta')) {
    filtro.closest('.tarjeta').insertBefore(vacio, document.getElementById('pie-arch'));
  }

  /* Sin tildes y en minúsculas. Las rutas que vienen de OneDrive traen nombres
   * en castellano, y obligar a escribir la tilde exacta para encontrar una
   * carpeta es exactamente el trabajo que este campo existe para quitar. */
  function llano(s) {
    return String(s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
  }

  function aplicar() {
    const texto = llano(filtro.value.trim());
    let visibles = 0;
    filas.forEach(fila => {
      const nom = fila.querySelector('.nom');
      const casa = !texto || llano(nom && nom.textContent).includes(texto);
      fila.hidden = !casa;
      if (casa) visibles++;
    });
    vacio.hidden = !(texto && visibles === 0);
    if (!vacio.hidden) {
      vacio.textContent = `Nada que se llame «${filtro.value.trim()}» en esta carpeta.`;
    }
  }

  filtro.addEventListener('input', aplicar);
  /* Al volver atrás, el navegador restaura lo escrito en el campo pero no el
   * estado de las filas: sin esta llamada la lista sale entera bajo un filtro
   * que parece puesto. */
  aplicar();
})();
