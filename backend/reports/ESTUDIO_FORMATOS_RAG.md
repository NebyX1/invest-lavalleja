# Formatos, bloques e índices para Gianna Invest

Evaluación local realizada el 24 y 25 de octubre de 2026, con corte bibliográfico al 24/10. Investigación, no despliegue ni sustitución de la base publicada. No se modifican el corpus de referencia, las audiencias, `.env`, la base de datos configurada ni los modelos de producción.

## Evaluación final

**Para alimentar el backend actual, elegiría el JSON normalizado `gianna.corpus.v1`. Como base de indexación mantendría fichas informativas breves con sección, título y localidad, búsqueda híbrida y reranking.** Es la alternativa simple que empató la mayor cobertura: 56/60 casos completos y todos los pasajes exigidos en 24/24 preguntas nuevas. No tiene un costo extra de segmentación semántica y preserva el contrato editorial existente.

La mejor candidata avanzada **sin perder cobertura en este conjunto** fue detectar fronteras semánticas sobre el cuerpo, sin prefijos compartidos: empató esos resultados y usó algo menos de contexto, a costo de mayor construcción. Su aparente ventaja de tiempo no está demostrada frente a la variación entre corridas. Buscar hijos y devolver padres fue una candidata más rápida, pero perdió un caso adicional y creó más vectores. Ninguna domina todos los criterios ni se adoptó automáticamente.

La conclusión no es que Markdown, Word o PDF no sirvan: **con el mismo texto y metadatos normalizados, el contenedor no mejora los embeddings**. Markdown puede ser una buena fuente de autoría, como en Turismo; su transformación a conocimiento validado es lo decisivo. PDF y Word deben conservarse como fuentes y pasar por conversión revisable, no usarse como sustitutos de un esquema explícito.

No se midió generación de respuestas en este estudio. **56/60 es cobertura esperada de fuentes, no 93% de respuestas correctas**, ni una certificación de ausencia de alucinaciones, vigencia factual o calidad de conversaciones. Los resultados justifican conservar la representación canónica y probar cambios de índice en el flujo completo antes de publicarlos.

## Qué se comparó

La pregunta tiene tres partes diferentes: **qué archivo intercambiar**, **qué unidad de conocimiento guardar** y **qué representación buscar**. Un PDF, un Word y un JSON con las mismas palabras pueden producir exactamente los mismos vectores si la extracción y normalización entregan el mismo texto. También pueden producir resultados distintos si el importador pierde títulos, fuentes, localidades, condiciones o límites de acceso.

Se generaron ocho representaciones exclusivamente de los **196 registros públicos habilitados** del paquete actual: JSON, JSONL, Markdown, TXT, DOCX, PDF de texto, CSV y HTML. Los 75 registros internos se excluyeron antes de convertir. Los marcadores de trazabilidad de las copias experimentales se retiran antes de generar embeddings: no son palabras de búsqueda ni respuestas programadas. El cuerpo original se conserva sin reescritura generativa.

Hay dos pistas de evaluación que no deben confundirse:

1. **Importación nativa:** se ejecuta `load_corpus` sin corregir sus resultados. Se cuentan registros, IDs originales, fuentes y metadatos conservados; las audiencias genéricas siguen siendo internas. PDF, CSV y HTML no se presentan como formatos admitidos por el backend actual.
2. **Transporte controlado:** se extrae el cuerpo de cada registro y se igualan sus metadatos mediante el paquete original. Esta pista aísla la pérdida de texto. Es un adaptador de laboratorio, **no** una capacidad ya implementada en la carga administrativa. Cuando las entradas del encoder coinciden byte a byte se demuestra su equivalencia por hash; no se inventan ocho benchmarks independientes de vectores idénticos. El PDF con saltos nuevos se indexa por separado.

## Protocolo de recuperación

