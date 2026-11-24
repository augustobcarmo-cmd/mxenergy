"""Normalización de texto para las reglas y la búsqueda."""

from __future__ import annotations

import re
import unicodedata

_NO_ALFANUM = re.compile(r"[^a-z0-9.]+")
# Un punto solo se conserva entre dígitos (8541.43); el resto es puntuación.
_PUNTO_SUELTO = re.compile(r"(?<!\d)\.|\.(?!\d)")


def sin_acentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def normalizar(s: str | None) -> str:
    """Minúsculas, sin acentos, solo letras, números y puntos entre dígitos."""
    if not s:
        return ""
    s = _NO_ALFANUM.sub(" ", sin_acentos(s).lower())
    s = _PUNTO_SUELTO.sub(" ", s)
    return " ".join(s.split())


def recortar(s: str | None, n: int) -> str:
    """Primeros n caracteres sin cortar palabras, con «…» si se recortó."""
    s = " ".join((s or "").split())
    if len(s) <= n:
        return s
    corte = s[:n].rsplit(" ", 1)[0]
    return corte.rstrip(",;:.") + "…"


def html_a_texto(html: str | None) -> str:
    """Texto visible de un fragmento HTML (sin scripts ni estilos)."""
    if not html:
        return ""
    from selectolax.lexbor import LexborHTMLParser

    arbol = LexborHTMLParser(html)
    for nodo in arbol.css("script, style, noscript"):
        nodo.decompose()
    raiz = arbol.body or arbol.root
    if raiz is None:
        return ""
    texto = raiz.text(separator="\n", strip=True)
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n{2,}", "\n", texto).strip()
