"""Migra las noticias de la versión local anterior (C:\\mxenergy\\data\\mxenergy.db).

Solo las fuentes que siguen activas; el DOF no se migra porque el recolector
lo completa desde el SIDOF (fuente oficial, con avisos y ediciones
extraordinarias), y las redes de las dependencias y los despachos se retiraron.

    python scripts/migrar_sqlite.py --db mxenergy.db --datos datos_rama
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mxenergy import modelo, tiempo  # noqa: E402
from mxenergy.almacen import Almacen  # noqa: E402
from mxenergy.recolector import fusionar  # noqa: E402
from mxenergy.reglas import Reglas  # noqa: E402
from mxenergy.texto import recortar  # noqa: E402

FUENTES = {
    "Energía Estratégica": "energia_estrategica",
    "Global Energy": "global_energy",
    "Mexico Business News": "mbn",
    "PV Magazine México": "pv_magazine",
    "Energía a Debate": "energia_a_debate",
    "Energy News MX": "energy_news",
    "Energy21": "energy21",
}


def migrar(db: Path, datos: Path) -> dict:
    reglas = Reglas.cargar()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    filas = con.execute(
        "SELECT source, title, url, published_at, published_date, raw_text, created_at "
        "FROM items WHERE source_type='noticia' ORDER BY published_at").fetchall()
    nuevos, omitidas = [], 0
    for f in filas:
        fid = FUENTES.get(f["source"])
        if not fid:
            omitidas += 1
            continue
        publicado = tiempo.a_local(datetime.fromisoformat(f["published_at"]))
        resumen = recortar(f["raw_text"] or "", 400) or None
        c = reglas.clasificar(f["title"], f["raw_text"] or "", es_noticia=True)
        region = None
        if fid == "energia_estrategica":
            region = "México" if reglas.es_mexico(f["title"], f["raw_text"]) else "Internacional"
        item = modelo.nuevo(
            id=modelo.id_noticia(f["url"]), tipo="noticia", fuente_id=fid, fuente=f["source"],
            titulo=" ".join(f["title"].split()), url=f["url"], fecha=publicado.date().isoformat(),
            hora=publicado.strftime("%H:%M"), resumen=resumen, region=region,
            primera_vez=f["created_at"],
        )
        nuevos.append(modelo.aplicar(item, c))
    alm = Almacen(datos)
    items = alm.items()
    agregados, actualizados = fusionar(items, nuevos, tiempo.ahora().isoformat(timespec="seconds"))
    alm.guardar_items(items)
    return {"leidas": len(filas), "migradas": len(nuevos), "omitidas": omitidas,
            "agregados": agregados, "actualizados": actualizados, "total": len(items)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--datos", required=True)
    a = p.parse_args(argv)
    print(migrar(Path(a.db), Path(a.datos)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