- Corpus canónico sin cambios; SHA-256 en el resumen JSON. 196 cuerpos públicos, 77.911 caracteres; el mayor tiene 1.267 caracteres. Ninguna ficha necesita dividirse con el límite contextual de 300 tokens del encoder en este corpus.
- 36 preguntas previas más **24 preguntas nuevas congeladas antes de obtener resultados**, con 58 pasajes literales esperados. Los ejemplos nuevos incluyen magnitudes y períodos, hipótesis frente a hechos, condiciones administrativas, las siete zonas, funciones de canales institucionales y límites de lo que consta en una fuente. Son ejemplos diseñados por otro agente y verificados contra el corpus, no un conjunto humano independiente ni tráfico real de producción.
- Granite 97M multilingüe R2 y mMARCO MiniLM ONNX cuantizados, revisiones y SHA de pesos fijadas; ONNX limitado a dos hilos CPU. No se impuso una cuota total de CPU al proceso de Windows ni se midió RAM máxima por variante. Ninguna llamada a Ollama ni a otro generador. Se mantiene el mismo modelo para aislar estructura e índice.
- Catorce configuraciones: fichas actuales 420/40; cuerpo sin contexto; título con 240; contexto con 180, 240, 300 y 420; condiciones en la entrada; serialización de claves JSON; agrupación de frases; separación por cambios de similitud; hijos de 120 que devuelven la ficha padre; agrupación de sección; ventanas de texto aplanado.
- Se añadieron tres controles exploratorios, sin cambiar preguntas ni pasajes: similitud entre frases sin prefijos compartidos, solapamiento de 30 tokens en cortes de 180 y embeddings del cuerpo con BM25 contextual. Los dos primeros se definieron después de ver las primeras cuatro estructuras; el tercero surgió al revisar el código de Turismo. No son una familia confirmatoria independiente. Total: 17 estructuras, más el transporte PDF si cambia su entrada al encoder.
- La separación semántica ensayada compara frases adyacentes del mismo registro con el mismo encoder, corta con similitud coseno menor a 0,65 y respeta un máximo de 240 tokens. No es una búsqueda exhaustiva de umbrales ni una comparación de todas las bibliotecas semánticas. No genera ni reescribe hechos.
- En las variantes sin encabezado/con solo título cambia también el encabezado que se entrega en contexto: se evalúa ese bloque completo, no una ablación exclusivamente del encoder. La variante JSON de búsqueda serializa sección, título, códigos de zona y cuerpo; no introduce todo el paquete ni toda su bibliografía en el vector. Las condiciones se agregan una sola vez a cada unidad entregada, no dos veces en la variante que también las indexa.
- Cuatro búsquedas por configuración: coseno exacto, BM25 español, fusión RRF y fusión más reranking de 24 candidatos. Cada canal entrega hasta 28 candidatos. Una pregunta con alias territoriales resueltos, igual para todos; sin intérprete generativo, reservas por tema, segunda lectura ni correspondencias pregunta→IDs. Se mantiene el límite propio de mMARCO: consulta acotada a 120 tokens y pareja a 512, recortando solo el pasaje de ranking. Los bloques grandes pueden perder su final ante el reranker; no se recorta la evidencia entregada. No se atribuye una mejora al formato ignorando ese límite del modelo.
- Presupuesto idéntico de **2.000 tokens de evidencia**, contado con el tokenizador de generación verificado, y un máximo de ocho unidades de contexto. Las condiciones originales se adjuntan sin truncarlas. No se permite ganar simplemente devolviendo más texto.
- Se mide cobertura de todos los grupos de fuentes, cobertura de los pasajes necesarios, posición del primer grupo pertinente, proporción de texto de fuentes esperadas como aproximación —no precisión semántica—, tokens, construcción, almacenamiento y latencia local. Los pasajes que cruzan dos hijos se acreditan por unión de offsets originales, no solo si caben en uno.
- Las configuraciones con entradas y evidencia idénticas se identifican explícitamente y reutilizan el resultado de calidad; sus tiempos copiados **no** son mediciones adicionales. Preparación semántica incluye sus inferencias auxiliares. Se separa la inicialización del modelo en un proceso nuevo; la caché del sistema operativo no se vació. El orden no está aleatorizado y las medidas de tiempo no certifican capacidad del VPS ni latencia concurrente.

## Resultados de recuperación

Las filas siguientes usan búsqueda híbrida más mMARCO, sin generación. Cada caso de fuentes exige cubrir **todos** sus grupos esperados. Cada caso de pasajes exige conservar **todos** sus extractos literales, no solo uno. La cota sigue siendo 2.000 tokens de evidencia; 24 casos contienen 58 extractos.

