"""Síntesis diaria del sector energético de México: DOF y prensa especializada.

Lee lo que la GitHub Action «Recolectar» guarda en la rama `datos` del
repositorio (o una carpeta local con MXENERGY_DATOS) y lo presenta por
edición: la del martes cubre el lunes; la del lunes, de viernes a domingo.
"""

from __future__ import annotations

import io
import os
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from mxenergy import tiempo, vista
from mxenergy.vista import NOMBRE_EDICION
from mxenergy.reglas import Reglas

st.set_page_config(page_title="Síntesis energética MX", page_icon="⚡", layout="wide")

ETIQUETA_PRIORIDAD = {"alta": "Prioridad alta", "media": "Prioridad media", "baja": "Prioridad baja"}
EE = vista.FUENTE_PRINCIPAL


@st.cache_data(ttl=600, show_spinner="Cargando publicaciones…")
def cargar_datos() -> vista.Datos:
    return vista.cargar()


@st.cache_resource
def cargar_reglas() -> Reglas:
    return Reglas.cargar()


def esc(s: str) -> str:
    """Texto seguro para st.markdown (sin enlaces, fórmulas ni HTML accidentales)."""
    s = str(s or "")
    for ch in "\\`*_[]<>$~|#":
        s = s.replace(ch, "\\" + ch)
    return s


def url_md(u: str) -> str:
    return (u or "").replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def insignias(reglas: Reglas, categorias: str) -> str:
    return " ".join(f":{reglas.color(c)}-badge[{esc(reglas.nombre(c))}]"
                    for c in filter(None, categorias.split(",")))


def fecha_corta(f: str) -> str:
    try:
        return tiempo.corta(date.fromisoformat(f))
    except ValueError:
        return f


def fecha_hora(iso: str | None) -> str:
    """'24 nov 2026, 16:14' a partir de una marca ISO."""
    try:
        dt = datetime.fromisoformat(iso or "")
    except ValueError:
        return iso or "—"
    return f"{dt.day} {tiempo.MESES_CORTOS[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def hace(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    minutos = int((tiempo.ahora() - dt).total_seconds() // 60)
    if minutos < 60:
        return f"hace {max(minutos, 0)} min"
    if minutos < 48 * 60:
        return f"hace {minutos // 60} h"
    return f"hace {minutos // 1440} días"


def tarjeta_dof(r, reglas: Reglas, motivos: bool = True) -> None:
    meta = [fecha_corta(r.fecha)]
    if r.edicion:
        meta.append(NOMBRE_EDICION.get(r.edicion, r.edicion))
    dep = r.sigla or (r.dependencia.title() if r.dependencia else "")
    if dep:
        meta.append(dep)
    if r.tipo_doc:
        meta.append(vista.tipo_doc(r.tipo_doc))
    lineas = [f"**[{esc(r.titulo)}]({url_md(r.url)})**",
              f":gray[{esc(' · '.join(meta))}] {insignias(reglas, r.categorias)}"]
    if motivos and r.motivos:
        lineas.append(f":gray[_{esc(r.motivos)}_]")
    st.markdown("  \n".join(lineas))


def tarjeta_noticia(r, reglas: Reglas, resumen: bool) -> None:
    meta = [r.fuente, f"{fecha_corta(r.fecha)} {r.hora}".strip()]
    lineas = [f"**[{esc(r.titulo)}]({url_md(r.url)})**",
              f":gray[{esc(' · '.join(meta))}] {insignias(reglas, r.categorias)}"]
    texto = vista.resumen_util(r.titulo, r.resumen) if resumen else ""
    if texto:
        texto = texto if len(texto) <= 240 else texto[:237].rsplit(" ", 1)[0] + "…"
        lineas.append(f":gray[{esc(texto)}]")
    st.markdown("  \n".join(lineas))


def tabla_enlaces(df: pd.DataFrame, columnas: dict[str, str], alto: int | None = None) -> None:
    vista_df = df[list(columnas)].rename(columns=columnas)
    st.dataframe(
        vista_df, hide_index=True, width="stretch", height=alto or "auto",
        column_config={"Enlace": st.column_config.LinkColumn("Enlace", display_text="Abrir")},
    )


