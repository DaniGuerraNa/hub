"""Modelos tipados. Dan al agente de mantenimiento una forma explícita que respetar."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Dominio = Literal["personal", "laboral"]
Guardrail = Literal["auto", "ask", "never"]
EstadoProyecto = Literal["activo", "pausado", "archivado"]
EstadoSlot = Literal["activo", "archivado"]
TipoRuta = Literal["asiento", "repo"]


class Ruta(BaseModel):
    ruta: str
    tipo: TipoRuta = "repo"


class Proyecto(BaseModel):
    """El dominio es un ATRIBUTO con filtro, no un muro (decisión 20)."""

    id: str
    nombre: str
    dominio: Dominio = "personal"
    # Un kit es un proyecto que otros consumen: además de sus capacidades,
    # aporta dependencias declaradas en `consumidores/`.
    # `asistente` marca el proyecto que el hub pinta como chat en vez de como
    # terminal. Va aquí y no en una ruta cableada para que mudarlo sea editar
    # una línea de YAML (decisión 75). Sólo puede haber uno; manda el primero.
    tipo: Literal["proyecto", "kit", "asistente"] = "proyecto"
    asiento: str | None = None
    rutas: list[Ruta] = Field(default_factory=list)
    estado_ref: str | None = None
    base_version: str | None = None
    guardrail: Guardrail = "ask"
    status: EstadoProyecto = "activo"
    nota: str = ""
    # Prefijos de nombre de contenedor Docker que pertenecen a este proyecto.
    # La atribución arranca por prefijo y se corrige a mano aquí: en el
    # Docker del usuario conviven contenedores de cinco proyectos distintos.
    contenedores: list[str] = Field(default_factory=list)

    def todas_las_rutas(self) -> list[str]:
        rutas = [r.ruta for r in self.rutas]
        if self.asiento:
            rutas.append(self.asiento)
        return rutas


class Slot(BaseModel):
    """Línea de trabajo con nombre. La ruta es un atributo, no la identidad (decisión 10).

    Es lo que permite que una nota larga sobreviva a un crash: los IDs de panel de
    tmux no sobreviven al reinicio del servidor, y varios paneles comparten la raíz
    del repo, así que ni el panel ni la ruta sirven como clave.
    """

    id: int | None = None
    proyecto_id: str
    nombre: str
    ruta: str | None = None
    nota: str = ""
    comando: str | None = None
    autostart_claude: bool = False
    status: EstadoSlot = "activo"
    creado_en: datetime | None = None
    ultima_actividad: datetime | None = None


class Panel(BaseModel):
    """Lo que el snapshotter observa. Efímero por naturaleza."""

    pane_id: str
    session: str
    window: int
    pane: int
    cwd: str
    titulo: str
    comando: str
    etiqueta: str
    proyecto_id: str | None = None
    slot_id: int | None = None
    activo: bool = False


class Snapshot(BaseModel):
    id: int | None = None
    tomado_en: datetime
    server_pid: int | None = None
    paneles: list[Panel] = Field(default_factory=list)
    preservado: bool = False


class Conexion(BaseModel):
    """Dónde despliega algo y dónde vive su credencial — nunca la credencial.

    `referencia_secreto` es un PUNTERO (`~/.ssh/config#vps-pruebas`). El hub no
    almacena secretos (decisión 28): sólo comprueba que el puntero exista.
    """

    alias: str
    host: str | None = None
    usuario: str | None = None
    proposito: str = ""
    proyectos: list[str] = Field(default_factory=list)
    referencia_secreto: str | None = None
    nota: str = ""
