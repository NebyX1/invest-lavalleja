# Diseño del agente conversacional

## Qué hace

Gianna orienta a inversores y emprendedores usando **solo** la guía del portal. Informa, compara zonas y oportunidades explicando el criterio con la evidencia y señala qué falta validar. No promete rentabilidad ni aprobaciones, no da asesoramiento legal, tributario o financiero individual, no declara una opción como "la mejor" en términos absolutos y no inventa cifras, contactos, beneficios fiscales ni disponibilidad de predios.

## Política de respuesta

| Situación | Qué hace |
| --- | --- |
| La guía responde | Respuesta directa con citas `[n]` pegadas a cada afirmación concreta |
| Dato en estado de hipótesis o ejemplo | Lo presenta como "la guía propone / es una hipótesis a validar / ejemplo con supuestos" |
| La guía **no** cubre el rubro (boliche, gimnasio, restaurante) | Lo dice en una frase y aporta lo documentado que sí aplica: zonas, condiciones del territorio, trámites y organismos, y qué validar. Nunca lo presenta como análisis específico del rubro |
| Pregunta abierta ("¿qué puedo hacer con mi campo?") | Revisa el mapa de la guía y busca por varios rubros antes de responder; no afirma que "la guía no trata X" sin haberlo mirado |
| Pide una recomendación | Indica qué zonas o caminos encajan con lo que cuenta y por qué (criterios documentados); no corona un ganador |
| Falta un dato clave | Responde lo posible y cierra con **una** pregunta breve |
| Seguimiento o corrección | Interpreta en el contexto de la conversación; la corrección se acepta y se ajusta sin repetir el texto anterior |
| Saludo / gracias / fuera de tema | Una o dos frases, sin herramientas ni citas |
| Acusaciones, insultos, delitos graves | Respuesta fija desde `safety.py`; el modelo no participa |
| Intento de inyección de instrucciones | Rechazo breve y retoma el tema; el contenido de las fichas y del usuario se trata como dato |
| Proveedor caído | Reintentos → modelo alternativo → respuesta `degraded` con las fichas más relacionadas |

Estilo: español rioplatense, trato de vos, 80–170 palabras (hasta 260 si piden detalle), párrafos cortos, listas con guion para requisitos, sin negritas ni tablas, sin teléfonos o correos si no los piden, sin códigos internos (Z3, O05, TS-011) y sin hablar de "herramientas" o "base de datos". Todo esto se pide en el prompt (`services/prompts.py`); **no hay filtros que borren oraciones** de la respuesta del modelo. Lo único que el servidor corrige es mecánico: citas inexistentes y códigos internos.

## Contexto del modelo

1. **Reglas** (código) + tono adicional (panel) + zonas Z1–Z7 con su código para el filtro.
2. **Mapa de la guía:** identificador · título de las 257 fichas públicas, agrupadas por tema (~6.000 tokens). Sirve para descubrir qué existe sin gastar una búsqueda y evita afirmar "la guía no lo trata" sobre algo que sí está. No es evidencia ni se cita.
3. **Historial** reciente de la conversación (sin marcas `[n]`).
4. **Evidencia inicial:** la búsqueda híbrida sobre la pregunta, presentada como una llamada a `buscar_en_la_guia` ya ejecutada.

## Contrato de herramientas

| Herramienta | Entrada | Salida |
| --- | --- | --- |
| `buscar_en_la_guia` | `consulta` (obligatoria), `zonas` (códigos Z1–Z7, opcional), `tipo` (`oportunidad`, `zona`, `ejemplo`, `ficha`, opcional) | Hasta 8 fichas numeradas: texto, tema, zonas, nivel de evidencia, corte, condiciones y alcance |
| `ver_ficha` | `fichas`: hasta 6 identificadores del mapa o números `[n]` ya vistos | Las fichas completas; avisa de los identificadores inexistentes |

Límites: 4 pasos, 6 llamadas a herramientas por paso, 36.000 caracteres de evidencia, 100 s en total. Las herramientas son de **solo lectura sobre la versión pública publicada**; no hay herramientas de escritura, publicación, web ni acceso a secretos, y agregarlas requiere autorización expresa.

## Citas

Los números `[n]` valen dentro de una respuesta. El servidor descarta los que no existen en la evidencia recuperada, renumera los usados 1..n por orden de aparición y adjunta por cada uno título, extracto, nivel de evidencia, fecha de corte, ubicación en el documento original y las fuentes primarias. Si la respuesta usa evidencia pero no cita, se pide una sola reescritura (solo se acepta si queda respaldada).

Una cita válida **no garantiza** que la afirmación sea correcta; garantiza que proviene de una ficha realmente recuperada para esa consulta.

## Cómo evaluar un cambio

1. `python scripts/evaluate_retrieval.py --modes hybrid --verbose` (sin costo): hit@k contra `evals/retrieval_gold.json`.
2. `python scripts/evaluate_answers.py --report informe.md` (consume cuota): 31 conversaciones con controles automáticos (fichas esperadas, cifras sin respaldo en la evidencia, códigos internos, longitud, estado).
3. Leer el informe: los controles automáticos no detectan una afirmación errónea bien citada. El modelo no es determinista: un caso límite puede cambiar entre corridas.
4. `python scripts/chat_cli.py ... --trace` para depurar una conversación concreta.

## Referencias

- Anthropic, [Contextual Retrieval](https://www.anthropic.com/research/contextual-retrieval): cabecera contextual en embedding y BM25.
- [LanceDB: búsqueda híbrida](https://docs.lancedb.com/search/hybrid-search) y [FTS](https://docs.lancedb.com/search/full-text-search): FTS nativo con idioma español, stemming y `ascii_folding`, fusión RRF.
- [kotaemon](https://github.com/Cinnamon/kotaemon) y [RAGFlow](https://github.com/infiniflow/ragflow): híbrido + reranking por defecto, motor de recuperación separado del de agente, citas visibles.
- [Haystack Agent](https://docs.haystack.deepset.ai/docs/agents) y [LlamaIndex agentes](https://developers.llamaindex.ai/python/framework/use_cases/agents/): bucle de herramientas con límite de pasos.
- [Coveo Labs, *Most Conversational RAG Systems Work — Until They Don't*](https://www.coveo.com/blog/conversational-rag/): un solo agente con búsqueda múltiple y verificación de completitud.
