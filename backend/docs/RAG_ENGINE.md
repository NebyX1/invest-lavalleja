# Arquitectura RAG y del agente

Estado verificado el 29/10/2026. Reemplaza al diseño anterior (planificador determinista + catálogo de rubros + contrato JSON), archivado en [`historico/`](historico/RAG_ENGINE_planificador_determinista.md).

## Por qué se rehízo

El diseño anterior fallaba por política, no por recuperación:

- Un **planificador de reglas** (`planner.py` + `catalog.py` + `activities.py`, ~100 KB de palabras clave) decidía qué se buscaba y cuándo abstenerse. Todo rubro que no estuviera en el catálogo ("boliche", "gimnasio", "restaurante") terminaba en una negativa enlatada.
- Un **tope artificial de 8.000 tokens por petición** obligaba a recortar evidencia y a una segunda lectura del modelo.
- El **cross-encoder** agregaba ~5 s por búsqueda en CPU, sin mejorar los aciertos (ver mediciones abajo).
- Un **timeout de 80 s** y cualquier error HTTP, respuesta vacía o recorte de contexto se mostraban igual: "El proveedor de respuestas no está disponible".

La referencia revisada (kotaemon, RAGFlow, Haystack/LlamaIndex agénticos, Contextual Retrieval de Anthropic, documentación de LanceDB) coincide en lo mismo: recuperación híbrida por defecto, un solo agente con herramientas y bucle acotado en vez de una cascada de reglas, fichas con cabecera contextual y citas validadas contra lo recuperado.

## Flujo de una consulta

```text
pregunta ──► seguridad determinista (safety.py: acusaciones, insultos, delitos) ──► respuesta fija, sin modelo
   │
   ├─ cortesía pura ("hola, gracias") ─────────────────────────────────────────► modelo sin herramientas
   │
   ▼
búsqueda híbrida inicial (retrieval.py)      denso Granite + BM25 español + RRF, ≈60 ms
   │                                         seguimiento corto ("¿y en Varela?") = pregunta anterior + actual
   ▼
modelo con herramientas (agent.py, hasta 4 pasos, plazo total 100 s)
   ├─ buscar_en_la_guia(consulta, zonas?, tipo?)   otra búsqueda, filtros blandos
   ├─ ver_ficha(n | id)                            lee una ficha completa
   └─ respuesta final con citas [n]
   ▼
validación: [n] inexistentes se descartan, se renumera 1..n por orden de aparición,
códigos internos (Z3, O05) se traducen a nombres, fuentes completas por cita
   ▼
JSON del chat (answer, citations, status, notice…) — mismo contrato que usa la isla React
```

Si el proveedor falla tras reintentos y modelo alternativo y ya hay evidencia, se devuelve un estado `degraded` con las tres fichas más relacionadas; sin evidencia, un error `ollama_unavailable` claro.

## La base de conocimiento

- **Formato de entrada:** `gianna.corpus.v1` (JSON). Cada registro: `id`, `title`, `section`, `topic`, `audience` (`public`/`internal`), `evidence_type`, `text`, `conditions`, `source_refs`, `zones`, `opportunity_id`, fechas y trazabilidad al DOCX original. Los registros internos nunca entran al índice público.
- **Fichas autosuficientes:** `better-rag/tools/restructure.py` fusiona los registros contiguos `sNN-MM-xx` en una ficha con su título padre (332 → 257 registros públicos, mediana de 1.088 caracteres). Evita que "Ocupación supuesta: 70 %" o "2 · Contrastar mercado" se recuperen sin su contexto. Une fuentes, zonas, bloques originales y fechas; no reescribe el texto ni usa un modelo.
- **Cabecera contextual** (`chunking.py`, versión `cards-context-v5`): título, tema, sección y zonas se anteponen al texto del embedding **y** del BM25. Los chunks se cortan con el tokenizador real del encoder (≤ 420 tokens; 262 chunks para 257 fichas).
- **Small-to-big:** se recupera por chunk, pero el agente recibe la ficha completa con sus condiciones, nivel de evidencia, fecha de corte y período. Las condiciones repetidas entre fichas se muestran una sola vez por respuesta.
- **Índice:** MariaDB guarda registros, versiones, chunks y caché de embeddings; LanceDB guarda vectores (cosine exacto) y el índice FTS español (stemming, `ascii_folding`, sin palabras vacías). Las versiones son inmutables y la publicación es un puntero transaccional.
- **Modelos:** Granite 97M multilingüe R2 (ONNX cuantizado, CLS/L2, 384 dim, CPU) y mMARCO MiniLM, fijados por SHA-256 en `services/neural.py`. Cambiarlos exige una versión nueva.

