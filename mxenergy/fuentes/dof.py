"""Diario Oficial de la Federación.

Fuente principal: la API del SIDOF (Secretaría de Gobernación), que devuelve
en JSON todas las notas de un día —matutina, vespertina y extraordinaria—, con
su dependencia, y el HTML completo de cada nota. Si la API falla para un día,
se usa el índice clásico de dof.gob.mx (pidiendo cada edición por su nombre:
sin `edicion`, el índice devuelve la vespertina y nunca la matutina).

Cada corrida revisa los últimos días (ediciones tardías) y completa los días
que falten desde `inicio_historial`; el texto de una nota se descarga una sola
vez y se clasifica con las reglas.
"""

from __future__ import annotations

import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from mxenergy import modelo
from mxenergy.fuentes import Contexto, Fuente
from mxenergy.texto import html_a_texto, normalizar, recortar
from mxenergy.tiempo import dias

SIDOF = "https://sidof.segob.gob.mx/dof/sidof"
EDICIONES = (("NotasMatutinas", "MAT"), ("NotasVespertinas", "VES"),
             ("NotasExtraordinarias", "EXT"))
LEGADO = (("https://diariooficial.segob.gob.mx", True), ("https://www.dof.gob.mx", False))

_TIPOS = {
    "DECRETO", "ACUERDO", "RESOLUCION", "AVISO", "LINEAMIENTOS", "REGLAS", "CONVOCATORIA",
    "EXTRACTO", "SENTENCIA", "CONVENIO", "OFICIO", "CIRCULAR", "PROGRAMA", "MANUAL",
    "ESTATUTO", "LEY", "REGLAMENTO", "INDICE", "DECLARATORIA", "CRITERIOS", "ANEXO",
    "CODIGO", "NORMA", "PROYECTO", "DISPOSICIONES", "CALENDARIO", "RESPUESTA",
    "MODIFICACION", "ACLARACION", "FE", "NOTA", "PLAN", "ESTRATEGIA", "BASES", "TARIFA",
}
_REF_AVISO = re.compile(r"^aviso ref\s*:?\s*\d+$", re.I)
_CODIGO = re.compile(r"codigo=(\d+)")
_FECHA = re.compile(r"fecha=([\d/]+)")


def url_publica(cod: int | str, d: date) -> str:
    return f"https://www.dof.gob.mx/nota_detalle.php?codigo={cod}&fecha={d:%d/%m/%Y}"


def _limpio(v) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).split())
    return None if s in ("", "null", "undefined", "None") else s


def tipo_doc(titulo: str) -> str | None:
    t = normalizar(titulo).upper()
    if t.startswith("DISPOSICIONES ADMINISTRATIVAS DE CARACTER GENERAL"):
        return "DACG"
    if t.startswith("PROYECTO DE NORMA OFICIAL MEXICANA"):
        return "PROY-NOM"
    if t.startswith("NORMA OFICIAL MEXICANA"):
        return "NOM"
    if t.startswith("FE DE ERRATAS"):
        return "FE DE ERRATAS"
    primera = t.split(" ", 1)[0] if t else ""
    if primera == "RESOLUCION" or "RESOLUCION" in t.split(" ")[:3]:
        return "RESOLUCION"
    return primera if primera in _TIPOS else None


def notas_sidof(j: dict) -> list[dict]:
    """Notas de la respuesta del SIDOF para un día (sin los encabezados)."""
    out: dict[int, dict] = {}
    for clave, edicion in EDICIONES:
        for n in j.get(clave) or []:
            titulo = _limpio(n.get("titulo"))
            cod = n.get("codNota")
            if not titulo or not cod:
                continue  # encabezado de una dependencia, sin nota propia
            cod = int(cod)
            poder = _limpio(n.get("codOrgaUno"))
            out.setdefault(cod, {
                "cod": cod,
                "titulo": titulo,
                "edicion": edicion,
                "poder": poder,
                "dependencia": _limpio(n.get("codOrgaDos")),
                "pagina": n.get("pagina"),
                "aviso": poder == "AV" or bool(_REF_AVISO.match(titulo)),
            })
    return list(out.values())


def encabezado_aviso(texto: str) -> tuple[str, str | None, bool, str]:
    """(título, emisor, es_edicto, cuerpo) de un aviso de la sección de avisos.

    Sus títulos en el índice son «Aviso REF:581287»; lo que dice qué es está en
    las primeras líneas del texto: quién lo publica y qué es (edicto,
    convocatoria, aviso de fusión…).
    """
    lineas = [ln.strip() for ln in (texto or "").split("\n") if ln.strip()]
    utiles = [ln for ln in lineas
              if normalizar(ln) not in ("estados unidos mexicanos", "")
              and not normalizar(ln).startswith("al margen")]
    cabeza = utiles[:4]
    es_edicto = any("edicto" in normalizar(ln) for ln in utiles[:6])
    emisor = cabeza[0] if cabeza else None
    titulo = recortar(" — ".join(cabeza[:3]), 180) if cabeza else "Aviso"
    cuerpo = "\n".join(utiles[3:])
    return titulo, emisor, es_edicto, cuerpo


