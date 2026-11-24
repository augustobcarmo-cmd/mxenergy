"""Red simulada y utilidades comunes: ninguna prueba sale a internet."""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from mxenergy import tiempo  # noqa: E402
from mxenergy.fuentes import Contexto  # noqa: E402
from mxenergy.red import ErrorRed  # noqa: E402
from mxenergy.reglas import Reglas  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
HOY = date(2026, 11, 24)


def fixture(nombre: str) -> bytes:
    return (FIX / nombre).read_bytes()


class Respuesta:
    def __init__(self, contenido: bytes):
        self.content = contenido
        self.status_code = 200
        self.encoding = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content)


class RedFalsa:
    """Responde según una tabla URL → bytes | Exception | callable(url)."""

    def __init__(self, tabla: dict | None = None, por_defecto=None):
        self.tabla = dict(tabla or {})
        self.por_defecto = por_defecto
        self.peticiones = 0
        self.pedidas: list[str] = []

    def get(self, url: str, verify: bool = True, **kw):
        self.peticiones += 1
        self.pedidas.append(url)
        r = self.tabla.get(url, self.por_defecto)
        if callable(r):
            r = r(url)
        if r is None:
            raise ErrorRed(f"HTTP 404 en {url}")
        if isinstance(r, Exception):
            raise r
        if isinstance(r, str):
            r = r.encode("utf-8")
        return Respuesta(r)

    def contenido(self, url, **kw):
        return self.get(url, **kw).content

    def texto(self, url, **kw):
        return self.get(url, **kw).text

    def json(self, url, **kw):
        return self.get(url, **kw).json()


def tabla_sidof() -> dict:
    """SIDOF: el 23-11-2026 con notas; cualquier otro día, sin edición."""
    vacio = json.dumps({"messageCode": 200, "response": "OK", "NotasMatutinas": [],
                        "NotasVespertinas": [], "NotasExtraordinarias": []}).encode()
    notas = json.loads(fixture("sidof_notas.json"))
    tabla = {}
    base = "https://sidof.segob.gob.mx/dof/sidof"
    for i in range(0, 200):
        d = date(2026, 8, 1).toordinal() + i
        f = date.fromordinal(d)
        tabla[f"{base}/notas/{f:%d-%m-%Y}"] = vacio
    tabla[f"{base}/notas/23-11-2026"] = fixture("sidof_dia.json")
    for cod, html in notas.items():
        if cod.startswith("_"):
            continue
        tabla[f"{base}/notas/nota/{cod}"] = json.dumps(
            {"messageCode": 200, "Nota": {"codNota": int(cod), "cadenaContenido": html}}).encode()
    return tabla


def tabla_noticias() -> dict:
    ee = "https://www.energiaestrategica.com"
    return {
        "https://medio.example/feed/": fixture("feed.xml"),
        f"{ee}/energiaestrategica/es": fixture("ee_portada.html"),
        f"{ee}/es/notes/atlas-firma-ppa-en-mexico-con-baterias-de-prueba": fixture("ee_mexico.html"),
        f"{ee}/es/notes/chile-licita-baterias-de-prueba-en-el-norte": fixture("ee_chile.html"),
        f"{ee}/es/notes/nota-vieja-republicada-de-prueba": fixture("ee_vieja.html"),
        "https://mexicobusiness.news/energy": fixture("mbn_listado.html"),
        "https://mexicobusiness.news/energy/news/cfe-awards-transmission-works-test": fixture("mbn_articulo.html"),
    }


CONFIG_PRUEBA = {
    "dof": {"activa": True, "inicio_historial": "2026-11-18", "dias_revision": 3,
            "max_dias_por_corrida": 10, "max_notas_por_corrida": 100, "descargas_simultaneas": 2},
    "noticias": {"ventana_dias": 4, "fuentes": [
        {"id": "energia_estrategica", "nombre": "Energía Estratégica", "tipo": "energia_estrategica",
         "prioridad": 1, "listados": [{"url": "https://www.energiaestrategica.com/es/articles/mexico",
                                       "region": "México"}]},
        {"id": "medio", "nombre": "Medio de prueba", "tipo": "rss", "url": "https://medio.example/feed/",
         "prioridad": 2},
        {"id": "mbn", "nombre": "Mexico Business News", "tipo": "mbn",
         "url": "https://mexicobusiness.news/energy", "prioridad": 2},
    ]},
    "alertas": {"dof": 2},
}


@pytest.fixture
def reglas() -> Reglas:
    return Reglas.cargar()


@pytest.fixture
def config(tmp_path) -> Path:
    ruta = tmp_path / "fuentes.yaml"
    ruta.write_text(yaml.safe_dump(CONFIG_PRUEBA, allow_unicode=True), encoding="utf-8")
    return ruta


@pytest.fixture
def red() -> RedFalsa:
    return RedFalsa({**tabla_sidof(), **tabla_noticias()})


def contexto(reglas: Reglas, red, existentes=None, estado=None, hoy: date = HOY) -> Contexto:
    return Contexto(red=red, reglas=reglas, hoy=hoy,
                    ahora=datetime(hoy.year, hoy.month, hoy.day, 5, 17, tzinfo=tiempo.TZ),
                    estado=estado if estado is not None else {}, existentes=existentes or {},
                    ventana_desde=date(2026, 11, 21), log=logging.getLogger("prueba"),
                    usar_navegador=False)
