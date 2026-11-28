# Rama `datos`

La escribe la GitHub Action «Recolectar DOF y noticias» en cada corrida (un solo
commit, sin historial). **No editar a mano**: la siguiente corrida la reemplaza.

| Archivo | Contenido |
|---|---|
| `items.parquet` | Todas las publicaciones (DOF y noticias) con su clasificación |
| `meta.json` | Última actualización y totales (lo lee la app) |
| `estado.json` | Salud de cada fuente y cobertura del DOF por día |
| `cache.json` | Fechas ya leídas de Energía Estratégica y Mexico Business News |
| `ejecuciones.jsonl` | Una línea por corrida (las últimas 1,000) |
| `logs/` | Log completo de las últimas 40 corridas (`ultima.log` = la más reciente) |
