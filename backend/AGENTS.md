# Instrucciones para mantenimiento

- Mantener Python/Flask, Gunicorn de un proceso, SQLite WAL, FastEmbed multilingual-E5-small CPU, Qdrant y Ollama Cloud. No sustituir el stack por FastAPI, GPU, PyTorch, Granite, LLM local o agentes sin aprobación explícita.
- El token se obtiene de `.env`/entorno y nunca llega al navegador, un prompt, Git, screenshots o logs. No abrir ni copiar `.env` de proyectos de referencia.
- No convertir un borrador o el anexo interno en fuente pública sin revisión y publicación explícitas. Mantener snapshots, huellas y filtros de audiencia en servidor.
- Cambiar modelo, exportación, pooling o normalización exige nueva huella y reindexación. Los tokens del chunk se cuentan con el tokenizador real. No mezclar vectores por compartir dimensiones.
- Las citas válidas estructuralmente no garantizan afirmaciones correctas. No etiquetar pruebas de contrato con mocks como benchmarks E5/Qdrant ni como evaluación factual.
- No eliminar CSP, CSRF, anti-replay, roles, rate limits o validación de hosts para arreglar un test. Agregar una prueba de regresión al corregir.
- Ejecutar `pytest`, revisión HTTP Flask, Docker/servicios reales y checklist antes de declarar producción. Actualizar `reports/VALIDACION.md` con resultados reales, incluidas limitaciones.
- No realizar push, publicar secretos, desplegar o llamar servicios de pago sin autorización del usuario. Esta entrega no se ha desplegado ni modificado repositorios remotos.
