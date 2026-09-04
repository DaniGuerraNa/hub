# Sala limpia: lo que ve una persona que instala el hub o un kit por primera vez.
#
# Ubuntu recién instalado con SÓLO lo que pide el doctor (git, tmux, uv, Claude
# Code) y un usuario nuevo sin `~/.claude`, sin memoria, sin skills de usuario y
# sin tmux abierto. Todo lo que aquí falle es lo que le fallaría a quien clone.
#
# Se construye una vez (`bash scripts/sala-limpia/sala.sh construir`) y se
# reutiliza; cada prueba arranca un contenedor nuevo desde esta imagen.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git tmux curl ca-certificates python3 sudo ripgrep locales \
    && locale-gen es_ES.UTF-8 && rm -rf /var/lib/apt/lists/*
# Un usuario normal, no root: `claude --dangerously-skip-permissions` se niega
# a correr como root, y tmux y systemd tampoco se comportan igual.
RUN useradd -m -s /bin/bash persona && echo "persona ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/persona
USER persona
WORKDIR /home/persona
ENV HOME=/home/persona LANG=es_ES.UTF-8 PATH=/home/persona/.local/bin:$PATH
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
RUN curl -fsSL https://claude.ai/install.sh | bash
