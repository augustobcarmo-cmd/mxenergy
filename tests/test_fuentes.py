import json
from datetime import date

from conftest import RedFalsa, contexto, fixture, tabla_noticias, tabla_sidof

from mxenergy.fuentes.dof import (FuenteDOF, encabezado_aviso, notas_sidof, parse_indice_legado,
                                  tipo_doc, url_publica)
from mxenergy.fuentes.energia_estrategica import FuenteEE, leer_articulo, portada_servidor, url_canonica
from mxenergy.fuentes.mbn import FuenteMBN, enlaces_listado
from mxenergy.fuentes.mbn import leer_articulo as leer_mbn
from mxenergy.fuentes.rss import FuenteRSS, leer_feed
from mxenergy.red import ErrorRed

DOF_CFG = {"inicio_historial": "2026-11-18", "dias_revision": 3, "max_dias_por_corrida": 10,
           "max_notas_por_corrida": 100, "descargas_simultaneas": 2}


# --- DOF ---------------------------------------------------------------------------

def test_notas_sidof_sin_encabezados():
    notas = notas_sidof(json.loads(fixture("sidof_dia.json")))
    cods = {n["cod"] for n in notas}
    assert 5804596 not in cods             # encabezado de dependencia, sin título
    assert {5804603, 5804604, 9000001} <= cods
    ves = next(n for n in notas if n["cod"] == 9000001)
    assert ves["edicion"] == "VES" and ves["dependencia"] == "SECRETARIA DE ENERGIA"
    assert next(n for n in notas if n["cod"] == 5804627)["aviso"]


def test_tipo_doc_y_url():
    assert tipo_doc("Tercera Resolución de Modificaciones a las Reglas") == "RESOLUCION"
    assert tipo_doc("Acuerdo por el que se emiten") == "ACUERDO"
    assert tipo_doc("Disposiciones administrativas de carácter general que establecen") == "DACG"
    assert tipo_doc("Norma Oficial Mexicana NOM-001-SEDE-2026") == "NOM"
    assert url_publica(5804604, date(2026, 11, 23)) == \
        "https://www.dof.gob.mx/nota_detalle.php?codigo=5804604&fecha=23/11/2026"


def test_organismo_y_objeto_de_convocatorias():
    from mxenergy.fuentes.dof import objeto_convocatoria, organismo_de

    assert organismo_de("018TON - CENTRO NACIONAL DE CONTROL DEL GAS NATURAL - REF:582598") == \
        "CENTRO NACIONAL DE CONTROL DEL GAS NATURAL"
    texto = "\n".join(["CFE COORDINACION REGIONAL DE PRODUCCION NOROESTE", "Con fundamento en …",
                       "Internacional Bajo la Cobertura de los Tratados No.", "CFE-0600-CAAAT-0022-2026",
                       "Adquisición de componentes para transformadores principales",
                       "de 176 MVA de la C.T. Puerto Libertad.", "Volumen a adquirir", "149 pzas"])
    assert objeto_convocatoria(texto) == ("Adquisición de componentes para transformadores principales "
                                          "de 176 MVA de la C.T. Puerto Libertad.")
    assert objeto_convocatoria("UNIVERSIDAD\nObjeto de la licitación: Servicio de limpieza integral") == \
        "Servicio de limpieza integral"


def test_encabezado_de_avisos():
    titulo, emisor, edicto, cuerpo = encabezado_aviso(
        "Estados Unidos Mexicanos\nCOMISIÓN FEDERAL DE ELECTRICIDAD\nCFE TRANSMISIÓN\nCONVOCATORIA\nObras.")
    assert emisor == "COMISIÓN FEDERAL DE ELECTRICIDAD" and not edicto
    assert titulo.startswith("COMISIÓN FEDERAL DE ELECTRICIDAD — CFE TRANSMISIÓN")
    assert encabezado_aviso("Estados Unidos Mexicanos\nJuzgado Primero\nEDICTO\nTexto")[2]


