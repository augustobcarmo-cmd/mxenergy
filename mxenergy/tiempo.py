"""Fechas en hora de la Ciudad de México y ediciones de la síntesis.

Una edición sale de lunes a viernes y cubre lo publicado desde el día hábil
anterior hasta el día previo: la del martes cubre el lunes; la del viernes, el
jueves; la del lunes, de viernes a domingo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Mexico_City")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]


def ahora() -> datetime:
    return datetime.now(TZ)


def hoy() -> date:
    return ahora().date()


def a_local(dt: datetime) -> datetime:
    """Fecha y hora en la Ciudad de México (las ingenuas se toman como UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ)


def periodo(edicion: date) -> tuple[date, date]:
    """(desde, hasta) que cubre la edición de ese día (lunes a viernes)."""
    if edicion.weekday() >= 5:
        raise ValueError("Las ediciones salen de lunes a viernes")
    hasta = edicion - timedelta(days=1)
    desde = hasta
    while desde.weekday() >= 5:
        desde -= timedelta(days=1)
    return desde, hasta


def edicion_de(dia: date) -> date:
    """Edición que cubre un día: el siguiente día hábil."""
    e = dia + timedelta(days=1)
    while e.weekday() >= 5:
        e += timedelta(days=1)
    return e


def edicion_vigente(hoy_: date) -> date:
    """La edición del día; en fin de semana, la del lunes siguiente (en curso)."""
    e = hoy_
    while e.weekday() >= 5:
        e += timedelta(days=1)
    return e


def ediciones(desde: date, hoy_: date) -> list[date]:
    """Ediciones con algo que mostrar, de la más nueva a la más vieja.

    Incluye la edición en curso (la que cubre hoy), que se va llenando a lo
    largo del día.
    """
    ultima = edicion_de(hoy_)
    primera = edicion_de(desde)
    out, e = [], ultima
    while e >= primera:
        if e.weekday() < 5:
            out.append(e)
        e -= timedelta(days=1)
    return out


def dias(desde: date, hasta: date) -> list[date]:
    n = (hasta - desde).days
    return [desde + timedelta(days=i) for i in range(n + 1)]


# --- formato -----------------------------------------------------------------

def larga(d: date) -> str:
    """'lunes 23 de noviembre de 2026'."""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def corta(d: date) -> str:
    """'lun 23 nov'."""
    return f"{DIAS_CORTOS[d.weekday()]} {d.day} {MESES_CORTOS[d.month - 1]}"


def rango(desde: date, hasta: date) -> str:
    """'viernes 20 al domingo 22 de noviembre de 2026' (o un solo día)."""
    if desde == hasta:
        return larga(desde)
    if (desde.year, desde.month) == (hasta.year, hasta.month):
        return (f"{DIAS[desde.weekday()]} {desde.day} al {DIAS[hasta.weekday()]} "
                f"{hasta.day} de {MESES[hasta.month - 1]} de {hasta.year}")
    return f"{larga(desde)} al {larga(hasta)}"
