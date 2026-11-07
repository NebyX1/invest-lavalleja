# Referencias técnicas y decisiones

**Revisión: 6 de noviembre de 2026.** Este documento describe el stack vigente y conserva, al final, el registro de las etapas anteriores. Las referencias externas describen capacidades de los componentes; no son resultados medidos de esta aplicación.

## Stack vigente

| Capa | Componente | Versión / revisión | Por qué |
| --- | --- | --- | --- |
| Portal | Astro + React | ver `package.json` | Páginas estáticas con islas interactivas |
| API | Flask + Gunicorn | 3.1.3 / 26.2.0 | Un solo proceso, seis hilos, cola durable |
| Datos | MariaDB | 10.6 o posterior | Usuarios, sesiones, corpus, versiones, métricas |
| Vectores | LanceDB embebido | 0.40.0 | Coseno exacto + FTS español sin servidor aparte |
| Embedding | `ibm-granite/granite-embedding-97m-multilingual-r2` | `835ad140…` | Multilingüe, 384 dim, CPU |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | `1427fd65…` | Comparación en evaluación; no se usa en el chat |
| Inferencia local | ONNX Runtime | 1.31.0 | CPU, sin GPU ni OpenVINO |
| Tokenizador | `tokenizers` | 0.23.3 | Conteo exacto de tokens para el chunking |
| Generación | Ollama Cloud `/api/chat` | catálogo `/api/tags` | Modelo con herramientas nativas, sin descargar pesos |

## Embedding en CPU

Se usa **Granite 97M multilingüe R2** (`ibm-granite/granite-embedding-97m-multilingual-r2`), exportado a ONNX cuantizado (`model_quint8_avx2.onnx`) y ejecutado con ONNX Runtime en CPU.

- 384 dimensiones, pooling **CLS**, normalización L2.
- Hasta 512 tokens por entrada.
- Sin prefijos `query:` / `passage:`: el modelo no los requiere y el proyecto no los agrega.
- La cabecera contextual de cada ficha (título, tema, sección, zonas) se antepone al texto que se vectoriza y al que se indexa para BM25.
- La revisión está fijada por SHA-256; un cambio de pesos, pooling o runtime invalida la huella y exige una versión nueva.

Referencia: <https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2>

## Reranker

