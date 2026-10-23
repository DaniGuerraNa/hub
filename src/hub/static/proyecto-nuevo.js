/* «Proyecto nuevo»: el diálogo que da de alta un proyecto vacío y lo monta.
 *
 * Vive aquí y no en index.html porque hace falta en dos sitios: en Panorama y
 * en Trabajo. En Trabajo no estaba, y es donde lo buscó la primera persona que
 * usó el hub sin que nadie se lo enseñara: entró, no vio cómo crear un
 * proyecto y creyó que sólo se podía pidiéndoselo al asistente (22-oct).
 *
 * Cualquier botón con `data-nuevo-proyecto` lo abre.
 */
document.addEventListener('click', async (e) => {
  if (!e.target.closest || !e.target.closest('[data-nuevo-proyecto]')) return;
  const boton = e.target.closest('[data-nuevo-proyecto]');

  const datos = await HubUI.formulario({
    titulo: 'Proyecto nuevo',
    aceptar: 'Crear y montar',
    campos: [
      { nombre: 'nombre', etiqueta: 'Nombre', requerido: true,
        marca: 'Mi proyecto', pista: 'La etiqueta que se pinta. Se puede cambiar después.' },
      { nombre: 'id', etiqueta: 'Identificador', requerido: true,
        marca: 'mi-proyecto', patron: '[a-z0-9][a-z0-9-]*',
        pista: 'Minúsculas, números y guiones. 🔴 No se puede cambiar después: los slots y las notas cuelgan de él.' },
      { nombre: 'ruta', etiqueta: 'Carpeta del proyecto', requerido: true,
        marca: '~/dev/mi-proyecto',
        pista: 'Absoluta, y vacía o inexistente. Si ya tiene contenido, lo que buscas es «anexa mi proyecto».' },
      // El caso de quien tiene repos que NO puede tocar —de otro equipo, o con
      // sus propias reglas—: la carpeta de arriba pasa a ser sólo el asiento
      // desde el que se orquesta, y estos se declaran para medirlos. El permiso
      // del agente se acota al asiento, así que quedan medibles y no escribibles.
      { nombre: 'rutas', etiqueta: 'Repos que ya existen (opcional)', multilinea: true,
        marca: '/ruta/al/repo-uno\n/ruta/al/repo-dos',
        pista: 'Una por línea, absolutas. Si el código vive fuera, decláralo aquí: la carpeta de arriba queda como asiento desde el que orquestas, y estos repos se miden pero NO se tocan. Lo que no se declara, no se mide.' },
      { nombre: 'dominio', etiqueta: 'Dominio', valor: 'personal',
        opciones: [['personal', 'Personal'], ['laboral', 'Laboral']] },
      { nombre: 'guardrail', etiqueta: 'Permiso para el agente', valor: 'ask',
        opciones: [['ask', 'Preguntar (ask)'], ['auto', 'Automático (auto)'],
                   ['never', 'Nunca (never) — crea el proyecto y no lanza nada']] },
    ],
    nota: 'El hub crea la carpeta vacía, la acota con permisos y da el alta. '
        + 'El contenido lo escribe un agente dentro de esa carpeta, y sólo ahí. '
        + 'Lo verás trabajar en /trabajo.',
  });
  if (!datos) return;

  const etiqueta = boton.textContent;
  boton.disabled = true;
  boton.textContent = 'creando…';
  const r = await fetch('/api/proyecto/nuevo', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  }).then((r) => r.json()).catch(() => ({ ok: false, error: 'sin conexión con el hub' }));

  boton.disabled = false;
  boton.textContent = etiqueta;

  if (!r.ok) {
    return HubUI.avisar({
      titulo: r.ocupada ? 'Esa carpeta ya tiene contenido' : 'No se pudo crear',
      mensaje: r.error || 'error desconocido',
    });
  }
  // 🔴 Con `never` el proyecto queda creado y NADIE lo monta. Decirlo importa:
  // sin este aviso el usuario ve que no se abre ninguna ventana y da por hecho
  // que ha fallado, cuando lo que tiene es un proyecto vacío ya registrado.
  if (!r.agente) {
    await HubUI.avisar({ titulo: `«${r.id}» creado, sin agente`, mensaje: r.aviso });
    return location.reload();
  }
  location.href = `/trabajo?session=${encodeURIComponent(r.session)}&ventana=${r.ventana}`;
});