def excel(df: pd.DataFrame) -> bytes:
    salida = io.BytesIO()
    cols = ["fecha", "hora", "fuente", "titulo", "url", "categorias", "prioridad", "sigla",
            "dependencia", "edicion", "tipo_doc", "region", "motivos", "resumen"]
    df[cols].to_excel(salida, index=False, sheet_name="Publicaciones")
    return salida.getvalue()


# --- datos -------------------------------------------------------------------------

try:
    datos = cargar_datos()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudieron leer los datos ({type(e).__name__}: {e}). Vuelve a intentar en unos minutos.")
    st.stop()
reglas = cargar_reglas()
items = datos.items
hoy = date.fromisoformat(os.environ["MXENERGY_HOY"]) if os.environ.get("MXENERGY_HOY") else tiempo.hoy()

st.title("⚡ Síntesis del sector energético · México")
actualizado = datos.meta.get("actualizado")
st.caption(f"DOF y prensa especializada, filtrados por reglas (sin IA) · Actualizado {hace(actualizado)}")
if items.empty:
    st.warning("Todavía no hay datos: la primera recolección aún no termina. Vuelve en unos minutos.")
    st.stop()
if actualizado:
    try:
        horas = (tiempo.ahora() - datetime.fromisoformat(actualizado)).total_seconds() / 3600
        if horas > 9:
            st.warning(f"La última actualización fue {hace(actualizado)}. La recolección corre cinco "
                       "veces al día; revisa la pestaña Estado.")
    except ValueError:
        pass

prioridad_fuente = {s_id: int(s.get("prioridad", 9))
                    for s_id, s in (datos.estado.get("fuentes") or {}).items()}
prioridad_fuente.setdefault(EE, 1)

# --- barra lateral -------------------------------------------------------------------

with st.sidebar:
    st.header("Filtros")
    cats_elegidas = st.multiselect(
        "Categorías", list(reglas.categorias), format_func=reglas.nombre, placeholder="Todas",
        help="Vacío = todas. Se aplica al DOF y a las noticias.")
    prioridad_min = st.radio("DOF: prioridad mínima", ["baja", "media", "alta"], horizontal=True,
                             format_func=str.capitalize)
    fuentes_noticias = sorted(set(items.loc[items["tipo"] == "noticia", "fuente"]))
    fuentes_elegidas = st.multiselect("Fuentes de noticias", fuentes_noticias, placeholder="Todas",
                                      help="Vacío = todas.")
    con_resumen = st.toggle("Mostrar el resumen de las noticias", value=True)
    filtro_texto = st.text_input("Filtrar por texto", placeholder="ej. almacenamiento, CENACE", key="filtro")
    st.divider()
    if st.button("🔄 Recargar datos"):
        cargar_datos.clear()
        st.rerun()
    st.caption(f"[Código y reglas en GitHub]({vista.url_repo()}) · "
               f"[Editar las reglas]({vista.url_repo('/edit/main/config/reglas.yaml')})")

umbral = {"baja": 2, "media": 1, "alta": 0}[prioridad_min]


def aplicar_filtros(df: pd.DataFrame) -> pd.DataFrame:
    df = vista.con_categorias(df, cats_elegidas)
    if filtro_texto:
        df = vista.buscar(df, filtro_texto)
    return df


pestana_sintesis, pestana_buscar, pestana_estado, pestana_como = st.tabs(
    ["📰 Síntesis", "🔎 Buscar", "🩺 Estado", "ℹ️ Cómo funciona"])

# --- síntesis ------------------------------------------------------------------------

