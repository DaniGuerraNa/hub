/* Dictar en vez de teclear, en el teléfono o en la PC.
 *
 * Graba en el navegador, sube el audio —a `data-grabar-url`, o a
 * /orquestador/audio si no lo dice— que lo transcribe EN CASA, y pega el texto
 * en el campo. El tablero sube a /api/voz (`transcribir.dictado`,
 * C-0149). 🔴 No envía nada: una transcripción equivocada en una orden que se
 * ejecuta sin nadie delante es el error que no se ve hasta que ya pasó, así
 * que el texto se queda a la vista y lo manda una persona.
 *
 * El micrófono sólo existe en un contexto seguro (HTTPS o localhost). Por el
 * tailnet el hub va por HTTPS, así que en el teléfono está; si no, se dice.
 */
(() => {
  // Cada botón se engancha una vez; se repasa tras `hub:repintado` porque una
  // acción sin recargar (C-0167) pinta botones nuevos —«Dictar» la respuesta
  // al orquestador— que al cargar no existían.
  function enganchar(boton) {
    if (boton.dataset.grabarListo) return;
    boton.dataset.grabarListo = '1';
    const destino = document.getElementById(boton.dataset.grabar);
    const estado = document.getElementById(boton.dataset.grabarEstado);
    const origen = document.getElementById(boton.dataset.grabarOrigen);
    const inicial = boton.textContent;
    const url = boton.dataset.grabarUrl || '/orquestador/audio';
    let grabadora = null;
    let trozos = [];

    const decir = (texto) => { if (estado) estado.textContent = texto; };

    // Al vaciarse el formulario —`sin-recarga.js` lo hace tras enviarlo bien
    // (C-0233, «Encolar»)— vuelve todo a como estaba antes de dictar. El
    // origen es un campo oculto y `reset()` no lo devuelve solo (su valor ES
    // su atributo): la tarea siguiente, tecleada, salía como «dictada».
    const origenInicial = origen ? origen.value : '';
    const estadoInicial = estado ? estado.textContent : '';
    if (boton.form) {
      boton.form.addEventListener('reset', () => {
        if (origen) origen.value = origenInicial;
        decir(estadoInicial);
      });
    }

    const extension = (tipo) =>
      tipo.includes('ogg') ? 'ogg' : tipo.includes('mp4') ? 'm4a' : 'webm';

    const transcribir = async (tipo) => {
      decir('Transcribiendo…');
      boton.disabled = true;
      const datos = new FormData();
      datos.append('audio', new Blob(trozos, { type: tipo }), 'audio.' + extension(tipo));
      try {
        const r = await fetch(url, { method: 'POST', body: datos });
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
  }
  const repasar = () => document.querySelectorAll('[data-grabar]').forEach(enganchar);
  repasar();
  document.addEventListener('hub:repintado', repasar);
})();
