from datetime import date

import pytest

from mxenergy import tiempo
from mxenergy.texto import normalizar, recortar


# --- ediciones -----------------------------------------------------------------

@pytest.mark.parametrize("edicion,desde,hasta", [
    (date(2026, 11, 24), date(2026, 11, 23), date(2026, 11, 23)),   # martes → lunes
    (date(2026, 11, 20), date(2026, 11, 19), date(2026, 11, 19)),   # viernes → jueves
    (date(2026, 11, 23), date(2026, 11, 20), date(2026, 11, 22)),   # lunes → vie a dom
])
def test_periodo_de_cada_edicion(edicion, desde, hasta):
    assert tiempo.periodo(edicion) == (desde, hasta)


def test_no_hay_edicion_en_fin_de_semana():
    with pytest.raises(ValueError):
        tiempo.periodo(date(2026, 11, 21))


def test_edicion_que_cubre_cada_dia():
    assert tiempo.edicion_de(date(2026, 11, 20)) == date(2026, 11, 23)   # viernes → lunes
    assert tiempo.edicion_de(date(2026, 11, 22)) == date(2026, 11, 23)   # domingo → lunes
    assert tiempo.edicion_de(date(2026, 11, 23)) == date(2026, 11, 24)


def test_edicion_vigente_y_lista():
    assert tiempo.edicion_vigente(date(2026, 11, 24)) == date(2026, 11, 24)
    assert tiempo.edicion_vigente(date(2026, 11, 21)) == date(2026, 11, 23)   # sábado → lunes
    eds = tiempo.ediciones(date(2026, 11, 19), date(2026, 11, 24))
    # en curso (mié 25, cubre hoy), hoy, lunes 23, viernes 20; sin fines de semana
    assert eds == [date(2026, 11, 25), date(2026, 11, 24), date(2026, 11, 23), date(2026, 11, 20)]


def test_formatos():
    assert tiempo.larga(date(2026, 11, 23)) == "lunes 23 de noviembre de 2026"
    assert tiempo.corta(date(2026, 11, 23)) == "lun 23 nov"
    assert tiempo.rango(date(2026, 11, 20), date(2026, 11, 22)) == \
        "viernes 20 al domingo 22 de noviembre de 2026"


# --- texto ---------------------------------------------------------------------------

def test_normalizar_conserva_fracciones_y_quita_puntuacion():
    assert normalizar("Módulos: 8541.43.01, S.A. de C.V.") == "modulos 8541.43.01 s a de c v"
    assert normalizar("ENERGÍA ELÉCTRICA.") == "energia electrica"


def test_recortar():
    assert recortar("uno dos tres cuatro", 9) == "uno dos…"
    assert recortar("corto", 10) == "corto"


# --- reglas --------------------------------------------------------------------------

def test_dependencia_energetica_es_alta(reglas):
    c = reglas.clasificar("Acuerdo por el que se emiten lineamientos", dependencia="SECRETARIA DE ENERGIA")
    assert c.prioridad == "alta" and "energia" in c.categorias
    assert "Dependencia: SENER" in c.motivos


def test_frase_completa_no_coincide_dentro_de_otra_palabra(reglas):
    assert reglas.clasificar("Programa de capacitación para personal de la Cfecto").prioridad == ""
    assert reglas.clasificar("Tarifas de la CFE para 2027").prioridad == "alta"


def test_reglas_de_comercio_exterior_y_fracciones(reglas):
    c = reglas.clasificar("Tercera Resolución de Modificaciones a las Reglas Generales de Comercio Exterior",
                          dependencia="SECRETARIA DE HACIENDA Y CREDITO PUBLICO")
    assert c.prioridad == "media" and c.categorias == ["fiscal"]
    c = reglas.clasificar("Tercera Resolución de Modificaciones a las Reglas Generales de Comercio Exterior",
                          "Anexo 22: 8541.43.01 módulos", dependencia="SECRETARIA DE HACIENDA Y CREDITO PUBLICO")
    assert c.prioridad == "alta" and c.categorias[0] == "industria"
    assert any("8541.43" in m for m in c.motivos)
    assert "8541.43.01" in c.coincidencias


