"""Una corrida completa: recolectar, clasificar, fusionar, guardar y registrar.

Cada fuente corre aislada: si una falla, las demás siguen y la falla queda en
el estado de la fuente, en el registro de corridas y en el log. Nada se pierde
en silencio: una fuente crítica que falla varias corridas seguidas levanta
una alerta (la Action la convierte en corrida roja y GitHub manda un correo).
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from mxenergy import modelo, tiempo
from mxenergy.almacen import Almacen
from mxenergy.fuentes import Contexto, construir
from mxenergy.red import Red
from mxenergy.reglas import RAIZ, Reglas
from mxenergy.texto import normalizar

RUTA_FUENTES = RAIZ / "config" / "fuentes.yaml"
log = logging.getLogger("mxenergy")


class _HoraLocal(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802
        return datetime.fromtimestamp(record.created, tiempo.TZ).strftime(datefmt or "%H:%M:%S")


def configurar_log(memoria: io.StringIO, nivel=logging.INFO) -> None:
    log.setLevel(logging.DEBUG)
    log.propagate = False
    for h in list(log.handlers):
        log.removeHandler(h)
    formato = _HoraLocal("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
    for destino, lvl in ((sys.stdout, nivel), (memoria, logging.DEBUG)):
        h = logging.StreamHandler(destino)
        h.setLevel(lvl)
        h.setFormatter(formato)
        log.addHandler(h)


def cargar_config(ruta: Path | None = None) -> dict:
    return yaml.safe_load(Path(ruta or RUTA_FUENTES).read_text(encoding="utf-8")) or {}


def fusionar(items: dict[str, dict], nuevos: list[dict], marca: str) -> tuple[int, int]:
    """Agrega o actualiza; conserva `primera_vez`. Devuelve (agregados, actualizados)."""
    agregados = actualizados = 0
    ignorar = {"primera_vez", "actualizado"}
    for it in nuevos:
        viejo = items.get(it["id"])
        if viejo is None:
            it["primera_vez"] = it.get("primera_vez") or marca
            it["actualizado"] = marca
            items[it["id"]] = it
            agregados += 1
            continue
        if any((viejo.get(k) or None) != (it.get(k) or None)
               for k in modelo.COLUMNAS if k not in ignorar):
            it["primera_vez"] = viejo.get("primera_vez") or marca
            it["actualizado"] = marca
            items[it["id"]] = it
            actualizados += 1
    return agregados, actualizados


def reclasificar(items: dict[str, dict], reglas: Reglas, marca: str) -> int:
    """Aplica las reglas vigentes a todo el historial. Devuelve cuántas cambiaron.

    El DOF se reclasifica con el título, el extracto y las coincidencias que se
    hallaron en su texto; un término nuevo que solo aparezca en el cuerpo se
    aplica hacia adelante (o con `--reprocesar-dof-dias`).
    """
    cambios = 0
    for it in items.values():
        if it.get("tipo") == "dof":
            frag = [normalizar(it.get("resumen"))] + modelo.coincidencias(it)
            c = reglas.clasificar(it.get("titulo") or "", frag, dependencia=it.get("dependencia"),
                                  es_edicto=it.get("tipo_doc") == "EDICTO", normalizado=True)
        else:
            texto = " ".join(filter(None, [it.get("resumen"), it.get("etiquetas")]))
            c = reglas.clasificar(it.get("titulo") or "", texto)
        antes = (it.get("categorias"), it.get("prioridad"), it.get("puntaje"), it.get("motivos"))
        modelo.aplicar(it, c)
        if it.get("tipo") == "dof":
            it["sigla"] = reglas.sigla(it.get("dependencia"))
        if antes != (it.get("categorias"), it.get("prioridad"), it.get("puntaje"), it.get("motivos")):
            it["actualizado"] = marca
            cambios += 1
    return cambios


def marcar_reproceso(items: dict[str, dict], estado: dict, hoy: date, dias_atras: int) -> int:
    """Hace que el DOF de los últimos N días se vuelva a descargar y clasificar."""
    if dias_atras <= 0:
        return 0
    desde = (hoy - timedelta(days=dias_atras - 1)).isoformat()
    n = 0
    for it in items.values():
        if it.get("tipo") == "dof" and (it.get("fecha") or "") >= desde:
            it["sin_texto"] = True
            n += 1
    for d, reg in (estado.get("dof_dias") or {}).items():
        if d >= desde:
            reg["estado"] = "reproceso"
    return n


def salud_por_fuente(items: dict[str, dict], hoy: date) -> dict[str, dict]:
    hace7 = (hoy - timedelta(days=6)).isoformat()
    out: dict[str, dict] = {}
    for it in items.values():
        s = out.setdefault(it.get("fuente_id") or "?", {"ultimo_item": "", "items_7d": 0, "total": 0})
        f = it.get("fecha") or ""
        s["total"] += 1
        if f > s["ultimo_item"]:
            s["ultimo_item"] = f
        if f >= hace7:
            s["items_7d"] += 1
    return out


def correr(datos: Path | str, solo: list[str] | None = None, usar_navegador: bool = True,
           hoy: date | None = None, reprocesar_dof_dias: int = 0,
           config: Path | None = None, reglas_ruta: Path | None = None,
           red: Red | None = None) -> dict:
    memoria = io.StringIO()
    configurar_log(memoria)
    t0 = time.monotonic()
    inicio = tiempo.ahora()
    marca = inicio.isoformat(timespec="seconds")
    hoy = hoy or inicio.date()

    reglas = Reglas.cargar(reglas_ruta)
    cfg = cargar_config(config)
    alm = Almacen(datos)
    items = alm.items()
    estado = alm.leer_json("estado.json", {})
    cache = alm.leer_json("cache.json", {})
    log.info("Corrida %s · reglas %s · %d publicaciones guardadas", marca, reglas.version, len(items))

    persistente = {"dof_dias": estado.get("dof_dias") or {},
                   "ee_fechas": cache.get("ee_fechas") or {},
                   "mbn_fechas": cache.get("mbn_fechas") or {}}
    if reprocesar_dof_dias:
        n = marcar_reproceso(items, persistente, hoy, reprocesar_dof_dias)
        log.info("Reproceso: %d notas del DOF de los últimos %d días", n, reprocesar_dof_dias)

    ventana = int((cfg.get("noticias") or {}).get("ventana_dias", 4))
    red = red or Red()
    ctx = Contexto(red=red, reglas=reglas, hoy=hoy, ahora=inicio, estado=persistente,
                   existentes=items, ventana_desde=hoy - timedelta(days=ventana - 1),
                   log=log, usar_navegador=usar_navegador)

    salud = estado.setdefault("fuentes", {})
    resultados, agregados_tot, actualizados_tot = [], 0, 0
    for fuente in construir(cfg, solo):
        t = time.monotonic()
        error = None
        try:
            nuevos = fuente.recolectar(ctx)
        except Exception as e:  # noqa: BLE001 — una fuente no tumba la corrida
            nuevos = []
            error = f"{type(e).__name__}: {e}"
            log.error("%s falló: %s", fuente.nombre, error, exc_info=log.isEnabledFor(logging.DEBUG))
        agregados, actualizados = fusionar(items, nuevos, marca)
        agregados_tot += agregados
        actualizados_tot += actualizados
        seg = round(time.monotonic() - t, 1)
        s = salud.setdefault(fuente.id, {})
        s.update({"nombre": fuente.nombre, "tipo": fuente.tipo, "prioridad": fuente.prioridad,
                  "ultima_corrida": marca, "encontrados": len(nuevos), "agregados": agregados,
                  "segundos": seg, "avisos": fuente.avisos[:5], "detalles": fuente.detalles})
        if error:
            s["fallas_seguidas"] = int(s.get("fallas_seguidas", 0)) + 1
            s["ultimo_error"] = {"cuando": marca, "mensaje": error[:400]}
        else:
            s["fallas_seguidas"] = 0
            s["ultima_ok"] = marca
        for aviso in fuente.avisos:
            log.warning("%s: %s", fuente.nombre, aviso)
        log.info("%s: %d encontradas, %d nuevas, %d actualizadas (%.1f s)%s", fuente.nombre,
                 len(nuevos), agregados, actualizados, seg, f" — ERROR {error}" if error else "")
        resultados.append({"id": fuente.id, "ok": error is None, "encontrados": len(nuevos),
                           "agregados": agregados, "actualizados": actualizados,
                           "segundos": seg, "error": error, "avisos": fuente.avisos[:5]})

    reclasificados = 0
    if estado.get("version_reglas") != reglas.version:
        reclasificados = reclasificar(items, reglas, marca)
        log.info("Reglas nuevas (%s → %s): %d publicaciones reclasificadas",
                 estado.get("version_reglas") or "—", reglas.version, reclasificados)
        estado["version_reglas"] = reglas.version

    for fid, s in salud_por_fuente(items, hoy).items():
        salud.setdefault(fid, {}).update(s)
    estado["dof_dias"] = persistente["dof_dias"]
    estado["actualizado"] = marca
    alm.guardar_items(items)
    alm.escribir_json("estado.json", estado)
    alm.escribir_json("cache.json", {"ee_fechas": persistente["ee_fechas"],
                                     "mbn_fechas": persistente["mbn_fechas"]})

    alertas = []
    for fid, umbral in (cfg.get("alertas") or {}).items():
        s = salud.get(fid) or {}
        if int(s.get("fallas_seguidas", 0)) >= int(umbral):
            alertas.append(f"{s.get('nombre', fid)} lleva {s['fallas_seguidas']} corridas con error: "
                           f"{(s.get('ultimo_error') or {}).get('mensaje', '')[:200]}")
    fechas = [it.get("fecha") for it in items.values() if it.get("fecha")]
    fin = tiempo.ahora()
    registro = {
        "inicio": marca, "fin": fin.isoformat(timespec="seconds"),
        "segundos": round(time.monotonic() - t0, 1),
        "evento": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "version_reglas": reglas.version, "total": len(items),
        "agregados": agregados_tot, "actualizados": actualizados_tot,
        "reclasificados": reclasificados, "peticiones": red.peticiones,
        "fuentes": resultados, "alertas": alertas,
    }
    alm.escribir_json("meta.json", {
        "actualizado": marca, "total": len(items), "desde": min(fechas, default=None),
        "hasta": max(fechas, default=None), "version_reglas": reglas.version,
        "ultima_corrida": {k: registro[k] for k in ("inicio", "segundos", "agregados", "alertas")},
    })
    alm.agregar_ejecucion(registro)
    for a in alertas:
        log.error("ALERTA: %s", a)
    log.info("Fin: %d publicaciones (%d nuevas, %d actualizadas, %d reclasificadas) en %.0f s, "
             "%d peticiones", len(items), agregados_tot, actualizados_tot, reclasificados,
             registro["segundos"], red.peticiones)
    alm.guardar_log(memoria.getvalue(), inicio)
    return {"registro": registro, "alertas": alertas,
            "cambios": bool(agregados_tot or actualizados_tot or reclasificados)}
