/* Sondear sólo mientras la pestaña se ve (C-0277).
 *
 * Los paneles de /trabajo (lienzos, consultas, programados) y el refresco de
 * /navegante y /reuniones preguntaban al hub cada pocos segundos aunque nadie
 * mirara: un /trabajo de fondo eran ~31 peticiones por minuto sin fin —con el
 * teléfono por la red privada, batería y datos—, y cada una abre la base y
 * deja su línea en el registro. Con la pestaña oculta se para; al volver se
 * pregunta enseguida, porque esperar el turno enseñaría justo el dato viejo.
 * Es lo que ya hacían a mano el latido de /trabajo y los talleres.
 *
 * Va en el <head> de `base.html` y no al final con `sin-recarga.js`: los
 * scripts de cada pantalla corren antes que los del final, y arrancan su
 * sondeo al cargar.
 *
 *   const parar = HubSondeo.cada(refrescar, 4000);   // parar() lo deja del todo
 */
(function () {
  function cada(fn, ms) {
    let reloj = 0;
    let vivo = true;
    const oculta = () => document.hidden === true;
    const arrancar = () => { if (vivo && !reloj && !oculta()) reloj = setInterval(fn, ms); };
    const pausar = () => { if (reloj) { clearInterval(reloj); reloj = 0; } };
    function alCambiar() {
      if (oculta()) { pausar(); return; }
      if (vivo && !reloj) { fn(); arrancar(); }
    }
    document.addEventListener('visibilitychange', alCambiar);
    arrancar();
    return function parar() {
      vivo = false;
      pausar();
      document.removeEventListener('visibilitychange', alCambiar);
    };
  }

  window.HubSondeo = { cada };
})();
