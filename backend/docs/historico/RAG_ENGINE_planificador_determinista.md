# Motor RAG · octubre de 2026

Desde el 24/10/2026 las versiones nuevas usan Granite 97M multilingüe R2 + mMARCO MiniLM + LanceDB, con ONNX cuantizado CPU. Flask, Gunicorn de un proceso, MariaDB y Ollama mantienen sus responsabilidades. Cada snapshot público conserva su tabla LanceDB y su huella de pesos, tokenizadores, pooling, normalización y runtime. Las versiones publicadas con `bekko-horizon-lance-v2` siguen usando ese par y `bekko-context-v2`, incluso durante la preparación de una nueva. No se cambian sus vectores ni su puntero. OpenVINO no se reintroduce: produjo `SIGSEGV` confirmado en el servidor.

## Revisión del 29/10: planificador determinista sin intérprete por modelo

Se eliminó el intérprete y el editor por modelo: la ruta, la actividad, las zonas y la intención las resuelve `services/planner.py` con regex y catálogo, sin llamadas al proveedor. El recorrido vigente es `RAG.answer` → `route_question` (saludo, identidad, seguridad, fuera de alcance) → `plan_question` (hasta 3 búsquedas) → `retrieve_for_plan` (anclas de catálogo primero, luego mMARCO sobre el resto, límite de contexto según intención) → `generate`/`finalize` (contrato JSON único `{answer, sufficient, evidence_ids, missing}`, con un solo reintento ante JSON inválido).

`services/catalog.py` concentra el conocimiento de ruteo: 16 oportunidades O01–O16 con zonas y prioridad, capítulos y perfiles de las 7 zonas, registros de requisitos por frente y tópicos de datos con sus registros. `services/activities.py` distingue tarjeta exacta, necesidad documentada y actividad no documentada (local bailable, kiosco, gimnasio, estación de servicio): sin tarjeta ni documentación no hay anclas y la respuesta es abstención, no perfiles de otras zonas. `source-context-v4` añade tipo de registro y actividades al prefijo de búsqueda. Cobertura medida: 36/36 grupos en `tests/data/retrieval_strategy_cases.json` con `scripts/evaluate_candidate_stack.py` sobre el corpus consolidado.

## Revisión del 24/10: búsqueda, contexto y migración

