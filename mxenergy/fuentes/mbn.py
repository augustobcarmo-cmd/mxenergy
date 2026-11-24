"""Mexico Business News (sección Energy, en inglés, sin RSS).

El listado trae los enlaces; la fecha, el título y el resumen se leen de cada
artículo (JSON-LD y metadatos) una sola vez: las fechas quedan en caché.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from mxenergy.fuentes import Contexto, Fuente
from mxenergy.fuentes.rss import construir
from mxenergy.texto import recortar
from mxenergy.tiempo import a_local
from mxenergy import modelo

BASE = "https://mexicobusiness.news"
_ARTICULO = re.compile(r"^/energy/news/[a-z0-9\-]+$")
_FECHA = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')


def enlaces_listado(html: str) -> list[str]:
    from selectolax.lexbor import LexborHTMLParser

    urls: list[str] = []
    for a in LexborHTMLParser(html).css("a"):
        href = (a.attributes.get("href") or "").split("?")[0].split("#")[0]
        if href.startswith(BASE):
            href = href[len(BASE):]
        if _ARTICULO.match(href):
            url = BASE + href
            if url not in urls:
                urls.append(url)
    return urls


def _iso(s: str) -> datetime | None:
    # MBN usa desfases sin dos puntos ('-0600'), que fromisoformat no acepta.
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s.strip()).replace("Z", "+00:00")
    try:
        return a_local(datetime.fromisoformat(s))
    except ValueError:
        return None


def leer_articulo(html: str) -> dict | None:
    from selectolax.lexbor import LexborHTMLParser

    arbol = LexborHTMLParser(html)
    publicado = None
    for s in arbol.css('script[type="application/ld+json"]'):
        try:
            j = json.loads(s.text())
        except (ValueError, TypeError):
            continue
        for c in (j if isinstance(j, list) else (j.get("@graph") or [j])):
            if isinstance(c, dict) and c.get("datePublished"):
                publicado = _iso(str(c["datePublished"]))
                break
        if publicado:
            break
    if publicado is None:
        m = _FECHA.search(html)
        publicado = _iso(m.group(1)) if m else None
    h1 = arbol.css_first("h1")
    titulo = " ".join((h1.text(strip=True) if h1 else "").split())
    if not titulo or publicado is None:
        return None
    resumen = ""
    for sel in ('meta[name="description"]', 'meta[property="og:description"]'):
        n = arbol.css_first(sel)
        if n is not None and (n.attributes.get("content") or "").strip():
            resumen = n.attributes["content"].strip()
            break
    return {"titulo": titulo, "publicado": publicado, "resumen": recortar(resumen, 400),
            "etiquetas": []}


class FuenteMBN(Fuente):
    tipo = "noticia"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        self.id = self.cfg.get("id", "mbn")
        self.nombre = self.cfg.get("nombre", "Mexico Business News")
        self.url = self.cfg.get("url", f"{BASE}/energy")
        self.prioridad = int(self.cfg.get("prioridad", 2))
        self.max_visitas = int(self.cfg.get("max_articulos_por_corrida", 25))

    def recolectar(self, ctx: Contexto) -> list[dict]:
        urls = enlaces_listado(ctx.red.texto(self.url))
        if not urls:
            raise RuntimeError("El listado no trajo artículos")
        cache: dict[str, str] = ctx.estado.setdefault("mbn_fechas", {})
        items, visitas = [], 0
        for url in urls:
            if modelo.id_noticia(url) in ctx.existentes:
                continue
            f = cache.get(url)
            if f is not None and (not f or date.fromisoformat(f[:10]) < ctx.ventana_desde):
                continue
            if visitas >= self.max_visitas:
                break
            visitas += 1
            try:
                art = leer_articulo(ctx.red.texto(url))
            except Exception as e:  # noqa: BLE001
                ctx.log.debug("MBN: %s no se pudo leer (%s)", url, e)
                continue
            if not art:
                cache[url] = ""
                continue
            cache[url] = art["publicado"].isoformat(timespec="minutes")
            if art["publicado"].date() >= ctx.ventana_desde:
                items.append(construir(ctx, self, {**art, "url": url}))
        if len(cache) > 1500:
            for u in sorted(cache, key=lambda u: cache[u] or "")[:500]:
                cache.pop(u, None)
        self.detalles = {"enlaces": len(urls), "abiertos": visitas}
        return items