| Configuración | Vectores | Fuentes completas /60 | Pasajes completos /24 | Tokens de contexto medios | Mediana consulta + ranking |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ficha contextual 420/40 | 196 | 56 | 24 | 1689 | 4,13 s |
| Cuerpo sin encabezado | 196 | 53 | 22 | 1406 | 3,30 s |
| Solo título, 240/0 | 197 | 53 | 22 | 1481 | 3,21 s |
| Contexto, 180/0 | 224 | 55 | 23 | 1487 | 2,96 s |
| Contexto, 240/0 | 203 | 55 | 23 | 1646 | 3,68 s |
| Contexto, 300/0 (= ficha actual) | 196 | 56 | 24 | 1689 | 4,13 s |
| Contexto, 420/0 (= ficha actual) | 196 | 56 | 24 | 1689 | 4,13 s |
| Condiciones dentro del índice | 199 | 53 | 24 | 1687 | 4,61 s |
| Claves JSON en el índice | 196 | 53 | 23 | 1691 | 4,39 s |
| Frases, 180 (= contextual 180) | 224 | 55 | 23 | 1487 | 2,96 s |
| Semántico con encabezados (= contextual 240) | 203 | 55 | 23 | 1646 | 3,68 s |
| Hijos 120 → ficha padre | 279 | 55 | 24 | 1699 | 2,23 s |
| Agrupar por sección, 420/40 | 62 | 55 | 23 | 1919 | 9,18 s |
| Ventanas aplanadas, 420/40 | 51 | 49 | 21 | 1759 | 9,50 s |
| Semántico sin prefijos, 240/0 | 215 | 56 | 24 | 1636 | 3,52 s |
| Contexto, 180/30 | 225 | 54 | 23 | 1509 | 1,76 s |
| Cuerpo denso + BM25 contextual | 196 | 54 | 23 | 1638 | 3,67 s |
| PDF con metadatos restaurados (control) | 196 | 56 | 24 | 1718 | 4,36 s |

Las cuatro filas indicadas como equivalentes reutilizan calidad y latencias del mismo índice; no son mediciones independientes. Hay **14 índices neuronales distintos**, 17 configuraciones estructurales más el control PDF y **4.320 filas lógicas pregunta × configuración × modalidad**. Siguen siendo 60 preguntas, no 4.320 pruebas independientes. Las métricas de los cuatro modos y cada fallo están en el JSON compacto; las selecciones detalladas, en el informe local completo.

### Canales del índice con las fichas actuales

| Modalidad | Fuentes completas /60 | Pasajes completos /24 | Mediana local |
| --- | ---: | ---: | ---: |
| Solo vectores | 47 | 18 | 54 ms |
| Solo BM25 español | 53 | 24 | 16 ms |
| Híbrido RRF | 54 | 22 | 70 ms |
| Híbrido y reranker | 56 | 24 | 4,13 s |

BM25 es esencial en estos ejemplos, pero falla varias paráfrasis/pedidos previos. La mezcla y el reranker elevan la cobertura, a costo de segundos de CPU. No convertiría “solo vectores” en la opción por defecto ni eliminaría el reranker basándome en que BM25 resolvió los 24 ejemplos nuevos.

### Calidad, construcción y costo

