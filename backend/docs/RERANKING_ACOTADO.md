# Reranking durante la respuesta

El chat y el laboratorio pueden reordenar hasta seis candidatos de la búsqueda
híbrida usando el mMARCO/Horizon del perfil de la versión consultada. Se conserva
el conjunto restante, las condiciones, las fuentes y los filtros de audiencia.
En el chat, la revisión semántica de seguridad ocurre antes de recuperar evidencia y no se
sustituye por el reranker.

## Presupuesto y concurrencia

`rerank_mode=bounded` habilita el camino de servicio; `hybrid` lo desactiva.
El presupuesto predeterminado es 400 ms, con un máximo de 400 ms. Se crea una
única instancia `RerankBudget` por respuesta y se comparte con las herramientas.
Su ventana empieza en la primera búsqueda, antes del encoder, para que una espera
causada por otra inferencia no dé derecho a otros 400 ms de reordenamiento.
Se permite como máximo un intento neural por respuesta. Las búsquedas posteriores
pueden reutilizar la caché; no abren nuevas ventanas de inferencia.

La admisión del reranker y de la caché no espera por locks. La inferencia usa
pares de hasta 160 tokens, batches de hasta cuatro y una consulta de hasta 64
tokens. Si una consulta es larga se preservan su cabeza de 24 tokens y su cola
de 40, incluyendo seguimientos recientes. Los tokenizadores se reconfiguran únicamente bajo el lock de inferencia y se
restauran antes de liberarlo, incluso ante errores. No se duplican los grandes
vocabularios del modelo; la comparación offline conserva su configuración.

ONNX recibe el tiempo restante y su `RunOptions.terminate` cancela la ejecución
al vencimiento. Es una cancelación cooperativa: puede haber sobrepaso del reloj
por planificación o por la operación activa, que debe medirse bajo carga. Los
resultados tardíos se descartan completos; no quedan inferencias huérfanas ni se
aceptan puntuaciones parciales. El encoder comparte el lock de CPU: la medición
concurrente incluye esa espera y no sólo el tiempo registrado por el reranker.

## Caché y fallback

La caché vive en el proceso, tiene 256 entradas y TTL de 300 segundos. Su clave
es un HMAC con secreto de arranque e incluye versión, fingerprint, consulta,
IDs ordenados y huellas de los pasajes y de los parámetros de servicio. Sólo
se conservan puntuaciones numéricas: no preguntas, documentos o respuestas.
Un cambio de versión, perfil o candidatos no reutiliza resultados anteriores.

Ante error, saturación, falta de disponibilidad, presupuesto agotado o scores
inválidos se conserva exactamente el resultado híbrido. No se descartan fichas
por un umbral de confianza no calibrado. El ajuste histórico `rerank_candidates`
admite su antiguo JSON; se normaliza en memoria al máximo de seis, sin escribir
ni migrar ajustes durante la lectura.

La traza de cada búsqueda incluye estado, motivo controlado, tiempo, intentos,
presupuesto y orden antes/después. Los eventos `retrieval.rerank_completed` no
incluyen preguntas ni fragmentos. El laboratorio muestra la decisión real,
incluidos los fallbacks y los aciertos de caché.

## Compatibilidad y validación

No cambian pesos, revisiones, embeddings, representación documental ni huellas
publicadas. No se reindexa ni se altera el puntero activo. La preparación y
verificación del perfil completo en el worker conserva su contrato anterior;
esta entrega no vuelve opcional la existencia de los artefactos en el arranque.
Los modos offline explícitos `fused`/`rerank` se mantienen para comparaciones,
separados del camino acotado.

`scripts.benchmark_reranker` requiere `--run` y rutas explícitas. No lee `.env`,
no llama al generador y sólo construye un índice temporal de prueba. Compara
calidad de recuperación, caché, ráfagas de tres concurrentes y controles de
error/timeout/ocupación con los modelos reales. El gold y un conjunto adicional
predeclarado se evalúan por separado; no equivalen a una evaluación factual de
las respuestas del modelo generativo ni de la instalación productiva.

Resultados y límites reales: [Validación](../reports/VALIDACION.md).
