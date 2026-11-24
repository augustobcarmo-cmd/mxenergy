"""Lectura de la rama `datos` y filtros para la app (sin Streamlit, para probarlos)."""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from mxenergy.modelo import COLUMNAS
from mxenergy.texto import normalizar

REPO = os.environ.get("MXENERGY_REPO", "augustobcarmo-cmd/mxenergy")
RAMA = os.environ.get("MXENERGY_RAMA", "datos")
FUENTE_PRINCIPAL = "energia_estrategica"
NUCLEO = {"electricidad", "almacenamiento", "transmision", "industria"}
ORDEN_PRIORIDAD = {"alta": 0, "media": 1, "baja": 2, "": 3}
NOMBRE_EDICION = {"MAT": "Matutina", "VES": "Vespertina", "EXT": "Extraordinaria"}
_TIPOS_DOC = {"RESOLUCION": "Resolución", "INDICE": "Índice", "CODIGO": "Código",
              "ACLARACION": "Aclaración", "MODIFICACION": "Modificación", "FE DE ERRATAS": "Fe de erratas",
              "DACG": "DACG", "NOM": "NOM", "PROY-NOM": "Proyecto de NOM", "LEY": "Ley"}


def tipo_doc(t: str) -> str:
    """Nombre para mostrar del tipo de publicación del DOF."""
    return _TIPOS_DOC.get(t, t.capitalize()) if t else ""


def resumen_util(titulo: str, resumen: str) -> str:
    """El resumen si dice algo más que el título (en varios medios lo repite)."""
    if not resumen:
        return ""
    t, r = normalizar(titulo), normalizar(resumen)
    if not r or r.startswith(t[:80]) or t.startswith(r[:80]):
        return ""
    return resumen


def url_raw(nombre: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{RAMA}/{nombre}"


def url_repo(ruta: str = "") -> str:
    return f"https://github.com/{REPO}{ruta}"


@dataclass
class Datos:
    items: pd.DataFrame
    meta: dict = field(default_factory=dict)
    estado: dict = field(default_factory=dict)
    ejecuciones: list = field(default_factory=list)
    origen: str = ""


def _leer(nombre: str, local: Path | None) -> bytes | None:
    if local is not None:
        ruta = local / nombre
        return ruta.read_bytes() if ruta.exists() else None
    import requests

    r = requests.get(url_raw(nombre), timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def cargar(carpeta: str | Path | None = None) -> Datos:
    """Publicaciones y estado: de una carpeta local (MXENERGY_DATOS) o de GitHub."""
    carpeta = carpeta or os.environ.get("MXENERGY_DATOS")
    local = Path(carpeta) if carpeta else None
    crudo = _leer("items.parquet", local)
    items = (pd.read_parquet(io.BytesIO(crudo)) if crudo
             else pd.DataFrame(columns=COLUMNAS))
    for c in COLUMNAS:
        if c not in items.columns:
            items[c] = None
    texto = ["titulo", "fuente", "fuente_id", "fecha", "hora", "resumen", "dependencia", "sigla",
             "edicion", "tipo_doc", "region", "etiquetas", "categorias", "prioridad", "motivos", "url"]
    for c in texto:
        items[c] = items[c].fillna("").astype(str)
    items["puntaje"] = pd.to_numeric(items["puntaje"], errors="coerce").fillna(0).astype(int)

    def js(nombre, defecto):
        b = _leer(nombre, local)
        return json.loads(b.decode("utf-8")) if b else defecto

    ejec = []
    b = _leer("ejecuciones.jsonl", local)
    if b:
        for ln in b.decode("utf-8").splitlines():
            try:
                ejec.append(json.loads(ln))
            except ValueError:
                pass
    return Datos(items=items, meta=js("meta.json", {}), estado=js("estado.json", {}),
                 ejecuciones=ejec, origen=str(local) if local else url_raw(""))


# --- filtros -------------------------------------------------------------------

def en_periodo(df: pd.DataFrame, desde: date, hasta: date) -> pd.DataFrame:
    return df[(df["fecha"] >= desde.isoformat()) & (df["fecha"] <= hasta.isoformat())]


def con_categorias(df: pd.DataFrame, categorias: list[str] | None) -> pd.DataFrame:
    if not categorias:
        return df
    elegidas = set(categorias)
    return df[df["categorias"].map(lambda s: bool(elegidas & set(filter(None, s.split(",")))))]


def buscar(df: pd.DataFrame, consulta: str) -> pd.DataFrame:
    """Todas las palabras (sin acentos ni mayúsculas) en título, resumen, dependencia…"""
    palabras = normalizar(consulta).split()
    if not palabras:
        return df
    campos = (df["titulo"] + " " + df["resumen"] + " " + df["dependencia"] + " " + df["sigla"]
              + " " + df["etiquetas"] + " " + df["fuente"] + " " + df["motivos"]).map(normalizar)
    mascara = pd.Series(True, index=df.index)
    for p in palabras:
        mascara &= campos.str.contains(p, regex=False)
    return df[mascara]


def solo_hidrocarburos(categorias: str) -> bool:
    cats = set(filter(None, categorias.split(",")))
    return "hidrocarburos" in cats and not (cats & NUCLEO)


def ordenar_dof(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(_o=df["prioridad"].map(ORDEN_PRIORIDAD).fillna(3)).sort_values(
        ["_o", "puntaje", "fecha", "titulo"], ascending=[True, False, False, True]).drop(columns="_o")


def ordenar_noticias(df: pd.DataFrame, prioridad_fuente: dict[str, int]) -> pd.DataFrame:
    """Lo más útil primero: fuente prioritaria, México, categorías del núcleo, lo reciente."""
    def puntos(r):
        cats = set(filter(None, r["categorias"].split(",")))
        p = r["puntaje"] + (2 if r["region"] == "México" else 0)
        p += 1 if cats & NUCLEO else 0
        p -= 2 if solo_hidrocarburos(r["categorias"]) else 0
        return p
    if df.empty:
        return df
    return df.assign(
        _f=df["fuente_id"].map(lambda f: prioridad_fuente.get(f, 9)),
        _p=df.apply(puntos, axis=1),
    ).sort_values(["_f", "_p", "fecha", "hora"], ascending=[True, False, False, False]).drop(
        columns=["_f", "_p"])
