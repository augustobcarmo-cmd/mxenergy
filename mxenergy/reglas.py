"""Motor de reglas: categorías, puntaje y prioridad sin IA.

Las reglas viven en config/reglas.yaml; este módulo solo las interpreta. Todo
se compara sobre texto normalizado (minúsculas, sin acentos) y como frase
completa, así que «cfe» no coincide dentro de otra palabra.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from mxenergy.texto import normalizar

RAIZ = Path(__file__).resolve().parents[1]
RUTA_REGLAS = RAIZ / "config" / "reglas.yaml"
PRIORIDADES = ("alta", "media", "baja")
MAX_TEXTO = 300_000  # caracteres del cuerpo que se revisan (los decretos largos se recortan)


@dataclass
class Termino:
    texto: str           # como aparece en el YAML, para mostrarlo
    patron: re.Pattern
    clave: str           # forma normalizada (sin el *)
    es_regex: bool = False

    def etiqueta(self, coincidencia: str) -> str:
        """Lo que se muestra en «motivos»: el término o, si es regex, lo hallado."""
        return coincidencia if self.es_regex else self.texto

    def busca(self, fragmentos: Iterable[str]) -> str | None:
        """Primera coincidencia (normalizada) en alguno de los fragmentos."""
        for f in fragmentos:
            if f:
                m = self.patron.search(f)
                if m:
                    return m.group(0)
        return None


def compilar(termino: str) -> Termino:
    termino = str(termino).strip()
    if termino.startswith("re:"):
        cuerpo = termino[3:]
        return Termino(cuerpo, re.compile(cuerpo), cuerpo, es_regex=True)
    prefijo = termino.endswith("*")
    limpio = termino.rstrip("*").strip()
    clave = normalizar(limpio)
    cuerpo = " ".join(re.escape(p) for p in clave.split(" "))
    fin = r"[a-z0-9]*" if prefijo else r"(?![a-z0-9])"
    patron = re.compile(r"(?<![a-z0-9])" + cuerpo + fin)
    return Termino(limpio + ("…" if prefijo else ""), patron, clave)


@dataclass
class Fraccion:
    codigo: str
    nombre: str
    patron: re.Pattern

    @classmethod
    def de(cls, codigo: str, nombre: str) -> "Fraccion":
        codigo = str(codigo).strip()
        cuerpo = re.escape(codigo)
        # Una partida de 4 dígitos se exige con subpartida («8544.49») para no
        # confundirla con un número cualquiera.
        resto = r"(?:\.\d{2})+" if "." not in codigo else r"(?:\.\d{2})*"
        return cls(codigo, nombre, re.compile(r"(?<![0-9.])" + cuerpo + resto + r"(?![0-9])"))

    def busca(self, fragmentos: Iterable[str]) -> str | None:
        for f in fragmentos:
            if f:
                m = self.patron.search(f)
                if m:
                    return m.group(0)
        return None


@dataclass
class Categoria:
    id: str
    nombre: str
    color: str
    descripcion: str
    peso_titulo: int
    cuenta_texto: bool
    max_texto: int
    techo: int | None
    terminos: list[Termino]
    solo_titulo: list[Termino]
    noticias: list[Termino]      # términos que solo se usan con noticias (en el DOF serían ambiguos)
    ambiguos: set[str]
    ceder_a: str | None
    fracciones: list[Fraccion]
    puntos_fraccion: int


@dataclass
class Dependencia:
    clave: str
    sigla: str
    categoria: str
    puntos: int


@dataclass
class Clasificacion:
    categorias: list[str] = field(default_factory=list)
    puntaje: int = 0
    prioridad: str = ""
    motivos: list[str] = field(default_factory=list)
    coincidencias: list[str] = field(default_factory=list)


def _contiene(nombre: str, texto: str) -> bool:
    return f" {nombre} " in f" {texto} "


class Reglas:
    def __init__(self, datos: dict, version: str = ""):
        self.version = version
        u = datos.get("umbrales") or {}
        self.umbrales = {"alta": int(u.get("alta", 3)), "media": int(u.get("media", 2)),
                         "baja": int(u.get("baja", 1))}
        self.categorias: dict[str, Categoria] = {}
        for cid, c in (datos.get("categorias") or {}).items():
            self.categorias[cid] = Categoria(
                id=cid,
                nombre=c.get("nombre", cid),
                color=c.get("color", "gray"),
                descripcion=c.get("descripcion", ""),
                peso_titulo=int(c.get("peso_titulo", 2)),
                cuenta_texto=bool(c.get("cuenta_texto", False)),
                max_texto=int(c.get("max_texto", 2)),
                techo=c.get("techo"),
                terminos=[compilar(t) for t in c.get("terminos") or []],
                solo_titulo=[compilar(t) for t in c.get("solo_titulo") or []],
                noticias=[compilar(t) for t in c.get("noticias") or []],
                ambiguos={normalizar(str(t).rstrip("*")) for t in c.get("ambiguos") or []},
                ceder_a=c.get("ceder_a"),
                fracciones=[Fraccion.de(f["codigo"], f.get("nombre", ""))
                            for f in c.get("fracciones") or []],
                puntos_fraccion=int(c.get("puntos_fraccion", 3)),
            )
        self.orden = {cid: i for i, cid in enumerate(self.categorias)}
        self.dependencias = [
            Dependencia(normalizar(d["nombre"]), d.get("sigla", d["nombre"]),
                        d["categoria"], int(d.get("puntos", 3)))
            for d in datos.get("dependencias") or []]
        self.siglas = {normalizar(k): v for k, v in (datos.get("siglas") or {}).items()}
        for d in self.dependencias:
            self.siglas.setdefault(d.clave, d.sigla)
        self.excluir = [compilar(t) for t in datos.get("excluir_titulo") or []]
        self.mexico = [compilar(t) for t in datos.get("mexico") or []]
        self.no_mexico = [normalizar(t) for t in datos.get("no_mexico") or []]

    # --- carga -------------------------------------------------------------

    @classmethod
    def cargar(cls, ruta: Path | str | None = None) -> "Reglas":
        crudo = Path(ruta or RUTA_REGLAS).read_bytes()
        version = hashlib.sha1(crudo).hexdigest()[:12]
        return cls(yaml.safe_load(crudo) or {}, version)

    # --- consultas ---------------------------------------------------------

    def nombre(self, categoria: str) -> str:
        c = self.categorias.get(categoria)
        return c.nombre if c else categoria

    def color(self, categoria: str) -> str:
        c = self.categorias.get(categoria)
        return c.color if c else "gray"

    def sigla(self, dependencia: str | None) -> str | None:
        if not dependencia:
            return None
        n = normalizar(dependencia)
        for clave, sigla in self.siglas.items():
            if _contiene(clave, n):
                return sigla
        return None

    def dependencia(self, dependencia: str | None) -> Dependencia | None:
        if not dependencia:
            return None
        n = normalizar(dependencia)
        for d in self.dependencias:
            if _contiene(d.clave, n):
                return d
        return None

    def es_mexico(self, *textos: str | None) -> bool:
        n = normalizar(" \n ".join(t for t in textos if t))
        for x in self.no_mexico:
            n = n.replace(x, " ")
        return any(t.busca([n]) for t in self.mexico)

    # --- clasificación -----------------------------------------------------

    def clasificar(self, titulo: str, texto: str | list[str] | None = None,
                   dependencia: str | None = None, es_edicto: bool = False,
                   normalizado: bool = False, es_noticia: bool = False,
                   max_puntos_dependencia: int | None = None) -> Clasificacion:
        """Categorías, puntaje y prioridad de una publicación.

        `texto` es el cuerpo (DOF) o el resumen (noticias); también puede ser
        una lista de fragmentos ya normalizados (`normalizado=True`), que es como
        se reclasifica el historial con las coincidencias guardadas.

        Con `es_noticia` se suman los términos de `noticias` de cada categoría
        y el resumen cuenta en todas. `max_puntos_dependencia` limita lo que
        aporta quien publica (convocatorias y avisos: que la CFE compre
        refacciones no basta para que sea relevante).
        """
        if es_noticia:
            return self._clasificar_noticia(titulo, texto)
        if es_edicto:
            return Clasificacion()
        tn = normalizar(titulo)
        if texto is None:
            fragmentos: list[str] = []
        elif isinstance(texto, str):
            fragmentos = [texto[:MAX_TEXTO] if normalizado else normalizar(texto[:MAX_TEXTO])]
        else:
            fragmentos = [f if normalizado else normalizar(f) for f in texto]
        fragmentos = [f for f in fragmentos if f]

        dep = self.dependencia(dependencia)
        # En avisos y convocatorias el texto nombra a quien publica a cada paso
        # («la Comisión Federal de Electricidad convoca…»): eso no cuenta.
        propios: set[str] = set()
        if max_puntos_dependencia is not None and dependencia:
            propios.add(normalizar(dependencia))
            if dep is not None:
                propios.add(normalizar(dep.sigla))
        if dep is not None and max_puntos_dependencia is not None:
            dep = Dependencia(dep.clave, dep.sigla, dep.categoria,
                              min(dep.puntos, max_puntos_dependencia))
        if dep is None or dep.puntos < self.umbrales["alta"]:
            if any(t.busca([tn]) for t in self.excluir):
                return Clasificacion()

        puntos: dict[str, int] = defaultdict(int)
        fuertes_titulo: set[str] = set()   # categorías con señal de título o dependencia
        motivos: list[str] = []
        coincidencias: list[str] = []
        if dep:
            puntos[dep.categoria] += dep.puntos
            fuertes_titulo.add(dep.categoria)
            motivos.append(f"Dependencia: {dep.sigla}")

        # Título
        en_titulo: dict[str, list[tuple[Termino, str]]] = {}
        for c in self.categorias.values():
            hits = []
            for t in c.terminos + c.solo_titulo:
                m = t.busca([tn])
                if m:
                    hits.append((t, m))
            if hits:
                en_titulo[c.id] = hits
        for c in self.categorias.values():
            if (c.id in en_titulo and c.ceder_a in en_titulo and c.ambiguos
                    and all(t.clave in c.ambiguos for t, _ in en_titulo[c.id])):
                del en_titulo[c.id]
        for cid, hits in en_titulo.items():
            c = self.categorias[cid]
            puntos[cid] += c.peso_titulo
            fuertes_titulo.add(cid)
            nombres = " y ".join(f"«{t.etiqueta(m)}»" for t, m in hits[:2])
            motivos.append(f"Título: {nombres}")

        # Texto
        if fragmentos:
            for c in self.categorias.values():
                if c.cuenta_texto:
                    ya = {id(t) for t, _ in en_titulo.get(c.id, [])}
                    hits = []
                    for t in c.terminos:
                        if id(t) in ya:
                            continue
                        m = t.busca(fragmentos)
                        if m and not any(m == p or m in p for p in propios):
                            hits.append((t, m))
                    if hits:
                        puntos[c.id] += min(len(hits), c.max_texto)
                        nombres = ", ".join(f"«{t.etiqueta(m)}»" for t, m in hits[:3])
                        motivos.append(f"Texto: {nombres}")
                        coincidencias.extend(m for _, m in hits)
                if c.fracciones:
                    hf = []
                    for f in c.fracciones:
                        m = f.busca(fragmentos)
                        if m:
                            hf.append((f, m))
                    if hf:
                        puntos[c.id] += c.puntos_fraccion
                        nombres = ", ".join(f"{f.codigo} ({f.nombre})" for f, _ in hf[:3])
                        motivos.append(f"Fracción arancelaria: {nombres}")
                        coincidencias.extend(m for _, m in hf)

        for cid in list(puntos):
            techo = self.categorias[cid].techo if cid in self.categorias else None
            if techo is not None:
                puntos[cid] = min(puntos[cid], int(techo))
        fuertes = {c: p for c, p in puntos.items() if p > 0}
        if not fuertes:
            return Clasificacion(motivos=motivos)
        categorias = sorted(fuertes, key=lambda c: (-fuertes[c], self.orden.get(c, 99)))
        mejor = max(fuertes.values())
        # +1 si dos categorías llegan a 2 con señales de título o dependencia
        # (el cuerpo solo no basta: un estatuto de Pemex menciona de todo).
        bonus = 1 if sum(1 for c, p in fuertes.items()
                         if p >= 2 and c in fuertes_titulo) >= 2 else 0
        puntaje = mejor + bonus
        return Clasificacion(categorias=categorias, puntaje=puntaje,
                             prioridad=self.prioridad(puntaje), motivos=motivos,
                             coincidencias=sorted(set(coincidencias)))

    def _clasificar_noticia(self, titulo: str, texto: str | list[str] | None) -> Clasificacion:
        """Noticias: todas las fuentes son del sector; las categorías sirven de filtro."""
        tn = normalizar(titulo)
        if isinstance(texto, list):
            xn = " \n ".join(normalizar(t) for t in texto)
        else:
            xn = normalizar((texto or "")[:5000])
        puntos: dict[str, int] = defaultdict(int)
        motivos: list[str] = []
        en_titulo: dict[str, list[tuple[Termino, str]]] = {}
        for c in self.categorias.values():
            hits = [(t, m) for t in c.terminos + c.solo_titulo + c.noticias if (m := t.busca([tn]))]
            if hits:
                en_titulo[c.id] = hits
        for c in self.categorias.values():
            if (c.id in en_titulo and c.ceder_a in en_titulo and c.ambiguos
                    and all(t.clave in c.ambiguos for t, _ in en_titulo[c.id])):
                del en_titulo[c.id]
        for cid, hits in en_titulo.items():
            puntos[cid] += self.categorias[cid].peso_titulo
            motivos.append("Título: " + " y ".join(f"«{t.etiqueta(m)}»" for t, m in hits[:2]))
        if xn:
            for c in self.categorias.values():
                if c.id in en_titulo:
                    continue
                hits = [(t, m) for t in c.terminos + c.noticias if (m := t.busca([xn]))]
                if hits:
                    puntos[c.id] += 1
                    motivos.append("Resumen: " + ", ".join(f"«{t.etiqueta(m)}»" for t, m in hits[:2]))
        if not puntos:
            return Clasificacion()
        categorias = sorted(puntos, key=lambda c: (-puntos[c], self.orden.get(c, 99)))
        puntaje = max(puntos.values())
        return Clasificacion(categorias=categorias, puntaje=puntaje,
                             prioridad=self.prioridad(puntaje), motivos=motivos)

    def prioridad(self, puntaje: int) -> str:
        u = self.umbrales
        if puntaje >= u["alta"]:
            return "alta"
        if puntaje >= u["media"]:
            return "media"
        if puntaje >= u["baja"]:
            return "baja"
        return ""