- Las fichas contextuales y la separación semántica sin prefijos empatan **56/60**, con los mismos cuatro fallos: comparación de zonas, bar, local bailable y terreno; ambas conservan los 58 pasajes de los 24 casos nuevos. Son fallos de la recuperación global acotada, no prueba de que los documentos no existan. No se ejecuta aquí el harness conversacional completo.
- La variante semántica sin prefijos usa 215 vectores frente a 196; **41.171 tokens de entrada al encoder** contando segmentación, frente a 21.866. Construirla tomó 62,45 s frente a 38,54 s; el contexto medio pasó de 1.689 a 1.636 tokens. Su mediana observada fue 3,52 s frente a 4,13 s: candidata para un piloto, sin ganancia de recuperación en este conjunto.
- El semántico con encabezados produjo las mismas fronteras que el contextual 240, pero hizo **42.258 tokens auxiliares**. Su costo de construcción informado combina preparación medida con codificación/índice reutilizados: no es otro build independiente. No aporta una mejora aquí.
- Buscar hijos y devolver el padre dio 55/60 y 24/24, con 279 entradas y unos 588 KiB de índice, frente a 196 y 447 KiB. La mediana observada bajó a 2,23 s; perdió además el caso de apertura de sociedad. No ahorró contexto generativo: devolvió unos 1.699 tokens frente a 1.689, porque devuelve la ficha completa. No es una reducción del 46% del tiempo total de respuesta.
- Agrupar por sección y aplanar reducen entradas a 62 y 51, pero elevan la mediana del reranking a unos nueve segundos y no superan la cobertura. Menos vectores no es igual a menos costo por pregunta.

**No hay un ganador de velocidad demostrado estadísticamente.** El propio control PDF se completó dos veces con los mismos resultados de calidad, pero sus medianas fueron 3,65 s y 4,36 s, una variación cercana al 19%. La mejora aparente del 15% del semántico sin prefijos cae dentro de ese orden de variación. Los tiempos son observaciones locales no intercaladas, no una certificación del VPS. Priorizaría primero conservación de información, procedencia y cobertura; repetiría la medición de latencia antes de cambiar defaults por diferencias pequeñas.

## Comparación de archivos de entrada

En transporte controlado, los ocho archivos permiten recuperar los 196 cuerpos completos, normalizando únicamente espacios y saltos. Siete conservan el cuerpo exactamente; PDF conserva 61 exactamente y cambia la disposición del espacio en los otros 135. Los siete formatos restantes producen el mismo hash de entradas al encoder después de restaurar metadatos. Esto no demuestra que sus importadores nativos sean equivalentes.

**Alcance de esa comparación:** JSON/JSONL son paquetes estructurados autoportantes; CSV contiene columnas de registros, pero no todo el registro bibliográfico. Las vistas narrativas de Word, Markdown, TXT, HTML y PDF muestran cuerpo y parte de sus metadatos, no codifican todos los campos ni las 50 fichas bibliográficas. Por tanto, los campos ausentes en su importación nativa no demuestran una incapacidad del formato ni son todos pérdidas del extractor: intervienen la vista exportada y su conversor. Solo la pista con metadatos igualados permite comparar recuperación del mismo conocimiento. No se compararon todos los posibles normalizadores disponibles para cada extensión.

| Archivo probado | Importación nativa de esta copia | Metadatos y decisión |
| --- | --- | --- |
| JSON `gianna.corpus.v1` | 196 registros; 196 identidades y todos sus campos iguales; 50 fuentes | Mejor paquete canónico cargable hoy: esquema explícito, trazabilidad y reporte de conversión. |
| JSONL | Los mismos 196 registros completos y 50 fuentes | Buen intercambio por registros. El exportador actual omite el reporte de conversión; el importador lee todo el archivo, no hace streaming. |
| Markdown | 196 registros internos por defecto | Conserva contenido, pero no reconstruye IDs originales, registro de fuentes, zonas ni condiciones como campos. Necesita un normalizador distinto para equivaler al paquete. |
| TXT sin encabezados Markdown | La extensión está admitida, pero esta copia se rechaza | El parser forma un registro que excede 80.000 caracteres. TXT con encabezados `#`/`##` usaría el mismo mecanismo que Markdown. No es un límite intrínseco de TXT. |
| Word genérico | 196 registros internos; 16 identidades conservadas por la regla de oportunidades | No reconstruye las 50 fuentes ni `conditions[]`; detecta algunas zonas. No confundir este caso genérico con el conversor específico de la guía original. |
| PDF de texto | No admitido por la carga actual | Extraíble en el laboratorio, pero requiere un adaptador seguro y trazabilidad antes de ser un formato de carga. |
| CSV | No admitido por la carga actual | Las columnas pueden transportar todos los campos; hace falta validar y transformar al esquema canónico. |
| HTML | No admitido por la carga actual | Puede conservar jerarquía y texto; también requiere normalizador y límites propios. |