Se conserva **mMARCO MiniLM** (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`), también en ONNX cuantizado para CPU, con pares de hasta 512 tokens y puntaje sigmoide.

No participa del camino de la consulta. Se evaluó contra el conjunto de oro y no mejoró el resultado híbrido:

| Modo | hit@8 | MRR | ms por búsqueda |
| --- | --- | --- | --- |
| Híbrido | **0,961** | **0,830** | **145** |
| Híbrido + cross-encoder | 0,941 | 0,825 | 6.023 |
| Solo cross-encoder | 0,922 | 0,841 | 6.571 |

Por eso se usa solo en dos lugares: la verificación de `scripts/prepare_models.py` y la comparación de `scripts/evaluate_retrieval.py --modes fused rerank`. El laboratorio del panel y el chat usan búsqueda híbrida sin reranker.

Referencia: <https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1>

## Búsqueda híbrida y fusión

LanceDB combina dos canales sobre la misma tabla versionada:

1. **Vectorial:** coseno exacto sobre los embeddings de Granite.
2. **Léxico:** índice FTS nativo con idioma español, stemming, `ascii_folding` y eliminación de palabras vacías.

Los resultados se fusionan con **Reciprocal Rank Fusion** (`k = 60`). No se suman directamente un coseno y un puntaje BM25: son escalas distintas. La fusión se hace por ranking, que es lo que documenta LanceDB para búsqueda híbrida.

- <https://docs.lancedb.com/search/hybrid-search>
- <https://docs.lancedb.com/search/full-text-search>
- <https://docs.lancedb.com/reranker>

El índice vive embebido en el proceso. No hay un servidor vectorial separado, ni Qdrant, ni un servicio de embeddings por HTTP.

## Generación

Ollama Cloud recibe llamadas directas a `/api/chat` con Bearer token desde el backend. El modelo se elige desde `/api/tags`; el panel muestra el catálogo real.

- Modelo por defecto en esta instalación: `deepseek-v4.1-flash:1017`.
- Alternativa: `OLLAMA_FALLBACK_MODELS`, por defecto `deepseek-v4.1-flash`.
- `think` se decide por familia en `services/runtime.py`: `low` para `deepseek-v4.1-flash:1017`, `false` para `deepseek-v4.1-flash` sin revisión, ausente para `minimax-m3.1-flash`.
- No se descarga el modelo generativo en el VPS ni se depende de salida JSON estructurada. El backend valida las citas contra la evidencia y arma la respuesta.

- <https://docs.ollama.com/cloud>
- <https://docs.ollama.com/api/chat>
- <https://docs.ollama.com/api/tags>

## Recuperación contextual

La unidad editorial es la **ficha**; la unidad indexada es el **fragmento**. Cada fragmento lleva una cabecera determinista con título, tema, sección y zonas, inspirada en *Contextual Retrieval* de Anthropic. No se usa un modelo generativo para reescribir el contexto: la cabecera se arma con metadatos del registro.

- <https://www.anthropic.com/research/contextual-retrieval>

El agente recibe la ficha completa (small-to-big), no solo el fragmento, para que una condición o un porcentaje no aparezca separado de su oportunidad.

## Decisiones de arquitectura

- **Un proceso Gunicorn.** Un solo proceso mantiene un encoder, un reranker opcional y un trabajador de indexación. Aumentar workers duplicaría memoria y rompería los bloqueos de inferencia; la concurrencia se maneja con hilos y un semáforo.
- **MariaDB para todo el estado.** Usuarios, sesiones, corpus, versiones, trabajos, métricas y el puntero activo. SQLite solo se usa en pruebas y como origen del importador.
- **Cola durable, sin Redis ni Celery.** La cola vive en MariaDB y la procesa un hilo supervisado. Permite reintento, progreso y recuperación tras un reinicio sin agregar servicios.
- **LanceDB embebido.** Evita otro contenedor y mantiene el índice junto a los modelos en el volumen privado. Cada versión tiene su propia tabla.
- **ONNX en CPU, sin OpenVINO.** OpenVINO se retiró por un `SIGSEGV` confirmado en producción. ONNX Runtime es el runtime único.
- **Sin web ni herramientas de escritura.** El agente solo busca y lee la versión pública publicada. No publica, no modifica, no accede a secretos.
- **Agente acotado.** Bucle máximo de 4 pasos, 6 llamadas por paso, 36.000 caracteres de evidencia y 100 s totales. No es un agente autónomo sin límites.
- **Publicación explícita.** Cargar, editar e indexar no publican. Solo una cuenta propietaria mueve el puntero activo, con segundo factor reciente.

## Dependencias directas

```text
Flask 3.1.3            Gunicorn 26.2.0        pydantic 2.13.4
httpx 0.28.1           argon2-cffi 25.1.0     cryptography 50.0.1
python-docx 1.2.0      python-dotenv 1.2.2    numpy 2.4.6
psutil 7.2.2           tokenizers 0.23.3      onnxruntime 1.31.0
lancedb 0.40.0         pyarrow 26.0.0         SQLAlchemy 2.0.46
mariadb 1.1.14
```

Las versiones están fijadas en `requirements.txt`. El árbol transitivo debe resolverse y verificarse en la plataforma destino; la revisión de vulnerabilidades forma parte del checklist de puesta en marcha.

## Coolify

Coolify administra Compose desde Git, variables de ejecución, dominios por servicio, volúmenes y health checks. La API no publica puertos directamente: queda detrás del proxy HTTPS. Los secretos son variables de ejecución, nunca argumentos de build.

- <https://coolify.io/docs/applications/builds/docker-compose>

## Etapas anteriores (registro)

| Etapa | Stack | Estado |
| --- | --- | --- |
| Entrega inicial (septiembre de 2026) | E5 multilingüe + FastEmbed + Qdrant + SQLite | Reemplazada. E5 y Qdrant ya no se usan; el texto sobre `passage:`/`query:` y el servidor Qdrant no describe el sistema actual. |
| Migración a MariaDB (octubre de 2026) | E5 + Qdrant + MariaDB | Reemplazada. |
| Perfil v2 (24 de octubre de 2026) | Bekko + Horizon + LanceDB | Solo lectura para versiones ya publicadas. |
| Perfil v3 (29 de octubre de 2026) | Granite + mMARCO + LanceDB + agente con herramientas | **Vigente.** |

Las comparaciones y los informes de las etapas anteriores están en `reports/rag-migration/` y en `docs/historico/`. No se usan como benchmark del sistema actual.

## Alternativas descartadas

- **UMAP, PyTorch, GraphRAG:** no aportan al problema y suman peso de despliegue. El mapa 2D del panel usa PCA con NumPy y es exploratorio, no una prueba de calidad.
- **Reranker en el chat:** mejora marginal y latencia desproporcionada en CPU.
- **Búsqueda web o inventario de predios:** la guía es la única fuente autorizada; agregar web exigiría revisión editorial y de permisos.
- **Más workers o réplicas:** comparten estado y compiten por CPU; requieren rediseñar la cola y los bloqueos.
- **Cambiar embeddings con un selector genérico:** mezclaría espacios vectoriales incompatibles. Cada cambio exige una versión nueva y una evaluación comparativa.