Se revisó [Giana Turismo](https://github.com/NebyX1/giana-turismo/tree/b1ce4826d36dfed9ea48c961ce645b82ab4adcc4): Granite, mMARCO, recuperación híbrida, contexto del padre y segunda oportunidad acotada. Se adaptaron esas ideas al perfil CPU/LanceDB existente; no se copiaron CUDA, Qdrant, búsqueda web, fast paths ni respuestas prefabricadas.

| Componente nuevo | Revisión fijada | Contrato |
| --- | --- | --- |
| `ibm-granite/granite-embedding-97m-multilingual-r2` | `835ad14087e140460703cf0fae09f97d469d65c2` | ONNX `model_quint8_avx2`, CLS + L2, 384 dimensiones; ventana operativa 512 tokens |
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | `1427fd652930e4ba29e8149678df786c240d8825` | ONNX `model_quint8_avx2`, padding ID 1, pares de hasta 512 tokens |

Fuentes primarias: [Granite y su pooling CLS](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2), [mMARCO](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1). Los modelos de producción no se eligen por sus puntuaciones MTEB: se comparan sobre preguntas y fuentes de este proyecto.

El nuevo recorrido es:

1. Capturar una versión inmutable; el intérprete recibe un inventario acotado derivado exclusivamente de sus títulos públicos, no una lista fija de temas supuestamente disponibles. Ese inventario orienta búsquedas y nunca sustituye evidencia.
2. Conservar la pregunta original, resolver alias territoriales y referencias conversacionales, y ejecutar hasta cuatro búsquedas globales. La misma resolución llega al reranker. Las búsquedas complementarias por zona no excluyen las fuentes generales de permisos o incentivos.
3. Seleccionar candidatos por turnos entre ángulos, no solo por frecuencia de repetición. Por defecto, 28 candidatos por búsqueda y 24 para reranking; los ajustes persistidos del operador se respetan. Cada página vuelve a validarse contra MariaDB en dos lecturas por lote, no dos consultas SQL por fragmento.
4. `source-context-v3` conserva los encabezados originales y la localidad junto al cuerpo, sin prefijos editoriales repetitivos. No altera el texto original, las condiciones, la audiencia, las fuentes ni el formato canónico `gianna.corpus.v1`.
5. mMARCO ordena por relevancia semántica; no se diluye su orden con una segunda fusión de igual peso. Los perfiles de los lugares consultados y las fuentes líderes de búsquedas complementarias conservan un lugar en el contexto acotado. No se eligen por IDs de fichas ni por una tabla sector→respuesta. Una fuente reservada sigue necesitando lectura pertinente: no prueba por sí sola que exista una oportunidad o un dato.
6. La respuesta puede usar una segunda lectura pública, una sola vez, cualquiera sea el tipo de pregunta. Antes de aceptar una abstención, el validador intenta esa lectura si no se hizo y pide una única revisión contra las fuentes existentes, aunque no haya resultados nuevos. No fuerza una respuesta positiva. La ausencia en los primeros resultados no prueba ausencia en toda la base. Un ejemplo técnico puede responder una pregunta informativa sin convertirse en oferta comercial real.
7. El laboratorio sin Ollama ejecuta ese motor con resolución local y reranker; la prueba con Ollama añade interpretación y generación. Muestra las consultas solo en la respuesta administrativa transitoria. Las trazas persistidas no guardan el texto de esas consultas.

### Preparación y transición sin cambiar `.env`

En el volumen persistente del contenedor:

```sh
python -m scripts.prepare_models --model-dir /app/data/models
python -m scripts.check_model_runtime --model-dir /app/data/models
```

Después, generar una versión nueva de la base pública ya revisada, probarla y publicarla explícitamente desde el panel. No es necesario volver a importar la documentación ni aprobar registros internos. La versión anterior continúa disponible con sus propios pesos; el worker prepara primero el perfil activo al arrancar. Si un rollback requiere un perfil aún no cargado, se encola su preparación y se solicita confirmar la publicación al terminar. No borrar el volumen ni los modelos anteriores durante la transición.

Para reproducir la evaluación completa, usar en Ajustes 28 candidatos de recuperación y 24 de reordenación, con contexto de 8 registros y 20.000 caracteres. No se sobrescriben ajustes persistidos: con el antiguo límite 20/16 se recuperaron las fuentes de 35/36 preguntas en Linux, pero se perdió la de población. Durante la migración pueden coexistir ambos pares en memoria: el smoke de ambos con 2 GiB pasó, pero alcanzó 1.764,9 MiB de RSS sin carga HTTP/indexación simultánea. Prever margen adicional y medir en el VPS antes de migrar; ese resultado no certifica 2 GiB como mínimo productivo.

Para restaurar artefactos v2 que falten, sin cambiar el perfil por defecto ni el índice:

```sh
python -m scripts.prepare_models --engine bekko-horizon-lance-v2 --model-dir /app/data/models
```

### Evaluación reproducible

```sh
python -m scripts.compare_retrieval_strategies --prepare
python -m scripts.evaluate_candidate_stack
python -m scripts.evaluate_candidate_stack --run-provider --output reports/evaluacion-nueva.json
```

El primer comando compara 20 combinaciones (720 ejecuciones sobre 36 preguntas, incluidas 12 reformulaciones designadas de validación); el segundo evalúa la aplicación sin proveedor; el tercero añade respuestas de Ollama y pares sintéticos con/sin fuente. Los índices y bases SQL son temporales, la base configurada no se conecta y no se publica contenido del portal. Los datos sintéticos nunca se presentan como oportunidades reales. La cobertura de IDs y las citas válidas no certifican verdad factual, vigencia ni rendimiento en el VPS: los resultados y limitaciones se registran en `reports/VALIDACION.md`.

## Rol informativo, memoria y contexto de 8K

La persona elige proyecto y zona. Gianna describe datos y diferencias documentadas, sin recomendar ganadores ni trasladar la consulta a otros negocios. Una posible relación con el proyecto se expresa en condicional: no demuestra público efectivo ni viabilidad. Aclarar respetuosamente un dato factual sigue siendo necesario; no equivale a corregir la intención. Solo se explican procedimientos cuando se preguntan.

La reformulación y la necesidad propuesta por el intérprete se usan para buscar, **no se entregan como un nuevo pedido al redactor ni al editor**. Estos reciben la pregunta literal, el proyecto/memoria y las zonas resueltas. Se evita así que una ampliación de búsqueda sobre demanda o viabilidad se convierta en una exigencia que la persona nunca formuló.

Una selección informativa adicional recibe la pregunta literal, memoria y borrador ya documentado, sin herramientas ni conocimiento externo. Solo puede seleccionar o reformular lo ya dicho, no incorporar hechos ni fuentes nuevas. Su salida estructurada `InformationEdit` separa `information` (hasta seis oraciones pertinentes), `missing_information` (el dato faltante) y `source_ids` (las citas del borrador usadas por la información positiva). El servidor muestra primero los datos; si solo queda ausencia, deriva `insufficient_evidence` y no adjunta citas. No se deja que una copia del estado del borrador convierta la falta de datos en una respuesta respaldada por una fuente irrelevante. No hay una lista de palabras prohibidas ni clasificación por tema. La selección semántica sigue dependiendo del modelo.

Las indicaciones de hacer/comprobar/validar/tramitar van al apartado separado `procedures`. El servidor solo lo muestra cuando `procedures_requested` indica que la pregunta lo pidió expresamente; una intención de invertir o una comparación no lo pide por sí sola. La clasificación de esas frases sigue siendo del modelo: el filtro estructural no certifica que este nunca deje una indicación en el apartado incorrecto. Es una restricción de alcance de la respuesta, no un filtro de temas de búsqueda.

Se reprodujo además una incompatibilidad real de formato: el proveedor devolvía valores válidos dentro de un contenedor `properties`, que podían leerse como campos vacíos. Se admite solo ese contenedor de instancia, manteniendo campos obligatorios, tipos y citas; un JSON Schema real o un objeto vacío se rechaza. Se añadió el mismo rechazo preventivo al intérprete, sin atribuirle incidentes no observados. Las pruebas conservan el formato real capturado, no solo la respuesta ideal del doble.

Se descartó realimentar al editor con todos los fragmentos: tendía a producir otro resumen de los consejos del documento. También se descartó la edición extensa con listas de citas a borrar y razonamiento oculto: consumía el tope y podía dejar sin respuesta una consulta válida. La búsqueda, segunda lectura y redacción fundamentada pertenecen al primer agente; la selección final es de pertinencia/tono, **no una segunda verificación factual**. Revalida las citas contra las ya declaradas y admite una reparación. Un fallo no se presenta como ausencia documental. Añade normalmente una llamada a Ollama y latencia. En DeepSeek V4.1 usa `reasoning_effort=none` para esta selección breve; el intérprete/redactor conservan su perfil. No se eleva el máximo del operador ni se sustituye su elección persistida.

La sesión guarda mensajes completos recientes cifrados, acotados por tokens y un tope defensivo de 256 mensajes. Se retiraron los recortes fijos de doce mensajes, seis mensajes enviados y 900 caracteres. El intérprete actualiza un resumen separado del proyecto, nombre, exclusiones e intereses. La conversación social recibe esa memoria para recordar datos propios sin inventar fuentes territoriales. Un cambio explícito actualiza el proyecto. El borrado y la caducidad siguen eliminando sesión y memoria.

`services/context_budget.py` aplica **8.000 tokens totales por petición**, no 8.000 de historial más fuentes. Cuenta mensajes, esquemas y herramientas/resultados; reserva salida y un margen de 512 para el formato del proveedor. Desaloja primero mensajes viejos, no el cuerpo o las condiciones de las fuentes. La evidencia inicial tiene además un máximo de 3.600 tokens y la segunda lectura, 4.500 acumulados, respetando también registros/caracteres. Si reglas, pregunta y evidencia no caben, devuelve `context_budget_exceeded`, no una falsa negativa. Puede reducir la salida para respetar el total, nunca elevarla sobre el ajuste del operador.

Para `deepseek-v4.1-flash*` usa el tokenizador oficial de generación `deepseek-ai/DeepSeek-V4.1-Flash`, revisión fijada `314113f8a7dadb388215396ba5fbee2c610a04d6`, verificado por manifiesto/SHA-256. **No es el tokenizador del embedding.** Otros modelos, o una instalación sin ese artefacto, usan una cota conservadora de bytes UTF-8: pueden admitir menos texto o rechazar antes una consulta. No se certificó el aprovechamiento de 8K con todos los generadores. La API informa el consumo real; las pruebas comprueban entrada **más** salida. El conteo local con margen no equivale exactamente a todos los formatos remotos. Referencias: [tokenizador oficial](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/tree/314113f8a7dadb388215396ba5fbee2c610a04d6), [uso de tokens](https://api-docs.deepseek.com/quick_start/token_usage/), [compatibilidad de Ollama](https://docs.ollama.com/api/openai-compatibility).

El comando existente `python -m scripts.prepare_models --model-dir /app/data/models` prepara también ese tokenizador. Ejecutarlo después de desplegar y conservar `/app/data`. No requiere `.env` nuevo ni reindexar solo por tono/memoria; la migración vectorial v2→v3 sí exige la versión nueva descrita arriba. No se descarga dentro del chat.

Auditoría HTTP con modelos/proveedor reales, CAPTCHA y sesiones aisladas:

```sh
python -m scripts.evaluate_information_dialogues --run-provider --workers 2 --max-output-tokens 4096 --extra-cases tests/data/information_memory_long_cases.json --output reports/auditoria-nueva.json
```

Requiere corpus autorizado y artefactos preparados. Lee solo las tres opciones de Ollama del entorno local; no conecta con la MariaDB configurada ni cambia publicaciones. Los IDs esperados sirven para comprobar resultados, nunca se entregan al generador. Las regex de tono son señales para revisión humana, no una puntuación automática. Resultados e iteraciones fallidas: [VALIDACION.md](../reports/VALIDACION.md).

`--max-output-tokens` configura exclusivamente la aplicación temporal de prueba. No cambia el panel ni `.env`. El presupuesto total de 8K sigue aplicándose y puede reducir la salida efectiva de una solicitud. No extrapolar una validación con un modelo, personalidad y límite a todas las otras combinaciones.

Tras comparar los perfiles explícitos 950/4.096, el predeterminado de instalaciones nuevas pasa a **4.096 de salida**, sin alterar límites ya guardados por el operador. La personalidad antigua predeterminada exacta pasa al rol informativo; los textos personalizados no se sobrescriben. En una instalación existente, comprobar el valor en Personalización antes de atribuirle los resultados del perfil de 4.096. El script de diálogos conserva 950 como control histórico si no se pasa la opción: el comando anterior selecciona explícitamente el perfil validado.

## Historial técnico anterior (perfil v2)

Las secciones siguientes documentan decisiones históricas, incluidas instrucciones de orientación y límites de memoria ya sustituidos. El recorrido vigente y los comandos de transición están arriba.

## Modelos

El generador se puede cambiar sin reindexar. El modelo seleccionado localmente tras la comparación es `deepseek-v4.1-flash:1017` en la API directa de Ollama (CLI: `deepseek-v4.1-flash:1017-cloud`), con `think:low` y un límite de 4.096 tokens de generación. Se comparó con `beam`/`beam:cloud` usando los mismos parámetros y tres turnos; el informe está en `reports/rag-migration/beam-vs-deepseek-1017.json`. El modelo DeepSeek sin revisión explícita mantiene su perfil anterior `think:false`. Se mantuvieron Bekko, Horizon y LanceDB. El catálogo real de `/api/tags` confirmó el nombre para la API; [Ollama documenta la distinción entre API y CLI](https://docs.ollama.com/cloud).

Con este MiniMax, una consulta completa agotó 2.000 tokens en `message.thinking` y dejó `message.content` vacío, incluso con `think:false`. Por eso se usa su modo predeterminado y un límite local explícito de 8.192 tokens de generación **incluido el razonamiento**, no 8.192 tokens de texto visible. El límite del panel admite hasta 8.192 y no se aumenta de forma oculta en el transporte. Clasificación y conversación conservan ese presupuesto cuando se selecciona este modelo, en lugar de recortarlo a 400/500; los otros modelos mantienen sus límites breves. Esto puede aumentar latencia y consumo. Los reintentos y límites de concurrencia siguen acotados.

| Componente | Modelo | Revisión fijada | Ejecución |
|---|---|---|---|
| Embedding | `hotchpotch/bekko-embedding-v1-a8m` | `c721113d59a1d91b447450324f51c4b3332c924a` | ONNX Runtime CPU, media enmascarada y normalización L2, 384 dimensiones |
| Reranker | `Horizon-Labs/multilingual-reranker-small` | `c2ec8fb3e499725b168bbed2164bfee095360f77` | ONNX Runtime cuantizado CPU, pares de 384 tokens, consulta hasta 120 tokens |

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

Desde `backend/` en una instalación exclusiva de pruebas, con `DATABASE_URL` apuntando a su esquema MariaDB aislado:

```powershell
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env build api
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env run --rm --no-deps api python -m scripts.prepare_models
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env up -d api
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env exec -T api python -m scripts.enable_human_test /app/data/invest_lavalleja_2026.gianna.json
```

LanceDB y modelos quedan dentro de `/app/data`, en el volumen persistente `gianna_data` del proyecto Compose correspondiente. Compose aísla este volumen; la base MariaDB depende de la única `DATABASE_URL` de esa instalación. El servicio Qdrant deja de ser una dependencia; sus datos anteriores pueden conservarse como respaldo histórico. Un rollback de datos dentro del motor nuevo requiere una versión compatible; volver al motor antiguo exige además su imagen y servicio anteriores.

## Medición

`tests/data/retrieval_cases.json` contiene ocho consultas con grupos de registros esperados revisados contra el corpus público. `python -m scripts.evaluate_retrieval --cases tests/data/retrieval_cases.json --output RUTA_NUEVA` evalúa el contexto final sin llamar a Ollama. Los informes antes/después están en `reports/rag-migration/`. Es una batería pequeña de regresión conocida, no un benchmark independiente ni una garantía factual de respuestas generadas. Las respuestas reales se revisan además por API pública con CAPTCHA y sesión.