La asignación interna de documentos genéricos es una protección, no un error que deba eliminarse. **Conservar audiencia pública tampoco aprueba ni publica automáticamente ningún registro.**

El JSON con sangría pesa 306.982 bytes; compactado, 255.022; el JSONL generado, 267.525. Por tanto, JSONL no resulta intrínsecamente más pequeño. DOCX pesa unos 72 KB por compresión, sin que eso lo vuelva mejor entrada para este backend. A este tamaño, la preservación de estructura importa mucho más que ahorrar decenas de KB. Los tiempos detallados de importación y extracción quedan separados en el resumen: no mezclamos el costo de leer bytes con el del normalizador completo.

## Contrato de conocimiento recomendado

La fuente de autoría puede seguir siendo Word o un Markdown jerárquico. La **entrega al backend actual** debería ser el paquete JSON `gianna.corpus.v1` validado, con `document`, `sources` y `records`. JSONL es una alternativa de intercambio, no una mejora automática de recuperación ni de memoria del importador actual.

Cada registro debería ser una unidad informativa autosuficiente: un dato, un perfil territorial, una ficha de actividad o una respuesta documental, con las condiciones necesarias para entenderlo. No cortaría una cifra de su unidad/período ni una afirmación de su límite. Tampoco convertiría las preguntas de evaluación en preguntas hipotéticas dentro del índice: eso contaminaría la prueba.

| Necesidad | Campos existentes que preservaría |
| --- | --- |
| Identidad y trazabilidad | `id`, `source_locator`, `original_block_ids`, `original_sha256` |
| Contexto de búsqueda | `section`, `title`, `topic`, `zones`; resolver nombres legibles desde los IDs territoriales |
| Información y alcance | `text` literal, `conditions`, `period`, `cutoff_date` cuando consten, sin inventarlos |
| Tratamiento editorial | `audience`, `evidence_type`, `enabled`, con revisión y aprobación independientes |
| Citas verificables | `source_refs` enlazados al registro `sources`, no solo números sin bibliografía |

No hace falta añadir campos que el esquema vigente rechazaría. Al buscar, se prepara una representación textual; al responder, se vuelve al registro y a sus condiciones originales. La extensión del archivo no sustituye ese contrato. Los documentos originales se conservan como referencias, no se sobrescriben.

En las 196 fichas actuales, la entrada contextual mayor tiene **289 tokens del encoder**. Por eso 300/0, 420/0 y 420/40 producen aquí las mismas unidades: no hay un cambio real de límites. Para futuras fuentes largas, el tamaño debe verificarse con el tokenizador y con casos nuevos; este empate no demuestra que el solapamiento nunca sirva.

Las agrupaciones multi-registro del laboratorio conservan offsets para puntuar pasajes, pero no son una implementación nueva del contrato de citas de producción. Antes de adoptarlas habría que preservar separadamente procedencia, audiencia, evidencia y fecha de cada afirmación. Buscar hijos y devolver la ficha padre conserva esa unidad editorial con menos cambios conceptuales, aunque aquí exige más vectores y no domina todas las métricas.

Cambiar la representación real exige construir y evaluar una **versión nueva**. No se debe sobrescribir la colección publicada ni mezclar espacios vectoriales, aunque las dimensiones coincidan. Este estudio no publica ni migra ninguna versión.

## Investigación contrastada

### La referencia de Giana Turismo

