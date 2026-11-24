# mxenergy — notas para trabajar en este repo

- Interfaz, mensajes, logs, reglas y documentación en **español** (México). Código y nombres en español.
- **Sin IA ni APIs de pago**: el filtro es `config/reglas.yaml`. No agregar llamadas a LLM.
- Toda la lógica de relevancia vive en `config/reglas.yaml`; el código solo la interpreta
  (`mxenergy/reglas.py`). Para un caso nuevo, primero un término o una exclusión en el YAML.
- La app (`app.py`) solo lee la rama `datos`; el recolector (`scripts/recolectar.py`) solo escribe ahí.
  `mxenergy/vista.py`, `tiempo.py`, `texto.py` y `reglas.py` no deben importar nada pesado.
- Pruebas sin red: `python -m pytest` (fixtures en `tests/fixtures`, red simulada en `tests/conftest.py`).
  Toda función nueva de una fuente lleva su prueba con un fixture real recortado.
- La recolección real corre en GitHub Actions (el entorno de Claude no llega a los sitios). Para validar
  un cambio de fuentes: push a `main` → corrida automática → revisar `logs/ultima.log` de la rama `datos`.
- Contexto del proyecto (Market Intelligence): documento `05_App_Digest_mxenergy.md` del proyecto.
