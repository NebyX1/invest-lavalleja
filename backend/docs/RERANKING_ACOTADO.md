# Reranking durante la respuesta

El chat y el laboratorio pueden reordenar hasta seis candidatos de la búsqueda
híbrida usando el mMARCO/Horizon del perfil de la versión consultada. Se conserva
el conjunto restante, las condiciones, las fuentes y los filtros de audiencia.
En el chat, la revisión semántica de seguridad ocurre antes de recuperar evidencia y no se
sustituye por el reranker.

## Presupuesto y concurrencia

`rerank_mode=bounded` habilita el camino de servicio; `hybrid` lo desactiva.
El presupuesto predeterminado es 1.500 ms, con un máximo de 1.500 ms. Se crea una
única instancia `RerankBudget` por respuesta y se comparte con las herramientas.
Su ventana empieza en la primera búsqueda, antes del encoder, para que una espera
causada por otra inferencia no dé derecho a otros 1.500 ms de reordenamiento.
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

## Revisión de recuperación del 08/11/2026

La política de servicio `bounded-window-v4` mantiene Granite/mMARCO, seis pares,
160 tokens, un intento por respuesta, cancelación, caché y fallback. La ventana
se amplió porque la inferencia real medía aproximadamente 0,7–0,9 s: 400 ms
cancelaban el reordenamiento. El antiguo valor predeterminado exacto de 400 se
normaliza a 1.500 al leer ajustes; los presupuestos menores personalizados se
conservan y no se escribe SQL durante esa lectura. El panel admite el mismo máximo.

Los perfiles territoriales y sectoriales pueden declarar `catalog_entry` con
nombres y alias. Se añaden hasta tres coincidencias de palabra completa al
reservorio de candidatos, con aislamiento por versión pública. No hay respuestas
por palabras clave ni un listado de temas inexistentes: un lugar nuevo se declara
en el corpus. La búsqueda densa y BM25 siguen recuperando las consultas sin alias.

En la ventana de seis se fusionan, con RRF de igual peso, el orden híbrido y el
orden neural; la cola y la preferencia de zona se conservan. El reordenamiento
neural puro empeoró el primer resultado de varias preguntas de este estudio.
La política de fusión forma parte de la huella de caché de servicio; no cambia
el espacio vectorial ni las versiones publicadas. Un perfil de catálogo es un
candidato, no un ganador impuesto.

Las medidas del estudio local y de Docker están en `reports/VALIDACION.md`.
Recuperar una ficha esperada no demuestra corrección, pertinencia o tono de la
respuesta generada. No se acredita latencia del servidor de Coolify con estas pruebas.