El [conversor de Turismo](https://github.com/NebyX1/giana-turismo/blob/main/scripts/ingest.py) parte de Markdown, conserva la ruta de encabezados, identificadores estables, referencias y líneas de origen, y genera vistas separadas de bloques, fragmentos, catálogo, FAQ y fuentes. Es una normalización estructural determinista, no cargar un Markdown indiferenciado. El [indexador vectorial](https://github.com/NebyX1/giana-turismo/blob/main/scripts/index_qdrant.py) utiliza el cuerpo; FTS recibe también título y jerarquía. Esto motiva el control de representaciones distintas para cada canal. Leer ese código no prueba por sí solo su exactitud ni reproduce su entorno GPU. No se ejecutaron sus scripts ni se copiaron SQLite, Qdrant o comandos que sustituyen colecciones.

Invest podría usar Markdown como formato de autoría con un conversor equivalente. **Su importador Markdown actual no hace esa misma transformación**. Por eso una conclusión sobre el archivo cargable hoy no es una condena de Markdown ni una prueba de que JSON tenga embeddings mejores.

### Estudios y documentación

Se consultaron fuentes primarias y código, no solo publicaciones promocionales. La fecha de corte bibliográfico es el 24/10/2026; una versión revisada puede cambiar el sentido de un resultado anterior.

| Enfoque | Evidencia consultada | Consecuencia para este estudio |
| --- | --- | --- |
| Contextual retrieval | [Anthropic, septiembre de 2024](https://www.anthropic.com/research/contextual-retrieval): contextos generados más BM25 reducen fallos de recuperación top-20 del 5,7% al 2,9% en sus conjuntos. Es una reducción relativa de fallos, no 49 puntos de exactitud. | Probar contexto es razonable. Sus cifras no se trasladan a títulos deterministas ni a este corpus. |
| Evaluación por evidencia | [Chroma](https://research.trychroma.com/evaluating-chunking) y [código reproducible](https://github.com/brandonstarxel/chunking_evaluation): medir tokens relevantes recuperados permite distinguir recuperación de documento y de pasaje. | Por eso no basta con contar IDs; añadimos pasajes literales y presupuesto igual. |
| Estructura y tokens | [Docling](https://docling-project.github.io/docling/concepts/chunking/) y [HybridChunker](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hybrid_chunker.py): partir según estructura, dividir lo sobredimensionado y unir pares compatibles, incluyendo encabezados en el presupuesto. | Inspira controles estructurales. No se ejecutó Docling/OCR y no se llama “Docling” a nuestro agrupador. “Hybrid chunking” no significa BM25 más vectores. |
| Separación semántica | [Qu, Tu y Bao, NAACL 2025](https://aclanthology.org/2025.findings-naacl.114/): no encuentra una ventaja constante que compense el costo de la separación semántica frente a alternativas simples. | Se mide una variante barata con el mismo encoder, en lugar de asumir que es superior. |
| Costos de métodos complejos | [Caspari y colaboradores, agosto de 2026](https://arxiv.org/html/2608.16586v1): ocho métodos, tres modelos y dos corpus muestran que calidad y costo no tienen un ganador universal. | El criterio es la relación calidad/costo local. No extrapolamos resultados de corpus ingleses de hasta un millón de documentos a 196 fichas. |
| Enriquecimiento generativo | [Mangla, versión 4 revisada el 16/10/2026](https://arxiv.org/abs/2603.23533v4): con recuperadores fuertes y reranking, el enriquecimiento puede ser equivalente a un prefijo gratuito. El propio autor retira resultados de versiones iniciales. | No se adopta una promesa antigua de MDKeyChunker ni se paga una llamada por ficha sin demostrar beneficio. Este estudio no ejecutó enriquecimiento generativo. |
| Late chunking | [Artículo](https://arxiv.org/abs/2409.04701) y [código Jina](https://github.com/jina-ai/late-chunking): contextualizar tokens de un documento antes de agrupar sus representaciones. | No es cambiar una extensión. Requiere salidas por token y otro pooling; nuestro perfil CLS no reproduce ese método. Investigado, no medido aquí. |
| Padre e hijos | [H-RAG, mayo de 2026](https://arxiv.org/html/2605.00631v1): recuperar hijos y agregar padres forma parte de un sistema evaluado; su resultado total no aísla esa técnica. | Se ensaya localmente buscar hijos y devolver la ficha original, sin atribuirnos el resultado del artículo. |
| Árboles y resúmenes | [RAPTOR](https://arxiv.org/abs/2401.18059) y [PageIndex](https://github.com/VectifyAI/PageIndex). Ambos ofrecen mecanismos distintos de acceso a documentos extensos; sus resultados son de sistemas y conjuntos particulares. | Investigados, no ejecutados. Resumir y recorrer con LLM agrega generación y validación. No hay aquí evidencia local para reemplazar un índice pequeño por esos sistemas. |
| Índice híbrido | [Documentación de LanceDB](https://docs.lancedb.com/search/hybrid-search) y [Markdown estructurado en Azure Search](https://learn.microsoft.com/en-us/azure/search/search-how-to-index-azure-blob-markdown). | Contrastar canales léxico y semántico; conservar encabezados y metadatos. Una base pequeña permite coseno exacto sin introducir aproximación ANN. |

También se siguieron discusiones especializadas: [r/Rag, enero de 2026](https://www.reddit.com/r/Rag/comments/1qocxu9/ran_30_rag_chunking_experiments_found_that_chunk/) advierte del sesgo de tamaños diferentes; su [implementación](https://github.com/somasays/rag-experiments/tree/main/chunking) requiere revisar unidades y envoltorios antes de aceptar sus porcentajes. [Otra discusión de replicación](https://www.reddit.com/r/LLMDevs/comments/1oto2qp/) conduce al artículo de Qu y colaboradores. Se usan como pistas y controles metodológicos, no como prueba de éxito en Gianna.

## Límites y materiales reproducibles

La suite final fue `python -m pytest --mariadb-docker -q`: **362 aprobadas, tres omitidas y una advertencia, 161,44 s**. Las omisiones corresponden al paquete privado histórico ausente de la ruta esperada; la evaluación real usó `better-rag` directamente. Persiste una advertencia de PydanticGraph sobre el bucle de eventos. Hay 14 pruebas mecánicas nuevas del evaluador; no se presentan como benchmarks de modelos.

Se revisó el propio evaluador y se corrigieron unión de evidencia entre hijos/condiciones, desplazamientos de espacios de PDF, repetición accidental de condiciones, identidad frente a mera coincidencia de IDs, costos auxiliares y filtrado de fuentes. Las preguntas y sus citas no se retocaron para mejorar resultados. Las selecciones completas se recalcularon; los ensayos parciales de depuración no se cuentan como éxitos independientes.

Un primer intento del control cuerpo-denso/BM25-contextual terminó con `rerank_timeout` antes del primer checkpoint de diez preguntas. Se repitió completo conservando el guard de 30 segundos. El incidente está registrado en el resumen; **no se convirtió en ausencia de conocimiento** ni se atribuyó una causa no verificada al servidor de producción. Se conservaron snapshots de reanudación para no perder resultados ante interrupciones.

Los ocho archivos son copias experimentales de transporte del contenido real, no una colección independiente de originales heterogéneos. El PDF es de una columna con texto seleccionable; **no** se evaluaron escaneos, OCR, lectura multicolumna, diagramas, tablas complejas ni notas de Word fuera del cuerpo. El PDF tiene 75 páginas y se renderizó con Poppler para revisar estructura general. DOCX se generó con estilos y se extrajo, pero el renderizador suministrado falló por ausencia de LibreOffice; no se certifica su paginación ni se entrega como documento editorial final.

La cobertura de evidencia no prueba vigencia factual, precisión de una respuesta generada ni abstención correcta ante temas ausentes. Se excluye el generador deliberadamente para no atribuirle al formato un cambio de redacción. Tampoco se mide toda la arquitectura conversacional del producto; las métricas no son comparables directamente con el 36/36 de la prueba anterior con harness completo.

Scripts: `scripts/build_format_fixtures.py`, `scripts/evaluate_knowledge_formats.py`. Preguntas nuevas: `tests/data/format_study_cases.json`. Resultados detallados y copias experimentales locales: `reports/format-study-20261024/`. El resumen compacto versionable queda en `reports/rag-migration/knowledge-format-study-20261024.json`.

```powershell
# Desde backend. Generación de artefactos con el runtime suministrado, sin añadir dependencias al servidor.
& "C:/Users/Nebyx/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" scripts/build_format_fixtures.py --corpus ../better-rag/Invest_Lavalleja_2026.gianna.json --output reports/format-study-20261024/formats
.\.venv\Scripts\python.exe -m scripts.evaluate_knowledge_formats
.\.venv\Scripts\python.exe -m pytest tests/test_format_study.py -q
```

No subir ni importar las copias experimentales como una base revisada. JSON/JSONL siguen sujetos a la revisión y publicación explícitas existentes.