def extracto(texto: str, titulo: str, n: int = 420) -> str:
    """Primer párrafo útil del cuerpo (sin el título ni el sello)."""
    tn = normalizar(titulo)[:60]
    for ln in (texto or "").split("\n"):
        ln = ln.strip()
        lnn = normalizar(ln)
        if (len(ln) < 40 or lnn.startswith("al margen") or (tn and lnn.startswith(tn))
                or lnn == "estados unidos mexicanos"):
            continue
        return recortar(ln, n)
    return recortar(texto, n)


def parse_indice_legado(html: str) -> list[dict]:
    """Notas del índice clásico de dof.gob.mx, cada una con su dependencia.

    Recorre el DOM en orden: los encabezados (td.subtitle_azul) preceden a sus
    notas.
    """
    from selectolax.lexbor import LexborHTMLParser

    arbol = LexborHTMLParser(html)
    raiz = arbol.body or arbol.root
    out: dict[int, dict] = {}
    dep = ""
    if raiz is None:
        return []
    for nodo in raiz.traverse(include_text=False):
        if nodo.tag == "td" and "subtitle_azul" in (nodo.attributes.get("class") or ""):
            t = nodo.text(strip=True).replace("\xa0", " ").strip()
            if t:
                dep = t
        elif nodo.tag == "a":
            href = nodo.attributes.get("href") or ""
            if "nota_detalle" not in href:
                continue
            m = _CODIGO.search(href)
            titulo = " ".join(nodo.text(strip=True).split())
            if not m or not titulo:
                continue
            out.setdefault(int(m.group(1)), {
                "cod": int(m.group(1)), "titulo": titulo, "edicion": None, "poder": None,
                "dependencia": dep or None, "pagina": None, "aviso": False,
            })
    return list(out.values())