def test_dof_recolecta_clasifica_y_registra_dias(reglas):
    red = RedFalsa(tabla_sidof())
    estado: dict = {}
    fuente = FuenteDOF(DOF_CFG)
    items = {i["id"]: i for i in fuente.recolectar(contexto(reglas, red, estado=estado))}
    assert len(items) == 8
    rgce = items["dof:5804604"]
    assert rgce["prioridad"] == "alta" and "industria" in rgce["categorias"]
    assert rgce["sigla"] == "SHCP" and rgce["edicion"] == "MAT" and rgce["tipo_doc"] == "RESOLUCION"
    assert "energía eléctrica" not in (rgce["coincidencias"] or "")   # el <script> no cuenta
    assert items["dof:5804603"]["prioridad"] == ""                    # participaciones: excluida
    assert items["dof:9000001"]["prioridad"] == "alta"                # SENER, vespertina
    edicto = items["dof:5804627"]
    assert edicto["tipo_doc"] == "EDICTO" and edicto["prioridad"] == ""
    aviso = items["dof:5804628"]
    assert aviso["titulo"].startswith("COMISIÓN FEDERAL DE ELECTRICIDAD")
    assert aviso["sigla"] == "CFE" and aviso["prioridad"] == "alta"
    assert "transmision" in aviso["categorias"]
    # Convocatorias: el título dice qué se licita; quien publica (CFE) ya no basta
    fv = items["dof:5804998"]
    assert fv["titulo"] == "COMISION FEDERAL DE ELECTRICIDAD — Adquisicion de sistemas fotovoltaicos"
    assert fv["tipo_doc"] == "CONVOCATORIA" and fv["prioridad"] == "alta" and fv["sigla"] == "CFE"
    carbon = items["dof:5804986"]
    assert carbon["titulo"].startswith("COMISION FEDERAL DE ELECTRICIDAD — Adquisición, Mantenimiento")
    assert carbon["prioridad"] == "baja"
    reg = estado["dof_dias"]
    assert reg["2026-11-23"]["estado"] == "ok" and reg["2026-11-23"]["ediciones"] == ["MAT", "VES"]
    assert reg["2026-11-22"]["estado"] == "sin_edicion"
    assert fuente.detalles["dias_pendientes"] == 0


def test_dof_no_vuelve_a_bajar_textos(reglas):
    red = RedFalsa(tabla_sidof())
    fuente = FuenteDOF(DOF_CFG)
    primera = {i["id"]: i for i in fuente.recolectar(contexto(reglas, red))}
    red.pedidas.clear()
    FuenteDOF(DOF_CFG).recolectar(contexto(reglas, red, existentes=primera))
    assert not [u for u in red.pedidas if "/notas/nota/" in u]


def test_dof_presupuesto_deja_el_dia_parcial(reglas):
    red = RedFalsa(tabla_sidof())
    estado: dict = {}
    cfg = {**DOF_CFG, "max_notas_por_corrida": 2}
    items = FuenteDOF(cfg).recolectar(contexto(reglas, red, estado=estado))
    assert len(items) == 2
    assert estado["dof_dias"]["2026-11-23"]["estado"] == "parcial"


def test_dof_usa_el_indice_clasico_si_el_sidof_falla(reglas):
    tabla = tabla_sidof()
    tabla["https://sidof.segob.gob.mx/dof/sidof/notas/20-11-2026"] = ErrorRed("HTTP 500")
    legado = fixture("dof_indice_legado.html")
    for ed in ("MAT", "VES"):
        tabla[f"https://diariooficial.segob.gob.mx/index.php?year=2026&month=11&day=20&edicion={ed}"] = legado
    cuerpos = {9100001: "Texto de prueba sobre generación distribuida.",
               9100002: "Texto de prueba sobre el abasto de medicamentos."}
    for cod, cuerpo in cuerpos.items():
        tabla[f"https://diariooficial.segob.gob.mx/nota_detalle.php?codigo={cod}&fecha=20/11/2026"] = \
            f"<html><div id='DivDetalleNota'><p>{cuerpo}</p></div></html>"
    estado: dict = {}
    items = {i["id"]: i for i in FuenteDOF(DOF_CFG).recolectar(
        contexto(reglas, RedFalsa(tabla), estado=estado))}
    assert estado["dof_dias"]["2026-11-20"]["origen"] == "dof.gob.mx"
    assert items["dof:9100001"]["sigla"] == "SENER"
    assert items["dof:9100002"]["prioridad"] == ""


def test_dof_falla_si_nada_responde(reglas):
    import pytest

    with pytest.raises(RuntimeError):
        FuenteDOF(DOF_CFG).recolectar(contexto(reglas, RedFalsa({}, por_defecto=ErrorRed("caído"))))


def test_parse_indice_legado():
    notas = parse_indice_legado(fixture("dof_indice_legado.html").decode())
    assert [(n["cod"], n["dependencia"]) for n in notas] == [
        (9100001, "SECRETARIA DE ENERGIA"), (9100002, "SECRETARIA DE SALUD")]


# --- RSS -------------------------------------------------------------------------------

