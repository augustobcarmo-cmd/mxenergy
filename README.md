# Síntesis diaria del sector energético · México

App: **https://sintesis-energia-mx.streamlit.app**

Lo que publican el **Diario Oficial de la Federación** y la prensa especializada del sector energético,
filtrado para el desarrollo de proyectos eléctricos y de almacenamiento en México. Sin IA y sin costo
de API: el filtro son reglas legibles en [`config/reglas.yaml`](config/reglas.yaml).

## Qué trae cada edición

Una edición por día hábil. La del martes cubre el lunes; la del viernes, el jueves; **la del lunes, de
viernes a domingo**. La edición en curso se va llenando a lo largo del día.

- **📜 DOF** — todas las publicaciones del día (matutina, vespertina y extraordinaria, avisos incluidos),
  con las relevantes arriba, por prioridad, y el motivo de cada una («Dependencia: CNE», «Título:
  almacenamiento de energía», «Fracción arancelaria: 8541.43 módulos fotovoltaicos»). Las demás quedan en
  «Todas las publicaciones del DOF».
- **⚡ Energía Estratégica** — la fuente principal: su sección México y los listados de portada,
  almacenamiento, fotovoltaica y eólica, separados en México y región.
- **📰 Otras fuentes** — Global Energy, Mexico Business News, PV Magazine México, Energía a Debate,
  Energy News MX y Energy21. Lo que solo es de hidrocarburos va aparte.

Además: búsqueda en todo el historial (con exportación a Excel), estado de cada fuente y registro de
corridas.

## Cómo funciona

```
GitHub Action «Recolectar»  ──►  rama datos (items.parquet, estado, logs)  ──►  app de Streamlit
 5:17 · 9:17 · 13:17 · 17:17 · 21:17 (CDMX)          un solo commit                lee la rama
```

| Pieza | Dónde |
|---|---|
| Recolector | `mxenergy/recolector.py`, fuentes en `mxenergy/fuentes/` |
| DOF | API del SIDOF (`sidof.segob.gob.mx`); si falla un día, el índice clásico de dof.gob.mx |
| Energía Estratégica | listados con Chromium sin ventana (Playwright); cada nota se lee del HTML del servidor |
| Reglas del filtro | `config/reglas.yaml` (motor en `mxenergy/reglas.py`) |
| Fuentes | `config/fuentes.yaml` |
| App | `app.py` (+ `mxenergy/vista.py`) |
| Datos | rama [`datos`](../../tree/datos): `items.parquet`, `estado.json`, `ejecuciones.jsonl`, `logs/` |

**Nada se pierde en silencio.** Cada corrida deja su log completo en `logs/` de la rama `datos` y una línea
en `ejecuciones.jsonl`; la pestaña *Estado* de la app muestra la salud de cada fuente y qué días del DOF
están completos. Si el DOF falla dos corridas seguidas (o Energía Estratégica tres), la corrida sale en rojo
y GitHub manda un correo. El recolector completa solo los días del DOF que falten desde
`inicio_historial`.

## Cómo mejorarla

- **Algo importante no aparece o sobra algo** → editar [`config/reglas.yaml`](config/reglas.yaml) (términos
  por categoría, dependencias, exclusiones). Al guardar en `main`, una corrida reclasifica todo el historial.
- **Agregar o apagar una fuente** → [`config/fuentes.yaml`](config/fuentes.yaml).
- **Volver a bajar el DOF de unos días** (por ejemplo, tras agregar términos que solo aparecen en el
  cuerpo) → *Actions → Recolectar DOF y noticias → Run workflow*, con «reprocesar_dof_dias».
- **Pruebas** (sin red): `pip install -r requirements-dev.txt && python -m pytest`.

## En local

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/recolectar.py --datos datos_local          # una corrida completa
MXENERGY_DATOS=datos_local streamlit run app.py            # la app con esos datos
```

`scripts/migrar_sqlite.py` trajo las noticias de agosto a noviembre de 2026 de la versión local anterior
(con IA); el DOF se completó desde el SIDOF.
