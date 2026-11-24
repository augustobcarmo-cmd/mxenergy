"""Energía Estratégica: la fuente más importante de la síntesis.

El medio no publica RSS y arma sus listados en el navegador, así que los
listados públicos (sección México, portada, storage, fotovoltaica, eólica) se
leen con un Chromium sin ventana, como los vería un lector. El endpoint de
datos del sitio está bajo /api/, que su robots.txt prohíbe, y no se toca.

Cada artículo sí viene armado desde el servidor: su fecha, título, resumen y
etiquetas se leen del HTML (JSON-LD y metadatos) con una petición normal, una
sola vez por artículo (las fechas quedan en caché).

Sin navegador (o si el render falla) se usa la portada tal como la entrega el
servidor, que trae una parte de las notas: la fuente no desaparece, se
achica, y la corrida lo avisa.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from mxenergy.fuentes import Contexto, Fuente
from mxenergy.fuentes.rss import construir
from mxenergy.red import UA
from mxenergy.texto import recortar
from mxenergy.tiempo import a_local
from mxenergy import modelo

BASE = "https://www.energiaestrategica.com"
SELECTOR = 'a[href*="/notes/"]'
_SLUG = re.compile(r"/(es)/notes/([a-z0-9][a-z0-9-]{8,})")
_SLUG_RSC = re.compile(r"/es/notes/([a-z0-9][a-z0-9-]{8,})")
_IMAGENES = re.compile(r".*\.(png|jpe?g|webp|gif|svg|woff2?|mp4)(\?.*)?$", re.I)
MAX_CACHE = 4000


def url_canonica(href: str | None) -> str | None:
    """https://www.energiaestrategica.com/es/notes/<slug> (solo notas en español)."""
    if not href:
        return None
    m = _SLUG.search(href)
    return f"{BASE}/es/notes/{m.group(2)}" if m else None


def leer_articulo(html: str) -> dict | None:
    """Título, fecha de publicación (hora local), resumen y etiquetas."""
    from selectolax.lexbor import LexborHTMLParser

    arbol = LexborHTMLParser(html)
    datos = None
    for s in arbol.css('script[type="application/ld+json"]'):
        try:
            j = json.loads(s.text())
        except (ValueError, TypeError):
            continue
        candidatos = j if isinstance(j, list) else (j.get("@graph") or [j])
        for c in candidatos:
            if isinstance(c, dict) and c.get("datePublished"):
                datos = c
                break
        if datos:
            break

    def meta(*claves):
        for k in claves:
            n = arbol.css_first(f'meta[property="{k}"]') or arbol.css_first(f'meta[name="{k}"]')
            v = (n.attributes.get("content") or "").strip() if n is not None else ""
            if v:
                return v
        return ""

    crudo = (datos or {}).get("datePublished") or meta("article:published_time")
    if not crudo:
        return None
    try:
        publicado = a_local(datetime.fromisoformat(crudo.replace("Z", "+00:00")))
    except ValueError:
        return None
    titulo = ((datos or {}).get("headline") or meta("og:title")
              or (arbol.css_first("title").text() if arbol.css_first("title") else ""))
    etiquetas = [t.strip() for t in meta("keywords", "news_keywords").split(",") if t.strip()]
    return {"titulo": " ".join(str(titulo).split()), "publicado": publicado,
            "resumen": recortar(meta("description", "og:description"), 400),
            "etiquetas": etiquetas}


def renderizar(urls: list[str], log) -> dict[str, list[str]]:
    """Enlaces a notas de cada listado, tras dejar que la página los arme."""
    from playwright.sync_api import sync_playwright

    out: dict[str, list[str]] = {}
    with sync_playwright() as p:
        navegador, errores = None, []
        for opciones in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
            try:
                navegador = p.chromium.launch(headless=True, **opciones)
                break
            except Exception as e:  # noqa: BLE001
                errores.append(f"{opciones.get('channel', 'chromium')}: {str(e)[:120]}")
        if navegador is None:
            raise RuntimeError("Sin navegador utilizable: " + " | ".join(errores))
        try:
            contexto = navegador.new_context(user_agent=UA, locale="es-MX")
            contexto.route(_IMAGENES, lambda ruta: ruta.abort())
            pagina = contexto.new_page()
            for url in urls:
                try:
                    pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    pagina.wait_for_selector(SELECTOR, state="attached", timeout=20_000)
                    # La lista se sigue llenando después del primer enlace.
                    pagina.wait_for_timeout(2_500)
                    pagina.mouse.wheel(0, 20_000)
                    pagina.wait_for_timeout(1_500)
                    hrefs = pagina.eval_on_selector_all(
                        SELECTOR, "els => els.map(e => e.getAttribute('href'))")
                    out[url] = [h for h in hrefs if h]
                    log.info("Energía Estratégica: %d enlaces en %s", len(set(out[url])), url)
                except Exception as e:  # noqa: BLE001
                    log.warning("Energía Estratégica: el listado %s no cargó (%s)", url, str(e)[:150])
                    out[url] = []
        finally:
            navegador.close()
    return out