def test_partida_de_cuatro_digitos_exige_subpartida(reglas):
    assert reglas.clasificar("Aviso", "pago de 8544 pesos").prioridad == ""
    assert reglas.clasificar("Aviso", "fracción 8544.49.99").prioridad != ""


def test_exclusiones_de_rutina(reglas):
    c = reglas.clasificar("Acuerdo por el cual se da a conocer el informe sobre la recaudación federal "
                          "participable y las participaciones federales", "Comisión Federal de Electricidad",
                          dependencia="SECRETARIA DE HACIENDA Y CREDITO PUBLICO")
    assert c.prioridad == ""
    c = reglas.clasificar("Acuerdo por el cual se dan a conocer los montos de los estímulos fiscales "
                          "aplicables a la enajenación de gasolinas en la región fronteriza")
    assert c.prioridad == ""


def test_la_exclusion_no_tapa_a_una_dependencia_energetica(reglas):
    c = reglas.clasificar("Código de Conducta de la Comisión Federal de Electricidad",
                          dependencia="COMISION FEDERAL DE ELECTRICIDAD")
    assert c.prioridad == "alta"


def test_autoconsumo_de_petroliferos_no_es_electrico(reglas):
    c = reglas.clasificar("Acuerdo que regula el autoconsumo de petrolíferos en flotillas")
    assert c.categorias == ["hidrocarburos"] and c.prioridad == "media"
    c = reglas.clasificar("Lineamientos del autoconsumo de energía eléctrica")
    assert "electricidad" in c.categorias and c.prioridad == "alta"


def test_texto_solo_suma_poco_y_los_sinonimos_cuentan_una_vez(reglas):
    c = reglas.clasificar("Acuerdo de la Secretaría de Turismo",
                          "pagos a la Comisión Federal de Electricidad (CFE) por energía")
    assert c.prioridad == "baja" and c.puntaje == 1


def test_el_cuerpo_no_da_bonus_a_un_estatuto(reglas):
    c = reglas.clasificar("Estatuto Orgánico de Petróleos Mexicanos",
                          "sector eléctrico, generación eléctrica y centrales eléctricas",
                          dependencia="PETROLEOS MEXICANOS")
    assert c.prioridad == "media"


def test_techo_de_hidrocarburos(reglas):
    c = reglas.clasificar("Lineamientos para estaciones de servicio de gas natural",
                          dependencia="AGENCIA DE SEGURIDAD, ENERGIA Y AMBIENTE")
    assert c.prioridad == "media" and c.puntaje == 2


def test_edicto_no_se_clasifica(reglas):
    assert reglas.clasificar("Juzgado — EDICTO", "Comisión Federal de Electricidad",
                             es_edicto=True).prioridad == ""


def test_regex_muestra_lo_hallado(reglas):
    c = reglas.clasificar("NOM-001-SEDE-2026, Instalaciones eléctricas")
    assert any("nom 001 sede" in m for m in c.motivos)


def test_mexico_sin_confundir_a_chile_ni_a_nuevo_mexico(reglas):
    assert reglas.es_mexico("Atlas firma PPA en Sonora")
    assert reglas.es_mexico("México lanza convocatoria")
    assert not reglas.es_mexico("La CNE de Chile licita baterías")
    assert not reglas.es_mexico("Nuevo México aprueba un parque solar")


def test_reclasificar_con_coincidencias_guardadas(reglas):
    original = reglas.clasificar("Decreto por el que se modifica la Tarifa", "fracción 8541.43.01")
    otra = reglas.clasificar("Decreto por el que se modifica la Tarifa", original.coincidencias,
                             normalizado=True)
    assert (otra.prioridad, otra.categorias) == (original.prioridad, original.categorias)


def test_resumen_que_repite_el_titulo_no_se_muestra():
    from mxenergy.vista import resumen_util, tipo_doc

    assert resumen_util("Banco Sabadell moviliza USD 56 millones", "Banco Sabadell moviliza USD 56 millones") == ""
    assert resumen_util("Título", "Otra cosa distinta") == "Otra cosa distinta"
    assert tipo_doc("RESOLUCION") == "Resolución" and tipo_doc("CONVOCATORIA") == "Convocatoria"
