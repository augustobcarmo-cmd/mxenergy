"""Corrida del recolector (la usa la GitHub Action; también sirve en local).

    python scripts/recolectar.py --datos datos_rama
    python scripts/recolectar.py --datos datos_rama --fuentes dof --reprocesar-dof-dias 7
    python scripts/recolectar.py --datos /tmp/prueba --sin-navegador

Escribe en GITHUB_OUTPUT: cambios, alerta, resumen.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mxenergy.recolector import correr  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Recolecta DOF y noticias en la carpeta de datos.")
    p.add_argument("--datos", required=True, help="Carpeta de la rama datos")
    p.add_argument("--fuentes", default="", help="Ids separados por coma (todas si se omite)")
    p.add_argument("--sin-navegador", action="store_true",
                   help="No usar Chromium (Energía Estratégica solo con la portada)")
    p.add_argument("--reprocesar-dof-dias", type=int, default=0,
                   help="Vuelve a descargar y clasificar el DOF de los últimos N días")
    a = p.parse_args(argv)

    solo = [f.strip() for f in a.fuentes.split(",") if f.strip()] or None
    resultado = correr(a.datos, solo=solo, usar_navegador=not a.sin_navegador,
                       reprocesar_dof_dias=a.reprocesar_dof_dias)
    r = resultado["registro"]
    fallidas = [f["id"] for f in r["fuentes"] if not f["ok"]]
    resumen = (f"{r['agregados']} nuevas, {r['actualizados']} actualizadas, "
               f"{r['reclasificados']} reclasificadas; total {r['total']}"
               + (f"; con error: {', '.join(fallidas)}" if fallidas else ""))
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"cambios={'true' if resultado['cambios'] else 'false'}\n")
            f.write(f"alerta={'true' if resultado['alertas'] else 'false'}\n")
            f.write(f"resumen={resumen}\n")
    print(resumen)
    for a_ in resultado["alertas"]:
        print(f"::error title=Fuente con fallas::{a_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