def portada_servidor(html: str) -> list[str]:
    """Notas que la portada ya trae armadas desde el servidor (respaldo)."""
    return [f"/es/notes/{s}" for s in dict.fromkeys(_SLUG_RSC.findall(html))]


class FuenteEE(Fuente):
    tipo = "noticia"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        self.id = self.cfg.get("id", "energia_estrategica")
        self.nombre = self.cfg.get("nombre", "Energía Estratégica")
        self.prioridad = int(self.cfg.get("prioridad", 1))
        self.listados = [(l["url"], l.get("region")) for l in self.cfg.get("listados") or []]
        self.max_visitas = int(self.cfg.get("max_articulos_por_corrida", 90))

    def candidatos(self, ctx: Contexto) -> dict[str, bool]:
        """{url de la nota: viene de la sección México}."""
        enlaces: dict[str, list[str]] = {}
        if ctx.usar_navegador and self.listados:
            try:
                enlaces = renderizar([u for u, _ in self.listados], ctx.log)
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"Navegador: {str(e)[:160]}")
                ctx.log.warning("Energía Estratégica: sin navegador (%s)", e)
        if not any(enlaces.values()):
            html = ctx.red.texto(f"{BASE}/energiaestrategica/es")
            enlaces = {f"{BASE}/energiaestrategica/es": portada_servidor(html)}
            self.avisos.append("Solo la portada del servidor (sin listados renderizados)")
        region_de = dict(self.listados)
        out: dict[str, bool] = {}
        for listado, hrefs in enlaces.items():
            mexico = region_de.get(listado) == "México"
            for h in hrefs:
                url = url_canonica(h)
                if url:
                    out[url] = out.get(url, False) or mexico
        self.detalles["listados"] = {u: len(set(h)) for u, h in enlaces.items()}
        return out

    def recolectar(self, ctx: Contexto) -> list[dict]:
        candidatos = self.candidatos(ctx)
        if not candidatos:
            raise RuntimeError("No se encontró ninguna nota en los listados")
        cache: dict[str, str] = ctx.estado.setdefault("ee_fechas", {})
        items, visitas, sin_abrir, fallas = [], 0, 0, 0
        for url, mexico in candidatos.items():
            ident = modelo.id_noticia(url)
            guardado = ctx.existentes.get(ident)
            if guardado is not None:
                if mexico and guardado.get("region") != "México":
                    item = dict(guardado)
                    item["region"] = "México"
                    items.append(item)
                continue
            if url in cache:
                f = cache[url]
                if not f or date.fromisoformat(f[:10]) < ctx.ventana_desde:
                    continue
            if visitas >= self.max_visitas:
                sin_abrir += 1
                continue
            visitas += 1
            try:
                art = leer_articulo(ctx.red.texto(url))
            except Exception as e:  # noqa: BLE001
                fallas += 1
                ctx.log.debug("Energía Estratégica: %s no se pudo leer (%s)", url, e)
                continue
            if not art:
                cache[url] = ""
                continue
            cache[url] = art["publicado"].isoformat(timespec="minutes")
            if art["publicado"].date() < ctx.ventana_desde:
                continue
            items.append(construir(ctx, self, {**art, "url": url},
                                   region="México" if mexico else None, detectar_region=True))
        self._podar(cache, ctx.hoy)
        self.detalles.update({"candidatos": len(candidatos), "abiertos": visitas,
                              "sin_abrir": sin_abrir, "fallas": fallas})
        if sin_abrir:
            self.avisos.append(f"{sin_abrir} nota(s) quedaron para la siguiente corrida (tope de {self.max_visitas})")
        if visitas and fallas == visitas:
            raise RuntimeError(f"No se pudo abrir ninguna de las {visitas} notas")
        return items

    @staticmethod
    def _podar(cache: dict[str, str], hoy: date) -> None:
        if len(cache) <= MAX_CACHE:
            return
        limite = (hoy - timedelta(days=60)).isoformat()
        for url in [u for u, f in cache.items() if not f or f[:10] < limite]:
            cache.pop(url, None)
