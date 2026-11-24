"""Medios con RSS (WordPress): Global Energy, PV Magazine México, Energía a
Debate, Energy News MX, Energy21.

Casi todos los feeds guardan unas 10 notas (uno o dos días), así que se pagina
(`?paged=2`, `3`…) hasta pasar el inicio de la ventana. Sin eso, el lunes
perdería lo del viernes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mxenergy import modelo
from mxenergy.fuentes import Contexto, Fuente
from mxenergy.texto import html_a_texto, recortar
from mxenergy.tiempo import a_local

MAX_PAGINAS = 12


def leer_feed(contenido: bytes) -> list[dict]:
    """Entradas del feed: título, enlace, fecha local, resumen y etiquetas."""
    import feedparser

    out = []
    for e in feedparser.parse(contenido).entries:
        st = e.get("published_parsed") or e.get("updated_parsed")
        titulo = " ".join((e.get("title") or "").split())
        enlace = (e.get("link") or "").strip()
        if not st or not titulo or not enlace:
            continue
        publicado = a_local(datetime(*st[:6], tzinfo=timezone.utc))
        resumen = e.get("summary") or e.get("description") or ""
        if "<" in resumen:
            resumen = html_a_texto(resumen)
        etiquetas = [t.get("term") for t in e.get("tags") or [] if t.get("term")]
        out.append({"titulo": titulo, "url": enlace, "publicado": publicado,
                    "resumen": recortar(resumen, 400), "etiquetas": etiquetas})
    return out


class FuenteRSS(Fuente):
    tipo = "noticia"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        self.id = self.cfg.get("id", "rss")
        self.nombre = self.cfg.get("nombre", self.id)
        self.url = self.cfg["url"]
        self.prioridad = int(self.cfg.get("prioridad", 2))

    def url_pagina(self, n: int) -> str:
        if n == 1:
            return self.url
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}paged={n}"

    def recolectar(self, ctx: Contexto) -> list[dict]:
        vistos: dict[str, dict] = {}
        paginas = 0
        mas_vieja = None
        for n in range(1, MAX_PAGINAS + 1):
            try:
                contenido = ctx.red.contenido(self.url_pagina(n))
            except Exception:
                if n == 1:
                    raise
                break  # páginas siguientes: fin del feed o 404
            paginas = n
            entradas = leer_feed(contenido)
            if not entradas:
                if n == 1:
                    raise RuntimeError("El feed no trajo entradas")
                break
            nuevas = 0
            for e in entradas:
                if e["url"] not in vistos:
                    vistos[e["url"]] = e
                    nuevas += 1
            mas_vieja = min(e["publicado"].date() for e in entradas)
            if mas_vieja < ctx.ventana_desde or nuevas == 0:
                break
        else:
            if mas_vieja and mas_vieja > ctx.ventana_desde:
                self.avisos.append(f"El feed solo alcanzó hasta {mas_vieja} en {MAX_PAGINAS} páginas")
        self.detalles = {"paginas": paginas, "entradas": len(vistos)}
        items = []
        for e in vistos.values():
            if e["publicado"].date() < ctx.ventana_desde:
                continue
            items.append(construir(ctx, self, e))
        return items


def construir(ctx: Contexto, fuente: Fuente, e: dict, region: str | None = None,
              detectar_region: bool = False) -> dict:
    """Publicación de una noticia, clasificada con título, resumen y etiquetas.

    La región (México / Internacional) solo se calcula para medios regionales
    (Energía Estratégica); los medios mexicanos la dejan vacía.
    """
    etiquetas = ", ".join(e.get("etiquetas") or [])
    if region is None and detectar_region:
        region = ("México" if ctx.reglas.es_mexico(e["titulo"], e.get("resumen"), etiquetas)
                  else "Internacional")
    clasif = ctx.reglas.clasificar(e["titulo"], " ".join(filter(None, [e.get("resumen"), etiquetas])),
                                   es_noticia=True)
    item = modelo.nuevo(
        id=modelo.id_noticia(e["url"]), tipo="noticia", fuente_id=fuente.id, fuente=fuente.nombre,
        titulo=e["titulo"], url=e["url"], fecha=e["publicado"].date().isoformat(),
        hora=e["publicado"].strftime("%H:%M"), resumen=e.get("resumen") or None,
        region=region, etiquetas=etiquetas or None,
    )
    return modelo.aplicar(item, clasif)
