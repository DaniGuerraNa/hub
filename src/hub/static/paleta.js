/* Paleta de comandos (Ctrl+K).
 *
 * Existe porque el problema que el hub resuelve no es de pantallas, es de
 * memoria: con ~20 ubicaciones y ~60 capacidades, escribir el nombre siempre
 * gana a recordar en qué sección estaba.
 *
 * Sin dependencias y sin build (decisión 23). El buscador vive en el servidor
 * (`/api/buscar`), así que esto sólo pinta y navega.
 */
(() => {
  const dlg = document.getElementById('paleta');
  const campo = document.getElementById('paleta-q');
  const lista = document.getElementById('paleta-res');
  const boton = document.getElementById('abrir-paleta');
  if (!dlg || !campo || !lista) return;

  let resultados = [];
  let marcado = 0;
  let peticion = 0;
  // Lo que se buscó y si la búsqueda contestó: con la lista vacía y sin
  // texto no se distinguía «no hay» de «se ha roto» (C-0354).
  let buscado = '';
  let fallo = false;

  const CLASES = {
    proyecto: 'proyecto', slot: 'slot', capacidad: 'capacidad',
    servicio: 'contenedor', conexion: 'conexión', sesion: 'sesión',
  };

  function pintar() {
    lista.textContent = '';
    if (!resultados.length) return pintarVacio();
    resultados.forEach((r, i) => {
      const li = document.createElement('li');
      if (i === marcado) li.className = 'marcado';
      const clase = document.createElement('span');
      clase.className = 'clase';
      clase.textContent = CLASES[r.clase] || r.clase;
      const titulo = document.createElement('span');
      titulo.className = 'titulo';
      titulo.textContent = r.titulo;
      const detalle = document.createElement('span');
      detalle.className = 'detalle';
      detalle.textContent = r.detalle || '';
      li.append(clase, titulo, detalle);
      li.addEventListener('click', () => ir(i));
      lista.appendChild(li);
    });
  }

  /* Una fila que no es un resultado: ni se marca ni lleva a ningún sitio.
   * Repite lo buscado, así que mientras llega la respuesta a la tecla
   * siguiente no se lee como la de ahora. */
  function pintarVacio() {
    if (!buscado) return;
    const li = document.createElement('li');
    li.className = 'vacio';
    const texto = document.createElement('span');
    texto.className = 'nada';
    texto.textContent = fallo ? 'No se pudo buscar: prueba otra vez en un momento.'
                              : `Nada con «${buscado}».`;
    li.append(texto);
    // Sólo existe donde el secretario es la voz y su panel está en la página.
    const secretario = window.HubSecretario;
    if (!fallo && secretario && typeof secretario.preguntar === 'function') {
      const q = buscado;
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'sutil';
      boton.textContent = 'Preguntárselo ' + aQuien();
      // Al pulsar y no con Enter: preguntarle llama al modelo, y un Enter
      // dado por costumbre sobre una búsqueda vacía no debe gastarlo.
      boton.addEventListener('click', () => {
        dlg.close();
        secretario.preguntar(`Busco «${q}» en el hub y la búsqueda no lo encuentra. ¿Dónde está?`);
      });
      li.append(boton);
    }
    lista.appendChild(li);
  }

  function aQuien() {
    const panel = document.getElementById('secretario-panel');
    const nombre = panel && panel.getAttribute('aria-label');
    return nombre && nombre !== 'Secretario' ? `a ${nombre}` : 'al secretario';
  }

  async function buscar() {
    const q = campo.value.trim();
    if (q.length < 2) { resultados = []; marcado = 0; buscado = ''; return pintar(); }
    // Contador de secuencia: sin él, una respuesta lenta de una consulta vieja
    // puede llegar después de una rápida y pisar resultados más nuevos.
    const mia = ++peticion;
    const r = await fetch(`/api/buscar?q=${encodeURIComponent(q)}`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    if (mia !== peticion) return;
    fallo = !Array.isArray(r);
    resultados = fallo ? [] : r;
    buscado = q;
    marcado = 0;
    pintar();
  }

  function ir(i) {
    const destino = resultados[i];
    if (destino) location.href = destino.url;
  }

  function abrir() {
    if (dlg.open) return;
    dlg.showModal();
    campo.value = '';
    resultados = [];
    buscado = '';
    pintar();
    campo.focus();
  }

  let temporizador;
  campo.addEventListener('input', () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(buscar, 120);
  });

  campo.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!resultados.length) return;
      marcado = (marcado + (e.key === 'ArrowDown' ? 1 : -1) + resultados.length) % resultados.length;
      pintar();
      lista.children[marcado]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      ir(marcado);
    }
  });

  if (boton) boton.addEventListener('click', abrir);

  /* Atajos de navegación, estilo `g` + destino.
   *
   * Van en secuencia y no con modificadores a propósito: Ctrl+ y Alt+ ya están
   * repartidos entre el navegador, tmux y Claude Code, y pelearse con ellos
   * acaba en un atajo que a veces hace otra cosa. */
  const DESTINOS = {
    p: ['/', 'Panorama'], t: ['/trabajo', 'Trabajo'], i: ['/inventario', 'Inventario'],
    r: ['/respaldo', 'Respaldo'], s: ['/servicios', 'Servicios'], c: ['/conexiones', 'Conexiones'],
    x: ['/contexto', 'Contexto'],
  };
  let esperandoDestino = false;
  let expira;

  function escribiendoAhora() {
    const activo = document.activeElement;
    // Incluye el terminal embebido: robarle una tecla arruina el comando que
    // estabas tecleando, que es la peor forma posible de fallar aquí.
    return !!activo && (
      activo.tagName === 'INPUT' || activo.tagName === 'TEXTAREA' ||
      activo.isContentEditable || (activo.closest && activo.closest('.xterm'))
    );
  }

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      return abrir();
    }
    if (e.ctrlKey || e.metaKey || e.altKey || dlg.open || escribiendoAhora()) return;

    if (esperandoDestino) {
      clearTimeout(expira);
      esperandoDestino = false;
      const destino = DESTINOS[e.key.toLowerCase()];
      if (destino) { e.preventDefault(); location.href = destino[0]; }
      return;
    }
    if (e.key === '/') { e.preventDefault(); return abrir(); }
    if (e.key === 'g') {
      esperandoDestino = true;
      // Si te quedas a medias, la secuencia se olvida sola: una tecla presa
      // indefinidamente convertiría la siguiente pulsación en un salto sorpresa.
      expira = setTimeout(() => { esperandoDestino = false; }, 1500);
      return;
    }
    if (e.key === '?') {
      e.preventDefault();
      HubUI.avisar({
        titulo: 'Atajos',
        mensaje: [
          'Ctrl+K  ·  /      buscar en todo el hub',
          'g luego p t i r s c x  ir a panorama, trabajo, inventario,',
          '                       respaldo, servicios, conexiones, contexto',
          'Alt+0..9          cambiar de ventana en la terminal',
          '?                 esta ayuda',
        ].join('\n'),
      });
    }
  });
})();
