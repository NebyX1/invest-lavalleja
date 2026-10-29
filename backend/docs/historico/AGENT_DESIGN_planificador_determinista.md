# Diseño del agente conversacional

## Por qué se reescribió

La captura del 29/10/2026 mostró dos fallos que no son de recuperación sino de
política de respuesta:

1. A "Quiero invertir en abrir un boliche, ¿qué info tenés?" el agente contestó
   una negativa enlatada y no ofreció el contexto adyacente que sí existe
   (perfiles de zona, requisitos de suelo, Bomberos, ambiente).
2. A "¿No debiste decirme qué zonas hay...?" repitió **palabra por palabra** la
   misma negativa. No reconoció la corrección ni respondió la pregunta literal.

Eso viola el patrón básico de un RAG conversacional: el sistema debe distinguir
"no tengo el dato exacto" de "no tengo nada útil", y debe reparar el turno
cuando la persona corrige.

## Patrones tomados de sistemas que funcionan

| Fuente | Patrón | Aplicación local |
| --- | --- | --- |
| [Coveo Labs, *Most Conversational RAG Systems Work — Until They Don't*](https://www.coveo.com/blog/conversational-rag/) | Taxonomía de consultas: simple, multi-query, compuesta, dependiente, multi-hop, comparativa, enumerativa. Un solo agente con bucle de búsqueda múltiple y **verificación de completitud** supera a más agentes. | `planner.py` clasifica intención (`facts`, `requirements`, `places`, `zone_options`, `compare`, `availability`); `retrieve_for_plan` hace hasta 3 búsquedas y conserva anclas; `answer.py` verifica el contrato y la longitud. |
| Coveo | Planner/Executor: el planificador no responde; define criterios de aceptación. | El plan determinista selecciona actividad, zonas, facets y anclas. El modelo solo redacta desde la evidencia. |
| [Databricks, *End-to-End RAG Workflow*](https://www.databricks.com/blog/rag-workflow) | Híbrido BM25 + denso, fusión RRF y reranking cross-encoder sobre un conjunto pequeño. | LanceDB híbrido + mMARCO; anclas de catálogo primero, luego reranking. |
| [arXiv 2605.01664](https://arxiv.org/html/2605.01664v1) | Grounding por afirmación, no solo citas válidas; el prompt conservador reduce afirmaciones no respaldadas. | `answer.py` exige `evidence_ids`; `evidence_guard.py` retira párrafos con entidades no presentes en la evidencia citada. |
| [Medium, *How to Handle Follow-up Questions in RAG-based Chats*](https://medium.com/@mne/how-to-handle-follow-up-questions-in-rag-based-chats-2d8032da207b) | Reformular la consulta con el historial antes de recuperar. | Estado de proyecto (`activity_id`, `zones`, `opportunities`, `intent`) y `standalone_question`; no se usa la prosa del asistente como evidencia. |

## Reglas de respuesta

- **Dato exacto**: una oración, con cita.
- **Dato parcial**: se responde con lo documentado y se nombra el límite. Ejemplo:
  no hay ficha de ocio nocturno, pero sí perfiles de zona y requisitos de
  suelo/Bomberos/ambiente.
- **Sin dato exacto y sin contexto adyacente**: abstención breve, sin citas.
- **Disponibilidad de inmuebles**: nunca se inventa una cartera. Se dice que no
  existe listado, precios ni superficies.
- **Corrección del usuario**: se reconoce en una frase y se responde la pregunta
  literal. Nunca se repite el texto anterior.
- **Zonas**: se nombran las siete zonas de trabajo y se aclara que son una
  segmentación funcional, no una zonificación legal ni una medición de demanda.
- **Comparaciones**: diferencias documentadas, sin ganador.
- **Seguridad**: alegaciones, insultos y delitos tienen rutas deterministas
  locales; no llegan al modelo.

## Flujo

```text
pregunta
  -> route_question (conversación / fuera de alcance / seguridad / conocimiento)
  -> plan_question (actividad, zonas, intención, facets, búsquedas, repair)
  -> retrieve_for_plan (anclas de catálogo + híbrido + reranker + presupuesto)
  -> generate (JSON: answer, sufficient, evidence_ids, missing)
  -> finalize (voz, códigos, duplicados, longitud)
  -> si el modelo se abstiene pero hay contexto adyacente: partial_answer
  -> citations desde los registros usados
```

## Pruebas de regresión

- `tests/test_dialogue_contract.py`: taxonomía, anclas, `zone_options`, repair,
  respuesta parcial y deduplicación de zonas.
- `tests/test_jobs_and_rag.py`: conversación de la captura, seguimiento
  "¿Y en Minas?", requisitos, oportunidades, disponibilidad, población local.
- `scripts/evaluate_public_chat.py --scenario locations`: espera respuesta
  parcial con zonas, sin inventar inmuebles y sin repetición.
- `scripts/evaluate_candidate_stack.py`: 36/36 grupos de fuentes sobre el corpus
  consolidado.

## Límites

La respuesta parcial sigue dependiendo de que la base tenga contexto adyacente.
No se afirma demanda, disponibilidad ni viabilidad. Aprobar grupos de registros
no certifica verdad factual ni vigencia. La evaluación con proveedor es una
batería conocida, no un holdout ciego.