with pestana_sintesis:
    primera = date.fromisoformat(datos.meta.get("desde") or (hoy - timedelta(days=30)).isoformat())
    ediciones = tiempo.ediciones(max(primera, hoy - timedelta(days=400)), hoy)
    vigente = tiempo.edicion_vigente(hoy)
    pedida = st.query_params.get("edicion")
    try:
        pedida_d = date.fromisoformat(pedida) if pedida else None
    except ValueError:
        pedida_d = None
    inicial = pedida_d if pedida_d in ediciones else (vigente if vigente in ediciones else ediciones[0])

    def etiqueta(e: date) -> str:
        d, h = tiempo.periodo(e)
        cubre = fecha_corta(d.isoformat()) if d == h else f"{fecha_corta(d.isoformat())} – {fecha_corta(h.isoformat())}"
        curso = " · en curso" if h >= hoy else ""
        return f"Edición del {fecha_corta(e.isoformat())} {e.year} · cubre {cubre}{curso}"

    c1, c2 = st.columns([3, 2])
    with c1:
        edicion = st.selectbox("Edición", ediciones, index=ediciones.index(inicial), format_func=etiqueta)
    with c2:
        personalizado = st.toggle("Periodo personalizado")
        rango = None
        if personalizado:
            d0, h0 = tiempo.periodo(edicion)
            rango = st.date_input("Del … al …", value=(d0, h0), min_value=primera, max_value=hoy,
                                  format="DD/MM/YYYY")
    if personalizado and isinstance(rango, tuple) and len(rango) == 2:
        desde, hasta = rango
    else:
        desde, hasta = tiempo.periodo(edicion)
        st.query_params["edicion"] = edicion.isoformat()

    en_curso = hasta >= hoy
    st.markdown(f"**Periodo cubierto:** {tiempo.rango(desde, hasta)}"
                + (" · _en curso: se completa a lo largo del día_" if en_curso else ""))

    periodo = vista.en_periodo(items, desde, hasta)
    dof = periodo[periodo["tipo"] == "dof"]
    dof_rel = aplicar_filtros(dof[dof["prioridad"].map(vista.ORDEN_PRIORIDAD).fillna(3) <= umbral])
    noticias = periodo[periodo["tipo"] == "noticia"]
    if fuentes_elegidas:
        noticias = noticias[noticias["fuente"].isin(fuentes_elegidas)]
    noticias = aplicar_filtros(noticias)
    ee = noticias[noticias["fuente_id"] == EE]
    otras = noticias[noticias["fuente_id"] != EE]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("DOF: relevantes", len(dof_rel), help=f"De {len(dof)} publicaciones en el periodo")
    m2.metric("DOF: prioridad alta", int((dof_rel["prioridad"] == "alta").sum()))
    m3.metric("Energía Estratégica", len(ee),
              help=f"{int((ee['region'] == 'México').sum())} sobre México")
    m4.metric("Otras fuentes", len(otras))

    # DOF
    st.subheader("📜 Diario Oficial de la Federación")
    if dof.empty:
        st.info("Sin publicaciones del DOF en el periodo (día inhábil o aún no se publica la edición).")
    elif dof_rel.empty:
        st.info(f"Ninguna de las {len(dof)} publicaciones del periodo pasó el filtro.")
    for p in ("alta", "media", "baja"):
        grupo = vista.ordenar_dof(dof_rel[dof_rel["prioridad"] == p])
        if grupo.empty:
            continue
        if p == "baja":   # coincidencias débiles: a mano, pero sin ocupar la portada
            with st.expander(f"{ETIQUETA_PRIORIDAD[p]} ({len(grupo)}): menciones en el texto"):
                for r in grupo.itertuples():
                    tarjeta_dof(r, reglas)
            continue
        st.markdown(f"##### {ETIQUETA_PRIORIDAD[p]} ({len(grupo)})")
        for r in grupo.itertuples():
            tarjeta_dof(r, reglas)
    if not dof.empty:
        with st.expander(f"Todas las publicaciones del DOF del periodo ({len(dof)})"):
            todo = dof.assign(
                Edición=dof["edicion"].map(lambda x: NOMBRE_EDICION.get(x, x)),
                Dependencia=dof.apply(lambda r: r["sigla"] or r["dependencia"].title(), axis=1),
            ).sort_values(["fecha", "edicion", "pagina"], ascending=[False, True, True])
            tabla_enlaces(todo, {"fecha": "Fecha", "Edición": "Edición", "Dependencia": "Dependencia",
                                 "titulo": "Título", "prioridad": "Prioridad", "url": "Enlace"})

    # Energía Estratégica
    st.subheader("⚡ Energía Estratégica")
    if ee.empty:
        st.info("Sin notas de Energía Estratégica en el periodo" + (" con estos filtros." if
                                                                     cats_elegidas or filtro_texto else "."))
    else:
        mx = vista.ordenar_noticias(ee[ee["region"] == "México"], prioridad_fuente)
        intl = vista.ordenar_noticias(ee[ee["region"] != "México"], prioridad_fuente)
        st.markdown(f"##### México ({len(mx)})")
        if mx.empty:
            st.caption("Sin notas sobre México en el periodo.")
        for r in mx.itertuples():
            tarjeta_noticia(r, reglas, con_resumen)
        with st.expander(f"Región e internacional ({len(intl)})", expanded=len(intl) <= 20):
            for r in intl.itertuples():
                tarjeta_noticia(r, reglas, con_resumen)

    # Otras fuentes
    st.subheader("📰 Otras fuentes")
    if otras.empty:
        st.info("Sin notas de otras fuentes en el periodo.")
    else:
        hidro = otras["categorias"].map(vista.solo_hidrocarburos)
        for r in vista.ordenar_noticias(otras[~hidro], prioridad_fuente).itertuples():
            tarjeta_noticia(r, reglas, con_resumen)
        if hidro.any():
            with st.expander(f"Hidrocarburos y gas ({int(hidro.sum())})"):
                for r in vista.ordenar_noticias(otras[hidro], prioridad_fuente).itertuples():
                    tarjeta_noticia(r, reglas, con_resumen)

