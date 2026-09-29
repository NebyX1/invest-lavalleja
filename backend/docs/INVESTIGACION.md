# Referencias técnicas y decisiones

Revisión: 28 de septiembre de 2026. Las referencias describen capacidades de los componentes, no resultados medidos de esta aplicación.

## Patrón institucional revisado

Repositorio `IntendenciaDeLavalleja/buzon-ciudadano-backend`, commit observado `3198d34ed3c15cee47caa33ef73e94dbfd16b6ed`: README, árbol, modelo de usuario, rutas de administración y factoría Flask. El ejemplo usa contraseña Argon2 y segundo factor por correo, administración por roles, auditoría y CSRF. Esta implementación conserva el patrón funcional, añade TOTP y reduce servicios persistentes para el alcance documental. No copia credenciales, historias de usuarios, adjuntos ni el código del Buzón.

https://github.com/IntendenciaDeLavalleja/buzon-ciudadano-backend

## Embeddings en CPU

Se mantiene `intfloat/multilingual-e5-small`. El modelo documenta 384 dimensiones, entradas de hasta 512 tokens y prefijos `query: ` / `passage: ` también en otros idiomas. Se implementa pooling medio y normalización, y se valida el presupuesto incluyendo metadatos y tokens especiales.

https://huggingface.co/intfloat/multilingual-e5-small

FastEmbed utiliza ONNX Runtime y admite modelos personalizados con configuración de pooling, normalización y fuente. No se afirma que sea universalmente el runtime más rápido ni que cualquier exportación sea automáticamente INT8. La entrega utiliza `onnx/model.onnx`, no una cuantización inventada.

https://github.com/qdrant/fastembed
https://github.com/qdrant/fastembed/blob/main/fastembed/text/custom_text_embedding.py
https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py
https://pypi.org/project/fastembed/

BM25 se configura en español. Su implementación FastEmbed requiere el modificador IDF en Qdrant; se incluye en la colección. No se fusionan directamente valores coseno y BM25 como si fueran escalas equivalentes: se usa RRF.

https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py
https://qdrant.tech/documentation/search/hybrid-queries/
https://api.qdrant.tech/api-reference/search/query-points

## Servicios y versiones

Se fija Qdrant Server `v1.19.1`, identificado como release estable en la revisión; no `latest` ni Edge beta. El contenedor no se ejecutó aquí. Se emplea su API REST con HTTPX y conexión reutilizable, evitando otro cliente de inferencia.

https://github.com/qdrant/qdrant/releases

Dependencias directas elegidas: Flask `3.1.3`, Gunicorn `26.2.0`, FastEmbed `0.8.1`, además de las versiones incluidas en `requirements.txt`. Se verificó la publicación de estos paquetes; la combinación completa y sus dependencias transitivas sigue pendiente de instalación y pruebas en la imagen final.

https://pypi.org/project/Flask/
https://pypi.org/project/gunicorn/
https://flask.palletsprojects.com/en/stable/deploying/gunicorn/

Ollama Cloud recibe llamadas directas a `/api/chat` con Bearer token desde el backend. El modelo se elige a partir de `/api/tags`. No se necesita descargar Ollama ni el modelo generativo en el VPS. No se depende de una garantía de salida estructurada JSON: el backend construye la respuesta y resuelve las citas conocidas.

https://docs.ollama.com/cloud
https://docs.ollama.com/api/chat
https://docs.ollama.com/api/tags

Coolify administra Compose desde Git, variables referenciadas, dominios por servicio, volúmenes y health checks declarados. Se evita publicar Qdrant con `ports:`. Las variables sensibles son de ejecución y no argumentos de build.

https://coolify.io/docs/applications/builds/docker-compose

## Razones de simplificación

Jinja y JavaScript local mantienen la administración en el backend Flask, sin compilar otro SPA. SQLite WAL evita agregar MariaDB para el volumen inicial. Una cola persistente de un trabajador permite reintento, recuperación y progreso sin Redis/Celery. El compromiso es una sola instancia, competencia temporal por CPU y necesidad de medir la latencia durante cargas.

PCA con NumPy se ejecuta después de indexar, no por cada pregunta. No se añade UMAP, PyTorch, GraphRAG, agentes autónomos, reranker o navegación web durante las conversaciones. Las mejoras de calidad deben justificarse con las preguntas reales de esta guía, no solo con popularidad de una biblioteca.
