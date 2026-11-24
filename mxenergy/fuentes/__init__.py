"""Recolectores. Cada uno devuelve publicaciones (dicts de `modelo.COLUMNAS`)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from mxenergy.red import Red
from mxenergy.reglas import Reglas


@dataclass
class Contexto:
    red: Red
    reglas: Reglas
    hoy: date
    ahora: datetime
    estado: dict                      # estado persistente (rama datos, estado.json)
    existentes: dict[str, dict]       # publicaciones ya guardadas, por id
    ventana_desde: date               # noticias: se guarda lo publicado desde aquí
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("mxenergy"))
    usar_navegador: bool = True


class Fuente:
    id = ""
    nombre = ""
    tipo = "noticia"
    prioridad = 2

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.detalles: dict = {}      # para el registro de la corrida
        self.avisos: list[str] = []   # problemas no fatales

    def recolectar(self, ctx: Contexto) -> list[dict]:  # pragma: no cover
        raise NotImplementedError


def construir(cfg_fuentes: dict, solo: list[str] | None = None) -> list[Fuente]:
    """Instancia las fuentes activas de config/fuentes.yaml."""
    from mxenergy.fuentes.dof import FuenteDOF
    from mxenergy.fuentes.energia_estrategica import FuenteEE
    from mxenergy.fuentes.mbn import FuenteMBN
    from mxenergy.fuentes.rss import FuenteRSS

    tipos = {"energia_estrategica": FuenteEE, "rss": FuenteRSS, "mbn": FuenteMBN}
    fuentes: list[Fuente] = []
    dof_cfg = cfg_fuentes.get("dof") or {}
    if dof_cfg.get("activa", True):
        fuentes.append(FuenteDOF(dof_cfg))
    for f in (cfg_fuentes.get("noticias") or {}).get("fuentes") or []:
        if not f.get("activa", True):
            continue
        clase = tipos.get(f.get("tipo"))
        if clase is None:
            logging.getLogger("mxenergy").warning("Tipo de fuente desconocido: %s", f.get("tipo"))
            continue
        fuentes.append(clase(f))
    if solo:
        fuentes = [f for f in fuentes if f.id in solo]
    return fuentes
