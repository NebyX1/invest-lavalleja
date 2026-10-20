# Motor RAG · octubre de 2026

Gianna usa Bekko + Horizon + LanceDB. Flask, Gunicorn de un proceso, MariaDB y la API de Ollama mantienen sus responsabilidades. MariaDB conserva documentos, versiones, aprobación editorial y el puntero activo. Cada versión pública tiene una tabla LanceDB propia y una huella que incluye pesos, tokenizadores, pooling, normalización y runtimes. El índice E5/Qdrant anterior requiere reindexación; sus vectores de 384 dimensiones no se reutilizan.

## Modelos

El generador se puede cambiar sin reindexar. El modelo seleccionado localmente tras la comparación es `deepseek-v4.1-flash:1017` en la API directa de Ollama (CLI: `deepseek-v4.1-flash:1017-cloud`), con `think:low` y un límite de 4.096 tokens de generación. Se comparó con `beam`/`beam:cloud` usando los mismos parámetros y tres turnos; el informe está en `reports/rag-migration/beam-vs-deepseek-1017.json`. El modelo DeepSeek sin revisión explícita mantiene su perfil anterior `think:false`. Se mantuvieron Bekko, Horizon y LanceDB. El catálogo real de `/api/tags` confirmó el nombre para la API; [Ollama documenta la distinción entre API y CLI](https://docs.ollama.com/cloud).

Con este MiniMax, una consulta completa agotó 2.000 tokens en `message.thinking` y dejó `message.content` vacío, incluso con `think:false`. Por eso se usa su modo predeterminado y un límite local explícito de 8.192 tokens de generación **incluido el razonamiento**, no 8.192 tokens de texto visible. El límite del panel admite hasta 8.192 y no se aumenta de forma oculta en el transporte. Clasificación y conversación conservan ese presupuesto cuando se selecciona este modelo, en lugar de recortarlo a 400/500; los otros modelos mantienen sus límites breves. Esto puede aumentar latencia y consumo. Los reintentos y límites de concurrencia siguen acotados.

| Componente | Modelo | Revisión fijada | Ejecución |
|---|---|---|---|
| Embedding | `hotchpotch/bekko-embedding-v1-a8m` | `c721113d59a1d91b447450324f51c4b3332c924a` | OpenVINO CPU, media enmascarada y normalización L2, 384 dimensiones |
| Reranker | `Horizon-Labs/multilingual-reranker-small` | `c2ec8fb3e499725b168bbed2164bfee095360f77` | ONNX cuantizado CPU, pares de 384 tokens, consulta hasta 120 tokens |

Se tomó como referencia la implementación de [Patitas Lavalleja](https://github.com/NebyX1/patitas-lavalleja). Bekko no usa los prefijos `query:`/`passage:` de E5. Los pasajes se cuentan con su tokenizador real y se limitan a 480 tokens, dentro de la ventana operativa de 512. Horizon ordena pasajes; su salida sigmoid es relevancia textual, no probabilidad de verdad o éxito del negocio. Los modelos se cargan una vez por proceso y comparten un bloqueo de inferencia. Sus configuraciones y pesos se preparan explícitamente y verifican con SHA-256; las peticiones de chat no descargan modelos.

Fuentes primarias: [Bekko](https://huggingface.co/hotchpotch/bekko-embedding-v1-a8m), [Horizon](https://huggingface.co/Horizon-Labs/multilingual-reranker-small), [LanceDB](https://docs.lancedb.com/).

## Recuperación general basada en evidencia

**Sustituye los filtros temáticos y plantillas introducidos el 19/10/2026.** El portal sigue siendo de inversiones. Desde el 19/10/2026 (segunda y tercera revisión) Gianna es un **agente de asesoría informativa** construido con PydanticAI (`services/agents.py`, patrón tomado de Gianna Lex): el modelo interpreta cada turno, sostiene la memoria del hilo e integra la evidencia en una respuesta coherente que compara las zonas u opciones de la base de conocimiento y explica la ventaja de cada una. Trata a la persona como un inversor adulto que sabe lo que quiere y pide información; no inventa hechos, disponibilidad ni beneficios y no da asesoramiento legal, fiscal o financiero definitivo. Esto sustituye el rol «solo informativo, sin orientación» de la revisión anterior. No hay una regla que decida que renovables, inventarios u otro tema carecen de información por su vocabulario.

1. **Puertas de seguridad deterministas** (`AgentHarness.hard_gate`): acusaciones a personas, delitos graves e insultos conservan sus rutas fijas y nunca llegan al modelo. Los saludos inequívocos reciben una cortesía sin interpretar.
2. **Intérprete de turnos** (`Agents.interpret`, una llamada breve, salida estructurada `TurnPlan` validada con reintento nativo). Recibe el mensaje, la memoria actual y la conversación como mensajes nativos, y devuelve: el acto (`chat`, `knowledge`, `deescalate`, `allegation`, `refuse`), el tipo de pedido (`places`, `opportunities`, `requirements`, `facts`, `compare`, `next_steps`, `followup`), la necesidad de la persona en una frase, una consulta autosuficiente, de dos a cuatro búsquedas con el vocabulario de la base y la **memoria actualizada**. No hay regex de intención: «Quiero poner un boliche» es un pedido de *dónde y qué ofrece cada lugar*, no de trámites. Si el modelo falla o devuelve algo inválido, `AgentHarness.retrieval_plan` aporta un plan determinista de respaldo que conserva la memoria previa.
3. Se captura una sola versión pública para toda la consulta. Se busca globalmente con la pregunta real, la consulta autosuficiente y las búsquedas del intérprete, hasta cuatro. Bekko y BM25 español consultan LanceDB y fusionan sus resultados con RRF. No se filtra por listas de temas, palabras del título, tipo de ficha, padrón, rentabilidad o localidad.
4. Cada ID vuelve a validarse contra MariaDB y su audiencia pública. Se combinan candidatos por registro y afinidad entre búsquedas. Las referencias explícitas del usuario pueden suplementar candidatos, pero no hay prioridades sector→ficha.
5. Horizon reordena hasta el presupuesto configurado de candidatos (16 por defecto) con las palabras de la persona y su necesidad. El orden final **fusiona con RRF (k=60) el orden por afinidad entre búsquedas y el del reranker**: el reranker pequeño en CPU es un juez inestable y por sí solo llegó a hundir los perfiles de zona que todas las búsquedas habían encontrado. Se prepara un contexto acotado con las fuentes originales y sus condiciones editoriales, sin eliminar secciones por tema. Una puntuación no se interpreta como probabilidad ni se usa un umbral para negar la respuesta.
6. **Agente de respuesta** (`Agents.answer`). Lee la necesidad, la memoria, la evidencia y la conversación nativa; decide si puede responder total, parcialmente o no. Solo en pedidos de dato puntual (`requirements`, `facts`, `develop`) dispone de la herramienta `buscar_en_la_base`: una única **segunda lectura** de solo lectura, con IDs nuevos que continúan la numeración, que se registra en la traza sin texto. En pedidos amplios (`places`, `opportunities`, `compare`) no se ofrece porque solo añadía ruido y latencia.
7. La respuesta sigue un contrato estructural (ver más abajo). Se conservan prevención de secretos, privacidad, seguridad, límites, estados y snapshots. Que el contrato sea válido no certifica el respaldo semántico de cada afirmación.

Las trazas registran búsqueda global, candidatos, reranking y fusión, contexto seleccionado, segundas lecturas y validación, sin almacenar consultas o texto documental en claro.

## Contrato de respuesta y falta de información

Todo se redacta después de buscar y leer los resultados. El agente devuelve texto plano con un contrato acotado (`services/response_policy.py`), validado por un `output_validator` de PydanticAI que reintenta de forma nativa hasta dos veces con el recordatorio del contrato:

- Primera línea `ESTADO: RESPONDE` o `ESTADO: SIN_INFORMACION`. El modelo decide semánticamente si la evidencia alcanza, total o parcialmente; solo declara `SIN_INFORMACION` cuando ningún fragmento aporta algo útil.
- Con `RESPONDE`: la respuesta sin IDs en el texto y una última línea `FUENTES: C1, C3`. El servidor conserva solo IDs que existen en el contexto público de esta consulta y depura (`supported_sources`) las declaradas que no comparten ni su título ni contenido sustancial con la respuesta; nunca deja la respuesta sin fuente. Las fuentes se muestran aparte en la interfaz.
- Con `SIN_INFORMACION`: una a tres frases naturales; no hay citas.
- Si el formato sigue inválido tras los reintentos, el resultado es `citation_guard_failed`, no una negativa.
- Las URLs se eliminan. Un guard de atribución solo retira párrafos que nombran entidades específicas (Bomberos, RUNAEV, DINACEA, SNAP, UNESCO…) ausentes de toda la evidencia recuperada.
- Un saneador de vocabulario (`refine_voice`) reemplaza «la guía», «la documentación consultada» y «hipótesis» por «mi base de conocimiento» y «posibilidad», respetando títulos reales de documentos oficiales. El prompt ya pide esa redacción; el saneador es la última salvaguarda.

La falta de hallazgos en una recuperación acotada no demuestra que el dato no exista en todo el corpus. La redacción debe reconocer ese límite. No hay búsqueda web ni fuentes externas durante el chat.

## Memoria y rol

La sesión cifrada conserva doce mensajes y el estado del proyecto. El estado incluye `memory` (`InvestorMemory`): proyecto de la persona, intereses, opciones ya presentadas y preferencias, todo acotado a seis ítems por lista, validado con Pydantic y nunca tratado como evidencia. El intérprete la recibe y la devuelve actualizada en cada turno; los turnos sociales no la modifican. El agente de respuesta y el de conversación reciben los últimos turnos como mensajes nativos sin marcas de cita. Las citas y hechos redactados en turnos anteriores nunca se usan como evidencia documental nueva. El borrado/expiración siguen el ciclo de vida de la sesión anónima.

El tipo de pedido elige la guía de tarea (`planning.policy_for`): describe qué contiene una respuesta útil (comparar zonas y la experiencia o público de cada una, ordenar requisitos, profundizar sin repetir lo ya presentado), no qué documentos están permitidos. El prompt (`ANSWER_SYSTEM`) fija el trato: un par informado, sin explicarle lo básico ni indicarle «primero definí…», con trámites solo si los pidió o si cambian la elección del lugar. Los módulos históricos de selección por sector no participan en `RAG.retrieve_plan`.

**Transporte y pruebas.** `Ollama.agent_model` usa el endpoint compatible con OpenAI de Ollama Cloud (`/v1`) con un transporte por solicitud, necesario porque PydanticAI ejecuta cada llamada síncrona en su propio bucle de eventos. Las pruebas usan `chat_function_model`, que ejecuta los mismos agentes sobre cualquier transporte con `chat(messages, settings, think)`; no hay llamadas pagas en la suite.

## Regresión general reproducible

`python -m scripts.evaluate_general_rag --run-provider --output RUTA_NUEVA` ejecuta consultas por la API pública con CAPTCHA/sesión y pares de corpus sintéticos aislados. Estos últimos usan Bekko, Horizon, LanceDB y el proveedor reales: la misma pregunta se ejecuta con y sin el documento pertinente, incluyendo paráfrasis y un tema fuera del antiguo catálogo. Solo se crean almacenamientos temporales aislados; no se reemplaza ni publica contenido en la base del portal. La versión pública se comprueba antes y después.

Las trazas permiten verificar que una negativa no salió de una regla previa a búsqueda/reranking/generación. Son regresiones pequeñas conocidas, no una garantía factual ni de cobertura exhaustiva. Las pruebas unitarias con dobles se reportan por separado. Los escenarios anteriores que exigían negativas específicas por tema o comparaciones territoriales fijas son históricos; no deben usarse como criterio de aceptación de este flujo.

## Qué se tomó de Harness²

Se revisaron [README](https://github.com/google-research/harness2), [recursion.py](https://github.com/google-research/harness2/blob/main/harness2/core/recursion.py), [spec.py](https://github.com/google-research/harness2/blob/main/harness2/core/spec.py) y [prompts.py](https://github.com/google-research/harness2/blob/main/harness2/core/prompts.py). Las ideas aplicadas son comparar ejecuciones sobre la misma tarea, conservar evidencia de cada fase, acotar intentos y mover instrucciones específicas fuera del prompt permanente. El propio framework ejecuta agentes de tareas mediante Codex/OpenCode y múltiples rollouts; no se instaló como dependencia del chat ni se habilitaron comandos o autoedición de reglas desde conversaciones. Se trata de una adaptación de diseño, no de una ejecución o benchmark de Harness².

## Preparar y reindexar en local

Desde `backend/`, con la configuración local existente:

```powershell
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env build api
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env run --rm --no-deps api python -m scripts.prepare_models
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env up -d api
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env exec -T api python -m scripts.enable_human_test /app/data/invest_lavalleja_2026.gianna.json
```

LanceDB y modelos quedan dentro de `/app/data`, en el volumen persistente `gianna_data` del proyecto Compose correspondiente. La pila humana conserva su aislamiento. El servicio Qdrant deja de ser una dependencia; sus datos anteriores pueden conservarse como respaldo histórico. Un rollback de datos dentro del motor nuevo requiere una versión compatible; volver al motor antiguo exige además su imagen y servicio anteriores.

## Medición

`tests/data/retrieval_cases.json` contiene ocho consultas con grupos de registros esperados revisados contra el corpus público. `python -m scripts.evaluate_retrieval --cases tests/data/retrieval_cases.json --output RUTA_NUEVA` evalúa el contexto final sin llamar a Ollama. Los informes antes/después están en `reports/rag-migration/`. Es una batería pequeña de regresión conocida, no un benchmark independiente ni una garantía factual de respuestas generadas. Las respuestas reales se revisan además por API pública con CAPTCHA y sesión.
