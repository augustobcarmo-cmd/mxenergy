import sqlite3

import yaml
from conftest import HOY, RAIZ, RedFalsa

from mxenergy.almacen import Almacen
from mxenergy.recolector import correr
from mxenergy.red import ErrorRed


def test_corrida_completa_e_idempotente(tmp_path, config, red):
    datos = tmp_path / "datos"
    r = correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    assert r["cambios"] and not r["alertas"]
    alm = Almacen(datos)
    items = alm.items()
    assert sum(1 for i in items.values() if i["tipo"] == "dof") == 6
    assert {i["fuente_id"] for i in items.values() if i["tipo"] == "noticia"} == \
        {"energia_estrategica", "medio", "mbn"}
    estado = alm.leer_json("estado.json")
    assert estado["fuentes"]["dof"]["fallas_seguidas"] == 0
    assert estado["fuentes"]["dof"]["ultimo_item"] == "2026-11-23"
    assert estado["version_reglas"]
    assert alm.leer_json("meta.json")["total"] == len(items)
    assert "DOF 2026-11-23" in (datos / "logs" / "ultima.log").read_text(encoding="utf-8")
    assert len(alm.ejecuciones()) == 1
    assert alm.leer_json("cache.json")["ee_fechas"]

    primera_vez = {k: v["primera_vez"] for k, v in items.items()}
    r2 = correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    assert r2["registro"]["agregados"] == 0 and r2["registro"]["actualizados"] == 0
    items2 = Almacen(datos).items()
    assert {k: v["primera_vez"] for k, v in items2.items()} == primera_vez
    assert len(Almacen(datos).ejecuciones()) == 2


def test_fuente_caida_suma_fallas_y_alerta(tmp_path, config):
    red = RedFalsa({}, por_defecto=ErrorRed("caído"))
    datos = tmp_path / "datos"
    r = correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    assert not r["alertas"]                      # una falla todavía no alerta
    r = correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    assert r["alertas"] and r["alertas"][0].startswith("DOF lleva 2 corridas con error")
    s = Almacen(datos).leer_json("estado.json")["fuentes"]["dof"]
    assert s["fallas_seguidas"] == 2 and "caído" in s["ultimo_error"]["mensaje"]


def test_reglas_nuevas_reclasifican_el_historial(tmp_path, config, red):
    datos = tmp_path / "datos"
    correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    reglas = yaml.safe_load((RAIZ / "config" / "reglas.yaml").read_text(encoding="utf-8"))
    reglas["umbrales"]["alta"] = 9
    ruta = tmp_path / "reglas.yaml"
    ruta.write_text(yaml.safe_dump(reglas, allow_unicode=True), encoding="utf-8")
    r = correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red, reglas_ruta=ruta)
    assert r["registro"]["reclasificados"] > 0
    items = Almacen(datos).items()
    assert not any(i["prioridad"] == "alta" for i in items.values())
    # la fracción hallada en el texto sigue contando sin volver a bajarlo
    assert "industria" in items["dof:5804604"]["categorias"]


def test_reproceso_vuelve_a_bajar_el_dof(tmp_path, config, red):
    datos = tmp_path / "datos"
    correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    red.pedidas.clear()
    correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red, reprocesar_dof_dias=3)
    assert [u for u in red.pedidas if u.endswith("/notas/nota/5804604")]
    assert not any(i.get("sin_texto") for i in Almacen(datos).items().values())


def test_migracion_desde_la_base_anterior(tmp_path):
    from scripts.migrar_sqlite import migrar

    db = tmp_path / "viejo.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE items (source TEXT, source_type TEXT, title TEXT, url TEXT, "
                "published_at TEXT, published_date TEXT, raw_text TEXT, created_at TEXT)")
    filas = [
        ("Energía Estratégica", "noticia", "México prorroga convocatoria de 935 MW BESS",
         "https://www.energiaestrategica.com/es/notes/mexico-bess", "2026-11-20T10:00:00-06:00",
         "2026-11-20", "La SENER amplió el plazo del almacenamiento.", "2026-11-21T09:00:00-06:00"),
        ("PV Magazine México", "noticia", "Nuevo parque solar en Sonora", "https://pv.example/a",
         "2026-11-20T08:00:00-06:00", "2026-11-20", "100 MW fotovoltaicos.", "2026-11-21T09:00:00-06:00"),
        ("SENER", "comunicado", "Tuit", "https://twitter.com/x", "2026-11-20T08:00:00-06:00",
         "2026-11-20", "", "2026-11-21T09:00:00-06:00"),
        ("Mondaq", "analisis", "Nota", "https://mondaq.example", "2026-11-20T08:00:00-06:00",
         "2026-11-20", "", "2026-11-21T09:00:00-06:00"),
    ]
    con.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", filas)
    con.commit()
    con.close()
    r = migrar(db, tmp_path / "datos")
    assert r["migradas"] == 2 and r["total"] == 2
    items = {i["fuente_id"]: i for i in Almacen(tmp_path / "datos").items().values()}
    assert items["energia_estrategica"]["region"] == "México"
    assert "almacenamiento" in items["energia_estrategica"]["categorias"]
    assert items["pv_magazine"]["primera_vez"].startswith("2026-11-21")


def test_app_muestra_la_edicion_y_busca(tmp_path, config, red, monkeypatch):
    from streamlit.testing.v1 import AppTest

    datos = tmp_path / "datos"
    correr(datos, usar_navegador=False, hoy=HOY, config=config, red=red)
    monkeypatch.setenv("MXENERGY_DATOS", str(datos))
    monkeypatch.setenv("MXENERGY_HOY", HOY.isoformat())
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    texto = "\n".join(m.value for m in at.markdown)
    assert "Periodo cubierto:** lunes 23 de noviembre de 2026" in texto
    assert "Reglas Generales de Comercio Exterior" in texto            # DOF relevante
    assert "recaudación federal participable" not in texto             # excluida (solo en la tabla)
    assert "Atlas firma su primer PPA privado en México" in texto      # EE México
    assert "Chile licita baterías en el norte" in texto                # EE internacional
    assert "Red Nacional de Transmisión" in texto                      # otras fuentes

    at.text_input(key="consulta").set_value("baterias").run()
    assert not at.exception
    assert any("resultados" in m.value for m in at.markdown)

    at.sidebar.multiselect[0].set_value(["fiscal"]).run()
    assert not at.exception
    texto = "\n".join(m.value for m in at.markdown)
    assert "Atlas firma" not in texto.split("##### Fuentes")[0].split("Busca en todo")[0]
