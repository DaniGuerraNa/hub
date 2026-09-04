#!/usr/bin/env bash
# Simula a una persona sin contexto. Corre DENTRO del contenedor.
#
#   persona.sh <carpeta> <etiqueta> "<petición>"
#
# Hace UNA petición a Claude Code en esa carpeta y, cada vez que el turno
# termina en una pregunta, contesta «sí, adelante» y sigue, hasta ocho turnos.
# El transcript queda en ~/salas/<etiqueta>.log, un bloque por turno.
#
# Cómo se lee:
#   - cada turno después del primero es una PREGUNTA que la persona tuvo que
#     contestar: cuéntalos;
#   - un «sí» no contesta una elección A/B: si la skill la plantea, la persona
#     se atasca y el transcript lo enseña repitiendo la pregunta. Eso también es
#     un hallazgo — la skill tenía un default y no lo tomó;
#   - un turno que termina sin pregunta es donde una persona real se quedaría
#     esperando: comprueba que lo prometido está hecho (curl, ls, tmux ls).
#
# RESPUESTA cambia lo que contesta la persona en cada parada, por si quieres
# medir otra actitud («no», «haz lo mínimo», «A»).
set -u
RESPUESTA=${RESPUESTA:-sí, adelante}
MODELO=${MODELO:-sonnet}
mkdir -p ~/salas; cd "$1" || exit 1; L=~/salas/$2.log; : > "$L"
echo "### PETICIÓN: $3" >> "$L"
salida=$(claude -p --model "$MODELO" --dangerously-skip-permissions "$3" 2>&1); rc=$?
{ echo "### TURNO 1 (rc=$rc)"; echo "$salida"; } | tee -a "$L"
for i in 2 3 4 5 6 7 8; do
  if ! echo "$salida" | tail -6 | grep -q "?"; then
    echo "### FIN sin pregunta en el turno $((i-1))" | tee -a "$L"; exit 0
  fi
  salida=$(claude -p --model "$MODELO" --dangerously-skip-permissions --continue "$RESPUESTA" 2>&1); rc=$?
  { echo "### TURNO $i (rc=$rc)"; echo "$salida"; } | tee -a "$L"
done
echo "### CORTADO en el turno 8: sigue preguntando" | tee -a "$L"
