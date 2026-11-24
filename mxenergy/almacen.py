"""Almacén de la rama `datos`: publicaciones, estado, registro de corridas y logs.

Estructura de la carpeta:
    items.parquet        todas las publicaciones (DOF y noticias)
    meta.json            resumen ligero para la app (última actualización, totales)
    estado.json          salud de cada fuente y cobertura del DOF por día
    cache.json           fechas ya leídas de Energía Estratégica y MBN
    ejecuciones.jsonl    una línea por corrida (las últimas 1,000)
    logs/                log completo de las últimas corridas
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from mxenergy.modelo import COLUMNAS

ESQUEMA_ENTEROS = {"pagina", "puntaje"}
ESQUEMA_BOOL = {"sin_texto"}


def _esquema():
    import pyarrow as pa

    campos = []
    for c in COLUMNAS:
        if c in ESQUEMA_ENTEROS:
            campos.append((c, pa.int32()))
        elif c in ESQUEMA_BOOL:
            campos.append((c, pa.bool_()))
        else:
            campos.append((c, pa.string()))
    return pa.schema(campos)


def _coercer(item: dict) -> dict:
    fila = {}
    for c in COLUMNAS:
        v = item.get(c)
        if v is None or (isinstance(v, float) and v != v):
            fila[c] = None
        elif c in ESQUEMA_ENTEROS:
            try:
                fila[c] = int(v)
            except (TypeError, ValueError):
                fila[c] = None
        elif c in ESQUEMA_BOOL:
            fila[c] = bool(v)
        else:
            fila[c] = str(v)
    return fila


class Almacen:
    def __init__(self, carpeta: Path | str):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def ruta(self, nombre: str) -> Path:
        return self.carpeta / nombre

    # --- publicaciones -------------------------------------------------------

    def items(self) -> dict[str, dict]:
        ruta = self.ruta("items.parquet")
        if not ruta.exists():
            return {}
        import pyarrow.parquet as pq

        filas = pq.read_table(ruta).to_pylist()
        return {f["id"]: {c: f.get(c) for c in COLUMNAS} for f in filas}

    def guardar_items(self, items: dict[str, dict]) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        filas = sorted((_coercer(i) for i in items.values()),
                       key=lambda f: (f["fecha"] or "", f["tipo"] or "", f["id"]), reverse=True)
        tabla = pa.Table.from_pylist(filas, schema=_esquema())
        tmp = self.ruta("items.parquet.tmp")
        pq.write_table(tabla, tmp, compression="zstd")
        os.replace(tmp, self.ruta("items.parquet"))

    # --- json -------------------------------------------------------------------

    def leer_json(self, nombre: str, defecto=None):
        ruta = self.ruta(nombre)
        if not ruta.exists():
            return {} if defecto is None else defecto
        return json.loads(ruta.read_text(encoding="utf-8"))

    def escribir_json(self, nombre: str, obj) -> None:
        ruta = self.ruta(nombre)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(ruta.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, ruta)

    # --- corridas y logs -------------------------------------------------------

    def ejecuciones(self) -> list[dict]:
        ruta = self.ruta("ejecuciones.jsonl")
        if not ruta.exists():
            return []
        out = []
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea:
                try:
                    out.append(json.loads(linea))
                except ValueError:
                    continue
        return out

    def agregar_ejecucion(self, registro: dict, maximo: int = 1000) -> None:
        todas = (self.ejecuciones() + [registro])[-maximo:]
        texto = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in todas)
        self.ruta("ejecuciones.jsonl").write_text(texto + "\n", encoding="utf-8")

    def guardar_log(self, texto: str, marca: datetime, conservar: int = 40) -> Path:
        carpeta = self.ruta("logs")
        carpeta.mkdir(exist_ok=True)
        ruta = carpeta / f"{marca:%Y-%m-%d_%H%M}.log"
        ruta.write_text(texto, encoding="utf-8")
        (carpeta / "ultima.log").write_text(texto, encoding="utf-8")
        viejos = sorted(p for p in carpeta.glob("*.log") if p.name != "ultima.log")
        for p in viejos[:-conservar]:
            p.unlink()
        return ruta