# --- buscar -----------------------------------------------------------------------------

with pestana_buscar:
    st.markdown("Busca en todo el historial: sin acentos ni mayúsculas, todas las palabras.")
    consulta = st.text_input("Buscar", placeholder="ej. almacenamiento de energía, aranceles módulos, CENACE",
                             key="consulta")
    b1, b2, b3 = st.columns([2, 1, 2])
    with b1:
        primera = date.fromisoformat(datos.meta.get("desde") or (hoy - timedelta(days=30)).isoformat())
        rango_b = st.date_input("Periodo", value=(max(primera, hoy - timedelta(days=90)), hoy),
                                min_value=primera, max_value=hoy, format="DD/MM/YYYY", key="rango_b")
    with b2:
        tipo_b = st.radio("Tipo", ["Todo", "DOF", "Noticias"], horizontal=True)
    with b3:
        solo_rel = st.checkbox("DOF: solo lo que pasó el filtro", value=True)
    res = items
    if isinstance(rango_b, tuple) and len(rango_b) == 2:
        res = vista.en_periodo(res, rango_b[0], rango_b[1])
    if tipo_b == "DOF":
        res = res[res["tipo"] == "dof"]
    elif tipo_b == "Noticias":
        res = res[res["tipo"] == "noticia"]
    if solo_rel:
        res = res[(res["tipo"] != "dof") | (res["prioridad"] != "")]
    res = vista.con_categorias(res, cats_elegidas)
    if fuentes_elegidas:
        res = res[(res["tipo"] == "dof") | res["fuente"].isin(fuentes_elegidas)]
    res = vista.buscar(res, consulta).sort_values(["fecha", "hora"], ascending=False)
    st.markdown(f"**{len(res)}** resultados")
    if not res.empty:
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Excel", excel(res), file_name=f"sintesis_{hoy.isoformat()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        d2.download_button("⬇️ CSV", res.drop(columns=["coincidencias"]).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"sintesis_{hoy.isoformat()}.csv", mime="text/csv")
        for r in res.head(300).itertuples():
            if r.tipo == "dof":
                tarjeta_dof(r, reglas, motivos=False)
            else:
                tarjeta_noticia(r, reglas, resumen=False)
        if len(res) > 300:
            st.caption("Se muestran los 300 más recientes; el Excel trae todos.")

# --- estado ---------------------------------------------------------------------------

with pestana_estado:
    st.markdown(f"**Última actualización:** {fecha_hora(actualizado)} ({hace(actualizado)}) · "
                f"**Publicaciones guardadas:** {len(items):,} · "
                f"**Desde:** {datos.meta.get('desde') or '—'}")
    filas = []
    for fid, s in sorted((datos.estado.get("fuentes") or {}).items(),
                         key=lambda kv: (kv[1].get("prioridad", 9), kv[1].get("nombre", kv[0]))):
        fallas = int(s.get("fallas_seguidas", 0))
        icono = "✅" if fallas == 0 and not s.get("avisos") else ("⚠️" if fallas == 0 else "❌")
        aviso = "; ".join(s.get("avisos") or [])
        error = (s.get("ultimo_error") or {}).get("mensaje", "") if fallas else ""
        filas.append({
            "": icono, "Fuente": s.get("nombre", fid), "Último ítem": s.get("ultimo_item", ""),
            "Últimos 7 días": s.get("items_7d", 0), "Total": s.get("total", 0),
            "Última corrida sin error": (s.get("ultima_ok") or "")[:16].replace("T", " "),
            "Fallas seguidas": fallas,
            "Aviso o error": error or aviso,
        })
    st.markdown("##### Fuentes")
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")

    st.markdown("##### DOF por día (últimos 21 días)")
    dof_dias = datos.estado.get("dof_dias") or {}
    tabla = []
    for d in tiempo.dias(hoy - timedelta(days=20), hoy)[::-1]:
        reg = dof_dias.get(d.isoformat()) or {}
        rel = items[(items["tipo"] == "dof") & (items["fecha"] == d.isoformat()) & (items["prioridad"] != "")]
        tabla.append({"Fecha": f"{tiempo.DIAS_CORTOS[d.weekday()]} {d.isoformat()}",
                      "Estado": {"ok": "✅ completo", "sin_edicion": "— sin edición", "parcial": "⏳ parcial",
                                 "error": "❌ error", "reproceso": "⏳ reproceso"}.get(reg.get("estado"), "· pendiente"),
                      "Notas": reg.get("notas", ""), "Relevantes": len(rel),
                      "Ediciones": ", ".join(reg.get("ediciones") or []), "Fuente": reg.get("origen", "")})
    st.dataframe(pd.DataFrame(tabla), hide_index=True, width="stretch")

    st.markdown("##### Últimas corridas")
    corridas = []
    for e in reversed(datos.ejecuciones[-30:]):
        corridas.append({
            "Inicio": (e.get("inicio") or "")[:16].replace("T", " "), "Segundos": e.get("segundos"),
            "Nuevas": e.get("agregados"), "Actualizadas": e.get("actualizados"),
            "Con error": ", ".join(f["id"] for f in e.get("fuentes", []) if not f.get("ok")) or "—",
            "Disparo": e.get("evento", ""),
        })
    if corridas:
        st.dataframe(pd.DataFrame(corridas), hide_index=True, width="stretch")
    st.markdown(f"[Log completo de la última corrida]({vista.url_raw('logs/ultima.log')}) · "
                f"[Historial de corridas en GitHub Actions]({vista.url_repo('/actions')})")

# --- cómo funciona ------------------------------------------------------------------------

with pestana_como:
    st.markdown(f"""
**Qué es.** Una síntesis diaria de lo que publican el **Diario Oficial de la Federación** y la prensa
especializada del sector energético, filtrada para lo que importa al desarrollo de proyectos eléctricos y de
almacenamiento en México.

**Ediciones.** Cada edición sale de lunes a viernes y cubre el día hábil anterior: la del martes cubre el
lunes y la del lunes cubre de viernes a domingo. La edición en curso se va llenando a lo largo del día.

**De dónde sale.**
- **DOF:** todas las publicaciones de cada día (matutina, vespertina y extraordinaria) desde la API oficial del
  SIDOF; si falla, desde el índice clásico de dof.gob.mx.
- **Energía Estratégica** (fuente principal): su sección México y los listados de portada, almacenamiento,
  fotovoltaica y eólica.
- **Otras fuentes:** Global Energy, Mexico Business News, PV Magazine México, Energía a Debate, Energy News MX
  y Energy21.

**Cuándo.** Una GitHub Action recolecta a las 5:17, 9:17, 13:17, 17:17 y 21:17 (hora del centro). La de la
madrugada cierra el día anterior, con la edición vespertina del DOF incluida.

**Cómo se filtra (sin IA).** Cada publicación se compara con las reglas de
[config/reglas.yaml]({vista.url_repo('/blob/main/config/reglas.yaml')}): dependencias que publican, términos en el
título y en el texto, y fracciones arancelarias de equipos. Cada publicación del DOF muestra el motivo por el que
aparece. Lo que no pasa el filtro sigue en «Todas las publicaciones del DOF» y en la búsqueda.

**Cómo mejorarla.** Si algo importante no aparece o sobra algo, basta con ajustar las listas de términos de
[reglas.yaml]({vista.url_repo('/edit/main/config/reglas.yaml')}) o las fuentes de
[fuentes.yaml]({vista.url_repo('/edit/main/config/fuentes.yaml')}). Al guardar, una corrida reclasifica todo el
historial. También puedes [abrir un issue]({vista.url_repo('/issues/new')}) con el caso.
""")
    st.markdown("##### Categorías")
    st.dataframe(pd.DataFrame([{"Categoría": c.nombre, "Qué cubre": c.descripcion}
                               for c in reglas.categorias.values()]), hide_index=True, width="stretch")
