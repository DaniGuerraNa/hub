/* Dictar en vez de teclear, en el teléfono.
 *
 * Graba en el navegador, sube el audio a /orquestador/audio —que lo transcribe
 * EN CASA, con el mismo transcriptor que los encargos— y pega el texto en el
 * campo. 🔴 No envía nada: una transcripción equivocada en una orden que se
 * ejecuta sin nadie delante es el error que no se ve hasta que ya pasó, así
 * que el texto se queda a la vista y lo manda una persona.
 *
 * El micrófono sólo existe en un contexto seguro (HTTPS o localhost). Por el
 * tailnet el hub va por HTTPS, así que en el teléfono está; si no, se dice.
 */
(() => {
  document.querySelectorAll('[data-grabar]').forEach((boton) => {
    const destino = document.getElementById(boton.dataset.grabar);
    const estado = document.getElementById(boton.dataset.grabarEstado);
    const origen = document.getElementById(boton.dataset.grabarOrigen);
    const inicial = boton.textContent;
    let grabadora = null;
    let trozos = [];

    const decir = (texto) => { if (estado) estado.textContent = texto; };

    const extension = (tipo) =>
      tipo.includes('ogg') ? 'ogg' : tipo.includes('mp4') ? 'm4a' : 'webm';

    const transcribir = async (tipo) => {
      decir('Transcribiendo…');
      boton.disabled = true;
      const datos = new FormData();
      datos.append('audio', new Blob(trozos, { type: tipo }), 'audio.' + extension(tipo));
      try {
        const r = await fetch('/orquestador/audio', { method: 'POST', body: datos });
        const j = await r.json();
        if (!j.ok) {
          decir('No se pudo transcribir: ' + j.error);
          return;
        }
        const previo = (destino.value || '').trimEnd();
        destino.value = previo ? previo + '\n' + j.texto : j.texto;
        if (origen) origen.value = 'audio';
        decir('Listo. Revísalo antes de mandarlo.');
      } catch (e) {
        decir('No se pudo transcribir: ' + e);
      } finally {
        boton.disabled = false;
      }
    };

    boton.addEventListener('click', async () => {
      if (grabadora) {
        grabadora.stop();
        return;
      }
      if (!navigator.mediaDevices || !window.MediaRecorder) {
        decir('Este navegador no deja grabar aquí (hace falta HTTPS). Escríbelo.');
        return;
      }
      let flujo;
      try {
        flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        decir('Sin permiso para el micrófono: ' + (e && e.message ? e.message : e));
        return;
      }
      trozos = [];
      const esta = new MediaRecorder(flujo);
      grabadora = esta;
      esta.addEventListener('dataavailable', (ev) => {
        if (ev.data && ev.data.size) trozos.push(ev.data);
      });
      esta.addEventListener('stop', () => {
        flujo.getTracks().forEach((pista) => pista.stop());
        grabadora = null;
        boton.textContent = inicial;
        boton.classList.remove('grabando');
        if (!trozos.length) {
          decir('No se grabó nada.');
          return;
        }
        transcribir(esta.mimeType || 'audio/webm');
      });
      esta.start();
      boton.textContent = 'Parar y transcribir';
      boton.classList.add('grabando');
      decir('Grabando… pulsa otra vez para terminar.');
    });
  });
})();