class FuenteDOF(Fuente):
    id = "dof"
    nombre = "DOF"
    tipo = "dof"
    prioridad = 0

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        c = self.cfg
        self.inicio = date.fromisoformat(str(c.get("inicio_historial", "2026-08-01")))
        self.dias_revision = int(c.get("dias_revision", 10))
        self.max_dias = int(c.get("max_dias_por_corrida", 40))
        self.max_notas = int(c.get("max_notas_por_corrida", 3000))
        self.hilos = int(c.get("descargas_simultaneas", 4))

    # --- plan ----------------------------------------------------------------

    def planificar(self, ctx: Contexto) -> list[date]:
        """Días a consultar, del más reciente al más viejo."""
        registro = ctx.estado.setdefault("dof_dias", {})
        revision = {ctx.hoy - timedelta(days=i) for i in range(self.dias_revision)}
        pendientes = [d for d in dias(self.inicio, ctx.hoy)
                      if d not in revision and (registro.get(d.isoformat()) or {}).get(
                          "estado") not in ("ok", "sin_edicion")]
        pendientes = sorted(pendientes, reverse=True)[: self.max_dias]
        return sorted(revision | set(pendientes), reverse=True)

    # --- consultas -----------------------------------------------------------

    def indice_sidof(self, ctx: Contexto, d: date) -> list[dict]:
        j = ctx.red.json(f"{SIDOF}/notas/{d:%d-%m-%Y}")
        if str(j.get("messageCode", 200)) not in ("200",):
            raise RuntimeError(f"SIDOF respondió {j.get('messageCode')}: {j.get('response')}")
        return notas_sidof(j)

    def texto_sidof(self, ctx: Contexto, cod: int) -> str:
        j = ctx.red.json(f"{SIDOF}/notas/nota/{cod}")
        nota = j.get("Nota") or {}
        return html_a_texto(nota.get("cadenaContenido") or "")

    def _legado(self, ctx: Contexto, ruta: str):
        ultimo = None
        for host, verify in LEGADO:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    return ctx.red.contenido(host + ruta, verify=verify)
            except Exception as e:  # noqa: BLE001
                ultimo = e
        raise RuntimeError(f"DOF clásico sin respuesta para {ruta}: {ultimo}")

    def indice_legado(self, ctx: Contexto, d: date) -> list[dict]:
        notas: dict[int, dict] = {}
        for ed in ("MAT", "VES"):
            ruta = f"/index.php?year={d.year}&month={d.month:02d}&day={d.day:02d}&edicion={ed}"
            html = self._legado(ctx, ruta)
            for n in parse_indice_legado(_decodificar(html)):
                n["edicion"] = ed
                notas.setdefault(n["cod"], n)
        return list(notas.values())

    def texto_legado(self, ctx: Contexto, cod: int, d: date) -> str:
        html = _decodificar(self._legado(ctx, f"/nota_detalle.php?codigo={cod}&fecha={d:%d/%m/%Y}"))
        from selectolax.lexbor import LexborHTMLParser

        nodo = LexborHTMLParser(html).css_first("#DivDetalleNota")
        return html_a_texto(nodo.html if nodo is not None else html)

    # --- recolección -----------------------------------------------------------

    def recolectar(self, ctx: Contexto) -> list[dict]:
        registro = ctx.estado.setdefault("dof_dias", {})
        plan = self.planificar(ctx)
        presupuesto = self.max_notas
        items: list[dict] = []
        fallidos, consultados, textos_bajados = [], 0, 0
        ultimo_error = ""
        for d in plan:
            if presupuesto <= 0:
                break
            clave = d.isoformat()
            origen = "sidof"
            try:
                notas = self.indice_sidof(ctx, d)
            except Exception as e:  # noqa: BLE001
                ctx.log.warning("DOF %s: SIDOF falló (%s); se usa el índice clásico", clave, e)
                origen = "dof.gob.mx"
                try:
                    notas = self.indice_legado(ctx, d)
                except Exception as e2:  # noqa: BLE001
                    ctx.log.warning("DOF %s: tampoco respondió el índice clásico (%s)", clave, e2)
                    ultimo_error = f"SIDOF: {e}; dof.gob.mx: {e2}"
                    registro[clave] = {"estado": "error", "revisado": ctx.ahora.isoformat(timespec="seconds"),
                                       "error": str(e2)[:200]}
                    fallidos.append(clave)
                    continue
            consultados += 1
            por_bajar = [n for n in notas
                         if modelo.id_dof(n["cod"]) not in ctx.existentes
                         or (ctx.existentes[modelo.id_dof(n["cod"])] or {}).get("sin_texto")]
            parcial = len(por_bajar) > presupuesto
            por_bajar = por_bajar[: max(presupuesto, 0)]
            presupuesto -= len(por_bajar)

            def bajar(n, d=d, origen=origen):
                try:
                    if origen == "sidof":
                        return n["cod"], self.texto_sidof(ctx, n["cod"])
                    return n["cod"], self.texto_legado(ctx, n["cod"], d)
                except Exception as e:  # noqa: BLE001
                    ctx.log.debug("DOF nota %s: sin texto (%s)", n["cod"], e)
                    return n["cod"], None

            with ThreadPoolExecutor(max_workers=max(1, self.hilos)) as ex:
                textos = dict(ex.map(bajar, por_bajar))
            textos_bajados += sum(1 for t in textos.values() if t)
            for n in notas:
                if n["cod"] in textos:
                    items.append(self.construir(ctx, n, d, textos[n["cod"]]))
            ediciones = sorted({n["edicion"] for n in notas if n.get("edicion")})
            registro[clave] = {
                "estado": "parcial" if parcial else ("ok" if notas else "sin_edicion"),
                "notas": len(notas), "origen": origen, "ediciones": ediciones,
                "revisado": ctx.ahora.isoformat(timespec="seconds"),
            }
            if notas:
                ctx.log.info("DOF %s: %d notas (%s)%s; %d textos nuevos", clave, len(notas),
                             "/".join(ediciones) or "—", "" if origen == "sidof" else f" vía {origen}",
                             len(por_bajar))
        self.detalles = {"dias_consultados": consultados, "dias_con_error": fallidos,
                         "textos_descargados": textos_bajados,
                         "dias_pendientes": sum(1 for d in dias(self.inicio, ctx.hoy)
                                                if (registro.get(d.isoformat()) or {}).get("estado")
                                                not in ("ok", "sin_edicion"))}
        if fallidos:
            self.avisos.append(f"Días sin respuesta: {', '.join(fallidos[:5])}")
        if plan and consultados == 0:
            raise RuntimeError("Ni el SIDOF ni el índice clásico respondieron en ningún día "
                               f"({ultimo_error[:240]})")
        return items

    def construir(self, ctx: Contexto, n: dict, d: date, texto: str | None) -> dict:
        titulo = n["titulo"]
        dependencia = n.get("dependencia")
        es_edicto = False
        tipo = tipo_doc(titulo)
        cuerpo = texto or ""
        if n.get("aviso"):
            if texto:
                titulo, emisor, es_edicto, cuerpo = encabezado_aviso(texto)
                dependencia = emisor
                tipo = "EDICTO" if es_edicto else (tipo_doc(titulo) or "AVISO")
            else:
                tipo = "AVISO"
        clasif = ctx.reglas.clasificar(titulo, cuerpo, dependencia=dependencia,
                                       es_edicto=es_edicto)
        item = modelo.nuevo(
            id=modelo.id_dof(n["cod"]), tipo="dof", fuente_id=self.id, fuente=self.nombre,
            titulo=titulo, url=url_publica(n["cod"], d), fecha=d.isoformat(),
            resumen=extracto(cuerpo, titulo) if cuerpo else None,
            dependencia=dependencia, sigla=ctx.reglas.sigla(dependencia),
            poder=n.get("poder"), edicion=n.get("edicion"), tipo_doc=tipo,
            pagina=int(n["pagina"]) if str(n.get("pagina") or "").isdigit() else None,
            sin_texto=texto is None,
        )
        return modelo.aplicar(item, clasif)


def _decodificar(contenido: bytes) -> str:
    """Las páginas clásicas del DOF son ISO-8859-1; algunas, UTF-8."""
    try:
        return contenido.decode("utf-8")
    except UnicodeDecodeError:
        return contenido.decode("iso-8859-1", errors="replace")