def test_leer_feed_en_hora_local():
    entradas = leer_feed(fixture("feed.xml"))
    assert entradas[0]["publicado"].isoformat().startswith("2026-11-23T12:30")   # 18:30 UTC
    assert entradas[0]["resumen"].startswith("El CENACE dio a conocer")
    assert entradas[0]["etiquetas"] == ["Transmisión"]


def test_categorias_de_noticias_con_terminos_propios(reglas):
    c = reglas.clasificar("Chile acumula atrasos en sus obras de transmisión", es_noticia=True)
    assert c.categorias == ["transmision"]
    c = reglas.clasificar("Los módulos Suntech obtienen certificación", es_noticia=True)
    assert c.categorias == ["industria"]
    # «módulos» solo no basta en el DOF
    assert reglas.clasificar("Acuerdo por el que se crean los Módulos de Atención Social").prioridad == ""


def test_rss_ventana_y_clasificacion(reglas):
    red = RedFalsa({"https://medio.example/feed/": fixture("feed.xml")})
    items = FuenteRSS({"id": "medio", "nombre": "Medio", "url": "https://medio.example/feed/"}).recolectar(
        contexto(reglas, red))
    assert len(items) == 2                       # la nota del 10-nov queda fuera de la ventana
    rnt = next(i for i in items if "cenace" in i["url"])
    assert "transmision" in rnt["categorias"] and rnt["region"] is None
    assert red.pedidas[-1].endswith("?paged=2") or len(red.pedidas) == 1


# --- Energía Estratégica ---------------------------------------------------------------------

def test_url_canonica_solo_espanol():
    assert url_canonica("/es/notes/abc-def-ghi-jkl") == "https://www.energiaestrategica.com/es/notes/abc-def-ghi-jkl"
    assert url_canonica("/energiaestrategica/es/notes/abc-def-ghi-jkl").endswith("/es/notes/abc-def-ghi-jkl")
    assert url_canonica("/en/notes/abc-def-ghi-jkl") is None


def test_leer_articulo_ee():
    a = leer_articulo(fixture("ee_mexico.html").decode())
    assert a["titulo"].startswith("Atlas firma") and a["etiquetas"] == ["PPA México", "baterías", "Sonora"]
    assert a["publicado"].isoformat().startswith("2026-11-23T09:00")
    b = leer_articulo(fixture("ee_chile.html").decode())          # JSON-LD en lista
    assert b["titulo"] == "Chile licita baterías en el norte"


def test_portada_del_servidor():
    slugs = portada_servidor(fixture("ee_portada.html").decode())
    assert len(slugs) == 3


def test_ee_recolecta_con_cache_y_region(reglas):
    red = RedFalsa(tabla_noticias())
    estado: dict = {}
    fuente = FuenteEE({"listados": [{"url": "https://www.energiaestrategica.com/es/articles/mexico",
                                     "region": "México"}]})
    items = {i["titulo"]: i for i in fuente.recolectar(contexto(reglas, red, estado=estado))}
    assert set(items) == {"Atlas firma su primer PPA privado en México con baterías",
                          "Chile licita baterías en el norte"}
    assert items["Atlas firma su primer PPA privado en México con baterías"]["region"] == "México"
    assert items["Chile licita baterías en el norte"]["region"] == "Internacional"
    assert "almacenamiento" in items["Chile licita baterías en el norte"]["categorias"]
    assert fuente.avisos                                   # sin navegador: lo avisa
    cache = estado["ee_fechas"]
    assert cache["https://www.energiaestrategica.com/es/notes/nota-vieja-republicada-de-prueba"].startswith("2026-05")
    # Segunda corrida: lo viejo no se vuelve a abrir
    red.pedidas.clear()
    FuenteEE({}).recolectar(contexto(reglas, red, estado=estado))
    assert not [u for u in red.pedidas if "nota-vieja" in u]


# --- MBN -------------------------------------------------------------------------------------

def test_mbn():
    assert enlaces_listado(fixture("mbn_listado.html").decode()) == [
        "https://mexicobusiness.news/energy/news/cfe-awards-transmission-works-test"]
    a = leer_mbn(fixture("mbn_articulo.html").decode())
    assert a["titulo"] == "CFE Awards Transmission Works in Sonora"
    assert a["publicado"].isoformat().startswith("2026-11-23T09:15")


def test_mbn_recolecta(reglas):
    items = FuenteMBN({}).recolectar(contexto(reglas, RedFalsa(tabla_noticias())))
    assert len(items) == 1 and items[0]["fuente"] == "Mexico Business News"
