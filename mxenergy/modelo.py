"""Forma de cada publicación guardada (DOF o noticia)."""

from __future__ import annotations

import hashlib

from mxenergy.reglas import Clasificacion

# Orden de las columnas en items.parquet. Los textos largos no se guardan:
# solo un extracto (`resumen`) y las coincidencias halladas en el cuerpo, que
# bastan para reclasificar cuando cambian las reglas.
COLUMNAS = [
    "id",            # dof:<codNota> | n:<sha1(url)>
    "tipo",          # dof | noticia
    "fuente_id",     # dof, energia_estrategica, rss…
    "fuente",        # nombre para mostrar
    "titulo",
    "url",
    "fecha",         # AAAA-MM-DD, hora de la Ciudad de México
    "hora",          # HH:MM o vacío
    "resumen",       # extracto del cuerpo (DOF) o descripción (noticia)
    "dependencia",   # DOF: dependencia u organismo que publica
    "sigla",         # DOF: sigla de la dependencia
    "poder",         # DOF: PE, PL, PJ, OA, OD, EPEM, AV…
    "edicion",       # DOF: MAT, VES, EXT
    "tipo_doc",      # DOF: DECRETO, ACUERDO, EDICTO…
    "pagina",        # DOF: página de la edición
    "region",        # noticias: México | Internacional
    "etiquetas",     # noticias: etiquetas de la fuente
    "categorias",    # ids separados por coma
    "prioridad",     # alta | media | baja | vacío
    "puntaje",
    "motivos",       # por qué aparece, separados por « · »
    "coincidencias", # términos hallados en el cuerpo, separados por « | »
    "sin_texto",     # DOF: True si no se pudo descargar el texto (se reintenta)
    "primera_vez",   # ISO, cuándo lo vio el recolector por primera vez
    "actualizado",   # ISO, última vez que cambió
]

SEP_MOTIVOS = " · "
SEP_COINC = " | "


def nuevo(**campos) -> dict:
    item = {c: None for c in COLUMNAS}
    item.update(campos)
    return item


def id_noticia(url: str) -> str:
    return "n:" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16]


def id_dof(cod_nota: int | str) -> str:
    return f"dof:{cod_nota}"


def aplicar(item: dict, c: Clasificacion) -> dict:
    item["categorias"] = ",".join(c.categorias)
    item["prioridad"] = c.prioridad
    item["puntaje"] = int(c.puntaje)
    item["motivos"] = SEP_MOTIVOS.join(c.motivos)
    item["coincidencias"] = SEP_COINC.join(c.coincidencias)
    return item


def coincidencias(item: dict) -> list[str]:
    raw = item.get("coincidencias") or ""
    return [x for x in raw.split(SEP_COINC) if x]


def categorias(item: dict) -> list[str]:
    raw = item.get("categorias") or ""
    return [x for x in raw.split(",") if x]