## Mediciones (51 preguntas, `evals/retrieval_gold.json`, sin llamar al modelo)

| Modo | hit@1 | hit@3 | hit@5 | hit@8 | MRR | ms por búsqueda |
| --- | --- | --- | --- | --- | --- | --- |
| **Híbrido (predeterminado)** | 0,745 | 0,902 | 0,922 | **0,961** | 0,830 | **60** |
| Híbrido + cross-encoder (fusión) | 0,725 | 0,922 | 0,941 | 0,941 | 0,825 | 4.797 |
| Solo cross-encoder | 0,784 | 0,882 | 0,902 | 0,922 | 0,841 | 4.846 |

El cross-encoder no aporta en este corpus y multiplica la latencia por 80, por eso quedó fuera del camino de la consulta (sigue en `Retriever.search(mode='fused')` y se mide con `scripts/evaluate_retrieval.py --modes`). Los fallos restantes del híbrido (por ejemplo, "¿con quién hablo para permisos?" ↔ ficha de contactos) los cubre el agente reformulando con otra búsqueda.

Estas cifras salen de un conjunto conocido y revisado por quien lo escribió: miden cobertura, no exactitud factual.

## Piezas

| Módulo | Responsabilidad |
| --- | --- |
| `services/agent.py` | Bucle del agente, evidencia numerada, validación de citas, degradación |
| `services/prompts.py` | Reglas del agente y definición de herramientas (el panel solo edita el tono) |
| `services/retrieval.py` | Búsqueda híbrida, filtros blandos de zona/tipo, ficha completa, mapa de la guía |
| `services/runtime.py` | Cliente de Ollama Cloud: reintentos, modelo alternativo, plazos, `think` por modelo |
| `services/safety.py` | Compuerta determinista que nunca delega en el modelo |
| `services/rag.py` | Orquestación, citas con fuentes, métricas (sin guardar la pregunta en claro) |
| `domain.py` | Zonas Z1–Z7, oportunidades O01–O16, etiquetas de evidencia |
| `services/vector_store.py`, `neural.py`, `jobs.py`, `knowledge.py` | Índice, modelos, cola de indexación, versiones (sin cambios de contrato) |

## Proveedor y contexto

- El modelo se elige en Ajustes (`OLLAMA_MODEL` solo inicia instalaciones nuevas). Por defecto `deepseek-v4.1-flash:1017` con `think: low`; si falla tres veces, se intenta `OLLAMA_FALLBACK_MODELS` (por defecto `deepseek-v4.1-flash`). Los nombres válidos salen de `/api/tags`.
- Sin tope de 8K: el corpus público completo son unos 65.000 tokens; cada respuesta usa entre 4.000 y 15.000 (tope de evidencia por respuesta: 36.000 caracteres).
- El historial (cifrado por sesión) conserva los últimos ~14.000 caracteres; las marcas `[n]` se quitan porque solo valen dentro de su respuesta.

## Límites conocidos

- La respuesta la redacta un modelo: puede equivocarse aunque cite. `scripts/evaluate_answers.py` marca cifras que no están en la evidencia y códigos internos, pero la lectura humana sigue siendo necesaria.
- La guía es la única fuente. No hay web, inventario de predios, precios ni contactos fuera de lo que figura en ella; el agente debe decirlo.
- Las hipótesis y los ejemplos numéricos de la guía se presentan como tales, no como datos observados.
- Las versiones publicadas con el motor Bekko/Horizon siguen consultables, con su representación original.
